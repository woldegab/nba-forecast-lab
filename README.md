# NBA Forecast Lab

Daily NBA win probabilities from an Elo model, with a public track record.

- **Today:** forecasts for today's 2026-27 games, saved before tip-off by a
  scheduled GitHub Action and never edited afterward.
- **Past seasons:** historical backtests for 2023-24 (warm-up), 2024-25 (development)
  and 2025-26 (held-out test).
- **Players:** player cards with recent averages, full game logs, and head-to-head
  history before any past game.

## Run locally

Requires Python 3.10+ and a Node version supported by Vite 8 (20.19+ or 22.12+).
First install dependencies:

```sh
python3 -m venv backend/.venv
backend/.venv/bin/python -m pip install -r backend/requirements.txt
npm --prefix client ci
```

If the saved data is not present, follow [the data setup](backend/README.md) to
import all three seasons, then generate the prediction artifacts:

```sh
backend/.venv/bin/python backend/evaluate_elo.py
```

Start the Python API in one terminal, from the repository root:

```sh
backend/.venv/bin/python -m uvicorn api:app --app-dir backend --host 127.0.0.1 --port 8000
```

Start React in a second terminal:

```sh
npm --prefix client run dev -- --port 5173 --strictPort
```

Open **http://127.0.0.1:5173**. API documentation is available at
http://127.0.0.1:8000/docs. Stop either server with Ctrl+C in its terminal.

## What you can explore

- Select any archived season and date; arrows move between dates with games.
- Compare each team's win probability with the final result.
- Expand a game to inspect pregame Elo ratings and venue treatment.
- Compare Elo accuracy and probability error with the home-team baseline.
- Review methodology and limitations; the warm-up season has no evaluation metrics.

React requests `/api/*`; Vite proxies these requests to the Python API. The API
loads `backend/data/backtest/predictions.csv` and `report.json` into a read-only
snapshot at startup. Page visits make no requests to NBA.com or BALLDONTLIE.
Restart the API after regenerating artifacts. Missing/invalid artifacts produce
an actionable HTTP 503 rather than fabricated predictions.

| Endpoint | Response |
|---|---|
| `GET /api/seasons` | Available seasons, game dates, counts and evaluation phase |
| `GET /api/games?date=2026-01-15` | Saved probabilities, ratings, scores and correctness |
| `GET /api/model-performance` | Original report, metrics, settings and limitations |

An empty date returns an empty game list. Missing or invalid date parameters
return HTTP 422. Local API paths are fixed; callers cannot choose files to read.

## Checks

```sh
backend/.venv/bin/python -m unittest discover -s backend -p 'test_*.py'
npm --prefix client run lint
npm --prefix client run build
```

The same checks run on every push and pull request in GitHub Actions
(`.github/workflows/ci.yml`).

## Live forecasts (2026-27)

`backend/live_forecast.py` keeps an append-only ledger in `backend/live/`:

```sh
# Once, locally, after importing all three archived seasons:
backend/.venv/bin/python backend/live_forecast.py init
# Daily (the GitHub Action does this at 15:00 UTC):
backend/.venv/bin/python backend/live_forecast.py update
```

`init` replays the archive and saves offseason-regressed starting ratings.
`update` downloads yesterday's and today's games from ESPN's public scoreboard, fills
in final scores, and records a forecast for every game on today's Eastern date that
has not tipped off. Earlier results come from the ledger itself, so each run needs only
two small requests. stats.nba.com blocks cloud servers like GitHub Actions; from a home
connection, `update --source nba` rebuilds the whole season from it instead. Games are
matched across sources by date and teams, so the two never double-count. A forecast row is
never rewritten; later runs only add the result. Ratings use finished games from
earlier dates only, matching the backtest. Games that ended before the ledger first
saw them are stored as `backfill` and excluded from the live record.

The workflow commits the ledger each morning, so the commit history shows every
forecast existed before its game. Offline runs with a saved NBA season-schedule file:
`update --input schedule.json --now 2026-11-26T15:00:00+00:00`.

Limitations: postponed games keep their original forecast. Game logs have no tip-off
time, so backfilled games are stamped midnight Eastern. Upcoming neutral-site games
need an entry in `neutral_sites.json`; finished ones are detected automatically.

## Player stats: this season and careers

stats.nba.com blocks cloud servers, so player stats are refreshed from a home
connection. This season's game logs and career stats live in a small second database,
`backend/data/current.sqlite3`; the archive (`nba.sqlite3`) stays untouched, which keeps
the repository from growing by megabytes every day. The player pages read both files.

```sh
scripts/mac_refresh.sh            # this season's games; careers on Mondays or first run
scripts/mac_refresh.sh --careers  # force a career refresh (10-20 minutes)
```

To run it every morning (8:30 a.m.; macOS catches up after sleep):

```sh
sed "s#REPO_PATH#$PWD#" scripts/com.nbaforecastlab.refresh.plist > ~/Library/LaunchAgents/com.nbaforecastlab.refresh.plist
launchctl bootstrap gui/$(id -u) ~/Library/LaunchAgents/com.nbaforecastlab.refresh.plist
```

Logs: `~/Library/Logs/nba-forecast-lab.log`. Stop it with
`launchctl bootout gui/$(id -u)/com.nbaforecastlab.refresh`.

## Deployment

One Docker image builds the React site and serves it from FastAPI, so the API and
pages share an origin. On Render: **New > Blueprint**, choose this repo
(`render.yaml`). Each push to `main`, including the daily forecast commit,
redeploys. Any Docker host works:

```sh
docker build -t nba-forecast-lab .
docker run -p 8000:8000 nba-forecast-lab
```

The site needs the generated artifacts committed: `backend/data/backtest/`,
`backend/data/nba.sqlite3`, `backend/data/player_points.json` and `backend/live/`.
Raw API downloads stay ignored.

See [model documentation](backend/README.md) and [first evaluation results](backend/BASELINE_RESULTS.md).

## Player explorer

Import historical player appearances (no paid API key):

```sh
backend/.venv/bin/python backend/import_players.py --season 2025-26
```

The importer validates the full response before storing records in the
`player_games` SQLite table. Reimports update existing appearances. The original
response is saved as `backend/data/player_logs_2025-26.json`; rerun offline with
`--input backend/data/player_logs_2025-26.json`.

The app opens on **Players**. Search by name or filter by the team at each player's
latest appearance. Select a card to see up to ten recent games, their averages,
and a scoring chart. These are season-ending historical statistics, not current
rosters or pregame projections. Missed games are not filled in with zeros.
Player statistics are not used in Elo predictions yet.

- `GET /api/players?season=2025-26` returns available seasons and player summaries.
- `GET /api/players/{player_id}?season=2025-26` returns the ten latest appearances.

Player endpoints read SQLite on each request; restart an older API process once
to load the new routes. The initial import contains 26,651 appearances for 582
players. This count describes the source response, not an independent completeness
guarantee. Team and player data remain local and excluded from Git.

## Historical player matchups

Under **Game predictions**, choose a date in 2025–26 and click **Explore player
matchups**. Select an actual game participant to explore Last 5, Last 10, or
season-to-date statistics. The roster is identified from postgame appearances;
it is not an archived pregame lineup or availability prediction.

All analysis rows satisfy `game_date < selected_game_date` within the selected
season. This excludes the selected game, other games on its date, and future
results. Previous meetings with the opponent use all earlier appearances in that
season and display their own sample size. No-history averages are null (shown
as a dash), never zero. These statistics are descriptive, not player projections.
Earlier team seasons remain browsable but show an unavailable-player-data state
until their player logs are imported.

- `GET /api/matchups/{game_id}` returns actual participant identities without game scores.
- `GET /api/matchups/{game_id}/players/{player_id}?window=5` returns pregame history.
  Supported windows: `5`, `10`, `season` (default `10`).

## Initial player-points baseline

Generate the local projection artifact after importing player and team logs:

```sh
backend/.venv/bin/python backend/evaluate_points.py
```

The fixed baseline averages up to ten earlier player appearances and requires at
least five. A ridge-regression challenger (penalty 1, standardized inputs) uses
recent points, minutes, scoring rate, rest and opponent team points allowed.
No selected-game or same-day outcomes enter either model's inputs.

Chronological 2025–26 protocol: train before January 1; select using January 1–15
MAE; calibrate a pooled nominal 80% error range using January 16–31; test from
February 1 onward. The baseline won development selection and remains the served
model even though the challenger was slightly better on the test period. We do
not select models using test results. Before January 16 only the baseline is
eligible; calibrated ranges are available only from February 1. Intervals are
pooled across players and are approximate, not individual guarantees.

See [the measured results](backend/PLAYER_POINTS_RESULTS.md). Projections are
conditional on actually appearing; availability, injuries and roster forecasts
are not modeled. The test period has now been evaluated and should not be reused
for tuning. `backend/data/player_points.json` stores the parameters, provenance,
metrics and historical projections. Regenerate it after changing source data.

Open a game, choose **Explore player matchups**, and select a player to see the
points projection. Changing the history window changes descriptive statistics,
not the fixed ten-game prediction baseline. The general Players page and player
detail pages now support Last 5 / Last 10 / Full season via a `window` query
parameter (`5`, `10`, or `season`) on both player endpoints.

Completed player matchups now show projected points, actual points, and
`actual − projected` by default, including whether the outcome falls inside an
available estimated range. The existing **Show results** setting carries from
the game slate into participant and player views, and can be changed there.
Replay mode hides actual points, differences, and range-hit information together.
Actual points are returned separately from pregame history and never enter the
projection calculation. If no projection exists, the actual score is still shown.
