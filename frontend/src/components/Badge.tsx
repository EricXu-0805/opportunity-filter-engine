import type { ReactNode } from 'react';

type BadgeVariant =
  | 'green'
  | 'red'
  | 'blue'
  | 'yellow'
  | 'orange'
  | 'gray'
  | 'indigo'
  | 'teal';

const VARIANT_CLASSES: Record<BadgeVariant, string> = {
  green: 'bg-emerald-50 text-emerald-700 ring-emerald-600/20',
  red: 'bg-red-50 text-red-700 ring-red-600/20',
  blue: 'bg-blue-50 text-blue-700 ring-blue-600/20',
  yellow: 'bg-amber-50 text-amber-700 ring-amber-600/20',
  orange: 'bg-orange-50 text-orange-700 ring-orange-600/20',
  gray: 'bg-gray-50 text-gray-600 ring-gray-500/20',
  indigo: 'bg-indigo-50 text-indigo-700 ring-indigo-600/20',
  teal: 'bg-teal-50 text-teal-700 ring-teal-600/20',
};

interface BadgeProps {
  variant: BadgeVariant;
  children: ReactNode;
  className?: string;
  dot?: boolean;
}

export default function Badge({ variant, children, className = '', dot }: BadgeProps) {
  return (
    <span
      className={`inline-flex items-center gap-1.5 px-2.5 py-0.5 rounded-full text-xs font-semibold ring-1 ring-inset ${VARIANT_CLASSES[variant]} ${className}`}
    >
      {dot && (
        <span
          className="w-1.5 h-1.5 rounded-full bg-current opacity-70"
          aria-hidden="true"
        />
      )}
      {children}
    </span>
  );
}
