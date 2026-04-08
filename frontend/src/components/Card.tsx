import type { ReactNode } from 'react';

interface CardProps {
  children: ReactNode;
  className?: string;
  padding?: string;
}

export default function Card({
  children,
  className = '',
  padding = 'p-8',
}: CardProps) {
  return (
    <div
      className={`bg-white border border-gray-200 rounded-2xl shadow-sm ${padding} ${className}`}
    >
      {children}
    </div>
  );
}
