import { Logo, Preview, WhyThisForecast } from './GameCard';
import { teamInfo } from '../utils/teams';
import { isEven } from '../utils/forecast';

const whole = (value) => `${Math.round(value * 100)}%`;
const tipoff = (iso) => new Date(iso).toLocaleTimeString('en-US', { hour: 'numeric', minute: '2-digit', timeZone: 'America/New_York' });

// An upcoming game as a tile: the two teams' colors and win chances up top,
// then a short caption with the pick and the AI preview.
export function MatchupTile({ game }) {
  const away = teamInfo(game.away_team);
  const home = teamInfo(game.home_team);
  const even = isEven(game);
  const homeFavored = game.home_win_probability >= 0.5;
  const pick = homeFavored ? home : away;
  const pickChance = Math.max(game.home_win_probability, game.away_win_probability);
  const side = (abbreviation, chance, favorite) => <div className={`tile-side${favorite ? ' favorite' : ''}`}>
    <Logo abbreviation={abbreviation} />
    <span className="tile-pct">{whole(chance)}</span>
  </div>;
  return <article className="tile" aria-label={`${away.fullName} at ${home.fullName}`}>
    <div className="tile-art" style={{ '--away': away.color, '--home': home.color }} role="img"
      aria-label={`Win chance: ${away.name} ${whole(game.away_win_probability)}, ${home.name} ${whole(game.home_win_probability)}`}>
      <span className="tile-time">{tipoff(game.tipoff_utc)} ET</span>
      {side(game.away_team, game.away_win_probability, !even && !homeFavored)}
      {side(game.home_team, game.home_win_probability, !even && homeFavored)}
    </div>
    <h3>{away.name} at {home.name}{game.neutral_site ? ' (neutral site)' : ''}</h3>
    <p className="tile-pick">{even ? 'Toss-up' : `${pick.name} favored, ${whole(pickChance)}`}</p>
    <Preview preview={game.preview} compact />
    <details className="why">
      <summary>Why this forecast</summary>
      <WhyThisForecast game={game} />
    </details>
  </article>;
}

// A finished (or not yet played) game as one row of a results list.
export function ResultRow({ game }) {
  const away = teamInfo(game.away_team);
  const home = teamInfo(game.home_team);
  const final = game.home_score != null;
  const line = (abbreviation, team, chance, score, isHome) => {
    const won = final && game.actual_winner === abbreviation;
    return <div className={`result-line${won ? ' won' : ''}${final && !won ? ' lost' : ''}`}>
      <Logo abbreviation={abbreviation} />
      <span className="result-name">{team.name}</span>
      <span className="result-chance">{whole(chance)} chance{isHome ? ', home' : ''}</span>
      <span className="result-score">{final ? score : ''}</span>
    </div>;
  };
  return <li className="result" aria-label={`${away.fullName} at ${home.fullName}`}>
    <div className="result-status">
      {final ? 'Final' : `${tipoff(game.tipoff_utc)} ET`}
      {final && game.correct !== null && <span className={game.correct ? 'hit' : 'miss'}>{game.correct ? 'Called it' : 'Missed'}</span>}
    </div>
    <div className="result-body">
      {line(game.away_team, away, game.away_win_probability, game.away_score, false)}
      {line(game.home_team, home, game.home_win_probability, game.home_score, true)}
      {final && <Preview preview={game.recap} compact />}
      <details className="why">
        <summary>Why this forecast</summary>
        <WhyThisForecast game={game} />
      </details>
    </div>
  </li>;
}
