import { fireEvent, render, screen } from '@testing-library/react';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import ContactInstructionsPanel from './ContactInstructionsPanel';

let locale: 'en' | 'zh' = 'en';
vi.mock('@/i18n/client', () => ({ useT: () => ({ locale }) }));
const subject = 'Undergraduate research inquiry';
const rule = { kind: 'subject', quote: `Use the subject “${subject}”.`, source_url: 'https://example.edu/join', checked_at: '2026-09-25T10:00:00Z', subject };
const target = { contact_instructions: { version: 1, status: 'known', email_policy: 'unknown', rules: [rule] } };

describe('ContactInstructionsPanel', () => {
  beforeEach(() => { locale = 'en'; });
  it('shows evidence and only changes a subject after the user chooses it', () => {
    const apply = vi.fn();
    render(<ContactInstructionsPanel target={target} subject="My draft" onUseSubject={apply} />);
    expect(screen.getByRole('link', { name: 'Source' })).toHaveAttribute('href', rule.source_url);
    expect(screen.getByText('Checked: 2026-09-25')).toBeVisible();
    expect(apply).not.toHaveBeenCalled();
    fireEvent.click(screen.getByRole('button', { name: 'Use this subject' }));
    expect(apply).toHaveBeenCalledWith(subject);
  });
  it('renders the quote as text and does not mistake required materials for attached files', () => {
    render(<ContactInstructionsPanel target={{ contact_instructions: { version: 1, status: 'known', email_policy: 'allowed', rules: [{ ...rule, kind: 'materials', subject: undefined, quote: '<script>evil()</script>', materials: ['CV', 'transcript'] }] } }} />);
    // An invalid optional subject is rejected, not partly trusted.
    expect(screen.getByText('Contact instructions could not be loaded. Refresh this opportunity and try again.')).toBeVisible();
  });
  it('shows unknown instructions in Chinese and drops a previous rule when target changes', () => {
    locale = 'zh';
    const { rerender } = render(<ContactInstructionsPanel target={target} />);
    expect(screen.getByText('要求的邮件主题', { selector: 'p.font-medium' })).toBeVisible();
    rerender(<ContactInstructionsPanel target={{}} />);
    expect(screen.queryByText(subject)).not.toBeInTheDocument();
    expect(screen.getByText('尚未确认适用的联系要求。联系前请核对官网。')).toBeVisible();
  });
  it('escapes source text and explains material preparation', () => {
    const { subject: _unused, ...evidence } = rule;
    render(<ContactInstructionsPanel target={{ contact_instructions: { version: 1, status: 'known', email_policy: 'allowed', rules: [{ ...evidence, kind: 'materials', quote: '<script>evil()</script>', materials: ['CV', 'transcript'] }] } }} />);
    expect(screen.getByText('<script>evil()</script>')).toBeVisible();
    expect(document.querySelector('script')).toBeNull();
    expect(screen.getByText('Preparing a draft does not attach files or submit an application.')).toBeVisible();
  });
});
