"""Read-only local API for saved historical backtests. No NBA network requests."""
from collections import defaultdict
from contextlib import asynccontextmanager
import csv
from datetime import date as Date
import json
import math
from pathlib import Path

import os

from fastapi import FastAPI, HTTPException, Query
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from player_api import player_router
from evaluate_elo import ORIGINAL_PARAMETERS
from insights import calibration, power_rankings, team_histories

DATA_DIR = Path(__file__).parent / "data" / "backtest"
LIVE_DIR = Path(__file__).parent / "live"
EVAL_DIR = Path(__file__).parent / "eval"
# Built React app; served by the API in production so one service hosts both.
STATIC_DIR = Path(os.environ.get("STATIC_DIR", Path(__file__).parent.parent / "client" / "dist"))


def load_snapshot(folder):
    report = json.loads((folder / "report.json").read_text())
    games_by_date = defaultdict(list)
    dates_by_season = defaultdict(set)
    seen = set()
    with (folder / "predictions.csv").open(newline="") as file:
        for row in csv.DictReader(file):
            game_date = Date.fromisoformat(row["game_date"]).isoformat()
            p = float(row["home_win_probability"])
            if not math.isfinite(p) or not 0 <= p <= 1 or row["game_id"] in seen:
                raise ValueError("Invalid or duplicate prediction")
            seen.add(row["game_id"])
            home_score, away_score = int(row["home_score"]), int(row["away_score"])
            actual = int(row["actual_home_win"])
            if actual not in (0, 1) or actual != int(home_score > away_score) or home_score == away_score:
                raise ValueError("Prediction outcome disagrees with scores")
            game = dict(game_id=row["game_id"], season=row["season"], date=game_date,
                home_team=row["home_team"], away_team=row["away_team"],
                home_score=home_score, away_score=away_score,
                home_rating=float(row["home_rating"]), away_rating=float(row["away_rating"]),
                home_win_probability=p, away_win_probability=1-p,
                neutral_site=bool(int(row["neutral_site"])),
                predicted_winner=row["home_team"] if p >= 0.5 else row["away_team"],
                actual_winner=row["home_team"] if actual else row["away_team"],
                correct=(p >= 0.5) == bool(actual))
            games_by_date[game_date].append(game)
            dates_by_season[row["season"]].add(game_date)
    seasons = []
    for season, coverage in sorted(report["coverage"].items(), reverse=True):
        dates = sorted(dates_by_season[season])
        count = sum(g["season"] == season for games in games_by_date.values() for g in games)
        if not dates or count != coverage["games"]:
            raise ValueError("Report and predictions have different coverage")
        seasons.append(dict(season=season, first_date=dates[0], last_date=dates[-1],
            dates=dates, games=count,
            phase="Warm-up" if season == report["warmup_season"] else
                  "Initial test" if season == report["test_season"] else "Development"))
    if set(dates_by_season) != set(report["coverage"]):
        raise ValueError("Unexpected season in predictions")
    return report, dict(games_by_date), seasons


def load_live(folder):
    """Live ledger and summary written by live_forecast.py."""
    summary = json.loads((folder / "summary.json").read_text())
    with (folder / f"predictions_{summary['season']}.csv").open(newline="") as file:
        rows = list(csv.DictReader(file))
    games = []
    for row in rows:
        p = float(row["home_win_probability"])
        if not math.isfinite(p) or not 0 <= p <= 1:
            raise ValueError("Invalid live probability")
        final = row["actual_home_win"] != ""
        actual = int(row["actual_home_win"]) if final else None
        games.append(dict(game_id=row["game_id"], date=row["game_date"], tipoff_utc=row["tipoff_utc"],
            home_team=row["home_team"], away_team=row["away_team"],
            neutral_site=bool(int(row["neutral_site"])), mode=row["mode"],
            predicted_at_utc=row["predicted_at_utc"],
            home_rating=float(row["home_rating"]), away_rating=float(row["away_rating"]),
            home_win_probability=p, away_win_probability=1 - p,
            predicted_winner=row["home_team"] if p >= 0.5 else row["away_team"],
            home_score=int(row["home_score"]) if final else None,
            away_score=int(row["away_score"]) if final else None,
            actual_winner=(row["home_team"] if actual else row["away_team"]) if final else None,
            correct=((p >= 0.5) == bool(actual)) if final else None))
    return summary, games


def create_app(data_dir=DATA_DIR, live_dir=LIVE_DIR, static_dir=STATIC_DIR, eval_dir=EVAL_DIR):
    @asynccontextmanager
    async def lifespan(app):
        try:
            app.state.snapshot = load_snapshot(Path(data_dir))
        except (OSError, ValueError, KeyError, TypeError):
            app.state.snapshot = None
        yield

    app = FastAPI(title="NBA Forecast Lab", version="0.1.0", lifespan=lifespan)
    app.include_router(player_router())

    def snapshot():
        if app.state.snapshot is None:
            raise HTTPException(503, "Saved backtest is unavailable. Generate it with backend/evaluate_elo.py and restart the API.")
        return app.state.snapshot

    @app.get("/api/seasons")
    def seasons():
        report, _, available = snapshot()
        return dict(seasons=available, generated_at=report["generated_at"], mode="historical_backtest")

    @app.get("/api/games")
    def games(date: Date = Query(...)):
        _, by_date, _ = snapshot()
        selected = date.isoformat()
        return dict(date=selected, games=by_date.get(selected, []), mode="historical_backtest")

    @app.get("/api/model-performance")
    def performance():
        report, _, _ = snapshot()
        return report

    @app.get("/api/live")
    def live(recent: int = Query(40, ge=0, le=200)):
        summary, games = live_games()
        upcoming = [g for g in games if g["home_score"] is None]
        finished = [g for g in games if g["home_score"] is not None and g["mode"] == "live"]
        return dict(summary=summary, upcoming=upcoming, recent=finished[-recent:][::-1] if recent else [],
                    model_change=model_change())

    def model_change():
        """When the live season switched models: forecasts saved after `since` use the new one."""
        try:
            start = json.loads((Path(live_dir) / "start_ratings.json").read_text())
        except (OSError, ValueError):
            return None
        current = dict(ORIGINAL_PARAMETERS, **start.get("parameters", {}))
        if current == ORIGINAL_PARAMETERS:
            return None
        return dict(since=start["generated_at"], margin_of_victory=current["margin_of_victory"],
                    back_to_back=current["back_to_back"])

    def with_previews(summary, games):
        """Attach saved previews (backend/previews.py) and recaps (backend/recaps.py) to their games."""
        def load(name):
            try:
                return json.loads((Path(live_dir) / f"{name}_{summary['season']}.json").read_text())
            except (OSError, ValueError):
                return {}
        previews, recaps = load("previews"), load("recaps")
        for g in games:
            p, r = previews.get(g["game_id"]), recaps.get(g["game_id"])
            g["preview"] = dict(headline=p["headline"], text=p["preview"], source=p["source"]) if p else None
            g["recap"] = dict(text=r["recap"], source=r["source"]) if r else None
        return summary, games

    @app.get("/api/ai-quality")
    def ai_quality():
        """Weekly AI text quality (backend/ai_eval.py weekly) and the judge's agreement with hand labels."""
        def read(name):
            try:
                return json.loads((Path(eval_dir) / name).read_text())
            except (OSError, ValueError):
                return None
        judge = read("judge_eval.json")
        return dict(history=read("history.json") or [], judge=judge["stats"] if judge else None)

    def live_games():
        try:
            return with_previews(*load_live(Path(live_dir)))
        except (OSError, ValueError, KeyError, TypeError):
            raise HTTPException(503, "Live forecasts are not available yet. Run backend/live_forecast.py update.")

    @app.get("/api/live/days")
    def live_days():
        """Every date this season with games, and how the forecasts did that day."""
        summary, games = live_games()
        days = {}
        for g in games:
            day = days.setdefault(g["date"], dict(date=g["date"], games=0, finished=0, correct=0, backfill=0))
            day["games"] += 1
            day["backfill"] += g["mode"] == "backfill"
            if g["correct"] is not None:
                day["finished"] += 1
                day["correct"] += g["correct"]
        return dict(season=summary["season"], days=sorted(days.values(), key=lambda d: d["date"]))

    @app.get("/api/live/day")
    def live_day(date: Date = Query(...)):
        _, games = live_games()
        selected = date.isoformat()
        return dict(date=selected, games=[g for g in games if g["date"] == selected])

    def team_sources():
        """{season: (games, history options, starting ratings by team or None)} from the archive and live ledger."""
        sources = {}
        if app.state.snapshot is not None:
            report, by_date, _ = app.state.snapshot
            archive = [g for day in by_date.values() for g in day]
            for season in {g["season"] for g in archive}:
                sources[season] = ([g for g in archive if g["season"] == season],
                                   dict(parameters=dict(ORIGINAL_PARAMETERS, **report["parameters"])), None)
        try:
            summary, games = load_live(Path(live_dir))
            start = json.loads((Path(live_dir) / "start_ratings.json").read_text())
            change = model_change()
            options = dict(parameters=dict(ORIGINAL_PARAMETERS, **start["parameters"]))
            if change:
                options.update(earlier=ORIGINAL_PARAMETERS, since=change["since"])
            sources[summary["season"]] = (games, options,
                                          {v["team"]: v["rating"] for v in start["ratings"].values()})
        except (OSError, ValueError, KeyError, TypeError):
            pass
        if not sources:
            raise HTTPException(503, "No forecasts are available yet.")
        return sources

    def pick_season(sources, season):
        seasons = sorted(sources, reverse=True)
        chosen = season or seasons[0]
        if chosen not in sources:
            raise HTTPException(404, "No forecasts for this season")
        return chosen, seasons

    @app.get("/api/teams")
    def teams(season: str | None = None):
        sources = team_sources()
        chosen, seasons = pick_season(sources, season)
        games, options, starting = sources[chosen]
        return dict(season=chosen, seasons=seasons, teams=power_rankings(team_histories(games, **options), starting))

    @app.get("/api/teams/{team}")
    def team(team: str, season: str | None = None):
        sources = team_sources()
        chosen, seasons = pick_season(sources, season)
        games, options, starting = sources[chosen]
        histories = team_histories(games, **options)
        ranking = next((row for row in power_rankings(histories, starting) if row["team"] == team.upper()), None)
        if ranking is None:
            raise HTTPException(404, "Team not found for this season")
        upcoming = [g for g in games if g.get("home_score") is None and team.upper() in (g["home_team"], g["away_team"])]
        return dict(season=chosen, seasons=seasons, **ranking, games=histories.get(team.upper(), []), upcoming=upcoming)

    @app.get("/api/calibration")
    def calibration_view():
        result = {}
        if app.state.snapshot is not None:
            report, by_date, _ = app.state.snapshot
            scored = [g for day in by_date.values() for g in day if g["season"] in report["results"]]
            result["archive"] = dict(seasons=sorted(report["results"]), games=len(scored), buckets=calibration(scored))
        try:
            summary, games = load_live(Path(live_dir))
            live = [g for g in games if g["mode"] == "live" and g["home_score"] is not None]
            result["live"] = dict(season=summary["season"], games=len(live), buckets=calibration(live))
        except (OSError, ValueError, KeyError, TypeError):
            pass
        if not result:
            raise HTTPException(503, "No forecasts are available yet.")
        return result

    @app.get("/og.png", include_in_schema=False)
    def link_preview():
        image = Path(live_dir) / "og.png"
        if not image.is_file():
            raise HTTPException(404, "Link preview has not been generated. Run backend/og_image.py.")
        return FileResponse(image, media_type="image/png", headers={"Cache-Control": "public, max-age=3600"})

    static = Path(static_dir)
    if (static / "index.html").exists():
        app.mount("/assets", StaticFiles(directory=static / "assets"), name="assets")

        @app.get("/{path:path}", include_in_schema=False)
        def frontend(path: str):
            if path.startswith("api/"):
                raise HTTPException(404, "Not found")
            candidate = (static / path).resolve()
            if path and candidate.is_file() and static.resolve() in candidate.parents:
                return FileResponse(candidate)
            return FileResponse(static / "index.html")

    return app


app = create_app()
