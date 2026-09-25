import type { Opportunity } from './types';

/** Pass through the server receipt; never derive a replacement from a card. */
export function isWritingTargetVersion(value: unknown): value is string {
  return typeof value === 'string' && /^wt1:[0-9a-f]{64}$/.test(value);
}

export function writingTargetVersion(
  target: Pick<Opportunity, 'writing_target_version'> | null | undefined,
): string | null {
  const value = target?.writing_target_version;
  return isWritingTargetVersion(value) ? value : null;
}
