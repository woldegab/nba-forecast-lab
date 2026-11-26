# NBA Forecast Lab

Daily NBA win probabilities from an Elo rating model, with a track record that can't be edited after the fact.

**Live site: [nba-forecast-lab.onrender.com](https://nba-forecast-lab.onrender.com)**
(free hosting; the first visit after a quiet spell can take up to a minute to wake up)


Every morning a scheduled job pulls the day's NBA schedule, forecasts each game, and commits
those forecasts to this repository before tip-off. Forecasts are never rewritten afterward, so
the commit history proves each one existed before its game was played.

## Results

The model was built on 2024-25 and then scored on 2025-26, a season it had not seen.

| Season | Games | Correct picks | Always pick home team | Brier score |
|---|---:|---:|---:|---:|
| 2024-25 (development) | 1,230 | 67.2% | 54.4% | 0.210 |
| 2025-26 (held-out test) | 1,230 | **68.5%** | 55.4% | **0.206** |
| 2026-27 (live) | updated daily | [see the site](https://nba-forecast-lab.onrender.com) | | |

Brier score measures the quality of the probabilities, not just the picks; lower is better, and
guessing 50/50 every game scores 0.250. The site's *How it works* page also has a calibration
chart: when the model gives a team a 70% chance, that team should win about 70% of the time.

**How the model improved.** The first version, plain Elo, got 67.7% right on the held-out season
with a Brier score of 0.2097. Two ideas were then tested on 2024-25 only, each kept only if it
clearly helped there: weighting wins by margin of victory, and a 50-point penalty for teams on the
second night of a back-to-back (those teams won just 44.7% of the time in 2024-25). Scored once
on 2025-26, the new version reached 68.5% and 0.2056. The 95% interval for the Brier improvement,
0.0016 to 0.0069, excludes zero, so the gain is unlikely to be luck. Live forecasts switched to
the new version in November 2026; earlier live forecasts are unchanged.

Details: [experiment results](backend/MODEL_EXPERIMENT_RESULTS.md) and the
[first version's backtest](backend/BASELINE_RESULTS.md).

## What's on the site

- **Today:** today's forecasts, the live record, the closest game of the day, and recent results.
- **Teams:** power rankings, plus each team's rating after every game this season.
- **Past seasons:** every game from three seasons, forecast one day at a time using only earlier results.
- **Players:** current-season averages, game logs, career stats, and head-to-head history before any game.
- **How it works:** the model in four steps, accuracy by season, and the calibration chart.

## How it works

**The model.** Every team has a rating. Before a game, the rating gap becomes a win probability,
after adding 65 points for the home team and subtracting 50 from a team that played the night
before. After each day, winners take points from losers (K = 20), more for an upset or a bigger
win, using FiveThirtyEight's margin-of-victory factor. Between seasons, ratings keep 75% of their
distance from the average.
Games on the same day never affect each other's forecasts.

**The data pipeline.**

```
8:30 a.m. CT   Mac (launchd)     nba_api -> this season's player stats and careers -> commit
9:00 a.m. CT   GitHub Actions    ESPN scoreboard -> record results, forecast today's games -> commit
each push      Render            rebuild the Docker image -> serve the API and the site
```

- `backend/live_forecast.py` keeps an append-only ledger. A forecast row is never rewritten;
  later runs only add the final score. Games that finished before the ledger first saw them are
  stored as *backfill* and kept out of the live record.
- ESPN works from GitHub's servers, but stats.nba.com blocks cloud servers, so player stats
  refresh from a home connection. Games are matched across sources by date and teams, so
  nothing is double-counted.
- The archive (`nba.sqlite3`) never changes. This season's player data lives in a small second
  database (`current.sqlite3`), which keeps daily commits to a few hundred KB.

**The stack.** Python, FastAPI and SQLite on the backend; React and Vite on the frontend; one
Docker image serves both. GitHub Actions runs the tests on every push and the forecasts every
morning. The rating and calibration charts are hand-written SVG, and Pillow draws the
link-preview image at each deploy.

## AI game previews

Each game on the Today page has a short plain-English preview. `backend/previews.py` builds
the facts for a game (win chance, record, last 10, streak, back-to-back) from earlier games
only, asks an LLM (Google's Gemini API, free tier) to write two or three sentences from
those facts, and checks the result before saving it:

- every number in the text must appear in the facts, and percentages must be the win chances
- both teams are named, the favorite is named, and the underdog is never called the favorite
- no injury or betting talk, and length limits

A preview that fails is retried once, then replaced by a plain template, so the site never
shows unchecked AI text. Previews are saved next to the forecasts and never rewritten.

```sh
GEMINI_API_KEY=... python backend/previews.py update   # today's previews (templates without a key)
GEMINI_API_KEY=... python backend/previews.py eval     # pass rate on 30 recent games -> backend/PREVIEW_EVAL.md
```

The daily workflow reads the key from the `GEMINI_API_KEY` repository secret.

## Run it locally

Requires Python 3.10+ and Node 20.19+ (or 22.12+).

```sh
python3 -m venv backend/.venv
backend/.venv/bin/python -m pip install -r backend/requirements.txt
npm --prefix client ci
```

Start the API in one terminal and the site in another:

```sh
backend/.venv/bin/python -m uvicorn api:app --app-dir backend --host 127.0.0.1 --port 8000
npm --prefix client run dev -- --port 5173 --strictPort
```

Open http://127.0.0.1:5173. API docs are at http://127.0.0.1:8000/docs.

The saved data is committed, so this works right away. To rebuild it from scratch, follow
[the data setup](backend/README.md), then run `backend/.venv/bin/python backend/evaluate_elo.py`.

### Checks

```sh
backend/.venv/bin/python -m unittest discover -s backend -p 'test_*.py'
npm --prefix client run lint
npm --prefix client run build
```

The same checks run on every push in GitHub Actions (`.github/workflows/ci.yml`).

## Daily jobs

**Forecasts** run in `.github/workflows/daily-forecasts.yml` at 15:00 UTC. By hand:

```sh
backend/.venv/bin/python backend/live_forecast.py init     # once: starting ratings from the archive
backend/.venv/bin/python backend/live_forecast.py update   # daily: results and today's forecasts
```

`update --source nba` rebuilds the whole season from stats.nba.com instead (home connection only).

**Player stats** run on a Mac at 8:30 a.m.:

```sh
scripts/mac_refresh.sh            # this season's games; careers on Mondays or the first run
scripts/mac_refresh.sh --careers  # force a career refresh (10-20 minutes)
```

To schedule it every morning (macOS catches up after sleep):

```sh
sed "s#REPO_PATH#$PWD#" scripts/com.nbaforecastlab.refresh.plist > ~/Library/LaunchAgents/com.nbaforecastlab.refresh.plist
launchctl bootstrap gui/$(id -u) ~/Library/LaunchAgents/com.nbaforecastlab.refresh.plist
```

Logs go to `~/Library/Logs/nba-forecast-lab.log`. Stop it with
`launchctl bootout gui/$(id -u)/com.nbaforecastlab.refresh`.

## Deployment

On Render, choose **New > Blueprint** and pick this repo (`render.yaml`). Every push to `main`,
including the daily forecast commit, redeploys. Any Docker host works:

```sh
docker build -t nba-forecast-lab .
docker run -p 8000:8000 nba-forecast-lab
```

## API

| Endpoint | Returns |
|---|---|
| `GET /api/live` | Today's forecasts, recent results and the live record |
| `GET /api/teams?season=` | Power rankings |
| `GET /api/teams/{team}?season=` | One team's game-by-game ratings and upcoming games |
| `GET /api/calibration` | Forecast chance vs. actual win rate, past and live |
| `GET /api/seasons`, `GET /api/games?date=` | Past seasons and each day's games |
| `GET /api/model-performance` | Backtest report and model settings |
| `GET /api/players`, `GET /api/players/{id}` | Player averages, game logs and careers |
| `GET /api/matchups/{game_id}` | Players in a past game and their pregame history |

## Limitations

- No injuries, lineups or travel. Rest only covers back-to-backs.
- Past-season forecasts are rebuilt from today's records, not saved at the time. That's what
  the live record is for.
- Player-points projections ([results](backend/PLAYER_POINTS_RESULTS.md)) assume the player plays.
- Neutral-site games need an entry in `backend/neutral_sites.json` before they're played.

More detail: [model documentation](backend/README.md).

---

© 2026 Adonaye Woldegebriel. All rights reserved. Not affiliated with the NBA.
