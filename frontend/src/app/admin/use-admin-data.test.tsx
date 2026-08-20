import { beforeEach, describe, expect, it, vi } from 'vitest';
import { fireEvent, render, screen, waitFor, within } from '@testing-library/react';
import AdminPage from './page';
import { SESSION_KEY } from './admin-api';
import type { OpsIncident, Ticket } from './types';

const { adminFetchMock, searchParams } = vi.hoisted(() => ({
  adminFetchMock: vi.fn(),
  searchParams: new URLSearchParams(''),
}));

vi.mock('next/navigation', () => ({ useSearchParams: () => searchParams }));

vi.mock('next/link', () => ({
  default: ({ href, children }: { href: string; children: React.ReactNode }) => (
    <a href={href}>{children}</a>
  ),
}));

vi.mock('@/i18n/client', () => ({
  useT: () => ({ t: (key: string) => key, locale: 'en', setLocale: vi.fn() }),
}));

vi.mock('./admin-api', async () => {
  const actual = await vi.importActual<typeof import('./admin-api')>('./admin-api');
  return { ...actual, adminFetch: adminFetchMock };
});

interface Call { path: string; init?: RequestInit }

const calls: Call[] = [];
let ticketRow: Ticket;
let ticketEvents: { actor: string; action: string; created_at: string }[];
let incidentRow: OpsIncident;
let mainStatus: { status: number; error?: string } | null;
let historyRows: Record<string, unknown>[];
let mainData: Record<string, unknown> | null;
let feedbackListStatus: { status: number; error?: string } | null;
let ticketPatchStatus: { status: number; error?: string } | null;

const lastCall = (predicate: (c: Call) => boolean) => [...calls].reverse().find(predicate);

function install() {
  adminFetchMock.mockImplementation(async (path: string, _token: string, init?: RequestInit) => {
    calls.push({ path, init });
    const body = init?.body ? JSON.parse(String(init.body)) : undefined;

    if (path.startsWith('/admin/data-quality/history')) {
      return { status: 200, data: { history: historyRows } };
    }
    if (path.startsWith('/admin/data-quality')) {
      if (mainStatus) return mainStatus;
      return {
        status: 200,
        data: mainData ?? {
          total: 10,
          global: {},
          sources: [],
          worst_fields: [],
          generated_at: '2026-08-04T10:00:00+00:00',
        },
      };
    }
    if (path.startsWith('/admin/health-check')) {
      return { status: 200, data: { ok: true, alerts: [], checked_at: '2026-08-04T10:00:00+00:00' } };
    }
    if (path.startsWith('/admin/collector-status/history')) {
      return { status: 200, data: { entries: [], count: 0 } };
    }
    if (path.startsWith('/admin/collector-status')) return { status: 200, data: { sources: [] } };
    if (path.startsWith('/admin/saved-search-health')) return { status: 200, data: { status: 'unconfigured' } };
    if (path.startsWith('/admin/orders')) return { status: 200, data: { status: 'ok', orders: [], count: 0 } };

    if (path.startsWith('/admin/feedback/')) {
      if (init?.method === 'PATCH') {
        if (ticketPatchStatus) return ticketPatchStatus;
        ticketRow = { ...ticketRow, ...body };
        ticketEvents = [
          ...ticketEvents,
          { actor: 'ana', action: 'status_changed', created_at: '2026-08-04T11:00:00+00:00' },
        ];
        return { status: 200, data: ticketRow };
      }
      if (init?.method === 'POST') {
        ticketRow = {
          ...ticketRow,
          admin_reply: body.reply,
          admin_reply_delivery: body.deliver ? 'emailed' : 'stored',
        };
        return { status: 200, data: ticketRow };
      }
      return { status: 200, data: { ticket: ticketRow, events: ticketEvents } };
    }
    if (path.startsWith('/admin/feedback')) {
      if (feedbackListStatus) return feedbackListStatus;
      return { status: 200, data: { status: 'ok', entries: [ticketRow], count: 1 } };
    }

    if (path.startsWith('/admin/ops/incidents/')) {
      if (path.endsWith('/retry')) {
        incidentRow = { ...incidentRow, attempt_count: (incidentRow.attempt_count ?? 0) + 1 };
        return { status: 200, data: incidentRow };
      }
      if (init?.method === 'PATCH') {
        incidentRow = { ...incidentRow, ...body };
        return { status: 200, data: incidentRow };
      }
      return { status: 200, data: { incident: incidentRow, events: [] } };
    }
    if (path.startsWith('/admin/ops/incidents')) {
      const kind = new URLSearchParams(path.split('?')[1] ?? '').get('kind');
      const incidents = !kind || kind === incidentRow.kind ? [incidentRow] : [];
      return {
        status: 200,
        data: {
          incidents,
          // Mirrors the endpoint's real payload (counts nested under
          // open_by_kind), not the flat map the UI used to assume.
          rollup: {
            open_by_kind: {
              collector_failure: 1, data_drift: 2, notification_failure: 0, manual_review: 4,
            },
            open_by_priority: { high: 3, normal: 4 },
            open_total: 7,
            truncated: false,
          },
        },
      };
    }
    return { status: 200, data: {} };
  });
}

beforeEach(() => {
  calls.length = 0;
  mainStatus = null;
  historyRows = [];
  mainData = null;
  feedbackListStatus = null;
  ticketPatchStatus = null;
  ticketRow = {
    id: 't1',
    created_at: '2026-08-01T10:00:00+00:00',
    subject: 'Broken compare page',
    message: 'Compare crashes on two schools',
    email: 'student@illinois.edu',
    status: 'open',
    priority: 'normal',
    assigned_to: null,
    props: {},
  };
  ticketEvents = [];
  incidentRow = {
    id: 'i1',
    kind: 'collector_failure',
    dedup_key: 'collector_failure:uiuc_faculty',
    scope: 'uiuc_faculty',
    title: 'uiuc_faculty collector failed',
    summary: 'HTTP 403 from the department directory',
    detail: { error_category: 'waf_block' },
    priority: 'high',
    status: 'open',
    failure_state: 'failed',
    occurrence_count: 4,
    attempt_count: 0,
    last_detected_at: '2026-08-04T10:00:00+00:00',
  };
  sessionStorage.setItem(SESSION_KEY, 'tok');
  install();
});

async function mount() {
  render(<AdminPage />);
  await screen.findByText('uiuc_faculty collector failed');
}

describe('useAdminData wiring', () => {
  it('loads every admin pane, including the ops queue, from one bootstrap', async () => {
    await mount();
    const paths = calls.map((c) => c.path);
    expect(paths).toContain('/admin/data-quality');
    expect(paths.some((p) => p.startsWith('/admin/feedback?'))).toBe(true);
    expect(paths.some((p) => p.startsWith('/admin/ops/incidents?'))).toBe(true);
    expect(screen.getByText('Broken compare page')).toBeInTheDocument();
  });

  it('keeps the ops queue and ticket inbox on screen when /admin/data-quality fails', async () => {
    mainStatus = { status: 500, error: 'data-quality exploded' };
    await mount();
    // the failing pane reports itself…
    expect(screen.getByText('data-quality exploded')).toBeInTheDocument();
    // …and the operational surfaces are still there
    expect(screen.getByText('uiuc_faculty collector failed')).toBeInTheDocument();
    expect(screen.getByText('Broken compare page')).toBeInTheDocument();
  });

  it('surfaces a 401 from a non-main admin call instead of rendering an empty section', async () => {
    feedbackListStatus = { status: 401, error: 'unauthorized' };
    render(<AdminPage />);
    expect(await screen.findByText('Invalid admin token')).toBeInTheDocument();
    // the console locks back to the token form rather than pretending the
    // inbox is simply empty
    expect(screen.getByText('admin.unauthorizedHint')).toBeInTheDocument();
    expect(sessionStorage.getItem(SESSION_KEY)).toBeNull();
  });

  describe('ticket mutations', () => {
    it('PATCHes the status and re-renders from the refetched server state', async () => {
      await mount();
      fireEvent.click(screen.getByRole('button', { name: 'Broken compare page' }));
      fireEvent.change(await screen.findByLabelText('admin.tickets.statusLabel'), {
        target: { value: 'triaged' },
      });

      const patch = await waitFor(() => {
        const c = lastCall((x) => x.path === '/admin/feedback/t1' && x.init?.method === 'PATCH');
        expect(c).toBeTruthy();
        return c!;
      });
      expect(JSON.parse(String(patch.init!.body))).toEqual({ status: 'triaged' });

      // the pill is server state read back after the mutation, not an
      // optimistic local flip
      expect(await screen.findByText('triaged')).toBeInTheDocument();
      expect(
        calls.filter((c) => c.path.startsWith('/admin/feedback?')).length,
      ).toBeGreaterThan(1);
    });

    it('a failed PATCH shows an error and leaves the prior state', async () => {
      await mount();
      fireEvent.click(screen.getByRole('button', { name: 'Broken compare page' }));
      ticketPatchStatus = { status: 500, error: 'HTTP 500' };
      fireEvent.change(await screen.findByLabelText('admin.tickets.statusLabel'), {
        target: { value: 'triaged' },
      });

      await waitFor(() =>
        expect(screen.getByText('admin.tickets.mutationFailed')).toBeInTheDocument(),
      );
      expect(screen.queryByText('triaged')).toBeNull();
      expect(screen.getByLabelText('admin.tickets.statusLabel')).toHaveValue('open');
    });

    it('posts a reply with the deliver flag and reads the delivery outcome back', async () => {
      await mount();
      fireEvent.click(screen.getByRole('button', { name: 'Broken compare page' }));
      fireEvent.change(await screen.findByLabelText('admin.tickets.replyTitle'), {
        target: { value: 'fixed in W15' },
      });
      fireEvent.click(screen.getByRole('button', { name: 'admin.tickets.replySave' }));

      await waitFor(() => {
        const c = lastCall((x) => x.path === '/admin/feedback/t1/reply');
        expect(c).toBeTruthy();
        expect(JSON.parse(String(c!.init!.body))).toEqual({ reply: 'fixed in W15', deliver: false });
      });
      // deliver=false → the backend stored it, so the UI says stored
      expect(await screen.findByText('admin.tickets.deliveryStored')).toBeInTheDocument();
      // a reply is not a resolution
      expect(screen.getByLabelText('admin.tickets.statusLabel')).toHaveValue('open');
    });
  });

  describe('ops mutations', () => {
    it('acknowledges through PATCH and re-renders the refetched status', async () => {
      await mount();
      fireEvent.click(screen.getByRole('button', { name: 'uiuc_faculty collector failed' }));
      fireEvent.click(await screen.findByRole('button', { name: 'admin.ops.acknowledge' }));

      await waitFor(() => {
        const c = lastCall((x) => x.path === '/admin/ops/incidents/i1' && x.init?.method === 'PATCH');
        expect(c).toBeTruthy();
        expect(JSON.parse(String(c!.init!.body))).toEqual({ status: 'acknowledged' });
      });
      expect(await screen.findByText('acknowledged')).toBeInTheDocument();
    });

    it('records a retry attempt without resolving the incident', async () => {
      await mount();
      fireEvent.click(screen.getByRole('button', { name: 'uiuc_faculty collector failed' }));
      fireEvent.click(await screen.findByRole('button', { name: 'admin.ops.retry' }));

      await waitFor(() =>
        expect(lastCall((x) => x.path === '/admin/ops/incidents/i1/retry')).toBeTruthy(),
      );
      expect(lastCall((x) => x.path === '/admin/ops/incidents/i1/retry')!.init?.method).toBe('POST');
      expect(await screen.findByText('admin.ops.retryRecorded')).toBeInTheDocument();
      // still open, still unresolved — a recorded attempt is not an outcome
      const row = screen.getByText('uiuc_faculty collector failed').closest('li')!;
      expect(within(row).getByText('open')).toBeInTheDocument();
      expect(incidentRow.status).toBe('open');
      expect(incidentRow.resolution).toBeUndefined();
    });

    it('the kind filter refetches with the kind query param', async () => {
      await mount();
      fireEvent.click(screen.getByRole('button', { name: 'admin.ops.kind.data_drift 2' }));
      await waitFor(() => {
        const c = lastCall((x) => x.path.startsWith('/admin/ops/incidents?'));
        expect(c!.path).toContain('kind=data_drift');
      });
      // the collector incident is no longer in the returned set
      await waitFor(() => expect(screen.queryByText('uiuc_faculty collector failed')).toBeNull());
    });

    it('the unresolved default hides closed incidents without a second request', async () => {
      incidentRow = { ...incidentRow, status: 'resolved', resolution: 'fixed' };
      render(<AdminPage />);
      await waitFor(() => expect(screen.getByText('admin.ops.empty')).toBeInTheDocument());
      expect(screen.queryByText('uiuc_faculty collector failed')).toBeNull();
    });
  });

  describe('ticket filters', () => {
    it('sends the status filter to the server', async () => {
      await mount();
      fireEvent.change(screen.getByLabelText('admin.tickets.filterStatus'), {
        target: { value: 'waiting_on_user' },
      });
      await waitFor(() => {
        const c = lastCall((x) => x.path.startsWith('/admin/feedback?'));
        expect(c!.path).toContain('status=waiting_on_user');
      });
    });

    it('sends unresolved_only when the operator asks for it', async () => {
      await mount();
      fireEvent.click(screen.getByLabelText('admin.tickets.filterUnresolved'));
      await waitFor(() => {
        const c = lastCall((x) => x.path.startsWith('/admin/feedback?'));
        expect(c!.path).toContain('unresolved_only=true');
      });
    });
  });
});

describe('W15: a disabled console is one condition, not many failures', () => {
  it('states the 503 once instead of repeating it in every section', async () => {
    // ADMIN_TOKEN unset => every admin call 503s. An E2E strict-mode
    // violation caught the old behavior: the login banner's text matched
    // three elements because each section echoed the same raw detail.
    adminFetchMock.mockImplementation(async (path: string, _tok: string, init?: RequestInit) => {
      calls.push({ path, init });
      return { status: 503, error: 'Admin endpoints disabled (ADMIN_TOKEN unset)' };
    });

    render(<AdminPage />);

    const banners = await screen.findAllByText(/Admin endpoints disabled/i);
    expect(banners).toHaveLength(1);
    expect(screen.queryByText('admin.ops.loadFailed')).not.toBeInTheDocument();
    expect(screen.queryByText('admin.tickets.loadFailed')).not.toBeInTheDocument();
    // A Refresh whose every call can only 503 is a dead control, not a
    // retry — it stays hidden while the console is switched off backend-side
    // (Lock remains, so the operator can still leave).
    expect(screen.queryByText('admin.refresh')).not.toBeInTheDocument();
  });

  it('still reports a genuine per-section failure', async () => {
    // A 500 on one section is a real, section-scoped outage and must show.
    feedbackListStatus = { status: 500, error: 'inbox exploded' };
    await mount();
    // ...and Refresh stays available, because retrying is what it is for.
    expect(screen.getByText('admin.refresh')).toBeInTheDocument();
    // This file's t() mock returns the bare key, so assert on that; the
    // interpolated reason is covered by FeedbackSection.test.tsx.
    expect(await screen.findByText('admin.tickets.loadFailed')).toBeInTheDocument();
  });
});

describe('previousSnapshot is wired through the hook, not just implemented in utils', () => {
  // findPreviousSnapshot has direct unit coverage, but the hook could stop
  // calling it — or go back to history[-2] — and every one of those unit
  // tests would stay green. This asserts the delta an operator actually sees.
  const SCOPE = 'reviewed-record-kind-v1';

  it('renders the delta against the last strictly-earlier same-scope entry', async () => {
    mainData = {
      total: 30,
      quality_scope: SCOPE,
      global: { listing_total: 10, empty_majors: 7 },
      sources: [],
      worst_fields: [],
      generated_at: '2026-08-04T10:00:00+00:00',
    };
    historyRows = [
      // Legacy: has the denominator, not the marker. Never a baseline.
      { t: '2026-08-01T10:00:00+00:00', total: 30, listing_total: 10, empty_majors: 999 },
      // T1 — the one true answer.
      { t: '2026-08-02T10:00:00+00:00', total: 30, listing_total: 10, empty_majors: 4, quality_scope: SCOPE },
      // T2 — the CURRENT snapshot, already appended by the backend. Sharing
      // the timestamp means comparing it with itself: zero delta.
      { t: '2026-08-04T10:00:00+00:00', total: 30, listing_total: 10, empty_majors: 7, quality_scope: SCOPE },
      // A scope this build does not know, newer still.
      { t: '2026-08-05T10:00:00+00:00', total: 30, listing_total: 10, empty_majors: 0, quality_scope: 'reviewed-record-kind-v2' },
    ];

    await mount();

    // 7 now vs 4 at T1 → +3. history[-2] would pick T1 only by luck here, so
    // the self-entry at T2 and the future row after it are what make this
    // discriminating: a raw index lands on T2 (delta 0) or the v2 row.
    expect(await screen.findByText('▲ +3')).toBeInTheDocument();
    expect(screen.queryByText('▲ +7')).not.toBeInTheDocument();
  });

  it('shows no delta at all when the current response is out of scope', async () => {
    mainData = {
      total: 30,
      global: { listing_total: 10, empty_majors: 7 },
      sources: [],
      worst_fields: [],
      generated_at: '2026-08-04T10:00:00+00:00',
    };
    historyRows = [
      { t: '2026-08-02T10:00:00+00:00', total: 30, listing_total: 10, empty_majors: 4, quality_scope: SCOPE },
    ];

    await mount();

    // No delta of ANY kind — asserted on the arrow, so a leak through some
    // other baseline cannot slip past a single hard-coded number.
    expect(screen.queryByText('▲ +3')).not.toBeInTheDocument();
    expect(screen.queryByText(/^[▲▼]/)).not.toBeInTheDocument();
  });
});
