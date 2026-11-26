#!/bin/zsh
# Refreshes player stats from your Mac, then pushes them so the site redeploys.
# stats.nba.com blocks cloud servers (GitHub Actions, Render), so this runs at home.
#   Every run: this season's player game logs.
#   Mondays, the first run, or with --careers: career stats for this season's players (10-20 min).
set -euo pipefail
cd "${0:A:h}/.."
PY=backend/.venv/bin/python
DB=backend/data/current.sqlite3

month=$(date +%m); year=$(date +%Y)
if (( 10#$month >= 10 )); then start=$year; else start=$((year - 1)); fi
season="$start-$(printf %02d $(( (start + 1) % 100 )))"
echo "=== $(date '+%Y-%m-%d %H:%M') refreshing $season"

git pull --rebase --autostash
$PY backend/import_players.py --season "$season" --database "$DB"

has_careers=$($PY -c "import sqlite3; print(bool(sqlite3.connect('$DB').execute(\"SELECT 1 FROM sqlite_master WHERE name='player_careers'\").fetchone()))")
if [[ "${1:-}" == "--careers" || "$(date +%u)" == 1 || "$has_careers" == False ]]; then
  $PY backend/import_careers.py --season "$season" --database "$DB"
fi

git add "$DB"
if git diff --cached --quiet; then
  echo "No changes."
else
  git commit -m "Player stats for $(date +%Y-%m-%d)"
  git push
fi
