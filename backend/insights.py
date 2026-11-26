"""Team rating histories, power rankings and calibration, computed from saved forecasts.

Everything here reads forecasts that were already made (the archive backtest and the
live ledger); nothing is re-estimated. A team's rating after a game is its pregame
rating plus the Elo update: K * (result - forecast win chance).
"""
from collections import defaultdict


def team_histories(games, k):
    """{team: [point, ...]} in date order. Unplayed games are left out."""
    history = defaultdict(list)
    for g in sorted(games, key=lambda g: (g["date"], g["game_id"])):
        if g.get("home_score") is None:
            continue
        home_won = g["home_score"] > g["away_score"]
        for team, opponent, rating, chance, won, home, scored, allowed in (
                (g["home_team"], g["away_team"], g["home_rating"], g["home_win_probability"], home_won, True,
                 g["home_score"], g["away_score"]),
                (g["away_team"], g["home_team"], g["away_rating"], 1 - g["home_win_probability"], not home_won, False,
                 g["away_score"], g["home_score"])):
            history[team].append(dict(date=g["date"], game_id=g["game_id"], opponent=opponent, home=home,
                                      result="W" if won else "L", score=f"{scored}-{allowed}",
                                      win_chance=round(chance, 4), rating_before=round(rating, 1),
                                      rating=round(rating + k * (int(won) - chance), 1)))
    return dict(history)


def power_rankings(histories, starting=None):
    """Teams ordered by their latest rating, with record and recent form."""
    teams = set(histories) | set(starting or {})
    rows = []
    for team in teams:
        points = histories.get(team, [])
        wins = sum(p["result"] == "W" for p in points)
        last10 = points[-10:]
        rating = points[-1]["rating"] if points else round(starting[team], 1)
        rows.append(dict(team=team, rating=rating, wins=wins, losses=len(points) - wins,
                         last10=f"{sum(p['result'] == 'W' for p in last10)}-{sum(p['result'] == 'L' for p in last10)}",
                         trend=[p["rating"] for p in points[-20:]]))
    rows.sort(key=lambda r: (-r["rating"], r["team"]))
    for rank, row in enumerate(rows, 1):
        row["rank"] = rank
    return rows


BINS = ((0.5, 0.6), (0.6, 0.7), (0.7, 0.8), (0.8, 0.9), (0.9, 1.0001))


def calibration(games):
    """How often the favorite won, grouped by the favorite's forecast win chance.

    A well-calibrated model's 70% favorites win about 70% of the time.
    """
    buckets = []
    for low, high in BINS:
        chosen = [g for g in games if g.get("home_score") is not None
                  and low <= max(g["home_win_probability"], 1 - g["home_win_probability"]) < high]
        if not chosen:
            buckets.append(dict(low=low, high=min(high, 1.0), games=0, forecast=None, actual=None))
            continue
        favorite_chance = [max(g["home_win_probability"], 1 - g["home_win_probability"]) for g in chosen]
        favorite_won = [(g["home_win_probability"] >= 0.5) == (g["home_score"] > g["away_score"]) for g in chosen]
        buckets.append(dict(low=low, high=min(high, 1.0), games=len(chosen),
                            forecast=round(sum(favorite_chance) / len(chosen), 4),
                            actual=round(sum(favorite_won) / len(chosen), 4)))
    return buckets
