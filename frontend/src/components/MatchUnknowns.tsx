import { useT } from '@/i18n/client';
import { en } from '@/i18n/dictionaries';

export default function MatchUnknowns({ fields }: { fields?: string[] }) {
  const { t } = useT();
  if (!Array.isArray(fields) || !fields.length) return null;

  const labels = new Set<string>();
  for (const field of fields) {
    if (typeof field !== 'string') continue;
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
