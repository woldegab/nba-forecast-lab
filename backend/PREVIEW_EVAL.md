# AI preview evaluation

Model: `gemini-flash-lite-latest`. Games: 30 recent games from the live ledger.
Generated 2026-11-27 by `backend/previews.py eval`.

**Passed every check on the first try: 27 of 30 (90%).**

Checks: only numbers from the facts, percentages match the win chances, both teams named, favorite named and never flipped, no injury or betting talk, length limits.

| Failure | Count |
|---|---:|
| confidence | 2 |
| request failed | 1 |

## Failed previews

- 2026-11-22 `0022600286`: confidence: says close game at 64%. Text: "The model gives the Celtics a 64% chance against the Warriors. Boston holds an 11-5 record while Golden State enters with an 8-8 record and a 5-5 last-10."
- 2026-11-23 `0022600287`: confidence: says close game at 63%. Text: "The model gives the Hornets a slight edge with a 63% win chance at home. Charlotte holds a 4-11 record and is on a 4-game losing streak, while the Grizzlies sit at 12-5."
- 2026-11-24 `0022600053`: request failed: HTTPStatusError. Text: ""

## Sample previews that passed

- 2026-11-21: "The model makes the Celtics a heavy favorite with an 82% win chance against the Kings. Boston holds an 11-4 record and goes up against Sacramento, which sits at 1-14 with an eight-game losing streak."
- 2026-11-22: "The model gives the Hawks a 51% chance against the Pistons in a close game. Atlanta is coming off a win with a 7-3 last-10 record and a 3-game winning streak."
- 2026-11-22: "The model gives the Thunder a 57% chance against the Heat. Oklahoma City holds a 10-6 record and is on a W1 streak, while Miami sits at 9-6 and is hot with an 8-2 last-10 record and W6 streak."

In production, a preview that fails is retried once and otherwise replaced by a template.
