"""Einstiegspunkt: llmctl chat | load | slo."""

import argparse
import asyncio
import json
import logging
import os
import sys

import httpx

from llmctl import __version__, logs
from llmctl.load import run_load
from llmctl.retry import TIMEOUT, send
from llmctl.slo import budget_remaining, error_ratio_query, query_scalar

log = logging.getLogger("llmctl")


def positive_int(text: str) -> int:
    value = int(text)
    if value < 1:
        raise argparse.ArgumentTypeError("muss >= 1 sein")
    return value


def objective(text: str) -> float:
    value = float(text)
    if not 0 < value < 1:
        raise argparse.ArgumentTypeError("muss zwischen 0 und 1 liegen, z. B. 0.995")
    return value


def build_parser() -> argparse.ArgumentParser:
    env = os.environ.get
    p = argparse.ArgumentParser(prog="llmctl", description="SRE-CLI für llm-gateway")
    p.add_argument("--version", action="version", version=f"llmctl {__version__}")
    p.add_argument("--url", default=env("LLMCTL_URL", "http://127.0.0.1:8080"))
    p.add_argument("--model", default=env("LLMCTL_MODEL", "mistral"))
    p.add_argument("-v", "--verbose", action="store_true")
    sub = p.add_subparsers(dest="cmd", required=True)

    chat = sub.add_parser("chat", help="eine Anfrage über das Gateway")
    chat.add_argument("prompt")
    chat.add_argument("--max-tokens", type=positive_int, default=256)
    chat.add_argument("--retries", type=int, default=3)

    load = sub.add_parser("load", help="Lasttest mit Latenz-Perzentilen")
    load.add_argument("-n", "--requests", type=positive_int, default=20)
    load.add_argument("-c", "--concurrency", type=positive_int, default=5)
    load.add_argument("--max-tokens", type=positive_int, default=16)
    load.add_argument("--json", action="store_true", help="Ergebnis als JSON")

    slo = sub.add_parser("slo", help="Fehlerbudget aus Prometheus")
    slo.add_argument("--prometheus", default=env("PROM_URL", "http://127.0.0.1:9090"))
    slo.add_argument("--objective", type=objective, default=0.995)
    slo.add_argument("--window", default="28d")
    slo.add_argument("--tenant")
    return p


def payload(args: argparse.Namespace, prompt: str) -> dict:
    return {
        "model": args.model,
        "messages": [{"role": "user", "content": prompt}],
        "max_tokens": args.max_tokens,
    }


def auth_headers() -> dict[str, str]:
    key = os.environ.get("LLMCTL_API_KEY", "")
    if not key:
        raise SystemExit("LLMCTL_API_KEY ist nicht gesetzt")
    return {"Authorization": f"Bearer {key}"}  # Key nie loggen


def cmd_chat(args, transport=None) -> int:
    with httpx.Client(
        base_url=args.url, headers=auth_headers(), timeout=TIMEOUT, transport=transport
    ) as client:
        resp = send(
            client,
            "POST",
            "/v1/chat/completions",
            json=payload(args, args.prompt),
            retries=args.retries,
        )
    if resp.status_code != 200:
        log.error("chat failed", extra={"status": resp.status_code, "body": resp.text})
        return 1
    body = resp.json()
    print(body["choices"][0]["message"]["content"])
    log.info("chat ok", extra={"usage": body.get("usage", {})})
    return 0


def cmd_load(args, transport=None) -> int:
    async def go():
        async with httpx.AsyncClient(
            base_url=args.url,
            headers=auth_headers(),
            timeout=TIMEOUT,
            transport=transport,
            limits=httpx.Limits(max_connections=args.concurrency),
        ) as client:
            return await run_load(
                client, payload(args, "Sag nur: ok"), args.requests, args.concurrency
            )

    s = asyncio.run(go()).summary()
    if args.json:
        print(json.dumps(s))
    else:
        print(
            f"requests={s['requests']} errors={s['errors']} "
            f"error_rate={s['error_rate']:.1%} rps={s['rps']}"
        )
        print(f"p50={s['p50_s']}s p95={s['p95_s']}s p99={s['p99_s']}s")
        print("codes: " + " ".join(f"{k}={v}" for k, v in s["codes"].items()))
    return 1 if s["errors"] else 0


def cmd_slo(args, transport=None) -> int:
    promql = error_ratio_query(args.window, args.tenant)
    log.debug("promql", extra={"query": promql})
    with httpx.Client(
        base_url=args.prometheus, timeout=10.0, transport=transport
    ) as client:
        ratio = query_scalar(client, promql)
    if ratio is None:
        print("keine Daten im Fenster – Gateway gescrapt?")
        return 3
    left = budget_remaining(ratio, args.objective)
    print(
        f"SLO {args.objective * 100:g}% über {args.window} "
        f"(Mandant: {args.tenant or 'alle'})"
    )
    print(f"Fehlerquote:    {ratio:.3%}")
    print(f"Budget erlaubt: {1 - args.objective:.3%}")
    print(f"Budget übrig:   {left:.1%}")
    return 0 if left >= 0 else 2


def main(argv: list[str] | None = None, transport=None) -> int:
    args = build_parser().parse_args(argv)
    logs.setup(args.verbose)
    commands = {"chat": cmd_chat, "load": cmd_load, "slo": cmd_slo}
    try:
        return commands[args.cmd](args, transport)
    except (httpx.HTTPError, ValueError, RuntimeError, KeyError, IndexError) as exc:
        log.error("failed", extra={"error": f"{type(exc).__name__}: {exc}"})
        return 1


if __name__ == "__main__":
    sys.exit(main())
