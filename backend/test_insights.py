import unittest

from insights import calibration, power_rankings, team_histories


def game(game_id, date, home, away, p, home_score=None, away_score=None, home_rating=1500.0, away_rating=1500.0):
    return dict(game_id=game_id, date=date, home_team=home, away_team=away, home_win_probability=p,
                home_rating=home_rating, away_rating=away_rating, home_score=home_score, away_score=away_score)


class InsightTests(unittest.TestCase):
    def test_rating_after_game_is_elo_update(self):
        history = team_histories([game('1', '2026-11-01', 'AAA', 'BBB', 0.6, 100, 90)], 20)
        self.assertEqual(history['AAA'][0]['rating'], round(1500 + 20 * (1 - 0.6), 1))
        self.assertEqual(history['BBB'][0]['rating'], round(1500 + 20 * (0 - 0.4), 1))
        self.assertEqual((history['BBB'][0]['result'], history['BBB'][0]['score'], history['BBB'][0]['home']), ('L', '90-100', False))

    def test_unplayed_games_are_skipped(self):
        self.assertEqual(team_histories([game('1', '2026-11-01', 'AAA', 'BBB', 0.6)], 20), {})

    def test_rankings_order_record_and_teams_without_games(self):
        history = team_histories([game('1', '2026-11-01', 'AAA', 'BBB', 0.5, 100, 90),
                                  game('2', '2026-11-02', 'BBB', 'AAA', 0.5, 80, 95)], 20)
        rows = power_rankings(history, {'AAA': 1500.0, 'BBB': 1500.0, 'CCC': 1510.0})
        self.assertEqual([r['team'] for r in rows], ['AAA', 'CCC', 'BBB'])
        self.assertEqual((rows[0]['wins'], rows[0]['losses'], rows[0]['last10'], rows[0]['rank']), (2, 0, '2-0', 1))
        self.assertEqual((rows[1]['wins'], rows[1]['trend']), (0, []))

    def test_calibration_buckets_use_the_favorite(self):
        games = [game('1', 'd', 'AAA', 'BBB', 0.75, 100, 90),    # favorite (home) won
                 game('2', 'd', 'AAA', 'BBB', 0.25, 100, 90),    # favorite (away, 75%) lost
                 game('3', 'd', 'AAA', 'BBB', 0.55, 90, 100),    # favorite (home) lost
                 game('4', 'd', 'AAA', 'BBB', 0.95)]             # not played yet
        buckets = {(b['low'], b['high']): b for b in calibration(games)}
        self.assertEqual(buckets[(0.7, 0.8)], dict(low=0.7, high=0.8, games=2, forecast=0.75, actual=0.5))
        self.assertEqual(buckets[(0.5, 0.6)]['actual'], 0.0)
        self.assertEqual(buckets[(0.9, 1.0)]['games'], 0)


if __name__ == '__main__':
    unittest.main()


class ModelChangeTests(unittest.TestCase):
    def test_margin_of_victory_history_matches_backtest(self):
        from evaluate_elo import PARAMETERS, backtest
        raw = [dict(game_id='1', season='x', game_date='2026-11-01', home_team_id=1, home_team='AAA', away_team_id=2,
                    away_team='BBB', home_score=130, away_score=100, neutral_site=0),
               dict(game_id='2', season='x', game_date='2026-11-02', home_team_id=2, home_team='BBB', away_team_id=1,
                    away_team='AAA', home_score=101, away_score=99, neutral_site=0)]
        ratings = {}
        rows = backtest(raw, PARAMETERS, ratings)
        games = [dict(game_id=r['game_id'], date=r['game_date'], home_team=r['home_team'], away_team=r['away_team'],
                      home_rating=r['home_rating'], away_rating=r['away_rating'],
                      home_win_probability=r['home_win_probability'], home_score=r['home_score'],
                      away_score=r['away_score']) for r in rows]
        history = team_histories(games, PARAMETERS)
        self.assertAlmostEqual(history['AAA'][-1]['rating'], ratings[1], places=1)
        self.assertAlmostEqual(history['AAA'][1]['rating_before'], history['AAA'][0]['rating'], places=1)

    def test_games_forecast_before_switch_use_old_model(self):
        from evaluate_elo import ORIGINAL_PARAMETERS, PARAMETERS
        g = game('1', '2026-11-01', 'AAA', 'BBB', 0.6, 130, 100)
        old = team_histories([dict(g, predicted_at_utc='2026-11-01T15:00:00+00:00')], PARAMETERS,
                             earlier=ORIGINAL_PARAMETERS, since='2026-11-26T22:00:00+00:00')
        self.assertEqual(old['AAA'][0]['rating'], round(1500 + 20 * 0.4, 1))
        new = team_histories([dict(g, predicted_at_utc='2026-11-27T15:00:00+00:00')], PARAMETERS,
                             earlier=ORIGINAL_PARAMETERS, since='2026-11-26T22:00:00+00:00')
        self.assertGreater(new['AAA'][0]['rating'], old['AAA'][0]['rating'])  # 30-point win counts more
