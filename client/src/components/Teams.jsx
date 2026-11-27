import { useEffect, useState } from 'react';
import { MatchupTile } from './Slate';
import { RatingChart, Sparkline } from './Charts';
import { ListSkeletons, Loading } from './Skeleton';
import { getData } from '../services/nbaApi';
import teamLogos from '../utils/teamLogos';
import { teamInfo } from '../utils/teams';

const shortDate = (day) => new Date(`${day}T12:00:00`).toLocaleDateString('en-US', { month: 'short', day: 'numeric' });

function useData(path) {
  const [state, setState] = useState({ loading: true });
  const [attempt, setAttempt] = useState(0);
  useEffect(() => {
    const controller = new AbortController();
    getData(path, controller.signal)
      .then((data) => setState({ data }))
      .catch((error) => { if (error.name !== 'AbortError') setState({ error: error.message }); });
    return () => controller.abort();
  }, [path, attempt]);
  return [state, () => { setState({ loading: true }); setAttempt((n) => n + 1); }];
}

function TeamLogo({ team, size = 'small' }) {
  const [failed, setFailed] = useState(false);
  return <span className={`logo logo-${size}`}>{!failed && teamLogos[team]
    ? <img src={teamLogos[team]} alt="" loading="lazy" onError={() => setFailed(true)} /> : team}</span>;
}

function SeasonSelect({ value, seasons, onChange }) {
  if (seasons.length < 2) return null;
  return <select className="season-select" aria-label="Season" value={value} onChange={(event) => onChange(event.target.value)}>
    {seasons.map((s) => <option key={s} value={s}>{s}</option>)}</select>;
}

function TeamPage({ team, season, onSeason, onBack }) {
  const [state, retry] = useData(`teams/${team}${season ? `?season=${encodeURIComponent(season)}` : ''}`);
  const info = teamInfo(team);
  if (!state.data) return <>
    <button className="back" onClick={onBack}>All teams</button>
    {state.error ? <div className="notice" role="alert"><p>{state.error}</p><button className="pill" onClick={retry}>Try again</button></div>
      : <Loading label="Loading team"><span className="bone hero-bone" /></Loading>}
  </>;
  const data = state.data;
  const recent = [...data.games].reverse().slice(0, 10);
  return <section>
    <button className="back" onClick={onBack}>All teams</button>
    <header className="team-hero" style={{ '--team': info.color }}>
      <TeamLogo team={team} size="large" />
      <div className="team-hero-text">
        <p className="muted">{info.city}</p>
        <h1>{info.name}</h1>
        <p className="team-facts"><span>Ranked {data.rank} of 30</span><span>{data.wins}–{data.losses}</span><span>Rating {Math.round(data.rating)}</span></p>
      </div>
      <SeasonSelect value={data.season} seasons={data.seasons} onChange={onSeason} />
    </header>
    <section className="panel">
      <h2>Rating this season</h2>
      <RatingChart games={data.games} color={info.color} name={info.fullName} />
    </section>
    {data.upcoming.length > 0 && <section className="section">
      <h2>Next up</h2>
      <div className="tiles">{data.upcoming.map((game) => <MatchupTile key={game.game_id} game={game} />)}</div>
    </section>}
    {recent.length > 0 && <section className="panel">
      <h2>Last {recent.length} games</h2>
      <div className="table-scroll"><table className="boxscore"><caption className="sr-only">Most recent games, newest first</caption>
        <thead><tr><th scope="col">Date</th><th scope="col">Opponent</th><th scope="col">Result</th><th scope="col" className="num">Forecast</th><th scope="col" className="num">Rating</th></tr></thead>
        <tbody>{recent.map((g) => <tr key={g.game_id}>
          <th scope="row">{shortDate(g.date)}</th>
          <td>{g.home ? 'vs' : 'at'} {teamInfo(g.opponent).name}</td>
          <td><span className={`result-dot ${g.result === 'W' ? 'win' : 'loss'}`}>{g.result}</span> {g.score}</td>
          <td className="num">{Math.round(g.win_chance * 100)}%</td>
          <td className="num">{Math.round(g.rating)} <small className={g.rating >= g.rating_before ? 'up' : 'down'}>{g.rating >= g.rating_before ? '+' : ''}{Math.round(g.rating - g.rating_before)}</small></td>
        </tr>)}</tbody>
      </table></div>
    </section>}
  </section>;
}

export default function Teams() {
  const [season, setSeason] = useState('');
  const [team, setTeam] = useState(null);
  const [state, retry] = useData(`teams${season ? `?season=${encodeURIComponent(season)}` : ''}`);
  if (team) return <TeamPage key={`${team}-${season}`} team={team} season={season} onSeason={setSeason} onBack={() => setTeam(null)} />;
  return <>
    <section className="intro simple">
      <div><h1>Teams</h1><p className="lede">Every team ranked by its current rating. Pick a team to see how it got there.</p></div>
    </section>
    {!state.data ? (state.error
      ? <div className="notice" role="alert"><p>{state.error}</p><button className="pill" onClick={retry}>Try again</button></div>
      : <Loading label="Loading teams"><ListSkeletons /></Loading>)
      : <>
        <div className="toolbar"><SeasonSelect value={state.data.season} seasons={state.data.seasons} onChange={setSeason} />
          <p className="muted small">{state.data.season} season. Ratings start at 1,500; higher is stronger.</p></div>
        <ol className="team-list">{state.data.teams.map((row) => {
          const info = teamInfo(row.team);
          return <li key={row.team}><button className="team-row" onClick={() => setTeam(row.team)}>
            <span className="rank">{row.rank}</span>
            <TeamLogo team={row.team} />
            <span className="team-text"><strong>{info.name}</strong><small>{info.city}</small></span>
            <span className="record"><strong>{row.wins}–{row.losses}</strong><small>Last 10: {row.last10}</small></span>
            <Sparkline values={row.trend} color={info.color} />
            <span className="rating"><strong>{Math.round(row.rating)}</strong><small>rating</small></span>
          </button></li>;
        })}</ol>
      </>}
  </>;
}
