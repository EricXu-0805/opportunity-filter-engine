import type { Metadata } from 'next';
import { Mail, BookOpen } from 'lucide-react';
import { getServerT } from '@/i18n/server';
import ContactTipsCard from './ContactTipsCard';
import DatabaseLinkCard from './DatabaseLinkCard';
import HighlightLabType from './HighlightLabType';
import { DATABASES, LAB_TYPES } from './types';

export const metadata: Metadata = {
  title: 'Resources — Cold-email guides & research databases',
  description:
    'Per-lab-type cold-email guides (wet, dry, humanities) and curated links to Illinois Experts, NIH Reporter, NSF Awards, and Google Scholar — four databases students use to research professors before reaching out.',
};

export default async function ResourcesPage() {
  const t = await getServerT();
  return (
    <div className="max-w-6xl mx-auto px-4 sm:px-6 lg:px-8 py-14 sm:py-20">
      <HighlightLabType />
      <header className="mb-12 sm:mb-16">
        <h1 className="text-4xl sm:text-5xl font-bold text-gray-900 tracking-tight leading-[1.1]">
          {t('resources.title')}
        </h1>
        <p className="mt-4 text-base sm:text-lg text-gray-500 max-w-2xl">
          {t('resources.subtitle')}
        </p>
      </header>

      <section aria-labelledby="contact-tips-heading" className="mb-16 sm:mb-20">
        <div className="flex items-center gap-3 mb-6">
          <Mail className="w-5 h-5 text-indigo-600" aria-hidden="true" />
          <h2 id="contact-tips-heading" className="text-xl sm:text-2xl font-bold text-gray-900 tracking-tight">
            {t('resources.contactTipsHeading')}
          </h2>
        </div>
        <p className="text-sm text-gray-500 mb-8 max-w-2xl">
          {t('resources.contactTipsSubtitle')}
        </p>
        <div className="grid grid-cols-1 md:grid-cols-3 gap-5">
          {LAB_TYPES.map((meta) => (
            <ContactTipsCard key={meta.key} labType={meta.key} />
          ))}
        </div>
      </section>

      <section aria-labelledby="databases-heading">
        <div className="flex items-center gap-3 mb-6">
          <BookOpen className="w-5 h-5 text-indigo-600" aria-hidden="true" />
          <h2 id="databases-heading" className="text-xl sm:text-2xl font-bold text-gray-900 tracking-tight">
            {t('resources.databasesHeading')}
          </h2>
        </div>
        <p className="text-sm text-gray-500 mb-8 max-w-2xl">
          {t('resources.databasesSubtitle')}
        </p>
        <div className="grid grid-cols-1 sm:grid-cols-2 gap-4">
          {DATABASES.map((link) => (
            <DatabaseLinkCard key={link.key} link={link} />
          ))}
        </div>
      </section>
    </div>
  );
}
