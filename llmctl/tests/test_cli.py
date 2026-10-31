import json

import httpx
import pytest

from llmctl.cli import main


def test_chat_end_to_end(monkeypatch, capsys):
    monkeypatch.setenv("LLMCTL_API_KEY", "lab-key-acme")
    monkeypatch.delenv("LLMCTL_MODEL", raising=False)  # Test hermetisch halten

    def handler(request: httpx.Request) -> httpx.Response:
        assert request.headers["Authorization"] == "Bearer lab-key-acme"
        body = json.loads(request.content)
        assert body["model"] == "mistral"
        return httpx.Response(
            200,
            json={
                "choices": [{"message": {"content": "Bonjour"}}],
                "usage": {"prompt_tokens": 5, "completion_tokens": 2},
            },
        )

    rc = main(["chat", "Hallo"], transport=httpx.MockTransport(handler))
    assert rc == 0
    assert capsys.readouterr().out.strip() == "Bonjour"


def test_missing_key(monkeypatch):
    monkeypatch.delenv("LLMCTL_API_KEY", raising=False)
    with pytest.raises(SystemExit, match="LLMCTL_API_KEY"):
        main(["chat", "Hallo"])


def test_rejects_zero_concurrency():
    with pytest.raises(SystemExit):
        main(["load", "-c", "0"])


def test_malformed_response_is_an_error(monkeypatch):
    monkeypatch.setenv("LLMCTL_API_KEY", "lab-key-acme")
    transport = httpx.MockTransport(lambda request: httpx.Response(200, json={}))
    assert main(["chat", "Hallo"], transport=transport) == 1
