import type { Metadata } from 'next';
import { Inter } from 'next/font/google';
import Header from '@/components/Header';
import './globals.css';

const inter = Inter({
  subsets: ['latin'],
  variable: '--font-inter',
  display: 'swap',
});

export const metadata: Metadata = {
  title: 'OpportunityEngine — UIUC Research & Internship Matching',
  description:
    'AI-powered matching engine connecting UIUC students with research positions and internship opportunities.',
};

export default function RootLayout({
  children,
}: {
  children: React.ReactNode;
}) {
  return (
    <html lang="en" className={inter.variable}>
      <body className={`${inter.className} min-h-screen flex flex-col`}>
        <Header />

        {/* Spacer for fixed header */}
        <div className="h-16" />

        <main className="flex-1">{children}</main>

        {/* Footer */}
        <footer className="border-t border-gray-200 bg-white">
          <div className="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8 py-8">
            <div className="flex flex-col sm:flex-row items-center justify-between gap-4">
              <p className="text-sm text-gray-400">
                © {new Date().getFullYear()} OpportunityEngine
              </p>
              <p className="text-xs text-gray-400 text-center">
                Not officially affiliated with the University of Illinois
                Urbana-Champaign. This is an independent student project.
              </p>
            </div>
          </div>
        </footer>
      </body>
    </html>
  );
}
