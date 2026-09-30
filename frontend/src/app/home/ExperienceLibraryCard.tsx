'use client';

import { useEffect, useRef, useState } from 'react';
import Card from '@/components/Card';
import {
  createManualCandidate,
  createResumeCandidates,
  ExperienceEvidenceError,
  isActiveExperience,
  sourceDigest,
  validateExperienceEntries,
} from '@/lib/experience-evidence';
import type { ExperienceEntry, ProfileData } from '@/lib/types';
import type { TFunc } from './types';

type EditBase = { resumeText: string; entriesJson: string };
type ChangeEntries = (entries: ExperienceEntry[], expected: EditBase) => boolean;

function EntryEditor({ entry, sourceCurrent, disabled, onReplace, onRemove, t }: {
  entry: ExperienceEntry;
  sourceCurrent: boolean;
  disabled: boolean;
  onReplace: (entry: ExperienceEntry) => void;
  onRemove: () => void;
  t: TFunc;
}) {
  const [text, setText] = useState(entry.text);
  const changed = text !== entry.text;
  const canConfirm = sourceCurrent && text.trim().length > 0 && !disabled;
  return (
    <details className="rounded-xl border border-gray-200 p-3">
      <summary className="cursor-pointer text-sm break-words">
        <span className="font-medium">{entry.text.slice(0, 100)}{entry.text.length > 100 ? '…' : ''}</span>
        <span className="block mt-1 text-xs text-gray-500">
          {t(`home.experience.status.${entry.status}`)} · {t(`home.experience.source.${entry.source.kind}`)}
          {!sourceCurrent && entry.source.kind === 'resume' && ` · ${t('home.experience.sourceChanged')}`}
        </span>
      </summary>
      <label className="mt-3 block text-sm">
        {t('home.experience.factLabel')}
        <textarea value={text} onChange={(event) => setText(event.target.value)} disabled={disabled}
          rows={5} className="mt-1 w-full rounded-lg border border-gray-300 p-2 text-sm disabled:opacity-50" />
      </label>
      {entry.source.kind === 'resume' && (
        <details className="mt-2 text-xs text-gray-600">
          <summary className="cursor-pointer">{t('home.experience.original')}</summary>
          <p className="mt-2 whitespace-pre-wrap break-words rounded-lg bg-gray-50 p-3">{entry.source.quote}</p>
        </details>
      )}
      <div className="mt-3 flex flex-wrap gap-2 text-xs">
        <button type="button" disabled={!canConfirm || (entry.status === 'confirmed' && !changed)}
          onClick={() => onReplace({ ...entry, text, status: 'confirmed', revision: entry.revision + 1 })}
          className="rounded-lg bg-indigo-600 px-3 py-2 text-white disabled:opacity-40">
          {t(changed ? 'home.experience.confirmCorrection' : 'home.experience.confirm')}
        </button>
        <button type="button" disabled={disabled || entry.status === 'rejected'}
          onClick={() => onReplace({ ...entry, status: 'rejected', revision: entry.revision + 1 })}
          className="rounded-lg border border-gray-300 px-3 py-2 disabled:opacity-40">{t('home.experience.exclude')}</button>
        <button type="button" disabled={disabled} onClick={onRemove}
          className="rounded-lg px-3 py-2 text-red-700 disabled:opacity-40">{t('common.remove')}</button>
      </div>
    </details>
  );
}

export function ExperienceLibraryCard({ profile, ready, onChange, t }: {
  profile: ProfileData;
  ready: boolean;
  onChange: ChangeEntries;
  t: TFunc;
}) {
  const [manualText, setManualText] = useState('');
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [digest, setDigest] = useState<{ raw: string; value: string } | null>(null);
  const mounted = useRef(true);
  const raw = profile.resume_text ?? '';
  const checked = validateExperienceEntries(profile.experience_entries);
  const entries = checked.ok ? checked.value : [];
  const expected = { resumeText: raw, entriesJson: JSON.stringify(profile.experience_entries ?? []) };
  useEffect(() => {
    mounted.current = true;
    return () => { mounted.current = false; };
  }, []);
  useEffect(() => {
    let active = true;
    sourceDigest(raw).then((value) => {
      if (active) setDigest({ raw, value });
    }).catch(() => {
      if (active) setDigest(null);
    });
    return () => { active = false; };
  }, [raw]);
  const context = { rawText: raw, expectedDigest: digest?.raw === raw ? digest.value : '' };
  const activeCount = entries.filter((entry) => isActiveExperience(entry, context)).length;
  const reportError = (caught: unknown) => setError(t(caught instanceof ExperienceEvidenceError
    ? `home.experience.errors.${caught.code}` : 'home.experience.errors.failed'));
  const apply = (next: ExperienceEntry[], base = expected): boolean => {
    const validation = validateExperienceEntries(next);
    if (!validation.ok) {
      reportError(new ExperienceEvidenceError(validation.code));
      return false;
    }
    if (!onChange(validation.value, base)) {
      setError(t('home.experience.errors.stale'));
      return false;
    }
    setError(null);
    return true;
  };
  const extract = async () => {
    if (!ready || busy || !checked.ok) return;
    const base = expected;
    const existing = entries;
    setBusy(true);
    setError(null);
    try {
      const proposals = await createResumeCandidates(raw);
      if (!mounted.current) return;
      const ids = new Set(existing.map((entry) => entry.id));
      apply([...existing, ...proposals.filter((entry) => !ids.has(entry.id))], base);
    } catch (caught) {
      if (mounted.current) reportError(caught);
    } finally {
      if (mounted.current) setBusy(false);
    }
  };
  return (
    <section id="experience-library" aria-labelledby="experience-library-title" className="scroll-mt-24">
      <Card>
        <h2 id="experience-library-title" className="text-xl font-bold text-gray-900">{t('home.experience.title')}</h2>
        <p className="mt-2 text-sm text-gray-600">{t('home.experience.description')}</p>
        <p className="mt-2 text-xs text-gray-500">{t('home.experience.limits')}</p>
        {!checked.ok ? (
          <p role="alert" className="mt-3 text-sm text-red-700">{t('home.experience.invalidStored')}</p>
        ) : (
          <>
            <p className="my-3 text-sm text-gray-700">{t('home.experience.count', { active: activeCount, total: entries.length })}</p>
            <button type="button" onClick={extract} disabled={!ready || busy || !raw.trim()}
              className="rounded-lg border border-indigo-300 px-3 py-2 text-sm text-indigo-700 disabled:opacity-40">
              {t(busy ? 'home.experience.extracting' : 'home.experience.extract')}
            </button>
            <div className="mt-4 space-y-2">
              {entries.map((entry) => (
                <EntryEditor key={`${entry.id}:${entry.revision}`} entry={entry} t={t} disabled={!ready || busy}
                  sourceCurrent={isActiveExperience({ ...entry, status: 'confirmed' }, context)}
                  onReplace={(replacement) => apply(entries.map((item) => item.id === entry.id ? replacement : item))}
                  onRemove={() => apply(entries.filter((item) => item.id !== entry.id))} />
              ))}
            </div>
            <details className="mt-4">
              <summary className="cursor-pointer text-sm font-medium text-indigo-700">{t('home.experience.addManual')}</summary>
              <label className="mt-2 block text-sm">{t('home.experience.manualLabel')}
                <textarea value={manualText} onChange={(event) => setManualText(event.target.value)} rows={4}
                  disabled={!ready || busy} className="mt-1 w-full rounded-lg border border-gray-300 p-2" />
              </label>
              <button type="button" disabled={!ready || busy || !manualText.trim()}
                onClick={() => {
                  try {
                    if (apply([...entries, createManualCandidate(manualText)])) setManualText('');
                  } catch (caught) { reportError(caught); }
                }} className="mt-2 rounded-lg border border-gray-300 px-3 py-2 text-sm disabled:opacity-40">
                {t('home.experience.addCandidate')}
              </button>
            </details>
          </>
        )}
        {error && <p role="alert" className="mt-3 text-sm text-red-700">{error}</p>}
      </Card>
    </section>
  );
}
