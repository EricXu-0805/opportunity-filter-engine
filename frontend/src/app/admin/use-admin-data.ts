'use client';

import { useCallback, useEffect, useMemo, useState } from 'react';
import { useSearchParams } from 'next/navigation';
import {
  adminFetch,
  DEFAULT_ACTOR,
  getAdminActor,
  setAdminActor,
  SESSION_KEY,
} from './admin-api';
import type {
  AdminResponse,
  CollectorHistoryEntry,
  CollectorStatus,
  FieldKey,
  HealthResponse,
  HistoryEntry,
  FeedbackInbox,
  OpsFilters,
  OpsIncident,
  OpsIncidentDetail,
  OpsIncidentsResponse,
  OpsPatch,
  OpsRollup,
  OrdersInbox,
  SavedSearchHealth,
  TFunc,
  TicketDetail,
  TicketFilters,
  TicketPatch,
  TicketWorkflow,
  OpsWorkflow,
  TriggerStatus,
} from './types';
import { OPS_CLOSED_STATUSES } from './types';

const AUTH_ERROR = 'Invalid admin token';

const DEFAULT_TICKET_FILTERS: TicketFilters = { status: '', priority: '', unresolvedOnly: false };
const DEFAULT_OPS_FILTERS: OpsFilters = { kind: '', status: 'unresolved' };

export function ticketQuery(f: TicketFilters): string {
  const params = new URLSearchParams({ limit: '50' });
  if (f.status) params.set('status', f.status);
  if (f.priority) params.set('priority', f.priority);
  if (f.unresolvedOnly) params.set('unresolved_only', 'true');
  return `/admin/feedback?${params.toString()}`;
}

export function opsQuery(f: OpsFilters): string {
  const params = new URLSearchParams({ limit: '100' });
  if (f.kind) params.set('kind', f.kind);
  if (f.status !== 'unresolved' && f.status !== 'all') params.set('status', f.status);
  // 'unresolved' has no single server-side status value, so it is also applied
  // as a display filter below. Sent as a hint in case the API grows support;
  // undeclared query params are ignored by the backend.
  if (f.status === 'unresolved') params.set('unresolved_only', 'true');
  return `/admin/ops/incidents?${params.toString()}`;
}

/** Hides closed incidents in the default working view without pretending the
 *  server sent a different list — it is still exactly what the API returned. */
function applyOpsView(incidents: OpsIncident[], filters: OpsFilters): OpsIncident[] {
  if (filters.status !== 'unresolved') return incidents;
  return incidents.filter((i) => !OPS_CLOSED_STATUSES.includes(i.status ?? 'open'));
}

export interface UseAdminDataResult {
  token: string;
  tokenInput: string;
  setTokenInput: (v: string) => void;
  actor: string;
  setActor: (v: string) => void;
  data: AdminResponse | null;
  history: HistoryEntry[];
  collectorStatus: CollectorStatus | null;
  collectorHistory: CollectorHistoryEntry[];
  health: HealthResponse | null;
  savedSearchHealth: SavedSearchHealth | null;
  feedbackInbox: FeedbackInbox | null;
  ordersInbox: OrdersInbox | null;
  loading: boolean;
  error: string | null;
  activeFieldFilter: FieldKey | null;
  setActiveFieldFilter: (v: FieldKey | null) => void;
  triggerStatus: TriggerStatus;
  previousSnapshot: HistoryEntry | null;
  filteredWorstFields: AdminResponse['worst_fields'];
  tickets: TicketWorkflow;
  ops: OpsWorkflow;
  fetchAll: (tok: string) => Promise<void>;
  handleSubmitToken: (e: React.FormEvent) => void;
  handleLock: () => void;
  handleTriggerRefresh: (mode: 'quick' | 'deep') => Promise<void>;
  handleConfirmOrder: (id: string) => Promise<void>;
}

export function useAdminData(t: TFunc): UseAdminDataResult {
  const searchParams = useSearchParams();

  const [token, setToken] = useState<string>('');
  const [tokenInput, setTokenInput] = useState<string>('');
  const [actor, setActorState] = useState<string>(DEFAULT_ACTOR);
  const [data, setData] = useState<AdminResponse | null>(null);
  const [history, setHistory] = useState<HistoryEntry[]>([]);
  const [collectorStatus, setCollectorStatus] = useState<CollectorStatus | null>(null);
  const [collectorHistory, setCollectorHistory] = useState<CollectorHistoryEntry[]>([]);
  const [health, setHealth] = useState<HealthResponse | null>(null);
  const [savedSearchHealth, setSavedSearchHealth] = useState<SavedSearchHealth | null>(null);
  const [feedbackInbox, setFeedbackInbox] = useState<FeedbackInbox | null>(null);
  const [ordersInbox, setOrdersInbox] = useState<OrdersInbox | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [activeFieldFilter, setActiveFieldFilter] = useState<FieldKey | null>(null);
  const [triggerStatus, setTriggerStatus] = useState<TriggerStatus>({ kind: 'idle' });

  // Ticket workflow state
  const [ticketFilters, setTicketFilters] = useState<TicketFilters>(DEFAULT_TICKET_FILTERS);
  const [ticketLoadError, setTicketLoadError] = useState<string | null>(null);
  const [ticketDetails, setTicketDetails] = useState<Record<string, TicketDetail | undefined>>({});
  const [ticketDetailLoading, setTicketDetailLoading] = useState<Record<string, boolean>>({});
  const [ticketPending, setTicketPending] = useState<Record<string, boolean>>({});
  const [ticketErrors, setTicketErrors] = useState<Record<string, string | null>>({});
  const [replyPending, setReplyPending] = useState<Record<string, boolean>>({});
  const [replyErrors, setReplyErrors] = useState<Record<string, string | null>>({});

  // Ops queue state
  const [opsFilters, setOpsFilters] = useState<OpsFilters>(DEFAULT_OPS_FILTERS);
  const [opsIncidents, setOpsIncidents] = useState<OpsIncident[]>([]);
  const [opsRollup, setOpsRollup] = useState<OpsRollup>({});
  const [opsLoaded, setOpsLoaded] = useState(false);
  const [opsError, setOpsError] = useState<string | null>(null);
  const [opsDetails, setOpsDetails] = useState<Record<string, OpsIncidentDetail | undefined>>({});
  const [opsDetailLoading, setOpsDetailLoading] = useState<Record<string, boolean>>({});
  const [opsPending, setOpsPending] = useState<Record<string, boolean>>({});
  const [opsErrors, setOpsErrors] = useState<Record<string, string | null>>({});

  /**
   * A 401 from ANY admin call means the token is dead — not just the one on
   * /admin/data-quality. Silently rendering an empty section on a 401 (the
   * pre-W15 behaviour for every non-main call) hides an expired session behind
   * what looks like "no data".
   */
  const surfaceAuthFailure = useCallback(() => {
    setError(AUTH_ERROR);
    try { sessionStorage.removeItem(SESSION_KEY); } catch { /* private mode */ }
    setToken('');
    setData(null);
  }, []);

  const setActor = useCallback((value: string) => {
    setActorState(setAdminActor(value));
  }, []);

  const fetchTickets = useCallback(async (tok: string, filters: TicketFilters) => {
    const res = await adminFetch<FeedbackInbox>(ticketQuery(filters), tok);
    if (res.status === 401) { surfaceAuthFailure(); return; }
    if (res.error) {
      // Do not blank the inbox on a transient read failure — the section says
      // "could not load" instead of silently looking like an empty queue.
      setTicketLoadError(res.error);
      return;
    }
    setTicketLoadError(null);
    setFeedbackInbox(res.data ?? null);
  }, [surfaceAuthFailure]);

  const fetchOps = useCallback(async (tok: string, filters: OpsFilters) => {
    const res = await adminFetch<OpsIncidentsResponse>(opsQuery(filters), tok);
    if (res.status === 401) { surfaceAuthFailure(); return; }
    setOpsLoaded(true);
    if (res.error) {
      setOpsError(res.error);
      setOpsIncidents([]);
      setOpsRollup({});
      return;
    }
    setOpsError(null);
    setOpsIncidents(res.data?.incidents ?? []);
    setOpsRollup(res.data?.rollup ?? {});
  }, [surfaceAuthFailure]);

  const fetchAll = useCallback(async (tok: string) => {
    if (!tok) return;
    setLoading(true);
    setError(null);
    try {
      const [main, hist, healthR, collector, collectorHist, ssHealth, fbInbox, ordInbox, opsRes] =
        await Promise.all([
          adminFetch<AdminResponse>(`/admin/data-quality`, tok),
          adminFetch<{ history: HistoryEntry[] }>(`/admin/data-quality/history?limit=30`, tok),
          adminFetch<HealthResponse>(`/admin/health-check`, tok),
          adminFetch<CollectorStatus>(`/admin/collector-status`, tok),
          adminFetch<{ entries: CollectorHistoryEntry[]; count: number }>(`/admin/collector-status/history?limit=30`, tok),
          adminFetch<SavedSearchHealth>(`/admin/saved-search-health`, tok),
          adminFetch<FeedbackInbox>(ticketQuery(ticketFilters), tok),
          adminFetch<OrdersInbox>(`/admin/orders?limit=50`, tok),
          adminFetch<OpsIncidentsResponse>(opsQuery(opsFilters), tok),
        ]);
      const all = [main, hist, healthR, collector, collectorHist, ssHealth, fbInbox, ordInbox, opsRes];
      if (all.some((r) => r.status === 401)) {
        surfaceAuthFailure();
        return;
      }
      if (main.status === 503) {
        setError('Admin endpoints disabled — ADMIN_TOKEN not set on backend');
        setData(null);
      } else if (main.error) {
        // The data-quality pane failing is not the whole console failing: the
        // ops queue and the ticket inbox are still authoritative and still
        // render. Only the pane that errored goes dark.
        setError(main.error);
        setData(null);
      } else {
        setData(main.data ?? null);
      }
      setHistory(hist.data?.history ?? []);
      setHealth(healthR.data ?? null);
      setCollectorStatus(collector.data ?? null);
      setCollectorHistory(collectorHist.data?.entries ?? []);
      setSavedSearchHealth(ssHealth.data ?? null);
      setTicketLoadError(fbInbox.error ?? null);
      if (!fbInbox.error) setFeedbackInbox(fbInbox.data ?? null);
      setOrdersInbox(ordInbox.data ?? null);
      setOpsLoaded(true);
      setOpsError(opsRes.error ?? null);
      setOpsIncidents(opsRes.data?.incidents ?? []);
      setOpsRollup(opsRes.data?.rollup ?? {});
    } finally {
      setLoading(false);
    }
  }, [ticketFilters, opsFilters, surfaceAuthFailure]);

  useEffect(() => {
    // Never authenticate from the URL: a ?token= there lands in the server
    // access log, the Referer header, and browser history. If one is present
    // (e.g. an old bookmark) strip it from the address bar and ignore it —
    // the operator re-enters the token via the form, persisted per tab in
    // sessionStorage.
    if (searchParams.get('token')) {
      const url = new URL(window.location.href);
      url.searchParams.delete('token');
      window.history.replaceState(null, '', url.pathname + (url.search ? url.search : ''));
    }
    let resolved: string | null = null;
    try { resolved = sessionStorage.getItem(SESSION_KEY); } catch { resolved = null; }
    /* eslint-disable react-hooks/set-state-in-effect --
       Auth token resolution must finish in one effect tick so the
       token-entry form is replaced atomically by the dashboard. */
    setActorState(getAdminActor());
    if (resolved) {
      setToken(resolved);
      setTokenInput(resolved);
      /* eslint-enable react-hooks/set-state-in-effect */
      fetchAll(resolved);
    }
    // fetchAll is intentionally not a dependency: it changes identity whenever
    // a filter changes, and re-running the bootstrap effect would refetch the
    // whole dashboard on every filter click.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [searchParams]);

  const handleSubmitToken = useCallback((e: React.FormEvent) => {
    e.preventDefault();
    if (!tokenInput) return;
    try { sessionStorage.setItem(SESSION_KEY, tokenInput); } catch { /* private mode */ }
    setToken(tokenInput);
    fetchAll(tokenInput);
  }, [tokenInput, fetchAll]);

  const handleLock = useCallback(() => {
    try { sessionStorage.removeItem(SESSION_KEY); } catch { /* private mode */ }
    setToken('');
    setTokenInput('');
    setData(null);
    setHistory([]);
    setCollectorStatus(null);
    setCollectorHistory([]);
    setHealth(null);
    setSavedSearchHealth(null);
    setFeedbackInbox(null);
    setOrdersInbox(null);
    setOpsIncidents([]);
    setOpsRollup({});
    setOpsLoaded(false);
    setOpsError(null);
    setOpsDetails({});
    setTicketDetails({});
    setError(null);
  }, []);

  const handleConfirmOrder = useCallback(async (id: string) => {
    if (!token) return;
    const res = await adminFetch(`/admin/orders/${id}/confirm`, token, { method: 'POST' });
    if (res.status === 401) { surfaceAuthFailure(); return; }
    if (res.error) {
      setError(res.error);
      return;
    }
    await fetchAll(token);
  }, [token, fetchAll, surfaceAuthFailure]);

  const handleTriggerRefresh = useCallback(async (mode: 'quick' | 'deep') => {
    if (!token) return;
    setTriggerStatus({ kind: 'busy' });
    const res = await adminFetch<{ ok: boolean }>(`/admin/trigger-refresh?mode=${mode}`, token, { method: 'POST' });
    if (res.status === 503) {
      setTriggerStatus({ kind: 'err', message: t('admin.triggerRefreshDisabled') });
      return;
    }
    if (res.error) {
      setTriggerStatus({ kind: 'err', message: res.error });
      return;
    }
    setTriggerStatus({ kind: 'ok', message: t('admin.triggerRefreshOk') });
  }, [token, t]);

  // ---- ticket workflow ----------------------------------------------------

  const loadTicketDetail = useCallback(async (id: string) => {
    if (!token) return;
    setTicketDetailLoading((s) => ({ ...s, [id]: true }));
    const res = await adminFetch<TicketDetail>(`/admin/feedback/${id}`, token);
    setTicketDetailLoading((s) => ({ ...s, [id]: false }));
    if (res.status === 401) { surfaceAuthFailure(); return; }
    if (res.error) {
      setTicketErrors((s) => ({ ...s, [id]: res.error! }));
      return;
    }
    setTicketDetails((s) => ({ ...s, [id]: res.data }));
  }, [token, surfaceAuthFailure]);

  const handleTicketPatch = useCallback(async (id: string, patch: TicketPatch): Promise<boolean> => {
    if (!token) return false;
    setTicketPending((s) => ({ ...s, [id]: true }));
    setTicketErrors((s) => ({ ...s, [id]: null }));
    const res = await adminFetch(`/admin/feedback/${id}`, token, {
      method: 'PATCH',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(patch),
    });
    if (res.status === 401) {
      setTicketPending((s) => ({ ...s, [id]: false }));
      surfaceAuthFailure();
      return false;
    }
    if (res.error) {
      setTicketErrors((s) => ({ ...s, [id]: res.error! }));
      setTicketPending((s) => ({ ...s, [id]: false }));
      return false;
    }
    // Deliberately ignore the PATCH body and re-read: the list and the event
    // timeline both have to come from the server, so the operator can never be
    // looking at a state the backend did not actually commit.
    await Promise.all([fetchTickets(token, ticketFilters), loadTicketDetail(id)]);
    setTicketPending((s) => ({ ...s, [id]: false }));
    return true;
  }, [token, ticketFilters, fetchTickets, loadTicketDetail, surfaceAuthFailure]);

  const handleTicketReply = useCallback(async (
    id: string,
    reply: string,
    deliver: boolean,
  ): Promise<boolean> => {
    if (!token) return false;
    setReplyPending((s) => ({ ...s, [id]: true }));
    setReplyErrors((s) => ({ ...s, [id]: null }));
    const res = await adminFetch(`/admin/feedback/${id}/reply`, token, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ reply, deliver }),
    });
    if (res.status === 401) {
      setReplyPending((s) => ({ ...s, [id]: false }));
      surfaceAuthFailure();
      return false;
    }
    if (res.error) {
      setReplyErrors((s) => ({ ...s, [id]: res.error! }));
      setReplyPending((s) => ({ ...s, [id]: false }));
      return false;
    }
    await Promise.all([fetchTickets(token, ticketFilters), loadTicketDetail(id)]);
    setReplyPending((s) => ({ ...s, [id]: false }));
    return true;
  }, [token, ticketFilters, fetchTickets, loadTicketDetail, surfaceAuthFailure]);

  const changeTicketFilters = useCallback((f: TicketFilters) => {
    setTicketFilters(f);
    if (token) fetchTickets(token, f);
  }, [token, fetchTickets]);

  // ---- ops queue ----------------------------------------------------------

  const loadOpsDetail = useCallback(async (id: string) => {
    if (!token) return;
    setOpsDetailLoading((s) => ({ ...s, [id]: true }));
    const res = await adminFetch<OpsIncidentDetail>(`/admin/ops/incidents/${id}`, token);
    setOpsDetailLoading((s) => ({ ...s, [id]: false }));
    if (res.status === 401) { surfaceAuthFailure(); return; }
    if (res.error) {
      setOpsErrors((s) => ({ ...s, [id]: res.error! }));
      return;
    }
    setOpsDetails((s) => ({ ...s, [id]: res.data }));
  }, [token, surfaceAuthFailure]);

  const handleOpsPatch = useCallback(async (id: string, patch: OpsPatch): Promise<boolean> => {
    if (!token) return false;
    setOpsPending((s) => ({ ...s, [id]: true }));
    setOpsErrors((s) => ({ ...s, [id]: null }));
    const res = await adminFetch(`/admin/ops/incidents/${id}`, token, {
      method: 'PATCH',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(patch),
    });
    if (res.status === 401) {
      setOpsPending((s) => ({ ...s, [id]: false }));
      surfaceAuthFailure();
      return false;
    }
    if (res.error) {
      setOpsErrors((s) => ({ ...s, [id]: res.error! }));
      setOpsPending((s) => ({ ...s, [id]: false }));
      return false;
    }
    await Promise.all([fetchOps(token, opsFilters), loadOpsDetail(id)]);
    setOpsPending((s) => ({ ...s, [id]: false }));
    return true;
  }, [token, opsFilters, fetchOps, loadOpsDetail, surfaceAuthFailure]);

  const handleOpsRetry = useCallback(async (id: string): Promise<boolean> => {
    if (!token) return false;
    setOpsPending((s) => ({ ...s, [id]: true }));
    setOpsErrors((s) => ({ ...s, [id]: null }));
    const res = await adminFetch(`/admin/ops/incidents/${id}/retry`, token, { method: 'POST' });
    if (res.status === 401) {
      setOpsPending((s) => ({ ...s, [id]: false }));
      surfaceAuthFailure();
      return false;
    }
    if (res.error) {
      setOpsErrors((s) => ({ ...s, [id]: res.error! }));
      setOpsPending((s) => ({ ...s, [id]: false }));
      return false;
    }
    // The POST recorded an ATTEMPT. It says nothing about whether the retry
    // worked — only a detector run can, so we refetch and let the incident
    // speak for itself.
    await Promise.all([fetchOps(token, opsFilters), loadOpsDetail(id)]);
    setOpsPending((s) => ({ ...s, [id]: false }));
    return true;
  }, [token, opsFilters, fetchOps, loadOpsDetail, surfaceAuthFailure]);

  const changeOpsFilters = useCallback((f: OpsFilters) => {
    setOpsFilters(f);
    if (token) fetchOps(token, f);
  }, [token, fetchOps]);

  const previousSnapshot = useMemo(
    () => history.length >= 2 ? history[history.length - 2] : null,
    [history],
  );

  const filteredWorstFields = useMemo(() => {
    if (!data) return [];
    if (!activeFieldFilter) return data.worst_fields;
    return data.worst_fields.filter(w => w.missing_fields?.includes(activeFieldFilter));
  }, [data, activeFieldFilter]);

  const tickets = useMemo<TicketWorkflow>(() => ({
    loadError: ticketLoadError,
    filters: ticketFilters,
    onFiltersChange: changeTicketFilters,
    details: ticketDetails,
    detailLoading: ticketDetailLoading,
    onOpen: loadTicketDetail,
    onPatch: handleTicketPatch,
    onReply: handleTicketReply,
    pending: ticketPending,
    errors: ticketErrors,
    replyPending,
    replyErrors,
  }), [
    ticketLoadError, ticketFilters, changeTicketFilters, ticketDetails, ticketDetailLoading,
    loadTicketDetail, handleTicketPatch, handleTicketReply, ticketPending, ticketErrors,
    replyPending, replyErrors,
  ]);

  const visibleIncidents = useMemo(
    () => applyOpsView(opsIncidents, opsFilters),
    [opsIncidents, opsFilters],
  );

  const ops = useMemo<OpsWorkflow>(() => ({
    incidents: visibleIncidents,
    rollup: opsRollup,
    loaded: opsLoaded,
    error: opsError,
    filters: opsFilters,
    onFiltersChange: changeOpsFilters,
    details: opsDetails,
    detailLoading: opsDetailLoading,
    onOpen: loadOpsDetail,
    onPatch: handleOpsPatch,
    onRetry: handleOpsRetry,
    pending: opsPending,
    errors: opsErrors,
  }), [
    visibleIncidents, opsRollup, opsLoaded, opsError, opsFilters, changeOpsFilters, opsDetails,
    opsDetailLoading, loadOpsDetail, handleOpsPatch, handleOpsRetry, opsPending, opsErrors,
  ]);

  return {
    token,
    tokenInput,
    setTokenInput,
    actor,
    setActor,
    data,
    history,
    collectorStatus,
    collectorHistory,
    health,
    savedSearchHealth,
    feedbackInbox,
    ordersInbox,
    loading,
    error,
    activeFieldFilter,
    setActiveFieldFilter,
    triggerStatus,
    previousSnapshot,
    filteredWorstFields,
    tickets,
    ops,
    fetchAll,
    handleSubmitToken,
    handleLock,
    handleTriggerRefresh,
    handleConfirmOrder,
  };
}
