import { useT } from '@/i18n/client';
import { en } from '@/i18n/dictionaries';

// What a posting states about applying. A card that is not a current listing
// shows none of an offer's terms, so it has none of these to verify.
const POSTING_FIELDS = new Set([
  'opportunity.preferred_year', 'opportunity.majors', 'opportunity.resume_required',
  'opportunity.paid', 'opportunity.application_effort', 'opportunity.on_campus',
  'opportunity.deadline',
]);

export default function MatchUnknowns(
  { fields, currentListing }: { fields?: string[]; currentListing: boolean },
) {
  const { t } = useT();
  if (!Array.isArray(fields) || !fields.length) return null;

  const labels = new Set<string>();
  for (const field of fields) {
    if (typeof field !== 'string') continue;
    if (!currentListing && POSTING_FIELDS.has(field)) continue;
    const key = field.replace('.', '_');
    labels.add(Object.hasOwn(en.card.unknownFields, key) ? key : 'other');
  }
  if (!labels.size) return null;
  return (
    <details className="mt-3 text-[13px] text-gray-700">
      <summary className="cursor-pointer font-semibold">{t('card.verifyConditions')}</summary>
      <ul className="mt-2 list-disc space-y-1 pl-5">
        {Array.from(labels, key => <li key={key}>{t(`card.unknownFields.${key}`)}</li>)}
      </ul>
    </details>
  );
}
