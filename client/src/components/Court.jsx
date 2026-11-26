// A simple half-court line drawing for days without games.
export default function Court() {
  return <svg className="court-art" viewBox="0 0 300 180" aria-hidden="true">
    <rect x="10" y="10" width="280" height="160" rx="4" />
    <line x1="150" y1="10" x2="150" y2="170" />
    <circle cx="150" cy="90" r="26" />
    <rect x="10" y="58" width="58" height="64" />
    <rect x="232" y="58" width="58" height="64" />
    <path d="M10 26 H40 A64 64 0 0 1 40 154 H10" />
    <path d="M290 26 H260 A64 64 0 0 0 260 154 H290" />
    <circle cx="22" cy="90" r="5" />
    <circle cx="278" cy="90" r="5" />
  </svg>;
}
