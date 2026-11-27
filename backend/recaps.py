"""Postgame recaps: did the model get it right? Written by an LLM, checked before saving.

  python backend/recaps.py update   # after live_forecast.py update: recaps for newly finished games

A recap compares the saved forecast with the final score. Like previews, it may use only
facts this project computed (pre-game win chance, records, the final score), and it is
checked before it is saved: numbers and scores must match, the winner can't be swapped,
and it can't call the model right when it was wrong (or an upset when it wasn't). A recap
that fails twice becomes a plain template. Saved recaps are never rewritten.
"""

import argparse
from datetime import datetime, timedelta, timezone
import json
import os
from pathlib import Path
import re

from live_forecast import EASTERN, LEDGER_FILE, LIVE_DIR, LIVE_SEASON, read_ledger
from previews import (ATTEMPTS, BANNED, MAX_CALLS, GeminiClient, Paced, QuotaError, allowed_numbers,
                      build_facts, facts_hash)

RECAP_FILE = f"recaps_{LIVE_SEASON}.json"
RECENT_DAYS = 3   # only recap games from the last few days; older games keep no recap

PROMPT = """You write one- or two-sentence recaps of finished NBA games for a forecasting website.
Use ONLY the facts in the JSON below. Do not mention players, injuries, betting or anything not in
the facts. Plain English; write streaks in words, never codes like W6.

Say who won and the final score (winner's points first, for example "112-104"). Say whether the
model's pre-game pick was right, using its win chance as a whole-number percent with "%". Call it
an upset only if "upset" is true in the facts. 60 to 300 characters.

Facts:
"""
SCHEMA = {"type": "OBJECT", "properties": {"recap": {"type": "STRING"}}, "required": ["recap"]}

WIN = re.compile(r"\b(beat|beats|won|wins|win|defeated|defeats|topped|tops|edged|edges|held off|rolled past|outlasted)\b", re.I)
LOSE = re.compile(r"\b(lost|loses|fell|falls|dropped|drops|were beaten|was beaten|came up short)\b", re.I)
RIGHT = re.compile(r"\b(called it|got it right|was right|correct(ly)?|as expected|pick held|delivered)\b", re.I)
WRONG = re.compile(r"\b(missed|was wrong|got it wrong|upset|surprise|stunned|shock(ed|ing)?)\b", re.I)


def recap_facts(row, rows):
    """Pre-game facts for a finished game plus its result."""
    facts = build_facts(row, rows)
    home_score, away_score = int(row["home_score"]), int(row["away_score"])
    winner = "home" if home_score > away_score else "away"
    pick = "home" if float(row["home_win_probability"]) >= 0.5 else "away"   # a 50/50 counts as a home pick
    facts.update(final=dict(home=home_score, away=away_score), winner=winner, model_pick=pick,
                 model_correct=pick == winner, upset=facts[winner]["win_chance"] < 50,
                 margin=abs(home_score - away_score))
    for team in ("home", "away"):
        facts[team].pop("played_yesterday", None)
    return facts


def _mentions(text, facts):
    return sorted((m.start(), side) for side in ("home", "away")
                  for word in {facts[side]["name"], facts[side]["city"]} if word
                  for m in re.finditer(rf"\b{re.escape(word)}\b", text, re.I))


def check(recap, facts):
    """Problems with a recap; an empty list means it passed."""
    text = recap.get("recap", "").strip()
    problems = []
    if not 60 <= len(text) <= 320:
        problems.append(f"length: {len(text)} characters, outside 60-320")
    winner, loser = facts["winner"], "away" if facts["winner"] == "home" else "home"
    if facts[winner]["name"].lower() not in text.lower():
        problems.append("does not name the winner")
    stray = sorted({int(n) for n in re.findall(r"\d+", text)} - allowed_numbers(facts))
    if stray:
        problems.append(f"numbers not in the facts: {stray}")
    chances = {facts["home"]["win_chance"], facts["away"]["win_chance"]}
    bad_pct = sorted({int(n) for n in re.findall(r"(\d+)\s*(?:%|percent\b)", text, re.I)} - chances)
    if bad_pct:
        problems.append(f"percentages that are not win chances: {bad_pct}")
    final = {facts["final"]["home"], facts["final"]["away"]}
    for a, b in re.findall(r"\b(\d{2,3})\s*[-–]\s*(\d{2,3})\b", text):
        if int(a) >= 60 and int(b) >= 60 and {int(a), int(b)} != final:
            problems.append(f"score {a}-{b} is not the final score")
    if re.search(r"\b(\d{2,3})\s*[-–]\s*(\d{2,3})\b", text):
        pair = [int(x) for x in re.search(r"\b(\d{2,3})\s*[-–]\s*(\d{2,3})\b", text).groups()]
        if set(pair) == final and pair[0] < pair[1]:
            problems.append("final score written loser-first")
    mentions = _mentions(text, facts)
    for pattern, wrong_side, label in ((WIN, loser, "says the loser won"), (LOSE, winner, "says the winner lost")):
        for verb in pattern.finditer(text):
            before = [side for pos, side in mentions if pos < verb.start()]
            if before and before[-1] == wrong_side and not re.search(r"\bnot\b|\bfailed\b", text[max(0, verb.start() - 12):verb.start()], re.I):
                problems.append(label)
                break
    if RIGHT.search(text) and not facts["model_correct"]:
        problems.append("says the model was right, but it missed")
    wrong = WRONG.search(text)
    if wrong and facts["model_correct"]:
        problems.append(f"says '{wrong.group(0)}', but the model's pick won")
    if re.search(r"\b[WL]\d+\b", text):
        problems.append("jargon: raw streak code like W6 instead of words")
    banned = BANNED.search(text)
    if banned:
        problems.append(f"off-limits topic: '{banned.group(0)}'")
    return problems


def template(facts):
    winner, loser = facts[facts["winner"]], facts["away" if facts["winner"] == "home" else "home"]
    high, low = max(facts["final"].values()), min(facts["final"].values())
    verdict = ("so the pick held" if facts["model_correct"]
               else "so this one was an upset" if facts["upset"] else "so the toss-up went their way")
    return dict(recap=f"The {winner['name']} beat the {loser['name']} {high}-{low}. "
                      f"The model had given the {winner['name']} a {winner['win_chance']}% chance, {verdict}.")


def ask(client, facts):
    data = client.ask(PROMPT + json.dumps(facts, indent=2), SCHEMA, max_tokens=250)
    return dict(recap=str(data.get("recap", "")))


def write_recap(facts, client, attempts=ATTEMPTS):
    problems = []
    for _ in range(attempts):
        try:
            draft = ask(client, facts)
        except QuotaError:
            raise
        except Exception as error:
            problems = [f"request failed: {type(error).__name__}"]
            continue
        problems = check(draft, facts)
        if not problems:
            return dict(draft, source="ai", model=client.model), []
    return dict(template(facts), source="template"), problems


def update(rows, saved, now, client=None, max_calls=MAX_CALLS):
    """Recap live games that finished in the last few days and have no recap yet."""
    saved, notes, calls = dict(saved), [], 0
    today = now.astimezone(EASTERN).date()
    earliest = (today - timedelta(days=RECENT_DAYS)).isoformat()
    todo = [r for r in rows if r["mode"] == "live" and r["home_score"] != ""
            and earliest <= r["game_date"] < today.isoformat() and r["game_id"] not in saved]
    for row in sorted(todo, key=lambda r: (r["game_date"], r["game_id"])):
        facts = recap_facts(row, rows)
        recap, problems = dict(template(facts), source="template"), []
        if client and calls < max_calls:
            try:
                recap, problems = write_recap(facts, client)
                calls += ATTEMPTS if problems else 1
            except QuotaError as error:
                notes.append(f"{error}; using templates for the rest.")
                client = None
        if problems:
            notes.append(f"{row['game_id']}: AI recap failed checks ({'; '.join(problems)}); used the template.")
        saved[row["game_id"]] = dict(recap, game_id=row["game_id"], facts_sha256=facts_hash(facts),
                                     generated_at_utc=now.astimezone(timezone.utc).isoformat(timespec="seconds"))
    return saved, notes


def evaluate(rows, client, limit=30):
    """Run the model on recent finished games and check every recap."""
    chosen = sorted((r for r in rows if r["home_score"] != ""), key=lambda r: (r["game_date"], r["game_id"]))[-limit:]
    results = []
    for row in chosen:
        facts = recap_facts(row, rows)
        try:
            draft = ask(client, facts)
            problems = check(draft, facts)
        except QuotaError:
            break
        except Exception as error:
            draft, problems = {}, [f"request failed: {type(error).__name__}"]
        results.append(dict(game_id=row["game_id"], date=row["game_date"], passed=not problems,
                            problems=problems, text=draft.get("recap", ""), draft=draft, facts=facts))
    return results


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    commands = parser.add_subparsers(dest="command", required=True)
    daily = commands.add_parser("update", help="Write recaps for recently finished games")
    daily.add_argument("--now", help="Override the current time (ISO 8601 with timezone)")
    daily.add_argument("--live-dir", type=Path, default=LIVE_DIR)
    args = parser.parse_args(argv)
    rows = list(read_ledger(args.live_dir / LEDGER_FILE).values())
    key = os.environ.get("GEMINI_API_KEY", "").strip()
    client = Paced(GeminiClient(key)) if key else None
    now = datetime.fromisoformat(args.now) if args.now else datetime.now(timezone.utc)
    path = args.live_dir / RECAP_FILE
    saved = json.loads(path.read_text()) if path.exists() else {}
    if not client:
        print("No GEMINI_API_KEY set; using template recaps.")
    updated, notes = update(rows, saved, now, client)
    path.write_text(json.dumps(updated, indent=2, sort_keys=True) + "\n")
    new = [updated[g] for g in updated if g not in saved]
    print(f"Saved {len(new)} recap(s): {sum(r['source'] == 'ai' for r in new)} AI, "
          f"{sum(r['source'] == 'template' for r in new)} template.")
    for note in notes:
        print(note)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
