import type { PrivateImportTarget } from './private-import-target-api';
import type { ImportSourceInfo } from './import-source';

export function privateImportErrorKey(code: string): string {
  const keys: Record<string, string> = {
    sign_in_required: 'privateImport.signInRequired', owner_changed: 'privateImport.ownerChanged',
    conflict: 'privateImport.conflict', changed: 'privateImport.conflict', deleted: 'privateImport.deleted', not_found: 'privateImport.missing',
    too_large: 'privateImport.tooLarge', invalid_input: 'privateImport.invalidInput',
    invalid_receipt: 'privateImport.unavailable', unavailable: 'privateImport.unavailable',
    timeout: 'privateImport.timeout', aborted: 'privateImport.interrupted',
    local_changed: 'privateImport.localChanged', local_missing: 'privateImport.localMissing',
    storage_damaged: 'import.storageDamaged', storage_unavailable: 'import.storageFailed',
  };
  return keys[code] ?? 'privateImport.unavailable';
}

// The validated cloud receipt, not arbitrary old raw metadata, defines this label.
export function privateImportSourceInfo(target: PrivateImportTarget): ImportSourceInfo {
  return { source: target.import_source?.description_source ?? 'unknown',
    aiInputScope: target.import_source?.ai_input_scope ?? 'unknown' };
}

export function privateImportSourceUrl(value: { source_url?: string; url?: string }): string | null {
  try {
    const parsed = new URL(value.source_url || value.url || '');
    return ['http:', 'https:'].includes(parsed.protocol) && !parsed.username && !parsed.password ? parsed.href : null;
  } catch { return null; }
}
