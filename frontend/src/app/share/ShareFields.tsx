import { fields, shareFieldLabels, sharePreviewValue, type ShareSnapshot } from '@/lib/managed-profile-share';

export function ShareFields({ snapshot, zh }: { snapshot: ShareSnapshot; zh: boolean }) {
  return (
    <dl className="divide-y divide-gray-200 rounded-lg border border-gray-200 px-4">
      {fields.filter(field => Object.hasOwn(snapshot, field)).map(field => (
        <div key={field} className="grid gap-1 py-3 sm:grid-cols-[12rem_1fr]">
          <dt className="font-medium">{shareFieldLabels[field][zh ? 1 : 0]}</dt>
          <dd className="whitespace-pre-wrap break-words">{sharePreviewValue(snapshot[field], zh) || (zh ? '未填写' : 'Empty')}</dd>
        </div>
      ))}
    </dl>
  );
}
