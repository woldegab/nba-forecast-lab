import { useEffect, useState } from 'react';
import GameCard from './components/GameCard';
import Players from './components/Players';
import Matchup from './components/Matchup';
import Tonight from './components/Tonight';
import Teams from './components/Teams';
import { CalibrationChart } from './components/Charts';
import { GameSkeletons, Loading } from './components/Skeleton';
import { getData } from './services/nbaApi';
import { teamInfo } from './utils/teams';
import './App.css';

const pct = (value) => `${(value * 100).toFixed(1)}%`;
const dateLabel = (date, options = { weekday: 'long', month: 'long', day: 'numeric', year: 'numeric' }) => new Date(`${date}T12:00:00`).toLocaleDateString('en-US', options);
const record = (accuracy, games) => { const wins = Math.round(accuracy * games); return `${wins.toLocaleString()}–${(games - wins).toLocaleString()}`; };
const views = [['tonight', 'Today'], ['teams', 'Teams'], ['archive', 'Past seasons'], ['players', 'Players'], ['model', 'How it works']];

function currentTheme() {
  const chosen = document.documentElement.dataset.theme;
  if (chosen) return chosen;
  return window.matchMedia?.('(prefers-color-scheme: dark)').matches ? 'dark' : 'light';
}

// Follows the device setting until the visitor picks one; the pick is remembered.
function ThemeToggle() {
  const [theme, setTheme] = useState(currentTheme);
  useEffect(() => {
    const media = window.matchMedia?.('(prefers-color-scheme: dark)');
    const follow = () => { if (!document.documentElement.dataset.theme) setTheme(currentTheme()); };
    media?.addEventListener('change', follow);
    return () => media?.removeEventListener('change', follow);
  }, []);
  useEffect(() => {
    document.body.classList.toggle('dark-ui', theme === 'dark');
    document.querySelectorAll('meta[name="theme-color"]').forEach((meta) => { meta.content = theme === 'dark' ? '#17181b' : '#ffffff'; });
  }, [theme]);
  const flip = () => {
    const next = theme === 'dark' ? 'light' : 'dark';
    document.documentElement.dataset.theme = next;
    try { localStorage.setItem('theme', next); } catch { /* private browsing: just don't remember */ }
    setTheme(next);
  };
  return <button className="theme-toggle" onClick={flip} aria-label={theme === 'dark' ? 'Switch to light mode' : 'Switch to dark mode'} title={theme === 'dark' ? 'Light mode' : 'Dark mode'}>
    {theme === 'dark'
      ? <svg viewBox="0 0 24 24" aria-hidden="true"><circle cx="12" cy="12" r="4" /><path d="M12 2v2M12 20v2M4.9 4.9l1.4 1.4M17.7 17.7l1.4 1.4M2 12h2M20 12h2M4.9 19.1l1.4-1.4M17.7 6.3l1.4-1.4" /></svg>
      : <svg viewBox="0 0 24 24" aria-hidden="true"><path d="M20 14.5A8 8 0 0 1 9.5 4a8 8 0 1 0 10.5 10.5z" /></svg>}
  </button>;
}

function Retry({ message, onRetry }) {
  return <div className="notice" role="alert"><p>{message}</p><button className="pill" onClick={onRetry}>Try again</button></div>;
}

function useArchive() {
  const [state, setState] = useState({ loading: true });
  const [attempt, setAttempt] = useState(0);
  useEffect(() => {
    const controller = new AbortController();
    Promise.all([getData('seasons', controller.signal), getData('model-performance', controller.signal)])
      .then(([available, report]) => {
        if (!available.seasons.length) throw new Error('No past seasons yet. Run backend/evaluate_elo.py.');
        setState({ data: { ...available, report } });
      }).catch((error) => { if (error.name !== 'AbortError') setState({ error: error.message }); });
    return () => controller.abort();
  }, [attempt]);
  return [state, () => { setState({ loading: true }); setAttempt((n) => n + 1); }];
}

function Slate({ date, controls }) {
  const [state, setState] = useState({ loading: true });
  const [attempt, setAttempt] = useState(0);
  const [matchup, setMatchup] = useState(null);
  const [query, setQuery] = useState('');
  const [filter, setFilter] = useState('all');
  const [showResults, setShowResults] = useState(true);
  useEffect(() => {
    const controller = new AbortController();
    getData(`games?date=${encodeURIComponent(date)}`, controller.signal)
      .then((data) => setState({ games: data.games }))
      .catch((error) => { if (error.name !== 'AbortError') setState({ error: error.message }); });
    return () => controller.abort();
  }, [date, attempt]);
  if (matchup) return <Matchup key={matchup.game_id} game={matchup} showResults={showResults} onShowResults={setShowResults} onBack={() => setMatchup(null)} />;
  if (state.loading) return <><div className="toolbar sticky">{controls}</div><Loading label="Loading games"><span className="bone day-bone" /><GameSkeletons /></Loading></>;
  if (state.error) return <><div className="toolbar sticky">{controls}</div><Retry message={state.error} onRetry={() => { setState({ loading: true }); setAttempt((n) => n + 1); }} /></>;
  const search = query.trim().toLowerCase();
  const visible = state.games.filter((game) =>
    [game.home_team, game.away_team, teamInfo(game.home_team).fullName, teamInfo(game.away_team).fullName].some((team) => team.toLowerCase().includes(search))
    && (filter === 'all' || !showResults || (filter === 'hit' ? game.correct : !game.correct)));
  const hits = state.games.filter((game) => game.correct).length;
  return <section>
    <div className="toolbar sticky">
      {controls}
      <div className="chips" role="group" aria-label="Filter by result">{[['all', 'All games'], ['hit', 'Called it'], ['miss', 'Missed']].map(([id, label]) =>
        <button key={id} className="chip" disabled={!showResults && id !== 'all'} aria-pressed={filter === id} onClick={() => setFilter(id)}>{label}</button>)}</div>
      <input className="search" type="search" aria-label="Search teams" placeholder="Search teams" value={query} onChange={(event) => setQuery(event.target.value)} />
      <label className="switch"><input type="checkbox" role="switch" checked={showResults} onChange={(event) => { setShowResults(event.target.checked); setFilter('all'); }} /><span aria-hidden="true" />Show results</label>
    </div>
    <h2 className="day-heading">{dateLabel(date)}{showResults && state.games.length > 0 && <span className="muted"> {hits} of {state.games.length} correct</span>}</h2>
    {!state.games.length ? <p className="empty">No games on this date. Use the arrows to find the next game day.</p>
      : !visible.length ? <p className="empty">No games match. <button className="text-link" onClick={() => { setQuery(''); setFilter('all'); }}>Clear filters</button></p>
      : <div className="card-grid">{visible.map((game) => <GameCard key={game.game_id} game={game} showResults={showResults} onExplore={() => setMatchup(game)} />)}</div>}
  </section>;
}

function Archive({ data }) {
  const initial = data.seasons.find((item) => item.season === data.report.test_season) || data.seasons[0];
  const [season, setSeason] = useState(initial.season);
  const [date, setDate] = useState(initial.first_date);
  const selected = data.seasons.find((item) => item.season === season);
  const result = data.report.results[season];
  const previous = selected.dates.filter((day) => day < date).at(-1);
  const next = selected.dates.find((day) => day > date);
  return <>
    <section className="intro simple">
      <div>
        <h1>Past seasons</h1>
        <p className="lede">Every game from three seasons, forecast one day at a time using only earlier results.</p>
      </div>
    </section>
    <p className="season-summary">{result
      ? <>{season} ({selected.phase === 'Initial test' ? 'held-out test' : selected.phase.toLowerCase()}): the model went <strong>{record(result.elo.accuracy, result.games)}</strong>, {pct(result.elo.accuracy)} correct. Picking the home team every time: {pct(result.always_pick_designated_home_accuracy)}.</>
      : <>{season} (warm-up) sets the starting ratings, so it isn't scored.</>}</p>
    <Slate key={date} date={date} controls={<>
      <select className="season-select" aria-label="Season" value={season} onChange={(event) => { const item = data.seasons.find((s) => s.season === event.target.value); setSeason(item.season); setDate(item.first_date); }}>
        {data.seasons.map((item) => <option key={item.season} value={item.season}>{item.season}</option>)}
      </select>
      <div className="date-picker">
        <button className="round" aria-label="Previous game day" disabled={!previous} onClick={() => setDate(previous)}>‹</button>
        <input type="date" aria-label="Game date" value={date} min={selected.first_date} max={selected.last_date}
          onChange={(event) => { const day = event.target.value; if (day >= selected.first_date && day <= selected.last_date) setDate(selected.dates.find((d) => d >= day) || selected.last_date); }} />
        <button className="round" aria-label="Next game day" disabled={!next} onClick={() => setDate(next)}>›</button>
      </div>
      <span className="toolbar-divider" aria-hidden="true" />
    </>} />
  </>;
}

function Model({ data }) {
  const { report } = data;
  const [live, setLive] = useState(null);
  const [calibration, setCalibration] = useState(null);
  useEffect(() => {
    const controller = new AbortController();
    getData('live?recent=0', controller.signal).then((body) => setLive(body.summary)).catch(() => {});
    getData('calibration', controller.signal).then(setCalibration).catch(() => {});
    return () => controller.abort();
  }, []);
  const series = calibration ? [
    { name: `Past seasons, ${calibration.archive.seasons[0]} to ${calibration.archive.seasons.at(-1)}`, className: 'archive', games: calibration.archive.games, buckets: calibration.archive.buckets },
    ...(calibration.live.games >= 30 ? [{ name: `Live ${calibration.live.season}`, className: 'live', games: calibration.live.games, buckets: calibration.live.buckets }] : []),
  ] : [];
  const rows = Object.entries(report.results).map(([season, r]) => ({ season, phase: season === report.test_season ? 'Held-out test' : 'Development',
    games: r.games, accuracy: r.elo.accuracy, home: r.always_pick_designated_home_accuracy, brier: r.elo.brier }));
  if (live?.live?.games) rows.push({ season: live.season, phase: 'Live, saved before tip-off', games: live.live.games, accuracy: live.live.accuracy, home: live.live.home_win_rate, brier: live.live.brier });
  const p = report.parameters;
  const steps = [
    ['Every team gets a rating', `Teams start at ${p.initial_rating.toLocaleString()}. The ${report.warmup_season} season sets the first real ratings.`],
    ['Compare ratings before each game', `The bigger the gap, the bigger the favorite. Home teams get ${p.home_advantage} extra points; neutral sites get none.`],
    ['Update after each day', `Winners take points from losers, more for an upset. Games on the same day never affect each other.`],
    ['Reset a little each summer', `Ratings keep ${p.retention * 100}% of their distance from average between seasons.`],
  ];
  return <>
    <section className="intro simple"><div><h1>How it works</h1><p className="lede">A simple rating system, judged on games it hadn't seen.</p></div></section>
    <div className="season-cards">{rows.map((row) => <article className="stat-card" key={row.season}>
      <p className="muted">{row.season}, {row.phase.toLowerCase()}</p>
      <p className="stat-big">{pct(row.accuracy)}</p>
      <p>correct across {row.games.toLocaleString()} games ({record(row.accuracy, row.games)})</p>
      <div className="compare">
        <div><span>Model</span><span className="track"><span style={{ width: pct(row.accuracy) }} /></span></div>
        <div><span>Home team</span><span className="track muted-track"><span style={{ width: pct(row.home) }} /></span></div>
      </div>
      <p className="muted small">Brier score {row.brier.toFixed(3)}</p>
    </article>)}</div>
    <p className="footnote">Brier score measures how good the probabilities are, not just the picks. Lower is better; guessing 50/50 every game scores 0.250.</p>
    {series.length > 0 && <section className="section calibration-section">
      <div>
        <h2>Do the percentages mean what they say?</h2>
        <p>Games are grouped by how confident the forecast was. If the model is honest, favorites given 70% should win about 70% of the time, so the dots should sit near the dashed line.</p>
        <p className="muted small">Bigger dots are groups with more games. Hover a dot for the numbers.</p>
      </div>
      <CalibrationChart series={series} />
    </section>}
    <section className="section">
      <h2>The model in four steps</h2>
      <ol className="steps">{steps.map(([title, text]) => <li key={title}><h3>{title}</h3><p>{text}</p></li>)}</ol>
    </section>
    <section className="section narrow">
      <h2>What it doesn't know</h2>
      <p>Injuries, lineups, rest days, travel and player stats. Past-season forecasts are rebuilt from today's records, not saved at the time. That's why the live record exists: it can't be rebuilt after the fact.</p>
    </section>
  </>;
}

export default function App() {
  const [view, setView] = useState('tonight');
  const [archive, retryArchive] = useArchive();
  const needsArchive = view === 'archive' || view === 'model';
  return <div className="app">
    <a className="skip-link" href="#main">Skip to content</a>
    <header className="header">
      <button className="wordmark" onClick={() => setView('tonight')} aria-label="Forecast Lab home">
        <svg viewBox="0 0 32 32" aria-hidden="true"><circle cx="16" cy="16" r="14" /><path d="M2 16h28M16 2v28M6.5 6.5c7 4 7 15 0 19M25.5 6.5c-7 4-7 15 0 19" /></svg>
        Forecast Lab
      </button>
      <nav className="nav" aria-label="Main">{views.map(([id, label]) => <button key={id} aria-current={view === id ? 'page' : undefined} onClick={() => setView(id)}>{label}</button>)}</nav>
      <ThemeToggle />
    </header>
    <main id="main" className="main">
      {view === 'tonight' && <Tonight onArchive={() => setView('archive')} />}
      {view === 'teams' && <Teams />}
      {view === 'players' && <Players />}
      {needsArchive && (archive.loading ? <Loading label="Loading"><section className="intro simple"><div><span className="bone title" /><span className="bone shorter" /></div></section><GameSkeletons count={3} /></Loading>
        : archive.error ? <Retry message={archive.error} onRetry={retryArchive} />
        : view === 'archive' ? <Archive data={archive.data} /> : <Model data={archive.data} />)}
    </main>
    <footer className="footer">Forecast Lab is an independent student project. Not affiliated with the NBA.</footer>
  </div>;
}
