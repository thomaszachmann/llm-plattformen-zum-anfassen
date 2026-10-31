"""Fehlerbudget aus Prometheus: Anteil 5xx an allen Gateway-Anfragen."""

import math
import re

import httpx

_TENANT = re.compile(r"^[a-z0-9-]+$")
_WINDOW = re.compile(r"^[0-9]+[smhdwy]$")


def error_ratio_query(window: str, tenant: str | None = None) -> str:
    # Eingaben validieren: kein PromQL-Injection über --tenant/--window
    if not _WINDOW.match(window):
        raise ValueError(f"ungültiges Fenster: {window!r}")
    if tenant is not None and not _TENANT.match(tenant):
        raise ValueError(f"ungültiger Mandant: {tenant!r}")
    sel = f'tenant="{tenant}"' if tenant else 'tenant!="unknown"'
    bad = f'sum(increase(gateway_requests_total{{{sel},code=~"5.."}}[{window}]))'
    total = f"sum(increase(gateway_requests_total{{{sel}}}[{window}]))"
    return f"{bad} / {total}"


def query_scalar(client: httpx.Client, promql: str) -> float | None:
    """Instant Query gegen /api/v1/query; None, wenn es keine Daten gibt."""
    resp = client.get("/api/v1/query", params={"query": promql})
    resp.raise_for_status()
    body = resp.json()
    if body.get("status") != "success":
        raise RuntimeError(body.get("error", "Prometheus-Fehler"))
    result = body["data"]["result"]
    if not result:
        return None
    value = float(result[0]["value"][1])
    return None if math.isnan(value) else value


def budget_remaining(error_ratio: float, objective: float) -> float:
    """1.0 = Budget unberührt, 0.0 = aufgebraucht, < 0 = SLO verletzt."""
    return 1 - error_ratio / (1 - objective)
