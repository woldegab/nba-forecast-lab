// Gray placeholders shaped like the content, shown while data loads
// (the free host can take up to a minute to wake up).
export function GameSkeletons({ count = 6 }) {
  return <div className="card-grid" aria-hidden="true">{Array.from({ length: count }, (_, i) =>
    <div className="game-card skeleton-card" key={i}>
      <span className="bone short" />
      <span className="bone row" />
      <span className="bone row" />
      <span className="bone thin" />
    </div>)}</div>;
}

export function PlayerSkeletons({ count = 8 }) {
  return <div className="player-grid" aria-hidden="true">{Array.from({ length: count }, (_, i) =>
    <div className="player-card" key={i}>
      <span className="bone photo" />
      <span className="bone short" />
      <span className="bone shorter" />
    </div>)}</div>;
}

export function ListSkeletons({ count = 8 }) {
  return <div className="team-list" aria-hidden="true">{Array.from({ length: count }, (_, i) =>
    <span className="bone list-row" key={i} />)}</div>;
}

export function Loading({ label, children }) {
  return <div role="status" aria-live="polite"><span className="sr-only">{label}</span>{children}</div>;
}
