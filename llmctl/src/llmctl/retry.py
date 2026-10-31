"""HTTP-Aufrufe mit Retries: exponentielles Backoff, Full Jitter, Retry-After."""

import logging
import random
import time
from collections.abc import Callable

import httpx

log = logging.getLogger(__name__)

RETRY_STATUS = {429, 502, 503, 504}
TIMEOUT = httpx.Timeout(60.0, connect=3.0)  # Generierung dauert, Connect nicht


def backoff(attempt: int, base: float = 0.5, cap: float = 8.0) -> float:
    """Full Jitter: zufällig zwischen 0 und min(cap, base * 2**attempt)."""
    return random.uniform(0, min(cap, base * 2**attempt))


def retry_after(resp: httpx.Response) -> float | None:
    """Retry-After in Sekunden; HTTP-Datumsangaben ignorieren wir bewusst."""
    try:
        return max(0.0, float(resp.headers.get("Retry-After", "")))
    except ValueError:
        return None


def send(
    client: httpx.Client,
    method: str,
    url: str,
    *,
    retries: int = 3,
    sleep: Callable[[float], None] = time.sleep,
    **kwargs,
) -> httpx.Response:
    for attempt in range(retries + 1):
        try:
            resp = client.request(method, url, **kwargs)
        except httpx.TransportError as exc:  # Connect-Fehler, Timeouts
            if attempt == retries:
                raise
            wait, reason = backoff(attempt), type(exc).__name__
        else:
            if resp.status_code not in RETRY_STATUS or attempt == retries:
                return resp
            ra = retry_after(resp)
            wait = ra if ra is not None else backoff(attempt)
            reason = str(resp.status_code)
        log.warning(
            "retry",
            extra={"attempt": attempt + 1, "reason": reason, "sleep_s": round(wait, 3)},
        )
        sleep(wait)
    raise AssertionError("unreachable")
