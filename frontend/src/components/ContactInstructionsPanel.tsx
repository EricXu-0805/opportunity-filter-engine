'use client';

import { useState } from 'react';
import { useT } from '@/i18n/client';
import { contactEmailBlock, contactInstructionCopy, contactMaterialLabel, contactSourceUrl, needsContactSubjectReview, readContactInstructions, requiredContactSubject } from '@/lib/contact-instructions';

/** Shows the same source-bound rules used by the email server and composer. */
export default function ContactInstructionsPanel({ target, subject, onUseSubject, subjectFormatConfirmed = false, onConfirmSubjectFormat }: {
  target: unknown; subject?: string; onUseSubject?: (value: string) => void;
  subjectFormatConfirmed?: boolean; onConfirmSubjectFormat?: (value: boolean) => void;
}) {
  const { locale } = useT();
  const [viewedAt] = useState(Date.now);
  const copy = contactInstructionCopy[locale];
  const policy = readContactInstructions(target);
  const blocked = contactEmailBlock(target, subject, { subjectFormatConfirmed });
  const required = requiredContactSubject(target);
  return <section className="rounded-xl border border-gray-200 bg-white p-4 space-y-3 min-w-0" aria-label={copy.title} data-testid="contact-instructions">
    <h3 className="text-sm font-semibold text-gray-900">{copy.title}</h3>
    {(!policy || policy.status === 'unknown') && <p className="text-sm text-gray-600">{policy ? copy.unknown : copy.unavailable}</p>}
    {blocked && policy && <p role="status" className="text-sm text-amber-800">{copy[blocked]}</p>}
    {required && <div className="space-y-1 text-sm">
      <p className="font-medium">{copy.requiredSubject}</p><p className="break-words">{required}</p>
      {onUseSubject && required !== subject && <button type="button" onClick={() => onUseSubject(required)} className="rounded-md px-3 py-2 bg-indigo-50 text-indigo-700">{copy.useSubject}</button>}
    </div>}
    {!!policy?.rules.length && <ul className="space-y-3">
      {policy.rules.map((rule, index) => <li key={`${rule.kind}:${rule.source_url}:${index}`} className="text-sm min-w-0">
        {!(rule.kind === 'subject' && required) && <p className="font-medium text-gray-800">{rule.kind === 'subject' ? copy.requiredSubject : rule.kind === 'form_only' ? copy.form_only : copy[rule.kind]}</p>}
        <blockquote className="mt-1 whitespace-pre-wrap break-words text-gray-600">{rule.quote}</blockquote>
        {rule.materials?.length ? <p className="mt-1 break-words">{rule.materials.map(item => contactMaterialLabel(item, locale)).join(' · ')}</p> : null}
        <p className="mt-1 flex flex-wrap gap-x-3 gap-y-1 text-xs text-gray-500">
          <a href={contactSourceUrl(rule.source_url) ?? undefined} target="_blank" rel="noopener noreferrer" className="text-indigo-600 underline">{copy.source}</a>
          <span>{copy.checked}: {rule.checked_at.slice(0, 10)}</span>
        </p>
        {viewedAt - Date.parse(rule.checked_at) > 60 * 86400 * 1000 && <p className="mt-1 text-xs text-amber-800">{copy.old}</p>}
      </li>)}
    </ul>}
    {needsContactSubjectReview(target) && <div className="space-y-2 text-sm text-gray-700">
      <p>{copy.subject_format}</p>
      {onConfirmSubjectFormat && <label className="flex items-start gap-2">
        <input type="checkbox" checked={subjectFormatConfirmed} disabled={!subject?.trim()} onChange={event => onConfirmSubjectFormat(event.target.checked)} className="mt-1" />
        <span>{copy.confirmFormat}</span>
      </label>}
    </div>}
    {policy?.rules.some(rule => rule.kind === 'materials') && <p className="text-xs text-gray-600">{copy.materialNote}</p>}
  </section>;
}
