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
  green: 'bg-emerald-50/80 text-emerald-600',
  red: 'bg-red-50/80 text-red-600',
  blue: 'bg-blue-50/80 text-blue-600',
  yellow: 'bg-amber-50/80 text-amber-600',
  orange: 'bg-orange-50/80 text-orange-600',
  gray: 'bg-gray-100/80 text-gray-500',
  indigo: 'bg-indigo-50/80 text-indigo-600',
  teal: 'bg-teal-50/80 text-teal-600',
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
      className={`inline-flex items-center gap-1.5 px-2.5 py-1 rounded-lg text-xs font-medium ${VARIANT_CLASSES[variant]} ${className}`}
    >
      {dot && (
        <span
          className="w-1.5 h-1.5 rounded-full bg-current opacity-60"
          aria-hidden="true"
        />
      )}
      {children}
    </span>
  );
}
