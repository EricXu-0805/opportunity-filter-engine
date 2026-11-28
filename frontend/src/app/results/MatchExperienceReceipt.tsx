'use client';

import { useLocale } from '@/i18n/client';
import { githubPullUrl, linkedGitHubPull } from '@/lib/github-contribution';
import type { ExperienceEntry, MatchResult } from '@/lib/types';

export function MatchExperienceReceipt({ basis, eligibleEntries }: {
  basis: NonNullable<MatchResult['experience_basis']>; eligibleEntries: ExperienceEntry[];
}) {
  const zh = useLocale() === 'zh';
  const entry = eligibleEntries.find((row) => row?.id === basis.entry_id && row.revision === basis.revision
    && row.status === 'confirmed' && typeof row.text === 'string');
  if (!entry) return null;
  const pull = linkedGitHubPull(entry);
  return <details className="mt-2 rounded-lg border border-gray-200 bg-white px-4 py-2 text-sm">
    <summary className="cursor-pointer font-medium">{zh ? '本次匹配采用的经历' : 'Experience used for this match'} · {basis.method}</summary>
    <p className="mt-2 whitespace-pre-wrap break-words">{entry.text}</p>
    <p className="mt-2 text-xs text-gray-600">
      {entry.source.kind === 'resume' && (zh ? '当前简历 · ' : 'Current résumé · ')}
      {entry.source.kind === 'manual' && /^li:[a-f0-9]{64}$/.test(entry.id) && 'LinkedIn · '}
      {pull && <>{zh ? '来自你填写的 GitHub 账号' : 'From the GitHub account you entered'} · <a className="underline" href={githubPullUrl(pull)} target="_blank" rel="noreferrer">{pull.repository} #{pull.number}</a> · </>}
      {zh ? '本人已确认' : 'Confirmed by you'} · {zh ? '修订' : 'Revision'} {entry.revision}</p>
  </details>;
}
