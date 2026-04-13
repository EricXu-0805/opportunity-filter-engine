'use client';

import Link from 'next/link';
import { usePathname } from 'next/navigation';
import { Sparkles } from 'lucide-react';

const NAV_ITEMS = [
  { href: '/', label: 'Find Matches' },
  { href: '/favorites', label: 'Favorites' },
  { href: '/dashboard', label: 'Dashboard' },
  { href: '/about', label: 'About' },
] as const;

export default function Header() {
  const pathname = usePathname();

  return (
    <header className="fixed top-0 left-0 right-0 z-50 bg-white/70 backdrop-blur-xl backdrop-saturate-150 border-b border-black/[0.06]">
      <div className="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8">
        <div className="flex items-center justify-between h-12">
          <Link href="/" className="flex items-center gap-2 group">
            <div className="w-7 h-7 rounded-lg bg-gradient-to-br from-blue-600 to-blue-500 flex items-center justify-center">
              <Sparkles className="w-3.5 h-3.5 text-white" strokeWidth={2.5} />
            </div>
            <span className="text-[15px] font-semibold text-gray-900 tracking-tight">
              Opportunity<span className="text-blue-600">Engine</span>
            </span>
          </Link>

          <nav className="flex items-center gap-0.5">
            {NAV_ITEMS.map(({ href, label }) => {
              const isActive =
                href === '/'
                  ? pathname === '/' || pathname === '/results'
                  : pathname.startsWith(href);
              return (
                <Link
                  key={href}
                  href={href}
                  className={`px-2.5 sm:px-3.5 py-1.5 rounded-full text-[12px] sm:text-[13px] font-medium transition-all duration-300
                    ${
                      isActive
                        ? 'bg-black/[0.06] text-gray-900'
                        : 'text-gray-500 hover:text-gray-900 hover:bg-black/[0.04]'
                    }`}
                >
                  {label}
                </Link>
              );
            })}
          </nav>
        </div>
      </div>
    </header>
  );
}
