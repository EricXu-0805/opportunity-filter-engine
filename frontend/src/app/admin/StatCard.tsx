'use client';

export function StatCard({
  label,
  value,
  color,
  pct,
  hint,
  delta,
  active,
  onClick,
}: {
  label: string;
  value: number;
  color: 'blue' | 'amber' | 'green' | 'gray';
  pct?: number;
  hint?: string;
  delta?: number | null;
  active?: boolean;
  onClick?: () => void;
}) {
  const colors = {
    blue: 'text-blue-700 bg-blue-50',
    amber: 'text-amber-700 bg-amber-50',
    green: 'text-emerald-700 bg-emerald-50',
    gray: 'text-gray-700 bg-gray-50',
  }[color];
  const className = `rounded-2xl p-4 transition-all ${colors} ${active ? 'ring-2 ring-blue-500 shadow-sm' : ''} ${onClick ? 'cursor-pointer hover:scale-[1.02]' : ''}`;
  const Tag = onClick ? 'button' : 'div';
  return (
    <Tag type={onClick ? 'button' : undefined} onClick={onClick} className={`${className} text-left w-full`}>
      <p className="text-[11px] font-semibold uppercase tracking-wider opacity-70">{label}</p>
      <p className="mt-1 text-2xl font-bold tabular-nums">{value.toLocaleString()}</p>
      {pct !== undefined && pct > 0 && (
        <p className="text-[11px] opacity-70">{pct.toFixed(1)}%</p>
      )}
      {hint && (
        <p className="text-[10px] opacity-60 mt-0.5 italic">{hint}</p>
      )}
      {typeof delta === 'number' && delta !== 0 && (
        <p className={`text-[10px] mt-1 font-medium ${delta > 0 ? 'text-red-600' : 'text-emerald-600'}`}>
          {delta > 0 ? `▲ +${delta}` : `▼ ${delta}`}
        </p>
      )}
    </Tag>
  );
}
