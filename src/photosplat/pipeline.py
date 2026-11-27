"""The CLI and dashboard share this worker. Stages commit only after success."""

from __future__ import annotations

import hashlib
import json
import math
import re
import subprocess
import threading
import time
from pathlib import Path

import psutil
from filelock import FileLock, Timeout

from .images import prepare
from .runtime import Runtime, linux_path
from .store import Store, digest, now, read, write

STAGES = ["verify", "prepare", "features", "matches", "cameras", "convert", "train", "evaluate", "export"]
LABELS = dict(
    verify="Verifying GPU execution",
    prepare="Preparing working images",
    features="Finding visual features",
    matches="Matching overlapping photos",
    cameras="Estimating camera positions",
    convert="Checking camera geometry",
    train="Learning the Gaussian scene",
    evaluate="Rendering held-out views",
    export="Exporting the scene",
)


def fingerprint(run):
    content = {"settings": run["settings"], "images": [(i["id"], i["sha256"]) for i in run["images"]]}
    return hashlib.sha256(json.dumps(content, sort_keys=True).encode()).hexdigest()


def tail(path: Path, limit=16000):
    if not path.exists():
        return ""
    with path.open("rb") as stream:
        stream.seek(max(0, path.stat().st_size - limit))
        text = stream.read().decode("utf-8", errors="replace")
    return re.sub(r"\x1b\[[0-9;]*[A-Za-z]", "", text)


def terminate(process):
    try:
        parent = psutil.Process(process.pid)
        children = parent.children(recursive=True)
        for child in reversed(children):
            child.terminate()
        parent.terminate()
        _, alive = psutil.wait_procs([*children, parent], timeout=5)
        for p in alive:
            p.kill()
    except psutil.NoSuchProcess:
        pass


class InterruptedRun(Exception):
    pass


class Pipeline:
    def __init__(self, store: Store, runtime: Runtime, stop: threading.Event | None = None):
        self.store, self.runtime = store, runtime
        self.stop = stop or threading.Event()

    def execute(self, run_id, stage, command):
        root = self.store.path("runs", run_id)
        logs = root / "logs"
        logs.mkdir(exist_ok=True)
        with self.store.lock:
            commands = read(root / "commands.json", [])
            commands.append({"time": now(), "stage": stage, "argv": command})
            write(root / "commands.json", commands)
        with (logs / f"{stage}.log").open("ab") as output:
            process = subprocess.Popen(command, stdout=output, stderr=subprocess.STDOUT)
            self.store.update("runs", run_id, pid=process.pid)
            while process.poll() is None:
                if self.stop.is_set() or self.store.get("runs", run_id).get("cancel_requested"):
                    terminate(process)
                    raise InterruptedRun(
                        "Stopped. Completed stages and the latest training checkpoint are preserved."
                    )
                time.sleep(0.3)
        if process.returncode:
            raise RuntimeError(
                f"{LABELS.get(stage, stage)} failed. Open its log for details.\n"
                + tail(logs / f"{stage}.log", 2200)
            )

    def help(self, run_id, command):
        root = self.store.path("runs", run_id)
        output = self.runtime.capture("sfm", ["colmap", command, "-h"])
        write(root / f"{command}-options.json", {"help": output})
        return output

    @staticmethod
    def option(help_text, *names):
        for name in names:
            if name in help_text:
                return name
        raise ValueError(f"Unsupported COLMAP option set: {names}. Use the documented pinned version.")

    def run(self, run_id):
        run = self.store.get("runs", run_id)
        root = self.store.path("runs", run_id)
        expected = fingerprint(run)
        if run.get("fingerprint") and run["fingerprint"] != expected:
            raise ValueError(
                "This run's inputs or settings changed. Create a new run rather than mixing artifacts."
            )
        for item in run["images"]:
            source = self.store.path("scenes", run["scene_id"]) / "originals" / item["filename"]
            if digest(source) != item["sha256"]:
                raise ValueError("A source snapshot changed. Restore it or create a new scene.")
        if "prepare" in run["completed"]:
            for item in read(root / "dataset/capture.json")["images"]:
                if digest(root / "dataset/images" / item["prepared"]) != item["prepared_sha256"]:
                    raise ValueError(
                        "A prepared photo changed. Create a new run to avoid stale camera calibration."
                    )
        for relative, checksum in run.get("artifacts", {}).items():
            if digest(root / relative) != checksum:
                raise ValueError(f"Saved stage artifact changed: {relative}. Create a new run.")
        previous_gpu = read(root / "gpu-verification.json")
        if previous_gpu and previous_gpu.get("versions"):
            engine = linux_path(self.runtime.engine) if self.runtime.wsl else str(self.runtime.engine)
            target = linux_path(root) if self.runtime.wsl else str(root)
            current_versions = json.loads(
                self.runtime.capture("train", ["python", engine, "environment", target])
            )
            if current_versions != previous_gpu["versions"]:
                raise ValueError(
                    "Training package versions changed since this run. Restore its environment or start a new run."
                )
        run = self.store.update(
            "runs",
            run_id,
            fingerprint=expected,
            status="running",
            error=None,
            runtime=self.runtime.options.model_dump(),
            started=run.get("started", now()),
        )
        data = root / "dataset"
        mapped_data = linux_path(data) if self.runtime.wsl else str(data)
        for stage in STAGES:
            if stage in run["completed"]:
                continue
            if self.stop.is_set() or self.store.get("runs", run_id).get("cancel_requested"):
                raise InterruptedRun("Stopped before the next stage. You can resume this run.")
            self.store.update("runs", run_id, stage=stage, stage_started=now())
            if stage == "prepare":
                prepare(self.store, run)
            elif stage in ("verify", "convert", "train", "evaluate", "export"):
                self.execute(run_id, stage, self.runtime.engine_command(stage, root))
            elif stage == "features":
                (data / "colmap/sparse").mkdir(parents=True, exist_ok=True)
                capture = read(data / "capture.json")["images"]
                sizes = {(i["prepared_width"], i["prepared_height"]) for i in capture}
                focal35 = {i["focal_35mm"] for i in capture}
                camera_models = {i["model"] for i in capture}
                mode = run["settings"]["camera_mode"]
                shared = mode == "shared" or (
                    mode == "auto" and len(sizes) == 1 and len(focal35) == 1 and len(camera_models) == 1
                )
                if mode == "shared" and (len(sizes) != 1 or len(focal35) != 1 or len(camera_models) != 1):
                    raise ValueError(
                        "Shared calibration needs one lens and consistent dimensions. Choose per-image mode."
                    )
                help_text = self.help(run_id, "feature_extractor")
                gpu = self.option(help_text, "--FeatureExtraction.use_gpu", "--SiftExtraction.use_gpu")
                size = self.option(
                    help_text, "--FeatureExtraction.max_image_size", "--SiftExtraction.max_image_size"
                )
                arguments = [
                    "colmap",
                    "feature_extractor",
                    "--database_path",
                    mapped_data + "/colmap/database.db",
                    "--image_path",
                    mapped_data + "/images",
                    "--ImageReader.camera_model",
                    "SIMPLE_RADIAL",
                    "--ImageReader.single_camera",
                    "1" if shared else "0",
                    gpu,
                    "1" if run["settings"]["sfm_gpu"] else "0",
                    size,
                    str(run["settings"]["max_size"]),
                ]
                if shared:
                    width, height = next(iter(sizes))
                    f35 = next(iter(focal35))
                    focal = (
                        f35 / math.hypot(36, 24) * math.hypot(width, height)
                        if f35
                        else 1.2 * max(width, height)
                    )
                    arguments += ["--ImageReader.camera_params", f"{focal},{width / 2},{height / 2},0"]
                self.execute(run_id, stage, self.runtime.command("sfm", arguments))
            elif stage == "matches":
                matcher = (
                    "sequential_matcher"
                    if run["settings"]["matching"] == "sequential"
                    else "exhaustive_matcher"
                )
                help_text = self.help(run_id, matcher)
                gpu = self.option(help_text, "--FeatureMatching.use_gpu", "--SiftMatching.use_gpu")
                guided = self.option(
                    help_text, "--FeatureMatching.guided_matching", "--SiftMatching.guided_matching"
                )
                self.execute(
                    run_id,
                    stage,
                    self.runtime.command(
                        "sfm",
                        [
                            "colmap",
                            matcher,
                            "--database_path",
                            mapped_data + "/colmap/database.db",
                            gpu,
                            "1" if run["settings"]["sfm_gpu"] else "0",
                            guided,
                            "1",
                        ],
                    ),
                )
            elif stage == "cameras":
                self.execute(
                    run_id,
                    stage,
                    self.runtime.command(
                        "sfm",
                        [
                            "colmap",
                            "mapper",
                            "--database_path",
                            mapped_data + "/colmap/database.db",
                            "--image_path",
                            mapped_data + "/images",
                            "--output_path",
                            mapped_data + "/colmap/sparse",
                            "--Mapper.num_threads",
                            "8",
                        ],
                    ),
                )
            run["completed"].append(stage)
            artifacts = run.get("artifacts", {})
            if stage == "convert":
                for name in ("dataset/transforms.json", "dataset/sparse_pc.ply"):
                    artifacts[name] = digest(root / name)
            self.store.update("runs", run_id, completed=run["completed"], artifacts=artifacts, pid=None)
            run["artifacts"] = artifacts
        self.store.update("runs", run_id, status="complete", stage="complete", finished=now(), pid=None)


class Queue:
    def __init__(self, store, runtime_getter):
        self.store, self.runtime_getter = store, runtime_getter
        self.stop_event = threading.Event()
        self.thread = None

    def start(self):
        self.thread = threading.Thread(target=self.loop, daemon=True, name="photosplat-worker")
        self.thread.start()

    def close(self):
        self.stop_event.set()
        if self.thread:
            self.thread.join(timeout=10)

    def loop(self):
        lock = FileLock(str(self.store.root / ".worker.lock"))
        while not self.stop_event.is_set():
            try:
                with lock.acquire(timeout=0):
                    # Holding the workspace lock proves no other managed worker owns these jobs.
                    for stale in self.store.list("runs"):
                        if stale["status"] == "running":
                            # A crashed server can leave a child alive. Do not launch a
                            # competing GPU job or kill an unrelated recycled PID.
                            pid = stale.get("pid")
                            try:
                                orphan = psutil.Process(pid) if pid else None
                                owned = orphan and any(
                                    "runtime.sh" in arg and "photosplat" in arg for arg in orphan.cmdline()
                                )
                                if owned:
                                    self.store.update(
                                        "runs",
                                        stale["id"],
                                        error="A previous worker is still active. Stop this run before resuming.",
                                    )
                                    while orphan.is_running() and not self.stop_event.is_set():
                                        if self.store.get("runs", stale["id"]).get("cancel_requested"):
                                            terminate(orphan)
                                            break
                                        self.stop_event.wait(0.5)
                                    if self.stop_event.is_set():
                                        return
                            except (psutil.NoSuchProcess, psutil.AccessDenied):
                                pass
                            self.store.update(
                                "runs",
                                stale["id"],
                                status="interrupted",
                                pid=None,
                                error="The application stopped. Review logs and resume from the saved stages.",
                            )
                    while not self.stop_event.is_set():
                        if self.store.background_task() or self.store.issues("runs"):
                            self.stop_event.wait(0.5)
                            continue
                        pending = [r for r in reversed(self.store.list("runs")) if r["status"] == "queued"]
                        if not pending:
                            self.stop_event.wait(0.5)
                            continue
                        run = pending[0]
                        try:
                            with self.store.lock:
                                if self.store.background_task() or self.store.issues("runs"):
                                    continue
                                lease = self.store.compute_lease()
                                lease.acquire()
                            try:
                                Pipeline(self.store, self.runtime_getter(), self.stop_event).run(run["id"])
                            finally:
                                lease.release()
                        except Timeout:
                            # A legacy queued job can meet a foreground CLI viewer.
                            # Keep it queued; never overlap the GPU work or fail it.
                            self.stop_event.wait(0.5)
                        except InterruptedRun as exc:
                            self.store.update(
                                "runs", run["id"], status="interrupted", error=str(exc), pid=None
                            )
                        except Exception as exc:
                            self.store.update("runs", run["id"], status="failed", error=str(exc), pid=None)
            except Timeout:
                self.stop_event.wait(1)
