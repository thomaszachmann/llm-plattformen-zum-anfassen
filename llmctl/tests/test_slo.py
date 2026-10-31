import httpx
import pytest

from llmctl.slo import budget_remaining, error_ratio_query, query_scalar


def prom(result):
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/api/v1/query"
        assert "gateway_requests_total" in request.url.params["query"]
        data = {"resultType": "vector", "result": result}
        return httpx.Response(200, json={"status": "success", "data": data})

    return httpx.Client(base_url="http://prom", transport=httpx.MockTransport(handler))


def test_query_contains_tenant_and_window():
    q = error_ratio_query("28d", "acme")
    assert 'tenant="acme"' in q and "[28d]" in q and 'code=~"5.."' in q


@pytest.mark.parametrize("window,tenant", [("28 d", None), ("28d", 'x"}or vector(1)')])
def test_query_rejects_bad_input(window, tenant):
    with pytest.raises(ValueError):
        error_ratio_query(window, tenant)


def test_query_scalar():
    c = prom([{"metric": {}, "value": [1760000000, "0.001"]}])
    assert query_scalar(c, error_ratio_query("28d")) == 0.001


def test_query_scalar_no_data():
    assert query_scalar(prom([]), error_ratio_query("28d")) is None
    nan = [{"metric": {}, "value": [1760000000, "NaN"]}]
    assert query_scalar(prom(nan), error_ratio_query("28d")) is None


def test_budget_remaining():
    assert budget_remaining(0.0, 0.995) == pytest.approx(1.0)
    assert budget_remaining(0.001, 0.995) == pytest.approx(0.8)
    assert budget_remaining(0.01, 0.995) == pytest.approx(-1.0)
