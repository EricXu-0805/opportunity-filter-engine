"""Which build is actually running — resolved from the environment only.

Why this module exists: the only build identity the API published was
``API_VERSION``, a hand-maintained string that has not been bumped since the
commit that introduced it, so ``"2.7.0"`` says nothing about what code is
serving a request. The single place the real commit appeared was a Sentry
release tag (``backend/lib/observability.py``), and Sentry is DSN-gated —
with no DSN configured the commit was recorded nowhere at all. There was no
way to ask a running instance what SHA it was, which means no way to tell
whether a deploy landed, whether a rollback took effect, or which code
produced a bad response.

Resolution order for the SHA:

1. ``RENDER_GIT_COMMIT`` — injected by Render for the commit it deployed.
   The host's own statement about what it checked out is the strongest
   evidence available from inside the process.
2. ``OFE_RELEASE_SHA`` — an explicit operator override for hosts that do not
   announce the commit themselves (Docker, Fly, a local prod-like run) and
   for the frontend/CI plumbing that shares the same variable name.
3. Nothing → ``None``.

What this module deliberately does NOT do:

* It never synthesizes a placeholder ("dev", "local", "unknown-sha",
  "0000000"). A fabricated SHA is strictly worse than no SHA: it looks like
  provenance while proving nothing, and it would silently satisfy exactly
  the audit this module answers.
* It never shells out to ``git rev-parse``. The deployed artifact has no
  ``.git`` directory (Render builds from a source tarball), so the call
  would fail in the only environment where the answer matters; and where it
  *would* succeed — a developer box, a CI checkout — it reports whatever
  happens to be on disk, not the code this process loaded. That is
  provenance theater, so the fallback is honest ``None`` instead.
* It publishes nothing but build identity. ``build_info`` is served on an
  unauthenticated endpoint, so it may never grow into an environment dump:
  every field below is either a commit SHA, a hard-coded version, a
  host-name label, or this process's start time.

Unknown is represented as ``None`` for the SHA (JSON ``null``) and the
literal string ``"unknown"`` for the environment. Callers must render those
as unknown — never as "fresh", "current", or "production".
"""

from __future__ import annotations

import os
import re
from datetime import UTC, datetime

# The declared API contract version. It describes the shape of the API, not
# the deployed artifact — ``release_sha`` is the only field that identifies
# code. Kept here so ``backend.main`` re-exports one source of truth.
BUILD_VERSION = "2.7.0"

UNKNOWN_ENVIRONMENT = "unknown"

# Environment variables consulted for the commit, in order of trust.
SHA_ENV_VARS: tuple[str, ...] = ("RENDER_GIT_COMMIT", "OFE_RELEASE_SHA")

_SHORT_SHA_LENGTH = 7

# A git commit is hex. Anything else — an empty string, the word "unknown",
# an unexpanded "$RENDER_GIT_COMMIT" template, a branch name — is not a
# build identity and must not be published as one.
_SHA_RE = re.compile(r"^[0-9a-fA-F]{7,40}$")

# Captured once, at import: the moment this process came up. Recomputing it
# per request would report "now" and hide how long the instance has been
# running (and therefore whether a deploy actually restarted it).
_STARTED_AT = datetime.now(UTC)


def _clean(name: str) -> str:
    return (os.environ.get(name) or "").strip()


def release_sha() -> str | None:
    """The full commit SHA of the running build, or ``None`` if unknown."""
    for name in SHA_ENV_VARS:
        candidate = _clean(name)
        if _SHA_RE.match(candidate):
            return candidate.lower()
    return None


def release_sha_short() -> str | None:
    """The first 7 characters of :func:`release_sha`, or ``None``."""
    full = release_sha()
    return full[:_SHORT_SHA_LENGTH] if full else None


def build_version() -> str:
    """The declared API contract version (see :data:`BUILD_VERSION`)."""
    return BUILD_VERSION


def environment() -> str:
    """Where this process is running: a host label, or ``"unknown"``.

    Render sets ``RENDER=true`` in every runtime it starts, so that is the
    ground truth about the host and is consulted first; ``OFE_ENVIRONMENT``
    is the label for hosts that do not identify themselves. Neither is
    interpreted as "production" — this returns what the environment stated,
    never an inference.
    """
    if _clean("RENDER").lower() in {"1", "true", "yes"}:
        return "render"
    return _clean("OFE_ENVIRONMENT") or UNKNOWN_ENVIRONMENT


def started_at() -> str:
    """ISO-8601 UTC timestamp of this process's start."""
    return _STARTED_AT.isoformat()


def health_build_fields() -> dict[str, object]:
    """The build-provenance fields added to ``/api/health``.

    Exactly three keys, all safe to serve unauthenticated. ``status`` and
    ``version`` stay owned by the handler because three existing consumers
    (frontend ``wakeBackend``, the Playwright ``webServer`` readiness gate,
    and ``tests/test_async_route_isolation``) depend on their current shape.
    """
    return {
        "release_sha": release_sha(),
        "environment": environment(),
        "started_at": started_at(),
    }


def build_info() -> dict[str, object]:
    """The complete build identity record, unknowns included."""
    return {
        "release_sha": release_sha(),
        "release_sha_short": release_sha_short(),
        "build_version": build_version(),
        "environment": environment(),
        "started_at": started_at(),
    }
