import type { Metadata } from 'next';
import { Inter } from 'next/font/google';
import Header from '@/components/Header';
import { getServerLocale, tServer } from '@/i18n/server';
import { LanguageProvider } from '@/i18n/client';
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
  metadataBase: new URL('https://opportunity-filter-engine.vercel.app'),
  openGraph: {
    title: 'OpportunityEngine',
    description: 'Find research and internship opportunities at UIUC that match your background.',
    siteName: 'OpportunityEngine',
    type: 'website',
  },
  twitter: {
    card: 'summary_large_image',
    title: 'OpportunityEngine',
    description: 'AI-powered UIUC research & internship matching.',
  },
};

export default function RootLayout({
  children,
}: {
  children: React.ReactNode;
}) {
  const locale = getServerLocale();
  const skipLabel = tServer('common.appName') === 'OpportunityEngine' && locale === 'zh'
    ? '跳到主要内容'
    : 'Skip to main content';
  const footerDisclaimer = locale === 'zh'
    ? '与 UIUC 无附属关系。独立学生项目。'
    : 'Not affiliated with UIUC. Independent student project.';

  return (
    <html lang={locale} className={inter.variable}>
      <body className={`${inter.className} min-h-screen flex flex-col`}>
        <LanguageProvider initialLocale={locale}>
          <a
            href="#main-content"
            className="sr-only focus:not-sr-only focus:fixed focus:top-2 focus:left-2 focus:z-[100] focus:px-4 focus:py-2 focus:bg-white focus:border focus:border-blue-500 focus:rounded-lg focus:text-sm focus:font-medium focus:text-blue-700 focus:shadow-lg"
          >
            {skipLabel}
          </a>
          <Header />

          <div className="h-12" aria-hidden="true" />

          <main id="main-content" tabIndex={-1} className="flex-1 focus:outline-none">{children}</main>

          <footer className="border-t border-black/[0.04] mt-16">
            <div className="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8 py-6">
              <div className="flex flex-col sm:flex-row items-center justify-between gap-3">
                <p className="text-[12px] text-gray-400">
                  © {new Date().getFullYear()} OpportunityEngine
                </p>
                <p className="text-[11px] text-gray-400 text-center">
                  {footerDisclaimer}
                </p>
              </div>
            </div>
          </footer>
        </LanguageProvider>
      </body>
    </html>
  );
}
