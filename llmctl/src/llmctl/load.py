"""Lastgenerator: N Anfragen mit begrenzter Parallelität, Latenz-Perzentile."""

import asyncio
import math
import time
from collections import Counter
from dataclasses import dataclass, field

import httpx


@dataclass
class Result:
    latencies: list[float] = field(default_factory=list)
    codes: Counter = field(default_factory=Counter)
    elapsed: float = 0.0

    @property
    def total(self) -> int:
        return sum(self.codes.values())

    @property
    def errors(self) -> int:
        return sum(n for c, n in self.codes.items() if not str(c).startswith("2"))

    def summary(self) -> dict:
        lat = self.latencies
        return {
            "requests": self.total,
            "errors": self.errors,
            "error_rate": round(self.errors / self.total, 4) if self.total else 0.0,
            "rps": round(self.total / self.elapsed, 2) if self.elapsed else 0.0,
            "p50_s": round(percentile(lat, 50), 3) if lat else None,
            "p95_s": round(percentile(lat, 95), 3) if lat else None,
            "p99_s": round(percentile(lat, 99), 3) if lat else None,
            "codes": {str(k): v for k, v in sorted(self.codes.items(), key=str)},
        }


def percentile(values: list[float], p: float) -> float:
    """Nearest-Rank-Methode: kleinster Wert, unter dem p % der Werte liegen."""
    if not values or not 0 < p <= 100:
        raise ValueError("values leer oder p außerhalb (0, 100]")
    ordered = sorted(values)
    return ordered[math.ceil(p / 100 * len(ordered)) - 1]


async def run_load(
    client: httpx.AsyncClient, payload: dict, total: int, concurrency: int
) -> Result:
    result = Result()
    sem = asyncio.Semaphore(concurrency)

    async def one() -> None:
        async with sem:
            start = time.perf_counter()
            try:
                resp = await client.post("/v1/chat/completions", json=payload)
                code: int | str = resp.status_code
            except httpx.HTTPError as exc:
                code = type(exc).__name__
            result.latencies.append(time.perf_counter() - start)
            result.codes[code] += 1

    start = time.perf_counter()
    async with asyncio.TaskGroup() as tg:
        for _ in range(total):
            tg.create_task(one())
    result.elapsed = time.perf_counter() - start
    return result
