import { test, expect, request as apiRequest, type APIRequestContext, type BrowserContext, type Page, type Response } from '@playwright/test';
import { randomUUID } from 'node:crypto';
import { STORAGE_KEYS } from '../src/lib/storage-keys';
import type { ProfileData } from '../src/lib/types';

// M19 scenario acceptance for cloud save, end to end: the production Home form,
// AuthModal and /auth/callback, a real supabase-js client, and the loopback
// stub (e2e/supabase-stub.mjs) standing in for GoTrue + PostgREST. The magic
// link is read from the stub's outbox and opened like a student opens it from
// their inbox. The SQL behind the stub's RPCs is proven against real Postgres
// in supabase/tests; what this file proves is the browser side of each flow.
const STUB = new URL(`http://127.0.0.1:${Number(process.env.E2E_SUPABASE_PORT ?? 54321)}`);
const path = (url: string) => new URL(url).pathname;
const isCas = (url: string) => path(url) === '/rest/v1/rpc/commit_profile_patch_cas';

interface Row { id: string; revision: number; profile_data: ProfileData }
interface StoredSession { access_token: string; user: { id: string; email: string | null; is_anonymous: boolean } }

const mailbox = (tag: string) => `cloud-save-${tag}-${randomUUID().slice(0, 8)}@example.test`;

async function stubGet<T>(http: APIRequestContext, route: string): Promise<T> {
  const response = await http.get(new URL(route, STUB).href);
  expect(response.status(), route).toBe(200);
  return response.json() as Promise<T>;
}
const profileRows = (http: APIRequestContext, uid: string) =>
  stubGet<Row[]>(http, `/rest/v1/profiles?select=id,revision,profile_data&id=eq.${uid}`);

/** The newest link the stub "mailed" to this address. */
async function latestLink(http: APIRequestContext, email: string, type: 'email_change' | 'magiclink') {
  let link = '';
  await expect.poll(async () => {
    const mail = await stubGet<Array<{ type: string; link: string }>>(http, `/__e2e/outbox?email=${encodeURIComponent(email)}`);
    link = mail.filter((item) => item.type === type).at(-1)?.link ?? '';
    return link;
  }, { message: `a ${type} link for ${email}` }).not.toBe('');
  return link;
}

async function storedSession(page: Page): Promise<StoredSession> {
  const raw = await page.evaluate(() => localStorage.getItem('ofe_auth'));
  expect(raw, 'a Supabase session in this browser').not.toBeNull();
  return JSON.parse(raw!) as StoredSession;
}

async function englishOnly(page: Page) {
  await page.addInitScript((key) => { localStorage.setItem(key, 'en'); }, STORAGE_KEYS.LOCALE);
}

const ACCOUNT_PROFILE: ProfileData = {
  name: 'Account owner 王', institution: 'UIUC', home_school: 'uiuc', college: 'Grainger College of Engineering',
  major: 'Electrical Engineering', grade: 'Junior', is_international: false,
  research_interests: 'Account interest in integrated photonics 王', skills: [], coursework: [],
  seeking_types: ['research'], search_weight: 50,
};
interface Account { uid: string; session: StoredSession }
const bearer = (account: Account) => ({ Authorization: `Bearer ${account.session.access_token}` });

/** A confirmed email account that already saved a profile elsewhere. */
async function seedAccount(http: APIRequestContext, email: string): Promise<Account> {
  expect(STUB.hostname).toBe('127.0.0.1');
  const signup = await http.post(new URL('/auth/v1/signup', STUB).href, { data: { email } });
  expect(signup.status()).toBe(200);
  const session = await signup.json() as StoredSession;
  expect(session.user).toMatchObject({ email, is_anonymous: false });
  const account = { uid: session.user.id, session };
  const saved = await http.post(new URL('/rest/v1/rpc/commit_profile_patch_cas', STUB).href, {
    headers: bearer(account), data: { p_expected_device_id: account.uid, p_expected_revision: 0, p_patch: ACCOUNT_PROFILE },
  });
  expect(await saved.json()).toMatchObject({ status: 'applied', revision: 1 });
  return account;
}

/** This browser is already signed in to the account (session only; the
 *  profile always arrives through a real read). */
async function signedIn(page: Page, account: Account) {
  await page.addInitScript((session) => {
    if (!localStorage.getItem('cloud-save-seeded')) {
      localStorage.setItem('ofe_auth', JSON.stringify(session));
      localStorage.setItem('cloud-save-seeded', '1');
    }
  }, account.session);
}

/** Every profile CAS the page sends, with the receipt the server gave it. */
function recordCas(page: Page) {
  const receipts: Array<{ uid: string; patch: Partial<ProfileData>; status: string; revision: number }> = [];
  page.on('response', async (response: Response) => {
    if (!isCas(response.url()) || response.request().method() !== 'POST') return;
    const sent = response.request().postDataJSON();
    const body = await response.json().catch(() => null);
    receipts.push({ uid: sent.p_expected_device_id, patch: sent.p_patch, status: body?.status ?? `http-${response.status()}`, revision: body?.revision ?? -1 });
  });
  return receipts;
}

async function waitForForm(page: Page) {
  await expect(page.locator('#college')).toBeEnabled({ timeout: 30_000 });
  await expect(page.getByTestId('hydration-note')).toHaveCount(0, { timeout: 30_000 });
}

async function fillForm(page: Page, profile: Pick<ProfileData, 'name' | 'college' | 'major' | 'grade' | 'research_interests'>) {
  await page.locator('#student_name').fill(profile.name ?? '');
  await page.locator('#college').selectOption(profile.college);
  await page.locator('#major').selectOption(profile.major);
  await page.locator('#grade').selectOption(profile.grade);
  await page.locator('#research_interests').fill(profile.research_interests);
}

async function expectForm(page: Page, profile: Pick<ProfileData, 'name' | 'college' | 'major' | 'grade' | 'research_interests'>) {
  await expect(page.locator('#student_name')).toHaveValue(profile.name ?? '');
  await expect(page.locator('#college')).toHaveValue(profile.college);
  await expect(page.locator('#major')).toHaveValue(profile.major);
  await expect(page.locator('#grade')).toHaveValue(profile.grade);
  await expect(page.locator('#research_interests')).toHaveValue(profile.research_interests);
}

/** Records every text the save-status line shows, and whether the test had
 *  released the held write at that moment. */
async function watchStatus(page: Page) {
  await page.evaluate(() => {
    const state = window as unknown as { cloudSaveStatuses: Array<{ text: string; released: boolean }>; cloudSaveReleased: boolean };
    state.cloudSaveStatuses = [];
    state.cloudSaveReleased = false;
    const node = document.getElementById('profile-save-status')!;
    new MutationObserver(() => {
      state.cloudSaveStatuses.push({ text: node.textContent ?? '', released: state.cloudSaveReleased });
    }).observe(node, { childList: true, subtree: true, characterData: true });
  });
}

/** "Profile saved" is shown only once the server has confirmed the write. */
async function expectStatusOnlyAfterRelease(page: Page) {
  const seen = await page.evaluate(() => (window as unknown as { cloudSaveStatuses: Array<{ text: string; released: boolean }> }).cloudSaveStatuses);
  expect(seen.some((entry) => entry.text.includes('Profile saved'))).toBe(true);
  expect(seen.filter((entry) => entry.text.includes('Profile saved') && !entry.released)).toEqual([]);
}

const accountMenu = (page: Page) => page.getByTestId('account-menu').filter({ visible: true });

/** Header "Sign in" -> email -> "Send magic link". Also returns the auth request
 *  the modal made: PUT /auth/v1/user is the in-place anonymous conversion. */
async function requestLink(page: Page, email: string) {
  await accountMenu(page).click();
  const modal = page.getByRole('dialog');
  await modal.getByLabel('Email', { exact: true }).fill(email);
  const sent = page.waitForRequest((request) => ['/auth/v1/user', '/auth/v1/otp'].includes(path(request.url()))
    && ['PUT', 'POST'].includes(request.method()));
  await modal.getByRole('button', { name: 'Send magic link', exact: true }).click();
  return { modal, request: await sent };
}

/** Opens the mailed link in this browser and waits for /auth/callback to land
 *  back on Home signed in. */
async function openLinkAndLand(page: Page, link: string, email: string) {
  // Checked on the navigation response, not the live address: once supabase-js
  // has exchanged a magic link's code it strips ?code= with replaceState, and
  // whether that happens before a URL assertion runs is a race.
  const landing = await page.goto(link);
  expect(landing?.request().redirectedFrom()?.url()).toContain('/auth/v1/verify');
  expect(landing?.url()).toMatch(/\/auth\/callback\?code=/);
  await expect(page.getByRole('heading', { name: "You're saved.", exact: true })).toBeVisible({ timeout: 15_000 });
  await expect(page.getByText(`Signed in as ${email}`, { exact: true })).toBeVisible();
  const callback = page.locator('main');
  const text = await callback.innerText();
  await page.waitForURL((url) => url.pathname === '/', { timeout: 15_000 });
  return text;
}

type GuestDraft = Pick<ProfileData, 'name' | 'college' | 'major' | 'grade' | 'research_interests'>;

/** A guest saves a profile on Home and signs in, in the same tab, to the
 *  account that already has its own profile at `email`. */
async function guestSignsInToAccount(page: Page, http: APIRequestContext, email: string, guest: GuestDraft) {
  await page.goto('/');
  await waitForForm(page);
  await fillForm(page, guest);
  await expect(page.locator('#profile-save-status')).toHaveText('Profile saved', { timeout: 15_000 });
  const { modal } = await requestLink(page, email);
  const existing = modal.getByTestId('auth-modal-signin-existing');
  await expect(existing).toBeVisible();
  await existing.click();
  await expect(modal.getByText('Check your inbox', { exact: true })).toBeVisible();
  const redeemed = page.waitForResponse((response) => path(response.url()) === '/rest/v1/rpc/redeem_merge_grant');
  await openLinkAndLand(page, await latestLink(http, email, 'magiclink'), email);
  expect(await (await redeemed).json()).toMatchObject({
    merged: true, summary: { profile: 'kept_target_saved_other_as_version' },
  });
  await waitForForm(page);
}

/** A guest saves a profile on Home, asks for a sign-in link to an account that
 *  already exists, and opens it in a NEW tab of the same browser while Home
 *  stays open in the first one. The new tab's merge redemption is held until
 *  `finish()`, so the first tab can be looked at while this browser is still
 *  being handed over to the account. */
async function signInFromNewTab(page: Page, context: BrowserContext, http: APIRequestContext, email: string, guest: GuestDraft) {
  await englishOnly(page);
  const receipts = recordCas(page);
  await page.goto('/');
  await waitForForm(page);
  await fillForm(page, guest);
  await expect(page.locator('#profile-save-status')).toHaveText('Profile saved', { timeout: 15_000 });
  const guestUid = (await storedSession(page)).user.id;
  const { modal } = await requestLink(page, email);
  const existing = modal.getByTestId('auth-modal-signin-existing');
  await expect(existing).toBeVisible();
  await existing.click();
  await expect(modal.getByText('Check your inbox', { exact: true })).toBeVisible();
  await modal.getByRole('button', { name: 'Done', exact: true }).click();
  const writesBeforeLink = receipts.length;

  const mailTab = await context.newPage();
  await englishOnly(mailTab);
  const mailReceipts = recordCas(mailTab);
  let release!: () => void;
  const held = new Promise<void>((resolve) => { release = resolve; });
  await mailTab.route('**/rest/v1/rpc/redeem_merge_grant', async (route) => { await held; await route.continue(); });
  const redeemSent = mailTab.waitForRequest((request) => path(request.url()) === '/rest/v1/rpc/redeem_merge_grant');
  const landing = await mailTab.goto(await latestLink(http, email, 'magiclink'));
  expect(landing?.url()).toMatch(/\/auth\/callback\?code=/);
  await redeemSent;
  // The new tab has exchanged the code, so the first tab hears the sign-in.
  await expect(accountMenu(page)).toHaveAttribute('aria-label', `Your account, signed in as ${email}`, { timeout: 15_000 });

  const finish = async () => {
    const redeemed = mailTab.waitForResponse((response) => path(response.url()) === '/rest/v1/rpc/redeem_merge_grant');
    release();
    expect(await (await redeemed).json()).toMatchObject({ merged: true, summary: { profile: 'kept_target_saved_other_as_version' } });
    await expect(mailTab.getByRole('heading', { name: "You're saved.", exact: true })).toBeVisible({ timeout: 15_000 });
    await mailTab.waitForURL((url) => url.pathname === '/', { timeout: 15_000 });
    await waitForForm(mailTab);
    await expectForm(mailTab, ACCOUNT_PROFILE);
  };
  return { guestUid, receipts, writesBeforeLink, mailReceipts, release: () => release(), finish };
}

const SIGNED_IN_ELSEWHERE = "You signed in from another tab, so this page switched to that account. "
  + "Once that tab has finished signing you in, load your account's profile here. Anything you type is kept.";

test.describe('M19 cloud save scenarios', () => {
  test('a guest who signs in keeps the profile in place and finds it on a second device', async ({ page, browser }, info) => {
    const http = await apiRequest.newContext();
    let second: BrowserContext | null = null;
    const email = mailbox('convert');
    const guest = {
      name: 'Cloud save guest 王', college: 'Grainger College of Engineering', major: 'Computer Science',
      grade: 'Sophomore', research_interests: 'Guest-typed interest in soft robotics 王',
    };
    try {
      await englishOnly(page);
      const receipts = recordCas(page);
      await page.goto('/');
      await waitForForm(page);
      await fillForm(page, guest);
      await expect(page.locator('#profile-save-status')).toHaveText('Profile saved', { timeout: 15_000 });
      const anon = await storedSession(page);
      expect(anon.user.is_anonymous).toBe(true);
      const [created] = await profileRows(http, anon.user.id);
      expect(created.profile_data).toMatchObject(guest);
      expect(receipts.every((receipt) => receipt.uid === anon.user.id)).toBe(true);
      expect(receipts.filter((receipt) => receipt.status === 'applied').at(-1)?.revision).toBe(created.revision);

      const { modal, request } = await requestLink(page, email);
      expect(request.method(), 'an anonymous session is converted in place, not replaced').toBe('PUT');
      await expect(modal.getByText('Check your inbox', { exact: true })).toBeVisible();
      await modal.getByRole('button', { name: 'Done', exact: true }).click();
      const writesBeforeLink = receipts.length;

      const landed = await openLinkAndLand(page, await latestLink(http, email, 'email_change'), email);
      expect(landed).toContain('We kept your profile');
      const permanent = await storedSession(page);
      expect(permanent.user).toMatchObject({ id: anon.user.id, email, is_anonymous: false });
      await waitForForm(page);
      await expectForm(page, guest);
      await expect(accountMenu(page)).toHaveAttribute('aria-label', `Your account, signed in as ${email}`);
      expect(receipts.slice(writesBeforeLink), 'signing in must not rewrite the profile').toEqual([]);
      expect(await profileRows(http, anon.user.id)).toEqual([created]);

      // A second device: a fresh guest browser signs in to the same email and
      // gets the same profile. Its empty guest session is merged, not adopted.
      second = await browser.newContext();
      const phone = await second.newPage();
      await englishOnly(phone);
      const phoneReceipts = recordCas(phone);
      await phone.goto('/');
      await waitForForm(phone);
      await expect(phone.locator('#research_interests')).toHaveValue('');
      const phoneGuest = (await storedSession(phone)).user.id;
      expect(phoneGuest).not.toBe(anon.user.id);
      const { modal: phoneModal } = await requestLink(phone, email);
      // The address belongs to an account now, so linking is refused and the
      // modal offers the existing-account link instead.
      const existing = phoneModal.getByTestId('auth-modal-signin-existing');
      await expect(existing).toBeVisible();
      await existing.click();
      await expect(phoneModal.getByText('Check your inbox', { exact: true })).toBeVisible();
      await openLinkAndLand(phone, await latestLink(http, email, 'magiclink'), email);
      expect((await storedSession(phone)).user).toMatchObject({ id: anon.user.id, email, is_anonymous: false });
      await waitForForm(phone);
      await expectForm(phone, guest);
      expect(phoneReceipts, 'the second device only reads the profile').toEqual([]);
      expect(await profileRows(http, anon.user.id)).toEqual([created]);
      await phone.screenshot({ path: info.outputPath('second-device-profile.png') });
    } finally {
      await second?.close();
      await http.dispose();
    }
  });

  test('a guest signing in to an existing account brings its favorite over and keeps the account profile', async ({ page }, info) => {
    const http = await apiRequest.newContext();
    const email = mailbox('merge');
    const accountFavorite = 'uiuc-grainger-surf', guestFavorite = 'uiuc-siebel-ugresearch';
    const guest = {
      name: 'Guest on a shared laptop 王', college: 'Grainger College of Engineering', major: 'Computer Science',
      grade: 'Freshman', research_interests: 'Guest draft about swarm robotics 王',
    };
    try {
      const account = await seedAccount(http, email);
      const favorite = await http.post(new URL('/rest/v1/favorites', STUB).href, {
        headers: bearer(account), data: { device_id: account.uid, opportunity_id: accountFavorite },
      });
      expect(favorite.status()).toBe(201);
      await englishOnly(page);
      const receipts = recordCas(page);
      await page.goto('/');
      await waitForForm(page);
      await fillForm(page, guest);
      await expect(page.locator('#profile-save-status')).toHaveText('Profile saved', { timeout: 15_000 });
      const guestUid = (await storedSession(page)).user.id;
      const [guestRow] = await profileRows(http, guestUid);
      expect(guestRow.profile_data).toMatchObject(guest);
      await page.goto(`/opportunities/${guestFavorite}`);
      await page.getByRole('button', { name: 'Add to favorites', exact: true }).click();
      const starred = page.getByRole('button', { name: 'Remove from favorites', exact: true });
      await expect(starred).toBeEnabled();
      await expect(starred).toHaveAttribute('aria-busy', 'false');
      expect(await stubGet(http, `/rest/v1/favorites?device_id=eq.${guestUid}`)).toMatchObject([{ opportunity_id: guestFavorite }]);

      const { modal, request } = await requestLink(page, email);
      expect(request.method()).toBe('PUT');
      // The address already has an account: linking is refused, and the only
      // way in is a sign-in link that carries this guest's data with it.
      const existing = modal.getByTestId('auth-modal-signin-existing');
      await expect(existing).toBeVisible();
      const minted = page.waitForResponse((response) => path(response.url()) === '/rest/v1/rpc/mint_merge_grant');
      await existing.click();
      expect((await minted).status(), 'the merge grant is minted before the link is sent').toBe(200);
      await expect(modal.getByText('Check your inbox', { exact: true })).toBeVisible();
      const writesBeforeLink = receipts.length;

      const redeemed = page.waitForResponse((response) => path(response.url()) === '/rest/v1/rpc/redeem_merge_grant');
      const landed = await openLinkAndLand(page, await latestLink(http, email, 'magiclink'), email);
      expect(await (await redeemed).json()).toMatchObject({
        merged: true, summary: { favorites: 1, profile: 'kept_target_saved_other_as_version' },
      });
      expect(landed).toContain('We kept 2 favorites and your profile');
      expect(landed).toContain('We also brought over from your other device: 1 favorites');
      expect((await storedSession(page)).user).toMatchObject({ id: account.uid, email, is_anonymous: false });
      await waitForForm(page);
      // The account's own profile is the one kept; the guest's copy is not
      // written over it, and is archived rather than dropped.
      await expectForm(page, ACCOUNT_PROFILE);
      expect(receipts.slice(writesBeforeLink), 'signing in must not write the guest profile into the account').toEqual([]);
      expect(await profileRows(http, account.uid)).toMatchObject([{ revision: 1, profile_data: ACCOUNT_PROFILE }]);
      expect(await stubGet(http, `/rest/v1/profile_versions?device_id=eq.${account.uid}`))
        .toMatchObject([{ profile_revision: null, profile_data: guest }]);
      expect(await stubGet(http, `/rest/v1/merged_devices?source_device_id=eq.${guestUid}`))
        .toMatchObject([{ target_device_id: account.uid }]);

      await page.goto('/favorites');
      for (const id of [accountFavorite, guestFavorite]) {
        await expect(page.locator(`a[href="/opportunities/${id}"]`).first()).toBeVisible({ timeout: 15_000 });
      }
      await page.screenshot({ path: info.outputPath('merged-favorites.png') });
    } finally {
      await http.dispose();
    }
  });

  test('a guest who signs in to an account with its own profile can restore the guest profile from Home', async ({ page }, info) => {
    const http = await apiRequest.newContext();
    const email = mailbox('restore');
    const guest = {
      name: 'Guest whose profile was set aside 王', college: 'Grainger College of Engineering', major: 'Computer Science',
      grade: 'Freshman', research_interests: 'Guest draft about tactile sensing 王',
    };
    // Fields the account has and the guest profile never set: a restore
    // leaves none of them behind.
    const accountOnly = {
      linkedin_url: 'https://www.linkedin.com/in/account-owner', resume_text: 'Account owner résumé: two years in a photonics lab 王',
    };
    const cleared = { linkedin_url: '', resume_text: '', seeking_types: ['research', 'summer_program'] };
    try {
      const account = await seedAccount(http, email);
      const patched = await http.post(new URL('/rest/v1/rpc/commit_profile_patch_cas', STUB).href, {
        headers: bearer(account), data: { p_expected_device_id: account.uid, p_expected_revision: 1, p_patch: accountOnly },
      });
      expect(await patched.json()).toMatchObject({ status: 'applied', revision: 2 });
      await englishOnly(page);
      const receipts = recordCas(page);
      const expected: number[] = [];
      page.on('request', (request) => {
        if (isCas(request.url()) && request.method() === 'POST') expected.push(request.postDataJSON().p_expected_revision);
      });
      const status = page.locator('#profile-save-status');
      await page.goto('/');
      await waitForForm(page);
      await fillForm(page, guest);
      await expect(status).toHaveText('Profile saved', { timeout: 15_000 });
      const { modal } = await requestLink(page, email);
      const existing = modal.getByTestId('auth-modal-signin-existing');
      await expect(existing).toBeVisible();
      await existing.click();
      await expect(modal.getByText('Check your inbox', { exact: true })).toBeVisible();
      const writesBeforeLink = receipts.length;
      const sendsBeforeLink = expected.length;

      const redeemed = page.waitForResponse((response) => path(response.url()) === '/rest/v1/rpc/redeem_merge_grant');
      await openLinkAndLand(page, await latestLink(http, email, 'magiclink'), email);
      expect(await (await redeemed).json()).toMatchObject({
        merged: true, summary: { profile: 'kept_target_saved_other_as_version' },
      });
      await waitForForm(page);
      await expectForm(page, ACCOUNT_PROFILE);

      // Home says where the guest profile went and offers it back; saying so
      // writes nothing.
      const notice = page.getByTestId('merged-guest-notice');
      await expect(notice).toContainText('Your guest profile is saved.', { timeout: 15_000 });
      await expect(notice).toContainText('saved the profile you made as a guest separately in this account');
      await expect(notice).toContainText('replaces the whole profile below with it, including the résumé, links');
      await expect(notice).toContainText('"Keep my account profile" is final');
      await expect(notice).not.toContainText('version history');
      const restore = page.getByTestId('restore-guest-profile');
      await expect(restore).toHaveText('Restore my guest profile');
      await expect(page.getByTestId('keep-account-profile')).toHaveText('Keep my account profile');
      expect(receipts.slice(writesBeforeLink)).toEqual([]);
      await notice.scrollIntoViewIfNeeded();
      await page.screenshot({ path: info.outputPath('restore-guest-profile-offer.png') });

      await restore.click();
      await expect(notice).toContainText('Your guest profile is restored.', { timeout: 15_000 });
      await expectForm(page, guest);
      await expect(status).not.toContainText("couldn't sync");
      // One revision-checked save of the whole profile, against the account
      // revision that was on screen: the account's profile was revision 2,
      // the guest's is 3.
      expect(expected.slice(sendsBeforeLink)).toEqual([2]);
      expect(receipts.slice(writesBeforeLink)).toMatchObject([{
        uid: account.uid, status: 'applied', revision: 3,
        patch: { name: guest.name, major: guest.major, grade: guest.grade, research_interests: guest.research_interests, ...cleared },
      }]);
      expect(await profileRows(http, account.uid)).toMatchObject([{ revision: 3, profile_data: { ...guest, ...cleared } }]);
      expect(await stubGet(http, `/rest/v1/profile_versions?device_id=eq.${account.uid}`))
        .toMatchObject([{ profile_revision: null, profile_data: guest }]);
      await page.screenshot({ path: info.outputPath('restore-guest-profile-done.png') });

      // Restored once; a reload shows it and does not offer it again.
      await page.reload();
      await waitForForm(page);
      await expectForm(page, guest);
      await expect(page.getByTestId('merged-guest-notice')).toHaveCount(0);
      expect(receipts.slice(writesBeforeLink)).toHaveLength(1);
    } finally {
      await http.dispose();
    }
  });

  test('a restore whose save gets no answer and did not reach the server changes nothing, and nothing of it is sent later', async ({ page, context }, info) => {
    const http = await apiRequest.newContext();
    const email = mailbox('restore-lost');
    const guest: GuestDraft = {
      name: 'Guest whose restore did not save 王', college: 'Grainger College of Engineering', major: 'Computer Science',
      grade: 'Freshman', research_interests: 'Guest draft about haptics that never reached the server 王',
    };
    try {
      const account = await seedAccount(http, email);
      await englishOnly(page);
      await guestSignsInToAccount(page, http, email, guest);
      const notice = page.getByTestId('merged-guest-notice');
      const restore = page.getByTestId('restore-guest-profile');
      const status = page.locator('#profile-save-status');
      await expect(restore).toBeEnabled({ timeout: 15_000 });
      // Every profile save this page tries, whether or not it gets through.
      const attempts: Array<Partial<ProfileData>> = [];
      page.on('request', (request) => {
        if (isCas(request.url()) && request.method() === 'POST') attempts.push(request.postDataJSON().p_patch);
      });

      // Offline, Restore is not sent at all, and the notice says why.
      await context.setOffline(true);
      await expect(restore).toBeDisabled();
      await expect(notice).toContainText('Restoring needs an internet connection.');
      await context.setOffline(false);
      await expect(restore).toBeEnabled({ timeout: 15_000 });

      // The restore's save never reaches the server. The notice reads the
      // stored profile back, finds the account's, and says nothing was
      // restored; the form never showed the guest profile.
      await page.route('**/rest/v1/rpc/commit_profile_patch_cas', (route) => route.abort('internetdisconnected'));
      await restore.click();
      await expect(notice).toContainText('Your guest profile was not restored, and the profile below is unchanged.', { timeout: 15_000 });
      await expectForm(page, ACCOUNT_PROFILE);
      await expect(status).not.toContainText("couldn't sync");
      await expect(restore).toBeEnabled();
      await expect(page.getByTestId('keep-account-profile')).toBeEnabled();
      expect(attempts).toMatchObject([{ name: guest.name, major: guest.major }]);
      await notice.scrollIntoViewIfNeeded();
      await page.screenshot({ path: info.outputPath('restore-not-restored.png') });

      // Nothing of it is pending: reconnecting sends nothing.
      await page.unroute('**/rest/v1/rpc/commit_profile_patch_cas');
      await context.setOffline(true);
      await page.waitForTimeout(300);
      const checked = page.waitForResponse((response) => path(response.url()) === '/rest/v1/profiles'
        && response.request().method() === 'GET');
      await context.setOffline(false);
      await checked;
      await page.waitForTimeout(3_000);
      expect(attempts, 'nothing is sent on reconnecting').toHaveLength(1);
      await expectForm(page, ACCOUNT_PROFILE);

      // Keeping the account profile only removes the offer, for good: a
      // reload shows the account profile, does not offer the guest profile
      // again, and sends nothing.
      await page.getByTestId('keep-account-profile').click();
      await expect(notice).toHaveCount(0);
      await page.reload();
      await waitForForm(page);
      await expectForm(page, ACCOUNT_PROFILE);
      await page.waitForTimeout(1_000);
      await expect(notice).toHaveCount(0);
      expect(attempts).toHaveLength(1);
      expect(await profileRows(http, account.uid)).toMatchObject([{ revision: 1, profile_data: ACCOUNT_PROFILE }]);
    } finally {
      await http.dispose();
    }
  });

  test('a restore the server saved but whose answer was lost is read back and shown as restored', async ({ page }) => {
    const http = await apiRequest.newContext();
    const email = mailbox('restore-answer-lost');
    const guest: GuestDraft = {
      name: 'Guest restored without an answer', college: 'Grainger College of Engineering', major: 'Computer Science',
      grade: 'Sophomore', research_interests: 'Guest draft about acoustic sensing',
    };
    try {
      const account = await seedAccount(http, email);
      await englishOnly(page);
      await guestSignsInToAccount(page, http, email, guest);
      const notice = page.getByTestId('merged-guest-notice');
      await expect(page.getByTestId('restore-guest-profile')).toBeEnabled({ timeout: 15_000 });
      // The save reaches the server, and its answer never reaches the page.
      await page.route('**/rest/v1/rpc/commit_profile_patch_cas', async (route) => {
        await route.fetch();
        await route.abort('internetdisconnected');
      });
      await page.getByTestId('restore-guest-profile').click();
      await expect(notice).toContainText('Your guest profile is restored.', { timeout: 15_000 });
      await expectForm(page, guest);
      await expect(page.getByTestId('restore-guest-profile')).toHaveCount(0);
      expect(await profileRows(http, account.uid)).toMatchObject([{ revision: 2, profile_data: guest }]);
      await page.unroute('**/rest/v1/rpc/commit_profile_patch_cas');

      await page.reload();
      await waitForForm(page);
      await expectForm(page, guest);
      await page.waitForTimeout(1_000);
      await expect(notice).toHaveCount(0);
      expect(await profileRows(http, account.uid)).toMatchObject([{ revision: 2, profile_data: guest }]);
    } finally {
      await http.dispose();
    }
  });

  test('an edit typed while a restore with no answer is read back waits, and then the notice, the form and the server agree', async ({ page }, info) => {
    // The review's probe E: sent at once, the edit was rebased onto the
    // restored row and saved, so the read-back found neither profile and
    // said "not restored" while the server held the guest's.
    const http = await apiRequest.newContext();
    const email = mailbox('restore-hold');
    // A junior, like the account: the grade is a field both profiles share.
    const guest: GuestDraft = {
      name: 'Guest whose restore was read back slowly', college: 'Grainger College of Engineering', major: 'Computer Science',
      grade: 'Junior', research_interests: 'Guest draft about microfluidics, read back slowly',
    };
    try {
      const account = await seedAccount(http, email);
      await englishOnly(page);
      await guestSignsInToAccount(page, http, email, guest);
      const notice = page.getByTestId('merged-guest-notice');
      const restore = page.getByTestId('restore-guest-profile');
      await expect(restore).toBeEnabled({ timeout: 15_000 });
      const attempts: Array<{ revision: number; patch: Partial<ProfileData> }> = [];
      page.on('request', (request) => {
        if (isCas(request.url()) && request.method() === 'POST') {
          attempts.push({ revision: request.postDataJSON().p_expected_revision, patch: request.postDataJSON().p_patch });
        }
      });
      // The restore reaches the server and its answer is lost; from then on
      // reading the profile is held until the test lets it through.
      let releaseReads!: () => void;
      const reads = new Promise<void>((resolve) => { releaseReads = resolve; });
      let holdReads = false;
      let first = true;
      await page.route('**/rest/v1/rpc/commit_profile_patch_cas', async (route) => {
        if (!first) { await route.continue(); return; }
        first = false;
        await route.fetch();
        holdReads = true;
        await route.abort('internetdisconnected');
      });
      await page.route('**/rest/v1/profiles?**', async (route) => {
        if (holdReads && route.request().method() === 'GET') await reads;
        await route.continue();
      });

      await restore.click();
      await expect(notice).toContainText('Checking whether your guest profile was restored', { timeout: 15_000 });
      await expect(page.getByTestId('keep-account-profile')).toBeDisabled();
      await expect(notice).toContainText('You can keep your account profile once the restore has finished.');
      await page.locator('#grade').selectOption('Senior');
      const hold = page.getByTestId('guest-restore-hold');
      await expect(hold).toHaveText('Saving and matching are paused until we know whether your guest profile was restored. Your entries are kept.');
      await expect(page.getByTestId('generate-matches')).toBeDisabled();
      // Well past the autosave's 1.5 s: the edit waits in the journal.
      await page.waitForTimeout(3_000);
      expect(attempts).toHaveLength(1);
      expect(await profileRows(http, account.uid)).toMatchObject([{ revision: 2, profile_data: guest }]);
      await notice.scrollIntoViewIfNeeded();
      await page.screenshot({ path: info.outputPath('restore-hold-while-checking.png') });

      releaseReads();
      await expect(notice).toContainText('Your guest profile is restored.', { timeout: 15_000 });
      // Then the edit goes out, against the restored row, and nothing is in
      // dispute: the form and the server hold the same profile.
      await expect.poll(async () => (await profileRows(http, account.uid))[0]?.revision, { timeout: 15_000 }).toBe(3);
      expect(await profileRows(http, account.uid)).toMatchObject([{ revision: 3, profile_data: { ...guest, grade: 'Senior' } }]);
      await expectForm(page, { ...guest, grade: 'Senior' });
      await expect(hold).toHaveCount(0);
      await expect(page.getByTestId('conflict-keep-mine')).toHaveCount(0);
      expect(attempts.slice(1).every((attempt) => Object.keys(attempt.patch).join() === 'grade')).toBe(true);

      await page.reload();
      await waitForForm(page);
      await expectForm(page, { ...guest, grade: 'Senior' });
      await page.waitForTimeout(1_000);
      await expect(notice).toHaveCount(0);
      expect(await profileRows(http, account.uid)).toMatchObject([{ revision: 3 }]);
    } finally {
      await http.dispose();
    }
  });

  test('an edit made offline after a restore with no answer could not be read back is sent on reconnecting only once the restore is read back', async ({ page, context }) => {
    const http = await apiRequest.newContext();
    const email = mailbox('restore-hold-offline');
    const guest: GuestDraft = {
      name: 'Guest whose restore was read back after reconnecting', college: 'Grainger College of Engineering',
      major: 'Computer Science', grade: 'Junior', research_interests: 'Guest draft about wearable sensing, offline',
    };
    try {
      const account = await seedAccount(http, email);
      await englishOnly(page);
      await guestSignsInToAccount(page, http, email, guest);
      const notice = page.getByTestId('merged-guest-notice');
      const status = page.locator('#profile-save-status');
      await expect(page.getByTestId('restore-guest-profile')).toBeEnabled({ timeout: 15_000 });
      const attempts: Array<Partial<ProfileData>> = [];
      page.on('request', (request) => {
        if (isCas(request.url()) && request.method() === 'POST') attempts.push(request.postDataJSON().p_patch);
      });
      // The restore reaches the server, and the browser goes offline before
      // its answer arrives, so the profile cannot be read back either.
      await page.route('**/rest/v1/rpc/commit_profile_patch_cas', async (route) => {
        await route.fetch();
        await context.setOffline(true);
        await route.abort('internetdisconnected');
      });
      await page.getByTestId('restore-guest-profile').click();
      await expect(notice).toContainText("We couldn't check whether your guest profile was restored.", { timeout: 15_000 });
      await page.unroute('**/rest/v1/rpc/commit_profile_patch_cas');

      await page.locator('#grade').selectOption('Senior');
      await page.waitForTimeout(3_000);
      expect(attempts, 'nothing is sent offline').toHaveLength(1);
      await expect(status).not.toContainText("couldn't sync");
      await expect(page.getByTestId('guest-restore-hold')).toBeVisible();

      // Back online: the notice reads the profile back, finds the restore,
      // and only then does the edit go out, against it.
      await context.setOffline(false);
      await expect(notice).toContainText('Your guest profile is restored.', { timeout: 15_000 });
      await expect.poll(async () => (await profileRows(http, account.uid))[0]?.revision, { timeout: 15_000 }).toBe(3);
      expect(await profileRows(http, account.uid)).toMatchObject([{ revision: 3, profile_data: { ...guest, grade: 'Senior' } }]);
      await expectForm(page, { ...guest, grade: 'Senior' });
      await expect(page.getByTestId('conflict-keep-mine')).toHaveCount(0);
      expect(attempts.slice(1).every((patch) => Object.keys(patch).join() === 'grade')).toBe(true);

      await page.reload();
      await waitForForm(page);
      await expectForm(page, { ...guest, grade: 'Senior' });
      await expect(notice).toHaveCount(0);
    } finally {
      await http.dispose();
    }
  });

  test('a restore offer left open restores nothing once a guest in another browser has signed in to the same account', async ({ page, browser }, info) => {
    const http = await apiRequest.newContext();
    const email = mailbox('restore-later');
    const first: GuestDraft = {
      name: 'Guest on the laptop 王', college: 'Grainger College of Engineering', major: 'Computer Science',
      grade: 'Freshman', research_interests: 'Laptop guest draft about soft robotics 王',
    };
    const second: GuestDraft = {
      name: 'Guest on the phone', college: 'Grainger College of Engineering', major: 'Electrical Engineering',
      grade: 'Sophomore', research_interests: 'Phone guest draft about power electronics',
    };
    let other: BrowserContext | null = null;
    try {
      const account = await seedAccount(http, email);
      await englishOnly(page);
      const receipts = recordCas(page);
      await guestSignsInToAccount(page, http, email, first);
      await expect(page.getByTestId('restore-guest-profile')).toHaveText('Restore my guest profile', { timeout: 15_000 });
      const writesAfterFirst = receipts.length;

      // The laptop's offer is left unanswered while a second guest signs in
      // to the same account on another browser, which archives its own.
      other = await browser.newContext();
      const phone = await other.newPage();
      await englishOnly(phone);
      await guestSignsInToAccount(phone, http, email, second);
      await expect(phone.getByTestId('restore-guest-profile')).toHaveText('Restore my guest profile', { timeout: 15_000 });
      expect(await stubGet(http, `/rest/v1/profile_versions?device_id=eq.${account.uid}&order=created_at.asc`))
        .toMatchObject([{ profile_revision: null, profile_data: first }, { profile_revision: null, profile_data: second }]);

      // The laptop's offer names its own guest's row, but a later sign-in has
      // since set the phone guest's profile aside in the same account, and
      // only the newest one set aside is restored. It restores nothing and
      // says so.
      await page.bringToFront();
      await page.getByTestId('restore-guest-profile').click();
      const notice = page.getByTestId('merged-guest-notice');
      await expect(notice).toContainText("Your guest profile can't be restored here any more", { timeout: 15_000 });
      await expect(notice).toContainText('Nothing was restored');
      await expect(page.getByTestId('restore-guest-profile')).toHaveCount(0);
      await expectForm(page, ACCOUNT_PROFILE);
      await page.screenshot({ path: info.outputPath('restore-after-later-merge.png') });
      expect(receipts.slice(writesAfterFirst), 'the laptop writes nothing').toEqual([]);
      expect(await profileRows(http, account.uid)).toMatchObject([{ revision: 1, profile_data: ACCOUNT_PROFILE }]);

      await page.reload();
      await waitForForm(page);
      await expect(page.getByTestId('merged-guest-notice'), 'and it is not offered again').toHaveCount(0);
    } finally {
      await other?.close();
      await http.dispose();
    }
  });

  test('a guest who opens the sign-in link in a new tab keeps the account profile, and the old tab writes nothing over it', async ({ page, context }) => {
    const http = await apiRequest.newContext();
    const email = mailbox('newtab');
    const guest = {
      name: 'Guest in the first tab 王', college: 'Grainger College of Engineering', major: 'Computer Science',
      grade: 'Freshman', research_interests: 'Guest draft typed before signing in 王',
    };
    try {
      const account = await seedAccount(http, email);
      await englishOnly(page);
      const receipts = recordCas(page);
      await page.goto('/');
      await waitForForm(page);
      await fillForm(page, guest);
      await expect(page.locator('#profile-save-status')).toHaveText('Profile saved', { timeout: 15_000 });
      const { modal } = await requestLink(page, email);
      const existing = modal.getByTestId('auth-modal-signin-existing');
      await expect(existing).toBeVisible();
      await existing.click();
      await expect(modal.getByText('Check your inbox', { exact: true })).toBeVisible();
      await modal.getByRole('button', { name: 'Done', exact: true }).click();
      const writesBeforeLink = receipts.length;

      // The student opens the mail in another tab; Home stays open behind it.
      const mailTab = await context.newPage();
      await englishOnly(mailTab);
      const mailReceipts = recordCas(mailTab);
      const redeemed = mailTab.waitForResponse((response) => path(response.url()) === '/rest/v1/rpc/redeem_merge_grant');
      await openLinkAndLand(mailTab, await latestLink(http, email, 'magiclink'), email);
      expect(await (await redeemed).json()).toMatchObject({
        merged: true, summary: { profile: 'kept_target_saved_other_as_version' },
      });
      await waitForForm(mailTab);
      await expectForm(mailTab, ACCOUNT_PROFILE);

      // Back in the first tab: it follows the sign-in and stops presenting the
      // guest's profile as this account's.
      await page.bringToFront();
      await expect(accountMenu(page)).toHaveAttribute('aria-label', `Your account, signed in as ${email}`, { timeout: 15_000 });
      await expect(page.locator('#student_name')).not.toHaveValue(guest.name);
      await page.reload();
      await waitForForm(page);
      await expectForm(page, ACCOUNT_PROFILE);
      expect(receipts.slice(writesBeforeLink), 'the old tab never writes the guest profile into the account').toEqual([]);
      expect(mailReceipts).toEqual([]);
      expect(await profileRows(http, account.uid)).toMatchObject([{ revision: 1, profile_data: ACCOUNT_PROFILE }]);
    } finally {
      await http.dispose();
    }
  });

  test('a guest Home tab left open while a new tab signs in loads the account profile on the first click, with no page reload', async ({ page, context }, info) => {
    const http = await apiRequest.newContext();
    const email = mailbox('open-tab-retry');
    const guest = {
      name: 'Guest whose tab stays open 王', college: 'Grainger College of Engineering', major: 'Computer Science',
      grade: 'Freshman', research_interests: 'Guest draft left in the first tab 王',
    };
    const typed = 'Typed in the first tab while the second one finished 王';
    let flow: Awaited<ReturnType<typeof signInFromNewTab>> | null = null;
    try {
      const account = await seedAccount(http, email);
      flow = await signInFromNewTab(page, context, http, email, guest);
      const note = page.getByTestId('hydration-note');
      const load = page.getByTestId('retry-profile-load');
      // The guest's profile is gone from the screen, and the note says why
      // rather than reporting a failed read.
      await expect(note).toHaveText(SIGNED_IN_ELSEWHERE, { timeout: 15_000 });
      await expect(load).toHaveText('Load my profile');
      await expect(page.locator('#student_name')).toHaveValue('');
      await watchStatus(page);
      // Typed while the other tab still holds the hand-off: kept on screen,
      // sent nowhere, and not reported as a save that failed.
      await page.locator('#research_interests').fill(typed);
      await expect(note).toHaveText(SIGNED_IN_ELSEWHERE);
      await load.scrollIntoViewIfNeeded();
      await page.screenshot({ path: info.outputPath('old-tab-while-new-tab-finishes.png') });

      await flow.finish();
      await page.bringToFront();
      await expect(note, "nothing loads behind the student's back").toHaveText(SIGNED_IN_ELSEWHERE);
      await load.click();
      await expect(note).toHaveCount(0, { timeout: 15_000 });
      await expectForm(page, { ...ACCOUNT_PROFILE, research_interests: typed });
      await expect(page.locator('#profile-save-status')).toHaveText('Profile saved', { timeout: 15_000 });
      const shown = await page.evaluate(() => (window as unknown as { cloudSaveStatuses: Array<{ text: string }> }).cloudSaveStatuses);
      expect(shown.filter((entry) => entry.text.includes("Couldn't save"))).toEqual([]);
      expect(flow.receipts.slice(flow.writesBeforeLink), 'the old tab writes only what was typed there, onto the account row').toEqual([
        { uid: account.uid, patch: { research_interests: typed }, status: 'applied', revision: 2 },
      ]);
      expect(flow.mailReceipts).toEqual([]);
      expect(await profileRows(http, account.uid))
        .toMatchObject([{ revision: 2, profile_data: { ...ACCOUNT_PROFILE, research_interests: typed } }]);
      expect(await stubGet(http, `/rest/v1/profile_versions?device_id=eq.${account.uid}`))
        .toMatchObject([{ profile_revision: null, profile_data: guest }]);
      expect(await profileRows(http, flow.guestUid)).toEqual([]);
    } finally {
      flow?.release();
      await http.dispose();
    }
  });

  test('in a guest Home tab left open while a new tab signs in, the next edit loads the account profile and saves only that edit', async ({ page, context }) => {
    const http = await apiRequest.newContext();
    const email = mailbox('open-tab-edit');
    const guest = {
      name: 'Guest who keeps typing 王', college: 'Grainger College of Engineering', major: 'Computer Science',
      grade: 'Sophomore', research_interests: 'Guest draft from before signing in 王',
    };
    const typed = 'First edit in the old tab after the new tab finished 王';
    let flow: Awaited<ReturnType<typeof signInFromNewTab>> | null = null;
    try {
      const account = await seedAccount(http, email);
      flow = await signInFromNewTab(page, context, http, email, guest);
      const note = page.getByTestId('hydration-note');
      await expect(note).toHaveText(SIGNED_IN_ELSEWHERE, { timeout: 15_000 });
      await flow.finish();

      await page.bringToFront();
      await watchStatus(page);
      await page.locator('#research_interests').fill(typed);
      await expect(note).toHaveCount(0, { timeout: 15_000 });
      await expectForm(page, { ...ACCOUNT_PROFILE, research_interests: typed });
      await expect(page.locator('#profile-save-status')).toHaveText('Profile saved', { timeout: 15_000 });
      const shown = await page.evaluate(() => (window as unknown as { cloudSaveStatuses: Array<{ text: string }> }).cloudSaveStatuses);
      expect(shown.filter((entry) => entry.text.includes("Couldn't save"))).toEqual([]);
      expect(flow.receipts.slice(flow.writesBeforeLink)).toEqual([
        { uid: account.uid, patch: { research_interests: typed }, status: 'applied', revision: 2 },
      ]);
      expect(flow.mailReceipts).toEqual([]);
      expect(await profileRows(http, account.uid))
        .toMatchObject([{ revision: 2, profile_data: { ...ACCOUNT_PROFILE, research_interests: typed } }]);
    } finally {
      flow?.release();
      await http.dispose();
    }
  });

  test('two browsers on one account: the later save is held as a conflict and neither text is lost', async ({ page, browser }, info) => {
    const http = await apiRequest.newContext();
    let second: BrowserContext | null = null;
    const laptopText = 'Laptop: interest in neural interfaces 王';
    const phoneText = 'Phone: interest in brain-computer interfaces 王';
    try {
      const account = await seedAccount(http, mailbox('devices'));
      second = await browser.newContext();
      const laptop = page, phone = await second.newPage();
      for (const device of [laptop, phone]) { await englishOnly(device); await signedIn(device, account); }
      const laptopCas = recordCas(laptop), phoneCas = recordCas(phone);
      for (const device of [laptop, phone]) {
        await device.goto('/');
        await waitForForm(device);
        await expectForm(device, ACCOUNT_PROFILE);
      }

      await laptop.locator('#research_interests').fill(laptopText);
      await expect(laptop.locator('#profile-save-status')).toHaveText('Profile saved', { timeout: 15_000 });
      expect(laptopCas).toMatchObject([{ status: 'applied', revision: 2, patch: { research_interests: laptopText } }]);

      // The phone still shows revision 1 and edits two fields; the laptop has
      // just changed one of them.
      await phone.locator('#grade').selectOption('Senior');
      await phone.locator('#research_interests').fill(phoneText);
      await expect(phone.locator('#profile-save-status'))
        .toContainText('Changed on another device — this edit was NOT saved.', { timeout: 15_000 });
      await expect(phone.getByTestId('conflict-keep-mine')).toBeVisible();
      await expect(phone.getByTestId('conflict-use-cloud')).toBeVisible();
      await expect(phone.locator('#research_interests'), 'the phone keeps what was typed there').toHaveValue(phoneText);
      // The stale write was refused outright; only the field nobody else
      // touched went through, rebased onto the laptop's revision.
      expect(phoneCas).toMatchObject([
        { status: 'conflict', revision: 2, patch: { grade: 'Senior', research_interests: phoneText } },
        { status: 'applied', revision: 3, patch: { grade: 'Senior' } },
      ]);
      expect(Object.keys(phoneCas[1].patch)).toEqual(['grade']);
      expect(await profileRows(http, account.uid), 'the laptop text is still the stored one')
        .toMatchObject([{ revision: 3, profile_data: { grade: 'Senior', research_interests: laptopText } }]);
      await phone.locator('#profile-save-status').scrollIntoViewIfNeeded();
      await phone.screenshot({ path: info.outputPath('conflict-on-phone.png') });

      await phone.getByTestId('conflict-keep-mine').click();
      await expect(phone.locator('#profile-save-status')).toHaveText('Profile saved', { timeout: 15_000 });
      await expect(phone.getByTestId('conflict-keep-mine')).toHaveCount(0);
      expect(phoneCas.at(-1)).toMatchObject({ status: 'applied', revision: 4, patch: { research_interests: phoneText } });
      expect(await profileRows(http, account.uid))
        .toMatchObject([{ revision: 4, profile_data: { ...ACCOUNT_PROFILE, grade: 'Senior', research_interests: phoneText } }]);

      await laptop.reload();
      await waitForForm(laptop);
      await expectForm(laptop, { ...ACCOUNT_PROFILE, grade: 'Senior', research_interests: phoneText });
      expect(laptopCas, 'the laptop only re-reads').toHaveLength(1);
    } finally {
      await second?.close();
      await http.dispose();
    }
  });

  test('an edit made offline is reported as not saved, and is sent once by itself when the browser is back online', async ({ page, context }, info) => {
    const http = await apiRequest.newContext();
    const offlineText = 'Typed on a train with no signal 王';
    let release!: () => void;
    const held = new Promise<void>((resolve) => { release = resolve; });
    try {
      const account = await seedAccount(http, mailbox('offline'));
      await englishOnly(page);
      await signedIn(page, account);
      const receipts = recordCas(page);
      await page.goto('/');
      await waitForForm(page);
      await expectForm(page, ACCOUNT_PROFILE);
      const status = page.locator('#profile-save-status');
      await watchStatus(page);

      await context.setOffline(true);
      await expect.poll(() => page.evaluate(() => navigator.onLine)).toBe(false);
      await page.locator('#research_interests').fill(offlineText);
      await expect(status).toContainText("Saved on this device only — we couldn't sync it.", { timeout: 15_000 });
      await expect(page.getByTestId('retry-sync')).toBeVisible();
      expect(receipts, 'no write reached the server').toEqual([]);
      expect(await profileRows(http, account.uid)).toMatchObject([{ revision: 1, profile_data: ACCOUNT_PROFILE }]);
      await status.scrollIntoViewIfNeeded();
      await page.screenshot({ path: info.outputPath('offline-save-failed.png') });

      // Hold the resend so the screen can be read while it is in flight, and
      // note which revision it was made against.
      const expected: number[] = [];
      await page.route('**/rest/v1/rpc/commit_profile_patch_cas', async (route) => {
        expected.push(route.request().postDataJSON().p_expected_revision);
        await held;
        await route.continue();
      });
      const resent = page.waitForResponse((response) => isCas(response.url()));
      // Back online. Nobody presses Retry.
      await context.setOffline(false);
      await expect.poll(() => page.evaluate(() => navigator.onLine)).toBe(true);
      await expect(status).toHaveText('Saving...', { timeout: 15_000 });
      await page.evaluate(() => { (window as unknown as { cloudSaveReleased: boolean }).cloudSaveReleased = true; });
      release();
      expect(await (await resent).json()).toMatchObject({ status: 'applied', revision: 2, profile: { research_interests: offlineText } });
      await expect(status).toHaveText('Profile saved');
      await expectStatusOnlyAfterRelease(page);
      expect(expected, 'one resend, made against the revision the edit was typed on').toEqual([1]);
      expect(receipts).toMatchObject([{ status: 'applied', revision: 2, patch: { research_interests: offlineText } }]);
      expect(await profileRows(http, account.uid))
        .toMatchObject([{ revision: 2, profile_data: { ...ACCOUNT_PROFILE, research_interests: offlineText } }]);
      // Coming back to the tab later sends nothing more: nothing is owed.
      await page.evaluate(() => document.dispatchEvent(new Event('visibilitychange')));
      await page.evaluate(() => window.dispatchEvent(new Event('online')));
      await page.waitForTimeout(2_000);
      expect(expected).toEqual([1]);

      await page.unroute('**/rest/v1/rpc/commit_profile_patch_cas');
      await page.reload();
      await waitForForm(page);
      await expect(page.locator('#research_interests')).toHaveValue(offlineText);
    } finally {
      release();
      await http.dispose();
    }
  });

  test('an edit that failed offline, and again when the browser came back, survives a reload and is sent from the journal', async ({ page, context }) => {
    const http = await apiRequest.newContext();
    const offlineText = 'Typed offline, then the tab was reloaded 王';
    try {
      const account = await seedAccount(http, mailbox('reload'));
      await englishOnly(page);
      await signedIn(page, account);
      const receipts = recordCas(page);
      await page.goto('/');
      await waitForForm(page);
      await context.setOffline(true);
      await expect.poll(() => page.evaluate(() => navigator.onLine)).toBe(false);
      await page.locator('#research_interests').fill(offlineText);
      await expect(page.getByTestId('retry-sync')).toBeVisible({ timeout: 15_000 });
      expect(receipts).toEqual([]);

      // The browser comes back but the server is still out of reach, so the
      // one resend on reconnecting fails as well.
      await page.route('**/rest/v1/rpc/commit_profile_patch_cas', (route) => route.abort('internetdisconnected'));
      const refused = page.waitForEvent('requestfailed', (request) => isCas(request.url()));
      await context.setOffline(false);
      await expect.poll(() => page.evaluate(() => navigator.onLine)).toBe(true);
      await refused;
      await expect(page.getByTestId('retry-sync')).toBeVisible({ timeout: 15_000 });
      await page.unroute('**/rest/v1/rpc/commit_profile_patch_cas');
      const sent = page.waitForResponse((response) => isCas(response.url()));
      await page.reload();
      await waitForForm(page);
      await expect(page.locator('#research_interests')).toHaveValue(offlineText);
      expect(await (await sent).json()).toMatchObject({ status: 'applied', revision: 2, profile: { research_interests: offlineText } });
      expect(receipts).toMatchObject([{ status: 'applied', patch: { research_interests: offlineText } }]);
      expect(await profileRows(http, account.uid))
        .toMatchObject([{ revision: 2, profile_data: { ...ACCOUNT_PROFILE, research_interests: offlineText } }]);
    } finally {
      await http.dispose();
    }
  });
});
