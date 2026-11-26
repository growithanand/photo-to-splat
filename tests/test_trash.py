"""Permanent deletion only ever targets generated files in temporary workspaces."""

import io
import os
import subprocess
from concurrent.futures import ThreadPoolExecutor
from threading import Barrier
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient
from PIL import Image

from photosplat.app import create_app
from photosplat.images import import_image
from photosplat.store import RunConflictError, Store, read, write


def capture(store, name="Discarded scene", *, trash=True):
    scene = store.create_scene(name)
    for index in range(12):
        data = io.BytesIO()
        Image.new("RGB", (32, 24), (index * 19, 70, 110)).save(data, "JPEG")
        import_image(store, scene["id"], f"photo-{index}.jpg", data.getvalue())
    scene = store.get("scenes", scene["id"])
    run = store.create_run(scene["id"], {})
    store.update("runs", run["id"], status="complete")
    folder = store.path("runs", run["id"])
    (folder / "checkpoint.ckpt").write_bytes(b"temporary test checkpoint")
    if trash:
        store.trash_scene(scene["id"])
    return scene, run


def payload(store, *scenes):
    return {"scene_ids": [s["id"] for s in scenes], "workspace": str(store.root), "confirmation": "DELETE"}


def directory_link(link, target):
    try:
        link.symlink_to(target, target_is_directory=True)
    except OSError:
        if os.name != "nt":
            pytest.skip("Directory links unavailable")

        # NTFS junctions need no developer-mode or administrator privilege.
        def literal(path):
            return "'" + str(path).replace("'", "''") + "'"

        subprocess.run(
            [
                "powershell.exe",
                "-NoProfile",
                "-NonInteractive",
                "-Command",
                f"New-Item -ItemType Junction -Path {literal(link)} -Target {literal(target)} | Out-Null",
            ],
            check=True,
            capture_output=True,
            creationflags=subprocess.CREATE_NO_WINDOW,
        )


def test_confirmation_workspace_and_snapshot_scope(tmp_path):
    store = Store(tmp_path / "workspace")
    first, run = capture(store)
    second, _ = capture(store, "Newly trashed scene")
    source = tmp_path / "source-photo.jpg"
    source.write_bytes(b"external source stays unchanged")
    with TestClient(create_app(store.root, worker=False)) as client:
        body = payload(store, first)
        assert client.post("/api/trash/purge", json={**body, "confirmation": ""}).status_code == 400
        assert client.post("/api/trash/purge", json={**body, "workspace": str(tmp_path)}).status_code == 409
        assert store.path("scenes", first["id"]).is_dir()
        result = client.post("/api/trash/purge", json=body)
        assert result.status_code == 200
        assert result.json() == {"deleted_scene_ids": [first["id"]], "failed": []}
        assert not store.path("scenes", first["id"]).exists()
        assert not store.path("runs", run["id"]).exists()
        assert store.get("scenes", second["id"], include_deleted=True)["deleted_at"]
        assert source.read_bytes() == b"external source stays unchanged"


def test_empty_trash_deletes_selected_scenes_but_keeps_live_scene(tmp_path):
    store = Store(tmp_path)
    first, _ = capture(store)
    second, _ = capture(store, "Second")
    live, live_run = capture(store, "Keep this", trash=False)
    with TestClient(create_app(tmp_path, worker=False)) as client:
        assert client.post("/api/trash/purge", json=payload(store, first, second)).json()["failed"] == []
        state = client.get("/api/state").json()
        assert state["trash"] == []
        assert state["scenes"][0]["id"] == live["id"]
        assert (store.path("runs", live_run["id"]) / "checkpoint.ckpt").is_file()


def test_restored_or_invalid_selection_rejects_entire_batch(tmp_path):
    store = Store(tmp_path)
    first, _ = capture(store)
    second, _ = capture(store, "Restored")
    store.restore_scene(second["id"])
    with pytest.raises(RunConflictError, match="restored"):
        store.purge_scenes([first["id"], second["id"]])
    assert not store.get("scenes", first["id"], include_deleted=True).get("purging")
    for selection in ([first["id"], "../outside"], [first["id"], first["id"]], []):
        with pytest.raises(ValueError):
            store.purge_scenes(selection)
    assert store.path("scenes", first["id"]).is_dir()


def test_partial_failure_keeps_cleanup_journal_and_can_retry(tmp_path, monkeypatch):
    import photosplat.store as module

    store = Store(tmp_path)
    scene, run = capture(store)
    folder = store.path("runs", run["id"])
    original = module.shutil.rmtree

    def fail_midway(path):
        assert path.resolve().is_relative_to(store.root)
        if path == folder:
            (folder / "record.json").unlink()
            raise PermissionError("file is in use")
        original(path)

    monkeypatch.setattr(module.shutil, "rmtree", fail_midway)
    result = store.purge_scenes([scene["id"]])
    assert result["failed"][0]["scene_id"] == scene["id"]
    journal = store.get("scenes", scene["id"], include_deleted=True)
    assert journal["purging"] and journal["purge_run_ids"] == [run["id"]]
    with pytest.raises(RunConflictError, match="Permanent deletion has started"):
        store.restore_scene(scene["id"])
    monkeypatch.setattr(module.shutil, "rmtree", original)
    assert store.purge_scenes([scene["id"]])["deleted_scene_ids"] == [scene["id"]]
    assert not folder.exists()


def test_redirected_scene_root_is_refused_before_deletion(tmp_path):
    store = Store(tmp_path / "workspace")
    scene = store.create_scene("Redirected")
    store.trash_scene(scene["id"])
    path = store.path("scenes", scene["id"])
    outside = tmp_path / "protected"
    assert path.resolve().is_relative_to(tmp_path.resolve())
    assert outside.resolve().is_relative_to(tmp_path.resolve())
    path.rename(outside)
    (outside / "sentinel").write_bytes(b"keep")
    directory_link(path, outside)
    with pytest.raises(ValueError, match="redirected"):
        store.purge_scenes([scene["id"]])
    assert (outside / "sentinel").read_bytes() == b"keep"


def test_nested_directory_link_does_not_delete_its_target(tmp_path):
    store = Store(tmp_path / "workspace")
    scene, _ = capture(store)
    outside = tmp_path / "protected"
    outside.mkdir()
    (outside / "sentinel").write_bytes(b"keep")
    directory_link(store.path("scenes", scene["id"]) / "linked-folder", outside)
    assert store.purge_scenes([scene["id"]])["failed"] == []
    assert (outside / "sentinel").read_bytes() == b"keep"


def test_corrupt_identity_and_foreign_run_reference_are_refused(tmp_path):
    store = Store(tmp_path)
    scene, _ = capture(store)
    other, other_run = capture(store, "Keep", trash=False)
    record = store.path("scenes", scene["id"]) / "record.json"
    original = read(record)
    write(record, {**original, "id": other["id"]})
    with pytest.raises(ValueError, match="does not match"):
        store.purge_scenes([scene["id"]])
    write(record, {**original, "purge_run_ids": [other_run["id"]]})
    with pytest.raises(ValueError, match="another scene"):
        store.purge_scenes([scene["id"]])
    assert (store.path("runs", other_run["id"]) / "checkpoint.ckpt").is_file()


def test_unknown_compute_owner_blocks_purge_but_unrelated_viewer_is_preserved(tmp_path):
    store = Store(tmp_path)
    scene, _ = capture(store)
    other, other_run = capture(store, "Viewer scene", trash=False)
    app = create_app(tmp_path, worker=False)
    with TestClient(app) as client, store.compute_lease():
        assert client.post("/api/trash/purge", json=payload(store, scene)).status_code == 409
        app.state.services.viewers[other_run["id"]] = (SimpleNamespace(poll=lambda: None), 7010)
        try:
            assert client.post("/api/trash/purge", json=payload(store, scene)).json()["failed"] == []
            assert store.compute_busy()
            assert store.get("scenes", other["id"])["name"] == "Viewer scene"
        finally:
            app.state.services.viewers.clear()


def test_restore_racing_purge_has_only_one_winner(tmp_path):
    store = Store(tmp_path)
    scene, _ = capture(store)
    barrier = Barrier(2)

    def attempt(action):
        barrier.wait()
        try:
            action()
            return "accepted"
        except (ValueError, FileNotFoundError):
            return "refused"

    with ThreadPoolExecutor(max_workers=2) as pool:
        tasks = [
            pool.submit(attempt, action)
            for action in (
                lambda: store.restore_scene(scene["id"]),
                lambda: store.purge_scenes([scene["id"]]),
            )
        ]
        assert sorted(task.result() for task in tasks) == ["accepted", "refused"]
