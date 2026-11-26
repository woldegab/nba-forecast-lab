const pct = (value) => `${Math.round(value * 100)}%`;
const shortDate = (day) => new Date(`${day}T12:00:00`).toLocaleDateString('en-US', { month: 'short', day: 'numeric' });

export function Sparkline({ values, color }) {
  if (values.length < 2) return <span className="sparkline empty" aria-hidden="true" />;
  const low = Math.min(...values); const high = Math.max(...values); const span = high - low || 1;
  const points = values.map((v, i) => `${(i / (values.length - 1)) * 96 + 2},${26 - ((v - low) / span) * 22}`).join(' ');
  return <svg className="sparkline" viewBox="0 0 100 28" aria-hidden="true"><polyline points={points} style={{ stroke: color }} /></svg>;
}

// Rating after each game, in the team's color, with a dot per game (filled = win).
export function RatingChart({ games, color, name }) {
  if (!games.length) return <p className="muted">No games played yet this season.</p>;
  const W = 800, H = 260, pad = { l: 48, r: 16, t: 16, b: 32 };
  const ratings = games.map((g) => g.rating).concat(games[0].rating_before, 1500);
  const step = [25, 50, 100].find((size) => (Math.max(...ratings) - Math.min(...ratings) + 20) / size <= 5) || 200;
  const low = Math.floor((Math.min(...ratings) - 10) / step) * step;
  const high = Math.ceil((Math.max(...ratings) + 10) / step) * step;
  const x = (i) => pad.l + (games.length === 1 ? 0.5 : i / (games.length - 1)) * (W - pad.l - pad.r);
  const y = (v) => pad.t + (1 - (v - low) / (high - low)) * (H - pad.t - pad.b);
  const ticks = []; for (let v = low; v <= high; v += step) ticks.push(v);
  const labelEvery = Math.max(1, Math.ceil(games.length / 6));
  const path = games.map((g, i) => `${i ? 'L' : 'M'}${x(i).toFixed(1)},${y(g.rating).toFixed(1)}`).join(' ');
  const first = games[0], last = games.at(-1);
  return <figure className="rating-chart">
    <div className="chart-scroll"><svg viewBox={`0 0 ${W} ${H}`} role="img" aria-label={`${name} rating went from ${Math.round(first.rating_before)} to ${Math.round(last.rating)} over ${games.length} games.`}>
      {ticks.map((v) => <g key={v} className="grid"><line x1={pad.l} x2={W - pad.r} y1={y(v)} y2={y(v)} /><text x={pad.l - 8} y={y(v)} dy="0.32em">{v}</text></g>)}
      {low <= 1500 && 1500 <= high && <line className="average" x1={pad.l} x2={W - pad.r} y1={y(1500)} y2={y(1500)} />}
      <path className="line" d={path} style={{ stroke: color }} />
      {games.map((g, i) => <circle key={g.game_id} cx={x(i)} cy={y(g.rating)} r={games.length > 50 ? 2.5 : 4}
        className={g.result === 'W' ? 'dot win' : 'dot loss'} style={{ '--team': color }}>
        <title>{`${shortDate(g.date)}: ${g.result} ${g.score} ${g.home ? 'vs' : 'at'} ${g.opponent}. Rating ${Math.round(g.rating)}.`}</title>
      </circle>)}
      {games.map((g, i) => (i % labelEvery === 0 || i === games.length - 1) &&
        <text key={`x${g.game_id}`} className="x-label" x={x(i)} y={H - 8} textAnchor="middle">{shortDate(g.date)}</text>)}
    </svg></div>
    <figcaption className="muted small">Rating after each game. Filled dots are wins. The dashed line is the league average, 1,500.</figcaption>
  </figure>;
}

// Forecast win chance vs. how often favorites actually won, per group.
export function CalibrationChart({ series }) {
  const W = 420, H = 320, pad = { l: 52, r: 16, t: 16, b: 48 };
  const x = (v) => pad.l + ((v - 0.5) / 0.5) * (W - pad.l - pad.r);
  const y = (v) => pad.t + (1 - (v - 0.4) / 0.6) * (H - pad.t - pad.b);
  const ticksX = [0.5, 0.6, 0.7, 0.8, 0.9, 1];
  const ticksY = [0.4, 0.6, 0.8, 1];
  return <figure className="calibration">
    <svg viewBox={`0 0 ${W} ${H}`} role="img" aria-label="Calibration: how often favorites won compared with their forecast chance">
      {ticksY.map((v) => <g key={`y${v}`} className="grid"><line x1={pad.l} x2={W - pad.r} y1={y(v)} y2={y(v)} /><text x={pad.l - 8} y={y(v)} dy="0.32em">{pct(v)}</text></g>)}
      {ticksX.map((v) => <text key={`x${v}`} className="x-label" x={x(v)} y={H - pad.b + 20} textAnchor="middle">{pct(v)}</text>)}
      <text className="axis-title" x={(W + pad.l) / 2} y={H - 6} textAnchor="middle">Forecast chance for the favorite</text>
      <line className="perfect" x1={x(0.5)} y1={y(0.5)} x2={x(1)} y2={y(1)} />
      {series.map((s) => {
        const points = s.buckets.filter((b) => b.games);
        return <g key={s.name} className={`series ${s.className}`}>
          <path d={points.map((b, i) => `${i ? 'L' : 'M'}${x(b.forecast)},${y(b.actual)}`).join(' ')} />
          {points.map((b) => <circle key={b.low} cx={x(b.forecast)} cy={y(b.actual)} r={Math.min(9, 3 + Math.sqrt(b.games) / 4)}>
            <title>{`${s.name}: favorites at ${pct(b.low)}–${pct(b.high)} won ${pct(b.actual)} of ${b.games} games (forecast ${pct(b.forecast)}).`}</title>
          </circle>)}
        </g>;
      })}
    </svg>
    <figcaption>
      <span className="legend perfect-key">Perfectly calibrated</span>
      {series.map((s) => <span key={s.name} className={`legend ${s.className}`}>{s.name} ({s.games.toLocaleString()} games)</span>)}
    </figcaption>
  </figure>;
}
