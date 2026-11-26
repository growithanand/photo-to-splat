import io
from concurrent.futures import ThreadPoolExecutor

import pytest
from fastapi.testclient import TestClient
from PIL import Image

from photosplat.app import create_app
from photosplat.images import import_image, prepare
from photosplat.pipeline import Pipeline
from photosplat.runtime import Runtime, linux_path
from photosplat.store import Store, read


def jpeg(index=0, orientation=None):
    buffer = io.BytesIO()
    image = Image.new(
        "RGB", (80, 60), ((index * 19) % 256, (index * 31 + 80) % 256, (index * 47 + 150) % 256)
    )
    exif = Image.Exif()
    if orientation:
        exif[274] = orientation
    image.save(buffer, format="JPEG", exif=exif)
    return buffer.getvalue()


def capture(tmp_path, count=12):
    store = Store(tmp_path)
    scene = store.create_scene("A little scene")
    for i in range(count):
        import_image(store, scene["id"], f"photo-{i}.jpg", jpeg(i))
    return store, store.get("scenes", scene["id"])


def test_import_hashes_duplicates_and_handles_same_names(tmp_path):
    store = Store(tmp_path)
    scene = store.create_scene("Vase")
    first = import_image(store, scene["id"], "same.jpg", jpeg(0))
    duplicate = import_image(store, scene["id"], "renamed.jpg", jpeg(0))
    other = import_image(store, scene["id"], "same.jpg", jpeg(50))
    assert duplicate["duplicate"] and duplicate["id"] == first["id"]
    assert other["id"] != first["id"]
    assert len(store.get("scenes", scene["id"])["images"]) == 2


def test_concurrent_imports_do_not_lose_records(tmp_path):
    store = Store(tmp_path)
    scene = store.create_scene("Collection")
    with ThreadPoolExecutor(max_workers=4) as pool:
        list(pool.map(lambda i: import_image(store, scene["id"], f"{i}.jpg", jpeg(i)), range(12)))
    assert len(store.get("scenes", scene["id"])["images"]) == 12


def test_orientation_and_original_preservation(tmp_path):
    store = Store(tmp_path)
    scene = store.create_scene("Portrait")
    original = jpeg(0, 6)
    item = import_image(store, scene["id"], "phone.jpg", original)
    assert (item["width"], item["height"]) == (60, 80)
    for i in range(1, 12):
        import_image(store, scene["id"], f"{i}.jpg", jpeg(i))
    run = store.create_run(scene["id"], {})
    prepare(store, run)
    assert (store.path("scenes", scene["id"]) / "originals" / item["filename"]).read_bytes() == original
    manifest = read(store.path("runs", run["id"]) / "dataset/capture.json")
    assert manifest["images"][0]["prepared_width"] == 60


def test_run_snapshot_is_independent_of_later_imports(tmp_path):
    store, scene = capture(tmp_path)
    first = store.create_run(scene["id"], {})
    import_image(store, scene["id"], "later.jpg", jpeg(90))
    store.update("runs", first["id"], status="complete")
    second = store.create_run(scene["id"], {"steps": 30000})
    assert len(first["images"]) == 12 and len(second["images"]) == 13
    assert first["id"] != second["id"]
    assert store.get("runs", first["id"])["settings"]["steps"] == 7000


def test_small_capture_and_unknown_selection_rejected(tmp_path):
    store, scene = capture(tmp_path, 3)
    with pytest.raises(ValueError, match="at least 12"):
        store.create_run(scene["id"], {})
    with pytest.raises(ValueError, match="not in this scene"):
        store.create_run(scene["id"], {"image_ids": ["missing"]})


def test_invalid_files_rejected(tmp_path):
    store = Store(tmp_path)
    scene = store.create_scene("Bad file")
    with pytest.raises(ValueError, match="Convert HEIC"):
        import_image(store, scene["id"], "photo.heic", b"test")
    with pytest.raises(ValueError, match="cannot be safely decoded"):
        import_image(store, scene["id"], "photo.jpg", b"test")


def test_changed_source_blocks_resume(tmp_path):
    store, scene = capture(tmp_path)
    run = store.create_run(scene["id"], {})
    image = run["images"][0]
    path = store.path("scenes", scene["id"]) / "originals" / image["filename"]
    path.write_bytes(jpeg(99))
    with pytest.raises(ValueError, match="snapshot changed"):
        Pipeline(store, Runtime()).run(run["id"])


def test_completed_preparation_survives_failure_and_detects_tampering(tmp_path, monkeypatch):
    store, scene = capture(tmp_path)
    run = store.create_run(scene["id"], {})
    pipeline = Pipeline(store, Runtime())

    def execute(run_id, stage, command):
        if stage == "features":
            raise RuntimeError("feature failure")

    monkeypatch.setattr(pipeline, "execute", execute)
    monkeypatch.setattr(
        pipeline, "help", lambda *args: "--FeatureExtraction.use_gpu --FeatureExtraction.max_image_size"
    )
    with pytest.raises(RuntimeError, match="feature failure"):
        pipeline.run(run["id"])
    saved = store.get("runs", run["id"])
    assert saved["completed"] == ["verify", "prepare"]
    manifest = read(store.path("runs", run["id"]) / "dataset/capture.json")
    (store.path("runs", run["id"]) / "dataset/images" / manifest["images"][0]["prepared"]).write_bytes(
        jpeg(70)
    )
    with pytest.raises(ValueError, match="prepared photo changed"):
        pipeline.run(run["id"])


def test_api_scene_import_storage_and_origin(tmp_path):
    app = create_app(tmp_path, worker=False)
    with TestClient(app) as client:
        assert client.get("/openapi.json").status_code == 200
        assert (
            client.post(
                "/api/scenes", json={"name": "A room"}, headers={"Origin": "http://evil.example"}
            ).status_code
            == 403
        )
        assert client.get("/api/state", headers={"Host": "evil.example"}).status_code == 403
        scene = client.post("/api/scenes", json={"name": "A room"}).json()
        response = client.post(
            f"/api/scenes/{scene['id']}/photos", files=[("files", ("photo.jpg", jpeg(), "image/jpeg"))]
        )
        assert len(response.json()["imported"]) == 1
        assert client.get(f"/api/scenes/{scene['id']}/thumb/not-an-id").status_code == 400
        assert client.post(f"/api/scenes/{scene['id']}/runs", json={}).status_code == 400
        assert client.put("/api/storage", json={"path": "relative"}).status_code == 400
        other = tmp_path / "other"
        assert client.put("/api/storage", json={"path": str(other)}).status_code == 200
        assert client.get("/api/state").json()["scenes"] == []
        assert (tmp_path / "scenes" / scene["id"] / "record.json").is_file()


def test_resume_is_explicit_and_runtime_cannot_change_mid_run(tmp_path):
    store, scene = capture(tmp_path)
    run = store.create_run(scene["id"], {})
    app = create_app(tmp_path, worker=False)
    with TestClient(app) as client:
        assert client.post(f"/api/runs/{run['id']}/resume").status_code == 409
        assert client.put("/api/runtime", json={"mode": "native"}).status_code == 409
        assert client.post(f"/api/runs/{run['id']}/stop").json()["status"] == "cancelled"
        assert client.post(f"/api/runs/{run['id']}/resume").json()["status"] == "queued"


def test_windows_path_conversion_preserves_spaces():
    assert linux_path(r"D:\My photos\scene 1") == "/mnt/d/My photos/scene 1"


def test_external_option_help_on_stderr_is_preserved(monkeypatch):
    import sys

    runtime = Runtime()
    monkeypatch.setattr(
        runtime,
        "command",
        lambda *args: [
            sys.executable,
            "-c",
            "import sys; print('--FeatureExtraction.use_gpu',file=sys.stderr)",
        ],
    )
    assert "--FeatureExtraction.use_gpu" in runtime.capture("sfm", ["colmap", "feature_extractor", "-h"])


def test_native_lock_is_portable_and_hashed(tmp_path):
    from photosplat.native_lock import export

    metadata = tmp_path / "prefix/conda-meta"
    metadata.mkdir(parents=True)
    (metadata / "package.json").write_text('{"url":"https://example.org/package.conda","md5":"abc123"}')
    output = tmp_path / "native.lock"
    export(metadata.parent, output)
    assert output.read_text() == "# platform: linux-64\n@EXPLICIT\nhttps://example.org/package.conda#abc123\n"
    assert str(tmp_path) not in output.read_text()


def test_folder_browser_and_selection_estimate(tmp_path):
    store, scene = capture(tmp_path)
    app = create_app(tmp_path, worker=False)
    with TestClient(app) as client:
        folder = client.get("/api/folders", params={"path": str(tmp_path)}).json()
        assert folder["path"] == str(tmp_path.resolve())
        assert any(f["name"] == "scenes" for f in folder["folders"])
        selected = scene["images"][:3]
        result = client.post(
            f"/api/scenes/{scene['id']}/estimate", json={"image_ids": [i["id"] for i in selected]}
        ).json()
        assert result["source_bytes"] == sum(i["bytes"] for i in selected)


def test_crashed_worker_child_is_not_mistaken_for_a_free_gpu(tmp_path):
    import subprocess
    import sys
    import time

    from photosplat.pipeline import Queue, terminate

    store, scene = capture(tmp_path)
    run = store.create_run(scene["id"], {})
    child = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(30)", "/photosplat/runtime.sh"])
    queue = Queue(store, Runtime)
    try:
        store.update("runs", run["id"], status="running", pid=child.pid)
        queue.start()
        deadline = time.monotonic() + 5
        while not store.get("runs", run["id"]).get("error") and time.monotonic() < deadline:
            time.sleep(0.05)
        assert "previous worker is still active" in store.get("runs", run["id"])["error"]
        assert child.poll() is None
        store.update("runs", run["id"], cancel_requested=True)
        deadline = time.monotonic() + 8
        while store.get("runs", run["id"])["status"] == "running" and time.monotonic() < deadline:
            time.sleep(0.05)
        assert store.get("runs", run["id"])["status"] == "interrupted"
    finally:
        terminate(child)
        queue.close()


def test_cli_preserves_runtime_and_gpu_worker_ownership(tmp_path, monkeypatch, capsys):
    import sys

    from filelock import FileLock

    from photosplat.cli import main

    store, scene = capture(tmp_path)
    run = store.create_run(scene["id"], {})
    store.update("runs", run["id"], status="failed", runtime={"train_prefix": "/different/environment"})
    monkeypatch.setattr(sys, "argv", ["photosplat", "--workspace", str(tmp_path), "resume", run["id"]])
    with pytest.raises(SystemExit) as stopped:
        main()
    assert stopped.value.code == 2
    assert "Restore this run's runtime settings" in capsys.readouterr().err
    assert store.get("runs", run["id"])["status"] == "failed"

    store.update("runs", run["id"], status="complete", completed=["train"])
    monkeypatch.setattr("photosplat.app.port_free", lambda port: True)
    # An open UI owns this lock even when its queue is idle.
    with FileLock(str(tmp_path / ".worker.lock")):
        for command in (["view", run["id"]], ["doctor", "--verify"]):
            monkeypatch.setattr(sys, "argv", ["photosplat", "--workspace", str(tmp_path), *command])
            with pytest.raises(SystemExit) as stopped:
                main()
            assert stopped.value.code == 2
            assert "Close this workspace's UI first" in capsys.readouterr().err


def test_scene_rename_keeps_photos_and_run_settings(tmp_path):
    store, scene = capture(tmp_path)
    run = store.create_run(scene["id"], {})
    renamed = store.rename_scene(scene["id"], "  Desk sculpture  ")
    assert renamed["name"] == "Desk sculpture"
    assert renamed["images"] == scene["images"]
    assert store.get("runs", run["id"])["scene_name"] == "Desk sculpture"
    assert store.get("runs", run["id"])["settings"] == run["settings"]
    with pytest.raises(ValueError, match="name between"):
        store.rename_scene(scene["id"], "   ")


def test_trash_restore_preserves_files_and_hides_run_actions(tmp_path):
    store, scene = capture(tmp_path)
    run = store.create_run(scene["id"], {})
    store.update("runs", run["id"], status="failed")
    photo = scene["images"][0]
    original = store.path("scenes", scene["id"]) / "originals" / photo["filename"]
    payload = original.read_bytes()
    app = create_app(tmp_path, worker=False)
    with TestClient(app) as client:
        assert client.patch(f"/api/scenes/{scene['id']}", json={"name": "Vase"}).status_code == 200
        assert client.delete(f"/api/scenes/{scene['id']}").status_code == 200
        state = client.get("/api/state").json()
        assert state["scenes"] == [] and state["runs"] == []
        assert state["trash"][0]["name"] == "Vase"
        assert client.get(f"/api/scenes/{scene['id']}/thumb/{photo['id']}").status_code == 404
        assert client.get(f"/api/runs/{run['id']}").status_code == 404
        assert client.post(f"/api/runs/{run['id']}/resume").status_code == 404
        assert client.post(f"/api/scenes/{scene['id']}/runs", json={}).status_code == 404
        assert original.read_bytes() == payload
        # Undo works after restarting the application, not just in the current tab.
        assert Store(tmp_path).get("scenes", scene["id"], include_deleted=True)["deleted_at"]
        assert client.post(f"/api/scenes/{scene['id']}/restore").status_code == 200
        state = client.get("/api/state").json()
        assert not state["trash"] and len(state["scenes"]) == len(state["runs"]) == 1
        assert client.get(f"/api/runs/{run['id']}").status_code == 200
        assert original.read_bytes() == payload


def test_active_runs_and_viewers_prevent_scene_deletion(tmp_path):
    from types import SimpleNamespace

    store, scene = capture(tmp_path)
    run = store.create_run(scene["id"], {})
    app = create_app(tmp_path, worker=False)
    with TestClient(app) as client:
        for status in ("queued", "running"):
            store.update("runs", run["id"], status=status)
            assert client.delete(f"/api/scenes/{scene['id']}").status_code == 409
        store.update("runs", run["id"], status="complete")
        app.state.services.viewers[run["id"]] = (SimpleNamespace(poll=lambda: None), 7010)
        try:
            assert client.get("/api/state").json()["viewers"][run["id"]]["url"].endswith(":7010")
            assert client.delete(f"/api/scenes/{scene['id']}").status_code == 409
        finally:
            app.state.services.viewers.clear()
        assert client.delete(f"/api/scenes/{scene['id']}").status_code == 200


def test_no_run_can_be_created_in_a_deleted_scene(tmp_path):
    store, scene = capture(tmp_path)
    store.trash_scene(scene["id"])
    with pytest.raises(FileNotFoundError, match="Trash"):
        store.create_run(scene["id"], {})
    store.restore_scene(scene["id"])
    with pytest.raises(ValueError, match="at least 12"):
        store.create_run(scene["id"], {"image_ids": []})


def test_trash_and_queue_are_serialized(tmp_path):
    from threading import Barrier

    store, scene = capture(tmp_path)
    barrier = Barrier(2)

    def attempt(action):
        barrier.wait()
        try:
            action()
            return "accepted"
        except (ValueError, FileNotFoundError):
            return "refused"

    with ThreadPoolExecutor(max_workers=2) as pool:
        futures = [
            pool.submit(attempt, action)
            for action in (lambda: store.trash_scene(scene["id"]), lambda: store.create_run(scene["id"], {}))
        ]
        assert sorted(f.result() for f in futures) == ["accepted", "refused"]
