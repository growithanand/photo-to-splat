"""Container delivery keeps native setup immutable and workspaces persistent."""

import pytest
from fastapi.testclient import TestClient

from photosplat.app import create_app
from photosplat.deployment import bind_host, viewer_ports, viewer_url
from photosplat.runtime import Runtime


@pytest.fixture
def container(monkeypatch, tmp_path):
    monkeypatch.setenv("PHOTOSPLAT_CONTAINER", "1")
    monkeypatch.setenv("PHOTOSPLAT_DATA_ROOT", str(tmp_path / "data"))
    monkeypatch.setenv("PHOTOSPLAT_VIEWER_PORT", "17010")
    return tmp_path / "data"


def test_local_network_defaults_are_preserved(monkeypatch):
    monkeypatch.delenv("PHOTOSPLAT_CONTAINER", raising=False)
    assert bind_host() == "127.0.0.1"
    assert list(viewer_ports()) == list(range(7010, 7030))
    assert viewer_url(7012) == "http://localhost:7012"


def test_container_networking_maps_a_single_viewer_port(container):
    assert bind_host() == "0.0.0.0"
    assert list(viewer_ports()) == [7010]
    assert viewer_url(7010) == "http://localhost:17010"


def test_container_uses_its_native_tools_even_with_old_runtime_settings(container):
    runtime = Runtime({"mode": "wsl", "train_prefix": "/old/prefix"})
    assert runtime.options.mode == "native" and not runtime.wsl
    assert runtime.options.train_prefix == ""


def test_container_settings_reject_installs_and_custom_runtime(container):
    with TestClient(create_app(container, worker=False)) as client:
        state = client.get("/api/state").json()
        assert state["delivery"] == {"mode": "docker", "data_root": str(container.resolve())}
        assert client.get("/api/health").json() == {"status": "ok"}
        assert client.post("/api/setup", json={"repair": True, "reviewed": True}).status_code == 409
        assert client.put("/api/runtime", json={"mode": "wsl"}).status_code == 409
        assert client.get("/api/health", headers={"host": "untrusted.example"}).status_code == 403
        assert (
            client.post(
                "/api/scenes", json={"name": "External"}, headers={"origin": "https://untrusted.example"}
            ).status_code
            == 403
        )


def test_container_storage_and_folder_picker_stay_on_the_data_volume(container, tmp_path):
    app = create_app(container, worker=False)
    app.state.services.check = lambda *args, **kwargs: True
    with TestClient(app) as client:
        assert client.put("/api/storage", json={"path": str(tmp_path / "ephemeral")}).status_code == 400
        assert client.get("/api/folders", params={"path": str(tmp_path)}).status_code == 400
        listing = client.get("/api/folders").json()
        assert listing["roots"] == [str(container.resolve())]
        assert listing["path"] == listing["parent"]
        child = container / "another-workspace"
        assert client.put("/api/storage", json={"path": str(child)}).status_code == 200
        assert app.state.services.store.root == child.resolve()


def test_container_fingerprint_does_not_depend_on_a_recreated_container_hostname(container, monkeypatch):
    runtime = Runtime()
    original = runtime.profile()
    monkeypatch.setattr("photosplat.runtime.platform.node", lambda: "new-container-id")
    assert runtime.profile() == original
