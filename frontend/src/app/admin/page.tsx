'use client';

import { Suspense } from 'react';
import { useT } from '@/i18n/client';

import { AdminDashboard } from './AdminDashboard';
import { AdminLoginForm } from './AdminLoginForm';
import { useAdminData } from './use-admin-data';

export default function AdminPage() {
  return (
    <Suspense fallback={null}>
      <AdminInner />
    </Suspense>
  );
}

function AdminInner() {
  const { t } = useT();
  const {
    token,
    tokenInput,
    setTokenInput,
    data,
    history,
    collectorStatus,
    collectorHistory,
    health,
    savedSearchHealth,
    conciergeQueue,
    feedbackInbox,
    ordersInbox,
    tickets,
    ops,
    actor,
    setActor,
    loading,
    error,
    adminDisabled,
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
  } = useAdminData(t);

  if (!token) {
    return (
      <AdminLoginForm
        tokenInput={tokenInput}
        setTokenInput={setTokenInput}
        onSubmit={handleSubmitToken}
        loading={loading}
        error={error}
        t={t}
      />
    );
  }

  return (
    <AdminDashboard
      adminDisabled={adminDisabled}
      data={data}
      history={history}
      collectorStatus={collectorStatus}
      collectorHistory={collectorHistory}
      health={health}
      savedSearchHealth={savedSearchHealth}
      conciergeQueue={conciergeQueue}
      feedbackInbox={feedbackInbox}
      ordersInbox={ordersInbox}
      tickets={tickets}
      ops={ops}
      actor={actor}
      onActorChange={setActor}
      loading={loading}
      error={error}
      activeFieldFilter={activeFieldFilter}
      setActiveFieldFilter={setActiveFieldFilter}
      triggerStatus={triggerStatus}
      previousSnapshot={previousSnapshot}
      filteredWorstFields={filteredWorstFields}
      onRefresh={() => fetchAll(token)}
      onLock={handleLock}
      onTriggerRefresh={handleTriggerRefresh}
      onConfirmOrder={handleConfirmOrder}
      t={t}
    />
  );
}
