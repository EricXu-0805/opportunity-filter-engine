'use client';

import { Github, Globe, Linkedin, Loader2 } from 'lucide-react';
import Card from '@/components/Card';
import type { ProfileData } from '@/lib/types';
import type { TFunc } from './types';

export function OnlineProfilesCard({
  profile,
  update,
  ghLoading,
  ghStatus,
  onGitHubImport,
  t,
}: {
  profile: ProfileData;
  update: <K extends keyof ProfileData>(key: K, value: ProfileData[K]) => void;
  ghLoading: boolean;
  ghStatus: string | null;
  onGitHubImport: () => void;
  t: TFunc;
}) {
  return (
    <Card>
      <div className="flex items-center gap-3 mb-6">
        <div className="w-10 h-10 rounded-xl bg-gray-100 flex items-center justify-center">
          <Globe className="w-5 h-5 text-gray-600" />
        </div>
        <div>
          <h2 className="text-xl font-bold text-gray-900">{t('home.cards.onlineProfilesTitle')}</h2>
          <p className="text-sm text-gray-400">{t('home.cards.onlineProfilesSubtitle')}</p>
        </div>
      </div>

      <div className="space-y-4">
        <div>
          <label htmlFor="linkedin_url" className="flex items-center gap-1.5 text-sm font-medium text-gray-700 mb-2">
            <Linkedin className="w-4 h-4 text-[#0A66C2]" />
            {t('home.form.linkedinLabel')}
          </label>
          <input
            id="linkedin_url"
            type="url"
            value={profile.linkedin_url ?? ''}
            onChange={(e) => update('linkedin_url', e.target.value)}
            placeholder={t('home.form.linkedinPlaceholder')}
            className="w-full px-4 py-3 border border-gray-200 rounded-2xl text-sm text-gray-700 placeholder:text-gray-400 focus:ring-2 focus:ring-blue-500/20 focus:border-blue-300 outline-none transition-all duration-300"
          />
          <p className="mt-2 text-xs text-gray-400">{t('home.form.linkedinHint')}</p>
        </div>

        <div>
          <label htmlFor="github_url" className="flex items-center gap-1.5 text-sm font-medium text-gray-700 mb-2">
            <Github className="w-4 h-4" />
            GitHub
          </label>
          <div className="flex gap-2">
            <input
              id="github_url"
              type="url"
              value={profile.github_url ?? ''}
              onChange={(e) => update('github_url', e.target.value)}
              placeholder={t('home.form.githubPlaceholder')}
              className="flex-1 px-4 py-3 border border-gray-200 rounded-2xl text-sm text-gray-700 placeholder:text-gray-400 focus:ring-2 focus:ring-blue-500/20 focus:border-blue-300 outline-none transition-all duration-300"
            />
            <button
              type="button"
              disabled={!profile.github_url?.trim() || ghLoading}
              onClick={onGitHubImport}
              className="px-4 py-3 text-sm font-medium text-white bg-gray-800 rounded-2xl hover:bg-gray-900 disabled:opacity-40 disabled:cursor-not-allowed transition-colors shrink-0"
            >
              {ghLoading ? <Loader2 className="w-4 h-4 animate-spin" /> : t('home.form.githubImport')}
            </button>
          </div>
          {ghStatus && (
            <p className={`mt-2 text-xs ${ghStatus.startsWith('__fail__') ? 'text-red-500' : 'text-emerald-600'}`}>
              {ghStatus.replace(/^__fail__/, '')}
            </p>
          )}
        </div>
      </div>
    </Card>
  );
}
