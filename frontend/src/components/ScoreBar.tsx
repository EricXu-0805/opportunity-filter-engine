interface ScoreBarProps {
  score: number;
  size?: 'sm' | 'md' | 'lg';
  showLabel?: boolean;
}

function getScoreColor(score: number): string {
  if (score >= 80) return 'from-emerald-400 to-emerald-300';
  if (score >= 60) return 'from-blue-400 to-blue-300';
  if (score >= 40) return 'from-amber-400 to-amber-300';
  return 'from-gray-300 to-gray-200';
}

function getScoreText(score: number): string {
  if (score >= 80) return 'text-emerald-600';
  if (score >= 60) return 'text-blue-600';
  if (score >= 40) return 'text-amber-600';
  return 'text-gray-500';
}

const HEIGHT_MAP = { sm: 'h-1', md: 'h-1.5', lg: 'h-2' } as const;

export default function ScoreBar({ score, size = 'md', showLabel = true }: ScoreBarProps) {
  const clamped = Math.max(0, Math.min(100, Math.round(score)));

  return (
    <div className="flex items-center gap-3">
      <div className={`flex-1 bg-black/[0.04] rounded-full overflow-hidden ${HEIGHT_MAP[size]}`}>
        <div
          className={`h-full rounded-full bg-gradient-to-r ${getScoreColor(clamped)} transition-all duration-700 ease-out`}
          style={{ width: `${clamped}%` }}
        />
      </div>
      {showLabel && (
        <span className={`text-sm font-semibold tabular-nums ${getScoreText(clamped)}`}>
          {clamped}%
        </span>
      )}
    </div>
  );
}
