'use client';

import { useCallback, useEffect, useMemo, useState } from 'react';
import { useSearchParams } from 'next/navigation';
import { RELEASE_SCOPE } from '@/lib/release-scope';
import { adminFetch, SESSION_KEY } from './admin-api';
import type {
  AdminResponse,
  CollectorHistoryEntry,
  CollectorStatus,
  FieldKey,
  HealthResponse,
  HistoryEntry,
  FeedbackInbox,
  OrdersInbox,
  SavedSearchHealth,
  TFunc,
  TriggerStatus,
} from './types';

export interface UseAdminDataResult {
  token: string;
  tokenInput: string;
  setTokenInput: (v: string) => void;
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

  const fetchAll = useCallback(async (tok: string) => {
    if (!tok) return;
    setLoading(true);
    setError(null);
    try {
      const [main, hist, healthR, collector, collectorHist, ssHealth, fbInbox] = await Promise.all([
        adminFetch<AdminResponse>(`/admin/data-quality`, tok),
        adminFetch<{ history: HistoryEntry[] }>(`/admin/data-quality/history?limit=30`, tok),
        adminFetch<HealthResponse>(`/admin/health-check`, tok),
        adminFetch<CollectorStatus>(`/admin/collector-status`, tok),
        adminFetch<{ entries: CollectorHistoryEntry[]; count: number }>(`/admin/collector-status/history?limit=30`, tok),
        adminFetch<SavedSearchHealth>(`/admin/saved-search-health`, tok),
        adminFetch<FeedbackInbox>(`/admin/feedback?limit=50`, tok),
      ]);
      const ordInbox = RELEASE_SCOPE.payments
        ? await adminFetch<OrdersInbox>(`/admin/orders?limit=50`, tok)
        : null;
      if (main.status === 401) {
        setError('Invalid admin token');
        sessionStorage.removeItem(SESSION_KEY);
        setToken('');
        setData(null);
        return;
      }
      if (main.status === 503) {
        setError('Admin endpoints disabled — ADMIN_TOKEN not set on backend');
        setData(null);
        return;
      }
      if (main.error) {
        setError(main.error);
        setData(null);
        return;
      }
      setData(main.data ?? null);
      setHistory(hist.data?.history ?? []);
      setHealth(healthR.data ?? null);
      setCollectorStatus(collector.data ?? null);
      setCollectorHistory(collectorHist.data?.entries ?? []);
      setSavedSearchHealth(ssHealth.data ?? null);
      setFeedbackInbox(fbInbox.data ?? null);
      setOrdersInbox(ordInbox?.data ?? null);
    } finally {
      setLoading(false);
    }
  }, []);

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
    if (resolved) {
      /* eslint-disable react-hooks/set-state-in-effect --
         Auth token resolution must finish in one effect tick so the
         token-entry form is replaced atomically by the dashboard. */
      setToken(resolved);
      setTokenInput(resolved);
      /* eslint-enable react-hooks/set-state-in-effect */
      fetchAll(resolved);
    }
  }, [searchParams, fetchAll]);

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
    setError(null);
  }, []);

  const handleConfirmOrder = useCallback(async (id: string) => {
    if (!token || !RELEASE_SCOPE.payments) return;
    const res = await adminFetch(`/admin/orders/${id}/confirm`, token, { method: 'POST' });
    if (res.error) {
      setError(res.error);
      return;
    }
    await fetchAll(token);
  }, [token, fetchAll]);

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

  const previousSnapshot = useMemo(
    () => history.length >= 2 ? history[history.length - 2] : null,
    [history],
  );

  const filteredWorstFields = useMemo(() => {
    if (!data) return [];
    if (!activeFieldFilter) return data.worst_fields;
    return data.worst_fields.filter(w => w.missing_fields?.includes(activeFieldFilter));
  }, [data, activeFieldFilter]);

  return {
    token,
    tokenInput,
    setTokenInput,
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
    fetchAll,
    handleSubmitToken,
    handleLock,
    handleTriggerRefresh,
    handleConfirmOrder,
  };
}
