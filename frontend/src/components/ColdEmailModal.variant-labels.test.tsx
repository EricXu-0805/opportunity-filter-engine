import { beforeEach, describe, expect, it, vi } from 'vitest';
import { act, render, screen, waitFor } from '@testing-library/react';
import { advanceOwnerEpoch, syncLocalIdentityOwner } from '@/lib/identity-owner';
import { emailReceipt, emailTarget, emailValidationReceipt } from './ColdEmailModal.test-fixtures';
import type { ProfileData } from '@/lib/types';

const api = vi.hoisted(() => ({ variants: vi.fn(), stream: vi.fn() }));
vi.mock('@/i18n/client', () => ({ useT: () => ({ t: (key: string) => key, locale: 'zh' }) }));
vi.mock('@/lib/api', () => ({
  validateEmailDraft: emailValidationReceipt,
  getEmailVariants: (...args: unknown[]) => emailReceipt(api.variants(...args), args[1] as string),
  generateColdEmailStream: (...args: unknown[]) => emailReceipt(api.stream(...args), args[1] as string),
  refineEmail: vi.fn(), generateColdEmail: vi.fn(), getVapidPublicKey: vi.fn(),
}));
vi.mock('@/lib/supabase', () => ({ onAuthChange: () => () => {}, confirmContactEvent: vi.fn(), updateInteractionDetails: vi.fn() }));
vi.mock('@/lib/auth-modal-context', () => ({ useAuthModal: () => ({ openModal: vi.fn() }) }));
import ColdEmailModal from './ColdEmailModal';

const profile: ProfileData = { name: 'Alex', institution: 'UIUC', college: 'Grainger', major: 'CS', grade: 'Sophomore',
  is_international: false, research_interests: 'sensors', skills: [], coursework: [] };
const draft = { subject: 'Sensor research', body: 'Dear Professor,\n\nBest,\nAlex', recipient_email: 'lab@example.edu',
  mailto_link: '', method: 'template' };
let owner = 0;
beforeEach(async () => {
  const uid = `variant-label-owner-${++owner}`; advanceOwnerEpoch(uid); await syncLocalIdentityOwner(uid);
  api.stream.mockReset().mockResolvedValue({ ...draft, id: 'balanced', label: 'Balanced' });
});

describe('ColdEmailModal — template variant tabs', () => {
  // The Chinese UI showed "Balanced / Skills Focus / Concise" next to
  // translated tone chips: the tabs rendered the server's English label.
  it('names the template variants in the reader language, by variant id', async () => {
    api.variants.mockReset().mockResolvedValue({ variants: [
      { ...draft, id: 'balanced', label: 'Balanced' },
      { ...draft, id: 'skills', label: 'Skills Focus', body: 'Skills body' },
      { ...draft, id: 'concise', label: 'Concise', body: 'Concise body' },
      { ...draft, id: 'unreviewed-variant', label: 'Server label', body: 'Other body' },
    ] });
    render(<ColdEmailModal isOpen onClose={vi.fn()} profile={profile} opportunityId="A" opportunityTitle="Lab"
      target={emailTarget('A')} />);
    await waitFor(() => expect(screen.getByRole('button', { name: 'coldEmail.variantLabels.balanced' })).toBeInTheDocument());
    await act(async () => {});
    expect(screen.getByRole('button', { name: 'coldEmail.variantLabels.skills' })).toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'coldEmail.variantLabels.concise' })).toBeInTheDocument();
    for (const english of ['Balanced', 'Skills Focus', 'Concise']) {
      expect(screen.queryByRole('button', { name: english })).toBeNull();
    }
    // A variant this build has no name for keeps the server's label.
    expect(screen.getByRole('button', { name: 'Server label' })).toBeInTheDocument();
  });
});
