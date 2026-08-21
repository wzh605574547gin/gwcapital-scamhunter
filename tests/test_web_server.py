from __future__ import annotations

import pytest
from fastapi.testclient import TestClient
from starlette.websockets import WebSocketDisconnect

from src.server import app


client = TestClient(app)


def test_healthz() -> None:
    response = client.get("/healthz")
    assert response.status_code == 200
    assert response.json() == {"status": "ok", "service": "gwcapital-scamhunter"}


def test_cc_frontend_is_allowed_by_cors() -> None:
    response = client.get(
        "/api/quota",
        headers={"Origin": "https://scamhunter.gwcapital.cc"},
    )
    assert response.status_code == 200
    assert response.headers["access-control-allow-origin"] == "https://scamhunter.gwcapital.cc"


def test_websocket_rejects_unknown_origin() -> None:
    with pytest.raises(WebSocketDisconnect) as exc:
        with client.websocket_connect(
            "/ws/analyze",
            headers={"Origin": "https://example.com"},
        ):
            pass
    assert exc.value.code == 1008


def test_websocket_accepts_frontend_and_validates_payload() -> None:
    with client.websocket_connect(
        "/ws/analyze",
        headers={"Origin": "https://scamhunter.gwcapital.xyz"},
    ) as websocket:
        websocket.send_json({"action": "start", "address": "not-a-tron-address"})
        payload = websocket.receive_json()

    assert payload["type"] == "error"
    assert "地址格式" in payload["data"]["message"]
