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
      {snapshot.version === 2 && <details key={`${snapshot.snapshot_version}:chain`} className={styles.chain}>
        <summary>{zh ? '查看来源核对过程' : 'View source verification'}</summary>
        <p className={styles.note}>{zh
          ? '教授主页链接到实验室首页；首页再链接到团队页和研究页。以下是资料来源核对，不是你的阅读记录。'
          : 'The faculty page links to the lab homepage, which links to the team and research pages. This verifies source links, not your reading.'}</p>
        <ol aria-label={zh ? '来源页面' : 'Source pages'}>
          {snapshot.source_chain.documents.map(document => <li key={document.role}>
            <span>{({profile: zh ? '教授主页' : 'Faculty profile', home: zh ? '实验室首页' : 'Lab homepage', team: zh ? '团队身份页' : 'Team identity page', research: zh ? '完整研究页' : 'Full research page'})[document.role]}: </span>
            <a href={document.source_url} target="_blank" rel="noopener noreferrer">{document.page_title}</a>
          </li>)}
        </ol>
        <ul aria-label={zh ? '已观察到的链接' : 'Observed links'}>
          {snapshot.source_chain.links.map((link, index) => <li key={index}>
            <span>{index === 0 ? (zh ? '教授主页 → 实验室首页' : 'Faculty profile → Lab homepage')
              : index === 1 ? (zh ? '实验室首页 → 团队页' : 'Lab homepage → Team page')
                : (zh ? '实验室首页 → 研究页' : 'Lab homepage → Research page')}</span>
            <span className={styles.rawLink}>{zh ? '原始链接：' : 'Original link: '}{link.raw_href}</span>
          </li>)}
        </ul>
        <p className={styles.note}>{zh ? '团队页身份：' : 'Identity on the team page: '}
          <strong>{snapshot.source_chain.identity.full_name}</strong> — {snapshot.source_chain.identity.role_text}
        </p>
      </details>}
      {snapshot.pages.map((page, index) => <details key={`${snapshot.snapshot_version}:${index}`} className={styles.page}>
        <summary>{page.kind === 'faculty_profile' ? (zh ? '教授主页：' : 'Faculty profile: ') : page.kind === 'lab_research' ? (zh ? '实验室研究全文：' : 'Full lab research: ') : (zh ? '实验室官网：' : 'Lab website: ')}{page.page_title}</summary>
        <a href={page.source_url} target="_blank" rel="noopener noreferrer">{zh ? '打开原始页面' : 'Open source page'}</a>
        {page.sections.map(section => <div key={section.section_id} className={styles.excerpt}>
          {section.heading && <h5>{section.heading}</h5>}
          <p>{section.text}</p>
        </div>)}
      </details>)}
    </>}
  </section>;
}
