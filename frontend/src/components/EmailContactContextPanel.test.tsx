import { fireEvent, render, screen, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { describe, expect, it, vi } from 'vitest';
import type { EmailContactContext, Opportunity } from '@/lib/types';
import { EMAIL_CONTACT_DRAFT_MAX_LENGTH, type EmailContactDraftSnapshot } from '@/lib/email-contact-draft';
import EmailContactContextPanel, { type EmailContactContextPanelProps } from './EmailContactContextPanel';

function mount(overrides: Partial<EmailContactContextPanelProps> = {}) {
  const props: EmailContactContextPanelProps = {
    onDraftChange: vi.fn(), onApply: vi.fn(), resetKey: 'owner-a:target-a:open-1', language: 'en', ...overrides,
  };
  const result = render(<EmailContactContextPanel {...props} />);
  const panel = screen.getByTestId('email-contact-context-panel') as HTMLDetailsElement;
  if (!panel.open) fireEvent.click(within(panel).getByText('Contact purpose and background'));
  return { ...result, props };
}
const apply = () => screen.getByRole('button', { name: 'Apply background to this draft' });
const purpose = () => screen.getByRole('combobox', { name: 'Contact purpose' });
const referralName = () => screen.getByRole('textbox', { name: 'Who referred you? (required)' });
const referralNote = () => screen.getByRole('textbox', { name: 'What did they actually say or suggest? (required)' });
const referralConfirm = () => screen.getByRole('checkbox', { name: 'I confirm these referral details are accurate and I may mention this person in the draft.' });
const previousMessage = () => screen.getByRole('textbox', { name: 'Previous email you sent (required)' });
const sentConfirm = () => screen.getByRole('checkbox', { name: 'I confirm I actually sent this email to this target and these details are accurate. This does not record a new send.' });
const availability = () => screen.getByRole('textbox', { name: 'When could you participate? (optional)' });
const availabilityConfirm = () => screen.getByRole('checkbox', { name: 'I confirm this availability is accurate.' });
function referral(name = 'Pat Lee', note = 'Pat suggested asking about a research project; this is not an endorsement.') {
  fireEvent.change(purpose(), { target: { value: 'referral' } });
  fireEvent.change(referralName(), { target: { value: name } });
  fireEvent.change(referralNote(), { target: { value: note } });
}
function followUp() {
  fireEvent.change(purpose(), { target: { value: 'follow_up' } });
  fireEvent.change(previousMessage(), { target: { value: 'Dear researcher,\nCould I ask about this project?\nRegards, Student' } });
}

describe('email contact context panel', () => {
  it('starts with first contact applied, leaves optional facts empty and never generates or contacts anyone', () => {
    const { props } = mount();
    expect(purpose()).toHaveValue('first_contact');
    expect(screen.getByTestId('email-contact-context-status')).toHaveTextContent('Background confirmed for the next draft');
    expect(apply()).toBeDisabled();
    expect(availability()).toHaveValue('');
    expect(props.onDraftChange).not.toHaveBeenCalled();
    expect(props.onApply).not.toHaveBeenCalled();
    expect(screen.getByText(/does not generate or send an email/)).toBeInTheDocument();
  });

  it('requires specific referral facts and explicit confirmation before applying an independent normalized copy', () => {
    const { props } = mount();
    fireEvent.change(purpose(), { target: { value: 'referral' } });
    fireEvent.click(apply());
    expect(screen.getByRole('alert')).toHaveTextContent('required details');
    expect(props.onApply).not.toHaveBeenCalled();
    fireEvent.change(referralName(), { target: { value: '  Pat 李  ' } });
    const note = '  Pat suggested asking.\nThey did not endorse my work.  ';
    fireEvent.change(referralNote(), { target: { value: note } });
    fireEvent.click(apply());
    expect(screen.getByRole('alert')).toHaveTextContent('Confirm the details');
    expect(props.onApply).not.toHaveBeenCalled();
    fireEvent.click(referralConfirm());
    fireEvent.click(apply());
    expect(props.onApply).toHaveBeenCalledExactlyOnceWith({ version: 1, purpose: 'referral',
      referral: { referrer_name: 'Pat 李', referral_note: note.trim(), confirmed: true } });
    expect(props.onDraftChange).toHaveBeenCalledTimes(4);
    expect(apply()).toBeDisabled();
  });

  it('invalidates previous confirmation synchronously on every fact edit and keeps all words', () => {
    const { props } = mount(); referral(); fireEvent.click(referralConfirm()); fireEvent.click(apply());
    const replacement = 'New exact information.\nI was not referred as an expert.';
    fireEvent.change(referralNote(), { target: { value: replacement } });
    expect(referralConfirm()).not.toBeChecked();
    expect(referralNote()).toHaveValue(replacement);
    expect(screen.getByTestId('email-contact-context-status')).toHaveTextContent('Changes are not applied');
    fireEvent.click(apply());
    expect(props.onApply).toHaveBeenCalledTimes(1);
    expect(screen.getByRole('alert')).toHaveTextContent('Confirm the details');
  });

  it('requires confirmation of a sent message without inventing a date or assuming no reply', () => {
    const { props } = mount(); followUp();
    expect(screen.getByRole('combobox', { name: 'Reply status' })).toHaveValue('unknown');
    fireEvent.click(apply());
    expect(props.onApply).not.toHaveBeenCalled();
    fireEvent.click(sentConfirm()); fireEvent.click(apply());
    expect(props.onApply).toHaveBeenCalledExactlyOnceWith({
      version: 1, purpose: 'follow_up',
      follow_up: { sent_confirmed: true, previous_message: 'Dear researcher,\nCould I ask about this project?\nRegards, Student', reply_status: 'unknown' },
    });
    expect(screen.getByTestId('email-contact-context-status')).toHaveTextContent('Background confirmed for the next draft');
  });

  it('requires received reply text, clears confirmation when status changes and omits inactive reply text', () => {
    const { props } = mount(); followUp();
    const status = screen.getByRole('combobox', { name: 'Reply status' });
    fireEvent.change(status, { target: { value: 'received' } });
    fireEvent.click(sentConfirm()); fireEvent.click(apply());
    expect(props.onApply).not.toHaveBeenCalled();
    expect(screen.getByRole('alert')).toHaveTextContent('required details');
    const reply = 'Please send a short description.\nDo not imply acceptance.';
    fireEvent.change(screen.getByRole('textbox', { name: 'Reply you received (required)' }), { target: { value: reply } });
    expect(sentConfirm()).not.toBeChecked();
    fireEvent.click(sentConfirm()); fireEvent.click(apply());
    expect(vi.mocked(props.onApply).mock.calls[0][0].follow_up).toMatchObject({ reply_status: 'received', reply_text: reply });
    fireEvent.change(status, { target: { value: 'unknown' } });
    expect(sentConfirm()).not.toBeChecked();
    fireEvent.click(sentConfirm()); fireEvent.click(apply());
    expect(vi.mocked(props.onApply).mock.calls[1][0].follow_up).not.toHaveProperty('reply_text');
    fireEvent.change(status, { target: { value: 'received' } });
    expect(screen.getByRole('textbox', { name: 'Reply you received (required)' })).toHaveValue(reply);
    expect(sentConfirm()).not.toBeChecked();
  });

  it.each(['declined', 'do_not_contact'])('keeps %s as a blocked UI-only state and allows an explicit return to first contact', (status) => {
    const { props } = mount(); followUp();
    const original = (previousMessage() as HTMLTextAreaElement).value;
    fireEvent.change(screen.getByRole('combobox', { name: 'Reply status' }), { target: { value: status } });
    fireEvent.click(sentConfirm());
    expect(apply()).toBeDisabled();
    expect(screen.getByRole('alert')).toHaveTextContent('current email and answers are kept');
    expect(previousMessage()).toHaveValue(original);
    expect(props.onApply).not.toHaveBeenCalled();
    fireEvent.change(purpose(), { target: { value: 'first_contact' } });
    fireEvent.click(apply());
    expect(props.onApply).toHaveBeenCalledExactlyOnceWith({ version: 1, purpose: 'first_contact' });
    fireEvent.change(purpose(), { target: { value: 'follow_up' } });
    expect(previousMessage()).toHaveValue(original);
    expect(sentConfirm()).not.toBeChecked();
    expect(apply()).toBeDisabled();
  });

  it('requires optional availability confirmation or an explicit skip, without silently including it', () => {
    const { props } = mount();
    fireEvent.change(availability(), { target: { value: '  Tuesdays, 3 hours; no summer availability.  ' } });
    fireEvent.click(apply());
    expect(props.onApply).not.toHaveBeenCalled();
    fireEvent.click(availabilityConfirm()); fireEvent.click(apply());
    expect(props.onApply).toHaveBeenLastCalledWith({ version: 1, purpose: 'first_contact',
      availability: { text: 'Tuesdays, 3 hours; no summer availability.', confirmed: true } });
    fireEvent.click(screen.getByRole('button', { name: 'Skip availability' }));
    expect(availability()).toHaveValue('');
    fireEvent.click(apply());
    expect(props.onApply).toHaveBeenLastCalledWith({ version: 1, purpose: 'first_contact' });
  });

  it('clears all fact confirmations after an unrelated background field changes, but confirming one does not clear another', () => {
    const { props } = mount(); referral();
    fireEvent.change(availability(), { target: { value: 'Friday afternoons.' } });
    fireEvent.click(referralConfirm()); fireEvent.click(availabilityConfirm());
    expect(referralConfirm()).toBeChecked(); expect(availabilityConfirm()).toBeChecked();
    fireEvent.change(referralName(), { target: { value: 'Pat A. Lee' } });
    expect(referralConfirm()).not.toBeChecked(); expect(availabilityConfirm()).not.toBeChecked();
    fireEvent.click(apply()); expect(props.onApply).not.toHaveBeenCalled();
  });

  it('retains an over-limit Unicode answer without clipping it or submitting', () => {
    const { props } = mount(); const long = '研究😀'.repeat(501) + '\nTAIL';
    referral('Pat', long); fireEvent.click(referralConfirm()); fireEvent.click(apply());
    expect(referralNote()).toHaveValue(long);
    expect(referralNote()).not.toHaveAttribute('maxlength');
    expect(props.onApply).not.toHaveBeenCalled();
    expect(screen.getByRole('alert')).toHaveTextContent('full text is kept');
  });

  it.each(['2026-02-30', 'not a date'])('rejects an invalid date %s while keeping the message and date', (date) => {
    const { props } = mount(); followUp();
    const input = screen.getByRole('textbox', { name: 'Date sent (optional, YYYY-MM-DD)' });
    fireEvent.change(input, { target: { value: date } });
    fireEvent.click(sentConfirm()); fireEvent.click(apply());
    expect(props.onApply).not.toHaveBeenCalled();
    expect(input).toHaveValue(date); expect(previousMessage()).not.toHaveValue('');
    expect(screen.getByRole('alert')).toHaveTextContent('invalid or too long');
  });

  it.each(['bad\u0000value', 'bad\uD800value'])('keeps unsupported Unicode input visible and safely refuses it', (bad) => {
    const { props } = mount(); referral('Pat', bad);
    fireEvent.click(referralConfirm()); fireEvent.click(apply());
    expect(props.onApply).not.toHaveBeenCalled(); expect(referralNote()).toHaveValue(bad);
    expect(screen.getByRole('alert')).toHaveTextContent('invalid or too long');
    expect(screen.getByRole('alert').textContent).not.toContain(bad);
  });

  it('retains dirty answers through parent rerenders, external context changes, collapse and language changes', () => {
    const { props, rerender } = mount(); referral('Private name', 'Private unsaved answer');
    rerender(<EmailContactContextPanel {...props} context={{ version: 1, purpose: 'first_contact', availability: { text: 'Remote accepted value', confirmed: true } }} />);
    expect(referralName()).toHaveValue('Private name'); expect(referralNote()).toHaveValue('Private unsaved answer');
    fireEvent.click(screen.getByText('Contact purpose and background'));
    expect(screen.getByTestId('email-contact-context-panel')).not.toHaveAttribute('open');
    fireEvent.click(screen.getByText('Contact purpose and background'));
    expect(referralNote()).toHaveValue('Private unsaved answer');
    rerender(<EmailContactContextPanel {...props} language="zh" />);
    expect(screen.getByRole('textbox', { name: '对方具体怎样介绍或建议联系？（必填）' })).toHaveValue('Private unsaved answer');
    expect(screen.getByTestId('email-contact-context-status')).toHaveTextContent('改动尚未应用');
    expect(props.onApply).not.toHaveBeenCalled();
  });

  it('resets private fields synchronously for a new owner or target session', () => {
    const { props, rerender } = mount(); referral('Private name', 'Old owner confidential note');
    rerender(<EmailContactContextPanel {...props} resetKey="owner-b:target-b:open-2" />);
    const panel = screen.getByTestId('email-contact-context-panel');
    expect(panel).not.toHaveTextContent('Old owner confidential note');
    fireEvent.click(screen.getByText('Contact purpose and background'));
    expect(purpose()).toHaveValue('first_contact');
    fireEvent.change(purpose(), { target: { value: 'referral' } });
    expect(referralName()).toHaveValue(''); expect(referralNote()).toHaveValue('');
    expect(referralConfirm()).not.toBeChecked(); expect(props.onApply).not.toHaveBeenCalled();
  });

  it('adopts a new external accepted context while pristine without mutating it or reporting a user edit', () => {
    const { props, rerender } = mount();
    const context: EmailContactContext = { version: 1, purpose: 'referral',
      referral: { referrer_name: 'Pat', referral_note: 'Suggested a conversation.', confirmed: true } };
    const before = JSON.stringify(context);
    rerender(<EmailContactContextPanel {...props} context={context} />);
    expect(purpose()).toHaveValue('referral'); expect(referralName()).toHaveValue('Pat'); expect(referralConfirm()).toBeChecked();
    expect(apply()).toBeDisabled(); expect(props.onDraftChange).not.toHaveBeenCalled();
    expect(JSON.stringify(context)).toBe(before);
  });

  it('preserves input through disabled state and does not emit changes or apply while paused', () => {
    const { props, rerender } = mount(); referral();
    const changes = vi.mocked(props.onDraftChange).mock.calls.length;
    rerender(<EmailContactContextPanel {...props} disabled />);
    expect(referralName()).toBeDisabled(); expect(apply()).toBeDisabled();
    fireEvent.change(referralName(), { target: { value: 'Forced event' } });
    fireEvent.click(referralConfirm()); fireEvent.click(apply());
    expect(referralName()).toHaveValue('Pat Lee');
    expect(props.onDraftChange).toHaveBeenCalledTimes(changes); expect(props.onApply).not.toHaveBeenCalled();
    rerender(<EmailContactContextPanel {...props} />);
    expect(referralName()).toHaveValue('Pat Lee'); expect(referralConfirm()).not.toBeChecked();
  });

  it('preserves text and shows only a safe error if the parent cannot apply it', () => {
    const onApply = vi.fn().mockImplementationOnce(() => { throw new Error('PRIVATE server content'); });
    mount({ onApply }); referral(); fireEvent.click(referralConfirm()); fireEvent.click(apply());
    expect(screen.getByRole('alert')).toHaveTextContent('could not be applied');
    expect(screen.getByRole('alert').textContent).not.toContain('PRIVATE');
    expect(referralNote()).not.toHaveValue('');
    fireEvent.click(apply()); expect(onApply).toHaveBeenCalledTimes(2);
  });

  it('keeps a continuously typed focused field mounted and makes all confirmation controls keyboard reachable', async () => {
    const user = userEvent.setup(); mount();
    await user.selectOptions(purpose(), 'referral');
    await user.click(referralName()); await user.type(referralName(), 'Pat Lee');
    expect(referralName()).toHaveFocus(); expect(referralName()).toHaveValue('Pat Lee');
    await user.tab(); expect(referralNote()).toHaveFocus();
    await user.type(referralNote(), 'Suggested a conversation.');
    await user.tab(); expect(referralConfirm()).toHaveFocus();
    await user.keyboard(' '); expect(referralConfirm()).toBeChecked();
    await user.tab(); expect(availability()).toHaveFocus();
    await user.tab(); expect(apply()).toHaveFocus();
  });

  it('keeps an invalid supplied context unconfirmed instead of presenting a false applied default', () => {
    mount({ context: { version: 1, purpose: 'referral', referral: { referrer_name: 'Missing rest' } } as EmailContactContext });
    expect(screen.getByTestId('email-contact-context-status')).toHaveTextContent('Changes are not applied');
    expect(screen.getByRole('alert')).toHaveTextContent('invalid');
  });
});


const paperOne = { title: 'Grounded Models 研究 🧪', year: 2025 };
const paperTwo = { title: 'Second study', year: 2024 };
const paperTarget = (papers: unknown[] = [paperOne, paperTwo], status = 'verified_author_id') => ({ id: 'paper-target', metadata: { recent_works: papers, publication_attribution_status: status } } as Opportunity);
const paperSelect = () => screen.getByRole('combobox', { name: 'Paper you looked at (optional)' });
const readingSelect = () => screen.getByRole('combobox', { name: 'How much did you read?' });
const readingConfirm = () => screen.getByRole('checkbox', { name: 'I confirm this reading level for the selected paper.' });
function selectReading(level = 'abstract') {
  fireEvent.change(paperSelect(), { target: { value: JSON.stringify([paperOne.title, paperOne.year]) } });
  fireEvent.change(readingSelect(), { target: { value: level } });
}

describe('verified paper reading preparation', () => {
  it.each(['title_only', 'abstract', 'full_text'])('requires a selected verified paper, explicit %s level and confirmation', level => {
    const { props } = mount({ opportunity: paperTarget() });
    expect(paperSelect()).toHaveValue('');
    expect(screen.queryByRole('combobox', { name: 'How much did you read?' })).toBeNull();
    fireEvent.change(paperSelect(), { target: { value: JSON.stringify([paperOne.title, paperOne.year]) } });
    fireEvent.click(apply()); expect(props.onApply).not.toHaveBeenCalled();
    expect(screen.getByRole('alert')).toHaveTextContent('reading level');
    fireEvent.change(readingSelect(), { target: { value: level } });
    fireEvent.click(apply()); expect(props.onApply).not.toHaveBeenCalled();
    fireEvent.click(readingConfirm()); fireEvent.click(apply());
    expect(props.onApply).toHaveBeenCalledExactlyOnceWith({ version: 1, purpose: 'first_contact', paper_reading: { ...paperOne, level, confirmed: true } });
    expect(screen.getByText(/does not claim understanding/)).toBeInTheDocument();
  });
  it('never lets a user type or add an arbitrary professor publication', () => {
    mount({ opportunity: paperTarget() });
    expect(within(paperSelect()).getAllByRole('option').map(o => o.textContent)).toEqual(['Skip paper reading', 'Grounded Models 研究 🧪 (2025)', 'Second study (2024)']);
    expect(screen.queryByRole('textbox', { name: /paper/i })).toBeNull();
  });
  it('invalidates reading confirmation on paper, level, or other background edits', () => {
    mount({ opportunity: paperTarget() }); selectReading(); fireEvent.click(readingConfirm());
    fireEvent.change(readingSelect(), { target: { value: 'full_text' } }); expect(readingConfirm()).not.toBeChecked();
    fireEvent.click(readingConfirm());
    fireEvent.change(paperSelect(), { target: { value: JSON.stringify([paperTwo.title, paperTwo.year]) } }); expect(readingConfirm()).not.toBeChecked();
    fireEvent.click(readingConfirm());
    fireEvent.change(availability(), { target: { value: 'Tuesday afternoons' } }); expect(readingConfirm()).not.toBeChecked();
  });
  it('supports skipping after a reading claim without keeping that claim in the applied context', () => {
    const { props } = mount({ opportunity: paperTarget() }); selectReading(); fireEvent.click(readingConfirm()); fireEvent.click(apply());
    fireEvent.click(screen.getByRole('button', { name: 'Skip paper reading' })); fireEvent.click(apply());
    expect(props.onApply).toHaveBeenLastCalledWith({ version: 1, purpose: 'first_contact' });
  });
  it.each(['name_match', 'pending', ''])('hides unverified titles for %s while letting the user skip', status => {
    const { props } = mount({ opportunity: paperTarget([paperOne], status) });
    expect(paperSelect()).toBeDisabled(); expect(screen.queryByText(/Grounded Models/)).toBeNull();
    expect(screen.getByText(/No papers matched to this researcher/)).toBeInTheDocument();
    expect(props.onApply).not.toHaveBeenCalled(); expect(apply()).toBeDisabled();
  });
  it('retires a removed paper confirmation, preserves other draft answers and requires an explicit skip or new choice', () => {
    const { props, rerender } = mount({ opportunity: paperTarget(), targetKey: 'version-1' });
    selectReading(); fireEvent.change(availability(), { target: { value: 'My original Tuesday availability.' } });
    fireEvent.click(readingConfirm()); fireEvent.click(availabilityConfirm()); fireEvent.click(apply());
    const before = vi.mocked(props.onDraftChange).mock.calls.length;
    rerender(<EmailContactContextPanel {...props} opportunity={paperTarget([paperTwo])} targetKey="version-2" />);
    expect(props.onDraftChange).toHaveBeenCalledTimes(before + 1);
    expect(readingConfirm()).not.toBeChecked(); expect(availability()).toHaveValue('My original Tuesday availability.');
    fireEvent.click(readingConfirm()); fireEvent.click(apply());
    expect(props.onApply).toHaveBeenCalledTimes(1); expect(screen.getByRole('alert')).toHaveTextContent('current verified paper');
    fireEvent.click(screen.getByRole('button', { name: 'Skip paper reading' })); fireEvent.click(availabilityConfirm()); fireEvent.click(apply());
    expect(props.onApply).toHaveBeenLastCalledWith({ version: 1, purpose: 'first_contact', availability: { text: 'My original Tuesday availability.', confirmed: true } });
  });
  it('requires re-confirmation even when a changed target version retains the same paper', () => {
    const context: EmailContactContext = { version: 1, purpose: 'first_contact', paper_reading: { ...paperOne, level: 'title_only', confirmed: true } };
    const { props, rerender } = mount({ context, opportunity: paperTarget(), targetKey: 'version-1' });
    expect(apply()).toBeDisabled();
    rerender(<EmailContactContextPanel {...props} targetKey="version-2" />);
    expect(readingConfirm()).not.toBeChecked(); expect(props.onDraftChange).toHaveBeenCalledExactlyOnceWith();
    fireEvent.click(apply()); expect(props.onApply).not.toHaveBeenCalled();
    fireEvent.click(readingConfirm()); fireEvent.click(apply()); expect(props.onApply).toHaveBeenCalledExactlyOnceWith(context);
  });
  it('adopts a simultaneously changed accepted context without losing its text and still revokes stale reading confirmation', () => {
    const { props, rerender } = mount({ opportunity: paperTarget(), targetKey: 'version-1' });
    const context: EmailContactContext = { version: 1, purpose: 'first_contact', availability: { text: 'Current accepted text', confirmed: true }, paper_reading: { ...paperOne, level: 'abstract', confirmed: true } };
    rerender(<EmailContactContextPanel {...props} context={context} targetKey="version-2" />);
    expect(availability()).toHaveValue('Current accepted text'); expect(readingConfirm()).not.toBeChecked();
    expect(props.onDraftChange).toHaveBeenCalledTimes(1);
  });
  it('clears paper selection on a new owner session and renders the same choices in Chinese', () => {
    const { props, rerender } = mount({ opportunity: paperTarget() }); selectReading(); fireEvent.click(readingConfirm());
    rerender(<EmailContactContextPanel {...props} resetKey="owner-b:new" language="zh" />);
    const panel = screen.getByTestId('email-contact-context-panel'); fireEvent.click(within(panel).getByText('联系目的与背景'));
    const select = screen.getByRole('combobox', { name: '你看过的论文（选填）' }); expect(select).toHaveValue('');
    fireEvent.change(select, { target: { value: JSON.stringify([paperOne.title, paperOne.year]) } });
    expect(screen.getByRole('combobox', { name: '你读到了哪一步？' })).toHaveValue('');
    expect(screen.getByRole('option', { name: '只看过标题' })).toBeInTheDocument();
    expect(screen.getByRole('checkbox', { name: '我确认自己对这篇论文的阅读程度。' })).not.toBeChecked();
  });
});


it('opens and revokes only reading confirmation on a server review request, retaining every other answer', () => {
  const context: EmailContactContext = { version: 1, purpose: 'first_contact', paper_reading: { ...paperOne, level: 'abstract', confirmed: true }, availability: { text: 'Five hours per week', confirmed: true } };
  const { props, rerender } = mount({ context, opportunity: paperTarget(), reviewRequested: 0 });
  const panel = screen.getByTestId('email-contact-context-panel') as HTMLDetailsElement;
  fireEvent.click(within(panel).getByText('Contact purpose and background'));
  rerender(<EmailContactContextPanel {...props} reviewRequested={1} />);
  expect(panel.open).toBe(true); expect(readingConfirm()).not.toBeChecked();
  expect(availability()).toHaveValue('Five hours per week'); expect(availabilityConfirm()).toBeChecked();
  expect(readingSelect()).toHaveValue('abstract'); expect(paperSelect()).not.toHaveValue('');
  expect(props.onDraftChange).not.toHaveBeenCalled(); expect(props.onApply).not.toHaveBeenCalled();
  fireEvent.click(apply()); expect(props.onApply).not.toHaveBeenCalled();
  fireEvent.click(readingConfirm()); fireEvent.click(apply()); expect(props.onApply).toHaveBeenCalledExactlyOnceWith(context);
});


describe('pending contact draft restoration', () => {
  const snapshotSpy = () => vi.fn<(snapshot: EmailContactDraftSnapshot | null) => void>();
  const lastSnapshot = (spy: ReturnType<typeof snapshotSpy>) => spy.mock.calls.at(-1)![0]!;

  it('restores partial raw text after unmount without applying it or inventing a confirmation', () => {
    const snapshots = snapshotSpy();
    const first = mount({ onDraftSnapshotChange: snapshots });
    fireEvent.change(purpose(), { target: { value: 'referral' } });
    fireEvent.change(referralName(), { target: { value: '  Unfinished name  ' } });
    const saved = lastSnapshot(snapshots);
    expect(saved.fields.referrerName).toBe('  Unfinished name  ');
    expect(saved.confirmed.referral).toBe(false); expect(saved.pending).toBe(true);
    first.unmount();
    const restored = mount({ initialDraft: saved, resetKey: 'owner-a:target-a:open-2' });
    expect(referralName()).toHaveValue('  Unfinished name  '); expect(referralNote()).toHaveValue('');
    expect(referralConfirm()).not.toBeChecked(); expect(restored.props.onApply).not.toHaveBeenCalled();
    expect(screen.getByTestId('email-contact-context-status')).toHaveTextContent('Changes are not applied');
    fireEvent.click(apply()); expect(restored.props.onApply).not.toHaveBeenCalled();
    expect(screen.getByRole('alert')).toHaveTextContent('required details');
  });

  it('restores checked but unapplied answers as pending and applies only on an explicit click', () => {
    const snapshots = snapshotSpy();
    const first = mount({ onDraftSnapshotChange: snapshots }); referral();
    fireEvent.click(referralConfirm());
    const saved = lastSnapshot(snapshots); expect(saved.confirmed.referral).toBe(true); expect(saved.pending).toBe(true);
    first.unmount();
    const restored = mount({ initialDraft: saved, onDraftSnapshotChange: snapshots });
    expect(referralConfirm()).toBeChecked(); expect(apply()).not.toBeDisabled();
    expect(restored.props.onApply).not.toHaveBeenCalled(); expect(lastSnapshot(snapshots).pending).toBe(true);
    fireEvent.click(apply());
    expect(restored.props.onApply).toHaveBeenCalledTimes(1); expect(lastSnapshot(snapshots).pending).toBe(false);
  });

  it('preserves malformed dates, over-limit original text, blocked status and inactive answers across reopening', () => {
    const snapshots = snapshotSpy(); const first = mount({ onDraftSnapshotChange: snapshots });
    const long = '研究😀'.repeat(600) + '\nTAIL';
    referral('Inactive referrer', long); followUp();
    fireEvent.change(screen.getByRole('textbox', { name: 'Date sent (optional, YYYY-MM-DD)' }), { target: { value: '20-??' } });
    fireEvent.change(screen.getByRole('combobox', { name: 'Reply status' }), { target: { value: 'declined' } });
    fireEvent.click(sentConfirm()); const saved = lastSnapshot(snapshots); first.unmount();
    const restored = mount({ initialDraft: saved });
    expect(screen.getByRole('textbox', { name: 'Date sent (optional, YYYY-MM-DD)' })).toHaveValue('20-??');
    expect(screen.getByRole('combobox', { name: 'Reply status' })).toHaveValue('declined');
    expect(sentConfirm()).toBeChecked(); expect(apply()).toBeDisabled(); expect(restored.props.onApply).not.toHaveBeenCalled();
    fireEvent.change(purpose(), { target: { value: 'referral' } });
    expect(referralName()).toHaveValue('Inactive referrer'); expect(referralNote()).toHaveValue(long);
    expect(referralConfirm()).not.toBeChecked();
  });

  it('ignores later initialDraft prop changes while keeping typing, focus and checkbox state in the current session', () => {
    const snapshots = snapshotSpy(); const view = mount({ onDraftSnapshotChange: snapshots });
    referral('Saved name', 'Saved note'); const old = lastSnapshot(snapshots);
    referralName().focus(); fireEvent.change(referralName(), { target: { value: 'Current typed name' } });
    fireEvent.click(referralConfirm()); const field = referralName(); field.focus();
    view.rerender(<EmailContactContextPanel {...view.props} initialDraft={old} language="zh" />);
    expect(screen.getByRole('textbox', { name: '谁介绍你联系？（必填）' })).toBe(field);
    expect(field).toHaveFocus(); expect(field).toHaveValue('Current typed name');
    expect(screen.getByRole('checkbox', { name: '我确认这些介绍信息属实，且可以在草稿中提及此人。' })).toBeChecked();
    expect(view.props.onApply).not.toHaveBeenCalled();
  });

  it('rejects a snapshot belonging to another opportunity instead of showing its private fields', () => {
    const snapshots = snapshotSpy(); const first = mount({ opportunity: paperTarget(), onDraftSnapshotChange: snapshots });
    referral('Private other target name', 'Private other target note'); const saved = lastSnapshot(snapshots); first.unmount();
    const restored = mount({ opportunity: { id: 'different-target' } as Opportunity, initialDraft: saved });
    expect(purpose()).toHaveValue('first_contact');
    fireEvent.change(purpose(), { target: { value: 'referral' } });
    expect(referralName()).toHaveValue(''); expect(referralNote()).toHaveValue('');
    expect(restored.props.onApply).not.toHaveBeenCalled();
  });

  it.each(['version', 'paper', 'attribution'])('revokes restored reading confirmation after a %s change and keeps every answer', change => {
    const snapshots = snapshotSpy(); const first = mount({ opportunity: paperTarget(), targetKey: 'v1', onDraftSnapshotChange: snapshots });
    selectReading('full_text'); fireEvent.change(availability(), { target: { value: 'Only Tuesday afternoons.' } });
    fireEvent.click(readingConfirm()); fireEvent.click(availabilityConfirm()); const saved = lastSnapshot(snapshots); first.unmount();
    const restored = mount({ initialDraft: saved, onDraftSnapshotChange: snapshots,
      opportunity: change === 'paper' ? paperTarget([paperTwo]) : change === 'attribution' ? paperTarget([paperOne], 'pending') : paperTarget(),
      targetKey: change === 'version' ? 'v2' : 'v1' });
    expect(readingConfirm()).not.toBeChecked(); expect(readingSelect()).toHaveValue('full_text');
    expect(paperSelect()).toHaveValue(saved.fields.paperKey); expect(availability()).toHaveValue('Only Tuesday afternoons.');
    expect(availabilityConfirm()).toBeChecked(); expect(lastSnapshot(snapshots).confirmed.paper).toBe(false);
    expect(lastSnapshot(snapshots).pending).toBe(true); expect(restored.props.onApply).not.toHaveBeenCalled();
    fireEvent.click(apply()); expect(restored.props.onApply).not.toHaveBeenCalled();
  });

  it('does not trust a stored applied marker when the separately accepted context is different', () => {
    const snapshots = snapshotSpy(); const first = mount({ onDraftSnapshotChange: snapshots });
    referral(); fireEvent.click(referralConfirm()); fireEvent.click(apply());
    const saved = lastSnapshot(snapshots); const accepted = vi.mocked(first.props.onApply).mock.calls[0][0];
    expect(saved.pending).toBe(false); first.unmount();
    const mismatched = mount({ initialDraft: saved });
    expect(apply()).not.toBeDisabled(); expect(mismatched.props.onApply).not.toHaveBeenCalled(); mismatched.unmount();
    const matched = mount({ initialDraft: saved, context: accepted });
    expect(apply()).toBeDisabled(); expect(matched.props.onApply).not.toHaveBeenCalled();
  });

  it('notifies edits, confirmations, failed and successful apply, source invalidation and server review with independent snapshots', () => {
    const snapshots = snapshotSpy(); const view = mount({ opportunity: paperTarget(), targetKey: 'v1', onDraftSnapshotChange: snapshots });
    const before = snapshots.mock.calls.length;
    selectReading(); expect(snapshots.mock.calls.length).toBe(before + 2);
    fireEvent.click(apply()); expect(snapshots.mock.calls.length).toBe(before + 3);
    fireEvent.click(readingConfirm()); expect(lastSnapshot(snapshots).confirmed.paper).toBe(true);
    const retained = lastSnapshot(snapshots); fireEvent.click(apply()); expect(lastSnapshot(snapshots).pending).toBe(false);
    view.rerender(<EmailContactContextPanel {...view.props} targetKey="v2" />);
    expect(lastSnapshot(snapshots).confirmed.paper).toBe(false); expect(retained.confirmed.paper).toBe(true);
    fireEvent.click(readingConfirm());
    view.rerender(<EmailContactContextPanel {...view.props} targetKey="v2" reviewRequested={1} />);
    expect(lastSnapshot(snapshots).confirmed.paper).toBe(false); expect(lastSnapshot(snapshots).pending).toBe(true);
  });

  it('reports an unsavable draft without clipping live input and can save again after the user shortens it', () => {
    const snapshots = snapshotSpy(); const view = mount({ onDraftSnapshotChange: snapshots });
    const long = 'x'.repeat(EMAIL_CONTACT_DRAFT_MAX_LENGTH) + 'TAIL'; referral('Pat', long);
    expect(lastSnapshot(snapshots)).toBeNull(); expect(referralNote()).toHaveValue(long);
    fireEvent.click(referralConfirm()); fireEvent.click(apply());
    expect(referralNote()).toHaveValue(long); expect(view.props.onApply).not.toHaveBeenCalled();
    expect(lastSnapshot(snapshots)).toBeNull();
    fireEvent.change(referralNote(), { target: { value: 'Shortened by the user.' } });
    expect(lastSnapshot(snapshots).fields.referralNote).toBe('Shortened by the user.');
    expect(lastSnapshot(snapshots).confirmed.referral).toBe(false);
  });

  it('restores collapsed state and reports a toggle without marking the background itself dirty', () => {
    const snapshots = snapshotSpy(); const first = mount({ onDraftSnapshotChange: snapshots });
    fireEvent.click(screen.getByText('Contact purpose and background'));
    fireEvent(screen.getByTestId('email-contact-context-panel'), new Event('toggle'));
    const saved = lastSnapshot(snapshots); expect(saved.expanded).toBe(false); expect(saved.pending).toBe(false);
    first.unmount(); const props = { ...first.props, initialDraft: saved, onDraftSnapshotChange: snapshots };
    render(<EmailContactContextPanel {...props} />);
    expect(screen.getByTestId('email-contact-context-panel')).not.toHaveAttribute('open');
    expect(props.onDraftChange).not.toHaveBeenCalled(); expect(props.onApply).not.toHaveBeenCalled();
  });
});

import { researchFixture } from '@/lib/research-context.test-utils';
import { emailPaperKey, emailPaperOptions } from '@/lib/email-paper-reading';

describe('research snapshot reading confirmation', () => {
  it('shows actual source/abstract but applying requires an explicit reading confirmation', () => {
    const research = researchFixture(); const opportunity = { id: 'research-target', research_context: research } as Opportunity;
    const { props } = mount({ opportunity, targetKey: 'wt1:a' });
    const option = emailPaperOptions(opportunity)[0];
    fireEvent.change(screen.getByRole('combobox', { name: 'Paper you looked at (optional)' }), { target: { value: emailPaperKey(option) } });
    const sourceLink = screen.getByRole('link', { name: research.snapshot!.works[0].title });
    expect(sourceLink).toHaveAttribute('href', research.snapshot!.works[0].source_url);
    expect(sourceLink).toHaveTextContent(research.snapshot!.works[0].title);
    expect(sourceLink).toHaveStyle({ display: 'block', overflowWrap: 'anywhere' });
    expect(sourceLink).not.toHaveAttribute('aria-label');
    expect(screen.getByText(research.snapshot!.works[0].abstract!)).toBeInTheDocument();
    const confirmation = screen.getByRole('checkbox', { name: 'I confirm this reading level for the selected paper.' });
    expect(confirmation).not.toBeChecked();
    fireEvent.change(screen.getByRole('combobox', { name: 'How much did you read?' }), { target: { value: 'full_text' } });
    fireEvent.click(apply()); expect(props.onApply).not.toHaveBeenCalled();
    fireEvent.click(confirmation); fireEvent.click(apply());
    expect(props.onApply).toHaveBeenCalledWith({ version: 1, purpose: 'first_contact', paper_reading: { ...option, level: 'full_text', confirmed: true } });
  });
  it('source version changes preserve other pending text and invalidate reading without upgrading a restored selection', () => {
    const research = researchFixture(); const opportunity = { id: 'research-target', research_context: research } as Opportunity;
    const selected = emailPaperOptions(opportunity)[0];
    const { props, rerender } = mount({ opportunity, targetKey: 'wt1:a' });
    fireEvent.change(availability(), { target: { value: 'I can participate on Tuesdays.' } });
    fireEvent.change(screen.getByRole('combobox', { name: 'Paper you looked at (optional)' }), { target: { value: emailPaperKey(selected) } });
    fireEvent.change(screen.getByRole('combobox', { name: 'How much did you read?' }), { target: { value: 'abstract' } });
    fireEvent.click(screen.getByRole('checkbox', { name: 'I confirm this reading level for the selected paper.' }));
    const newer = structuredClone(opportunity); newer.research_context!.snapshot!.snapshot_version = 'rs1:' + 'b'.repeat(64);
    rerender(<EmailContactContextPanel {...props} opportunity={newer} targetKey="wt1:b" />);
    expect(availability()).toHaveValue('I can participate on Tuesdays.');
    expect(screen.getByRole('checkbox', { name: 'I confirm this reading level for the selected paper.' })).not.toBeChecked();
    fireEvent.click(apply()); expect(props.onApply).not.toHaveBeenCalled();
    expect(screen.getByText('Previous paper is no longer available')).toBeInTheDocument();
  });
});
