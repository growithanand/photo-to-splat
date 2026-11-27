"""Use real CPU child processes to check task ownership across server restarts."""

import json
import subprocess
import sys
import time

import psutil
import pytest
from fastapi.testclient import TestClient

from photosplat.app import create_app
from photosplat.background import Tasks, alive, task_path
from photosplat.store import RunConflictError, Store, read, write


def wait_for(predicate, timeout=10):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if predicate():
            return
        time.sleep(0.05)
    raise AssertionError("The test process did not reach the expected state.")


def sleeper(ready):
    return [
        sys.executable,
        "-c",
        f"from pathlib import Path; import time; Path({str(ready)!r}).write_text('ready'); time.sleep(40)",
    ]


@pytest.mark.parametrize("reserved", [False, True])
def test_shutdown_stops_owned_task_and_its_child_before_releasing_workspace(tmp_path, reserved):
    app = create_app(tmp_path, worker=False)
    store = app.state.services.store
    tasks = app.state.services.tasks
    ready = tmp_path / "ready"
    lease = store.compute_lease() if reserved else None
    if lease:
        lease.acquire()
    process, task_id = tasks.start("setup", sleeper(ready), tmp_path / "setup.log", lease=lease)
    try:
        assert Store(tmp_path).compute_busy()  # Includes the supervisor handoff.
        with pytest.raises(RunConflictError):
            Store(tmp_path).require_idle()
        wait_for(ready.exists)
        child = read(task_path(store))["child"]
        with TestClient(app):
            pass  # Exiting the actual app lifespan must stop its owned task.
        process.wait(timeout=10)
        assert not alive(child)
        assert read(task_path(store))["state"] == "interrupted"
        assert not Store(tmp_path).compute_busy()
    finally:
        tasks.stop(task_id)
        process.wait(timeout=10)


def test_server_exit_keeps_child_supervised_and_restarted_app_can_stop_it(tmp_path):
    parent_script = tmp_path / "parent.py"
    ready = tmp_path / "ready"
    parent_script.write_text(
        "from pathlib import Path\nimport time\n"
        "from photosplat.background import Tasks\nfrom photosplat.store import Store\n"
        f"root=Path({str(tmp_path)!r})\n"
        f"process, task_id=Tasks(Store(root), root).start('setup', {sleeper(ready)!r}, root/'setup.log')\n"
        f"while not Path({str(ready)!r}).exists(): time.sleep(.05)\n"
        "print(task_id, flush=True)\n"
    )
    parent = subprocess.run([sys.executable, str(parent_script)], capture_output=True, text=True, timeout=15)
    assert parent.returncode == 0, parent.stderr
    store = Store(tmp_path)
    task = read(task_path(store))
    try:
        assert not alive(task["owner"])
        assert alive(task["supervisor"]) and alive(task["child"])
        assert Store(tmp_path).compute_busy()
        with TestClient(create_app(tmp_path, worker=False)) as client:
            state = client.get("/api/state").json()
            assert state["setup"]["state"] == "running"
            assert state["background"]["id"] == task["id"]
            assert client.post("/api/setup").status_code == 409
            assert client.post(f"/api/background/{task['id']}/stop").status_code == 200
            wait_for(lambda: not store.compute_busy())
        assert not alive(task["child"])
    finally:
        Tasks(store, tmp_path).stop(task["id"])
        wait_for(lambda: not alive(task["supervisor"]))


def test_timed_out_verification_invalidates_cached_success_and_stops_child(tmp_path):
    store = Store(tmp_path)
    tasks = Tasks(store, tmp_path)
    write(tmp_path / "diagnostics/verification.json", {"passed": True, "fingerprint": "old"})
    result = tasks.run(
        "verification",
        sleeper(tmp_path / "ready"),
        tmp_path / "check.log",
        timeout=0.3,
        fingerprint="new",
    )
    assert result.returncode == 1
    task = read(task_path(store))
    assert not alive(task["child"])
    assert not store.compute_busy()
    record = read(tmp_path / "diagnostics/verification.json")
    assert record["passed"] is False and record["fingerprint"] == "new"


def test_successful_verification_is_recorded_even_without_a_server_observer(tmp_path):
    store = Store(tmp_path)
    tasks = Tasks(store, tmp_path)
    report = tmp_path / "diagnostics/gpu-verification.json"
    command = [
        sys.executable,
        "-c",
        f"from pathlib import Path; p=Path({str(report)!r}); p.parent.mkdir(exist_ok=True); p.write_text('{{\"passed\":true}}')",
    ]
    assert tasks.run("verification", command, tmp_path / "check.log", fingerprint="current").returncode == 0
    cached = json.loads((tmp_path / "diagnostics/verification.json").read_text())
    assert cached["passed"] and cached["fingerprint"] == "current"
    assert not store.compute_busy()


def test_supervisor_requires_a_fresh_gpu_report(tmp_path):
    store = Store(tmp_path)
    write(tmp_path / "diagnostics/gpu-verification.json", {"passed": True})
    result = Tasks(store, tmp_path).run(
        "verification", [sys.executable, "-c", "pass"], tmp_path / "check.log", fingerprint="current"
    )
    assert result.returncode == 1
    assert read(tmp_path / "diagnostics/verification.json")["passed"] is False


def test_dead_supervisor_cannot_make_its_live_child_look_like_idle_work(tmp_path):
    store = Store(tmp_path)
    tasks = Tasks(store, tmp_path)
    ready = tmp_path / "ready"
    process, task_id = tasks.start("setup", sleeper(ready), tmp_path / "setup.log")
    try:
        wait_for(ready.exists)
        task = read(task_path(store))
        psutil.Process(task["supervisor"]["pid"]).kill()
        process.wait(timeout=10)
        assert alive(task["child"])
        assert Store(tmp_path).compute_busy()
        assert store.background_task()["state"] == "recovery"
        tasks.stop(task_id)
        assert not alive(task["child"])
        assert not store.compute_busy()
    finally:
        tasks.stop(task_id)
        process.wait(timeout=10)
