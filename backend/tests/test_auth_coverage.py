"""Regression: every REST API route and WebSocket require real session auth."""

import pytest
from fastapi.routing import APIRoute
from fastapi.testclient import TestClient
from starlette.websockets import WebSocketDisconnect

from app.api.deps import get_current_user
from app.main import app


def _dependency_calls(route: APIRoute) -> set:
    calls = set()
    pending = list(route.dependant.dependencies)
    while pending:
        dependant = pending.pop()
        calls.add(dependant.call)
        pending.extend(dependant.dependencies)
    return calls


def test_every_api_v1_route_requires_current_user():
    api_routes = [
        route
        for route in app.routes
        if isinstance(route, APIRoute) and route.path.startswith("/api/v1/")
    ]
    assert api_routes
    unprotected = [
        f"{','.join(sorted(route.methods or []))} {route.path}"
        for route in api_routes
        if get_current_user not in _dependency_calls(route)
    ]
    assert unprotected == []


def test_api_without_cookie_returns_401_json_not_redirect():
    with TestClient(app, raise_server_exceptions=False) as client:
        response = client.get("/api/v1/shipments/", follow_redirects=False)
    assert response.status_code == 401
    assert response.headers.get("location") is None
    assert response.json() == {
        "detail": {"code": "UNAUTHENTICATED", "message": "Yêu cầu đăng nhập"}
    }


def test_websocket_without_cookie_closes_4401():
    with TestClient(app) as client:
        with pytest.raises(WebSocketDisconnect) as caught:
            with client.websocket_connect("/ws"):
                pass
    assert caught.value.code == 4401
