import { useEffect, useState } from 'react';
import GameCard, { Logo } from './GameCard';
import Court from './Court';
import { GameSkeletons, Loading } from './Skeleton';
import { getData } from '../services/nbaApi';
import { isEven } from '../utils/forecast';
import { teamInfo } from '../utils/teams';

const pct = (value) => `${(value * 100).toFixed(1)}%`;
const whole = (value) => `${Math.round(value * 100)}%`;
const longDate = (day) => new Date(`${day}T12:00:00`).toLocaleDateString('en-US', { weekday: 'long', month: 'long', day: 'numeric' });
const shortDate = (day) => new Date(`${day}T12:00:00`).toLocaleDateString('en-US', { month: 'long', day: 'numeric' });
const tipoff = (iso) => new Date(iso).toLocaleTimeString('en-US', { hour: 'numeric', minute: '2-digit', timeZone: 'America/New_York' });

function byDate(games) {
  const groups = [];
  for (const game of games) {
    const last = groups.at(-1);
    if (last && last.date === game.date) last.games.push(game);
    else groups.push({ date: game.date, games: [game] });
  }
  return groups;
}

function RecordCard({ summary, change }) {
  const live = summary.live;
  if (!live.games) return <aside className="record-card"><p className="muted">The live record starts once the first forecasted games finish.</p></aside>;
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
    {change && <p className="muted small model-change">Model updated {shortDate(new Date(change.since).toLocaleDateString('en-CA', { timeZone: 'America/New_York' }))}: newer forecasts also count margin of victory and back-to-backs. Earlier forecasts are unchanged.</p>}
  </aside>;
}

// The day's closest game, shown large with both teams' colors meeting in the middle.
function FeaturedGame({ game }) {
  const away = teamInfo(game.away_team);
  const home = teamInfo(game.home_team);
  const even = isEven(game);
  return <article className="featured" style={{ '--away': away.color, '--home': home.color }} aria-label={`Closest game today: ${away.fullName} at ${home.fullName}`}>
    <p className="featured-label">Closest game today, {tipoff(game.tipoff_utc)} ET</p>
    <div className="featured-teams">
      <div className={`featured-side${!even && game.away_win_probability > 0.5 ? ' favorite' : ''}`} style={{ '--team': away.color }}>
        <Logo abbreviation={game.away_team} />
        <span className="team-text"><strong>{away.name}</strong><small>{away.city}</small></span>
        <span className="featured-pct">{whole(game.away_win_probability)}</span>
      </div>
      <span className="featured-at" aria-hidden="true">{game.neutral_site ? 'vs' : 'at'}</span>
      <div className={`featured-side home${!even && game.home_win_probability > 0.5 ? ' favorite' : ''}`} style={{ '--team': home.color }}>
        <Logo abbreviation={game.home_team} />
        <span className="team-text"><strong>{home.name}</strong><small>{home.city}</small></span>
        <span className="featured-pct">{whole(game.home_win_probability)}</span>
      </div>
    </div>
    <div className="split big" aria-hidden="true">
      <span style={{ flexGrow: game.away_win_probability, background: away.color }} />
      <span style={{ flexGrow: game.home_win_probability, background: home.color }} />
    </div>
  </article>;
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
    <div className="card-grid">{state.games.map((game) => <GameCard key={game.game_id} game={game} />)}</div>
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

function EmptyDay({ next }) {
  return <section className="empty-day">
    <Court />
    <h2>No games today</h2>
    <p className="muted">{next
      ? <>Next up: {longDate(next.date)}, {next.games} game{next.games === 1 ? '' : 's'}. Forecasts post that morning.</>
      : <>Forecasts post each morning on game days.</>}</p>
  </section>;
}

export default function Tonight({ onArchive }) {
  const [state, setState] = useState({ loading: true });
  const [attempt, setAttempt] = useState(0);
  const [day, setDay] = useState(null); // null means today
  const [days, setDays] = useState([]);
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
  const featured = upcoming.length > 1
    ? upcoming.reduce((best, g) => (Math.abs(g.home_win_probability - 0.5) < Math.abs(best.home_win_probability - 0.5) ? g : best))
    : null;
  const others = upcoming.filter((g) => g !== featured);
  const todayDate = today || new Date().toLocaleDateString('en-CA', { timeZone: 'America/New_York' });
  const shown = day || todayDate;
  const previous = days.filter((d) => d < shown).at(-1);
  const next = day ? (days.find((d) => d > shown && d < todayDate) || todayDate) : null;
  const pick = (picked) => setDay(picked === todayDate ? null : picked);
  return <>
    <section className="intro">
      <div>
        <h1>{day ? 'Earlier this season' : today ? "Today's games" : 'Today'}</h1>
        <DayNav shown={shown} previous={previous} next={next} isToday={!day} onPick={pick} />
        <p className="intro-note">Each forecast is saved before tip-off and never changed, so the record can't be adjusted after the fact.</p>
      </div>
      <RecordCard summary={summary} change={state.data.model_change} />
    </section>

    {day ? <PastDay key={day} date={day} /> : <>
    {upcoming.length === 0 && <EmptyDay next={summary.next_games} />}
    {featured && <FeaturedGame game={featured} />}
    {others.length > 0 && <div className="card-grid">{others.map((game) => <GameCard key={game.game_id} game={game} animate />)}</div>}

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

    </>}
    {summary.backfill.games > 0 && <p className="footnote">
      {summary.backfill.games} games from earlier this season were scored afterward, using only results from before each game. They aren't part of the record.
    </p>}
  </>;
}
