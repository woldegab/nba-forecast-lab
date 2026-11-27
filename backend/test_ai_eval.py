from datetime import date
import json
from pathlib import Path
import tempfile
import unittest

import ai_eval
from previews import QuotaError, build_facts, template
from test_previews import GOOD, ROWS


class FakeClient:
    model, prompt_version = "fake", "v3"

    def __init__(self, write=None, ask=None):
        self.writes, self.asks = list(write or []), list(ask or [])

    def write(self, facts):
        draft = self.writes.pop(0) if self.writes else "valid"
        if isinstance(draft, Exception):
            raise draft
        return template(facts) if draft == "valid" else draft

    def ask(self, text, schema, **kwargs):
        answer = self.asks.pop(0)
        if isinstance(answer, Exception):
            raise answer
        return answer


class AgreementTests(unittest.TestCase):
    def test_perfect_and_chance_agreement(self):
        perfect = ai_eval.agreement([("good", "good"), ("bad", "bad")] * 5)
        self.assertEqual((perfect["agreement"], perfect["kappa"]), (1.0, 1.0))
        # Judge always says good: 80% agreement looks high, but kappa shows it's no better than chance.
        lazy = ai_eval.agreement([("good", "good")] * 8 + [("bad", "good")] * 2)
        self.assertAlmostEqual(lazy["agreement"], 0.8)
        self.assertAlmostEqual(lazy["kappa"], 0.0)

    def test_confusion_counts(self):
        stats = ai_eval.agreement([("good", "bad"), ("good", "good"), ("bad", "bad")])
        self.assertEqual(stats["confusion"]["you good, judge bad"], 1)


class LabelAndJudgeTests(unittest.TestCase):
    def setUp(self):
        folder = tempfile.TemporaryDirectory()
        self.addCleanup(folder.cleanup)
        self.dir = Path(folder.name)
        facts = build_facts(ROWS[3], ROWS)
        self.saved = self.dir / "PREVIEW_EVAL.json"
        self.saved.write_text(json.dumps(dict(model="fake", results=[
            dict(game_id=str(i), draft=GOOD, facts=facts) for i in range(3)] + [dict(game_id="x", draft={}, facts=facts)])))

    def test_label_saves_and_resumes(self):
        answers = iter(["g", "", "b", "too dull", "q"])
        ai_eval.label(self.dir, self.saved, ask=lambda _: next(answers), say=lambda *_: None)
        labels = json.loads((self.dir / ai_eval.LABELS).read_text())
        self.assertEqual({k: v["label"] for k, v in labels.items()}, {"0": "good", "1": "bad"})
        answers = iter(["g", ""])
        ai_eval.label(self.dir, self.saved, ask=lambda _: next(answers), say=lambda *_: None)
        self.assertEqual(len(json.loads((self.dir / ai_eval.LABELS).read_text())), 3)

    def test_judge_reports_agreement(self):
        answers = iter(["g", "", "b", "", "g", ""])
        ai_eval.label(self.dir, self.saved, ask=lambda _: next(answers), say=lambda *_: None)
        client = FakeClient(ask=[dict(verdict="good", reason="fine"), dict(verdict="good", reason="fine"),
                                 dict(verdict="good", reason="fine")])
        self.assertEqual(ai_eval.judge(self.dir, client), 0)
        report = (self.dir / "JUDGE_EVAL.md").read_text()
        self.assertIn("| AI judge alone | 67% agreement", report)
        self.assertIn("Rules + judge", report)
        self.assertIn("still disagree", report)


class TextTests(unittest.TestCase):
    def test_preview_text_keeps_final_period(self):
        self.assertEqual(ai_eval.preview_text(dict(headline="A at B", preview="The model likes A.")),
                         "A at B. The model likes A.")
        self.assertEqual(ai_eval.finished("Cut off"), "Cut off.")

    def test_rule_verdict_catches_codes_in_saved_text(self):
        facts = build_facts(ROWS[3], ROWS)
        good = ai_eval.preview_text(GOOD)
        self.assertEqual(ai_eval.rule_verdict(good, facts), "good")
        self.assertEqual(ai_eval.rule_verdict(good.replace("Boston is 2-0", "Boston is W2 at 2-0"), facts), "bad")


class CompareAndWeeklyTests(unittest.TestCase):
    def test_compare_recommends_only_clear_wins(self):
        bad = dict(GOOD, preview=GOOD["preview"].replace("64%", "80%"))
        clients = {"m:v3": FakeClient(write=[bad, bad, bad]), "m:v4": FakeClient(write=["valid"] * 3)}
        with tempfile.TemporaryDirectory() as folder:
            report = ai_eval.compare(Path(folder), ROWS, "key", ["m:v3", "m:v4"], 3, False,
                                     make_client=lambda model, prompt: clients[f"{model}:{prompt}"])
            text = (Path(folder) / "COMPARE.md").read_text()
        self.assertEqual([r["passed"] for r in report], [0, 3])
        self.assertIn("switch to `m:v4`", text)

    def test_weekly_appends_one_entry_per_day(self):
        with tempfile.TemporaryDirectory() as folder:
            for _ in range(2):
                client = FakeClient(ask=[dict(recap="x")] * 3 + [dict(verdict="good", reason="ok")] * 3)
                ai_eval.weekly(Path(folder), ROWS, client, 3, today=date(2026, 11, 30))
            history = json.loads((Path(folder) / ai_eval.HISTORY).read_text())
        self.assertEqual(len(history), 1)
        entry = history[0]
        self.assertEqual(entry["previews"]["passed"], 3)
        self.assertEqual(entry["recaps"]["passed"], 0)          # "x" fails the recap checks
        self.assertEqual(entry["previews"]["judge_good"], 3)

    def test_request_errors_not_counted_as_answers(self):
        summary = ai_eval.summarize([dict(passed=False, problems=["request failed: HTTPStatusError"]),
                                     dict(passed=True, problems=[])])
        self.assertEqual((summary["answered"], summary["request_failures"]), (1, 1))


if __name__ == "__main__":
    unittest.main()
