'use client';

import { useLocale } from '@/i18n/client';
import { githubPullUrl, validGitHubPullSource } from '@/lib/github-contribution';
import type { ExperienceEntry, MatchResult } from '@/lib/types';

export function MatchExperienceReceipt({ basis, entries }: {
  basis: NonNullable<MatchResult['experience_basis']>; entries?: ExperienceEntry[];
}) {
  const zh = useLocale() === 'zh';
  const entry = Array.isArray(entries) && entries.find((row) => row?.id === basis.entry_id && row.revision === basis.revision
    && row.status === 'confirmed' && typeof row.text === 'string' && (row.source?.kind === 'manual' || row.source?.kind === 'github'));
  if (!entry) return null;
  return <details className="mt-2 rounded-lg border border-gray-200 bg-white px-4 py-2 text-sm">
    <summary className="cursor-pointer font-medium">{zh ? '本次匹配采用的经历' : 'Experience used for this match'} · {basis.method}</summary>
    <p className="mt-2 whitespace-pre-wrap break-words">{entry.text}</p>
    <p className="mt-2 text-xs text-gray-600">{entry.source.kind === 'github' && validGitHubPullSource({ ...entry.source })
      ? <a className="underline" href={githubPullUrl(entry.source)} target="_blank" rel="noreferrer">{entry.source.repository} #{entry.source.number}</a> : (zh ? '本人已确认' : 'Confirmed by you')} · {zh ? '修订' : 'Revision'} {entry.revision}</p>
  </details>;
}
