import type { Metadata } from 'next';
import { Inter } from 'next/font/google';
import AuthModal from '@/components/AuthModal';
import BackendWaker from '@/components/BackendWaker';
import GuestBanner from '@/components/GuestBanner';
import FeedbackWidget from '@/components/FeedbackWidget';
import OnboardingIntro from '@/components/OnboardingIntro';
import Header from '@/components/Header';
import { AuthModalProvider } from '@/lib/auth-modal-context';
import { SITE_URL } from '@/lib/site';
import { getServerLocale } from '@/i18n/server';
import { LanguageProvider } from '@/i18n/client';
import './globals.css';

const inter = Inter({
  subsets: ['latin'],
  variable: '--font-inter',
  display: 'swap',
});

export const metadata: Metadata = {
  title: {
    default: 'JoinALab — Research & Internship Matching for Students',
    template: '%s · JoinALab',
  },
  description:
    'AI-powered matching that connects students with research positions, internships, and fellowships that actually fit their background — across a growing list of top universities.',
  metadataBase: new URL(SITE_URL),
  applicationName: 'JoinALab',
  authors: [{ name: 'Eric Xu', url: 'https://github.com/EricXu-0805' }],
  keywords: [
    'research matching', 'undergraduate research', 'REU',
    'internships', 'fellowships', 'summer programs',
    'find a research lab', 'AI opportunity matching',
  ],
  openGraph: {
    title: 'JoinALab — Research & Internship Matching',
    description:
      'Find research and internship opportunities that actually match your background. AI-powered, free, built by students.',
    siteName: 'JoinALab',
    type: 'website',
    locale: 'en_US',
    alternateLocale: 'zh_CN',
    url: SITE_URL,
  },
  twitter: {
    card: 'summary_large_image',
    title: 'JoinALab — Research Matching',
    description:
      'AI-powered matching for research positions, internships, and fellowships.',
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
  const skipLabel = locale === 'zh' ? '跳到主要内容' : 'Skip to main content';
  const footerDisclaimer = locale === 'zh'
    ? '与所列大学无附属关系。独立学生项目。'
    : 'Not affiliated with any listed university. Independent student project.';
  const privacyLabel = locale === 'zh' ? '隐私政策' : 'Privacy Policy';
  const termsLabel = locale === 'zh' ? '服务条款' : 'Terms of Service';
  const contactLabel = locale === 'zh' ? '联系' : 'Contact';
  const builtByLabel = locale === 'zh' ? '由 Guoyi (Eric) Xu 打造' : 'Built by Guoyi (Eric) Xu';

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
              className="sr-only focus:not-sr-only focus:fixed focus:top-2 focus:left-2 focus:z-[100] focus:px-4 focus:py-2 focus:bg-white focus:border focus:border-indigo-500 focus:rounded-lg focus:text-sm focus:font-medium focus:text-indigo-700 focus:shadow-lg"
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
                    © {new Date().getFullYear()} JoinALab
                  </p>
                  <nav className="flex items-center gap-4">
                    <a href="/privacy" className="text-[12px] text-gray-400 hover:text-gray-700 transition-colors">
                      {privacyLabel}
                    </a>
                    <a href="/terms" className="text-[12px] text-gray-400 hover:text-gray-700 transition-colors">
                      {termsLabel}
                    </a>
                    <a href="/about" className="text-[12px] text-gray-400 hover:text-gray-700 transition-colors">
                      {contactLabel}
                    </a>
                    <a
                      href="https://github.com/EricXu-0805/opportunity-filter-engine"
                      target="_blank"
                      rel="noopener noreferrer"
                      className="text-[12px] text-gray-400 hover:text-gray-700 transition-colors"
                    >
                      GitHub
                    </a>
                  </nav>
                  <p className="text-[11px] text-gray-400 text-center">
                    {footerDisclaimer}
                  </p>
                </div>
                <p className="mt-3 text-center text-[11px] text-gray-300">
                  {builtByLabel} ·{' '}
                  <a href="mailto:eric.guoyi.xu@gmail.com" className="hover:text-gray-600 transition-colors">
                    eric.guoyi.xu@gmail.com
                  </a>
                </p>
              </div>
            </footer>

            {/* Floating feedback affordance — always available, bottom-right. */}
            <FeedbackWidget />

            {/* Single modal mount-point. Visible only when openModal()
                is called from anywhere in the tree. */}
            <AuthModal />

            {/* First-visit product intro — top-most overlay (z-60), shown once. */}
            <OnboardingIntro />
          </AuthModalProvider>
        </LanguageProvider>
      </body>
    </html>
  );
}
