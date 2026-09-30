/** Slightly above the server's default three-minute, multi-stage deadline. */
export const COLD_EMAIL_STREAM_TIMEOUT_MS = 195_000;
export type ColdEmailStreamFailure = 'timeout' | 'cancelled' | 'unsupported' | 'http_error' | 'invalid_response' | 'network_error' | 'WRITING_TARGET_CHANGED' | 'EMAIL_CONTACT_INSTRUCTIONS' | 'EMAIL_READING_CHANGED' | 'EMAIL_INPUT_TOO_LARGE';
export class ColdEmailStreamError extends Error {
  constructor(public readonly code: ColdEmailStreamFailure, public readonly status?: number) {
    super(code === 'timeout' ? 'Email generation took too long. Your draft is kept. Try again when ready.'
      : code === 'WRITING_TARGET_CHANGED' ? 'This opportunity changed. Your draft is kept. Check it again before continuing.'
      : code === 'EMAIL_CONTACT_INSTRUCTIONS' ? 'Check the current contact instructions. Your draft is kept.'
      : code === 'EMAIL_READING_CHANGED' ? 'Check your reading selection against this opportunity. Your draft is kept.'
      : code === 'EMAIL_INPUT_TOO_LARGE' ? emailInputTooLargeMessage('en')
      : code === 'cancelled' ? 'Email generation was cancelled.'
        : 'Email generation could not be completed. Your draft is kept.');
    this.name = 'ColdEmailStreamError';
  }
}
/** Only a definite missing/unsupported endpoint permits a compatibility POST.
 * A disconnect, timeout or malformed result may already have spent model work. */
export function canFallbackColdEmailStream(error: unknown): boolean {
  return error instanceof ColdEmailStreamError && error.code === 'unsupported'
    && (error.status === 404 || error.status === 405);
}

export function isEmailInputTooLarge(error: unknown): boolean {
  return !!error && typeof error === 'object' && 'code' in error && error.code === 'EMAIL_INPUT_TOO_LARGE';
}
export function emailInputTooLargeMessage(locale: string): string {
  return locale === 'zh'
    ? '用于写邮件的资料和修改要求合计太长。请减少本次选用的内容后重试；原稿和要求已保留。'
    : 'The selected email material and edit request are too long together. Reduce the selected content and try again. Your draft and request are kept.';
}
