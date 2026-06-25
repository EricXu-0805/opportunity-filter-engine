import type { MatchBucket } from '@/lib/types';

interface ScoreBarProps {
  score: number;
  size?: 'sm' | 'md' | 'lg';
  showLabel?: boolean;
  /**
   * FE-3: when the caller knows the match bucket, the bar color is derived from
   * it so the bar always agrees with the bucket badge. The backend reassigns
   * buckets by percentile (not a fixed score cutoff), so deriving color from the
   * absolute score alone produced a green "High Priority" badge next to a blue
   * bar in the boundary bands. Without a bucket, fall back to score thresholds.
   */
  bucket?: MatchBucket;
}

const BUCKET_COLOR: Record<MatchBucket, { bar: string; text: string }> = {
  high_priority: { bar: 'from-emerald-400 to-emerald-300', text: 'text-emerald-600' },
  good_match: { bar: 'from-indigo-400 to-indigo-300', text: 'text-indigo-600' },
  reach: { bar: 'from-amber-400 to-amber-300', text: 'text-amber-600' },
  low_fit: { bar: 'from-gray-300 to-gray-200', text: 'text-gray-500' },
};

function getScoreColor(score: number): string {
  if (score >= 80) return 'from-emerald-400 to-emerald-300';
  if (score >= 60) return 'from-indigo-400 to-indigo-300';
  if (score >= 40) return 'from-amber-400 to-amber-300';
  return 'from-gray-300 to-gray-200';
}

function getScoreText(score: number): string {
  if (score >= 80) return 'text-emerald-600';
  if (score >= 60) return 'text-indigo-600';
  if (score >= 40) return 'text-amber-600';
  return 'text-gray-500';
}

const HEIGHT_MAP = { sm: 'h-1', md: 'h-1.5', lg: 'h-2' } as const;

export default function ScoreBar({ score, size = 'md', showLabel = true, bucket }: ScoreBarProps) {
  const clamped = Math.max(0, Math.min(100, Math.round(score)));
  const barColor = bucket ? BUCKET_COLOR[bucket].bar : getScoreColor(clamped);
  const textColor = bucket ? BUCKET_COLOR[bucket].text : getScoreText(clamped);

  return (
    <div className="flex items-center gap-3">
      <div className={`flex-1 bg-black/[0.04] rounded-full overflow-hidden ${HEIGHT_MAP[size]}`}>
        <div
          className={`h-full rounded-full bg-gradient-to-r ${barColor} transition-all duration-700 ease-out`}
          style={{ width: `${clamped}%` }}
        />
      </div>
      {showLabel && (
        <span className={`text-sm font-semibold tabular-nums ${textColor}`}>
          {clamped}%
        </span>
      )}
    </div>
  );
}
