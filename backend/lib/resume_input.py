"""Bounds for stored resume text and the separate, selective AI projection."""

# Unicode code points, matching frontend/src/lib/resume-input.ts.
MAX_RESUME_TEXT_CHARACTERS = 60_000
RESUME_AI_CHUNK_CHARACTERS = 8_000
RESUME_AI_MAX_CHUNKS = 8
RESUME_AI_CONCURRENCY = 2
RESUME_AI_TIME_BUDGET_SECONDS = 45.0


def resume_chunks(text: str) -> list[tuple[int, int, str]]:
    """Cover every character in at most eight bounded, non-overlapping chunks.

    Prefer a line boundary within the last 500 characters. Advancing by at
    least 7,500 keeps 60,000 characters within eight chunks. Offsets refer to
    the original text; joining the chunk text must reproduce it exactly.
    """
    if len(text) > MAX_RESUME_TEXT_CHARACTERS:
        raise ValueError("resume text exceeds 60,000 characters")
    chunks: list[tuple[int, int, str]] = []
    start = 0
    while start < len(text):
        end = min(start + RESUME_AI_CHUNK_CHARACTERS, len(text))
        if end < len(text):
            boundary = text.rfind("\n", start + 7_499, end)
            if boundary >= 0:
                end = boundary + 1
        chunks.append((start, end, text[start:end]))
        start = end
    return chunks
