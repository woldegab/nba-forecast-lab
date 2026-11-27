"""Measure the AI-written text: hand labels, an AI judge, side-by-side comparisons, weekly tracking.

  python backend/ai_eval.py label     # grade saved previews yourself, good or bad (no API calls)
  python backend/ai_eval.py judge     # an AI judge grades the same previews; report agreement with you
  python backend/ai_eval.py compare --variants gemini-flash-lite-latest:v3 gemini-flash-lite-latest:v4
  python backend/ai_eval.py weekly    # previews + recaps + judge on recent games; appends eval/history.json

Rule checks (previews.py, recaps.py) catch facts that are wrong. The judge catches what rules
can't, such as jargon or a dull preview, but a judge is only worth using once it agrees with a
person, so `judge` reports agreement and Cohen's kappa against your labels first.
"""

import argparse
from collections import Counter
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import sys

import previews
import recaps
from live_forecast import LEDGER_FILE, LIVE_DIR, read_ledger
from previews import GeminiClient, Paced, QuotaError

EVAL_DIR = Path(__file__).parent / "eval"
LABELS = "labels.json"
HISTORY = "history.json"
SAVED_PREVIEWS = Path(__file__).parent / "PREVIEW_EVAL.json"

# Rubric v2, revised after comparing v1's grades with 29 hand labels (see eval/JUDGE_EVAL.md).
JUDGE_PROMPT = """You grade short game previews written for a basketball forecasting website read by casual fans.
Answer "good" only if ALL of these hold:
- Every claim agrees with the facts below; nothing is invented.
- No codes: any W or L followed by a number (W1, L4, W6) is a code and makes the preview bad, even if
  the same fact is also written in words.
- Plain English a casual fan understands. Short scene-setting phrases such as "in Denver" or "into the
  game" are fine; only fail wording that is unclear (for example "a 3-game streak" without saying won or lost).
- Useful: names the favorite with its win chance (or calls it a toss-up) and adds at least one record, last-10 or streak fact.
- The wording matches the chance: "slight edge" or "close" only from 50% to 60% (a 63% or 64% favorite is
  NOT a slight edge); "heavy favorite" only at 70% or more.
- Not confusing: if the stats the preview mentions make the underdog look better than the favorite (better
  record or better recent form) and the preview gives no reason for the pick, a fan would be confused: bad.
Otherwise answer "bad". Give a one-sentence reason.

Facts:
{facts}

Preview:
{text}
"""
JUDGE_SCHEMA = {
    "type": "OBJECT",
    "properties": {"verdict": {"type": "STRING", "enum": ["good", "bad"]}, "reason": {"type": "STRING"}},
    "required": ["verdict", "reason"],
}


def judge_one(client, facts, text):
    data = client.ask(JUDGE_PROMPT.format(facts=json.dumps(facts, indent=2), text=text), JUDGE_SCHEMA,
                      temperature=0, max_tokens=200)
    verdict = str(data.get("verdict", "")).lower()
    return ("good" if verdict == "good" else "bad"), str(data.get("reason", ""))


def preview_text(draft):
    headline, body = draft.get("headline", "").strip().rstrip("."), draft.get("preview", "").strip()
    return f"{headline}. {body}" if headline else body


def finished(text):
    """Labels saved before a fix had their final period removed, which made them look cut off."""
    text = text.strip()
    return text if text.endswith((".", "!", "?")) else text + "."


def rule_verdict(text, facts):
    """'good' if the text passes the rule checks in previews.py, else 'bad'."""
    headline, _, body = text.partition(". ")
    return "good" if not previews.check(dict(headline=headline, preview=body), facts) else "bad"


# ---------- agreement ----------

def agreement(pairs):
    """Agreement rate, Cohen's kappa and confusion counts for (human, judge) label pairs."""
    n = len(pairs)
    if not n:
        return dict(n=0, agreement=None, kappa=None, confusion={})
    agree = sum(h == j for h, j in pairs) / n
    human, judge = Counter(h for h, _ in pairs), Counter(j for _, j in pairs)
    chance = sum(human[k] * judge[k] for k in ("good", "bad")) / (n * n)
    kappa = None if chance == 1 else (agree - chance) / (1 - chance)
    confusion = {f"you {h}, judge {j}": c for (h, j), c in Counter(pairs).items()}
    return dict(n=n, agreement=agree, kappa=kappa, confusion=confusion)


def kappa_words(kappa):
    if kappa is None:
        return "undefined (every label was the same)"
    return ("almost perfect" if kappa > 0.8 else "substantial" if kappa > 0.6 else "moderate" if kappa > 0.4
            else "fair" if kappa > 0.2 else "slight or none")


# ---------- commands ----------

def label(eval_dir, saved=SAVED_PREVIEWS, ask=input, say=print):
    """Grade saved previews one at a time. Progress is saved after every answer."""
    if not saved.exists():
        say(f"No saved previews at {saved}. Run `python backend/previews.py eval` first.")
        return 1
    items = [r for r in json.loads(saved.read_text())["results"] if r.get("draft")]
    path = eval_dir / LABELS
    labels = json.loads(path.read_text()) if path.exists() else {}
    todo = [r for r in items if r["game_id"] not in labels]
    say(f"{len(labels)} labeled, {len(todo)} to go. g = good, b = bad, s = skip, q = quit.")
    say("Good means: accurate, plain English, useful, and the wording matches the chance.")
    for item in todo:
        f = item["facts"]
        say("")
        say(f"{f['away']['name']} ({f['away']['win_chance']}%, {f['away']['record']}, last 10 {f['away']['last10']}, "
            f"streak {f['away']['streak']}) at {f['home']['name']} ({f['home']['win_chance']}%, {f['home']['record']}, "
            f"last 10 {f['home']['last10']}, streak {f['home']['streak']})")
        say(f"  {preview_text(item['draft'])}")
        answer = ask("good or bad? ").strip().lower()[:1]
        if answer == "q":
            break
        if answer not in ("g", "b"):
            continue
        note = ask("why (optional)? ").strip()
        labels[item["game_id"]] = dict(label="good" if answer == "g" else "bad", note=note,
                                       text=preview_text(item["draft"]), facts=f)
        eval_dir.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(labels, indent=2) + "\n")
    say(f"Saved {len(labels)} label(s) to {path}.")
    return 0


def judge(eval_dir, client):
    path = eval_dir / LABELS
    if not path.exists():
        print("No labels yet. Run `python backend/ai_eval.py label` first.", file=sys.stderr)
        return 1
    labels = json.loads(path.read_text())
    rows = []
    for game_id, item in labels.items():
        try:
            verdict, reason = judge_one(client, item["facts"], finished(item["text"]))
        except QuotaError as error:
            print(f"{error}; stopping after {len(rows)}.", file=sys.stderr)
            break
        except Exception as error:
            print(f"{game_id}: request failed ({type(error).__name__}); skipped.", file=sys.stderr)
            continue
        rules = rule_verdict(finished(item["text"]), item["facts"])
        combined = "good" if rules == "good" and verdict == "good" else "bad"
        rows.append(dict(game_id=game_id, human=item["label"], judge=verdict, rules=rules, combined=combined,
                         reason=reason, text=finished(item["text"])))
    stats = agreement([(r["human"], r["judge"]) for r in rows])
    rules_stats = agreement([(r["human"], r["rules"]) for r in rows])
    combined_stats = agreement([(r["human"], r["combined"]) for r in rows])

    def fmt(st):
        if not st["n"]:
            return "n/a"
        kappa = "n/a" if st["kappa"] is None else format(st["kappa"], ".2f")
        return f"{st['agreement']:.0%} agreement, kappa {kappa} ({kappa_words(st['kappa'])})"

    lines = ["# AI judge vs. hand labels", "",
             f"Judge model: `{client.model}`, rubric v2. Previews graded by both: {stats['n']}.", "",
             "| Grader | Matches your labels |", "|---|---|",
             f"| Rule checks alone | {fmt(rules_stats)} |",
             f"| AI judge alone | {fmt(stats)} |",
             f"| **Rules + judge** (good only if both say good, as production would use it) | **{fmt(combined_stats)}** |", "",
             "Rubric v2 was written after reading v1's disagreements on these same labels, so these are development "
             "results. A fair test needs new labels the rubric hasn't seen.", "",
             "Kappa corrects for agreement you'd get by chance: 0 is no better than guessing, 1 is perfect."]
    if stats["n"]:
        lines += ["", "Judge alone vs. you:", "", "| | Count |", "|---|---:|"] + \
                 [f"| {k} | {v} |" for k, v in sorted(stats["confusion"].items())]
        disagreements = [r for r in rows if r["human"] != r["combined"]]
        if disagreements:
            lines += ["", "## Where rules + judge still disagree with you", ""] + [
                f"- You: {r['human']}; rules: {r['rules']}, judge: {r['judge']} ({r['reason']}): \"{r['text']}\""
                for r in disagreements]
    eval_dir.mkdir(parents=True, exist_ok=True)
    (eval_dir / "JUDGE_EVAL.md").write_text("\n".join(lines) + "\n")
    (eval_dir / "judge_eval.json").write_text(json.dumps(dict(model=client.model, stats=stats, rules=rules_stats, combined=combined_stats, rows=rows), indent=2) + "\n")
    print("\n".join(lines))
    return 0


def summarize(results, judged=None):
    failures = Counter(p.split(":")[0] for r in results for p in r["problems"])
    requests = failures.pop("request failed", 0)
    answered = len(results) - requests
    summary = dict(n=len(results), answered=answered, passed=sum(r["passed"] for r in results),
                   request_failures=requests, failures=dict(failures))
    if judged is not None:
        summary["judge_good"] = sum(v == "good" for v in judged)
        summary["judged"] = len(judged)
    return summary


def judge_results(client, results):
    verdicts = []
    for r in results:
        if not r.get("draft"):
            continue
        try:
            verdicts.append(judge_one(client, r["facts"], preview_text(r["draft"]))[0])
        except QuotaError:
            break
        except Exception:
            continue
    return verdicts


def pct(a, b):
    return f"{a / b:.0%}" if b else "n/a"


def compare(eval_dir, rows, key, variants, limit, use_judge, make_client=None):
    """Same games through each model:prompt variant. The first variant is the current one."""
    make_client = make_client or (lambda model, prompt: Paced(GeminiClient(key, model, prompt)))
    judge_client = make_client(previews.DEFAULT_MODEL, previews.ACTIVE_PROMPT) if use_judge else None
    report = []
    for variant in variants:
        model, _, prompt = variant.partition(":")
        client = make_client(model, prompt or previews.ACTIVE_PROMPT)
        results = previews.evaluate(rows, client, limit)
        verdicts = judge_results(judge_client, results) if judge_client else None
        report.append(dict(variant=variant, **summarize(results, verdicts)))
    current, *others = report
    lines = ["# Model and prompt comparison", "",
             f"Same {limit} recent games for every variant. The first row is the current setup.", "",
             "| Variant | Passed rule checks | Request errors |" + (" Judge: good |" if use_judge else ""),
             "|---|---:|---:|" + ("---:|" if use_judge else "")]
    for r in report:
        lines.append(f"| `{r['variant']}` | {r['passed']} of {r['answered']} ({pct(r['passed'], r['answered'])}) | "
                     f"{r['request_failures']} |" + (f" {r['judge_good']} of {r['judged']} |" if use_judge else ""))
    lines += ["", "Rule: switch only if a variant passes at least 2 more games than the current setup "
                  "(smaller gaps are within run-to-run noise)."]
    best = max(others, key=lambda r: (r["passed"], r.get("judge_good", 0)), default=None)
    if best and best["passed"] >= current["passed"] + 2:
        lines.append(f"**Recommendation: switch to `{best['variant']}`.**")
    else:
        lines.append(f"**Recommendation: keep `{current['variant']}`.**")
    lines += ["", "Failure types:", ""] + [f"- `{r['variant']}`: {r['failures'] or 'none'}" for r in report]
    eval_dir.mkdir(parents=True, exist_ok=True)
    (eval_dir / "COMPARE.md").write_text("\n".join(lines) + "\n")
    (eval_dir / "compare.json").write_text(json.dumps(report, indent=2) + "\n")
    print("\n".join(lines))
    return report


def weekly(eval_dir, rows, client, limit, today=None):
    """Score fresh previews and recaps on recent games and append the result to history.json."""
    preview_results = previews.evaluate(rows, client, limit)
    recap_results = recaps.evaluate(rows, client, limit)
    verdicts = judge_results(client, preview_results)
    entry = dict(date=(today or datetime.now(timezone.utc).date()).isoformat(), model=client.model,
                 prompt=getattr(client, "prompt_version", None),
                 previews=summarize(preview_results, verdicts), recaps=summarize(recap_results))
    path = eval_dir / HISTORY
    history = json.loads(path.read_text()) if path.exists() else []
    history = [h for h in history if h["date"] != entry["date"]] + [entry]
    eval_dir.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(history, indent=2) + "\n")
    p, r = entry["previews"], entry["recaps"]
    print(f"{entry['date']} {entry['model']} prompt {entry['prompt']}: previews {p['passed']}/{p['answered']} passed, "
          f"judge good {p.get('judge_good', 0)}/{p.get('judged', 0)}; recaps {r['passed']}/{r['answered']} passed.")
    return entry


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    commands = parser.add_subparsers(dest="command", required=True)
    commands.add_parser("label", help="Grade saved previews yourself")
    judge_cmd = commands.add_parser("judge", help="AI judge vs. your labels")
    judge_cmd.add_argument("--model", help="Model to use as the judge (default: GEMINI_MODEL or the preview model)")
    cmp_ = commands.add_parser("compare", help="Compare model:prompt variants on the same games")
    cmp_.add_argument("--variants", nargs="+", required=True, help="model:prompt, current setup first")
    cmp_.add_argument("--limit", type=int, default=20)
    cmp_.add_argument("--judge", action="store_true", help="Also grade with the AI judge (doubles the requests)")
    week = commands.add_parser("weekly", help="Weekly quality check, appended to eval/history.json")
    week.add_argument("--limit", type=int, default=20)
    for command in commands.choices.values():
        command.add_argument("--live-dir", type=Path, default=LIVE_DIR)
        command.add_argument("--eval-dir", type=Path, default=EVAL_DIR)
    args = parser.parse_args(argv)
    if args.command == "label":
        return label(args.eval_dir)
    key = os.environ.get("GEMINI_API_KEY", "").strip()
    if not key:
        print("Set GEMINI_API_KEY first.", file=sys.stderr)
        return 1
    if args.command == "judge":
        return judge(args.eval_dir, Paced(GeminiClient(key, args.model)))
    rows = list(read_ledger(args.live_dir / LEDGER_FILE).values())
    if args.command == "compare":
        compare(args.eval_dir, rows, key, args.variants, args.limit, args.judge)
        return 0
    weekly(args.eval_dir, rows, Paced(GeminiClient(key)), args.limit)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
