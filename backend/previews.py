"""Plain-English game previews, written by an LLM from the model's own numbers.

  python backend/previews.py update   # after live_forecast.py update: previews for today's games
  python backend/previews.py eval     # score the LLM on recent games and write PREVIEW_EVAL.md

Each preview is built only from facts this project computed (win chance, record, last 10,
streak, back-to-back). Every AI preview is checked before it is saved: numbers must match
the facts, both teams must be named, the favorite must not be flipped, and injury or betting
talk is rejected. A preview that fails twice is replaced by a plain template, so the site
never shows unchecked AI text. Like forecasts, a saved preview is never rewritten.

Uses Google's Gemini API free tier (set GEMINI_API_KEY; no billing account needed). With no
key, or if the API is unavailable, every game gets a template preview instead.
"""

import argparse
from collections import defaultdict
from datetime import date, datetime, timedelta, timezone
import hashlib
import json
import os
from pathlib import Path
import re
import sys
import time

from live_forecast import EASTERN, LEDGER_FILE, LIVE_DIR, LIVE_SEASON, read_ledger

PREVIEW_FILE = f"previews_{LIVE_SEASON}.json"
EVAL_FILE = Path(__file__).parent / "PREVIEW_EVAL.md"
DEFAULT_MODEL = "gemini-flash-lite-latest"
MAX_CALLS = 20          # hard cap per run, far below the free tier's daily limit
PACE_SECONDS = 6.0      # gap between requests, to stay under free-tier per-minute limits
MAX_WAIT = 90           # longest the API may ask us to wait before we give up for the run
ATTEMPTS = 2

TEAMS = {
    "ATL": ("Atlanta", "Hawks"), "BOS": ("Boston", "Celtics"), "BKN": ("Brooklyn", "Nets"),
    "CHA": ("Charlotte", "Hornets"), "CHI": ("Chicago", "Bulls"), "CLE": ("Cleveland", "Cavaliers"),
    "DAL": ("Dallas", "Mavericks"), "DEN": ("Denver", "Nuggets"), "DET": ("Detroit", "Pistons"),
    "GSW": ("Golden State", "Warriors"), "HOU": ("Houston", "Rockets"), "IND": ("Indiana", "Pacers"),
    "LAC": ("LA", "Clippers"), "LAL": ("Los Angeles", "Lakers"), "MEM": ("Memphis", "Grizzlies"),
    "MIA": ("Miami", "Heat"), "MIL": ("Milwaukee", "Bucks"), "MIN": ("Minnesota", "Timberwolves"),
    "NOP": ("New Orleans", "Pelicans"), "NYK": ("New York", "Knicks"), "OKC": ("Oklahoma City", "Thunder"),
    "ORL": ("Orlando", "Magic"), "PHI": ("Philadelphia", "76ers"), "PHX": ("Phoenix", "Suns"),
    "POR": ("Portland", "Trail Blazers"), "SAC": ("Sacramento", "Kings"), "SAS": ("San Antonio", "Spurs"),
    "TOR": ("Toronto", "Raptors"), "UTA": ("Utah", "Jazz"), "WAS": ("Washington", "Wizards"),
}

INSTRUCTIONS = """You write short previews of NBA games for a forecasting website read by casual fans.
Use ONLY the facts in the JSON below. Do not mention players, injuries, betting, odds, point
spreads, or anything not in the facts. Do not predict a score. Plain English, no jargon.

Write:
- headline: at most 70 characters.
- preview: 2 or 3 sentences, 150 to 400 characters. Name both teams by nickname. Say which team
  the model favors and its win chance as a whole-number percent written with "%" (for example
  "64%"). If neither team is favored, call it a toss-up.
  Include at least one record, last-10 or streak number from the facts. Skip filler such as
  "in this matchup". Match the wording to the chance: "heavy favorite" only at 70% or more,
  "slight edge" or "close" only at 60% or less. Only call a team hot, on a streak, or coming
  off a win or loss if its streak in the facts says so (W = wins, L = losses).

Example: "The model gives the Celtics a 64% chance in New York. Boston has won 3 straight and is
7-3 in its last 10, while the Knicks have dropped 4 of their last 5 at 2-8."

Facts:
"""

SCHEMA = {
    "type": "OBJECT",
    "properties": {"headline": {"type": "STRING"}, "preview": {"type": "STRING"}},
    "required": ["headline", "preview"],
}

BANNED = re.compile(r"\b(injur\w*|bets?|betting|odds|spread|parlay|over/under|lock|guarantee\w*|sure thing)\b", re.I)


# ---------- facts ----------

def _record(results):
    wins = sum(results)
    return f"{wins}-{len(results) - wins}"


def _streak(results):
    if not results:
        return None
    last, count = results[-1], 0
    for result in reversed(results):
        if result != last:
            break
        count += 1
    return f"{'W' if last else 'L'}{count}"


def team_facts(rows, before):
    """Per-team results ({abbr: [1, 0, ...]}) and last game dates, from games before a date."""
    results, last_game = defaultdict(list), {}
    for row in sorted(rows, key=lambda r: (r["game_date"], r["game_id"])):
        if row["game_date"] >= before:
            continue
        for team in (row["home_team"], row["away_team"]):
            last_game[team] = row["game_date"]
        if row["home_score"] == "":
            continue
        home_won = int(row["home_score"]) > int(row["away_score"])
        results[row["home_team"]].append(int(home_won))
        results[row["away_team"]].append(int(not home_won))
    return results, last_game


def build_facts(row, rows):
    """Everything a preview may say about one game, using only games from earlier dates."""
    day = row["game_date"]
    results, last_game = team_facts(rows, day)
    yesterday = (date.fromisoformat(day) - timedelta(days=1)).isoformat()
    home_chance = round(float(row["home_win_probability"]) * 100)
    tipoff = datetime.fromisoformat(row["tipoff_utc"]).astimezone(EASTERN)

    def side(abbr, chance):
        city, name = TEAMS.get(abbr, ("", abbr))
        games = results.get(abbr, [])
        return dict(abbr=abbr, city=city, name=name, win_chance=chance,
                    record=_record(games), last10=_record(games[-10:]) if games else "0-0",
                    streak=_streak(games), played_yesterday=last_game.get(abbr) == yesterday)

    favorite = "home" if home_chance > 50 else "away" if home_chance < 50 else None
    return dict(game_id=row["game_id"], date=day, tipoff_et=tipoff.strftime("%-I:%M %p ET"),
                neutral_site=bool(int(row["neutral_site"])), favorite=favorite,
                home=side(row["home_team"], home_chance), away=side(row["away_team"], 100 - home_chance))


# ---------- checks ----------

def allowed_numbers(facts):
    """Every integer the facts contain; a preview may use no others."""
    text = json.dumps({k: v for k, v in facts.items() if k != "game_id"})
    return {int(n) for n in re.findall(r"\d+", text)} | {10}   # "last 10"


def check(preview, facts):
    """Problems with a preview, as short strings. An empty list means it passed."""
    problems = []
    headline, text = preview.get("headline", "").strip(), preview.get("preview", "").strip()
    whole = f"{headline}. {text}"
    if not 100 <= len(text) <= 450:
        problems.append(f"length: {len(text)} characters, outside 100-450")
    if not headline or len(headline) > 80:
        problems.append("headline missing or too long")
    for team in (facts["home"], facts["away"]):
        if team["name"].lower() not in whole.lower():
            problems.append(f"does not name the {team['name']}")
    allowed = allowed_numbers(facts)
    stray = sorted({int(n) for n in re.findall(r"\d+", whole)} - allowed)
    if stray:
        problems.append(f"numbers not in the facts: {stray}")
    chances = {facts["home"]["win_chance"], facts["away"]["win_chance"]}
    bad_pct = sorted({int(n) for n in re.findall(r"(\d+)\s*(?:%|percent\b)", whole, re.I)} - chances)
    if bad_pct:
        problems.append(f"percentages that are not win chances: {bad_pct}")
    if facts["favorite"]:
        favorite = facts[facts["favorite"]]
        underdog = facts["away" if facts["favorite"] == "home" else "home"]
        if favorite["name"].lower() not in whole.lower():
            problems.append("does not name the favorite")
        for sentence in re.split(r"(?<=[.!?])\s+", whole):
            s = sentence.lower()
            if underdog["name"].lower() in s and favorite["name"].lower() not in s \
                    and re.search(r"\bfavou?r(ed|ites?)\b", s) and not re.search(r"\b(not|underdogs?)\b", s):
                problems.append("calls the underdog the favorite")
        if re.search(rf"{underdog['win_chance']}\s*%", whole) and f"{favorite['win_chance']}%" not in whole.replace(" %", "%") \
                and underdog["win_chance"] != favorite["win_chance"]:
            problems.append("gives only the underdog's chance")
    problems += claim_problems(whole, facts)
    match = BANNED.search(whole)
    if match:
        problems.append(f"off-limits topic: '{match.group(0)}'")
    return problems


STRONG = re.compile(r"\b(strong(ly)?|heav(y|ily)|big|clear|solid|comfortabl[ey])\b[^.]*\bfavou?r", re.I)
WEAK = re.compile(r"\b(slight(ly)?|narrow(ly)?|tight|close (game|one|contest|matchup)|toss-?up|coin flip|evenly matched)\b", re.I)
HOT = re.compile(r"\b(win(ning)? streak|won (\w+ )?straight|hot|coming off (a )?wins?|recent wins?|winning ways)\b", re.I)
COLD = re.compile(r"\b(losing streak|lost (\w+ )?straight|skid|slump|cold|coming off (a )?loss(es)?|recent loss(es)?)\b", re.I)


def claim_problems(text, facts):
    """Wording that the numbers don't support: confidence words and streak claims."""
    problems = []
    top = max(facts["home"]["win_chance"], facts["away"]["win_chance"])
    if STRONG.search(text) and top < 70:
        problems.append(f"confidence: says strong favorite at {top}%")
    if WEAK.search(text) and top > 60:
        problems.append(f"confidence: says close game at {top}%")
    # A streak claim belongs to the team named most recently before it ("Denver brings a win
    # streak into Chicago" is about Denver), or to both teams after "both teams". Names match
    # as whole words, so the city "LA" never matches inside "last".
    mentions = sorted((m.start(), team) for team in (facts["home"], facts["away"])
                      for word in {team["name"], team["city"]} if word
                      for m in re.finditer(rf"\b{re.escape(word)}\b", text, re.I))
    for pattern, letter, label in ((HOT, "W", "winning"), (COLD, "L", "losing")):
        for claim in pattern.finditer(text):
            sentence_start = max(text.rfind(".", 0, claim.start()), text.rfind("!", 0, claim.start()))
            sentence = text[sentence_start + 1:claim.start()]
            if re.search(r"\bboth teams\b", sentence, re.I):
                subjects = [facts["home"], facts["away"]]
            else:
                before = [team for pos, team in mentions if pos < claim.start()]
                after = [team for pos, team in mentions if pos > claim.end()]
                subjects = before[-1:] or after[:1]
            for team in subjects:
                if not (team["streak"] or "").startswith(letter):
                    problems.append(f"streak: calls the {team['name']} {label} but their streak is {team['streak']}")
    return problems


# ---------- writing ----------

def template(facts):
    """Plain preview used when the AI is unavailable or fails its checks."""
    home, away = facts["home"], facts["away"]
    joiner = "vs." if facts["neutral_site"] else "at"
    if facts["favorite"]:
        fav = facts[facts["favorite"]]
        lead = f"The model gives the {fav['name']} a {fav['win_chance']}% chance to win."
    else:
        lead = "The model sees this one as a toss-up."
    form = (f"The {away['name']} are {away['record']} this season ({away['last10']} in their last 10), "
            f"and the {home['name']} are {home['record']} ({home['last10']}).")
    tired = [t["name"] for t in (away, home) if t["played_yesterday"]]
    rest = f" The {' and '.join(tired)} also played last night." if tired else ""
    return dict(headline=f"{away['name']} {joiner} {home['name']}, {facts['tipoff_et']}",
                preview=f"{lead} {form}{rest}")


class GeminiClient:
    """Gemini API (free tier works) with JSON output matching SCHEMA."""

    def __init__(self, key, model=None, timeout=30):
        self.key, self.model, self.timeout = key, model or os.environ.get("GEMINI_MODEL", DEFAULT_MODEL), timeout

    def write(self, facts):
        import httpx
        response = httpx.post(
            f"https://generativelanguage.googleapis.com/v1beta/models/{self.model}:generateContent",
            headers={"x-goog-api-key": self.key},
            json=dict(contents=[dict(parts=[dict(text=INSTRUCTIONS + json.dumps(facts, indent=2))])],
                      generationConfig=dict(responseMimeType="application/json", responseSchema=SCHEMA,
                                            temperature=0.7, maxOutputTokens=400)),
            timeout=self.timeout)
        if response.status_code == 429:
            raise QuotaError("Gemini free-tier limit reached", retry_after(response))
        response.raise_for_status()
        text = response.json()["candidates"][0]["content"]["parts"][0]["text"]
        data = json.loads(text)
        return dict(headline=str(data.get("headline", "")), preview=str(data.get("preview", "")))


class QuotaError(RuntimeError):
    def __init__(self, message, wait=None):
        super().__init__(message)
        self.wait = wait   # seconds the API asked us to wait; None means a daily limit or unknown


def retry_after(response):
    """Seconds from Gemini's RetryInfo ("retryDelay": "37s"), if it sent one."""
    try:
        for detail in response.json()["error"].get("details", []):
            if "retryDelay" in detail:
                return float(str(detail["retryDelay"]).rstrip("s"))
    except (ValueError, KeyError, TypeError, AttributeError):
        pass
    return None


class Paced:
    """Wraps a client: waits between requests, and once when the API asks us to slow down."""

    def __init__(self, client, pace=PACE_SECONDS, sleep=time.sleep):
        self.client, self.pace, self.sleep, self.last = client, pace, sleep, None
        self.model = client.model

    def write(self, facts):
        for attempt in range(2):
            if attempt == 0 and self.last is not None and self.pace:
                self.sleep(self.pace)
            self.last = True
            try:
                return self.client.write(facts)
            except QuotaError as error:
                if attempt or error.wait is None or error.wait > MAX_WAIT:
                    raise
                self.sleep(error.wait + 1)


def write_preview(facts, client, attempts=ATTEMPTS):
    """(preview dict, problems from the last failed try). Falls back to the template."""
    problems = []
    for _ in range(attempts):
        try:
            draft = client.write(facts)
        except QuotaError:
            raise
        except Exception as error:   # network, bad JSON, unexpected response: try again, then template
            problems = [f"request failed: {type(error).__name__}"]
            continue
        problems = check(draft, facts)
        if not problems:
            return dict(draft, source="ai", model=client.model), []
    return dict(template(facts), source="template"), problems


def facts_hash(facts):
    return hashlib.sha256(json.dumps(facts, sort_keys=True).encode()).hexdigest()[:16]


def update(rows, saved, now, client=None, max_calls=MAX_CALLS):
    """Add previews for today's live forecasts that don't have one. Returns (saved, notes)."""
    saved, notes = dict(saved), []
    today = now.astimezone(EASTERN).date().isoformat()
    todo = [r for r in rows if r["game_date"] == today and r["mode"] == "live"
            and r["home_score"] == "" and r["game_id"] not in saved]
    calls = 0
    for row in sorted(todo, key=lambda r: (r["tipoff_utc"], r["game_id"])):
        facts = build_facts(row, rows)
        preview, problems = dict(template(facts), source="template"), []
        if client and calls < max_calls:
            try:
                preview, problems = write_preview(facts, client)
                calls += ATTEMPTS if problems else 1
            except QuotaError as error:
                notes.append(f"{error}; using templates for the rest.")
                client = None
        if problems:
            notes.append(f"{row['game_id']}: AI preview failed checks ({'; '.join(problems)}); used the template.")
        saved[row["game_id"]] = dict(preview, game_id=row["game_id"], facts_sha256=facts_hash(facts),
                                     generated_at_utc=now.astimezone(timezone.utc).isoformat(timespec="seconds"))
    return saved, notes


# ---------- evaluation ----------

def evaluate(rows, client, limit=30):
    """Run the model on recent games and report how often its previews pass every check."""
    chosen = sorted((r for r in rows if r["home_score"] != ""), key=lambda r: (r["game_date"], r["game_id"]))[-limit:]
    results = []
    for row in chosen:
        facts = build_facts(row, rows)
        try:
            draft = client.write(facts)
            problems = check(draft, facts)
        except QuotaError as error:
            print(f"{error}; stopping after {len(results)} game(s).", file=sys.stderr)
            break
        except Exception as error:
            draft, problems = {}, [f"request failed: {type(error).__name__}"]
        results.append(dict(game_id=row["game_id"], date=row["game_date"], passed=not problems,
                            problems=problems, preview=draft.get("preview", ""), draft=draft, facts=facts))
    return results


def rescore(results):
    """Re-run the current checks on saved outputs: no API calls."""
    return [dict(r, problems=(p := check(r["draft"], r["facts"]) if r.get("draft") else r["problems"]),
                 passed=not p) for r in results]


def eval_report(results, model):
    passed = sum(r["passed"] for r in results)
    reasons = defaultdict(int)
    for r in results:
        for p in r["problems"]:
            reasons[p.split(":")[0]] += 1
    lines = ["# AI preview evaluation", "",
             f"Model: `{model}`. Games: {len(results)} recent games from the live ledger.",
             f"Generated {datetime.now(timezone.utc).date().isoformat()} by `backend/previews.py eval`.", "",
             f"**Passed every check on the first try: {passed} of {len(results)} ({passed / max(len(results), 1):.0%}).**", "",
             "Checks: only numbers from the facts, percentages match the win chances, both teams named, "
             "favorite named and never flipped, no injury or betting talk, length limits.", ""]
    if reasons:
        lines += ["| Failure | Count |", "|---|---:|"] + [f"| {k} | {v} |" for k, v in sorted(reasons.items(), key=lambda x: -x[1])]
        lines += ["", "## Failed previews", ""]
        for r in results:
            if not r["passed"]:
                lines.append(f"- {r['date']} `{r['game_id']}`: {'; '.join(r['problems'])}. Text: \"{r['preview']}\"")
    passing = [r for r in results if r["passed"]][:3]
    if passing:
        lines += ["", "## Sample previews that passed", ""] + [f"- {r['date']}: \"{r['preview']}\"" for r in passing]
    lines += ["", "In production, a preview that fails is retried once and otherwise replaced by a template."]
    return "\n".join(lines) + "\n"


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    commands = parser.add_subparsers(dest="command", required=True)
    daily = commands.add_parser("update", help="Write previews for today's games")
    daily.add_argument("--now", help="Override the current time (ISO 8601 with timezone)")
    test = commands.add_parser("eval", help="Score the model on recent games")
    test.add_argument("--limit", type=int, default=30)
    test.add_argument("--output", type=Path, default=EVAL_FILE)
    test.add_argument("--rescore", action="store_true",
                      help="Re-check the outputs saved by the last eval with the current checks (no API calls)")
    for command in (daily, test):
        command.add_argument("--live-dir", type=Path, default=LIVE_DIR)
    args = parser.parse_args(argv)
    rows = list(read_ledger(args.live_dir / LEDGER_FILE).values())
    key = os.environ.get("GEMINI_API_KEY", "").strip()
    client = Paced(GeminiClient(key)) if key else None

    if args.command == "eval" and args.rescore:
        saved_runs = args.output.with_suffix(".json")
        if not saved_runs.exists():
            print(f"No saved outputs at {saved_runs}; run eval first.", file=sys.stderr)
            return 1
        run = json.loads(saved_runs.read_text())
        results = rescore(run["results"])
        report = eval_report(results, run["model"]).replace("Passed every check on the first try",
                                                            "Passed every check (re-scored, same outputs)")
        args.output.write_text(report)
        saved_runs.write_text(json.dumps(dict(run, results=results), indent=2) + "\n")
        print(report)
        return 0

    if args.command == "eval":
        if not client:
            print("Set GEMINI_API_KEY to run the evaluation.", file=sys.stderr)
            return 1
        results = evaluate(rows, client, args.limit)
        if not results:
            print("No games were evaluated; the free-tier limit may be used up for today.", file=sys.stderr)
            return 1
        report = eval_report(results, client.model)
        args.output.write_text(report)
        args.output.with_suffix(".json").write_text(json.dumps(dict(model=client.model, results=results), indent=2) + "\n")
        print(report)
        return 0

    now = datetime.fromisoformat(args.now) if args.now else datetime.now(timezone.utc)
    path = args.live_dir / PREVIEW_FILE
    saved = json.loads(path.read_text()) if path.exists() else {}
    if not client:
        print("No GEMINI_API_KEY set; using template previews.")
    updated, notes = update(rows, saved, now, client)
    path.write_text(json.dumps(updated, indent=2, sort_keys=True) + "\n")
    new = [updated[g] for g in updated if g not in saved]
    print(f"Saved {len(new)} preview(s): {sum(p['source'] == 'ai' for p in new)} AI, "
          f"{sum(p['source'] == 'template' for p in new)} template.")
    for note in notes:
        print(note)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
