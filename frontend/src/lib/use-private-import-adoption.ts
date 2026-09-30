'use client';

import { useEffect, useMemo, useSyncExternalStore } from 'react';
import { createPrivateImportAdoptionController, type PrivateImportAdoptionState } from './private-import-adoption';
export type { PrivateImportAdoptionState, PrivateImportAdoptionReview, PrivateImportAdoptionError } from './private-import-adoption';
const EMPTY: PrivateImportAdoptionState = Object.freeze({ status: 'idle' });

/** Opening a page only subscribes. prepare/confirm require explicit UI actions. */
export function usePrivateImportAdoption() {
  const controller = useMemo(() => createPrivateImportAdoptionController(), []);
  const state = useSyncExternalStore(controller.subscribe, controller.getState, () => EMPTY);
  useEffect(() => () => { controller.cancel(); }, [controller]);
  return { state, prepare: controller.prepare, confirm: controller.confirm, cancel: controller.cancel, startNewCopy: controller.startNewCopy };
}
