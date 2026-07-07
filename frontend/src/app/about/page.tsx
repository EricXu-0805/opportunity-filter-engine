import { Shield, Mail, User } from 'lucide-react';
import { getServerT } from '@/i18n/server';
import { WalkthroughSection } from '@/app/home/WalkthroughSection';

const STACK = [
  { label: 'Next.js 16', categoryKey: 'about.stackCategories.frontend' },
  { label: 'Tailwind CSS', categoryKey: 'about.stackCategories.frontend' },
  { label: 'FastAPI', categoryKey: 'about.stackCategories.backend' },
  { label: 'Python 3.11', categoryKey: 'about.stackCategories.backend' },
  { label: 'Supabase', categoryKey: 'about.stackCategories.database' },
  { label: 'Vercel', categoryKey: 'about.stackCategories.deploy' },
  { label: 'GitHub Actions', categoryKey: 'about.stackCategories.cicd' },
  { label: 'scikit-learn', categoryKey: 'about.stackCategories.ml' },
] as const;

// Non-lead contributors. Names are proper nouns (not translated); roles are.
const CONTRIBUTORS = [
  { name: 'Emily', initials: 'E', roleKey: 'about.collabEmilyRole' },
] as const;

export default async function AboutPage() {
  const t = await getServerT();
  return (
    <div className="py-20">

      <div className="max-w-3xl mx-auto px-4 sm:px-6 lg:px-8 text-center mb-10">
        <h1 className="text-5xl sm:text-6xl font-bold text-gray-900 tracking-tight leading-[1.1]">
          {t('about.heroLine1')}
          <br />
          <span className="bg-gradient-to-r from-indigo-600 to-indigo-400 bg-clip-text text-transparent">
            {t('about.heroLine2')}
          </span>
        </h1>
        <p className="mt-6 text-lg text-gray-400 leading-relaxed max-w-xl mx-auto">
          {t('about.heroSubtitle')}
        </p>
      </div>

      {/* The product walkthrough (moved here from the landing page) is the
          "how it works" for About — the wider band gives the tour room. */}
      <div className="max-w-5xl mx-auto px-4 sm:px-6 lg:px-8 mb-20">
        <WalkthroughSection />
      </div>

      <div className="max-w-3xl mx-auto px-4 sm:px-6 lg:px-8">

        <div className="mb-20">
          <h2 className="text-[13px] font-semibold text-gray-400 uppercase tracking-widest text-center mb-12">
            {t('about.builtWith')}
          </h2>
          <div className="flex flex-wrap justify-center gap-2">
            {STACK.map((entry) => (
              <span
                key={entry.label}
                className="px-4 py-2 rounded-full bg-white text-[13px] font-medium text-gray-600 shadow-[0_1px_4px_rgba(0,0,0,0.05)]"
              >
                {entry.label}
              </span>
            ))}
          </div>
        </div>

        <div className="bg-white rounded-2xl shadow-[0_1px_8px_rgba(0,0,0,0.05)] p-8 mb-20">
          <div className="flex items-start gap-5">
            <div className="w-10 h-10 rounded-xl bg-indigo-600/[0.08] flex items-center justify-center shrink-0">
              <Shield className="w-5 h-5 text-indigo-600" />
            </div>
            <div>
              <h3 className="text-[15px] font-semibold text-gray-900 mb-1.5">{t('about.privacy')}</h3>
              <p className="text-[14px] text-gray-400 leading-relaxed">
                {t('about.privacyBody')}
              </p>
            </div>
          </div>
        </div>

        <div className="mb-16">
          <h2 className="text-[13px] font-semibold text-gray-400 uppercase tracking-widest text-center mb-12">
            {t('about.behindTitle')}
          </h2>
          <div className="bg-white rounded-2xl shadow-[0_1px_8px_rgba(0,0,0,0.05)] p-8">
            <div className="flex flex-col sm:flex-row items-center sm:items-start gap-6 text-center sm:text-left">
              {/* Photo placeholder — reserved; swap the inner block for an <Image /> when the portrait is ready. */}
              <div className="shrink-0 flex flex-col items-center gap-2">
                <div className="w-24 h-24 rounded-full bg-gray-50 border-2 border-dashed border-gray-200 flex items-center justify-center">
                  <User className="w-9 h-9 text-gray-300" aria-hidden="true" />
                </div>
                <span className="text-[11px] text-gray-300">{t('about.photoComing')}</span>
              </div>
              <div className="flex-1">
                <p className="text-[17px] font-semibold text-gray-900">{t('about.author')}</p>
                <p className="text-[13px] text-gray-400 mt-1">{t('about.authorRole')}</p>
                <p className="text-[14px] text-gray-500 leading-relaxed mt-4">{t('about.behindBody')}</p>
                <div className="flex flex-wrap items-center justify-center sm:justify-start gap-2.5 mt-5">
                  <a
                    href="mailto:eric.guoyi.xu@gmail.com"
                    className="inline-flex items-center gap-2 px-4 py-2 rounded-full bg-gray-900 text-white text-[13px] font-medium hover:bg-gray-800 transition-colors duration-300"
                  >
                    <Mail className="w-4 h-4" />
                    {t('about.emailLabel')}
                  </a>
                </div>
              </div>
            </div>

            <div className="mt-8 pt-8 border-t border-black/[0.05]">
              <p className="text-[11px] font-semibold text-gray-400 uppercase tracking-widest mb-4">
                {t('about.contributorsTitle')}
              </p>
              <ul className="flex flex-wrap gap-x-8 gap-y-4">
                {CONTRIBUTORS.map((c) => (
                  <li key={c.name} className="flex items-center gap-3">
                    <span className="w-9 h-9 rounded-full bg-indigo-50 text-indigo-600 text-[13px] font-semibold flex items-center justify-center">
                      {c.initials}
                    </span>
                    <span>
                      <span className="block text-[14px] font-semibold text-gray-900">{c.name}</span>
                      <span className="block text-[12px] text-gray-400">{t(c.roleKey)}</span>
                    </span>
                  </li>
                ))}
              </ul>
            </div>
          </div>
        </div>

        <div className="text-center">
          <p className="text-[11px] text-gray-400 leading-relaxed max-w-md mx-auto">
            {t('about.disclaimer')}
          </p>
        </div>

      </div>
    </div>
  );
}
