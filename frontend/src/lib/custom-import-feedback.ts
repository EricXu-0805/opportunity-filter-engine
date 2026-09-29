import type { CustomImportWriteFailureReason } from './custom-imports';

export function customImportFailureKey(reason: CustomImportWriteFailureReason): string {
  const keys: Record<CustomImportWriteFailureReason, string> = {
    owner_changed: 'import.storageOwnerUnavailable', changed: 'import.storageChanged',
    missing: 'import.storageMissing', identity_mismatch: 'import.updateIdentityMismatch',
    storage_failed: 'import.storageFailed', storage_damaged: 'import.storageDamaged',
    coordination_unavailable: 'import.storageCoordinationUnavailable', lock_timeout: 'import.storageBusy',
  };
  return keys[reason];
}

export function canRetryCustomImport(reason: string): boolean {
  return reason === 'storage_failed' || reason === 'lock_timeout' || reason === 'coordination_unavailable';
}
