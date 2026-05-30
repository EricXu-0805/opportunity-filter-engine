export function SummaryCard({
  label,
  count,
  accent,
}: {
  label: string;
  count: number;
  accent?: 'emerald' | 'blue' | 'amber';
}) {
  const textColor = accent
    ? { emerald: 'text-emerald-600', blue: 'text-blue-600', amber: 'text-amber-600' }[accent]
    : 'text-gray-900';

  return (
    <div className="bg-white rounded-2xl shadow-[0_1px_6px_rgba(0,0,0,0.04)] px-5 py-5">
      <p className={`text-3xl font-bold tabular-nums tracking-tight ${textColor}`}>{count}</p>
      <p className="text-[11px] font-medium text-gray-400 mt-1 uppercase tracking-wider">{label}</p>
    </div>
  );
}
