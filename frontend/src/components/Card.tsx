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
      className={`bg-white rounded-3xl shadow-[0_2px_12px_rgba(0,0,0,0.06)] ${padding} ${className}`}
    >
      {children}
    </div>
  );
}
