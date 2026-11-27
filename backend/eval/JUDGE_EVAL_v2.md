# AI judge vs. hand labels

Judge model: `gemini-flash-lite-latest`, rubric v2. Previews graded by both: 29.

| Grader | Matches your labels |
|---|---|
| Rule checks alone | 90% agreement, kappa 0.78 (substantial) |
| AI judge alone | 86% agreement, kappa 0.72 (substantial) |
| **Rules + judge** (good only if both say good, as production would use it) | **86% agreement, kappa 0.72 (substantial)** |

Rubric v2 was written after reading v1's disagreements on these same labels, so these are development results. A fair test needs new labels the rubric hasn't seen.

Kappa corrects for agreement you'd get by chance: 0 is no better than guessing, 1 is perfect.

Judge alone vs. you:

| | Count |
|---|---:|
| you bad, judge bad | 11 |
| you bad, judge good | 1 |
| you good, judge bad | 3 |
| you good, judge good | 14 |

## Where rules + judge still disagree with you

- You: good; rules: good, judge: bad (The preview describes a 64 percent favorite as a slight edge or close matchup? No, wait, the preview mentions the win chance but uses repetitive phrasing and fails to mention any stats for the underdog Trail Blazers.): "76ers host Trail Blazers with 64% win chance. The model gives the 76ers a 64% chance against the Trail Blazers. Philadelphia brings a five-game win streak into the home game with an 8-2 record in its last ten."
- You: bad; rules: good, judge: good (The preview correctly identifies the favorite with its win chance, avoids codes, uses plain English, aligns the phrasing with the 63% probability, and is fully supported by the facts.): "Suns visit Pelicans. The model gives the Suns a 63% chance to win with a 3-game streak. The Pelicans have lost 3 straight and hold a 1-9 record in their last 10 games."
- You: good; rules: good, judge: bad (The preview mentions that Miami enters on a 7-game win streak with an 8-2 last-10 while Philadelphia is 14-4 and lost its last game (L1), making the underdog look better in recent form without providing any reason for the 76ers pick.): "76ers host the Heat. The model gives the 76ers a 64% chance to win at home. Philadelphia has a 14-4 record, while Miami enters on a 7-game win streak with an 8-2 last-10."
- You: good; rules: good, judge: bad (The preview mentions a 3-game win streak for the Spurs, but the facts indicate a streak of W3, which contains a forbidden code format.): "Spurs and Trail Blazers Clash in Portland. The model gives the Spurs a 56% chance against the Trail Blazers. San Antonio comes in hot with a 9-1 last-10 record and a 3-game win streak, while Portland sits at 11-6."
