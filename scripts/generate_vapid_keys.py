"""Generate a VAPID keypair for Web Push.

Usage:
    pip install pywebpush
    python scripts/generate_vapid_keys.py

Prints env vars to paste into Vercel + backend hosting env.
"""
from __future__ import annotations

import base64
import sys


def main() -> int:
    try:
        from cryptography.hazmat.primitives.asymmetric import ec
        from cryptography.hazmat.primitives import serialization
    except ImportError:
        print("Missing `cryptography`. Install with: pip install cryptography", file=sys.stderr)
        return 1

    private_key = ec.generate_private_key(ec.SECP256R1())
    public_key = private_key.public_key()

    priv_pem = private_key.private_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PrivateFormat.PKCS8,
        encryption_algorithm=serialization.NoEncryption(),
    ).decode("ascii")

    pub_raw = public_key.public_bytes(
        encoding=serialization.Encoding.X962,
        format=serialization.PublicFormat.UncompressedPoint,
    )
    pub_b64 = base64.urlsafe_b64encode(pub_raw).rstrip(b"=").decode("ascii")

    print()
    print("=" * 68)
    print("VAPID keypair generated.")
    print("=" * 68)
    print()
    print("# Backend env (Python host running /api/cron/reminders):")
    print(f"VAPID_PRIVATE_KEY=<<<paste PEM below>>>")
    print(f"VAPID_PUBLIC_KEY={pub_b64}")
    print(f"VAPID_SUBJECT=mailto:your-email@example.com")
    print()
    print("# Frontend env (Vercel — public, used by service worker):")
    print(f"NEXT_PUBLIC_VAPID_PUBLIC_KEY={pub_b64}")
    print()
    print("# VAPID_PRIVATE_KEY (PEM, paste as a single-line or quoted multi-line env):")
    print("-" * 68)
    print(priv_pem.strip())
    print("-" * 68)
    print()
    print("Save these in your password manager. The private key must stay secret.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
