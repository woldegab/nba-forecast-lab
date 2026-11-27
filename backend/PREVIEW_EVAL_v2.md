# AI preview evaluation

Model: `gemini-flash-lite-latest`. Games: 30 recent games from the live ledger.
Generated 2026-11-27 by `backend/previews.py eval`.

**Passed every check on the first try: 25 of 30 (83%).**

Checks: only numbers from the facts, percentages match the win chances, both teams named, favorite named and never flipped, no injury or betting talk, length limits.

| Failure | Count |
|---|---:|
| streak | 3 |
| confidence | 2 |

## Failed previews

- 2026-11-22 `0022600283`: streak: calls the Bulls winning but their streak is L1. Text: "The model makes the Nuggets a heavy favorite with a 72% win chance. Denver brings a 7-3 last-10 record and a two-game win streak into the game against Chicago, which is 4-11."
- 2026-11-22 `0022600286`: confidence: says close game at 64%. Text: "The model gives the Celtics a slight edge with a 64% win chance against the Warriors. Boston holds an 11-5 record, while Golden State enters with an 8-8 record and a 5-5 last-10 run."
- 2026-11-23 `0022600287`: confidence: says close game at 63%. Text: "The model gives the Hornets a slight edge with a 63% win chance at home against the Grizzlies. Charlotte enters with a 4-11 record and a four-game losing streak, while Memphis holds a 12-5 record."
- 2026-11-23 `0022600293`: streak: calls the Pelicans winning but their streak is L3. Text: "The model gives the Suns a 63% chance to win. Phoenix brings a 3-game win streak and a 7-3 record in their last 10 games into New Orleans. The Pelicans enter with a 1-9 record in their last 10 and have lost 3 straight."
- 2026-11-25 `0022600059`: streak: calls the Clippers winning but their streak is L4. Text: "The model gives the Grizzlies a 59% chance at home. Memphis brings a 7-3 last-10 record and a 1-game win streak, while the Clippers have dropped 4 straight."

## Sample previews that passed

- 2026-11-21: "The model makes the Celtics a heavy favorite with an 82% win chance against the Kings. Boston sits at 11-4 with a 7-3 record in their last 10 games. Sacramento holds a 1-14 record and is on an eight-game losing streak after playing yesterday."
- 2026-11-22: "The model gives the Hawks a 51% chance to win, making this a close game. Atlanta is on a 3-game win streak with a 7-3 record in its last 10, while Detroit is coming off a loss."
- 2026-11-22: "The model gives the Thunder a slight edge with a 57% win chance. Oklahoma City brings a 10-6 record and a 1-game win streak into the game, while the Heat hold a 9-6 record and are hot with 6 straight wins."

In production, a preview that fails is retried once and otherwise replaced by a template.
