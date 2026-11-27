import io

import pytest
from fastapi.testclient import TestClient
from PIL import Image

from photosplat.app import create_app
from photosplat.images import import_image, prepare
from photosplat.store import RunConflictError, Store, read, write


@pytest.mark.parametrize("damaged", ["{", "[]", '{"id":null}'])
def test_bad_scene_record_leaves_healthy_collection_available_and_files_untouched(tmp_path, damaged):
    store = Store(tmp_path)
    good = store.create_scene("Healthy capture")
    bad = store.create_scene("Damaged capture")
    path = store.path("scenes", bad["id"]) / "record.json"
    path.write_text(damaged)
    with TestClient(create_app(tmp_path, worker=False)) as client:
        response = client.get("/api/state")
        assert response.status_code == 200
        data = response.json()
        assert [s["id"] for s in data["scenes"]] == [good["id"]]
        assert data["record_issues"][0]["path"] == str(path)
        assert path.read_text() == damaged
        write(path, bad)
        assert not client.get("/api/state").json()["record_issues"]


def capture(store):
    scene = store.create_scene("Capture")
    for index in [8, 1, 11, 3, 10, 0, 5, 2, 9, 4, 7, 6]:
        data = io.BytesIO()
        Image.new("RGB", (25, 20), (index * 20, 50, 90)).save(data, "JPEG")
        import_image(store, scene["id"], f"capture_{index}.jpg", data.getvalue())
    return scene


def test_unknown_run_ownership_blocks_admission_without_hiding_healthy_scenes(tmp_path):
    store = Store(tmp_path)
    scene = capture(store)
    run = store.create_run(scene["id"], {})
    (store.path("runs", run["id"]) / "record.json").write_text("{")
    with TestClient(create_app(tmp_path, worker=False)) as client:
        data = client.get("/api/state").json()
        assert len(data["scenes"]) == 1 and data["record_issues"]
        assert client.post(f"/api/scenes/{scene['id']}/runs", json={}).status_code == 409
    with pytest.raises(RunConflictError):
        Store(tmp_path).create_run(scene["id"], {})


def test_sequential_order_is_natural_filename_order_and_saved_runs_are_unchanged(tmp_path):
    store = Store(tmp_path)
    scene = capture(store)
    old = store.create_run(scene["id"], {})
    store.update("runs", old["id"], status="complete")
    run = store.create_run(scene["id"], {"matching": "sequential"})
    expected = [f"capture_{n}.jpg" for n in range(12)]
    assert [p["name"] for p in run["images"]] == expected
    assert run["image_order"] == "capture-filename-v1"
    prepare(store, run)
    manifest = read(store.path("runs", run["id"]) / "dataset/capture.json")
    assert [p["name"] for p in manifest["images"]] == expected
    assert store.get("runs", old["id"])["images"] == old["images"]


@pytest.mark.parametrize("mode", ["P", "RGBA"])
def test_working_images_retain_palette_and_rgba_transparency(tmp_path, mode):
    store = Store(tmp_path)
    scene = store.create_scene("Transparency")
    data = io.BytesIO()
    image = Image.new(mode, (25, 20))
    image.save(data, "PNG", **({"transparency": 0} if mode == "P" else {}))
    item = import_image(store, scene["id"], "image.png", data.getvalue())
    run = {"id": "a" * 32, "scene_id": scene["id"], "images": [item], "settings": {"max_size": 800}}
    prepare(store, run)
    working = next((store.path("runs", run["id"]) / "dataset/images").iterdir())
    with Image.open(working) as result:
        assert working.suffix == ".png" and result.mode == "RGBA"
        assert result.getpixel((0, 0))[3] == 0
