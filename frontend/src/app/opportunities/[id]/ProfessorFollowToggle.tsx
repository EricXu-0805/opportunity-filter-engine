'use client';

import { useEffect, useState } from 'react';
import { BellRing, LoaderCircle } from 'lucide-react';
import { useT } from '@/i18n/client';
import {
  followProfessor,
  isCanonicalProfessorId,
  listProfessorFollows,
  unfollowProfessor,
} from '@/lib/supabase';

type LoadStatus = 'loading' | 'ready' | 'error';

export function ProfessorFollowToggle({
  professorId,
  professorName,
  school,
}: {
  professorId?: string | null;
  professorName?: string | null;
  school?: string | null;
}) {
  // Only faculty records carry a tracking id; everything else renders nothing.
  if (!isCanonicalProfessorId(professorId)) return null;
  return (
    <ProfessorFollowControl
      key={professorId}
      professorId={professorId}
      professorName={professorName ?? null}
      school={school ?? null}
    />
  );
}

function ProfessorFollowControl({
  professorId,
  professorName,
  school,
}: {
  professorId: string;
  professorName: string | null;
  school: string | null;
}) {
  const { t } = useT();
  const [loadStatus, setLoadStatus] = useState<LoadStatus>('loading');
  const [reloadToken, setReloadToken] = useState(0);
  const [following, setFollowing] = useState(false);
  const [saving, setSaving] = useState(false);
  const [saveFailed, setSaveFailed] = useState(false);
  const [retryTarget, setRetryTarget] = useState<boolean | null>(null);

  useEffect(() => {
    let cancelled = false;

    listProfessorFollows()
      .then((follows) => {
        if (cancelled) return;
        setFollowing(follows.some((f) => f.professorId === professorId));
        setLoadStatus('ready');
      })
      .catch(() => {
        if (!cancelled) setLoadStatus('error');
      });

    return () => { cancelled = true; };
  }, [professorId, reloadToken]);

  function retryLoad() {
    setLoadStatus('loading');
    setSaveFailed(false);
    setRetryTarget(null);
    setReloadToken((token) => token + 1);
  }

  async function persist(nextFollowing: boolean) {
    if (saving) return;
    setSaving(true);
    setSaveFailed(false);
    try {
      if (nextFollowing) {
        await followProfessor(professorId, professorName, school);
      } else {
        await unfollowProfessor(professorId);
      }
      setFollowing(nextFollowing);
      setRetryTarget(null);
    } catch {
      setSaveFailed(true);
      setRetryTarget(nextFollowing);
    } finally {
      setSaving(false);
    }
  }

  if (loadStatus === 'loading') {
    return (
      <section className="border-t border-gray-100 px-5 py-4 sm:px-8" aria-live="polite">
        <div className="flex items-center gap-2 text-sm text-gray-500">
          <LoaderCircle className="h-4 w-4 animate-spin" aria-hidden="true" />
          {t('detail.professorFollow.loading')}
        </div>
      </section>
    );
  }

  if (loadStatus === 'error') {
    return (
      <section className="border-t border-gray-100 px-5 py-4 sm:px-8" aria-live="polite">
        <p className="text-sm font-medium text-red-700">{t('detail.professorFollow.loadError')}</p>
        <button
          type="button"
          onClick={retryLoad}
          className="mt-2 text-sm font-medium text-indigo-600 hover:text-indigo-700 focus:outline-none focus-visible:ring-2 focus-visible:ring-indigo-500 rounded"
        >
          {t('detail.professorFollow.retry')}
        </button>
      </section>
    );
  }

  return (
    <section className="border-t border-gray-100 px-5 py-4 sm:px-8" aria-live="polite">
      <div className="flex items-center justify-between gap-4">
        <div className="min-w-0">
          <p className="flex items-center gap-2 text-sm font-semibold text-gray-900">
            <BellRing className="h-4 w-4 text-indigo-500" aria-hidden="true" />
            {t('detail.professorFollow.title')}
          </p>
          <p className="mt-1 text-xs leading-relaxed text-gray-500">
            {t('detail.professorFollow.body')}
          </p>
        </div>
        <button
          type="button"
          role="switch"
          aria-checked={following}
          aria-label={t(following
            ? 'detail.professorFollow.unfollow'
            : 'detail.professorFollow.follow')}
          disabled={saving}
          onClick={() => { void persist(!following); }}
          className={`relative h-7 w-12 shrink-0 rounded-full transition-colors focus:outline-none focus-visible:ring-2 focus-visible:ring-indigo-500 disabled:cursor-wait disabled:opacity-60 ${
            following ? 'bg-indigo-600' : 'bg-gray-200'
          }`}
        >
          <span
            aria-hidden="true"
            className={`absolute top-1 h-5 w-5 rounded-full bg-white shadow-sm transition-transform ${
              following ? 'translate-x-6' : 'translate-x-1'
            }`}
          />
        </button>
      </div>
      {saving && (
        <p className="mt-2 text-xs text-gray-500">{t('detail.professorFollow.saving')}</p>
      )}
      {saveFailed && retryTarget !== null && (
        <div className="mt-2 flex items-center gap-3">
          <p className="text-xs text-red-700">{t('detail.professorFollow.saveError')}</p>
          <button
            type="button"
            onClick={() => { void persist(retryTarget); }}
            className="text-xs font-semibold text-indigo-600 hover:text-indigo-700 focus:outline-none focus-visible:ring-2 focus-visible:ring-indigo-500 rounded"
          >
            {t('detail.professorFollow.retry')}
          </button>
        </div>
      )}
    </section>
  );
}
