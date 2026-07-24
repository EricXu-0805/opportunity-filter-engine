"""Fail-closed Web Push delivery for persisted, user-controlled endpoints.

The endpoint stored in a PushSubscription is not a trusted service URL: a
client can persist an arbitrary value and the reminder cron consumes it later.
Validate it immediately before delivery, disable redirects/proxy inheritance,
and bound the synchronous ``pywebpush`` call outside the event-loop thread.
"""

from __future__ import annotations

import asyncio
import ipaddress
import socket
from collections.abc import Callable, Mapping
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from functools import partial
from typing import Any
from urllib.parse import urlsplit

import requests
from requests.adapters import HTTPAdapter
from requests.models import PreparedRequest

MAX_PUSH_ENDPOINT_BYTES = 2048
WEBPUSH_CONNECT_TIMEOUT_SECONDS = 3.0
WEBPUSH_READ_TIMEOUT_SECONDS = 5.0
WEBPUSH_TOTAL_TIMEOUT_SECONDS = 10.0

# Keep blocking DNS + requests work out of FastAPI's event-loop thread.  The
# pool is intentionally bounded: a provider outage cannot create unbounded
# worker growth, while the requests timeout still releases active workers.
_WEBPUSH_EXECUTOR = ThreadPoolExecutor(max_workers=4, thread_name_prefix="safe-webpush")


class UnsafePushEndpointError(ValueError):
    """A subscription endpoint did not pass the outbound-network policy.

    ``reason`` is a low-cardinality code suitable for metrics.  The exception
    text deliberately excludes the attacker-controlled URL and resolved IPs.
    """

    def __init__(self, reason: str):
        self.reason = reason
        super().__init__("push endpoint rejected by outbound-network policy")


class WebPushDeliveryTimeout(TimeoutError):
    """The end-to-end delivery deadline expired."""


@dataclass(frozen=True)
class ValidatedPushEndpoint:
    endpoint: str
    hostname: str
    port: int
    addresses: tuple[str, ...]


Resolver = Callable[..., list[tuple[Any, ...]]]
WebPushCallable = Callable[..., Any]


def _reject(reason: str) -> None:
    raise UnsafePushEndpointError(reason)


def _normalise_hostname(hostname: str) -> str:
    host = hostname.rstrip(".").lower()
    if not host:
        _reject("missing_hostname")
    try:
        ascii_host = host.encode("idna").decode("ascii")
    except UnicodeError:
        _reject("invalid_hostname")
    if len(ascii_host) > 253:
        _reject("invalid_hostname")
    return ascii_host


def _is_disallowed_name(hostname: str) -> bool:
    return (
        hostname == "localhost"
        or hostname.endswith(".localhost")
        or hostname.endswith(".local")
        or hostname.endswith(".localdomain")
        or hostname.endswith(".internal")
        or hostname.endswith(".home")
        or hostname.endswith(".lan")
    )


def validate_push_endpoint(
    endpoint: object,
    *,
    resolver: Resolver | None = None,
) -> ValidatedPushEndpoint:
    """Validate a Web Push endpoint and all of its current A/AAAA answers.

    DNS is fail-closed: an empty/unresolvable hostname is rejected, and every
    returned address must be globally routable.  This includes rejecting
    loopback, RFC1918/private, link-local/cloud-metadata, reserved, multicast,
    and unspecified IPv4/IPv6 addresses.
    """

    if not isinstance(endpoint, str) or not endpoint or endpoint != endpoint.strip():
        _reject("invalid_endpoint")
    try:
        endpoint_bytes = endpoint.encode("utf-8")
    except UnicodeError:
        _reject("invalid_endpoint")
    if len(endpoint_bytes) > MAX_PUSH_ENDPOINT_BYTES:
        _reject("endpoint_too_long")
    if any(ord(character) < 0x20 or ord(character) == 0x7F for character in endpoint):
        _reject("invalid_endpoint")

    try:
        parsed = urlsplit(endpoint)
        port = parsed.port or 443
    except ValueError:
        _reject("invalid_endpoint")

    if parsed.scheme.lower() != "https":
        _reject("https_required")
    if not parsed.netloc or parsed.hostname is None:
        _reject("missing_hostname")
    if parsed.username is not None or parsed.password is not None:
        _reject("userinfo_not_allowed")
    if parsed.fragment:
        _reject("fragment_not_allowed")

    hostname = _normalise_hostname(parsed.hostname)
    if _is_disallowed_name(hostname):
        _reject("disallowed_hostname")

    resolve = resolver or socket.getaddrinfo
    try:
        answers = resolve(
            hostname,
            port,
            family=socket.AF_UNSPEC,
            type=socket.SOCK_STREAM,
            proto=socket.IPPROTO_TCP,
        )
    except (OSError, UnicodeError):
        _reject("dns_resolution_failed")

    addresses: list[str] = []
    for answer in answers:
        try:
            address = answer[4][0]
            ip = ipaddress.ip_address(address)
        except (IndexError, TypeError, ValueError):
            _reject("dns_resolution_failed")
        if not ip.is_global:
            _reject("non_public_address")
        canonical = str(ip)
        if canonical not in addresses:
            addresses.append(canonical)

    if not addresses:
        _reject("dns_resolution_failed")

    return ValidatedPushEndpoint(
        endpoint=endpoint,
        hostname=hostname,
        port=port,
        addresses=tuple(addresses),
    )


class _PinnedHTTPSAdapter(HTTPAdapter):
    """Connect to a validated IP while verifying the logical HTTPS origin.

    Replacing only the urllib3 pool host closes the validate-then-resolve DNS
    rebinding race.  ``server_hostname`` and ``assert_hostname`` preserve TLS
    SNI and certificate verification against the original push-service host.
    """

    def __init__(self, endpoint: ValidatedPushEndpoint):
        self._endpoint = endpoint
        super().__init__(max_retries=0)

    def _assert_same_origin(self, request: PreparedRequest) -> None:
        try:
            parsed = urlsplit(request.url or "")
            hostname = _normalise_hostname(parsed.hostname or "")
            port = parsed.port or 443
        except (UnsafePushEndpointError, ValueError) as exc:
            raise ValueError("request origin does not match validated push endpoint") from exc
        if (
            parsed.scheme.lower() != "https"
            or hostname != self._endpoint.hostname
            or port != self._endpoint.port
        ):
            raise ValueError("request origin does not match validated push endpoint")

    def build_connection_pool_key_attributes(self, request, verify, cert=None):  # noqa: ANN001, ANN201
        self._assert_same_origin(request)
        host_params, pool_kwargs = super().build_connection_pool_key_attributes(
            request,
            verify,
            cert,
        )
        host_params["host"] = self._endpoint.addresses[0]
        host_params["port"] = self._endpoint.port
        pool_kwargs["server_hostname"] = self._endpoint.hostname
        pool_kwargs["assert_hostname"] = self._endpoint.hostname
        return host_params, pool_kwargs

    def add_headers(self, request, *args, **kwargs):  # noqa: ANN001, ANN201
        super().add_headers(request, *args, **kwargs)
        try:
            logical_ip = ipaddress.ip_address(self._endpoint.hostname)
        except ValueError:
            host = self._endpoint.hostname
        else:
            host = f"[{logical_ip}]" if logical_ip.version == 6 else str(logical_ip)
        if self._endpoint.port != 443:
            host = f"{host}:{self._endpoint.port}"
        request.headers["Host"] = host


class _NoRedirectSession(requests.Session):
    """No-proxy/no-redirect session pinned to one validated HTTPS origin."""

    def __init__(self, endpoint: ValidatedPushEndpoint):
        super().__init__()
        self.trust_env = False
        self.max_redirects = 0
        self.mount("https://", _PinnedHTTPSAdapter(endpoint))

    def request(self, method, url, *args, **kwargs):  # noqa: ANN001, ANN201
        kwargs["allow_redirects"] = False
        return super().request(method, url, *args, **kwargs)


def _perform_webpush(
    *,
    endpoint: ValidatedPushEndpoint,
    webpush_func: WebPushCallable,
    subscription_info: Mapping[str, Any],
    data: str,
    vapid_private_key: str,
    vapid_claims: Mapping[str, str | int],
) -> Any:
    # pywebpush uses requests synchronously.  Never inherit HTTP(S)_PROXY from
    # the process: a proxy can invalidate direct-destination SSRF checks.  TLS
    # verification remains at requests' secure default.
    with _NoRedirectSession(endpoint) as session:
        return webpush_func(
            subscription_info=dict(subscription_info),
            data=data,
            vapid_private_key=vapid_private_key,
            # pywebpush mutates claims (aud/exp), so isolate every recipient.
            vapid_claims=dict(vapid_claims),
            timeout=(WEBPUSH_CONNECT_TIMEOUT_SECONDS, WEBPUSH_READ_TIMEOUT_SECONDS),
            requests_session=session,
        )


async def send_webpush_safely(
    *,
    subscription_info: Mapping[str, Any],
    data: str,
    vapid_private_key: str,
    vapid_claims: Mapping[str, str | int],
    webpush_func: WebPushCallable,
    resolver: Resolver | None = None,
    total_timeout: float = WEBPUSH_TOTAL_TIMEOUT_SECONDS,
) -> Any:
    """Validate and deliver one push within an end-to-end wall-clock budget."""

    endpoint = subscription_info.get("endpoint")
    loop = asyncio.get_running_loop()

    async def operation() -> Any:
        # Resolve immediately before pywebpush.  Resolver errors and empty
        # answers are rejected rather than delegated to requests (fail closed).
        validated = await loop.run_in_executor(
            _WEBPUSH_EXECUTOR,
            partial(validate_push_endpoint, endpoint, resolver=resolver),
        )
        return await loop.run_in_executor(
            _WEBPUSH_EXECUTOR,
            partial(
                _perform_webpush,
                endpoint=validated,
                webpush_func=webpush_func,
                subscription_info=subscription_info,
                data=data,
                vapid_private_key=vapid_private_key,
                vapid_claims=vapid_claims,
            ),
        )

    try:
        return await asyncio.wait_for(operation(), timeout=total_timeout)
    except TimeoutError as exc:
        raise WebPushDeliveryTimeout("web push delivery deadline exceeded") from exc
