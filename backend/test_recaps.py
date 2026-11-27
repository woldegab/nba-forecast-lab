from datetime import datetime, timezone
import unittest

from previews import QuotaError
from recaps import check, recap_facts, template, update, write_recap
from test_previews import ROWS, row


class FakeClient:
    model = "fake"

    def __init__(self, *drafts):
        self.drafts, self.calls = list(drafts), 0

    def ask(self, text, schema, **kwargs):
        self.calls += 1
        draft = self.drafts.pop(0)
        if isinstance(draft, Exception):
            raise draft
        return draft


# Nov 25: BOS (60%) won at MIA 95-90, so the model was right.
RIGHT = recap_facts(ROWS[2], ROWS)
# Nov 21: MIA (45%) won at NYK 101-99, an upset.
UPSET = recap_facts(ROWS[1], ROWS)
NOW = datetime(2026, 11, 26, 15, 0, tzinfo=timezone.utc)


class FactTests(unittest.TestCase):
    def test_result_facts(self):
        self.assertEqual((RIGHT["winner"], RIGHT["model_correct"], RIGHT["upset"]), ("away", True, False))
        self.assertEqual((UPSET["winner"], UPSET["model_correct"], UPSET["upset"]), ("away", False, True))
        self.assertEqual(RIGHT["final"], dict(home=90, away=95))


class CheckTests(unittest.TestCase):
    def test_good_recaps_pass(self):
        self.assertEqual(check(dict(recap="The Celtics beat the Heat 95-90 in Miami. The model gave Boston a 60% "
                                          "chance, and the pick held."), RIGHT), [])
        self.assertEqual(check(dict(recap="The Heat stunned the Knicks 101-99. The model had given Miami only a 45% "
                                          "chance, so this was an upset."), UPSET), [])

    def test_wrong_score_fails(self):
        problems = check(dict(recap="The Celtics beat the Heat 98-90. The model gave Boston a 60% chance and was right."), RIGHT)
        self.assertTrue(any("not the final score" in p or "numbers not in the facts" in p for p in problems))

    def test_loser_first_score_fails(self):
        problems = check(dict(recap="The Celtics beat the Heat 90-95. The model gave Boston a 60% chance and was right."), RIGHT)
        self.assertIn("final score written loser-first", problems)

    def test_swapped_winner_fails(self):
        problems = check(dict(recap="The Heat beat the Celtics 95-90 at home. The model gave Boston a 60% chance."), RIGHT)
        self.assertIn("says the loser won", problems)

    def test_cannot_claim_right_when_wrong(self):
        problems = check(dict(recap="The Heat beat the Knicks 101-99, and the model called it with a 45% chance."), UPSET)
        self.assertIn("says the model was right, but it missed", problems)

    def test_cannot_call_expected_win_an_upset(self):
        problems = check(dict(recap="The Celtics beat the Heat 95-90 in a stunning upset. The model gave Boston a 60% chance."), RIGHT)
        self.assertTrue(any("but the model's pick won" in p for p in problems))

    def test_templates_always_pass(self):
        for game in ROWS + [row("7", "2026-11-25", "NYK", "BOS", 0.5, 100, 101)]:
            if game["home_score"] == "":
                continue
            facts = recap_facts(game, ROWS)
            self.assertEqual(check(template(facts), facts), [], game["game_id"])


class WriteTests(unittest.TestCase):
    def test_falls_back_after_two_bad_tries(self):
        bad = dict(recap="The Heat beat the Celtics 95-90 at home. The model gave Boston a 60% chance.")
        recap, problems = write_recap(RIGHT, FakeClient(bad, bad))
        self.assertEqual(recap["source"], "template")
        self.assertTrue(problems)

    def test_only_recent_live_games_and_never_rewrites(self):
        good = dict(recap="The Celtics beat the Heat 95-90 in Miami. The model gave Boston a 60% chance, and the pick held.")
        saved, _ = update(ROWS, {}, NOW, FakeClient(good))
        self.assertEqual(list(saved), ["3"])          # Nov 20 and 21 are older than 3 days
        again, _ = update(ROWS, saved, NOW, FakeClient())
        self.assertEqual(again, saved)

    def test_quota_switches_to_templates(self):
        saved, notes = update(ROWS, {}, NOW, FakeClient(QuotaError("limit")))
        self.assertEqual(saved["3"]["source"], "template")
        self.assertTrue(notes)


if __name__ == "__main__":
    unittest.main()
