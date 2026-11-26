# Elo backtest

Historical evaluation; not live predictions.

2023-24 initializes ratings; 2024-25 is development; 2025-26 is the held-out evaluation.
K=20, home advantage=65 Elo points and offseason retention=75% were fixed before evaluation.
Margin of victory and a 50-point back-to-back penalty were chosen on 2024-25 and scored once on 2025-26.

| Season | Games | Elo accuracy | Home-pick accuracy | Elo Brier | Home-rate Brier | Elo log loss |
|---|---:|---:|---:|---:|---:|---:|
| 2024-25 | 1230 | 67.2% | 54.4% | 0.2100 | 0.2480 | 0.6065 |
| 2025-26 | 1230 | 68.5% | 55.4% | 0.2056 | 0.2472 | 0.5982 |

Brier score and log loss measure probability error; lower is better. A 50/50 prediction has Brier score 0.25.
The home-rate baseline uses only 2023-24 results, with 50/50 for neutral games.

All three seasons pass coverage checks: 1,230 games, 30 teams, 82 appearances per team.
Predictions are saved before rating updates; all games on a date use ratings from earlier dates.

## Limitations

- Historical backtest using current corrected records, not archived pregame snapshots.
- Ratings update after prior test games; this evaluates daily sequential forecasting, not preseason forecasts.
- No injuries, rosters, player projections, travel or playoff updates. Rest covers back-to-backs only.
- Neutral-site registry is manually maintained; home-court advantage is zero for listed games.
- 2025-26 has now been evaluated; repeated development against it would make it development data.
