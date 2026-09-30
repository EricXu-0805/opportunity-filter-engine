import { useEffect, useState, type ComponentProps } from 'react';
import { cleanup, fireEvent, render, screen } from '@testing-library/react';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import type { Opportunity } from '@/lib/types';
import type { WritingTargetState } from '@/lib/use-writing-target';
import { DEFAULT_PROFILE } from '@/app/home/types';

const reader = vi.hoisted(() => ({ state: null as WritingTargetState | null, starts: 0, enabled: false, id: '' }));
vi.mock('@/lib/use-writing-target', () => ({ useWritingTarget: (enabled: boolean, id: string) => {
  reader.enabled = enabled; reader.id = id;
  useEffect(() => { if (enabled) reader.starts += 1; }, [enabled, id]);
  return reader.state!;
} }));
type Shared = { isOpen: boolean; targetReady?: boolean; targetChecking?: boolean; targetMembershipReady?: boolean;
  target?: Opportunity | null; opportunity?: Opportunity; targetKey?: string; opportunityTitle?: string;
  targetRefresh?: WritingTargetState; onOpenLegacy?: () => void; onOpenFull?: () => void };
let received: Shared;
function Editor(props: Shared) {
  useEffect(() => { received = props; });
  const [text, setText] = useState('');
  if (!props.isOpen) return null;
  return <div><textarea aria-label="Manual draft" value={text} onChange={event => setText(event.target.value)} />
    <button disabled={!props.targetReady}>Generate</button>
    {props.onOpenLegacy && <button onClick={props.onOpenLegacy}>Bullets</button>}
    {props.onOpenFull && <button onClick={props.onOpenFull}>Full</button>}
  </div>;
}
vi.mock('./ColdEmailModal', () => ({ default: Editor }));
vi.mock('./TailorModal', () => ({ default: Editor }));
vi.mock('./FullTargetResumeModal', () => ({ default: Editor }));
vi.mock('./ResumeRenovationModal', () => ({ default: Editor }));
import CheckedColdEmailModal from './CheckedColdEmailModal';
import CheckedTailorModal from './CheckedTailorModal';
import ResumeWorkspaceModal from './ResumeWorkspaceModal';
const target: Opportunity = { id: 'target', title: 'Full current target', organization: 'University', opportunity_type: 'research',
  paid: 'unknown', location: 'Campus', on_campus: true, description_clean: 'Complete target information', keywords: [],
  eligibility: { international_friendly: 'unknown', preferred_year: [], majors: [], skills_required: [], citizenship_required: null },
  application: { application_effort: 'unknown', requires_resume: 'unknown', contact_method: 'email' },
  metadata: { is_active: true, confidence_score: 1 } };
const props = { isOpen: true, onClose: vi.fn(), profile: DEFAULT_PROFILE, opportunityId: target.id, opportunityTitle: 'Seed title', target,
  ownerReady: true, ownerScopeKey: 'owner' };
beforeEach(() => { reader.starts = 0; reader.state = { status: 'ready', target, reason: null, refresh: vi.fn(), checkForAction: vi.fn() }; });
afterEach(cleanup);
describe('real writing entry wrappers', () => {
  it.each(['email', 'tailor'] as const)('%s uses the detail receipt and cannot override Results membership', kind => {
    const Component = kind === 'email' ? CheckedColdEmailModal : CheckedTailorModal;
    const view = render(<Component {...props} targetReady={false} />);
    expect(received.target).toBe(target); expect(received.targetRefresh).toBe(reader.state);
    expect(received.targetMembershipReady).toBe(false); expect(screen.getByText('Generate')).toBeDisabled();
    view.rerender(<Component {...props} targetReady />);
    expect(screen.getByText('Generate')).toBeEnabled(); expect(received.opportunityTitle).toBe(target.title);
  });
  it.each(['checking', 'missing', 'blocked', 'failed'] as const)('keeps manual email during %s and exposes the precise target status', status => {
    const view = render(<CheckedColdEmailModal {...props} />);
    fireEvent.change(screen.getByRole('textbox'), { target: { value: 'Exact manual text 王' } });
    reader.state = { ...reader.state!, status };
    view.rerender(<CheckedColdEmailModal {...props} />);
    expect(screen.getByRole('textbox')).toHaveValue('Exact manual text 王');
    expect(screen.getByText('Generate')).toBeDisabled(); expect(received.targetMembershipReady).toBe(true);
    expect(received.targetChecking).toBe(status === 'checking'); expect(received.targetRefresh?.status).toBe(status);
  });
  it('does not replace a Tailor buffer when the checked same-id target changes', () => {
    const view = render(<CheckedTailorModal {...props} />);
    fireEvent.change(screen.getByRole('textbox'), { target: { value: 'Unchanged manual bullet' } });
    const latest = { ...target, description_clean: 'Updated full description' };
    reader.state = { ...reader.state!, target: latest };
    view.rerender(<CheckedTailorModal {...props} />);
    expect(screen.getByRole('textbox')).toHaveValue('Unchanged manual bullet');
    expect(received.target).toBe(latest); expect(received.targetKey).toBe(JSON.stringify(latest));
  });
  it('uses one mounted reader across full/legacy switches, and checks again on reopen', () => {
    const p: ComponentProps<typeof ResumeWorkspaceModal> = { isOpen: true, onClose: vi.fn(), profile: DEFAULT_PROFILE, opportunity: target };
    const view = render(<ResumeWorkspaceModal {...p} />);
    expect(reader.starts).toBe(1); expect(received.opportunity).toBe(target);
    fireEvent.click(screen.getByText('Bullets'));
    expect(reader.starts).toBe(1); expect(received.target).toBe(target); expect(received.targetRefresh).toBe(reader.state);
    fireEvent.click(screen.getByText('Full')); expect(reader.starts).toBe(1);
    view.rerender(<ResumeWorkspaceModal {...p} isOpen={false} />);
    expect(screen.queryByRole('textbox')).toBeNull();
    view.rerender(<ResumeWorkspaceModal {...p} />); expect(reader.starts).toBe(2);
  });
  it('disables a closed reader and keeps parent checking independently', () => {
    const view = render(<CheckedColdEmailModal {...props} isOpen={false} />);
    expect(reader.enabled).toBe(false); expect(screen.queryByRole('textbox')).toBeNull();
    view.rerender(<CheckedColdEmailModal {...props} targetReady={false} targetChecking />);
    expect(received.targetChecking).toBe(true); expect(received.targetReady).toBe(false);
  });
});
