import { useEffect, useState } from 'react';
import PlayerPhoto from './PlayerPhoto';
import { getData } from '../services/nbaApi';
import { teamInfo } from '../utils/teams';

const windows = [['5', 'Last 5'], ['10', 'Last 10'], ['season', 'Season']];
const columns = [['points', 'Points'], ['rebounds', 'Rebounds'], ['assists', 'Assists'], ['minutes', 'Minutes']];

function WindowControls({ value, onChange }) {
  return <div className="segmented" role="group" aria-label="Games included">{windows.map(([key, label]) =>
    <button key={key} aria-pressed={value === key} onClick={() => onChange(key)}>{label}</button>)}</div>;
}

function useLoad(path, deps) {
  const [state, setState] = useState({ loading: true });
  const [attempt, setAttempt] = useState(0);
  useEffect(() => {
    const controller = new AbortController();
    getData(path, controller.signal)
      .then((data) => setState({ data }))
      .catch((error) => { if (error.name !== 'AbortError') setState({ error: error.message }); });
    return () => controller.abort();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [...deps, attempt]);
  return [state, () => { setState({ loading: true }); setAttempt((n) => n + 1); }];
}

function Loading({ state, retry, label }) {
  if (state.error) return <div className="notice" role="alert"><p>{state.error}</p><button className="pill" onClick={retry}>Try again</button></div>;
  return <p className="notice" role="status">{label}</p>;
}

function PlayerDetail({ id, season, window, onWindow, onBack }) {
  const [state, retry] = useLoad(`players/${id}?season=${encodeURIComponent(season)}&window=${window}`, [id, season, window]);
  if (!state.data) return <><button className="back" onClick={onBack}>All players</button><Loading state={state} retry={retry} label="Loading games…" /></>;
  const player = state.data;
  const chronological = [...player.games].reverse();
  const maximum = Math.max(...chronological.map((game) => game.points), 1);
  return <section>
    <button className="back" onClick={onBack}>All players</button>
    <header className="player-head">
      <PlayerPhoto id={player.player_id} name={player.name} large color={teamInfo(player.team).color} />
      <div><h1>{player.name}</h1><p className="lede">{teamInfo(player.team).fullName}, {season} regular season</p></div>
    </header>
    <WindowControls value={window} onChange={onWindow} />
    <dl className="statline">{columns.map(([key, label]) =>
      <div key={key}><dt>{label}</dt><dd>{player.averages[key].toFixed(1)}</dd></div>)}</dl>
    <p className="footnote">Averages over {player.sample_games} {player.sample_games === 1 ? 'game' : 'games'}. Games missed are skipped, not counted as zero.</p>
    <section className="panel">
      <h2>Points by game</h2><p className="muted small">Oldest to newest</p>
      <div className="spark" role="img" aria-label={`Points per game, oldest to newest: ${chronological.map((game) => game.points).join(', ')}`}>
        {chronological.map((game) => <div key={game.game_id}><span style={{ height: `${game.points / maximum * 100}%` }} /><b>{game.points}</b><small>{game.game_date.slice(5).replace('-', '/')}</small></div>)}
      </div>
    </section>
    <section className="panel">
      <h2>Game log</h2>
      <div className="table-scroll"><table className="boxscore"><caption className="sr-only">Games, newest first</caption>
        <thead><tr><th scope="col">Date</th><th scope="col">Matchup</th><th scope="col">Result</th><th scope="col" className="num">MIN</th><th scope="col" className="num">PTS</th><th scope="col" className="num">REB</th><th scope="col" className="num">AST</th></tr></thead>
        <tbody>{player.games.map((game) => <tr key={game.game_id}><th scope="row">{game.game_date}</th><td>{game.matchup}</td><td>{game.result}</td>
          <td className="num">{game.minutes.toFixed(0)}</td><td className="num strong">{game.points}</td><td className="num">{game.rebounds}</td><td className="num">{game.assists}</td></tr>)}</tbody>
      </table></div>
    </section>
  </section>;
}

const sorts = [['points', 'Points'], ['rebounds', 'Rebounds'], ['assists', 'Assists']];

function PlayerCard({ player, onSelect }) {
  return <button className="player-card" onClick={() => onSelect(player.player_id)}>
    <PlayerPhoto id={player.player_id} name={player.name} card color={teamInfo(player.team).color} />
    <span className="player-card-text">
      <strong>{player.name}</strong>
      <small>{teamInfo(player.team).fullName}</small>
      <span className="player-card-stats">
        <span><b>{player.points.toFixed(1)}</b> pts</span>
        <span><b>{player.rebounds.toFixed(1)}</b> reb</span>
        <span><b>{player.assists.toFixed(1)}</b> ast</span>
      </span>
    </span>
  </button>;
}

export default function Players() {
  const [window, setWindow] = useState('10');
  const [season, setSeason] = useState('');
  const [query, setQuery] = useState('');
  const [team, setTeam] = useState('all');
  const [sort, setSort] = useState('points');
  const [shown, setShown] = useState(24);
  const [selected, setSelected] = useState(null);
  const [state, retry] = useLoad(`players?window=${window}${season ? `&season=${encodeURIComponent(season)}` : ''}`, [season, window]);
  if (!state.data) return <><section className="intro simple"><div><h1>Players</h1></div></section><Loading state={state} retry={retry} label="Loading players…" /></>;
  const data = state.data;
  if (selected) return <PlayerDetail key={`${selected}-${data.season}-${window}`} id={selected} season={data.season} window={window} onWindow={setWindow} onBack={() => setSelected(null)} />;
  const teams = [...new Set(data.players.map((player) => player.team))].sort();
  const search = query.trim().toLowerCase();
  const visible = data.players
    .filter((player) => player.name.toLowerCase().includes(search) && (team === 'all' || player.team === team))
    .sort((a, b) => b[sort] - a[sort] || a.name.localeCompare(b.name));
  return <>
    <section className="intro simple"><div><h1>Players</h1><p className="lede">Averages from {data.season} game logs. Pick a player to see every game.</p></div></section>
    <div className="search-bar">
      <label><span>Player</span><input type="search" placeholder="Search by name" value={query} onChange={(event) => { setQuery(event.target.value); setShown(24); }} /></label>
      <label><span>Team</span><select value={team} onChange={(event) => { setTeam(event.target.value); setShown(24); }}><option value="all">All teams</option>{teams.map((value) => <option key={value} value={value}>{teamInfo(value).fullName}</option>)}</select></label>
      <label><span>Season</span><select value={data.season} onChange={(event) => { setTeam('all'); setSeason(event.target.value); }}>{data.seasons.map((value) => <option key={value}>{value}</option>)}</select></label>
    </div>
    <div className="toolbar">
      <div className="chips" role="group" aria-label="Sort by">{sorts.map(([key, label]) => <button key={key} className="chip" aria-pressed={sort === key} onClick={() => setSort(key)}>{label}</button>)}</div>
      <WindowControls value={window} onChange={setWindow} />
    </div>
    <p className="muted small" role="status">{visible.length} players, sorted by {sorts.find(([key]) => key === sort)[1].toLowerCase()}</p>
    {visible.length ? <>
      <div className="player-grid">{visible.slice(0, shown).map((player) => <PlayerCard key={player.player_id} player={player} onSelect={setSelected} />)}</div>
      {shown < visible.length && <div className="more"><button className="pill" onClick={() => setShown((n) => n + 24)}>Show more players</button></div>}
    </> : <p className="empty">No players match. <button className="text-link" onClick={() => { setQuery(''); setTeam('all'); }}>Clear filters</button></p>}
  </>;
}
