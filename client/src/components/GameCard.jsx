import { useEffect, useLayoutEffect, useRef, useState } from 'react';
import teamLogos from '../utils/teamLogos';
import { teamInfo } from '../utils/teams';
import { isEven } from '../utils/forecast';

const whole = (value) => `${Math.round(value * 100)}%`;
const tipoff = (iso) => new Date(iso).toLocaleTimeString('en-US', { hour: 'numeric', minute: '2-digit', timeZone: 'America/New_York' });

function Logo({ abbreviation }) {
  const [failed, setFailed] = useState(false);
  return <span className="logo">
    {!failed && teamLogos[abbreviation] ? <img src={teamLogos[abbreviation]} alt="" loading="lazy" onError={() => setFailed(true)} /> : abbreviation}
  </span>;
}

function TeamLine({ abbreviation, probability, score, favorite, winner, reveal, home }) {
  const team = teamInfo(abbreviation);
  return <div className={`team-line${favorite ? ' favorite' : ''}${reveal && !winner ? ' lost' : ''}`} style={{ '--team': team.color }}>
    <Logo abbreviation={abbreviation} />
    <span className="team-text"><strong>{team.name}</strong><small>{team.city}{home ? ', home' : ''}</small></span>
    {reveal ? <>
      <span className="chance">{whole(probability)}</span>
      <span className="score">{score}</span>
    </> : <span className="big-chance">{whole(probability)}</span>}
  </div>;
}

export { Logo };

// A short plain-English preview saved with the forecast (backend/previews.py).
// On small cards the text is capped at 3 lines; "More" appears only when something is cut off.
function CompactText({ text }) {
  const ref = useRef(null);
  const [open, setOpen] = useState(false);
  const [cut, setCut] = useState(false);
  useLayoutEffect(() => {
    const el = ref.current;
    if (!el || open) return undefined;
    const measure = () => setCut(el.scrollHeight > el.clientHeight + 1);
    measure();
    window.addEventListener('resize', measure);
    return () => window.removeEventListener('resize', measure);
  }, [text, open]);
  return <>
    <p ref={ref} className={`preview${open ? ' open' : ''}`}>{text}</p>
    {(cut || open) && <button className="more-toggle" aria-expanded={open} onClick={() => setOpen(!open)}>{open ? 'Less' : 'More'}</button>}
  </>;
}

export function Preview({ preview, compact = false }) {
  if (!preview) return null;
  if (compact) {
    return <>
      <CompactText text={preview.text} />
      {preview.source === 'ai' && <p className="ai-mark" title="Written by an AI model from this site's numbers, then checked automatically: every number must match, and no injury or betting talk.">AI-written, fact-checked</p>}
    </>;
  }
  return <p className="preview">{preview.text}
    {preview.source === 'ai' && <span className="preview-tag" title="Written by an AI model from this site's numbers, then checked automatically: every number must match, and no injury or betting talk.">AI-written, fact-checked</span>}
  </p>;
}

// The forecast's edge in Elo points, compared with the ratings plus home court, shows
// whether a back-to-back penalty was applied (stored ratings don't include it).
function restAdjustment(game) {
  const p = Math.min(Math.max(game.home_win_probability, 1e-9), 1 - 1e-9);
  const implied = 400 * Math.log10(p / (1 - p));
  const expected = game.home_rating - game.away_rating + (game.neutral_site ? 0 : 65);
  const gap = Math.round(implied - expected);
  return Math.abs(gap) < 5 ? null : { side: gap < 0 ? 'home' : 'away', points: Math.abs(gap) };
}

// Plain-English reasoning behind a forecast: ratings, home court and any back-to-back penalty.
export function WhyThisForecast({ game }) {
  const away = teamInfo(game.away_team);
  const home = teamInfo(game.home_team);
  const rest = restAdjustment(game);
  const tired = rest && (rest.side === 'home' ? home.name : away.name);
  return <p>{away.name} are rated {Math.round(game.away_rating)} and the {home.name} {Math.round(game.home_rating)}.
    {game.neutral_site ? ' Neither team gets a home-court boost at a neutral site.' : ' The home team gets a 65-point boost.'}
    {tired && ` The ${tired} played the night before, so they lose ${rest.points} points for this game.`}
    {' '}Ratings only count games from earlier days.{isEven(game) && ' When a game is a true 50/50, the home team counts as the pick.'}</p>;
}

export default function GameCard({ game, showResults = true, onExplore, animate = false }) {
  // Bars start even and grow to the forecast split once, when the card first appears.
  const [grown, setGrown] = useState(!animate);
  useEffect(() => {
    if (grown) return undefined;
    const frame = requestAnimationFrame(() => setGrown(true));
    return () => cancelAnimationFrame(frame);
  }, [grown]);
  const final = game.home_score != null;
  const reveal = final && showResults;
  const away = teamInfo(game.away_team);
  const home = teamInfo(game.home_team);
  const even = isEven(game);
  const homeFavored = !even && game.home_win_probability > 0.5;
  const awayFavored = !even && game.home_win_probability < 0.5;
  const status = final ? (showResults ? 'Final' : 'Result hidden') : `${tipoff(game.tipoff_utc)} ET`;
  return <article className="game-card" aria-label={`${away.fullName} at ${home.fullName}`}>
    <div className="game-meta">
      <span>{status}{game.neutral_site ? ', neutral site' : ''}</span>
      {reveal ? <span className={`badge ${game.correct ? 'hit' : 'miss'}`}>{game.correct ? 'Called it' : 'Missed'}</span>
        : even ? <span className="badge even">Even matchup</span> : null}
    </div>
    <div className="team-lines">
      <TeamLine abbreviation={game.away_team} probability={game.away_win_probability} score={game.away_score}
        favorite={awayFavored} winner={game.actual_winner === game.away_team} reveal={reveal} />
      <TeamLine abbreviation={game.home_team} probability={game.home_win_probability} score={game.home_score}
        favorite={homeFavored} winner={game.actual_winner === game.home_team} reveal={reveal} home />
    </div>
    <div className="split" role="img" aria-label={`Win chance: ${away.fullName} ${whole(game.away_win_probability)}, ${home.fullName} ${whole(game.home_win_probability)}`}>
      <span style={{ flexGrow: grown ? game.away_win_probability : 0.5, background: away.color }} />
      <span style={{ flexGrow: grown ? game.home_win_probability : 0.5, background: home.color }} />
    </div>
    {!final && <Preview preview={game.preview} compact />}
    {final && showResults && <Preview preview={game.recap} compact />}
    <div className="game-actions">
      <details>
        <summary>Why this forecast</summary>
        <WhyThisForecast game={game} />
      </details>
      {onExplore && <button className="text-link" onClick={onExplore}>Player matchups</button>}
    </div>
  </article>;
}
