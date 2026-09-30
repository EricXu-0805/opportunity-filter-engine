'use client';

import { useT } from '@/i18n/client';
import { contactSourceUrl } from '@/lib/contact-instructions';
import { targetConditionLabel, targetConditionStatus, targetConditionReason, targetConditionValue, type EmailTargetConditions } from '@/lib/email-target-conditions';

export default function EmailTargetConditionsPanel({ receipt, current }: { receipt: EmailTargetConditions | null; current: boolean }) {
  const { locale } = useT();
  const zh = locale === 'zh';
  const rows = current ? receipt?.conditions ?? [] : [];
  const sourced = rows.filter(row => row.usage === 'usable').length;
  return <section data-testid="email-target-conditions" className="rounded-xl border border-gray-200 bg-gray-50 p-3 text-xs text-gray-700 min-w-0">
    <details>
      <summary className="cursor-pointer font-semibold text-gray-800">{zh ? '本次参考的目标条件' : 'Target conditions for this draft'}<span className="ml-2 font-normal text-gray-500">{!sourced ? zh ? '申请条件尚未核对' : 'Application conditions need review' : zh ? `${sourced} 项有依据 · ${rows.length - sourced} 项需核对` : `${sourced} sourced · ${rows.length - sourced} to review`}</span></summary>
      {!current ? <p className="mt-2">{zh ? '这份草稿所用的目标资料尚未核对。原稿仍保留。' : 'The target information for this draft has not been checked. Your draft is kept.'}</p>
        : !receipt || !rows.length ? <p className="mt-2">{zh ? '这份资料未提供可确认的申请条件，不代表没有要求。联系前请查看来源。' : 'No confirmed application conditions were provided. This does not mean there are no requirements. Check the source before contacting.'}</p>
        : <div className="mt-2 space-y-3">
          <p>{zh ? '这里只说明目标要求，不代表你已符合资格、准备好材料或附上文件。' : 'These describe the target’s requirements, not proof that you qualify, have prepared the materials or attached files.'}</p>
          {(['usable', 'ask_only', 'excluded'] as const).map(usage => {
            const group = rows.filter(row => row.usage === usage);
            return group.length > 0 && <div key={usage}>
              <h4 className="font-semibold">{usage === 'usable' ? zh ? '来源明确说明' : 'Stated in the source' : usage === 'ask_only' ? zh ? '仍需核对' : 'Still to confirm' : zh ? '本次未采用' : 'Not used for this draft'}</h4>
              <ul className="mt-2 space-y-3">{group.map(row => <li key={row.field} className="break-words min-w-0">
                <p className="font-medium">{targetConditionLabel(row.field, locale)} · {targetConditionStatus(row, locale)}</p>
                {targetConditionReason(row, locale) && <p className="mt-1 text-amber-800">{targetConditionReason(row, locale)}</p>}
                {row.value !== null && <p className="mt-1 whitespace-pre-wrap [overflow-wrap:anywhere]">{targetConditionValue(row, locale)}</p>}
                {row.sources.length > 0 && <details className="mt-1"><summary className="cursor-pointer text-indigo-700">{zh ? '查看依据与来源' : 'View evidence and sources'}</summary><ul className="mt-2 space-y-2">{row.sources.map((source, index) => <li key={index}>
                  {source.heading && <p className="font-medium whitespace-pre-wrap [overflow-wrap:anywhere]">{source.heading}</p>}
                  <blockquote className="whitespace-pre-wrap [overflow-wrap:anywhere]">{source.quote}</blockquote>
                  <p className="mt-1 flex flex-wrap gap-x-3 gap-y-1 text-gray-500"><a href={contactSourceUrl(source.source_url)!} target="_blank" rel="noopener noreferrer" className="text-indigo-700 underline">{zh ? '查看来源' : 'View source'}</a><span>{zh ? '来源核对日期：' : 'Source checked: '}{source.checked_at.slice(0, 10)}</span></p>
                </li>)}</ul></details>}
              </li>)}</ul>
            </div>;
          })}
        </div>}
    </details>
  </section>;
}
