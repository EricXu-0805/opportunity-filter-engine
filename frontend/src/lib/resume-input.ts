// Keep the accepted raw-text limit aligned with backend/lib/resume_input.py.
// Count Unicode code points, matching Pydantic/Python, rather than UTF-16 units.
export const MAX_RESUME_TEXT_CHARACTERS = 60_000;
export const RESUME_AI_CHUNK_CHARACTERS = 8_000;

export function resumeTextCharacters(text: string): number {
  return Array.from(text).length;
}
