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

        <div className="h-12" />

        <main className="flex-1">{children}</main>

        <footer className="border-t border-black/[0.04] mt-16">
          <div className="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8 py-6">
            <div className="flex flex-col sm:flex-row items-center justify-between gap-3">
              <p className="text-[12px] text-gray-400">
                © {new Date().getFullYear()} OpportunityEngine
              </p>
              <p className="text-[11px] text-gray-400 text-center">
                Not affiliated with UIUC. Independent student project.
              </p>
            </div>
          </div>
        </footer>
      </body>
    </html>
  );
}
