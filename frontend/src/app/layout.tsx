import type { Metadata } from 'next';
import { Inter } from 'next/font/google';
import AuthModal from '@/components/AuthModal';
import BackendWaker from '@/components/BackendWaker';
import GuestBanner from '@/components/GuestBanner';
import Header from '@/components/Header';
import { AuthModalProvider } from '@/lib/auth-modal-context';
import { SITE_URL } from '@/lib/site';
import { getServerLocale, getServerT } from '@/i18n/server';
import { LanguageProvider } from '@/i18n/client';
import './globals.css';

const inter = Inter({
  subsets: ['latin'],
  variable: '--font-inter',
  display: 'swap',
});

export const metadata: Metadata = {
  title: {
    default: 'OpportunityEngine — UIUC Research & Internship Matching',
    template: '%s · OpportunityEngine',
  },
  description:
    'AI-powered matching engine connecting UIUC undergraduates with 1,700+ research positions, internships, and summer programs that actually fit their background.',
  metadataBase: new URL(SITE_URL),
  applicationName: 'OpportunityEngine',
  authors: [{ name: 'Eric Xu', url: 'https://github.com/EricXu-0805' }],
  keywords: [
    'UIUC research', 'UIUC internships', 'undergraduate research',
    'REU', 'research matching', 'Illinois research opportunities',
    'Grainger Engineering', 'summer programs', 'AI opportunity matching',
  ],
  openGraph: {
    title: 'OpportunityEngine — UIUC Research & Internship Matching',
    description:
      'Find research and internship opportunities at UIUC that actually match your background. AI-powered, free, built by students.',
    siteName: 'OpportunityEngine',
    type: 'website',
    locale: 'en_US',
    alternateLocale: 'zh_CN',
    url: SITE_URL,
  },
  twitter: {
    card: 'summary_large_image',
    title: 'OpportunityEngine — UIUC Research Matching',
    description:
      'AI-powered matching engine for 1,700+ UIUC research positions and internships.',
    creator: '@EricXu_0805',
  },
  robots: {
    index: true,
    follow: true,
    googleBot: { index: true, follow: true, 'max-image-preview': 'large' },
  },
  alternates: {
    canonical: SITE_URL,
    languages: {
      'en': `${SITE_URL}?lang=en`,
      'zh': `${SITE_URL}?lang=zh`,
    },
  },
};

export default async function RootLayout({
  children,
}: {
  children: React.ReactNode;
}) {
  const locale = await getServerLocale();
  const t = await getServerT();
  const skipLabel = t('common.appName') === 'OpportunityEngine' && locale === 'zh'
    ? '跳到主要内容'
    : 'Skip to main content';
  const footerDisclaimer = locale === 'zh'
    ? '与 UIUC 无附属关系。独立学生项目。'
    : 'Not affiliated with UIUC. Independent student project.';
  const privacyLabel = locale === 'zh' ? '隐私政策' : 'Privacy Policy';
  const termsLabel = locale === 'zh' ? '服务条款' : 'Terms of Service';

  return (
    <html lang={locale} className={inter.variable}>
      <body className={`${inter.className} min-h-screen flex flex-col`}>
        <LanguageProvider initialLocale={locale}>
          {/* AuthModalProvider must wrap everything that calls
              useAuthModal (Header AccountMenu, GuestBanner, anchors,
              page-level buttons like Save to account). One <AuthModal />
              instance lives at the root so phase transitions stay
              consistent across surfaces. */}
          <AuthModalProvider>
            <BackendWaker />
            <a
              href="#main-content"
              className="sr-only focus:not-sr-only focus:fixed focus:top-2 focus:left-2 focus:z-[100] focus:px-4 focus:py-2 focus:bg-white focus:border focus:border-blue-500 focus:rounded-lg focus:text-sm focus:font-medium focus:text-blue-700 focus:shadow-lg"
            >
              {skipLabel}
            </a>
            <Header />

            <div className="h-12" aria-hidden="true" />

            {/* Post-signout reassurance. Self-gating: only renders when
                the just-signed-out flag is set + user is now anon. */}
            <GuestBanner />

            <main id="main-content" tabIndex={-1} className="flex-1 focus:outline-none">{children}</main>

            <footer className="border-t border-black/[0.04] mt-16">
              <div className="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8 py-6">
                <div className="flex flex-col sm:flex-row items-center justify-between gap-3">
                  <p className="text-[12px] text-gray-400">
                    © {new Date().getFullYear()} OpportunityEngine
                  </p>
                  <nav className="flex items-center gap-4">
                    <a href="/privacy" className="text-[12px] text-gray-400 hover:text-gray-700 transition-colors">
                      {privacyLabel}
                    </a>
                    <a href="/terms" className="text-[12px] text-gray-400 hover:text-gray-700 transition-colors">
                      {termsLabel}
                    </a>
                  </nav>
                  <p className="text-[11px] text-gray-400 text-center">
                    {footerDisclaimer}
                  </p>
                </div>
              </div>
            </footer>

            {/* Single modal mount-point. Visible only when openModal()
                is called from anywhere in the tree. */}
            <AuthModal />
          </AuthModalProvider>
        </LanguageProvider>
      </body>
    </html>
  );
}
