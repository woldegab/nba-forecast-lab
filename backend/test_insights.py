import unittest

from insights import calibration, power_rankings, team_histories


def game(game_id, date, home, away, p, home_score=None, away_score=None, home_rating=1500.0, away_rating=1500.0):
    return dict(game_id=game_id, date=date, home_team=home, away_team=away, home_win_probability=p,
                home_rating=home_rating, away_rating=away_rating, home_score=home_score, away_score=away_score)


class InsightTests(unittest.TestCase):
    def test_rating_after_game_is_elo_update(self):
        history = team_histories([game('1', '2026-11-01', 'AAA', 'BBB', 0.6, 100, 90)], k=20)
        self.assertEqual(history['AAA'][0]['rating'], round(1500 + 20 * (1 - 0.6), 1))
        self.assertEqual(history['BBB'][0]['rating'], round(1500 + 20 * (0 - 0.4), 1))
        self.assertEqual((history['BBB'][0]['result'], history['BBB'][0]['score'], history['BBB'][0]['home']), ('L', '90-100', False))

    def test_unplayed_games_are_skipped(self):
        self.assertEqual(team_histories([game('1', '2026-11-01', 'AAA', 'BBB', 0.6)], k=20), {})

    def test_rankings_order_record_and_teams_without_games(self):
        history = team_histories([game('1', '2026-11-01', 'AAA', 'BBB', 0.5, 100, 90),
                                  game('2', '2026-11-02', 'BBB', 'AAA', 0.5, 80, 95)], k=20)
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
