'use client';

import Link from 'next/link';
import { usePathname } from 'next/navigation';
import { Search, LayoutDashboard, Info, Sparkles } from 'lucide-react';

const NAV_ITEMS = [
  { href: '/', label: 'Find Matches', icon: Search },
  { href: '/dashboard', label: 'Dashboard', icon: LayoutDashboard },
  { href: '/about', label: 'About', icon: Info },
] as const;

export default function Header() {
  const pathname = usePathname();

  return (
    <header className="fixed top-0 left-0 right-0 z-50 bg-white/80 backdrop-blur-lg border-b border-gray-200/60">
      <div className="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8">
        <div className="flex items-center justify-between h-16">
          {/* Logo */}
          <Link href="/" className="flex items-center gap-2.5 group">
            <div className="w-8 h-8 rounded-lg bg-gradient-to-br from-blue-600 to-blue-500 flex items-center justify-center shadow-sm group-hover:shadow-md transition-shadow">
              <Sparkles className="w-4.5 h-4.5 text-white" strokeWidth={2.5} />
            </div>
            <span className="text-lg font-bold text-gray-900 tracking-tight">
              Opportunity<span className="text-blue-600">Engine</span>
            </span>
          </Link>

          {/* Navigation */}
          <nav className="flex items-center gap-1">
            {NAV_ITEMS.map(({ href, label, icon: Icon }) => {
              const isActive =
                href === '/'
                  ? pathname === '/' || pathname === '/results'
                  : pathname.startsWith(href);
              return (
                <Link
                  key={href}
                  href={href}
                  className={`flex items-center gap-2 px-4 py-2 rounded-lg text-sm font-medium transition-all duration-200
                    ${
                      isActive
                        ? 'bg-blue-50 text-blue-700'
                        : 'text-gray-500 hover:text-gray-900 hover:bg-gray-50'
                    }`}
                >
                  <Icon className="w-4 h-4" />
                  <span className="hidden sm:inline">{label}</span>
                </Link>
              );
            })}
          </nav>
        </div>
      </div>
    </header>
  );
}
