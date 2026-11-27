from datetime import datetime, timezone
import json
from pathlib import Path
import tempfile
import unittest
from unittest import mock

import previews
from previews import QuotaError, build_facts, check, template, update, write_preview


def row(game_id, day, home, away, p, home_score="", away_score="", mode="live", tipoff=None):
    return dict(game_id=game_id, game_date=day, tipoff_utc=tipoff or f"{day}T23:30:00+00:00", home_team=home,
                away_team=away, home_team_id="1", away_team_id="2", neutral_site="0", home_rating="1550",
                away_rating="1500", home_win_probability=str(p), predicted_at_utc=f"{day}T15:00:00+00:00",
                mode=mode, home_score=str(home_score), away_score=str(away_score),
                actual_home_win="" if home_score == "" else str(int(home_score > away_score)))


ROWS = [
    row("1", "2026-11-20", "BOS", "NYK", 0.6, 110, 100),
    row("2", "2026-11-21", "NYK", "MIA", 0.55, 99, 101),
    row("3", "2026-11-25", "MIA", "BOS", 0.4, 90, 95),
    row("4", "2026-11-26", "NYK", "BOS", 0.36),   # today; BOS played yesterday
]
NOW = datetime(2026, 11, 26, 15, 0, tzinfo=timezone.utc)


class FakeClient:
    model = "fake"

    def __init__(self, *drafts):
        self.drafts, self.calls = list(drafts), 0

    def write(self, facts):
        self.calls += 1
        draft = self.drafts.pop(0)
        if isinstance(draft, Exception):
            raise draft
        return draft


GOOD = dict(headline="Celtics visit the Knicks",
            preview="The model gives the Celtics a 64% chance to win in New York, even on the second night of a "
                    "back-to-back. Boston is 2-0 this season, while the Knicks are 0-2 and looking for a first win.")


class FactTests(unittest.TestCase):
    def test_uses_only_earlier_games(self):
        facts = build_facts(ROWS[3], ROWS)
        self.assertEqual(facts["away"]["record"], "2-0")
        self.assertEqual(facts["home"]["record"], "0-2")
        self.assertEqual(facts["away"]["streak"], "W2")
        self.assertEqual((facts["away"]["win_chance"], facts["home"]["win_chance"]), (64, 36))
        self.assertEqual(facts["favorite"], "away")

    def test_back_to_back_flag(self):
        facts = build_facts(ROWS[3], ROWS)
        self.assertTrue(facts["away"]["played_yesterday"])
        self.assertFalse(facts["home"]["played_yesterday"])

    def test_later_games_do_not_leak(self):
        later = ROWS + [row("5", "2026-11-27", "BOS", "MIA", 0.5, 120, 80)]
        self.assertEqual(build_facts(ROWS[3], later)["away"]["record"], "2-0")


class CheckTests(unittest.TestCase):
    facts = build_facts(ROWS[3], ROWS)

    def test_good_preview_passes(self):
        self.assertEqual(check(GOOD, self.facts), [])

    def test_invented_number_fails(self):
        bad = dict(GOOD, preview=GOOD["preview"].replace("2-0 this season", "averaging 118 points"))
        self.assertTrue(any("numbers not in the facts" in p for p in check(bad, self.facts)))

    def test_wrong_percentage_fails(self):
        bad = dict(GOOD, preview=GOOD["preview"].replace("64%", "70%"))
        self.assertTrue(any("percentages" in p for p in check(bad, self.facts)))

    def test_flipped_favorite_fails(self):
        bad = dict(GOOD, preview="The Knicks are favored at home tonight with a 36% chance. "
                                 "The Celtics are 2-0 and played last night, so this could be close for both teams.")
        problems = check(bad, self.facts)
        self.assertIn("calls the underdog the favorite", problems)

    def test_betting_and_injury_talk_fail(self):
        for word in ("odds", "injury", "betting"):
            bad = dict(GOOD, preview=GOOD["preview"] + f" Watch the {word} closely.")
            self.assertTrue(any("off-limits" in p for p in check(bad, self.facts)), word)

    def test_must_name_both_teams(self):
        bad = dict(GOOD, headline="Big game tonight",
                   preview="The model gives the Celtics a 64% chance to win, even on the second night of a "
                           "back-to-back. They are 2-0 this season and have won two straight games heading in.")
        self.assertIn("does not name the Knicks", check(bad, self.facts))

    def test_template_always_passes(self):
        for game in ROWS:
            facts = build_facts(game, ROWS)
            self.assertEqual(check(template(facts), facts), [], game["game_id"])


class ClaimTests(unittest.TestCase):
    facts = build_facts(ROWS[3], ROWS)   # Celtics 64%, streak W2; Knicks streak L2

    def test_percent_spelled_out_is_checked(self):
        bad = dict(GOOD, preview=GOOD["preview"].replace("64%", "70 percent"))
        self.assertTrue(any("percentages" in p for p in check(bad, self.facts)))

    def test_false_streak_claim_fails(self):
        bad = dict(GOOD, preview=GOOD["preview"] + " Both teams are coming off recent wins.")
        self.assertTrue(any("calls the Knicks winning" in p for p in check(bad, self.facts)))

    def test_true_streak_claim_passes(self):
        ok = dict(GOOD, preview=GOOD["preview"].replace("Boston is 2-0", "Boston is on a winning streak at 2-0"))
        self.assertEqual(check(ok, self.facts), [])

    def test_confidence_words_must_match_the_chance(self):
        strong = dict(GOOD, preview=GOOD["preview"].replace("gives the Celtics", "strongly favors the Celtics, giving them"))
        self.assertTrue(any("strong favorite" in p for p in check(strong, self.facts)))
        close = dict(GOOD, preview=GOOD["preview"] + " Expect a close game.")
        self.assertTrue(any("close game" in p for p in check(close, self.facts)))   # 64% is above the 60% line
        slight = build_facts(row("9", "2026-11-26", "NYK", "BOS", 0.45), ROWS)
        ok = dict(GOOD, preview="The model gives the Celtics a slight edge at 55% in New York. The Knicks are "
                                "0-2 this season, and Boston is 2-0 after winning both of its first games.")
        self.assertEqual(check(ok, slight), [])

    def test_close_game_wording_rejected_for_big_favorite(self):
        rows = ROWS[:3] + [row("4", "2026-11-26", "NYK", "BOS", 0.2)]
        facts = build_facts(rows[3], rows)
        bad = dict(GOOD, preview=GOOD["preview"].replace("64%", "80%") + " It should be a tight game.")
        self.assertTrue(any("close game" in p for p in check(bad, facts)))


class AttributionTests(unittest.TestCase):
    def facts(self, home, away, p, home_streak, away_streak):
        f = build_facts(row("9", "2026-11-26", home, away, p), ROWS)
        f["home"]["streak"], f["away"]["streak"] = home_streak, away_streak
        return f

    def test_short_city_does_not_match_inside_words(self):
        facts = self.facts("MEM", "LAC", 0.59, "W1", "L4")
        text = dict(headline="Clippers at Grizzlies", preview="The model gives the Grizzlies a 59% chance at home. "
                    "Memphis brings a 7-3 last-10 record and a 1-game win streak, while the Clippers have dropped 4 straight.")
        self.assertEqual([p for p in check(text, facts) if p.startswith("streak")], [])

    def test_streak_belongs_to_team_named_before_it(self):
        facts = self.facts("CHI", "DEN", 0.28, "L1", "W2")
        text = dict(headline="Nuggets at Bulls", preview="The model makes the Nuggets a heavy favorite with a 72% win "
                    "chance. Denver brings a 7-3 last-10 record and a two-game win streak into the game against Chicago, which is 4-11.")
        self.assertEqual([p for p in check(text, facts) if p.startswith("streak")], [])

    def test_wrong_team_still_caught(self):
        facts = self.facts("CHI", "DEN", 0.28, "L1", "W2")
        text = dict(headline="Nuggets at Bulls", preview="The model makes the Nuggets a heavy favorite with a 72% win "
                    "chance. Chicago is on a winning streak but Denver is 7-3 in its last 10 games.")
        self.assertTrue(any("calls the Bulls winning" in p for p in check(text, facts)))

    def test_rescore_uses_saved_outputs(self):
        facts = self.facts("MEM", "LAC", 0.59, "W1", "L4")
        draft = dict(headline="Clippers at Grizzlies", preview="The model gives the Grizzlies a 59% chance at home, "
                     "and Memphis is 1-0 in its last game while the Clippers have lost 4 straight games coming in.")
        old = [dict(game_id="9", date="2026-11-26", passed=False, problems=["stale"], preview=draft["preview"],
                    draft=draft, facts=facts)]
        self.assertTrue(previews.rescore(old)[0]["passed"])


class WriteTests(unittest.TestCase):
    facts = build_facts(ROWS[3], ROWS)

    def test_ai_preview_kept_when_it_passes(self):
        preview, problems = write_preview(self.facts, FakeClient(GOOD))
        self.assertEqual((preview["source"], problems), ("ai", []))

    def test_retries_then_falls_back_to_template(self):
        bad = dict(GOOD, preview=GOOD["preview"].replace("64%", "80%"))
        client = FakeClient(bad, bad)
        preview, problems = write_preview(self.facts, client)
        self.assertEqual((preview["source"], client.calls), ("template", 2))
        self.assertTrue(problems)

    def test_second_try_can_succeed(self):
        bad = dict(GOOD, preview=GOOD["preview"].replace("64%", "80%"))
        preview, _ = write_preview(self.facts, FakeClient(bad, GOOD))
        self.assertEqual(preview["source"], "ai")

    def test_network_error_falls_back(self):
        preview, problems = write_preview(self.facts, FakeClient(OSError("down"), OSError("down")))
        self.assertEqual(preview["source"], "template")
        self.assertIn("request failed", problems[0])


class UpdateTests(unittest.TestCase):
    def test_only_todays_live_games_and_never_rewrites(self):
        saved, _ = update(ROWS, {}, NOW, FakeClient(GOOD))
        self.assertEqual(list(saved), ["4"])
        again, _ = update(ROWS, saved, NOW, FakeClient())   # no drafts: would raise if called
        self.assertEqual(again, saved)

    def test_no_key_means_templates(self):
        saved, _ = update(ROWS, {}, NOW, None)
        self.assertEqual(saved["4"]["source"], "template")

    def test_quota_switches_to_templates(self):
        rows = ROWS + [row("5", "2026-11-26", "MIA", "BOS", 0.5, tipoff="2026-11-27T01:00:00+00:00")]
        saved, notes = update(rows, {}, NOW, FakeClient(QuotaError("limit"), GOOD))
        self.assertEqual({saved[g]["source"] for g in ("4", "5")}, {"template"})
        self.assertTrue(any("limit" in n for n in notes))

    def test_cli_round_trip_without_key(self):
        with tempfile.TemporaryDirectory() as folder:
            live = Path(folder)
            fields = list(ROWS[0])
            import csv
            with (live / previews.LEDGER_FILE).open("w", newline="") as file:
                writer = csv.DictWriter(file, fieldnames=fields)
                writer.writeheader()
                writer.writerows(ROWS)
            with mock.patch.dict("os.environ", {"GEMINI_API_KEY": ""}):
                self.assertEqual(previews.main(["update", "--live-dir", folder, "--now", NOW.isoformat()]), 0)
            saved = json.loads((live / previews.PREVIEW_FILE).read_text())
            self.assertEqual(saved["4"]["source"], "template")


class PacingTests(unittest.TestCase):
    def test_waits_between_requests_and_retries_once_when_asked(self):
        waits = []
        client = previews.Paced(FakeClient(GOOD, QuotaError("slow down", wait=20), GOOD), pace=6, sleep=waits.append)
        client.write({}); client.write({})
        self.assertEqual(waits, [6, 21])

    def test_daily_limit_is_not_retried(self):
        client = previews.Paced(FakeClient(QuotaError("daily", wait=None)), pace=0, sleep=lambda s: None)
        with self.assertRaises(QuotaError):
            client.write({})

    def test_eval_keeps_results_before_the_limit(self):
        results = previews.evaluate(ROWS, FakeClient(GOOD, QuotaError("limit")))
        self.assertEqual(len(results), 1)


class EvalTests(unittest.TestCase):
    def test_report_counts_passes_and_failures(self):
        bad = dict(GOOD, preview=GOOD["preview"].replace("64%", "80%"))
        rows = [r for r in ROWS if r["home_score"] != ""]
        results = previews.evaluate(ROWS, FakeClient(*([bad] + [template(build_facts(r, ROWS)) for r in rows[1:]])))
        self.assertEqual(len(results), 3)
        report = previews.eval_report(results, "fake")
        self.assertIn("2 of 3", report)


if __name__ == "__main__":
    unittest.main()
