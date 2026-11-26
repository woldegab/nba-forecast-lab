import unittest

from evaluate_elo import backtest, metrics


def game(game_id, date, home_score=110, away_score=100, neutral=0):
    return dict(game_id=game_id, game_date=date, season='2023-24', home_team_id=1,
                away_team_id=2, home_team='AAA', away_team='BBB',
                home_score=home_score, away_score=away_score, neutral_site=neutral)


class EloTests(unittest.TestCase):
    def test_current_and_future_results_do_not_change_pregame_forecast(self):
        first = game('1', '2023-10-24')
        second = game('2', '2023-10-25')
        original = backtest([first, second])
        second['home_score'] = 80
        changed = backtest([first, second])
        self.assertEqual([r['home_win_probability'] for r in original],
                         [r['home_win_probability'] for r in changed])
        self.assertEqual(backtest([first])[0]['home_win_probability'], original[0]['home_win_probability'])

    def test_previous_results_affect_next_date(self):
        rows = backtest([game('1', '2023-10-24'), game('2', '2023-10-25')])
        self.assertGreater(rows[1]['home_win_probability'], rows[0]['home_win_probability'])

    def test_same_day_results_are_not_used(self):
        rows = backtest([game('1', '2023-10-24'), game('2', '2023-10-24')])
        self.assertEqual(rows[0]['home_win_probability'], rows[1]['home_win_probability'])

    def test_neutral_equal_teams_are_even(self):
        self.assertEqual(backtest([game('1', '2023-10-24', neutral=1)])[0]['home_win_probability'], 0.5)

    def test_offseason_regression(self):
        second = game('2', '2024-10-24')
        second['season'] = '2024-25'
        row = backtest([game('1', '2023-10-24', neutral=1), second])[1]
        self.assertEqual(row['home_rating'], 1507.5)
        self.assertEqual(row['away_rating'], 1492.5)

    def test_probability_metrics(self):
        result = metrics([0.5, 0.5], [0, 1])
        self.assertEqual(result['brier'], 0.25)
        self.assertAlmostEqual(result['log_loss'], 0.69314718)


if __name__ == '__main__':
    unittest.main()


class ExtensionTests(unittest.TestCase):
    def game(self, game_id, day, home, away, home_score, away_score):
        return dict(game_id=game_id, season="2024-25", game_date=day, home_team_id=home, home_team=str(home),
                    away_team_id=away, away_team=str(away), home_score=home_score, away_score=away_score, neutral_site=0)

    def test_defaults_ignore_margin_and_rest(self):
        from evaluate_elo import PARAMETERS, backtest
        close = [self.game("1", "2024-11-01", 1, 2, 101, 100), self.game("2", "2024-11-02", 1, 3, 100, 90)]
        blowout = [self.game("1", "2024-11-01", 1, 2, 140, 100), self.game("2", "2024-11-02", 1, 3, 100, 90)]
        self.assertEqual(backtest(close, PARAMETERS)[1]["home_win_probability"],
                         backtest(blowout, PARAMETERS)[1]["home_win_probability"])

    def test_margin_of_victory_rewards_blowouts_more(self):
        from evaluate_elo import PARAMETERS, backtest
        p = dict(PARAMETERS, margin_of_victory=True)
        close, blowout = {}, {}
        backtest([self.game("1", "2024-11-01", 1, 2, 101, 100)], p, close)
        backtest([self.game("1", "2024-11-01", 1, 2, 140, 100)], p, blowout)
        self.assertGreater(blowout[1], close[1])
        self.assertAlmostEqual(close[1] - 1500, 1500 - close[2])  # points move, none created

    def test_margin_multiplier_shrinks_for_favorites(self):
        from evaluate_elo import margin_multiplier
        self.assertGreater(margin_multiplier(20, 0), margin_multiplier(5, 0))
        self.assertLess(margin_multiplier(20, 200), margin_multiplier(20, 0))

    def test_back_to_back_penalty_only_after_consecutive_days(self):
        from evaluate_elo import PARAMETERS, backtest
        p = dict(PARAMETERS, back_to_back=30.0)
        games = [self.game("1", "2024-11-01", 1, 2, 100, 90), self.game("2", "2024-11-01", 3, 4, 100, 90),
                 self.game("3", "2024-11-02", 1, 3, 100, 90),   # team 1 tired, team 3 tired
                 self.game("4", "2024-11-02", 5, 2, 100, 90),   # team 2 tired, 5 rested
                 self.game("5", "2024-11-04", 6, 5, 100, 90)]   # one day off: nobody tired
        rows = {r["game_id"]: r for r in backtest(games, p)}
        plain = {r["game_id"]: r for r in backtest(games, PARAMETERS)}
        self.assertAlmostEqual(rows["3"]["home_win_probability"], plain["3"]["home_win_probability"])
        self.assertGreater(rows["4"]["home_win_probability"], plain["4"]["home_win_probability"])
        from evaluate_elo import played_yesterday
        self.assertTrue(played_yesterday(5, "2024-11-03", {5: "2024-11-02"}))
        self.assertFalse(played_yesterday(5, "2024-11-04", {5: "2024-11-02"}))
        self.assertFalse(played_yesterday(6, "2024-11-04", {}))


class ExperimentTests(unittest.TestCase):
    def test_bootstrap_interval_contains_the_difference(self):
        from experiment_model import bootstrap_difference
        outcomes = [1, 0, 1, 1, 0, 1, 0, 1] * 25
        current = [0.6] * len(outcomes)
        chosen = [0.65 if y else 0.55 for y in outcomes]
        difference, low, high = bootstrap_difference(current, chosen, outcomes, resamples=500)
        self.assertLess(difference, 0)
        self.assertLessEqual(low, difference)
        self.assertLessEqual(difference, high)
