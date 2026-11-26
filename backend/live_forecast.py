"""Live 2026-27 Elo forecasts, recorded before tip-off in an append-only ledger.

Two commands:

  init    Replay the three archived seasons from the local database, regress the
          final ratings for the offseason, and save them as the 2026-27 starting
          ratings. Run once, locally, after importing 2025-26.

  update  Download this season's results and today's scoreboard (stats.nba.com via
          nba_api), fill in final scores, and record a forecast for every game today
          (US Eastern date) that has not started yet. Run daily, after the previous
          day's games have finished.

Forecast rows are never rewritten: once a game's probability is in the ledger,
later runs only add its final score. Games that finished before the ledger first
saw them are stored as "backfill" and reported separately from "live" forecasts.
"""

import argparse
import copy
import csv
from collections import defaultdict
from datetime import datetime, timedelta, timezone
import hashlib
import json
from pathlib import Path
import sqlite3
import sys
import time
from zoneinfo import ZoneInfo

from evaluate_elo import PARAMETERS, SEASONS, audit, backtest, metrics, win_probability
from import_games import DEFAULT_DB, NEUTRAL_SITES

LIVE_SEASON = "2026-27"
LIVE_DIR = Path(__file__).parent / "live"
START_FILE = "start_ratings.json"
LEDGER_FILE = f"predictions_{LIVE_SEASON}.csv"
SUMMARY_FILE = "summary.json"
EASTERN = ZoneInfo("America/New_York")

FINAL, NOT_STARTED = 3, 1
PREDICTION_FIELDS = ["game_id", "game_date", "tipoff_utc", "home_team_id", "home_team",
                     "away_team_id", "away_team", "neutral_site", "home_rating",
                     "away_rating", "home_win_probability", "predicted_at_utc", "mode"]
RESULT_FIELDS = ["home_score", "away_score", "actual_home_win"]
LEDGER_FIELDS = PREDICTION_FIELDS + RESULT_FIELDS


# ---------- starting ratings ----------

def start_ratings(games, parameters=None):
    """End-of-archive ratings, regressed toward the mean for the new season."""
    p = PARAMETERS if parameters is None else parameters
    ratings = {}
    backtest(games, p, ratings)
    teams = {}
    for g in games:
        teams[g["home_team_id"]] = g["home_team"]
        teams[g["away_team_id"]] = g["away_team"]
    return {str(team): dict(team=teams[team], rating=round(
        p["initial_rating"] + p["retention"] * (rating - p["initial_rating"]), 6))
        for team, rating in sorted(ratings.items())}


def init(database, output):
    with sqlite3.connect(f"{Path(database).resolve().as_uri()}?mode=ro", uri=True) as connection:
        connection.row_factory = sqlite3.Row
        games = [dict(r) for r in connection.execute(
            "SELECT * FROM games WHERE season_type='Regular Season' AND season IN (?, ?, ?) "
            "ORDER BY game_date, game_id", SEASONS)]
    audit(games)
    ratings = start_ratings(games)
    if len(ratings) != 30:
        raise ValueError(f"Expected 30 teams, found {len(ratings)}")
    digest = hashlib.sha256(json.dumps(games, sort_keys=True).encode()).hexdigest()
    payload = dict(season=LIVE_SEASON, carried_from=SEASONS[-1], parameters=PARAMETERS,
                   generated_at=datetime.now(timezone.utc).isoformat(timespec="seconds"),
                   archive_sha256=digest, ratings=ratings)
    output.mkdir(parents=True, exist_ok=True)
    (output / START_FILE).write_text(json.dumps(payload, indent=2) + "\n")
    return payload


# ---------- schedule and results ----------
# Data comes from stats.nba.com through nba_api, the library the importers already use.
# (NBA.com's CDN schedule files answer 403 to scripts.)

def with_retries(label, request, attempts=3):
    for attempt in range(attempts):
        try:
            return request()
        except Exception as error:  # nba_api surfaces requests, timeout and JSON errors
            if attempt + 1 == attempts:
                raise RuntimeError(f"{label} failed: {type(error).__name__}: {error}") from error
            delay = 5 * (2 ** attempt)
            print(f"{label} failed; retrying in {delay}s", file=sys.stderr)
            time.sleep(delay)


def fetch_results(season=LIVE_SEASON, timeout=30):
    """Team game logs for finished regular-season games (two rows per game)."""
    from nba_api.stats.endpoints import leaguegamelog
    return with_retries("Results request", lambda: leaguegamelog.LeagueGameLog(
        season=season, season_type_all_star="Regular Season", player_or_team_abbreviation="T",
        timeout=timeout).get_normalized_dict()["LeagueGameLog"])


def fetch_scoreboard(day, timeout=30):
    """Every game on one date (YYYY-MM-DD, US Eastern), with status and tip-off time."""
    from nba_api.stats.endpoints import scoreboardv3
    return with_retries(f"Scoreboard request for {day}", lambda: scoreboardv3.ScoreboardV3(
        game_date=day, league_id="00", timeout=timeout).get_dict())


def parse_game(g, time_key):
    """One game in the NBA's JSON shape (schedule file or scoreboard), validated."""
    game_id = str(g["gameId"])
    tipoff = datetime.fromisoformat(g[time_key].replace("Z", "+00:00"))
    home, away = g["homeTeam"], g["awayTeam"]
    if home["teamId"] == away["teamId"]:
        raise ValueError(f"Game {game_id}: same team twice")
    status = int(g["gameStatus"])
    game = dict(game_id=game_id, tipoff=tipoff,
                game_date=tipoff.astimezone(EASTERN).date().isoformat(),
                status=status, postponed="ppd" in str(g.get("gameStatusText", "")).lower(),
                home_team_id=int(home["teamId"]), home_team=home["teamTricode"],
                away_team_id=int(away["teamId"]), away_team=away["teamTricode"],
                neutral_site=int(bool(g.get("isNeutral")) or game_id in NEUTRAL_SITES),
                home_score=None, away_score=None)
    if status == FINAL:
        scores = [home.get("score"), away.get("score")]
        if any(isinstance(s, bool) or not isinstance(s, int) or s < 0 for s in scores) or scores[0] == scores[1]:
            raise ValueError(f"Game {game_id}: invalid final score")
        game["home_score"], game["away_score"] = scores
    return game


def parse_schedule(data, season=LIVE_SEASON):
    """Regular-season games from a saved NBA season-schedule file (used with --input)."""
    schedule = data["leagueSchedule"]
    if schedule.get("seasonYear") != season:
        raise ValueError(f"Schedule is for {schedule.get('seasonYear')}, expected {season}")
    games = [parse_game(g, "gameDateTimeUTC") for day in schedule["gameDates"] for g in day["games"]
             if str(g["gameId"]).startswith("002")]   # regular season only
    if len({g["game_id"] for g in games}) != len(games):
        raise ValueError("Duplicate game in schedule")
    if not games:
        raise ValueError("No regular-season games in schedule")
    return sorted(games, key=lambda g: (g["tipoff"], g["game_id"]))


def parse_scoreboard(data):
    """Regular-season games from one day's scoreboard."""
    return [parse_game(g, "gameTimeUTC") for g in data["scoreboard"]["games"]
            if str(g["gameId"]).startswith("002")]


def games_from_results(rows, season=LIVE_SEASON):
    """Finished games from team game logs, validated like import_games.py.

    Game logs have no tip-off time, so these games get midnight Eastern on their date.
    A game where neither team is listed as home (Mexico City, Europe, NBA Cup
    semifinals) is treated as neutral.
    """
    expected_season = "2" + season[:4]
    grouped = defaultdict(list)
    for row in rows:
        if str(row["SEASON_ID"]) != expected_season:
            raise ValueError("Results are not from the requested regular season")
        grouped[str(row["GAME_ID"])].append(row)
    games = []
    for game_id, teams in grouped.items():
        if len(teams) != 2:
            raise ValueError(f"Game {game_id}: expected exactly two team records")
        neutral = game_id in NEUTRAL_SITES
        if neutral:
            designated = NEUTRAL_SITES[game_id]["home"]
            home = [r for r in teams if r["TEAM_ABBREVIATION"] == designated]
            away = [r for r in teams if r["TEAM_ABBREVIATION"] != designated]
        else:
            home = [r for r in teams if " vs. " in r["MATCHUP"]]
            away = [r for r in teams if " @ " in r["MATCHUP"]]
        if len(home) != 1 or len(away) != 1:
            neutral = True
            first, second = sorted(teams, key=lambda r: int(r["TEAM_ID"]))
            home, away = [first], [second]
        home, away = home[0], away[0]
        dates = {datetime.fromisoformat(str(r["GAME_DATE"])[:10]).date().isoformat() for r in teams}
        if len(dates) != 1 or home["TEAM_ID"] == away["TEAM_ID"]:
            raise ValueError(f"Game {game_id}: inconsistent teams or dates")
        scores = [home["PTS"], away["PTS"]]
        if any(isinstance(s, bool) or not isinstance(s, int) or s < 0 for s in scores) or scores[0] == scores[1]:
            raise ValueError(f"Game {game_id}: invalid final score")
        if [home["WL"], away["WL"]] != (["W", "L"] if scores[0] > scores[1] else ["L", "W"]):
            raise ValueError(f"Game {game_id}: results disagree with scores")
        day = dates.pop()
        games.append(dict(game_id=game_id, tipoff=datetime.fromisoformat(f"{day}T00:00:00").replace(tzinfo=EASTERN),
                          game_date=day, status=FINAL, postponed=False,
                          home_team_id=int(home["TEAM_ID"]), home_team=home["TEAM_ABBREVIATION"],
                          away_team_id=int(away["TEAM_ID"]), away_team=away["TEAM_ABBREVIATION"],
                          neutral_site=int(neutral), home_score=scores[0], away_score=scores[1]))
    return games


def combine(results, *scoreboards):
    """Scoreboard games, with game-log results taking precedence for finished games."""
    games = {}
    for board in scoreboards:
        for game in board:
            games[game["game_id"]] = game
    for game in results:
        listed = games.get(game["game_id"])
        if listed:  # keep the real tip-off time and the scoreboard's home/away designation
            game = dict(game, tipoff=listed["tipoff"])
            if game["home_team_id"] != listed["home_team_id"]:
                game.update(home_team_id=game["away_team_id"], home_team=game["away_team"],
                            away_team_id=game["home_team_id"], away_team=game["home_team"],
                            home_score=game["away_score"], away_score=game["home_score"])
        games[game["game_id"]] = game
    return sorted(games.values(), key=lambda g: (g["tipoff"], g["game_id"]))


def download_games(now):
    """This season's finished games plus yesterday's and today's scoreboards."""
    today = now.astimezone(EASTERN).date()
    yesterday = (today - timedelta(days=1)).isoformat()
    boards = [parse_scoreboard(fetch_scoreboard(day)) for day in (yesterday, today.isoformat())]
    return combine(games_from_results(fetch_results()), *boards)


# ---------- ledger ----------

def read_ledger(path):
    if not path.exists():
        return {}
    with path.open(newline="") as file:
        rows = list(csv.DictReader(file))
    ledger = {}
    for row in rows:
        if row["game_id"] in ledger:
            raise ValueError(f"Ledger has game {row['game_id']} twice")
        ledger[row["game_id"]] = row
    return ledger


def write_ledger(path, ledger):
    rows = sorted(ledger.values(), key=lambda r: (r["tipoff_utc"], r["game_id"]))
    temporary = path.with_suffix(".tmp")
    with temporary.open("w", newline="") as file:
        writer = csv.DictWriter(file, fieldnames=LEDGER_FIELDS)
        writer.writeheader()
        writer.writerows(rows)
    temporary.replace(path)


def prediction_row(game, home_rating, away_rating, probability, now, mode):
    return dict(game_id=game["game_id"], game_date=game["game_date"],
                tipoff_utc=game["tipoff"].isoformat(timespec="seconds"),
                home_team_id=game["home_team_id"], home_team=game["home_team"],
                away_team_id=game["away_team_id"], away_team=game["away_team"],
                neutral_site=game["neutral_site"], home_rating=round(home_rating, 6),
                away_rating=round(away_rating, 6), home_win_probability=round(probability, 6),
                predicted_at_utc=now.isoformat(timespec="seconds"), mode=mode,
                home_score="", away_score="", actual_home_win="")


def update(schedule_games, start, ledger, now):
    """Return (ledger, notes). Existing forecast fields are never changed."""
    ledger = copy.deepcopy(ledger)
    notes = []
    today = now.astimezone(EASTERN).date().isoformat()
    by_id = {g["game_id"]: g for g in schedule_games}

    # 1. Record final scores for games already in the ledger.
    for game_id, row in ledger.items():
        game = by_id.get(game_id)
        if game and game["status"] == FINAL and row["home_score"] == "":
            row["home_score"], row["away_score"] = game["home_score"], game["away_score"]
            row["actual_home_win"] = int(game["home_score"] > game["away_score"])

    # 2. Rebuild current ratings from finished games on earlier dates only.
    finished = [g for g in schedule_games if g["status"] == FINAL and g["game_date"] < today]
    ratings = {int(team): value["rating"] for team, value in start["ratings"].items()}
    replay = backtest([dict(g, season=LIVE_SEASON) for g in finished], start["parameters"], ratings)

    # 3. Games that finished before the ledger saw them: backfill, labeled as such.
    for row in replay:
        if row["game_id"] not in ledger:
            game = by_id[row["game_id"]]
            new = prediction_row(game, row["home_rating"], row["away_rating"],
                                 row["home_win_probability"], now, "backfill")
            new.update(home_score=game["home_score"], away_score=game["away_score"],
                       actual_home_win=row["actual_home_win"])
            ledger[row["game_id"]] = new

    # 4. Live forecasts for today's games that have not tipped off.
    unfinished_earlier = [g["game_id"] for g in schedule_games
                          if g["game_date"] < today and g["status"] != FINAL and not g["postponed"]]
    if unfinished_earlier:
        notes.append(f"Skipped today's forecasts: {len(unfinished_earlier)} earlier game(s) not final "
                     f"({', '.join(unfinished_earlier[:5])}).")
        return ledger, notes
    for game in schedule_games:
        if (game["game_date"] == today and game["status"] == NOT_STARTED and not game["postponed"]
                and game["tipoff"] > now and game["game_id"] not in ledger):
            home = ratings.get(game["home_team_id"], start["parameters"]["initial_rating"])
            away = ratings.get(game["away_team_id"], start["parameters"]["initial_rating"])
            probability = win_probability(home, away, game["neutral_site"], start["parameters"])
            ledger[game["game_id"]] = prediction_row(game, home, away, probability, now, "live")
    return ledger, notes


def summarize(ledger, now):
    def score(rows):
        done = [r for r in rows if r["actual_home_win"] != ""]
        if not done:
            return dict(games=0)
        probabilities = [float(r["home_win_probability"]) for r in done]
        outcomes = [int(r["actual_home_win"]) for r in done]
        return dict(games=len(done), **metrics(probabilities, outcomes),
                    home_win_rate=sum(outcomes) / len(outcomes))
    rows = list(ledger.values())
    live = [r for r in rows if r["mode"] == "live"]
    return dict(season=LIVE_SEASON, updated_at=now.isoformat(timespec="seconds"),
                live=score(live), backfill=score([r for r in rows if r["mode"] == "backfill"]),
                all=score(rows), pending=sum(r["actual_home_win"] == "" for r in rows),
                first_live_date=min((r["game_date"] for r in live), default=None),
                note="Live forecasts were saved before tip-off. Backfill rows were computed "
                     "after the game from earlier results only, and are reported separately.")


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    commands = parser.add_subparsers(dest="command", required=True)
    first = commands.add_parser("init", help="Create 2026-27 starting ratings from the local archive")
    first.add_argument("--database", type=Path, default=DEFAULT_DB)
    daily = commands.add_parser("update", help="Record results and today's forecasts")
    daily.add_argument("--input", type=Path, help="Read a saved NBA season-schedule JSON instead of downloading")
    daily.add_argument("--now", help="Override the current time (ISO 8601, for testing)")
    for command in (first, daily):
        command.add_argument("--live-dir", type=Path, default=LIVE_DIR)
    args = parser.parse_args(argv)
    try:
        if args.command == "init":
            payload = init(args.database, args.live_dir)
            print(f"Saved {len(payload['ratings'])} starting ratings to {args.live_dir / START_FILE}")
            return 0
        now = datetime.fromisoformat(args.now) if args.now else datetime.now(timezone.utc)
        if now.tzinfo is None:
            raise ValueError("--now must include a timezone, e.g. 2026-11-26T15:00:00+00:00")
        start = json.loads((args.live_dir / START_FILE).read_text())
        games = parse_schedule(json.loads(args.input.read_text())) if args.input else download_games(now)
        ledger_path = args.live_dir / LEDGER_FILE
        before = read_ledger(ledger_path)
        ledger, notes = update(games, start, before, now)
        write_ledger(ledger_path, ledger)
        summary = summarize(ledger, now)
        (args.live_dir / SUMMARY_FILE).write_text(json.dumps(summary, indent=2) + "\n")
    except (RuntimeError, ValueError, KeyError, TypeError, OSError, sqlite3.Error) as error:
        print(f"Live update failed: {error}", file=sys.stderr)
        return 1
    added = {mode: sum(r["mode"] == mode for g, r in ledger.items() if g not in before)
             for mode in ("live", "backfill")}
    print(f"Added {added['live']} live forecast(s) and {added['backfill']} backfill row(s); "
          f"{summary['pending']} awaiting results.")
    live = summary["live"]
    if live["games"]:
        print(f"Live record: {live['accuracy']:.1%} over {live['games']} games, Brier {live['brier']:.4f}.")
    for note in notes:
        print(note)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
