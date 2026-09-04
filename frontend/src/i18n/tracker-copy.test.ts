/**
 * The exact strings the tracker surfaces render, in both languages.
 *
 * Every page test in this repo mocks `t` to return the key, which is right
 * for testing structure and useless for testing wording — a page can render
 * `tracker.title` forever while the dictionary says something false. These
 * assertions read the dictionary directly.
 *
 * What they pin: the board's first column is Contacted, and a faculty contact
 * is the majority of what a student tracks here. Calling the whole surface an
 * "Application Tracker" told them their outreach did not count.
 */
import { describe, expect, it } from 'vitest';
import { INTERACTION_OPTIONS } from '@/app/opportunities/[id]/types';
import { dictionaries } from './dictionaries';

const en = dictionaries.en;
const zh = dictionaries.zh;

describe('tracker copy names outreach as well as applications', () => {
  it('the board page', () => {
    expect(en.tracker.title).toBe('Outreach & application tracker');
    expect(en.tracker.subtitle)
      .toBe('Your outreach and applications, organized by stage.');
    expect(en.tracker.emptyTitle).toBe('Nothing tracked yet');
    expect(en.tracker.emptyBody).toBe(
      'Mark an opportunity as Contacted, Applied, Replied, or Interviewing '
      + 'from your results and it will show up here.',
    );
    expect(en.tracker.loadError).toBe(
      "Couldn't load your tracker — everything you have tracked is safe.",
    );

    expect(zh.tracker.title).toBe('联系与申请追踪');
    expect(zh.tracker.subtitle).toBe('你的联系与申请记录，按阶段整理。');
    expect(zh.tracker.emptyTitle).toBe('还没有追踪任何记录');
    expect(zh.tracker.emptyBody)
      .toBe('在结果页把某个机会标为「已联系 / 已申请 / 已回复 / 面试中」，它就会出现在这里。');
    expect(zh.tracker.loadError).toBe('无法加载追踪看板——你记录的内容仍然安全。');
  });

  it('the dashboard section', () => {
    expect(en.dashboard.trackerSection.title).toBe('Outreach & application tracker');
    expect(en.dashboard.trackerSection.emptyTitle).toBe('Nothing tracked yet');
    expect(en.dashboard.trackerSection.emptyBody).toBe(
      'Mark opportunities as Contacted, Applied, Replied, or Interviewing '
      + 'from the results page and they will show up here.',
    );
    expect(en.dashboard.trackerSection.errorTitle).toBe("Couldn't load your tracker.");

    expect(zh.dashboard.trackerSection.title).toBe('联系与申请追踪');
    expect(zh.dashboard.trackerSection.emptyTitle).toBe('还没有跟踪任何记录');
    expect(zh.dashboard.trackerSection.emptyBody)
      .toBe('在结果页把机会标记为已联系、已申请、已回复或面试中，它们就会显示在这里。');
    expect(zh.dashboard.trackerSection.errorTitle).toBe('无法加载你的联系与申请追踪。');
  });

  it('the other places that name the tracker to a student', () => {
    expect(en.account.trackerDesc).toBe("Outreach and applications you're tracking");
    expect(en.dashboard.subtitle).toBe(
      'Your saved targets, deadlines, outreach, and application progress.',
    );
    expect(en.onboarding.trackerTitle).toBe('Track every outreach and application');
    expect(en.onboarding.trackerBody).toBe(
      'Move each opportunity through Contacted → Applied → Replied → Interviewing, '
      + 'add notes, and set reminders so nothing slips.',
    );
    expect(en.home.walkthrough.steps.tracker.title)
      .toBe('Track every outreach and application');
    expect(en.home.walkthrough.steps.tracker.caption).toBe(
      'A board of everyone you’ve contacted and everything you’ve applied to — '
      + 'statuses, notes, and reminders so no reply falls through.',
    );
    // EN nav stays the generic "Tracker" — it is a name, not a claim.
    expect(en.nav.tracker).toBe('Tracker');

    expect(zh.account.trackerDesc).toBe('你正在追踪的联系与申请');
    // ZH has no short generic equivalent, so both of these carried the
    // application-only name.
    expect(zh.account.tracker).toBe('联系与申请追踪');
    expect(zh.nav.tracker).toBe('联系与申请追踪');
    expect(zh.dashboard.subtitle).toBe('你的收藏、截止日期、联系与申请进度。');
    expect(zh.onboarding.trackerTitle).toBe('追踪每一次联系与申请');
    expect(zh.onboarding.trackerBody)
      .toBe('把每个机会在「已联系 → 已申请 → 已回复 → 面试中」之间推进,记笔记、设提醒,不漏任何一步。');
  });
});

describe('the admin unreviewed-record-kind queue has real copy in both languages', () => {
  // AdminDashboard.test.tsx and SourceTable.test.tsx use local stub
  // dictionaries, so they prove the components ask for the right keys and
  // nothing about whether those keys exist. Deleting or misspelling either
  // one here would leave both suites green and print a raw key on the board.
  it.each([
    ['en', en],
    ['zh', zh],
  ])('%s has both the card label and the column header', (_, dict) => {
    for (const value of [
      dict.admin.unreviewedRecordKind,
      dict.admin.bySourceCols.unreviewedRecordKind,
    ]) {
      expect(typeof value).toBe('string');
      expect(value.trim().length).toBeGreaterThan(0);
      // Not the key echoed back — that is what a missing entry looks like.
      expect(value).not.toContain('unreviewedRecordKind');
      expect(value).not.toContain('admin.');
    }
  });

  it('says the same thing in each language', () => {
    expect(en.admin.unreviewedRecordKind).toBe('Unreviewed record type');
    expect(zh.admin.unreviewedRecordKind).toBe('未审核记录类型');
    expect(en.admin.bySourceCols.unreviewedRecordKind).toBe('Unreviewed type');
    expect(zh.admin.bySourceCols.unreviewedRecordKind).toBe('类型未审核');
  });
});

describe('reminder copy describes the state, never the target', () => {
  it('names the state, because an actionable listing marked rejected is undeliverable too', () => {
    expect(en.tracker.reminderUnavailable)
      .toBe('New reminders are unavailable in the current state.');
    expect(en.tracker.reminderWontSend)
      .toBe('This reminder will not be sent in the current state.');
    expect(en.coldEmail.reminderUnavailable)
      .toBe('Sent. A follow-up reminder is unavailable in the current state.');

    expect(zh.tracker.reminderUnavailable).toBe('当前状态下无法新建提醒。');
    expect(zh.tracker.reminderWontSend).toBe('当前状态下不会发送这条提醒。');
    expect(zh.coldEmail.reminderUnavailable).toBe('已发送。当前状态下无法设置跟进提醒。');
  });

  it('the dashboard says "not deliverable", never "could not be loaded"', () => {
    // Most of these resolved perfectly well; they are closed, unreviewed, or
    // in a status the cron does not select. Claiming a load failure would be
    // false, and claiming they are due would be worse.
    expect(en.dashboard.reminders.needsReview).toBe(
      "{count} reminders aren't currently deliverable — open your tracker to review them.",
    );
    expect(en.dashboard.reminders.detailsUnavailable).toBe(
      "We couldn't confirm which reminders will be delivered, so none are shown as due "
      + '— check them in your tracker.',
    );

    expect(zh.dashboard.reminders.needsReview)
      .toBe('有 {count} 条提醒当前无法发送——请到追踪看板查看。');
    expect(zh.dashboard.reminders.detailsUnavailable)
      .toBe('我们无法确认哪些提醒会被发送，因此不显示任何到期标签——请到追踪看板查看。');
  });
});

/**
 * The pill row on an opportunity page is built by mapping INTERACTION_OPTIONS
 * and translating `detail.interactions.<type>`. Walking the flow on production
 * 2026-08-30 found a button reading literally "detail.interactions.contacted":
 * 'contacted' joined the option list with the W12-15 tracker merge and neither
 * dictionary ever got the label. Every other page test mocks `t` to echo the
 * key, so the raw key looked exactly like a pass.
 */
describe('every status pill the detail page can render has a label', () => {
  it.each(['en', 'zh'] as const)('%s', (locale) => {
    const labels = dictionaries[locale].detail.interactions as Record<string, string>;
    const missing = INTERACTION_OPTIONS.filter((type) => !labels[type]);
    expect(missing).toEqual([]);
  });
});

describe('the undated deadline chip says what it selects', () => {
  // The chip filters on `is_rolling`, which campus_graph.py,
  // simplify_internships.py and ucb_campus.py all write as a literal `True`
  // whenever a scrape found no date. 6,690 non-faculty records carry it; 58
  // have the scraped `deadline_note` that noDeadlineKind requires before any
  // surface may say "rolling". Two testers walking production picked this chip
  // and were shown programs whose own pages publish a deadline — Northwestern
  // SynBREU, cohort already formed, and UIUC PRIMO.
  //
  // types.ts already states the rule ("`is_rolling` alone is a blanket
  // collector default and must never be presented as a scraped fact") and the
  // detail and compare surfaces obey it. This is the one that did not.
  // EVERY key that names this filter, not just the chip. The button in the
  // empty state applies the identical filter and still said "Show listings
  // marked rolling" / "查看标注为滚动招生的项目" — the guard could not fail on it
  // because it only ever read the sibling. 滚动 is in the alternation for the
  // same reason: it is the word this product's own zh dictionary uses for
  // rolling, so without it the zh half could not catch the regression either.
  const ROLLING_LABEL_KEYS = [
    ['results', 'filters', 'deadlineRolling'],
    ['results', 'empty', 'showRolling'],
  ] as const;

  it.each(['en', 'zh'] as const)('%s promises no open window', (locale) => {
    for (const path of ROLLING_LABEL_KEYS) {
      const label = path.reduce<unknown>((node, key) => (node as Record<string, unknown>)[key], dictionaries[locale]);
      expect(label, path.join('.')).toBeTruthy();
      expect(label as string, path.join('.')).not.toMatch(/rolling|anytime|滚动|常年|随时/i);
    }
  });
});

describe('the field-relevance line says what it counts', () => {
  // Three testers read "1142 strong matches in your field" over chips saying
  // High Priority 22 / Good Match 1296, and "31 strong matches" over a High
  // Priority of 1 after a filter. The number counts results with any keyword
  // overlap with the student's field (ranker.field_relevant) — no quality
  // threshold at all. The app's own word for quality is the bucket label, so
  // this line may not borrow it.
  it.each(['en', 'zh'] as const)('%s does not claim strength', (locale) => {
    const { fieldMatches, fieldMatchesOne } = dictionaries[locale].results;
    for (const label of [fieldMatches, fieldMatchesOne]) {
      expect(label).toBeTruthy();
      expect(label).not.toMatch(/strong|强匹配|优质/i);
    }
    expect(fieldMatches).toMatch(/\{count\}/);
  });
});
