"""Does margin of victory or rest (back-to-backs) improve the Elo model?

Rules, fixed before any results were seen:

1. Choices are made on the development season (2024-25) only, after the 2023-24 warm-up.
   The main measure is Brier score (probability error; lower is better). Accuracy is
   reported but not used to choose, because it is noisier.
2. Back-to-back penalty: try 0, 10, 20, 30, 40 and 50 Elo points; take the one with the
   lowest development Brier score.
3. Keep each change only if it lowers the development Brier score by at least 0.0005
   compared with the model without it; smaller gaps are within game-to-game noise.
   The two changes are judged one at a time, then together (together must beat the
   better single change by the same margin).
4. The chosen model and the current model are scored once on the held-out season
   (2025-26). A paired bootstrap (2,000 resamples of games, fixed seed) gives a 95%
   interval for the difference in Brier score.
5. The chosen model replaces the current one only if it also has a lower held-out
   Brier score. Either way, the result is reported.

K (20), home advantage (65) and offseason retention (75%) stay fixed.
"""

import argparse
from datetime import date
import json
from pathlib import Path
import random
import sqlite3

from evaluate_elo import PARAMETERS, SEASONS, audit, backtest, metrics, played_yesterday
from import_games import DEFAULT_DB

PENALTIES = (0, 10, 20, 30, 40, 50)
MIN_GAIN = 0.0005
RESAMPLES = 2000
SEED = 2026


def load(database):
    with sqlite3.connect(f"{Path(database).resolve().as_uri()}?mode=ro", uri=True) as connection:
        connection.row_factory = sqlite3.Row
        games = [dict(r) for r in connection.execute(
            "SELECT * FROM games WHERE season_type='Regular Season' AND season IN (?, ?, ?) "
            "ORDER BY game_date, game_id", SEASONS)]
    audit(games)
    return games


def score(games, season, parameters):
    """Metrics for one season; earlier seasons only warm the ratings up."""
    rows = [r for r in backtest([g for g in games if g["season"] <= season], parameters) if r["season"] == season]
    probabilities = [r["home_win_probability"] for r in rows]
    outcomes = [r["actual_home_win"] for r in rows]
    return dict(metrics(probabilities, outcomes), games=len(rows)), probabilities, outcomes


def variant(margin_of_victory=False, back_to_back=0):
    return dict(PARAMETERS, margin_of_victory=margin_of_victory, back_to_back=float(back_to_back))


def bootstrap_difference(current, chosen, outcomes, resamples=RESAMPLES, seed=SEED):
    """95% interval for Brier(chosen) - Brier(current) over resampled games."""
    errors = [(c - y) ** 2 - (b - y) ** 2 for b, c, y in zip(current, chosen, outcomes)]
    rng = random.Random(seed)
    n = len(errors)
    means = sorted(sum(errors[rng.randrange(n)] for _ in range(n)) / n for _ in range(resamples))
    return sum(errors) / n, means[int(0.025 * resamples)], means[int(0.975 * resamples) - 1]


def rest_facts(games, season):
    """How often back-to-backs happen and how those teams did, in one season."""
    last, b2b_games, b2b_wins, mismatched, mismatched_rested_wins = {}, 0, 0, 0, 0
    for day in sorted({g["game_date"] for g in games if g["season"] == season}):
        todays = [g for g in games if g["game_date"] == day]
        for g in todays:
            home_tired = played_yesterday(g["home_team_id"], day, last)
            away_tired = played_yesterday(g["away_team_id"], day, last)
            home_won = g["home_score"] > g["away_score"]
            b2b_games += home_tired + away_tired
            b2b_wins += (home_tired and home_won) + (away_tired and not home_won)
            if home_tired != away_tired:
                mismatched += 1
                mismatched_rested_wins += (away_tired and home_won) or (home_tired and not home_won)
        for g in todays:
            last[g["home_team_id"]] = last[g["away_team_id"]] = day
    return dict(back_to_back_appearances=b2b_games, back_to_back_win_rate=b2b_wins / max(b2b_games, 1),
                one_team_tired_games=mismatched, rested_team_win_rate=mismatched_rested_wins / max(mismatched, 1))


def main():
    parser = argparse.ArgumentParser(description="Margin-of-victory and rest experiment for the Elo model.")
    parser.add_argument("--database", type=Path, default=DEFAULT_DB)
    parser.add_argument("--output", type=Path, default=Path(__file__).parent / "MODEL_EXPERIMENT_RESULTS.md")
    args = parser.parse_args()
    games = load(args.database)
    dev, test = SEASONS[1], SEASONS[2]
    lines = ["# Model experiment: margin of victory and rest", "",
             f"Chosen on {dev} (development), then scored once on {test} (held out).",
             "Rules were written before results; see `backend/experiment_model.py`.", ""]

    facts = rest_facts(games, dev)
    lines += [f"## Rest in {dev}", "",
              f"- Teams on the second night of a back-to-back: {facts['back_to_back_appearances']} appearances, "
              f"won {facts['back_to_back_win_rate']:.1%}.",
              f"- Games where only one team was on a back-to-back: {facts['one_team_tired_games']}; "
              f"the rested team won {facts['rested_team_win_rate']:.1%}.", ""]

    # Step 1-2: development comparisons.
    baseline, _, _ = score(games, dev, variant())
    mov, _, _ = score(games, dev, variant(margin_of_victory=True))
    penalties = {b: score(games, dev, variant(back_to_back=b))[0] for b in PENALTIES}
    best_penalty = min(PENALTIES, key=lambda b: penalties[b]["brier"])
    lines += [f"## Development ({dev})", "", "| Model | Correct picks | Brier | Log loss |", "|---|---:|---:|---:|"]
    row = lambda name, m: f"| {name} | {m['accuracy']:.1%} | {m['brier']:.4f} | {m['log_loss']:.4f} |"
    lines.append(row("Current model", baseline))
    lines.append(row("+ margin of victory", mov))
    for b in PENALTIES[1:]:
        lines.append(row(f"+ back-to-back penalty {b}", penalties[b]))

    # Step 3: keep each change only if it helps on development.
    keep_mov = mov["brier"] <= baseline["brier"] - MIN_GAIN
    keep_rest = best_penalty > 0 and penalties[best_penalty]["brier"] <= baseline["brier"] - MIN_GAIN
    chosen_parameters = variant(margin_of_victory=keep_mov, back_to_back=best_penalty if keep_rest else 0)
    if keep_mov and keep_rest:
        both, _, _ = score(games, dev, chosen_parameters)
        lines.append(row(f"+ both (penalty {best_penalty})", both))
        alone = min((mov, variant(margin_of_victory=True)),
                    (penalties[best_penalty], variant(back_to_back=best_penalty)), key=lambda x: x[0]["brier"])
        if both["brier"] > alone[0]["brier"] - MIN_GAIN:
            chosen_parameters = alone[1]
    lines += ["", f"Margin of victory: {'kept' if keep_mov else 'dropped'} "
              f"(Brier {mov['brier']:.4f} vs {baseline['brier']:.4f}).",
              f"Back-to-back: best penalty {best_penalty}; {'kept' if keep_rest else 'dropped'} "
              f"(Brier {penalties[best_penalty]['brier']:.4f} vs {baseline['brier']:.4f}).", ""]

    chosen_name = (" + ".join(filter(None, [
        "margin of victory" if chosen_parameters["margin_of_victory"] else "",
        f"back-to-back {chosen_parameters['back_to_back']:g}" if chosen_parameters["back_to_back"] else ""]))
        or "current model")
    result = dict(development=dict(current=baseline, margin_of_victory=mov,
                                   back_to_back={str(b): m for b, m in penalties.items()}),
                  chosen=chosen_name, chosen_parameters=chosen_parameters, rest_facts=facts)

    # Step 4-5: one look at the held-out season.
    if chosen_name == "current model":
        lines += [f"## Held out ({test})", "", "Neither change helped on development, so nothing was tested "
                  "on the held-out season and the current model stays.", ""]
        result["adopt"] = False
    else:
        current_test, current_p, outcomes = score(games, test, variant())
        chosen_test, chosen_p, _ = score(games, test, chosen_parameters)
        difference, low, high = bootstrap_difference(current_p, chosen_p, outcomes)
        adopt = chosen_test["brier"] < current_test["brier"]
        lines += [f"## Held out ({test}), scored once", "", "| Model | Correct picks | Brier | Log loss |",
                  "|---|---:|---:|---:|", row("Current model", current_test), row(f"Chosen: {chosen_name}", chosen_test), "",
                  f"Brier difference (chosen minus current): {difference:+.4f}, 95% interval {low:+.4f} to {high:+.4f}.",
                  ("The interval excludes zero, so the improvement is unlikely to be luck."
                   if high < 0 else "The interval includes zero, so the difference could be luck."
                   if low <= 0 <= high else "The chosen model was worse on held-out games."),
                  "", f"Decision: {'switch to the chosen model' if adopt else 'keep the current model'}.", ""]
        result.update(adopt=adopt, held_out=dict(current=current_test, chosen=chosen_test,
                      brier_difference=difference, interval=[low, high]))

    args.output.write_text("\n".join(lines))
    args.output.with_suffix(".json").write_text(json.dumps(result, indent=2, default=str) + "\n")
    print("\n".join(lines))
    print(f"Saved {args.output.name} and {args.output.with_suffix('.json').name}")


if __name__ == "__main__":
    main()
