"""Small, inspectable JSON records; photographs and checkpoints stay in the workspace."""

from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
import stat
import uuid
from datetime import datetime, timezone
from pathlib import Path

from filelock import FileLock, Timeout


class SceneBusyError(ValueError):
    """The scene still owns work that must be stopped before removing it."""


class RunConflictError(ValueError):
    def __init__(self, message: str, run: dict | None = None):
        super().__init__(message)
        self.run = run


class RecordError(ValueError):
    """Keep an unreadable record in place so it can be recovered from a backup."""


def now() -> str:
    return datetime.now(timezone.utc).isoformat()


def identity() -> str:
    return uuid.uuid4().hex


def digest(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            h.update(block)
    return h.hexdigest()


def read(path: Path, default=None):
    return json.loads(path.read_text(encoding="utf-8")) if path.exists() else default


def write(path: Path, data) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.{uuid.uuid4().hex}.tmp")
    temporary.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")
    os.replace(temporary, path)


def valid_id(value: str) -> str:
    if not re.fullmatch(r"[a-f0-9]{32}", value):
        raise ValueError("Unknown scene or run identifier.")
    return value


class Store:
    def __init__(self, root: Path):
        self.root = root.expanduser().resolve()
        self.root.mkdir(parents=True, exist_ok=True)
        self.lock = FileLock(str(self.root / ".records.lock"))
        (self.root / "scenes").mkdir(exist_ok=True)
        (self.root / "runs").mkdir(exist_ok=True)

    def path(self, kind: str, item_id: str) -> Path:
        if kind not in ("scenes", "runs"):
            raise ValueError("Unknown record type.")
        return self.root / kind / valid_id(item_id)

    def get(self, kind: str, item_id: str, *, include_deleted=False) -> dict:
        record = self.load_record(kind, self.path(kind, item_id) / "record.json")
        if record is None:
            raise FileNotFoundError(f"This {kind[:-1]} does not exist in the selected workspace.")
        if not include_deleted:
            if record.get("deleted_at"):
                raise FileNotFoundError("This scene is in Trash. Restore it before opening it.")
            if kind == "runs":
                self.get("scenes", record["scene_id"])
        return record

    def save(self, kind: str, record: dict) -> None:
        with self.lock:
            write(self.path(kind, record["id"]) / "record.json", record)

    def update(self, kind: str, item_id: str, **changes) -> dict:
        with self.lock:
            record = self.get(kind, item_id)
            record.update(changes)
            record["updated"] = now()
            self.save(kind, record)
            return record

    def list(self, kind: str, *, include_deleted=False) -> list[dict]:
        if kind not in ("scenes", "runs"):
            raise ValueError("Unknown record type.")
        records, _ = self.scan(kind)
        if not include_deleted:
            records = [r for r in records if not r.get("deleted_at")]
            if kind == "runs":
                scenes = {s["id"] for s in self.list("scenes")}
                records = [r for r in records if r["scene_id"] in scenes]
        return sorted(records, key=lambda r: r["created"], reverse=True)

    def load_record(self, kind: str, path: Path):
        try:
            if not path.exists():
                return None
            record = read(path)
            if not isinstance(record, dict) or record.get("id") != valid_id(path.parent.name):
                raise ValueError("Record identity does not match its folder.")
            datetime.fromisoformat(record["created"])
            name = record["name" if kind == "scenes" else "scene_name"]
            if not isinstance(name, str) or not name.strip() or not isinstance(record["images"], list):
                raise ValueError("Invalid scene name or photo inventory.")
            for image in record["images"]:
                valid_id(image["id"])
                if any(not isinstance(image[key], str) for key in ("name", "filename", "sha256")):
                    raise ValueError("Invalid photo metadata.")
                if any(
                    not isinstance(image[key], int) or image[key] <= 0 for key in ("width", "height", "bytes")
                ):
                    raise ValueError("Invalid photo dimensions or size.")
                if (
                    image["filename"] in {"", ".", ".."}
                    or "/" in image["filename"]
                    or "\\" in image["filename"]
                ):
                    raise ValueError("Photo filenames must stay inside the scene.")
            if kind == "runs":
                from .models import RunOptions

                valid_id(record["scene_id"])
                RunOptions(**record["settings"])
                if record["status"] not in {
                    "queued",
                    "running",
                    "complete",
                    "failed",
                    "interrupted",
                    "cancelled",
                }:
                    raise ValueError("Unknown run status.")
                if not isinstance(record["stage"], str) or not isinstance(record["completed"], list):
                    raise ValueError("Invalid run stages.")
                if any(not isinstance(stage, str) for stage in record["completed"]):
                    raise ValueError("Invalid completed stage.")
            return record
        except (OSError, ValueError, TypeError, KeyError) as exc:
            raise RecordError(
                f"Cannot read {path}. Restore this record from a backup; files were left in place. {exc}"
            ) from exc

    def scan(self, kind: str):
        records, issues = [], []
        for path in (self.root / kind).glob("*/record.json"):
            try:
                record = self.load_record(kind, path)
                if record is not None:
                    records.append(record)
            except RecordError as exc:
                issues.append({"kind": kind, "path": str(path), "message": str(exc)})
        return records, issues

    def issues(self, kind: str | None = None):
        return [issue for group in ([kind] if kind else ["scenes", "runs"]) for issue in self.scan(group)[1]]

    def rename_scene(self, scene_id: str, name: str) -> dict:
        name = name.strip()
        if not 1 <= len(name) <= 100:
            raise ValueError("Give the scene a name between 1 and 100 characters.")
        with self.lock:
            scene = self.update("scenes", scene_id, name=name)
            # Names are display metadata; input hashes and run settings stay intact.
            for run in self.list("runs"):
                if run["scene_id"] == scene_id:
                    self.update("runs", run["id"], scene_name=name)
            return scene

    def trash_scene(self, scene_id: str) -> dict:
        with self.lock:
            scene = self.get("scenes", scene_id, include_deleted=True)
            if scene.get("deleted_at"):
                return scene
            if any(
                r["scene_id"] == scene_id and r["status"] in ("running", "queued") for r in self.list("runs")
            ):
                raise SceneBusyError(
                    "Stop this scene's queued or running reconstructions before deleting it."
                )
            scene.update(deleted_at=now(), updated=now())
            self.save("scenes", scene)
            return scene

    def restore_scene(self, scene_id: str) -> dict:
        with self.lock:
            scene = self.get("scenes", scene_id, include_deleted=True)
            if scene.get("purging"):
                raise RunConflictError(
                    "Permanent deletion has started for this scene. Retry deletion to clean up its remaining files."
                )
            scene.pop("deleted_at", None)
            scene["updated"] = now()
            self.save("scenes", scene)
            return scene

    def _purge_path(self, kind: str, item_id: str) -> Path:
        target = self.path(kind, item_id)
        base = self.root / kind
        # Only direct, generated scene/run folders are deletion targets. A
        # junction or symlink must never redirect a root outside the workspace.
        if base.resolve() != base or target.resolve() != target or target.parent != base:
            raise ValueError(
                "Refusing deletion: a scene or run folder is redirected outside its managed location."
            )
        if not target.is_relative_to(self.root) or target == self.root:
            raise ValueError("Refusing deletion outside the workspace.")
        if target.exists() and not target.is_dir():
            raise ValueError("Refusing deletion: a managed folder was replaced by a file.")
        return target

    def purge_scenes(self, scene_ids: list[str], *, allow_compute=False) -> dict:
        with self.lock:
            if self.issues("runs"):
                raise RunConflictError(
                    "Recover the unreadable run records before permanently deleting scenes."
                )
            if not scene_ids or len(set(scene_ids)) != len(scene_ids):
                raise ValueError("Choose one or more distinct scenes from Trash.")
            if self.compute_busy() and not allow_compute:
                raise RunConflictError(
                    "Wait for the workspace's active task before permanently deleting scenes."
                )
            runs = self.list("runs", include_deleted=True)
            plans = []
            # Validate the entire selection before deleting any files.
            for scene_id in scene_ids:
                self._purge_path("scenes", scene_id)
                scene = self.get("scenes", scene_id, include_deleted=True)
                if scene.get("id") != scene_id:
                    raise ValueError("Refusing deletion: the scene record does not match its folder.")
                if not scene.get("deleted_at"):
                    raise RunConflictError(
                        "Trash changed: a selected scene was restored. Review Trash again."
                    )
                related = [run for run in runs if run["scene_id"] == scene_id]
                if any(run["status"] in ("queued", "running") for run in related):
                    raise RunConflictError("Stop this scene's active runs before permanently deleting it.")
                run_ids = sorted(set(scene.get("purge_run_ids", [])) | {run["id"] for run in related})
                for run_id in run_ids:
                    folder = self._purge_path("runs", run_id)
                    record = read(folder / "record.json")
                    if record and record.get("scene_id") != scene_id:
                        raise ValueError("Refusing deletion: a run belongs to another scene.")
                plans.append((scene, run_ids))
            deleted, failed = [], []
            for scene, run_ids in plans:
                scene_id = scene["id"]
                # Keep a recovery record until the last file is removed. A
                # partially removed scene can be cleaned up, never restored.
                scene.update(purging=True, purge_run_ids=run_ids, purge_error=None)
                try:
                    self.save("scenes", scene)
                    for run_id in run_ids:
                        folder = self._purge_path("runs", run_id)
                        if folder.exists():
                            shutil.rmtree(folder)
                    folder = self._purge_path("scenes", scene_id)
                    for child in folder.iterdir():
                        if child.name == "record.json":
                            continue
                        if child.is_symlink() or not child.is_dir():
                            child.unlink()
                        elif os.name == "nt" and (
                            child.lstat().st_file_attributes & stat.FILE_ATTRIBUTE_REPARSE_POINT
                        ):
                            # A junction is a directory entry on Windows.
                            # Remove that entry without following its target.
                            child.rmdir()
                        else:
                            # Nested links inside a regular directory are
                            # handled by rmtree without traversing their targets.
                            shutil.rmtree(child)
                    (folder / "record.json").unlink()
                    folder.rmdir()
                    deleted.append(scene_id)
                except (OSError, ValueError) as exc:
                    message = f"Some files could not be removed. Close files or viewers using them, then retry. {exc}"
                    scene["purge_error"] = message
                    try:
                        self._purge_path("scenes", scene_id)
                        self.save("scenes", scene)
                    except (OSError, ValueError):
                        message += " The cleanup record could not be updated. Reopen Trash after checking folder permissions."
                    failed.append({"scene_id": scene_id, "message": message})
            return {"deleted_scene_ids": deleted, "failed": failed}

    def create_scene(self, name: str) -> dict:
        name = name.strip()
        if not 1 <= len(name) <= 100:
            raise ValueError("Give the scene a name between 1 and 100 characters.")
        scene = dict(id=identity(), name=name, created=now(), images=[])
        self.save("scenes", scene)
        return scene

    def create_run(self, scene_id: str, settings: dict) -> dict:
        # Serialize with Trash/import so a new job cannot appear after removal.
        with self.lock:
            self.require_idle()
            return self._create_run(scene_id, settings)

    def active_run(self) -> dict | None:
        runs = self.list("runs", include_deleted=True)
        return next((r for r in runs if r["status"] == "running"), None) or next(
            (r for r in runs if r["status"] == "queued"), None
        )

    def compute_lease(self) -> FileLock:
        # Each caller gets its own handle. Sharing a reentrant lock object would
        # let a second request in the same process accidentally pass the check.
        return FileLock(str(self.root / ".compute.lock"), timeout=0, thread_local=False)

    def compute_busy(self) -> bool:
        if self.background_task():
            return True
        try:
            with self.compute_lease():
                return False
        except Timeout:
            return True

    def background_task(self):
        from .background import active_task

        return active_task(self)

    def require_idle(self) -> None:
        if self.issues("runs"):
            raise RunConflictError("Recover the unreadable run records before starting more work.")
        run = self.active_run()
        if run:
            raise RunConflictError(
                f"A reconstruction is already {run['status']} for “{run['scene_name']}”. "
                "Finish or stop it before starting another.",
                run,
            )
        if self.compute_busy():
            raise RunConflictError(
                "Another viewer, GPU check, or setup task owns this workspace. Let it finish first."
            )

    def resume_run(self, run_id: str, runtime: dict) -> dict:
        with self.lock:
            run = self.get("runs", run_id)
            if run["status"] not in ("failed", "interrupted", "cancelled"):
                raise RunConflictError(
                    "Only a stopped or failed run can be resumed. Use a new run for different settings.", run
                )
            self.require_idle()
            if run.get("runtime") and run["runtime"] != runtime:
                raise RunConflictError(
                    "Restore this run's runtime settings before resuming, or create a new run."
                )
            return self.update("runs", run_id, status="queued", cancel_requested=False, error=None)

    def stop_run(self, run_id: str) -> dict:
        with self.lock:
            run = self.get("runs", run_id)
            if run.get("cancel_requested") and run["status"] in ("running", "cancelled", "interrupted"):
                return run
            if run["status"] not in ("queued", "running"):
                raise RunConflictError("This run is not active.")
            return self.update(
                "runs",
                run_id,
                cancel_requested=True,
                status="cancelled" if run["status"] == "queued" else "running",
            )

    def _create_run(self, scene_id: str, settings: dict) -> dict:
        from .models import RunOptions

        options = RunOptions(**settings).model_dump()
        scene = self.get("scenes", scene_id)
        image_ids = options.pop("image_ids")
        selected = set([i["id"] for i in scene["images"]] if image_ids is None else image_ids)
        images = [i for i in scene["images"] if i["id"] in selected]
        if options["matching"] == "sequential":
            # Original capture names survive imports made in separate batches.
            def capture_order(image):
                parts = re.split(r"(\d+)", image["name"].casefold())
                return tuple((1, int(p)) if p.isdigit() else (0, p) for p in parts), image["sha256"]

            images.sort(key=capture_order)
        if len(selected) != len(images):
            raise ValueError("The selection contains photos that are not in this scene.")
        if len(images) < 12:
            raise ValueError(
                "Choose at least 12 overlapping photos. Around 80–200 is a useful first capture."
            )
        if options["matching"] == "exhaustive" and len(images) > 500:
            raise ValueError(
                "For more than 500 photos choose sequential matching and use capture-ordered filenames."
            )
        run = dict(
            id=identity(),
            scene_id=scene_id,
            scene_name=scene["name"],
            created=now(),
            status="queued",
            stage="queued",
            completed=[],
            settings=options,
            images=images,
            error=None,
            cancel_requested=False,
            image_order="capture-filename-v1" if options["matching"] == "sequential" else "import-v1",
        )
        # This snapshot belongs to the run. Future imports do not alter it.
        self.save("runs", run)
        return run
