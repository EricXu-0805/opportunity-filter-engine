interface ScoreBarProps {
  score: number; // 0–100
  size?: 'sm' | 'md' | 'lg';
  showLabel?: boolean;
}

function getScoreColor(score: number): string {
  if (score >= 80) return 'from-emerald-500 to-emerald-400';
  if (score >= 60) return 'from-blue-500 to-blue-400';
  if (score >= 40) return 'from-amber-500 to-amber-400';
  return 'from-gray-400 to-gray-300';
}

function getScoreBg(score: number): string {
  if (score >= 80) return 'bg-emerald-50';
  if (score >= 60) return 'bg-blue-50';
  if (score >= 40) return 'bg-amber-50';
  return 'bg-gray-50';
}

function getScoreText(score: number): string {
  if (score >= 80) return 'text-emerald-700';
  if (score >= 60) return 'text-blue-700';
  if (score >= 40) return 'text-amber-700';
  return 'text-gray-600';
}

const HEIGHT_MAP = { sm: 'h-1.5', md: 'h-2', lg: 'h-3' } as const;

export default function ScoreBar({ score, size = 'md', showLabel = true }: ScoreBarProps) {
  const clamped = Math.max(0, Math.min(100, Math.round(score)));

  return (
    <div className="flex items-center gap-3">
      <div className={`flex-1 ${getScoreBg(clamped)} rounded-full overflow-hidden ${HEIGHT_MAP[size]}`}>
        <div
          className={`h-full rounded-full bg-gradient-to-r ${getScoreColor(clamped)} transition-all duration-500 ease-out`}
          style={{ width: `${clamped}%` }}
        />
      </div>
      {showLabel && (
        <span className={`text-sm font-bold tabular-nums ${getScoreText(clamped)}`}>
          {clamped}%
        </span>
      )}
    </div>
  );
}
