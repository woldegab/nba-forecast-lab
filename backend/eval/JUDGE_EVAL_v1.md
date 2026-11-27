# AI judge vs. hand labels

Judge model: `gemini-flash-lite-latest`. Previews graded by both: 29.

**Agreement: 69%. Cohen's kappa: 0.34 (fair).**

Kappa corrects for agreement you'd get by chance: 0 is no better than guessing, 1 is perfect.

| | Count |
|---|---:|
| you bad, judge bad | 6 |
| you bad, judge good | 6 |
| you good, judge bad | 3 |
| you good, judge good | 14 |

## Disagreements

- You: good, judge: bad (The preview includes the forbidden filler phrase 'in a close matchup' and 'in this matchup' variations.) — "Hawks Host Pistons in Close Matchup. The model gives the Hawks a 51% chance against the Pistons in a close game. Atlanta is coming off a win with a 7-3 last-10 record and a 3-game winning streak"
- You: bad, judge: good (The preview is accurate, uses plain English, correctly identifies the favorite with its win chance, and includes the required records and last-10 facts while matching the 64% probability with the phrase slight edge.) — "Celtics visit Warriors with a slight edge. The model gives the Celtics a 64% chance against the Warriors. Boston holds an 11-5 record while Golden State enters with an 8-8 record and a 5-5 last-10"
- You: bad, judge: good (The preview accurately reflects all facts, uses plain English suitable for casual fans, includes the correct win probability and a fitting description, and mentions relevant record and streak facts without any jargon.) — "Hornets Host Grizzlies in Charlotte. The model gives the Hornets a slight edge with a 63% win chance at home. Charlotte holds a 4-11 record and is on a 4-game losing streak, while the Grizzlies sit at 12-5"
- You: good, judge: bad (The preview contains repetitive phrasing and cuts off mid-sentence.) — "76ers host Trail Blazers with 64% win chance. The model gives the 76ers a 64% chance against the Trail Blazers. Philadelphia brings a five-game win streak into the home game with an 8-2 record in its last ten"
- You: bad, judge: good (The preview correctly identifies the heavy favorite, matches the 78% win chance with appropriate wording, includes accurate records and streak facts, and uses plain English.) — "Thunder Visit Pacers. The model favors the Thunder as a heavy favorite with a 78% win chance over the Pacers. Oklahoma City is 10-7 on the season with an L1 streak, while Indiana sits at 5-12 with an L4 streak"
- You: bad, judge: good (The preview correctly identifies the favorite with its win chance, includes required streak and last-10 facts, matches the wording to the 63% probability, and avoids jargon.) — "Suns visit Pelicans. The model gives the Suns a 63% chance to win with a 3-game streak. The Pelicans have lost 3 straight and hold a 1-9 record in their last 10 games"
- You: good, judge: bad (The preview uses prohibited filler phrase 'into the matchup'.) — "Nuggets Face Mavericks in Denver. The model gives the Nuggets a heavy favorite 79% chance to win at home. Denver brings a 3-game winning streak into the matchup with a 10-5 record, while the Mavericks sit at 10-7"
- You: bad, judge: good (The preview accurately reflects the facts, uses plain English without jargon, provides the win chance and required team facts, and avoids mismatched probability wording.) — "Hornets Host Bulls in Charlotte. The model gives the Hornets a 68% chance against the Bulls. Charlotte holds a 4-12 record and a five-game losing streak, while Chicago sits at 5-12 with one straight win"
- You: bad, judge: good (The preview meets all criteria by using plain English, accurately reflecting the facts and win chances, and including necessary team records and streaks without any jargon.) — "Thunder host Timberwolves in Oklahoma City. The model gives the Thunder a 64% chance against the Timberwolves. Oklahoma City holds a 10-8 record with a 4-6 last-10 and a two-game skid, while Minnesota sits at 13-5 with an 8-2 last-10 and two straight wins"
