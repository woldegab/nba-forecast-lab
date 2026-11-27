import { useEffect, useState } from 'react';
import { MatchupTile, ResultRow } from './Slate';
import Court from './Court';
import { GameSkeletons, Loading } from './Skeleton';
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

// The live record as a row of numbers under the headline.
function RecordStrip({ summary, change, saved }) {
  const live = summary.live;
  if (!live.games) return <p className="muted record-strip-empty">{saved
    ? `The live record starts tonight: ${saved} forecast${saved === 1 ? '' : 's'} saved before tip-off and never changed.`
    : 'The live record starts once the first forecasted games finish.'}</p>;
  const wins = Math.round(live.accuracy * live.games);
  const homeWins = Math.round(live.home_win_rate * live.games);
  return <section aria-label="Live record">
    <dl className="record-strip">
      <div><dt>Record since {shortDate(summary.first_live_date)}</dt><dd>{wins}–{live.games - wins}</dd></div>
      <div><dt>Correct picks</dt><dd>{pct(live.accuracy)}</dd></div>
      <div><dt>Always picking home</dt><dd>{homeWins}–{live.games - homeWins}</dd></div>
      <div><dt>Brier score</dt><dd>{live.brier.toFixed(3)}</dd></div>
    </dl>
    <p className="muted small record-note">Each forecast is saved before tip-off and never changed.
      {change && <> Model updated {shortDate(new Date(change.since).toLocaleDateString('en-CA', { timeZone: 'America/New_York' }))}: newer forecasts also count margin of victory and back-to-backs.</>}</p>
  </section>;
}

// One earlier day of the season, with how the forecasts did.
function PastDay({ date }) {
  const [state, setState] = useState({ loading: true });
  useEffect(() => {
    const controller = new AbortController();
    getData(`live/day?date=${date}`, controller.signal)
      .then((data) => setState({ games: data.games }))
      .catch((error) => { if (error.name !== 'AbortError') setState({ error: error.message }); });
    return () => controller.abort();
  }, [date]);
  if (state.loading) return <Loading label="Loading games"><GameSkeletons count={3} /></Loading>;
  if (state.error) return <div className="notice" role="alert"><p>{state.error}</p></div>;
  const finished = state.games.filter((g) => g.correct !== null);
  const live = finished.filter((g) => g.mode === 'live');
  const backfill = state.games.filter((g) => g.mode === 'backfill').length;
  return <section aria-label={`Games on ${longDate(date)}`}>
    <h2 className="day-heading">{finished.length
      ? <>{finished.filter((g) => g.correct).length} of {finished.length} correct</>
      : 'No final scores yet'}</h2>
    {backfill > 0 && <p className="muted small past-note">{backfill === state.games.length
      ? 'These games were scored afterward, using only results from before each game. They aren\'t part of the record.'
      : `${backfill} of these games were scored afterward and aren't part of the record; the other ${live.length} were saved before tip-off.`}</p>}
    <ul className="results">{state.games.map((game) => <ResultRow key={game.game_id} game={game} />)}</ul>
  </section>;
}

function DayNav({ shown, previous, next, isToday, onPick }) {
  return <div className="day-nav">
    <button className="round" aria-label="Previous day with games" disabled={!previous} onClick={() => onPick(previous)}>‹</button>
    <p className="lede day-nav-date" aria-live="polite">{longDate(shown)}</p>
    <button className="round" aria-label="Next day with games" disabled={!next} onClick={() => onPick(next)}>›</button>
    {!isToday && <button className="text-link" onClick={() => onPick(null)}>Back to today</button>}
  </div>;
}

function EmptyDay({ next, today }) {
  const count = next && `${next.games} game${next.games === 1 ? '' : 's'}`;
  // Before the morning job runs, today's games aren't forecast yet; say so instead of "no games".
  if (next && next.date === today) {
    return <section className="empty-day">
      <Court />
      <h2>Today's forecasts are on the way</h2>
      <p className="muted">There are {count} today. Forecasts post at about 9 a.m. Central, before any tip-off.</p>
    </section>;
  }
  return <section className="empty-day">
    <Court />
    <h2>No games today</h2>
    <p className="muted">{next
      ? <>Next up: {longDate(next.date)}, {count}. Forecasts post that morning.</>
      : <>Forecasts post each morning on game days.</>}</p>
  </section>;
}

export default function Tonight({ onArchive }) {
  const [state, setState] = useState({ loading: true });
  const [attempt, setAttempt] = useState(0);
  const [day, setDay] = useState(null); // null means today
  const [days, setDays] = useState([]);
  const [shownDays, setShownDays] = useState(1); // recent results: newest day first, more on request
  useEffect(() => {
    const controller = new AbortController();
    getData('live/days', controller.signal).then((data) => setDays(data.days.map((d) => d.date))).catch(() => {});
    return () => controller.abort();
  }, [attempt]);
  useEffect(() => {
    const controller = new AbortController();
    getData('live?recent=60', controller.signal)
      .then((data) => setState({ data }))
      .catch((error) => { if (error.name !== 'AbortError') setState({ error: error.message }); });
    return () => controller.abort();
  }, [attempt]);

  if (state.loading) return <Loading label="Loading today's games">
    <section className="intro"><div><span className="bone title" /><span className="bone shorter" /></div><span className="bone record-bone" /></section>
    <GameSkeletons />
  </Loading>;
  if (state.error) return <div className="notice" role="alert"><p>{state.error}</p>
    <div className="notice-actions"><button className="pill" onClick={() => { setState({ loading: true }); setAttempt((n) => n + 1); }}>Try again</button><button className="pill" onClick={onArchive}>Browse past seasons</button></div></div>;

  const { summary, upcoming, recent } = state.data;
  const today = upcoming[0]?.date;
  const todayDate = today || new Date().toLocaleDateString('en-CA', { timeZone: 'America/New_York' });
  const shown = day || todayDate;
  const yesterday = new Date(new Date(`${todayDate}T12:00:00Z`).getTime() - 864e5).toISOString().slice(0, 10);
  const previous = days.filter((d) => d < shown).at(-1);
  const next = day ? (days.find((d) => d > shown && d < todayDate) || todayDate) : null;
  const pick = (picked) => setDay(picked === todayDate ? null : picked);
  return <>
    <section className="today-head">
      <h1>{day ? 'Earlier this season' : upcoming.length ? `${upcoming.length} game${upcoming.length === 1 ? '' : 's'} tonight` : 'Today'}</h1>
      <DayNav shown={shown} previous={previous} next={next} isToday={!day} onPick={pick} />
      <RecordStrip summary={summary} change={state.data.model_change} saved={day ? 0 : upcoming.length} />
    </section>

    {day ? <PastDay key={day} date={day} /> : <>
    {upcoming.length === 0 && <EmptyDay next={summary.next_games} today={todayDate} />}
    {upcoming.length > 0 && <div className="tiles">{upcoming.map((game) => <MatchupTile key={game.game_id} game={game} />)}</div>}

    {recent.length > 0 && <section className="section recent" aria-label="Recent results">
      {byDate(recent).slice(0, shownDays).map((group) => {
        const hits = group.games.filter((game) => game.correct).length;
        return <div className="day" key={group.date}>
          <h2>{group.date === yesterday ? 'Yesterday' : longDate(group.date)}<span className="muted"> {hits} of {group.games.length} correct</span></h2>
          <ul className="results">{group.games.map((game) => <ResultRow key={game.game_id} game={game} />)}</ul>
        </div>;
      })}
      {byDate(recent).length > shownDays && <button className="pill show-more" onClick={() => setShownDays((n) => n + 2)}>Show earlier days</button>}
    </section>}

    </>}
    {summary.backfill.games > 0 && <p className="footnote">
      {summary.backfill.games} games from earlier this season were scored afterward, using only results from before each game. They aren't part of the record.
    </p>}
  </>;
}
