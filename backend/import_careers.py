"""Import career regular-season stats for every player in a season, from stats.nba.com.

Writes season-by-season totals and career totals to the small current-season
database (data/current.sqlite3), which the player pages read alongside the archive.
About one request per player, spaced out so NBA.com doesn't throttle the run:
roughly 10-20 minutes for a full season's players. Run from a home connection;
stats.nba.com blocks cloud servers such as GitHub Actions.
"""
import argparse
from datetime import datetime, timezone
from pathlib import Path
import sqlite3
import sys
import time

from import_games import DEFAULT_DB

CURRENT_DB = Path(__file__).parent / 'data' / 'current.sqlite3'
STATS = ('GP', 'MIN', 'PTS', 'REB', 'AST')


def parse_career(data):
    """(season rows, career row) from PlayerCareerStats.get_normalized_dict().

    A player traded mid-season has one row per team plus a 'TOT' row; the TOT row
    is used for that season and the teams are listed in the order played.
    """
    by_season = {}
    for row in data['SeasonTotalsRegularSeason']:
        by_season.setdefault(row['SEASON_ID'], []).append(row)
    seasons = []
    for season, rows in by_season.items():
        totals = [r for r in rows if r['TEAM_ABBREVIATION'] == 'TOT']
        if len(totals) > 1 or (not totals and len(rows) > 1):
            raise ValueError(f'Season {season}: expected one row or a TOT row')
        total = totals[0] if totals else rows[0]
        teams = [r['TEAM_ABBREVIATION'] for r in rows if r['TEAM_ABBREVIATION'] != 'TOT']
        seasons.append((season, '/'.join(teams), *[_count(total, f) for f in STATS]))
    career_rows = data['CareerTotalsRegularSeason']
    if len(career_rows) > 1:
        raise ValueError('Expected one career row')
    career = tuple(_count(career_rows[0], f) for f in STATS) if career_rows else None
    return sorted(seasons), career


def _count(row, field):
    value = row[field]
    if value is None:
        return 0
    if isinstance(value, bool) or not isinstance(value, (int, float)) or value < 0:
        raise ValueError(f'Invalid {field}: {value!r}')
    return float(value) if field == 'MIN' else int(value)


def store(database, player_id, seasons, career, updated_at):
    with sqlite3.connect(database) as db:
        db.execute('''CREATE TABLE IF NOT EXISTS player_seasons (
            player_id INTEGER, season TEXT, teams TEXT, gp INTEGER, minutes REAL,
            points INTEGER, rebounds INTEGER, assists INTEGER, PRIMARY KEY(player_id, season))''')
        db.execute('''CREATE TABLE IF NOT EXISTS player_careers (
            player_id INTEGER PRIMARY KEY, gp INTEGER, minutes REAL, points INTEGER,
            rebounds INTEGER, assists INTEGER, first_season TEXT, last_season TEXT, updated_at TEXT)''')
        db.execute('DELETE FROM player_seasons WHERE player_id=?', (player_id,))
        db.executemany('INSERT INTO player_seasons VALUES (?,?,?,?,?,?,?,?)',
                       [(player_id, *row) for row in seasons])
        if career:
            db.execute('''INSERT INTO player_careers VALUES (?,?,?,?,?,?,?,?,?)
                ON CONFLICT(player_id) DO UPDATE SET gp=excluded.gp, minutes=excluded.minutes,
                points=excluded.points, rebounds=excluded.rebounds, assists=excluded.assists,
                first_season=excluded.first_season, last_season=excluded.last_season,
                updated_at=excluded.updated_at''',
                (player_id, *career, seasons[0][0], seasons[-1][0], updated_at))


def season_players(season, databases):
    ids = set()
    for database in databases:
        if not Path(database).exists():
            continue
        with sqlite3.connect(f'{Path(database).resolve().as_uri()}?mode=ro', uri=True) as db:
            if db.execute("SELECT 1 FROM sqlite_master WHERE name='player_games'").fetchone():
                ids.update(r[0] for r in db.execute('SELECT DISTINCT player_id FROM player_games WHERE season=?', (season,)))
    return sorted(ids)


def fetch(player_id, attempts=3, timeout=30):
    from nba_api.stats.endpoints import playercareerstats
    for attempt in range(attempts):
        try:
            return playercareerstats.PlayerCareerStats(player_id=player_id, timeout=timeout).get_normalized_dict()
        except Exception as error:  # requests, timeout and JSON errors from nba_api
            if attempt + 1 == attempts:
                raise RuntimeError(f'{type(error).__name__}: {error}') from error
            time.sleep(5 * (2 ** attempt))


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument('--season', required=True, help='Import careers for players who appeared in this season')
    parser.add_argument('--database', type=Path, default=CURRENT_DB)
    parser.add_argument('--delay', type=float, default=0.8, help='Seconds between requests')
    parser.add_argument('--limit', type=int, help='Only the first N players (for testing)')
    args = parser.parse_args(argv)
    players = season_players(args.season, [DEFAULT_DB, args.database])[:args.limit]
    if not players:
        print(f'No players found for {args.season}. Run import_players.py first.', file=sys.stderr)
        return 1
    args.database.parent.mkdir(parents=True, exist_ok=True)
    updated_at = datetime.now(timezone.utc).isoformat(timespec='seconds')
    failures = []
    for number, player_id in enumerate(players, 1):
        try:
            seasons, career = parse_career(fetch(player_id))
            if seasons:
                store(args.database, player_id, seasons, career, updated_at)
        except (RuntimeError, ValueError, KeyError, TypeError) as error:
            failures.append(player_id)
            print(f'Player {player_id} failed: {error}', file=sys.stderr)
        if number % 50 == 0:
            print(f'{number} of {len(players)} players done')
        time.sleep(args.delay)
    print(f'Imported careers for {len(players) - len(failures)} of {len(players)} players.')
    # A few failures are normal (retired or two-way players); many means NBA.com is refusing us.
    return 1 if len(failures) > max(5, len(players) // 10) else 0


if __name__ == '__main__':
    raise SystemExit(main())
