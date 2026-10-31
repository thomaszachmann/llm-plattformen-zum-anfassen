import asyncio
import itertools

import httpx
import pytest

from llmctl.load import percentile, run_load


def test_percentile_nearest_rank():
    values = [float(i) for i in range(1, 101)]  # 1..100
    assert percentile(values, 50) == 50.0
    assert percentile(values, 95) == 95.0
    assert percentile(values, 99) == 99.0
    assert percentile([3.0], 99) == 3.0


def test_percentile_rejects_empty():
    with pytest.raises(ValueError):
        percentile([], 50)


def test_run_load_counts_errors():
    counter = itertools.count()

    def handler(request: httpx.Request) -> httpx.Response:
        # jede vierte Anfrage scheitert
        return httpx.Response(500 if next(counter) % 4 == 3 else 200, json={})

    async def go():
        async with httpx.AsyncClient(
            base_url="http://gw", transport=httpx.MockTransport(handler)
        ) as client:
            return await run_load(client, {}, total=20, concurrency=5)

    s = asyncio.run(go()).summary()
    assert s["requests"] == 20
    assert s["errors"] == 5
    assert s["error_rate"] == 0.25
    assert s["codes"] == {"200": 15, "500": 5}
