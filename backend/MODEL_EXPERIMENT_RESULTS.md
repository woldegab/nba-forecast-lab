# Model experiment: margin of victory and rest

Chosen on 2024-25 (development), then scored once on 2025-26 (held out).
Rules were written before results; see `backend/experiment_model.py`.

## Rest in 2024-25

- Teams on the second night of a back-to-back: 450 appearances, won 44.7%.
- Games where only one team was on a back-to-back: 308; the rested team won 57.8%.

## Development (2024-25)

| Model | Correct picks | Brier | Log loss |
|---|---:|---:|---:|
| Current model | 65.3% | 0.2144 | 0.6165 |
| + margin of victory | 66.8% | 0.2118 | 0.6109 |
| + back-to-back penalty 10 | 65.0% | 0.2139 | 0.6153 |
| + back-to-back penalty 20 | 65.4% | 0.2134 | 0.6143 |
| + back-to-back penalty 30 | 66.0% | 0.2131 | 0.6134 |
| + back-to-back penalty 40 | 66.1% | 0.2128 | 0.6128 |
| + back-to-back penalty 50 | 65.9% | 0.2126 | 0.6123 |
| + both (penalty 50) | 67.2% | 0.2100 | 0.6065 |

Margin of victory: kept (Brier 0.2118 vs 0.2144).
Back-to-back: best penalty 50; kept (Brier 0.2126 vs 0.2144).

## Held out (2025-26), scored once

| Model | Correct picks | Brier | Log loss |
|---|---:|---:|---:|
| Current model | 67.7% | 0.2097 | 0.6081 |
| Chosen: margin of victory + back-to-back 50 | 68.5% | 0.2056 | 0.5982 |

Brier difference (chosen minus current): -0.0041, 95% interval -0.0069 to -0.0016.
The interval excludes zero, so the improvement is unlikely to be luck.

Decision: switch to the chosen model.
