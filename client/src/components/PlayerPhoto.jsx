import { useState } from 'react';
import teamLogos from '../utils/teamLogos';

export default function PlayerPhoto({ id, name, large = false, card = false, color, team }) {
  const [failedSource, setFailedSource] = useState(null);
  const source = `https://cdn.nba.com/headshots/nba/latest/260x190/${id}.png`;
  const initials = name.split(' ').filter(Boolean).slice(0, 2).map((word) => word[0]).join('');
  const size = card ? ' player-photo-card' : large ? ' player-photo-large' : '';
  return <span className={`player-photo${size}`} style={color ? { '--team': color } : undefined}>
    {team && teamLogos[team] && <img className="photo-watermark" src={teamLogos[team]} alt="" aria-hidden="true" loading="lazy" onError={(event) => { event.currentTarget.hidden = true; }} />}
    <span className="photo-initials" aria-hidden="true">{initials}</span>
    {id && failedSource !== source && <img
      src={source}
      alt={card ? '' : `${name} headshot`}
      loading={large ? 'eager' : 'lazy'}
      decoding="async"
      width="260"
      height="190"
      onError={() => setFailedSource(source)}
    />}
  </span>;
}
