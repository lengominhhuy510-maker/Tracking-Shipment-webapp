"""TASK-15: StaticFiles + SPA fallback — F5 on client routes must not 404."""

import pytest
from fastapi.testclient import TestClient

import app.main as main_module
from app.main import app

INDEX_HTML = "<!doctype html><html><body>SPA</body></html>"


@pytest.fixture()
def static_dir(tmp_path, monkeypatch):
    static = tmp_path / "static"
    (static / "assets").mkdir(parents=True)
    (static / "index.html").write_text(INDEX_HTML, encoding="utf-8")
    (static / "vite.svg").write_text("<svg/>", encoding="utf-8")
    (static / "assets" / "app.js").write_text("console.log(1)", encoding="utf-8")
    # secret sits OUTSIDE the static dir — must never be served
    (tmp_path / "secret.txt").write_text("top-secret", encoding="utf-8")
    monkeypatch.setattr(main_module, "_STATIC_DIR", static)
    return static


@pytest.fixture()
def client():
    with TestClient(app, raise_server_exceptions=False) as c:
        yield c


def test_root_serves_index_html(static_dir, client):
    response = client.get("/")
    assert response.status_code == 200
    assert response.text == INDEX_HTML
    assert response.headers["content-type"].startswith("text/html")


def test_client_route_f5_serves_index_not_404(static_dir, client):
    for path in ("/shipments", "/shipments/123", "/deep/nested/route"):
        response = client.get(path)
        assert response.status_code == 200, path
        assert response.text == INDEX_HTML, path


def test_existing_static_file_is_served(static_dir, client):
    response = client.get("/vite.svg")
    assert response.status_code == 200
    assert response.text == "<svg/>"
    response = client.get("/assets/app.js")
    assert response.status_code == 200
    assert response.text == "console.log(1)"


def test_unknown_api_path_stays_404_json_not_index(static_dir, client):
    response = client.get("/api/v1/definitely-not-a-route")
    assert response.status_code == 404
    assert "text/html" not in response.headers.get("content-type", "")


def test_api_prefix_without_version_stays_404(static_dir, client):
    assert client.get("/api").status_code == 404
    assert client.get("/api/").status_code == 404


def test_ws_path_not_swallowed_by_fallback(static_dir, client):
    # GET /ws is not a websocket handshake; fallback must not serve index for it
    response = client.get("/ws")
    assert response.status_code == 404


def test_path_traversal_never_escapes_static_dir(static_dir, client):
    response = client.get("/..%2fsecret.txt")
    assert response.status_code == 200
    assert response.text == INDEX_HTML  # falls back to index, never the secret


def test_missing_frontend_build_returns_404(tmp_path, monkeypatch, client):
    monkeypatch.setattr(main_module, "_STATIC_DIR", tmp_path / "nope")
    response = client.get("/shipments/123")
    assert response.status_code == 404
