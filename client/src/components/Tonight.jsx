import { useEffect, useState } from 'react';
import GameCard from './GameCard';
import { isEven } from '../utils/forecast';
import { teamInfo } from '../utils/teams';
import { getData } from '../services/nbaApi';

const pct = (value) => `${(value * 100).toFixed(1)}%`;
const longDate = (day) => new Date(`${day}T12:00:00`).toLocaleDateString('en-US', { weekday: 'long', month: 'long', day: 'numeric' });
const shortDate = (day) => new Date(`${day}T12:00:00`).toLocaleDateString('en-US', { month: 'long', day: 'numeric' });

function byDate(games) {
  const groups = [];
  for (const game of games) {
    const last = groups.at(-1);
    if (last && last.date === game.date) last.games.push(game);
    else groups.push({ date: game.date, games: [game] });
  }
  return groups;
}

function RecordCard({ summary }) {
  const live = summary.live;
  if (!live.games) return <aside className="record-card"><p className="muted">The record starts once the first forecasted games finish.</p></aside>;
  const wins = Math.round(live.accuracy * live.games);
  const homeWins = Math.round(live.home_win_rate * live.games);
  return <aside className="record-card" aria-label="Live record">
    <p className="muted">Record since {shortDate(summary.first_live_date)}</p>
    <p className="record-number">{wins}–{live.games - wins}</p>
    <dl className="record-facts">
      <div><dt>Correct picks</dt><dd>{pct(live.accuracy)}</dd></div>
      <div><dt>Always pick home team</dt><dd>{homeWins}–{live.games - homeWins}</dd></div>
      <div><dt>Brier score</dt><dd>{live.brier.toFixed(3)}</dd></div>
    </dl>
  </aside>;
}

function Highlights({ games }) {
  if (games.length < 2) return null;
  const strength = (game) => Math.max(game.home_win_probability, game.away_win_probability);
  const favorite = games.reduce((best, game) => (strength(game) > strength(best) ? game : best));
  const closest = games.reduce((best, game) => (strength(game) < strength(best) ? game : best));
  const pick = (game) => teamInfo(game.home_win_probability >= 0.5 ? game.home_team : game.away_team).name;
  return <dl className="highlights">
    <div><dt>Biggest favorite</dt><dd>{pick(favorite)}, {Math.round(strength(favorite) * 100)}%</dd></div>
    <div><dt>Closest game</dt><dd>{teamInfo(closest.away_team).name} at {teamInfo(closest.home_team).name}{isEven(closest) ? ', even' : `, ${Math.round(strength(closest) * 100)}%`}</dd></div>
  </dl>;
}

export default function Tonight({ onArchive }) {
  const [state, setState] = useState({ loading: true });
  const [attempt, setAttempt] = useState(0);
  useEffect(() => {
    const controller = new AbortController();
    getData('live?recent=60', controller.signal)
      .then((data) => setState({ data }))
      .catch((error) => { if (error.name !== 'AbortError') setState({ error: error.message }); });
    return () => controller.abort();
  }, [attempt]);

  if (state.loading) return <p className="notice" role="status">Loading today's games…</p>;
  if (state.error) return <div className="notice" role="alert"><p>{state.error}</p>
    <div className="notice-actions"><button className="pill" onClick={() => { setState({ loading: true }); setAttempt((n) => n + 1); }}>Try again</button><button className="pill" onClick={onArchive}>Browse past seasons</button></div></div>;

  const { summary, upcoming, recent } = state.data;
  const today = upcoming[0]?.date;
  return <>
    <section className="intro">
      <div>
        <h1>{today ? "Today's games" : 'No games left today'}</h1>
        <p className="lede">{today ? longDate(today) : 'New forecasts are posted every morning.'}</p>
        <Highlights games={upcoming} />
        <p className="intro-note">Each forecast is saved before tip-off and never changed, so the record can't be adjusted after the fact.</p>
      </div>
      <RecordCard summary={summary} />
    </section>

    {upcoming.length > 0 && <div className="card-grid">{upcoming.map((game) => <GameCard key={game.game_id} game={game} />)}</div>}

    {recent.length > 0 && <section className="section">
      <h2>Recent results</h2>
      {byDate(recent).map((group) => {
        const hits = group.games.filter((game) => game.correct).length;
        return <div className="day" key={group.date}>
          <h3>{longDate(group.date)}<span className="muted"> {hits} of {group.games.length} correct</span></h3>
          <div className="card-grid">{group.games.map((game) => <GameCard key={game.game_id} game={game} />)}</div>
        </div>;
      })}
    </section>}

    {summary.backfill.games > 0 && <p className="footnote">
      {summary.backfill.games} games from earlier this season were scored afterward, using only results from before each game. They aren't part of the record.
    </p>}
  </>;
}
