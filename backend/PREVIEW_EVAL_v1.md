# AI preview evaluation

Model: `gemini-flash-lite-latest`. Games: 30 recent games from the live ledger.
Generated 2026-11-27 by `backend/previews.py eval`.

**Passed every check on the first try: 30 of 30 (100%).**

Checks: only numbers from the facts, percentages match the win chances, both teams named, favorite named and never flipped, no injury or betting talk, length limits.


## Sample previews that passed

- 2026-11-21: "The Boston Celtics take on the Sacramento Kings in this matchup. The model strongly favors the Celtics with an 82% chance to win the game."
- 2026-11-22: "The Atlanta Hawks take on the Detroit Pistons in a tight game. The model slightly favors the Atlanta Hawks with a 51 percent chance to win."
- 2026-11-22: "The Miami Heat host the Oklahoma City Thunder in this upcoming game. The model favors the Thunder with a 57% chance to win. Both teams enter this matchup following recent wins."

In production, a preview that fails is retried once and otherwise replaced by a template.
