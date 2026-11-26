from pathlib import Path
import sqlite3
import tempfile
import unittest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from import_players import normalize, store
import import_careers
from player_api import player_router


class PlayerTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.db = Path(self.temp.name) / 'nba.sqlite3'
        self.rows = [dict(SEASON_ID='22025', GAME_ID=str(i), PLAYER_ID=1,
            GAME_DATE=f'2026-01-{i:02}', PLAYER_NAME='Example Player', TEAM_ABBREVIATION='BOS',
            MATCHUP='BOS vs. NYK', WL='W', MIN=30, PTS=i, REB=5, AST=4) for i in range(1, 13)]
        store(normalize(self.rows, '2025-26'), self.db)
        app = FastAPI()
        app.include_router(player_router(self.db, Path(self.temp.name) / 'current.sqlite3'))
        self.client = TestClient(app)
        self.addCleanup(self.client.close)

    def test_latest_ten_and_summary_agree(self):
        detail = self.client.get('/api/players/1?season=2025-26').json()
        self.assertEqual([g['points'] for g in detail['games']], list(range(12,2,-1)))
        self.assertEqual(detail['averages']['points'], 7.5)
        summary = self.client.get('/api/players').json()['players'][0]
        self.assertEqual(summary['points'], detail['averages']['points'])
        self.assertEqual(summary['sample_games'], 10)

    def test_player_windows_match_list_and_detail(self):
        for window, count, average in [('5',5,10),('10',10,7.5),('season',12,6.5)]:
            detail = self.client.get(f'/api/players/1?season=2025-26&window={window}').json()
            summary = self.client.get(f'/api/players?window={window}').json()['players'][0]
            self.assertEqual(detail['sample_games'],count)
            self.assertEqual(detail['averages']['points'],average)
            self.assertEqual(summary['points'],average)
        self.assertEqual(self.client.get('/api/players?window=100').status_code,422)

    def test_reimport_does_not_duplicate(self):
        store(normalize(self.rows, '2025-26'), self.db)
        with sqlite3.connect(self.db) as db:
            self.assertEqual(db.execute('SELECT COUNT(*) FROM player_games').fetchone()[0],12)

    def test_small_sample_and_historical_team(self):
        row = dict(self.rows[0], PLAYER_ID=2, TEAM_ABBREVIATION='LAL', PTS=25)
        store(normalize([row], '2025-26'), self.db)
        result = self.client.get('/api/players/2?season=2025-26').json()
        self.assertEqual(result['sample_games'],1)
        self.assertEqual(result['averages']['points'],25)
        self.assertEqual(result['team'],'LAL')

    def test_invalid_import(self):
        for change in [dict(SEASON_ID='22024'), dict(PTS=-1), dict(MIN=float('nan'))]:
            with self.assertRaises(ValueError):
                normalize([dict(self.rows[0], **change)], '2025-26')
        with self.assertRaises(ValueError):
            normalize([self.rows[0],self.rows[0]], '2025-26')

    def add_matchup(self, game_id='10', date='2026-01-10'):
        with sqlite3.connect(self.db) as db:
            db.execute('CREATE TABLE IF NOT EXISTS games (game_id TEXT, season TEXT, game_date TEXT, home_team TEXT, away_team TEXT)')
            db.execute('INSERT INTO games VALUES (?,?,?,?,?)', (game_id,'2025-26',date,'BOS','NYK'))

    def test_pregame_windows_and_cutoff(self):
        self.add_matchup()
        base = '/api/matchups/10/players/1'
        all_games = self.client.get(base+'?window=season').json()
        self.assertEqual(all_games['sample_games'], 9)
        self.assertTrue(all(g['game_date'] < '2026-01-10' for g in all_games['games']))
        self.assertEqual(all_games['opponent_sample_games'], 9)
        recent = self.client.get(base+'?window=5').json()
        self.assertEqual([g['points'] for g in recent['games']], [9,8,7,6,5])
        self.assertEqual(recent['averages']['points'],7)
        self.assertEqual(recent['opponent_sample_games'],9)
        self.assertEqual(self.client.get(base+'?window=30').status_code,422)
        # Changing selected-game and future outcomes cannot affect the analysis.
        with sqlite3.connect(self.db) as db:
            db.execute("UPDATE player_games SET points=999 WHERE game_date>='2026-01-10'")
        changed = self.client.get(base+'?window=season').json()
        self.assertEqual(changed.pop('actual_points'), 999)
        self.assertEqual(all_games.pop('actual_points'), 10)
        self.assertEqual(changed, all_games)

    def test_opening_game_has_missing_not_zero_averages(self):
        self.add_matchup('1','2026-01-01')
        result = self.client.get('/api/matchups/1/players/1').json()
        self.assertEqual(result['sample_games'],0)
        self.assertIsNone(result['averages']['points'])
        self.assertEqual(result['opponent_games'],[])

    def test_participants_do_not_expose_selected_game_statistics(self):
        self.add_matchup()
        result = self.client.get('/api/matchups/10').json()
        self.assertEqual(result['players'],[dict(player_id=1,name='Example Player',team='BOS')])
        self.assertNotIn('home_score',result['game'])
        self.assertEqual(self.client.get('/api/matchups/10/players/99').status_code,404)

    def test_missing_player_or_season(self):
        self.assertEqual(self.client.get('/api/players/999?season=2025-26').status_code,404)
        self.assertEqual(self.client.get('/api/players?season=2000-01').status_code,404)


def career_data(rows, career):
    # Same shape as PlayerCareerStats.get_normalized_dict() (checked against player 2544).
    keys = ('SEASON_ID', 'TEAM_ABBREVIATION', 'GP', 'MIN', 'PTS', 'REB', 'AST')
    return dict(SeasonTotalsRegularSeason=[dict(zip(keys, r), PLAYER_ID=1) for r in rows],
                CareerTotalsRegularSeason=[dict(zip(keys[2:], career), PLAYER_ID=1)] if career else [])


class CareerTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        folder = Path(self.temp.name)
        self.archive, self.current = folder / 'nba.sqlite3', folder / 'current.sqlite3'
        row = lambda season, game, pts: dict(SEASON_ID='2' + season[:4], GAME_ID=game, PLAYER_ID=1,
            GAME_DATE='2026-01-01' if season == '2025-26' else '2026-11-01', PLAYER_NAME='Example Player',
            TEAM_ABBREVIATION='BOS', MATCHUP='BOS vs. NYK', WL='W', MIN=30, PTS=pts, REB=5, AST=4)
        store(normalize([row('2025-26', 'a', 10)], '2025-26'), self.archive)
        store(normalize([row('2026-27', 'b', 20)], '2026-27'), self.archive)    # also imported into the archive
        store(normalize([row('2026-27', 'b', 22)], '2026-27'), self.current)    # newer copy wins
        app = FastAPI()
        app.include_router(player_router(self.archive, self.current))
        self.client = TestClient(app)
        self.addCleanup(self.client.close)

    def test_traded_season_uses_total_row(self):
        seasons, career = import_careers.parse_career(career_data([
            ('2003-04', 'CLE', 79, 3127, 1654, 432, 465),
            ('2004-05', 'AAA', 20, 600, 200, 50, 40), ('2004-05', 'BBB', 30, 900, 300, 60, 50),
            ('2004-05', 'TOT', 50, 1500, 500, 110, 90)], (129, 4627, 2154, 542, 555)))
        self.assertEqual(seasons[1], ('2004-05', 'AAA/BBB', 50, 1500.0, 500, 110, 90))
        self.assertEqual(career, (129, 4627.0, 2154, 542, 555))

    def test_rejects_ambiguous_seasons(self):
        with self.assertRaises(ValueError):
            import_careers.parse_career(career_data([('2004-05', 'AAA', 1, 1, 1, 1, 1),
                                                     ('2004-05', 'BBB', 1, 1, 1, 1, 1)], None))

    def test_current_file_wins_and_seasons_are_not_doubled(self):
        body = self.client.get('/api/players').json()
        self.assertEqual(body['seasons'], ['2026-27', '2025-26'])
        detail = self.client.get('/api/players/1?season=2026-27').json()
        self.assertEqual([g['points'] for g in detail['games']], [22])
        self.assertIsNone(detail['career'])

    def test_detail_includes_career_per_game(self):
        seasons, career = import_careers.parse_career(career_data([
            ('2024-25', 'BOS', 10, 300, 200, 50, 40), ('2025-26', 'BOS', 20, 600, 300, 100, 60)],
            (30, 900, 500, 150, 100)))
        import_careers.store(self.current, 1, seasons, career, '2026-11-26T15:00:00+00:00')
        career_body = self.client.get('/api/players/1?season=2026-27').json()['career']
        self.assertEqual((career_body['games'], career_body['first_season'], career_body['last_season']), (30, '2024-25', '2025-26'))
        self.assertAlmostEqual(career_body['averages']['points'], 500 / 30)
        self.assertEqual([s['season'] for s in career_body['seasons']], ['2025-26', '2024-25'])
        self.assertEqual(career_body['seasons'][0]['points'], 15)

    def test_season_players_reads_both_files(self):
        self.assertEqual(import_careers.season_players('2026-27', [self.archive, self.current]), [1])


if __name__ == '__main__':
    unittest.main()
