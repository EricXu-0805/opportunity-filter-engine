import Link from 'next/link';
import { Sparkles } from 'lucide-react';

export default function NotFound() {
  return (
    <div className="flex flex-col items-center justify-center min-h-[70vh] gap-6 px-4">
      <p className="text-7xl font-bold text-gray-200 tabular-nums">404</p>
      <p className="text-[17px] text-gray-500 text-center">
        This page doesn&apos;t exist.
      </p>
      <Link
        href="/"
        className="inline-flex items-center gap-2 px-5 py-2.5 text-[13px] font-semibold text-white bg-blue-600 rounded-full hover:bg-blue-700 transition-colors"
      >
        <Sparkles className="w-3.5 h-3.5" />
        Back to Home
      </Link>
    </div>
  );
}
