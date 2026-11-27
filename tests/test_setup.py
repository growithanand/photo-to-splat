"""Readiness and setup lifecycle checks; never download packages or run CUDA."""

import json
import subprocess
import threading
import time
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient

from photosplat.app import Services, create_app
from photosplat.runtime import Runtime
from photosplat.store import write


def stub_task(monkeypatch, handler):
    def run(self, kind, command, log, **kwargs):
        report_path = self.home / "diagnostics/gpu-verification.json"
        if kind == "verification":
            report_path.unlink(missing_ok=True)
        result = handler(command, **kwargs)
        if kind == "verification":
            from photosplat.store import read

            report = read(report_path) if result.returncode == 0 else None
            passed = bool(report and report.get("passed"))
            write(
                self.home / "diagnostics/verification.json",
                {
                    "fingerprint": kwargs["fingerprint"],
                    "passed": passed,
                    "report": report,
                    "checked": "2026-11-27T12:00:00Z",
                    "error": None if passed else "GPU fixture did not produce a passing report.",
                },
            )
        return result

    monkeypatch.setattr("photosplat.background.Tasks.run", run)


def detected(*, installed=True, fingerprint="environment-a", storage=True):
    return {
        "state": "verify" if installed and storage else "setup" if not installed else "attention",
        "tools_installed": installed,
        "managed": True,
        "missing_tools": [] if installed else ["colmap"],
        "fingerprint": fingerprint if installed else None,
        "free_bytes": (100 if storage else 1) * 1024**3,
        "checks": [{"id": "storage", "name": "Storage", "state": "ready" if storage else "attention"}],
    }


def check(services, verify=False):
    assert services.check(verify)
    deadline = time.monotonic() + 5
    while services.diagnostic_lock.locked() and time.monotonic() < deadline:
        time.sleep(0.01)
    assert not services.diagnostic_lock.locked()
    return services.diagnostic


def cache(root, *, passed=True):
    write(
        root / "diagnostics/verification.json",
        {
            "fingerprint": "environment-a",
            "passed": passed,
            "checked": "2026-11-26T12:00:00Z",
            "report": {"passed": passed},
            "error": None if passed else "CUDA execution failed",
        },
    )


def test_verified_setup_survives_restart_recheck_and_workspace_change(tmp_path, monkeypatch):
    cache(tmp_path)
    monkeypatch.setattr(Runtime, "readiness", lambda self, root: detected())
    for _ in range(2):
        services = Services(tmp_path, worker=False)
        assert check(services)["verified"]
        assert check(services)["state"] == "ready"
    with TestClient(create_app(tmp_path, worker=False)) as client:
        assert (
            client.put("/api/storage", json={"path": str(tmp_path / "another-workspace")}).status_code == 200
        )
        deadline = time.monotonic() + 5
        while time.monotonic() < deadline:
            state = client.get("/api/state").json()
            if state["diagnostic"]["state"] != "checking":
                break
            time.sleep(0.01)
        assert state["diagnostic"]["verified"]


@pytest.mark.parametrize("result", [detected(fingerprint="changed"), detected(installed=False)])
def test_changed_or_missing_environment_cannot_reuse_success(tmp_path, monkeypatch, result):
    cache(tmp_path)
    monkeypatch.setattr(Runtime, "readiness", lambda self, root: result.copy())
    diagnostic = check(Services(tmp_path, worker=False))
    assert not diagnostic["verified"]
    assert diagnostic["verification_changed"]


def test_low_disk_space_does_not_request_reinstallation(tmp_path, monkeypatch):
    cache(tmp_path)
    monkeypatch.setattr(Runtime, "readiness", lambda self, root: detected(storage=False))
    diagnostic = check(Services(tmp_path, worker=False))
    assert diagnostic["tools_installed"] and diagnostic["verified"]
    assert diagnostic["state"] == "attention"


def test_failed_retest_replaces_success_and_survives_restart(tmp_path, monkeypatch):
    cache(tmp_path)
    monkeypatch.setattr(Runtime, "readiness", lambda self, root: detected())
    stub_task(monkeypatch, lambda *a, **k: SimpleNamespace(returncode=1))
    result = check(Services(tmp_path, worker=False), verify=True)
    assert not result["verified"] and result["verification_error"]
    assert not check(Services(tmp_path, worker=False))["verified"]


def test_success_requires_a_new_passing_gpu_report(tmp_path, monkeypatch):
    monkeypatch.setattr(Runtime, "readiness", lambda self, root: detected())
    write(tmp_path / "diagnostics/gpu-verification.json", {"passed": True})
    stub_task(monkeypatch, lambda *a, **k: SimpleNamespace(returncode=0))
    assert not check(Services(tmp_path, worker=False), verify=True)["verified"]

    def render(*args, **kwargs):
        write(tmp_path / "diagnostics/gpu-verification.json", {"passed": True, "gpu": "test fixture"})
        return SimpleNamespace(returncode=0)

    stub_task(monkeypatch, render)
    result = check(Services(tmp_path, worker=False), verify=True)
    assert result["verified"] and result["verified_at"]
    assert check(Services(tmp_path, worker=False))["verified"]


def test_gpu_timeout_preserves_installed_tools_and_failed_test_on_restart(tmp_path, monkeypatch):
    cache(tmp_path)
    monkeypatch.setattr(Runtime, "readiness", lambda self, root: detected())

    def timeout(*args, **kwargs):
        raise subprocess.TimeoutExpired("GPU fixture", 900)

    stub_task(monkeypatch, timeout)
    result = check(Services(tmp_path, worker=False), verify=True)
    assert result["tools_installed"] and not result["verified"]
    assert "timed out" in result["verification_error"]
    restarted = check(Services(tmp_path, worker=False))
    assert not restarted["verified"] and "timed out" in restarted["verification_error"]


def test_damaged_cache_does_not_prevent_startup(tmp_path, monkeypatch):
    path = tmp_path / "diagnostics/verification.json"
    path.parent.mkdir()
    path.write_text("{unfinished")
    monkeypatch.setattr(Runtime, "readiness", lambda self, root: detected())
    assert check(Services(tmp_path, worker=False))["state"] == "verify"


def test_stale_install_request_does_not_launch_installer(tmp_path, monkeypatch):
    monkeypatch.setattr(Runtime, "readiness", lambda self, root: detected())

    def unexpected(*a, **k):
        pytest.fail("A healthy environment must not start installation")

    stub_task(monkeypatch, unexpected)
    with TestClient(create_app(tmp_path, worker=False)) as client:
        assert client.post("/api/setup").json()["state"] == "already_installed"
        assert client.post("/api/setup").json()["state"] == "already_installed"


def test_review_receipt_persists_and_profile_changes_require_review(tmp_path, monkeypatch):
    monkeypatch.setattr(Runtime, "readiness", lambda self, root: detected(installed=False))
    with TestClient(create_app(tmp_path, worker=False)) as client:
        state = client.get("/api/state").json()
        profile = state["setup_profile"]
        assert client.post("/api/setup", json={"profile": profile}).status_code == 409
        assert (
            client.post("/api/setup/review", json={"profile": profile, "reviewed": True}).status_code == 200
        )
    with TestClient(create_app(tmp_path, worker=False)) as client:
        assert client.get("/api/state").json()["setup_reviewed"]
        monkeypatch.setattr(Runtime, "profile", lambda self: "new-tool-profile")
        assert not client.get("/api/state").json()["setup_reviewed"]
        assert client.post("/api/setup", json={"profile": profile}).status_code == 409


def test_missing_component_install_and_explicit_repair_keep_admission_guards(tmp_path, monkeypatch):
    monkeypatch.setattr(Runtime, "readiness", lambda self, root: detected(installed=False))
    entered, release = threading.Event(), threading.Event()
    commands = []

    def install(command, **kwargs):
        commands.append(command)
        entered.set()
        assert release.wait(5)
        return SimpleNamespace(returncode=1)

    stub_task(monkeypatch, install)
    app = create_app(tmp_path, worker=False)
    with TestClient(app) as client:
        profile = client.get("/api/state").json()["setup_profile"]
        try:
            assert client.post("/api/setup", json={"profile": profile, "reviewed": True}).status_code == 200
            assert entered.wait(3)
            assert commands[0][-1] == "colmap"
            assert client.post("/api/setup", json={"profile": profile}).status_code == 409
        finally:
            release.set()
            deadline = time.monotonic() + 5
            while app.state.services.store.compute_busy() and time.monotonic() < deadline:
                time.sleep(0.01)
        monkeypatch.setattr(Runtime, "readiness", lambda self, root: detected())
        assert client.post("/api/setup", json={"profile": profile, "repair": True}).status_code == 409
        assert (
            client.post("/api/setup", json={"profile": profile, "repair": True, "reviewed": True}).status_code
            == 200
        )
        deadline = time.monotonic() + 5
        while app.state.services.store.compute_busy() and time.monotonic() < deadline:
            time.sleep(0.01)
        assert commands[-1][-3:] == ["compiler", "colmap", "training"]


def test_custom_environment_is_never_silently_replaced(tmp_path, monkeypatch):
    monkeypatch.setattr(Runtime, "readiness", lambda self, root: detected(installed=False))
    app = create_app(tmp_path, worker=False)
    app.state.services.settings["runtime"]["train_prefix"] = "/custom/train"
    with TestClient(app) as client:
        response = client.post("/api/setup", json={"repair": True, "reviewed": True})
        assert response.status_code == 409 and "Custom environments" in response.json()["detail"]
        assert app.state.services.settings["runtime"]["train_prefix"] == "/custom/train"


def test_inventory_fingerprint_tracks_versions_driver_and_route_but_not_disk(tmp_path, monkeypatch):
    runtime = Runtime()
    outputs = {
        "gpu": "GPU fixture, 24576 MiB, driver-a, uuid-a",
        "colmap": "COLMAP fixture",
        "compiler": "CUDA compiler fixture",
        "training": {
            "versions": {"torch": "2.7.1", "gsplat": "1.4"},
            "cuda": "12.8",
            "prefix": "/managed/train",
        },
    }

    def capture(kind, args, **kwargs):
        key = (
            "gpu"
            if args[0] == "nvidia-smi"
            else "colmap"
            if args[0] == "colmap"
            else "compiler"
            if args[0] == "nvcc"
            else "training"
        )
        return json.dumps(outputs[key]) if key == "training" else outputs[key]

    monkeypatch.setattr(runtime, "capture", capture)
    original = runtime.readiness(tmp_path)
    assert original["tools_installed"]
    for key in ("gpu", "colmap", "compiler"):
        saved = outputs[key]
        outputs[key] += " changed"
        assert runtime.readiness(tmp_path)["fingerprint"] != original["fingerprint"]
        outputs[key] = saved
    outputs["training"]["versions"]["gsplat"] = "changed"
    assert runtime.readiness(tmp_path)["fingerprint"] != original["fingerprint"]
    outputs["training"]["versions"]["gsplat"] = "1.4"
    monkeypatch.setattr("photosplat.runtime.shutil.disk_usage", lambda root: SimpleNamespace(free=1024**3))
    low_disk = runtime.readiness(tmp_path)
    assert low_disk["state"] == "attention" and low_disk["fingerprint"] == original["fingerprint"]
    runtime.options.distro = "Another distro"
    assert runtime.readiness(tmp_path)["fingerprint"] != original["fingerprint"]
