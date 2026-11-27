"""Loopback-only API and bundled frontend. GPU work runs outside request handlers."""

from __future__ import annotations

import os
import shutil
import socket
import subprocess
import threading
from contextlib import asynccontextmanager
from functools import wraps
from pathlib import Path
from urllib.parse import urlparse

from fastapi import FastAPI, File, HTTPException, Request, UploadFile
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from .background import Tasks, task_path
from .images import MAX_BYTES, estimate, import_image
from .models import RunOptions, RuntimeOptions, SceneRequest
from .pipeline import LABELS, STAGES, Queue, tail, terminate
from .runtime import Runtime
from .store import RunConflictError, SceneBusyError, Store, now, read, valid_id, write


class StorageRequest(BaseModel):
    path: str


class PurgeRequest(BaseModel):
    scene_ids: list[str] = Field(min_length=1)
    workspace: str
    confirmation: str


class ReviewRequest(BaseModel):
    profile: str
    reviewed: bool


class SetupRequest(BaseModel):
    profile: str | None = None
    repair: bool = False
    reviewed: bool = False


class Services:
    def __init__(self, home: Path, worker=True):
        self.home = home.expanduser().resolve()
        self.home.mkdir(parents=True, exist_ok=True)
        self.settings = read(
            self.home / "app.json", {"workspace": str(self.home), "runtime": RuntimeOptions().model_dump()}
        )
        self.store = Store(Path(self.settings["workspace"]))
        self.queue = Queue(self.store, self.runtime)
        self.worker_enabled = worker
        self.diagnostic = {"state": "checking", "checks": [], "verified": False}
        self.diagnostic_lock = threading.Lock()
        self.control_lock = threading.RLock()
        self.diagnostic_verify = False
        self.viewers = {}
        self.viewer_leases = {}
        self.importing = {}
        self.setup_job = {"state": "idle"}
        self.tasks = Tasks(self.store, self.home)
        self.background_seen = None

    def refresh_background(self):
        task = self.store.background_task() or read(task_path(self.store), {})
        if not task:
            return None
        state = task.get("state")
        if task.get("kind") == "setup":
            self.setup_job = {
                "started": task.get("started"),
                "error": task.get("error"),
                "state": "running"
                if state in {"starting", "running"}
                else "failed"
                if state in {"recovery", "interrupted"}
                else state,
            }
        seen = task.get("id"), state
        if self.background_seen != seen:
            self.background_seen = seen
            if (
                state in {"complete", "failed", "interrupted"}
                and not self.tasks.closing.is_set()
                and not self.diagnostic_lock.locked()
            ):
                self.check()
            elif task.get("kind") == "verification" and state in {"starting", "running"}:
                self.diagnostic = {**self.diagnostic, "state": "verifying", "verified": False}
        return {key: task[key] for key in ("id", "kind", "state", "error", "stop_requested") if key in task}

    def runtime(self):
        return Runtime(self.settings.get("runtime", {}))

    def save_settings(self):
        write(self.home / "app.json", self.settings)

    def verification_record(self):
        try:
            value = read(self.home / "diagnostics/verification.json", {})
            return value if isinstance(value, dict) else {}
        except (OSError, ValueError):
            # A damaged cache must request verification, never prevent launch.
            return {}

    def apply_verification(self, result):
        record = self.verification_record()
        result["verified"] = False
        if not result.get("fingerprint") or record.get("fingerprint") != result["fingerprint"]:
            result["verification_changed"] = bool(record.get("fingerprint"))
            return result
        result["verified_at"] = record.get("checked")
        if (
            record.get("passed") is True
            and isinstance(record.get("report"), dict)
            and record["report"].get("passed") is True
        ):
            result.update(verified=True, gpu_test=record.get("report"))
            if result["state"] == "verify":
                result["state"] = "ready"
        else:
            result.update(verification_error=record.get("error"), state="attention")
        return result

    def serialized(self, operation):
        @wraps(operation)
        def call(*args, **kwargs):
            # All action admission uses the same lock order. The disk lock also
            # protects requests from another app process sharing this workspace.
            with self.control_lock, self.store.lock:
                return operation(*args, **kwargs)

        return call

    def live_viewers(self):
        for run_id, (process, _) in list(self.viewers.items()):
            if process.poll() is not None:
                self.release_viewer(run_id, process)
        return dict(self.viewers)

    def release_viewer(self, run_id, process):
        with self.control_lock:
            if self.viewers.get(run_id, (None,))[0] is process:
                self.viewers.pop(run_id, None)
                lease = self.viewer_leases.pop(run_id, None)
                if lease:
                    lease.release()

    def activity(self):
        task = self.store.background_task()
        if task:
            return {
                "kind": "recovery" if task["state"] == "recovery" else task.get("kind", "external"),
                "message": task.get("error")
                or "A setup or GPU check still owns this workspace. Let it finish or stop it safely.",
            }
        if self.store.issues("runs"):
            return {
                "kind": "recovery",
                "message": "Recover the unreadable run records before starting more GPU work. Your files have been left in place.",
            }
        run = self.store.active_run()
        if run:
            return {
                "kind": "reconstruction",
                "message": f"Reconstruction {run['status']} for “{run['scene_name']}”.",
                "run_id": run["id"],
                "scene_id": run["scene_id"],
            }
        if self.setup_job["state"] == "running":
            return {
                "kind": "setup",
                "message": "Reconstruction tools are being installed. Wait for setup to finish.",
            }
        if self.diagnostic_lock.locked():
            return {
                "kind": "verification" if self.diagnostic_verify else "diagnostics",
                "message": "GPU verification is running."
                if self.diagnostic_verify
                else "Checking reconstruction tools.",
            }
        viewers = self.live_viewers()
        if viewers:
            run_id = next(iter(viewers))
            run = self.store.get("runs", run_id)
            return {
                "kind": "viewer",
                "message": "Stop the open 3D viewer before starting other GPU work.",
                "run_id": run_id,
                "scene_id": run["scene_id"],
            }
        if self.store.compute_busy():
            return {
                "kind": "external",
                "message": "Another app process is using this workspace. Wait for its viewer, GPU check, or setup to finish.",
            }
        return None

    def require_idle(self):
        activity = self.activity()
        if activity:
            raise RunConflictError(activity["message"], self.store.active_run())

    def reserve_compute(self):
        from filelock import Timeout

        lease = self.store.compute_lease()
        try:
            lease.acquire()
        except Timeout as exc:
            raise RunConflictError("This workspace is already being used by another GPU task.") from exc
        return lease

    def check(self, verify=False):
        with self.control_lock, self.store.lock:
            if self.tasks.closing.is_set() or self.store.background_task():
                return False
            if self.diagnostic_lock.locked():
                return False
            if verify:
                self.require_idle()
            lease = self.reserve_compute() if verify else None
            self.diagnostic_verify = verify
            self.diagnostic_lock.acquire()

        def work():
            result = None
            try:
                self.diagnostic = {"state": "checking", "checks": [], "verified": False}
                result = self.apply_verification(self.runtime().readiness(self.store.root))
                if verify and result.get("fingerprint") and result["state"] != "unsupported":
                    result["state"] = "verifying"
                    result["verified"] = False
                    self.diagnostic = result
                    cmd = self.runtime().engine_command("verify", self.home / "diagnostics")
                    (self.home / "diagnostics").mkdir(exist_ok=True)
                    (self.home / "diagnostics/gpu-verification.json").unlink(missing_ok=True)
                    self.tasks.run(
                        "verification",
                        cmd,
                        self.home / "gpu-check.log",
                        lease=lease,
                        timeout=900,
                        fingerprint=result["fingerprint"],
                    )
                    # The supervisor saves the result even if the server exits.
                    result.pop("verification_error", None)
                    result["state"] = (
                        "verify" if all(c["state"] == "ready" for c in result["checks"]) else "attention"
                    )
                    result = self.apply_verification(result)
                result["checked"] = now()
                self.diagnostic = result
            except Exception as exc:
                failed_at = now()
                if verify:
                    # A failed retest must not revive an older success on restart.
                    try:
                        write(
                            self.home / "diagnostics/verification.json",
                            {
                                "fingerprint": (result or {}).get("fingerprint"),
                                "passed": False,
                                "checked": failed_at,
                                "error": str(exc),
                            },
                        )
                    except OSError:
                        pass
                self.diagnostic = {
                    **(result or {"checks": []}),
                    "state": "attention",
                    "verified": False,
                    "error": str(exc),
                    **(
                        {"verification_error": str(exc), "verified_at": failed_at}
                        if verify and result
                        else {}
                    ),
                }
            finally:
                if lease:
                    lease.release()
                self.diagnostic_lock.release()

        try:
            threading.Thread(target=work, daemon=True).start()
        except Exception:
            if lease:
                lease.release()
            self.diagnostic_lock.release()
            raise
        return True

    def busy(self):
        return any(r["status"] in ("running", "queued") for r in self.store.list("runs"))


def create_app(home: Path | None = None, worker=True):
    services = Services(
        home or Path(os.getenv("PHOTOSPLAT_WORKSPACE", str(Path.home() / "PhotoToSplat"))), worker
    )

    @asynccontextmanager
    async def lifespan(app):
        if worker:
            services.queue.start()
            services.check()
        yield
        services.tasks.close()
        services.queue.close()
        for run_id, (p, _) in list(services.viewers.items()):
            terminate(p)
            services.release_viewer(run_id, p)

    app = FastAPI(title="Photo to Splat", lifespan=lifespan)
    app.state.services = services

    @app.middleware("http")
    async def local_only(request: Request, call_next):
        host = request.headers.get("host", "").split(":")[0]
        if host not in ("127.0.0.1", "localhost", "testserver"):
            return JSONResponse({"detail": "This application is local-only."}, status_code=403)
        origin = request.headers.get("origin")
        if origin and urlparse(origin).netloc != request.headers.get("host"):
            return JSONResponse(
                {"detail": "Use the application's own local page for this request."}, status_code=403
            )
        return await call_next(request)

    @app.exception_handler(ValueError)
    async def invalid(_, exc):
        return JSONResponse({"detail": str(exc)}, status_code=400)

    @app.exception_handler(RunConflictError)
    async def conflict(_, exc):
        return JSONResponse({"detail": str(exc), "active_run": exc.run}, status_code=409)

    @app.exception_handler(FileNotFoundError)
    async def missing(_, exc):
        return JSONResponse({"detail": str(exc)}, status_code=404)

    @app.get("/api/state")
    @services.serialized
    def state():
        background = services.refresh_background()
        return {
            "settings": services.settings,
            "diagnostic": services.diagnostic,
            "scenes": services.store.list("scenes"),
            "runs": services.store.list("runs"),
            "trash": [s for s in services.store.list("scenes", include_deleted=True) if s.get("deleted_at")],
            "viewers": {
                run_id: {"url": f"http://localhost:{port}"}
                for run_id, (process, port) in services.viewers.items()
                if process.poll() is None
            },
            "setup": services.setup_job,
            "background": background,
            "record_issues": services.store.issues(),
            "setup_profile": services.runtime().profile(),
            "setup_reviewed": services.settings.get("setup_review") == services.runtime().profile(),
            "activity": services.activity(),
            "stages": [{"id": s, "label": LABELS[s]} for s in STAGES],
        }

    @app.post("/api/diagnostics")
    @services.serialized
    def check(verify: bool = False):
        services.require_idle()
        if not services.check(verify):
            raise HTTPException(409, "A tool or GPU check is already running.")
        return {"started": True}

    @app.put("/api/runtime")
    @services.serialized
    def runtime(options: RuntimeOptions):
        services.require_idle()
        services.settings["runtime"] = options.model_dump()
        services.save_settings()
        services.check()
        return services.settings

    @app.put("/api/storage")
    @services.serialized
    def storage(options: StorageRequest):
        services.require_idle()
        if services.importing:
            raise HTTPException(409, "Wait for photo import to finish before switching workspaces.")
        if not Path(options.path).is_absolute():
            raise ValueError("Choose an absolute local folder path.")
        new_store = Store(Path(options.path))
        services.queue.close()
        services.store = new_store
        services.tasks = Tasks(new_store, services.home)
        services.background_seen = None
        services.queue = Queue(new_store, services.runtime)
        if worker:
            services.queue.start()
        services.settings["workspace"] = str(new_store.root)
        services.save_settings()
        services.check()
        return services.settings

    @app.get("/api/folders")
    def folders(path: str = ""):
        target = Path(path).expanduser() if path else services.store.root
        if not target.is_absolute():
            raise ValueError("Choose an absolute directory.")
        target = target.resolve()
        while not target.is_dir() and target.parent != target:
            target = target.parent
        try:
            children = [
                {"name": p.name, "path": str(p)}
                for p in sorted(target.iterdir(), key=lambda p: p.name.lower())
                if p.is_dir() and not p.name.startswith(".")
            ][:200]
        except (PermissionError, OSError) as exc:
            raise HTTPException(403, "This folder is not readable. Choose another location.") from exc
        roots = (
            [f"{chr(i)}:\\" for i in range(67, 91) if Path(f"{chr(i)}:\\").is_dir()]
            if os.name == "nt"
            else ["/", str(Path.home()), "/mnt"]
        )
        return {"path": str(target), "parent": str(target.parent), "folders": children, "roots": roots}

    @app.post("/api/setup/review")
    @services.serialized
    def review_setup(request: ReviewRequest):
        if request.profile != services.runtime().profile():
            raise RunConflictError("The tool profile changed. Review the current setup requirements.")
        services.settings["setup_review"] = request.profile if request.reviewed else None
        services.save_settings()
        return {"reviewed": request.reviewed}

    @app.post("/api/setup")
    @services.serialized
    def setup(request: SetupRequest | None = None):
        services.require_idle()
        request = request or SetupRequest()
        rt = services.runtime()
        # A stale tab cannot turn a healthy environment into another installation.
        fresh = services.apply_verification(rt.readiness(services.store.root))
        services.diagnostic = fresh
        if fresh.get("tools_installed") and not request.repair:
            return {
                "state": "already_installed",
                "message": "Tools are already installed. No installation was started.",
            }
        if fresh["state"] == "unsupported":
            raise RunConflictError("Resolve the platform/NVIDIA driver check before installing GPU tools.")
        if rt.options.train_prefix or rt.options.sfm_prefix:
            raise RunConflictError(
                "Custom environments are selected. Fix their paths or switch to managed environments; managed setup will not replace them."
            )
        if request.profile != rt.profile():
            raise RunConflictError(
                "The tool profile changed. Refresh and review the current setup requirements."
            )
        if not (request.reviewed or services.settings.get("setup_review") == request.profile):
            raise RunConflictError("Review the installation requirements and storage allowance first.")
        if request.repair and not request.reviewed:
            raise RunConflictError("Confirm managed repair before starting it.")
        if fresh.get("free_bytes", 0) < 5 * 1024**3:
            raise RunConflictError(
                "Free workspace storage before installing tools. The tool volume needs additional space too."
            )
        services.settings["setup_review"] = request.profile
        services.save_settings()
        script = Path(__file__).with_name("setup-runtime.sh")
        from .runtime import linux_path

        components = ["compiler", "colmap", "training"] if request.repair else fresh["missing_tools"]
        command = [
            "bash",
            linux_path(script) if rt.wsl else str(script),
            *(["--repair"] if request.repair else []),
            *components,
        ]
        if rt.wsl:
            command = ["wsl", "-d", rt.options.distro, "--", *command]
        elif os.name == "nt":
            raise ValueError("Select WSL mode first.")
        lease = services.reserve_compute()
        services.setup_job = {"state": "running", "started": now()}

        def install():
            try:
                result = services.tasks.run("setup", command, services.home / "setup.log", lease=lease)
                with services.control_lock, services.store.lock:
                    services.setup_job = {
                        "state": "complete" if result.returncode == 0 else "failed",
                        "error": tail(services.home / "setup.log", 2000) if result.returncode else None,
                    }
                    if result.returncode == 0 and not services.tasks.closing.is_set():
                        services.check()
            except Exception as exc:
                services.setup_job = {"state": "failed", "error": str(exc)}
            finally:
                lease.release()

        try:
            threading.Thread(target=install, daemon=True).start()
        except Exception as exc:
            lease.release()
            services.setup_job = {"state": "failed", "error": str(exc)}
            raise
        return services.setup_job

    @app.post("/api/background/{task_id}/stop")
    @services.serialized
    def stop_background(task_id: str):
        services.tasks.stop(valid_id(task_id))
        return {"stopping": True}

    @app.get("/api/setup/log")
    def setup_log():
        return {"text": tail(services.home / "setup.log")}

    @app.post("/api/scenes", status_code=201)
    def scene(request: SceneRequest):
        return services.store.create_scene(request.name)

    @app.patch("/api/scenes/{scene_id}")
    def rename_scene(scene_id: str, request: SceneRequest):
        return services.store.rename_scene(scene_id, request.name)

    @app.delete("/api/scenes/{scene_id}")
    @services.serialized
    def trash_scene(scene_id: str):
        if services.importing.get(scene_id):
            raise HTTPException(409, "Wait for this scene's photo import to finish before deleting it.")
        with services.store.lock:
            for run_id, (process, _) in services.viewers.items():
                run = services.store.get("runs", run_id, include_deleted=True)
                if run["scene_id"] == scene_id and process.poll() is None:
                    raise HTTPException(409, "Stop this scene's 3D viewer before deleting it.")
            try:
                return services.store.trash_scene(scene_id)
            except SceneBusyError as exc:
                raise HTTPException(409, str(exc)) from exc

    @app.post("/api/scenes/{scene_id}/restore")
    @services.serialized
    def restore_scene(scene_id: str):
        return services.store.restore_scene(scene_id)

    @app.post("/api/trash/purge")
    @services.serialized
    def purge_trash(request: PurgeRequest):
        if request.confirmation != "DELETE":
            raise ValueError("Type DELETE to confirm permanent deletion.")
        if Path(request.workspace).expanduser().resolve() != services.store.root:
            raise RunConflictError("The workspace changed. Open Trash again and review the selected scenes.")
        targets = set(request.scene_ids)
        if (
            services.importing
            or services.setup_job["state"] == "running"
            or services.diagnostic_lock.locked()
        ):
            raise RunConflictError(
                "Wait for photo import, setup, and checks to finish before emptying Trash."
            )
        viewers = services.live_viewers()
        for run_id in viewers:
            if services.store.get("runs", run_id, include_deleted=True)["scene_id"] in targets:
                raise RunConflictError("Stop this scene's viewer before permanently deleting it.")
        active = services.store.active_run()
        if active and active["scene_id"] in targets:
            raise RunConflictError("Stop this scene's active run before permanently deleting it.")
        # Unrelated, identified work only uses its own scene/run folders. An
        # unknown compute owner stays protected by Store's conservative default.
        result = services.store.purge_scenes(request.scene_ids, allow_compute=bool(viewers or active))
        free = shutil.disk_usage(services.store.root).free
        services.diagnostic["free_bytes"] = free
        for check in services.diagnostic.get("checks", []):
            if check["id"] == "storage":
                check.update(
                    detail=f"{free / 1024**3:.1f} GiB available",
                    state="ready" if free > 5 * 1024**3 else "attention",
                )
        return result

    @app.post("/api/scenes/{scene_id}/photos")
    async def photos(scene_id: str, files: list[UploadFile] = File(...)):
        if len(files) > 16:
            raise ValueError("Import photos in batches of up to 16.")
        with services.control_lock:
            store = services.store
            store.get("scenes", scene_id)
            services.importing[scene_id] = services.importing.get(scene_id, 0) + 1
        imported, errors = [], []
        try:
            for file in files:
                try:
                    if shutil.disk_usage(store.root).free < MAX_BYTES * 2:
                        raise ValueError("Not enough free workspace space for another photo.")
                    payload = await file.read(MAX_BYTES + 1)
                    imported.append(import_image(store, scene_id, file.filename or "photo.jpg", payload))
                except ValueError as exc:
                    errors.append(str(exc))
                finally:
                    await file.close()
            return {"imported": imported, "errors": errors}
        finally:
            with services.control_lock:
                remaining = services.importing.get(scene_id, 1) - 1
                if remaining:
                    services.importing[scene_id] = remaining
                else:
                    services.importing.pop(scene_id, None)

    @app.get("/api/scenes/{scene_id}/thumb/{image_id}")
    def thumb(scene_id: str, image_id: str):
        services.store.get("scenes", scene_id)
        path = services.store.path("scenes", scene_id) / "thumbs" / f"{valid_id(image_id)}.jpg"
        if not path.is_file():
            raise HTTPException(404, "Thumbnail not found.")
        return FileResponse(path)

    @app.post("/api/scenes/{scene_id}/estimate")
    def storage_estimate(scene_id: str, options: RunOptions):
        scene = services.store.get("scenes", scene_id)
        images = [i for i in scene["images"] if options.image_ids is None or i["id"] in options.image_ids]
        return {
            **estimate(images, options.max_size),
            "free_bytes": shutil.disk_usage(services.store.root).free,
        }

    @app.post("/api/scenes/{scene_id}/runs", status_code=201)
    @services.serialized
    def start(scene_id: str, options: RunOptions):
        services.require_idle()
        scene = services.store.get("scenes", scene_id)
        images = [i for i in scene["images"] if options.image_ids is None or i["id"] in options.image_ids]
        needed = estimate(images, options.max_size)["working_low_bytes"]
        if shutil.disk_usage(services.store.root).free < needed:
            raise ValueError(
                "The workspace has less free space than the lower planning estimate. Choose another drive."
            )
        return services.store.create_run(scene_id, options.model_dump())

    @app.post("/api/runs/{run_id}/resume")
    @services.serialized
    def resume(run_id: str):
        services.require_idle()
        return services.store.resume_run(run_id, services.runtime().options.model_dump())

    @app.post("/api/runs/{run_id}/stop")
    @services.serialized
    def stop(run_id: str):
        return services.store.stop_run(run_id)

    @app.get("/api/runs/{run_id}")
    def run_info(run_id: str):
        run = services.store.get("runs", run_id)
        root = services.store.path("runs", run_id)
        return {
            **run,
            "camera_report": read(root / "camera-report.json"),
            "metrics": read(root / "metrics.json"),
            "renders": [p.name for p in sorted((root / "renders").glob("*.png"))],
            "export_ready": (root / "export/splat.ply").is_file(),
        }

    @app.get("/api/runs/{run_id}/log")
    def log(run_id: str, stage: str = "train"):
        services.store.get("runs", run_id)
        if stage not in STAGES:
            raise ValueError("Unknown stage.")
        return {"text": tail(services.store.path("runs", run_id) / "logs" / f"{stage}.log")}

    @app.get("/api/runs/{run_id}/render/{filename}")
    def render(run_id: str, filename: str):
        services.store.get("runs", run_id)
        if not __import__("re").fullmatch(r"eval_img_\d+\.png", filename):
            raise ValueError("Unknown render filename.")
        path = services.store.path("runs", run_id) / "renders" / filename
        if not path.is_file():
            raise HTTPException(404, "This comparison has not been rendered yet.")
        return FileResponse(path)

    @app.get("/api/runs/{run_id}/download/{artifact}")
    def download(run_id: str, artifact: str):
        services.store.get("runs", run_id)
        allowed = {
            "splat": "export/splat.ply",
            "metrics": "metrics.json",
            "manifest": "record.json",
            "cameras": "camera-report.json",
        }
        if artifact not in allowed:
            raise ValueError("Unknown artifact.")
        path = services.store.path("runs", run_id) / allowed[artifact]
        if not path.is_file():
            raise HTTPException(404, "This artifact is not ready yet.")
        return FileResponse(path, filename=path.name)

    @app.post("/api/runs/{run_id}/viewer")
    @services.serialized
    def viewer(run_id: str):
        run = services.store.get("runs", run_id)
        if "train" not in run["completed"]:
            raise HTTPException(409, "Finish training before opening the viewer.")
        if run_id in services.live_viewers():
            return {"url": f"http://localhost:{services.viewers[run_id][1]}"}
        services.require_idle()
        port = next((p for p in range(7010, 7030) if port_free(p)), None)
        if not port:
            raise HTTPException(409, "No local viewer port is available.")
        root = services.store.path("runs", run_id)
        lease = services.reserve_compute()
        try:
            with (root / "viewer.log").open("ab") as output:
                p = subprocess.Popen(
                    services.runtime().engine_command("view", root, str(port)),
                    stdout=output,
                    stderr=subprocess.STDOUT,
                )
        except Exception:
            lease.release()
            raise
        services.viewers[run_id] = (p, port)
        services.viewer_leases[run_id] = lease

        def watch():
            try:
                p.wait()
            finally:
                services.release_viewer(run_id, p)

        try:
            threading.Thread(target=watch, daemon=True).start()
        except Exception:
            terminate(p)
            services.release_viewer(run_id, p)
            raise
        return {"url": f"http://localhost:{port}", "starting": True}

    @app.post("/api/viewers/stop")
    @services.serialized
    def stop_viewers():
        for run_id, (p, _) in list(services.viewers.items()):
            terminate(p)
            services.release_viewer(run_id, p)
        return {"stopped": True}

    web = Path(__file__).parent / "web"
    if (web / "index.html").is_file():
        app.mount("/", StaticFiles(directory=web, html=True), name="frontend")
    else:

        @app.get("/")
        def not_built():
            return {"detail": "Frontend assets are missing. Run the documented frontend build."}

    return app


def port_free(port):
    with socket.socket() as sock:
        return sock.connect_ex(("127.0.0.1", port)) != 0
