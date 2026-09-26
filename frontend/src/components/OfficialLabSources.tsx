import { parseLabContext, type LabContext } from '@/lib/lab-context';
import styles from './OfficialLabSources.module.css';

/** Read-only sources. Expanding a page never confirms reading or edits a draft. */
export default function OfficialLabSources({ context, zh }: { context?: LabContext; zh: boolean }) {
  const parsed = parseLabContext(context);
  const usable = parsed?.status === 'available';
  const snapshot = parsed?.snapshot;
  return <section className={styles.sources} aria-label={zh ? '教授与实验室官网资料' : 'Faculty and lab website sources'}>
    <h4>{zh ? '官网研究资料' : 'Website research sources'}</h4>
    <p className={styles.note}>{usable
      ? (zh ? '用于说明研究方向。不能证明正在招人，也不代表你读过这些资料或具备其中的技能。' : 'Use these sources for research context. They do not confirm an opening, your reading, or your skills.')
      : parsed?.status === 'stale'
        ? (zh ? '资料已过期，暂不用于新建议。可查看上次保存的原文。' : 'These sources are out of date and excluded from new suggestions. You can still view the saved text.')
        : (zh ? '暂时没有核对过的官网研究资料。' : 'No verified website research material is available yet.')}</p>
    {snapshot && <>
      <p className={styles.checked}>{zh ? '核对时间（UTC）：' : 'Checked (UTC): '}
        <time dateTime={snapshot.checked_at}>{snapshot.checked_at.replace('T', ' ').replace(/(?:\.\d+)?Z$/, '')}</time>
      </p>
      {snapshot.pages.map((page, index) => <details key={`${snapshot.snapshot_version}:${index}`} className={styles.page}>
        <summary>{page.kind === 'faculty_profile' ? (zh ? '教授主页：' : 'Faculty profile: ') : (zh ? '实验室官网：' : 'Lab website: ')}{page.page_title}</summary>
        <a href={page.source_url} target="_blank" rel="noopener noreferrer">{zh ? '打开原始页面' : 'Open source page'}</a>
        {page.sections.map(section => <div key={section.section_id} className={styles.excerpt}>
          {section.heading && <h5>{section.heading}</h5>}
          <p>{section.text}</p>
        </div>)}
      </details>)}
    </>}
  </section>;
}
