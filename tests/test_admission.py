"""Exercise competing requests without starting CUDA or installing anything."""

import io
import subprocess
import sys
import threading
from concurrent.futures import ThreadPoolExecutor
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient
from PIL import Image

from photosplat.app import create_app
from photosplat.images import import_image
from photosplat.pipeline import terminate
from photosplat.store import RunConflictError, Store


def scene_with_photos(root):
    store = Store(root)
    scene = store.create_scene("Test sculpture")
    for index in range(12):
        image = io.BytesIO()
        Image.new("RGB", (40, 30), (index * 18, 90, 120)).save(image, "JPEG")
        import_image(store, scene["id"], f"photo-{index}.jpg", image.getvalue())
    return store, scene


def simultaneously(*actions):
    barrier = threading.Barrier(len(actions))

    def perform(action):
        barrier.wait()
        return action()

    with ThreadPoolExecutor(max_workers=len(actions)) as pool:
        return [future.result() for future in [pool.submit(perform, action) for action in actions]]


def test_simultaneous_start_across_two_app_instances_accepts_exactly_one(tmp_path):
    store, scene = scene_with_photos(tmp_path)
    # Independent Store/Services objects exercise the on-disk lock, not just a
    # shared Python object or the UI's disabled button.
    with (
        TestClient(create_app(tmp_path, worker=False)) as first,
        TestClient(create_app(tmp_path, worker=False)) as second,
    ):
        results = simultaneously(
            lambda: first.post(f"/api/scenes/{scene['id']}/runs", json={}),
            lambda: second.post(f"/api/scenes/{scene['id']}/runs", json={}),
        )
        assert sorted(r.status_code for r in results) == [201, 409]
        assert len(store.list("runs")) == 1
        assert first.get("/api/state").json()["activity"]["kind"] == "reconstruction"


def test_running_and_queued_jobs_block_other_scenes_and_cli_store(tmp_path):
    store, scene = scene_with_photos(tmp_path)
    other = store.create_scene("Another object")
    run = store.create_run(scene["id"], {})
    with TestClient(create_app(tmp_path, worker=False)) as client:
        for status in ("queued", "running"):
            store.update("runs", run["id"], status=status)
            assert client.post(f"/api/scenes/{other['id']}/runs", json={}).status_code == 409
            with pytest.raises(RunConflictError):
                Store(tmp_path).create_run(scene["id"], {})
        store.update("runs", run["id"], status="complete")
        assert client.post(f"/api/scenes/{scene['id']}/runs", json={}).status_code == 201


def test_start_racing_resume_accepts_one_and_double_resume_is_refused(tmp_path):
    store, scene = scene_with_photos(tmp_path)
    run = store.create_run(scene["id"], {})
    store.update("runs", run["id"], status="failed")
    with TestClient(create_app(tmp_path, worker=False)) as client:
        results = simultaneously(
            lambda: client.post(f"/api/scenes/{scene['id']}/runs", json={}),
            lambda: client.post(f"/api/runs/{run['id']}/resume"),
        )
        assert sum(response.status_code in (200, 201) for response in results) == 1
        assert sum(response.status_code == 409 for response in results) == 1
        for item in store.list("runs"):
            store.update("runs", item["id"], status="failed")
        results = simultaneously(*[lambda: client.post(f"/api/runs/{run['id']}/resume") for _ in range(2)])
        assert sorted(response.status_code for response in results) == [200, 409]


def test_shared_compute_lease_blocks_run_and_is_released_on_failure(tmp_path):
    store, scene = scene_with_photos(tmp_path)
    with pytest.raises(RuntimeError, match="interrupted"):
        with store.compute_lease():
            assert Store(tmp_path).compute_busy()
            with pytest.raises(RunConflictError):
                Store(tmp_path).create_run(scene["id"], {})
            raise RuntimeError("interrupted")
    assert not store.compute_busy()
    assert store.create_run(scene["id"], {})["status"] == "queued"


def test_viewer_double_launch_is_idempotent_and_blocks_other_operations(tmp_path, monkeypatch):
    store, scene = scene_with_photos(tmp_path)
    run = store.create_run(scene["id"], {})
    store.update("runs", run["id"], status="complete", completed=["train"])
    child = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(30)"])
    launches = []

    def launch(*args, **kwargs):
        launches.append(args)
        return child

    monkeypatch.setattr("photosplat.app.subprocess.Popen", launch)
    monkeypatch.setattr("photosplat.app.port_free", lambda port: True)
    try:
        with (
            TestClient(create_app(tmp_path, worker=False)) as client,
            TestClient(create_app(tmp_path, worker=False)) as other,
        ):
            results = simultaneously(
                *[lambda: client.post(f"/api/runs/{run['id']}/viewer") for _ in range(2)]
            )
            assert all(response.status_code == 200 for response in results)
            assert len(launches) == 1
            for endpoint, method, payload in (
                (f"/api/scenes/{scene['id']}/runs", "post", {}),
                ("/api/diagnostics?verify=true", "post", {}),
                ("/api/setup", "post", {}),
                ("/api/runtime", "put", {"mode": "native"}),
                ("/api/storage", "put", {"path": str(tmp_path / "other")}),
            ):
                assert getattr(client, method)(endpoint, json=payload).status_code == 409
            assert other.post(f"/api/scenes/{scene['id']}/runs", json={}).status_code == 409
            assert client.post("/api/viewers/stop").status_code == 200
            assert not store.compute_busy()
    finally:
        terminate(child)


def test_failed_viewer_launch_releases_reservation(tmp_path, monkeypatch):
    store, scene = scene_with_photos(tmp_path)
    run = store.create_run(scene["id"], {})
    store.update("runs", run["id"], status="complete", completed=["train"])

    def failed(*args, **kwargs):
        raise OSError("viewer executable unavailable")

    monkeypatch.setattr("photosplat.app.subprocess.Popen", failed)
    monkeypatch.setattr("photosplat.app.port_free", lambda port: True)
    with TestClient(create_app(tmp_path, worker=False)) as client:
        with pytest.raises(OSError):
            client.post(f"/api/runs/{run['id']}/viewer")
        assert not store.compute_busy()
        assert client.post(f"/api/scenes/{scene['id']}/runs", json={}).status_code == 201


@pytest.mark.parametrize("operation", ["verification", "setup"])
def test_background_tasks_block_conflicts_and_release_on_failure(tmp_path, monkeypatch, operation):
    store, scene = scene_with_photos(tmp_path)
    started, finish = threading.Event(), threading.Event()

    def hold(*args, **kwargs):
        started.set()
        assert finish.wait(10)
        return SimpleNamespace(returncode=1)

    monkeypatch.setattr(
        "photosplat.background.Tasks.run", lambda self, kind, command, log, **kwargs: hold(command)
    )
    app = create_app(tmp_path, worker=False)
    runtime = SimpleNamespace(
        readiness=lambda root: {
            "state": "setup" if operation == "setup" else "verify",
            "checks": [],
            "fingerprint": "test-environment" if operation == "verification" else None,
            "tools_installed": operation != "setup",
            "missing_tools": ["training"],
            "free_bytes": 100 * 1024**3,
        },
        engine_command=lambda *args: ["unused"],
        profile=lambda: "test-profile",
        wsl=True,
        options=SimpleNamespace(distro="Ubuntu", train_prefix="", sfm_prefix="", model_dump=lambda: {}),
    )
    monkeypatch.setattr(app.state.services, "runtime", lambda: runtime)
    with TestClient(app) as client:
        app.state.services.diagnostic = {"state": "verify", "verified": False, "checks": []}
        endpoint = "/api/setup" if operation == "setup" else "/api/diagnostics?verify=true"
        try:
            assert (
                client.post(endpoint, json={"profile": "test-profile", "reviewed": True}).status_code == 200
            )
            assert started.wait(3)
            for path, method, payload in (
                (f"/api/scenes/{scene['id']}/runs", "post", {}),
                ("/api/diagnostics?verify=true", "post", {}),
                ("/api/setup", "post", {}),
                ("/api/runtime", "put", {"mode": "native"}),
                ("/api/storage", "put", {"path": str(tmp_path / "elsewhere")}),
            ):
                assert getattr(client, method)(path, json=payload).status_code == 409
            with pytest.raises(RunConflictError):
                Store(tmp_path).create_run(scene["id"], {})
        finally:
            finish.set()
            import time

            deadline = time.monotonic() + 5
            while store.compute_busy() and time.monotonic() < deadline:
                time.sleep(0.02)
        assert not store.compute_busy()


def test_import_and_repeated_stop_have_safe_conflict_behavior(tmp_path):
    store, scene = scene_with_photos(tmp_path)
    app = create_app(tmp_path, worker=False)
    with TestClient(app) as client:
        app.state.services.importing[scene["id"]] = 1
        assert client.delete(f"/api/scenes/{scene['id']}").status_code == 409
        assert client.put("/api/storage", json={"path": str(tmp_path / "next")}).status_code == 409
        app.state.services.importing.clear()
        run = store.create_run(scene["id"], {})
        assert client.post(f"/api/runs/{run['id']}/stop").status_code == 200
        assert client.post(f"/api/runs/{run['id']}/stop").status_code == 200


def test_worker_keeps_compute_lease_until_failure_is_recorded(tmp_path, monkeypatch):
    import time

    from photosplat.pipeline import Pipeline, Queue
    from photosplat.runtime import Runtime

    store, scene = scene_with_photos(tmp_path)
    run = store.create_run(scene["id"], {})
    started, finish = threading.Event(), threading.Event()

    def fail_after_wait(pipeline, run_id):
        store.update("runs", run_id, status="running")
        started.set()
        assert finish.wait(10)
        raise RuntimeError("simulated stage failure")

    monkeypatch.setattr(Pipeline, "run", fail_after_wait)
    queue = Queue(store, Runtime)
    try:
        queue.start()
        assert started.wait(3)
        assert Store(tmp_path).compute_busy()
        with pytest.raises(RunConflictError):
            store.create_run(scene["id"], {})
        finish.set()
        deadline = time.monotonic() + 5
        while store.get("runs", run["id"])["status"] != "failed" and time.monotonic() < deadline:
            time.sleep(0.02)
        assert store.get("runs", run["id"])["status"] == "failed"
        assert not Store(tmp_path).compute_busy()
    finally:
        finish.set()
        queue.close()
