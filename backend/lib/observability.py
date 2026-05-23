"""Optional Sentry wiring for the FastAPI backend.

Activated only when ``SENTRY_DSN`` is set in the environment, so dev /
CI / local-only deploys stay fully offline. The function returns
``True`` when Sentry was actually initialized so callers (and tests)
can branch on it; everything else is a graceful no-op.

Operator setup (one-time):

  1. Create a Python project at https://sentry.io and copy its DSN.
  2. On Render → backend service → Environment, set:
       SENTRY_DSN=https://<key>@oN.ingest.sentry.io/<id>
       SENTRY_ENVIRONMENT=production   (optional; defaults to "production")
       SENTRY_TRACES_SAMPLE_RATE=0.1   (optional; 0.0-1.0; default 0.1)
  3. Trigger a redeploy. The next 5xx will land in Sentry.

No PII is sent: ``send_default_pii=False`` masks request bodies, IP
addresses, and cookies, which matters because the cold-email + matches
endpoints take student profile payloads.
"""

from __future__ import annotations

import logging
import os

logger = logging.getLogger(__name__)


def init_sentry() -> bool:
    """Initialize Sentry if SENTRY_DSN is set; otherwise no-op.

    Idempotent: safe to call multiple times. Returns ``True`` iff
    ``sentry_sdk.init`` was actually invoked.
    """
    dsn = (os.environ.get("SENTRY_DSN") or "").strip()
    if not dsn:
        logger.info("Sentry disabled (SENTRY_DSN unset).")
        return False

    try:
        import sentry_sdk
    except ImportError:
        logger.warning("SENTRY_DSN is set but sentry-sdk is not installed; skipping.")
        return False

    environment = os.environ.get("SENTRY_ENVIRONMENT", "production").strip() or "production"

    try:
        traces_sample_rate = float(os.environ.get("SENTRY_TRACES_SAMPLE_RATE", "0.1"))
    except ValueError:
        traces_sample_rate = 0.1
    traces_sample_rate = max(0.0, min(1.0, traces_sample_rate))

    release = os.environ.get("SENTRY_RELEASE") or os.environ.get("RENDER_GIT_COMMIT")

    sentry_sdk.init(
        dsn=dsn,
        environment=environment,
        traces_sample_rate=traces_sample_rate,
        release=release,
        send_default_pii=False,
        attach_stacktrace=False,
        max_breadcrumbs=50,
    )
    logger.info(
        "Sentry initialized (environment=%s, traces_sample_rate=%.2f, release=%s).",
        environment,
        traces_sample_rate,
        release or "unset",
    )
    return True
