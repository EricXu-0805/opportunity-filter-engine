'use client';

import dynamic from 'next/dynamic';
import { FileText, Upload } from 'lucide-react';
import Card from '@/components/Card';
import type { ProfileData, ResumeParseResponse } from '@/lib/types';
import type { TFunc } from './types';

const ResumeUpload = dynamic(() => import('@/components/ResumeUpload'), {
  ssr: false,
  loading: () => (
    <div className="h-24 rounded-xl bg-gray-50 border border-dashed border-gray-200 animate-pulse" />
  ),
});

export function DocumentsCard({
  profile,
  onResumeParsed,
  t,
}: {
  profile: ProfileData;
  onResumeParsed: (data: ResumeParseResponse) => void;
  t: TFunc;
}) {
  return (
    <Card>
      <div className="flex items-center gap-3 mb-6">
        <div className="w-10 h-10 rounded-xl bg-orange-50 flex items-center justify-center">
          <FileText className="w-5 h-5 text-uiuc-orange" />
        </div>
        <div>
          <h2 className="text-xl font-bold text-gray-900">{t('home.cards.documentsTitle')}</h2>
          <p className="text-sm text-gray-400">{t('home.cards.documentsSubtitle')}</p>
        </div>
      </div>

      <ResumeUpload onParsed={onResumeParsed} alreadyUploaded={!!profile.resume_text} />

      <div className="mt-4 flex items-start gap-2 px-3 py-2.5 rounded-lg bg-blue-50/60">
        <Upload className="w-4 h-4 text-blue-500 mt-0.5 shrink-0" />
        <p className="text-xs text-blue-600 leading-relaxed">{t('home.cards.resumePrivacy')}</p>
      </div>
    </Card>
  );
}
