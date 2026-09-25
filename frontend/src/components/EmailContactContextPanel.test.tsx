import { fireEvent, render, screen, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { describe, expect, it, vi } from 'vitest';
import type { EmailContactContext } from '@/lib/types';
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
