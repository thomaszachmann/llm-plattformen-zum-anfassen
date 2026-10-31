import httpx
import pytest

from llmctl.retry import backoff, send


def client_with(responses):
    """MockTransport spielt eine feste Folge von Antworten/Fehlern ab."""
    calls = iter(responses)

    def handler(request: httpx.Request) -> httpx.Response:
        item = next(calls)
        if isinstance(item, Exception):
            raise item
        return item

    return httpx.Client(base_url="http://gw", transport=httpx.MockTransport(handler))


def test_honors_retry_after():
    slept = []
    c = client_with(
        [
            httpx.Response(429, headers={"Retry-After": "2"}),
            httpx.Response(200, json={"ok": True}),
        ]
    )
    resp = send(c, "POST", "/v1/chat/completions", sleep=slept.append)
    assert resp.status_code == 200
    assert slept == [2.0]


def test_gives_up_after_retries():
    slept = []
    c = client_with([httpx.Response(503)] * 3)
    resp = send(c, "GET", "/", retries=2, sleep=slept.append)
    assert resp.status_code == 503
    assert len(slept) == 2


def test_no_retry_on_client_error():
    slept = []
    c = client_with([httpx.Response(401)])
    assert send(c, "GET", "/", sleep=slept.append).status_code == 401
    assert slept == []


def test_transport_error_is_retried_then_raised():
    slept = []
    c = client_with([httpx.ConnectError("refused")] * 2)
    with pytest.raises(httpx.ConnectError):
        send(c, "GET", "/", retries=1, sleep=slept.append)
    assert len(slept) == 1


@pytest.mark.parametrize("attempt,cap", [(0, 0.5), (1, 1.0), (3, 4.0), (10, 8.0)])
def test_backoff_bounds(attempt, cap):
    for _ in range(100):
        assert 0 <= backoff(attempt) <= cap
