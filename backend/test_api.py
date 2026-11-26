import csv
import json
from pathlib import Path
import tempfile
import unittest

from fastapi.testclient import TestClient
from api import create_app


class ApiTests(unittest.TestCase):
    def setUp(self):
        self.folder = tempfile.TemporaryDirectory()
        self.addCleanup(self.folder.cleanup)
        self.path = Path(self.folder.name)
        self.report = dict(generated_at='2026-09-20T00:00:00Z', warmup_season='2023-24',
            test_season='2025-26', coverage={'2025-26': {'games': 1}},
            results={'2025-26': {'elo': {'accuracy': 1.0}}})
        (self.path / 'report.json').write_text(json.dumps(self.report))
        self.row = dict(game_id='example', season='2025-26', game_date='2026-01-15',
            home_team='AAA', away_team='BBB', neutral_site=1, home_rating=1520,
            away_rating=1480, home_win_probability=0.6, actual_home_win=1,
            home_score=110, away_score=100)
        self.write_row()

    def write_row(self):
        with (self.path / 'predictions.csv').open('w', newline='') as file:
            writer = csv.DictWriter(file, fieldnames=self.row.keys())
            writer.writeheader()
            writer.writerow(self.row)

    def test_game_response_preserves_prediction_and_result(self):
        with TestClient(create_app(self.path)) as client:
            response = client.get('/api/games?date=2026-01-15')
            self.assertEqual(response.status_code, 200)
            game = response.json()['games'][0]
            self.assertEqual(game['home_win_probability'], 0.6)
            self.assertEqual(game['away_win_probability'], 0.4)
            self.assertTrue(game['neutral_site'])
            self.assertTrue(game['correct'])
            self.assertEqual(game['predicted_winner'], 'AAA')
            self.assertEqual(game['home_score'], 110)

    def test_metadata_and_metrics_match_artifact(self):
        with TestClient(create_app(self.path)) as client:
            season = client.get('/api/seasons').json()['seasons'][0]
            self.assertEqual(season['dates'], ['2026-01-15'])
            self.assertEqual(season['phase'], 'Initial test')
            self.assertEqual(client.get('/api/model-performance').json(), self.report)

    def test_empty_date_and_bad_date(self):
        with TestClient(create_app(self.path)) as client:
            self.assertEqual(client.get('/api/games?date=2026-01-16').json()['games'], [])
            self.assertEqual(client.get('/api/games?date=invalid').status_code, 422)
            self.assertEqual(client.get('/api/games').status_code, 422)

    def test_missing_artifacts_return_actionable_error(self):
        with TestClient(create_app(self.path / 'missing')) as client:
            response = client.get('/api/seasons')
            self.assertEqual(response.status_code, 503)
            self.assertIn('evaluate_elo.py', response.json()['detail'])

    def test_invalid_predictions_are_not_served(self):
        self.row['home_win_probability'] = 'nan'
        self.write_row()
        with TestClient(create_app(self.path)) as client:
            self.assertEqual(client.get('/api/seasons').status_code, 503)

    def test_mismatched_coverage_is_not_served(self):
        self.report['coverage']['2025-26']['games'] = 2
        (self.path / 'report.json').write_text(json.dumps(self.report))
        with TestClient(create_app(self.path)) as client:
            self.assertEqual(client.get('/api/seasons').status_code, 503)


class LiveAndStaticTests(unittest.TestCase):
    def setUp(self):
        folder = tempfile.TemporaryDirectory()
        self.addCleanup(folder.cleanup)
        self.path = Path(folder.name)
        self.live = self.path / 'live'
        self.live.mkdir()
        (self.live / 'summary.json').write_text(json.dumps(dict(season='2026-27', live=dict(games=1))))
        fields = ['game_id', 'game_date', 'tipoff_utc', 'home_team_id', 'home_team', 'away_team_id',
                  'away_team', 'neutral_site', 'home_rating', 'away_rating', 'home_win_probability',
                  'predicted_at_utc', 'mode', 'home_score', 'away_score', 'actual_home_win']
        rows = [['1', '2026-11-25', '2026-11-26T00:30:00+00:00', 1, 'AAA', 2, 'BBB', 0, 1550, 1450,
                 0.7, '2026-11-25T15:00:00+00:00', 'live', 99, 100, 0],
                ['2', '2026-11-26', '2026-11-27T00:30:00+00:00', 2, 'BBB', 1, 'AAA', 0, 1450, 1550,
                 0.35, '2026-11-26T15:00:00+00:00', 'live', '', '', '']]
        with (self.live / 'predictions_2026-27.csv').open('w', newline='') as file:
            writer = csv.writer(file)
            writer.writerow(fields)
            writer.writerows(rows)
        self.static = self.path / 'dist'
        (self.static / 'assets').mkdir(parents=True)
        (self.static / 'index.html').write_text('<html>app</html>')
        (self.static / 'assets' / 'app.js').write_text('console.log(1)')

    def client(self, live=None):
        return TestClient(create_app(self.path / 'missing', live or self.live, self.static))

    def test_live_splits_upcoming_and_finished(self):
        with self.client() as client:
            body = client.get('/api/live').json()
            self.assertEqual([g['game_id'] for g in body['upcoming']], ['2'])
            recent = body['recent'][0]
            self.assertFalse(recent['correct'])
            self.assertEqual(recent['actual_winner'], 'BBB')
            self.assertIsNone(body['upcoming'][0]['correct'])

    def test_live_days_and_single_day(self):
        with self.client() as client:
            days = client.get('/api/live/days').json()['days']
            self.assertEqual([d['date'] for d in days], ['2026-11-25', '2026-11-26'])
            self.assertEqual((days[0]['finished'], days[0]['correct']), (1, 0))
            self.assertEqual(days[1]['finished'], 0)
            day = client.get('/api/live/day?date=2026-11-25').json()
            self.assertEqual([g['game_id'] for g in day['games']], ['1'])
            self.assertEqual(client.get('/api/live/day?date=2026-12-25').json()['games'], [])
            self.assertEqual(client.get('/api/live/day?date=nope').status_code, 422)

    def test_model_change_reported_after_switch(self):
        with self.client() as client:
            self.assertIsNone(client.get('/api/live').json()['model_change'])
        (self.live / 'start_ratings.json').write_text(json.dumps(dict(generated_at='2026-11-26T22:00:00+00:00',
            parameters=dict(k=20.0, margin_of_victory=True, back_to_back=50.0),
            ratings={'1': dict(team='AAA', rating=1550.0), '2': dict(team='BBB', rating=1450.0)})))
        with self.client() as client:
            change = client.get('/api/live').json()['model_change']
            self.assertEqual(change['since'], '2026-11-26T22:00:00+00:00')
            self.assertEqual(change['back_to_back'], 50.0)
            self.assertEqual(len(client.get('/api/teams').json()['teams']), 2)

    def test_previews_attached_to_games(self):
        (self.live / 'previews_2026-27.json').write_text(json.dumps({'2': dict(
            headline='AAA at BBB', preview='The model gives the AAA a 65% chance.', source='ai')}))
        with self.client() as client:
            game = client.get('/api/live').json()['upcoming'][0]
            self.assertEqual(game['preview']['source'], 'ai')
            self.assertIsNone(client.get('/api/live/day?date=2026-11-25').json()['games'][0]['preview'])

    def test_missing_live_files_return_503(self):
        with self.client(self.path / 'nothing') as client:
            self.assertEqual(client.get('/api/live').status_code, 503)

    def test_teams_rankings_detail_and_calibration(self):
        (self.live / 'start_ratings.json').write_text(json.dumps(dict(parameters=dict(k=20.0),
            ratings={'1': dict(team='AAA', rating=1550.0), '2': dict(team='BBB', rating=1450.0)})))
        with self.client() as client:
            body = client.get('/api/teams').json()
            self.assertEqual(body['season'], '2026-27')
            self.assertEqual([t['team'] for t in body['teams']], ['AAA', 'BBB'])
            self.assertEqual((body['teams'][0]['wins'], body['teams'][0]['losses']), (0, 1))
            detail = client.get('/api/teams/bbb').json()
            self.assertEqual(detail['games'][0]['result'], 'W')
            self.assertEqual([g['game_id'] for g in detail['upcoming']], ['2'])
            self.assertEqual(client.get('/api/teams/ZZZ').status_code, 404)
            live = client.get('/api/calibration').json()['live']
            self.assertEqual(live['games'], 1)
            self.assertEqual(next(b for b in live['buckets'] if b['low'] == 0.7)['actual'], 0.0)

    def test_link_preview_served_when_generated(self):
        with self.client() as client:
            self.assertEqual(client.get('/og.png').status_code, 404)
        from og_image import render
        render(self.live, self.path / 'missing', self.live / 'og.png')
        with self.client() as client:
            response = client.get('/og.png')
            self.assertEqual((response.status_code, response.headers['content-type']), (200, 'image/png'))
            self.assertEqual(response.content[:8], b'\x89PNG\r\n\x1a\n')

    def test_teams_need_some_forecasts(self):
        with self.client(self.path / 'nothing') as client:
            self.assertEqual(client.get('/api/teams').status_code, 503)
            self.assertEqual(client.get('/api/calibration').status_code, 503)

    def test_serves_built_app_and_spa_routes(self):
        with self.client() as client:
            self.assertEqual(client.get('/').text, '<html>app</html>')
            self.assertEqual(client.get('/live').text, '<html>app</html>')
            self.assertEqual(client.get('/assets/app.js').text, 'console.log(1)')
            self.assertEqual(client.get('/api/unknown').status_code, 404)
            self.assertEqual(client.get('/../secret').text, '<html>app</html>')


if __name__ == '__main__':
    unittest.main()
