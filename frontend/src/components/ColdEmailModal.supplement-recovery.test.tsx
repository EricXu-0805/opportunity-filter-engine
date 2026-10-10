import { emailValidationReceipt } from './ColdEmailModal.test-fixtures';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import { act, fireEvent, render, screen, waitFor, within } from '@testing-library/react';
import type { ComponentProps } from 'react';
import { advanceOwnerEpoch, captureOwnerToken, PRIVATE_STORAGE_LOCK, syncLocalIdentityOwner } from '@/lib/identity-owner';
import { createColdEmailDraftWriter, readColdEmailDraft } from '@/lib/cold-email-draft';
import { STORAGE_KEYS } from '@/lib/storage-keys';
import type { EmailContactContext, ProfileData } from '@/lib/types';
import { emailReceipt, emailTarget } from './ColdEmailModal.test-fixtures';

const api = vi.hoisted(() => ({ variants: vi.fn(), stream: vi.fn(), refine: vi.fn(), recipient: vi.fn(), assign: vi.fn(), confirm: vi.fn() }));
vi.mock('@/lib/api', () => ({
  validateEmailDraft: emailValidationReceipt,
  getEmailVariants: (...args: unknown[]) => emailReceipt(api.variants(...args), args[1] as string,
    (args[3] as { expectedTargetVersion: string }).expectedTargetVersion,
    (args[3] as { contactContext: EmailContactContext }).contactContext),
  generateColdEmailStream: (...args: unknown[]) => emailReceipt(api.stream(...args), args[1] as string,
    (args[2] as { expectedTargetVersion: string }).expectedTargetVersion,
    (args[2] as { contactContext: EmailContactContext }).contactContext),
  refineEmail: (...args: unknown[]) => emailReceipt(api.refine(...args), args[3] as string), generateColdEmail: vi.fn(), getVapidPublicKey: vi.fn(),
}));
vi.mock('@/lib/email-compose', () => ({ verifyComposeRecipient: api.recipient }));
vi.mock('@/lib/supabase', () => ({ onAuthChange: () => () => {}, confirmContactEvent: api.confirm, updateInteractionDetails: vi.fn() }));
vi.mock('@/lib/auth-modal-context', () => ({ useAuthModal: () => ({ openModal: vi.fn() }) }));
vi.mock('@/i18n/client', () => { const t = (key: string) => key; return { useT: () => ({ t, locale: 'en' }), useLocale: () => 'en' }; });
const supplement = vi.hoisted(() => ({ controller: null as unknown, options: null as unknown }));
vi.mock('./use-resume-supplement', () => ({ useResumeSupplement: (options: unknown) => { supplement.options=options; return supplement.controller; } }));
import ColdEmailModal from './ColdEmailModal';
import { createEmptyResumeMaster } from '@/lib/resume-master';
import type { useResumeSupplement, ResumeSupplementOptions } from './use-resume-supplement';

const master = createEmptyResumeMaster('recovery-master');
master.activities = [{id:'project-one',kind:'project',title:{id:'title',revision:1,status:'confirmed',value:'Sensor project',source:{kind:'manual'}},details:[]}];
const profile: ProfileData = { name: 'Alex', institution: 'UIUC', college: 'Grainger', major: 'CS', grade: 'Sophomore',
  is_international: false, research_interests: 'sensors', skills: [], coursework: [], resume_master: master, experience_entries: [] };
const target = emailTarget('recovery-target');
const draft = { id: 'v1', label: 'Template', subject: 'Original subject', body: 'Original complete draft', recipient_email: 'lab@example.edu', mailto_link: '' };
const edits = { subject: 'My manually edited subject', body: 'My complete handwritten paragraph.\nDo not replace it.', recipient: 'chosen@example.edu', request: 'Keep my project contribution and shorten the introduction.' };
type Props = ComponentProps<typeof ColdEmailModal>;
let ownerNumber = 0;

beforeEach(async () => {
  localStorage.clear(); advanceOwnerEpoch('draft-recovery-' + ++ownerNumber); await syncLocalIdentityOwner('draft-recovery-' + ownerNumber);
  const token=captureOwnerToken(); const view = { viewId:'fresh-view', baseProfile:profile, renderedProfile:profile, revision:1,token,identityGeneration:token.epoch,source:'hydration' as const };
  supplement.controller = { view, acceptedView:view, phase:'ready', error:null, ownerScopeKey:'scope',operationLocked:false,confirmedEntryId:null,acceptCurrent:vi.fn().mockResolvedValue(undefined),assign:vi.fn(),confirm:vi.fn().mockResolvedValue({durable:false,reason:'record-failed'}),retryRecorded:vi.fn(),baseline:vi.fn((activityId:string)=>({view,activityId,targetKey:(supplement.options as ResumeSupplementOptions).targetKey})) } satisfies ReturnType<typeof useResumeSupplement>;
  api.variants.mockReset().mockResolvedValue({ variants: [draft], recipient_status: 'revealed' });
  api.stream.mockReset().mockResolvedValue({ ...draft, method: 'template' }); api.refine.mockReset();
  api.recipient.mockReset().mockResolvedValue(undefined); api.confirm.mockReset().mockResolvedValue({ interaction: { type: 'contacted' } });
  vi.spyOn(window, 'open').mockImplementation(() => ({ closed: false, opener: null, location: { href: 'about:blank' }, close: vi.fn() }) as unknown as Window);
  Object.defineProperty(navigator, 'clipboard', { configurable: true, value: { writeText: vi.fn().mockResolvedValue(undefined) } });
});
function mount(overrides: Partial<Props> = {}) {
  const props: Props = { isOpen: true, onClose: vi.fn(), profile, opportunityId: target.id, opportunityTitle: 'Lab', target, ...overrides };
  return { ...render(<ColdEmailModal {...props} />), props };
}
const field = (name: 'subject' | 'body' | 'to' | 'requestLabel') => screen.getByLabelText('coldEmail.' + name);
const button = (name: string) => screen.getByRole('button', { name: 'coldEmail.' + name });
const change = (name: Parameters<typeof field>[0], value: string) => fireEvent.change(field(name), { target: { value } });
async function ready() {
  await screen.findByDisplayValue(draft.body);
  await waitFor(() => expect(button('generateAiDraft')).toBeEnabled());
  await act(async () => {});
  expect(api.stream).not.toHaveBeenCalled();
}
function edit() { change('subject', edits.subject); change('body', edits.body); change('to', edits.recipient); change('requestLabel', edits.request); }
function expectEdits() {
  expect(field('subject')).toHaveValue(edits.subject); expect(field('body')).toHaveValue(edits.body);
  expect(field('to')).toHaveValue(edits.recipient); expect(field('requestLabel')).toHaveValue(edits.request);
}
async function close(view: ReturnType<typeof mount>) {
  fireEvent.click(button('closeAria'));
  await waitFor(() => expect(view.props.onClose).toHaveBeenCalledOnce());
  view.unmount();
}
const task = () => screen.getByLabelText('What was the task?');
const method = () => screen.getByLabelText('What methods or tools did you use?');
const accuracy = () => screen.getByLabelText(/(?:I confirm the selected information|I reviewed the current activity and profile, and confirm the selected information) is accurate\./);
const controller = () => supplement.controller as ReturnType<typeof useResumeSupplement>;
function openSupplement() { const panel = screen.getByTestId('cold-email-supplement'); fireEvent.click(panel.querySelector('summary')!); fireEvent(panel, new Event('toggle')); }
function answer() {
  fireEvent.change(screen.getByRole('combobox', {name:'Project or experience in your master résumé'}), {target:{value:'project-one'}});
  fireEvent.change(task(),{target:{value:'Exact unsubmitted task 王'}}); fireEvent.change(method(),{target:{value:'Unselected private method'}});
  fireEvent.click(screen.getByLabelText('Include task')); fireEvent.click(accuracy());
}
async function savedAnswer(value = 'Exact unsubmitted task 王') {
  await waitFor(()=>{ const r=readColdEmailDraft(captureOwnerToken(),target.id);expect(r.status).toBe('present');if(r.status==='present')expect(r.draft.pendingSupplement?.answers.task).toBe(value);
    expect(screen.getByTestId('cold-email-draft-status')).toHaveTextContent(/Saved on this browser/); });
}
async function propose() {
  api.refine.mockResolvedValue({body:'Proposed revised body',method:'llm'});
  change('requestLabel','Keep the project description'); fireEvent.submit(field('requestLabel').closest('form')!);
  await screen.findByRole('region',{name:'Pending edit suggestion'});
}
// Real modal, supplement panel, owner authority, Web Locks and draft store.
// Only network/model and profile controller responses are faked.
describe('cold email unfinished supplement persistence',()=>{
 it('restores a fresh panel after close with both selected and unselected text, but no submission authority',async()=>{
  const view=mount();await ready();edit();openSupplement();answer();await close(view);api.stream.mockClear();mount();
  await waitFor(()=>expect(task()).toHaveValue('Exact unsubmitted task 王'));
  expectEdits();expect(method()).toHaveValue('Unselected private method');expect(screen.getByLabelText('Include task')).toBeChecked();
  expect(accuracy()).not.toBeChecked();expect(accuracy()).toBeEnabled();expect(accuracy()).toHaveAccessibleName('I reviewed the current activity and profile, and confirm the selected information is accurate.');
  expect(controller().confirm).not.toHaveBeenCalled();expect(api.stream).not.toHaveBeenCalled();expect(api.confirm).not.toHaveBeenCalled();
 });
 it('restores on the same mounted modal after closing and reopening',async()=>{
  const view=mount();await ready();openSupplement();answer();fireEvent.click(button('closeAria'));await waitFor(()=>expect(view.props.onClose).toHaveBeenCalledOnce());
  view.rerender(<ColdEmailModal {...view.props} isOpen={false}/>);view.rerender(<ColdEmailModal {...view.props} isOpen/>);
  await waitFor(()=>expect(task()).toHaveValue('Exact unsubmitted task 王'));expect(accuracy()).not.toBeChecked();expect(controller().confirm).not.toHaveBeenCalled();
 });
 it('does not show another opportunity or account pending answers',async()=>{
  const view=mount();await ready();openSupplement();answer();await close(view);
  const other=mount({target:emailTarget('other-opportunity'),opportunityId:'other-opportunity'});await screen.findByDisplayValue(draft.body);openSupplement();expect(task()).toHaveValue('');await close(other);
  advanceOwnerEpoch('different-supplement-owner');await syncLocalIdentityOwner('different-supplement-owner');mount();await screen.findByDisplayValue(draft.body);openSupplement();expect(task()).toHaveValue('');expect(controller().confirm).not.toHaveBeenCalled();
 });
 it('retains the mounted answers when a close flush fails, then durably saves the same answers on retry',async()=>{
  const view=mount();await ready();openSupplement();answer();await savedAnswer();
  const original=localStorage.setItem.bind(localStorage);const writes=vi.spyOn(localStorage,'setItem').mockImplementation((key,value)=>{if(key.includes(STORAGE_KEYS.COLD_EMAIL_DRAFT_PREFIX))throw new DOMException('fixture quota','QuotaExceededError');original(key,value);});
  fireEvent.change(task(),{target:{value:'New unsaved task'}});await waitFor(()=>expect(screen.getByTestId('cold-email-draft-status')).toHaveTextContent('Could not save'));
  fireEvent.click(button('closeAria'));await act(async()=>{});expect(task()).toHaveValue('New unsaved task');expect(method()).toHaveValue('Unselected private method');expect(view.props.onClose).not.toHaveBeenCalled();
  writes.mockRestore();fireEvent.click(screen.getByTestId('cold-email-draft-retry'));await savedAnswer('New unsaved task');await close(view);mount();await waitFor(()=>expect(task()).toHaveValue('New unsaved task'));
 });
 it('retains oversize input and the previous durable draft until the full new input is made savable',async()=>{
  const view=mount();await ready();openSupplement();answer();await savedAnswer();const huge='原'.repeat(66000);fireEvent.change(method(),{target:{value:huge}});
  expect(method()).toHaveValue(huge);expect(screen.getByTestId('cold-email-draft-retry')).toBeDisabled();fireEvent.click(button('closeAria'));await act(async()=>{});
  expect(method()).toHaveValue(huge);expect(view.props.onClose).not.toHaveBeenCalled();const record=readColdEmailDraft(captureOwnerToken(),target.id);if(record.status!=='present')throw new Error('saved draft missing');expect(record.draft.pendingSupplement?.answers.method).toBe('Unselected private method');
  fireEvent.change(method(),{target:{value:'Short enough, not truncated'}});fireEvent.click(screen.getByTestId('cold-email-draft-retry'));await savedAnswer();await close(view);mount();await waitFor(()=>expect(method()).toHaveValue('Short enough, not truncated'));
 });
 it('does not let accepting an AI edit overwrite supplement answers entered while its history save waits',async()=>{
  mount();await ready();openSupplement();answer();await savedAnswer();await propose();
  let release!:()=>void;const held=new Promise<void>(resolve=>{release=resolve;});const lock=navigator.locks.request(PRIVATE_STORAGE_LOCK,{mode:'exclusive'},()=>held);
  try { fireEvent.click(screen.getByRole('button',{name:'Accept suggestion'}));await act(async()=>{});
    fireEvent.change(task(),{target:{value:'New answer during history save'}});expect(task()).toHaveValue('New answer during history save');
  } finally { await act(async()=>{release();await lock;}); }
  await savedAnswer('New answer during history save');expect(field('body')).toHaveValue(draft.body);
  const record=readColdEmailDraft(captureOwnerToken(),target.id);if(record.status!=='present')throw new Error('saved draft missing');expect(record.draft.history).toHaveLength(0);expect(record.draft.body).toBe(draft.body);expect(controller().confirm).not.toHaveBeenCalled();
 });
 it('keeps pending answers separate from successful AI history and does not restore confirmation with a historical email',async()=>{
  mount();await ready();openSupplement();answer();await savedAnswer();await propose();fireEvent.click(screen.getByRole('button',{name:'Accept suggestion'}));await waitFor(()=>expect(field('body')).toHaveValue('Proposed revised body'));
  const record=readColdEmailDraft(captureOwnerToken(),target.id);if(record.status!=='present')throw new Error('saved draft missing');expect(record.draft.history).toHaveLength(1);expect(record.draft.history[0]).not.toHaveProperty('pendingSupplement');expect(record.draft.pendingSupplement?.answers.task).toBe('Exact unsubmitted task 王');
  fireEvent.change(task(),{target:{value:'Answer edited after old email version'}});
  const history=screen.getByTestId('cold-email-history');fireEvent.click(history.querySelector('summary')!);fireEvent(history,new Event('toggle'));
  fireEvent.click(within(history).getByRole('button',{name:'Compare and restore'}));fireEvent.click(screen.getByRole('button',{name:'Restore this version'}));
  await waitFor(()=>expect(field('body')).toHaveValue(draft.body));await savedAnswer('Answer edited after old email version');expect(accuracy()).not.toBeChecked();expect(controller().confirm).not.toHaveBeenCalled();
 });
 it('cannot clear an oversized supplement save failure by deleting a historical email version',async()=>{
  const view=mount();await ready();openSupplement();answer();await savedAnswer();await propose();fireEvent.click(screen.getByRole('button',{name:'Accept suggestion'}));await waitFor(()=>expect(field('body')).toHaveValue('Proposed revised body'));
  const huge='原'.repeat(66000);fireEvent.change(method(),{target:{value:huge}});expect(screen.getByTestId('cold-email-draft-status')).toHaveTextContent('Could not save');
  const history=screen.getByTestId('cold-email-history');fireEvent.click(history.querySelector('summary')!);fireEvent(history,new Event('toggle'));
  const confirmation=vi.spyOn(window,'confirm').mockReturnValue(true);fireEvent.click(within(history).getByRole('button',{name:'Delete this version'}));await act(async()=>{});
  expect(confirmation).not.toHaveBeenCalled();expect(method()).toHaveValue(huge);expect(screen.getByTestId('cold-email-draft-status')).toHaveTextContent('Could not save');
  fireEvent.click(button('closeAria'));await act(async()=>{});expect(view.props.onClose).not.toHaveBeenCalled();expect(method()).toHaveValue(huge);
  const record=readColdEmailDraft(captureOwnerToken(),target.id);if(record.status!=='present')throw new Error('saved draft missing');expect(record.draft.history).toHaveLength(1);expect(record.draft.pendingSupplement?.answers.method).toBe('Unselected private method');
 });
 it('keeps the email when recovered answers are discarded and prevents cancelled deletion from clearing either',async()=>{
  const view=mount();await ready();edit();openSupplement();answer();await close(view);mount();await waitFor(()=>expect(task()).toHaveValue('Exact unsubmitted task 王'));
  const prompt=vi.spyOn(window,'confirm').mockReturnValue(false);fireEvent.click(screen.getByTestId('cold-email-draft-clear'));expectEdits();expect(task()).toHaveValue('Exact unsubmitted task 王');
  prompt.mockReturnValue(true);fireEvent.click(screen.getByRole('button',{name:'Discard recovered answers and start again'}));await waitFor(()=>expect(task()).toHaveValue(''));expectEdits();expect(controller().confirm).not.toHaveBeenCalled();
 });
 it('does not revive a deleted draft or overwrite another editor with a late supplement change',async()=>{
  mount();await ready();openSupplement();answer();await savedAnswer();const owner=captureOwnerToken();const record=readColdEmailDraft(owner,target.id);if(record.status!=='present')throw new Error('saved draft missing');
  await act(async()=>{expect((await createColdEmailDraftWriter(owner,target.id,record.revision).delete()).status).toBe('deleted');});
  fireEvent.change(task(),{target:{value:'Late answer after other editor deleted'}});await waitFor(()=>expect(screen.getByTestId('cold-email-draft-status')).not.toHaveTextContent(/Saving|Saved on this browser/));expect(readColdEmailDraft(owner,target.id).status).toBe('missing');expect(task()).toHaveValue('Late answer after other editor deleted');
 });
});
