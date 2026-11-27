"""Supervise setup and verification independently of the web server's lifetime."""

from __future__ import annotations

import os
import subprocess
import sys
import threading
import time
from pathlib import Path

import psutil

from .store import RunConflictError, Store, identity, now, read, valid_id, write

ACTIVE = {"starting", "running", "recovery"}


def process_identity(pid):
    process = psutil.Process(pid)
    return {"pid": process.pid, "created": process.create_time()}


def alive(owner):
    if not owner:
        return False
    try:
        process = psutil.Process(owner["pid"])
        return process.create_time() == owner["created"] and process.status() != psutil.STATUS_ZOMBIE
    except (psutil.NoSuchProcess, KeyError, TypeError):
        return False
    except psutil.AccessDenied:
        # Permission failure is not proof that a compute owner has ended.
        return True


def task_path(store):
    return store.root / ".background-task.json"


def result_path(store, task_id):
    return store.root / ".background-results" / f"{task_id}.json"


def active_task(store):
    with store.lock:
        try:
            task = read(task_path(store), {})
            if not isinstance(task, dict) or (
                task_path(store).exists()
                and (
                    not task.get("id")
                    or task.get("state") not in ACTIVE | {"complete", "failed", "interrupted"}
                )
            ):
                raise ValueError("Invalid background task record.")
            if task_path(store).exists():
                valid_id(task["id"])
                if task.get("kind") not in {"setup", "verification"} or not isinstance(
                    task.get("owner"), dict
                ):
                    raise ValueError("Invalid background task identity.")
            if task.get("state") not in ACTIVE:
                return None
            if task["state"] == "starting" and not alive(task.get("owner")):
                # A late supervisor checks this state before it starts any child.
                task.update(state="interrupted", error="The app stopped before this task started.")
                write(task_path(store), task)
                return None
            if task["state"] == "running" and not alive(task.get("supervisor")):
                task.update(
                    state="recovery",
                    error="The task supervisor stopped unexpectedly. Stop the remaining task before retrying.",
                )
                write(task_path(store), task)
            return task
        except (OSError, ValueError, TypeError, KeyError):
            return {
                "state": "recovery",
                "kind": "unknown",
                "error": "The background task record is unreadable. Close the app and recover it from a backup before starting more GPU work.",
            }


def update_task(store, task_id, **changes):
    with store.lock:
        task = read(task_path(store), {})
        if task.get("id") != task_id:
            raise RuntimeError("The background task record changed.")
        task.update(changes)
        if task.get("state") in {"complete", "failed", "interrupted"}:
            write(result_path(store, task_id), task)
        write(task_path(store), task)
        return task


class Tasks:
    def __init__(self, store, home):
        self.store, self.home = store, home
        self.closing = threading.Event()
        self.owned = set()

    def start(self, kind, command, log, *, lease=None, timeout=None, fingerprint=None):
        try:
            with self.store.lock:
                if self.closing.is_set():
                    raise RuntimeError("The application is shutting down.")
                if active_task(self.store):
                    raise RunConflictError("A previous setup or GPU check still owns this workspace.")
                if lease is None:
                    self.store.require_idle()
                task = {
                    "id": identity(),
                    "kind": kind,
                    "state": "starting",
                    "started": now(),
                    "owner": process_identity(os.getpid()),
                    "command": command,
                    "log": str(log),
                    "home": str(self.home),
                    "timeout": timeout,
                    "fingerprint": fingerprint,
                    "stop_requested": False,
                }
                write(task_path(self.store), task)
                if kind == "verification":
                    write(
                        self.home / "diagnostics/verification.json",
                        {
                            "fingerprint": fingerprint,
                            "passed": False,
                            "checked": now(),
                            "report": None,
                            "error": "Verification started but has not produced a passing result. Retry if it was interrupted.",
                        },
                    )
                self.owned.add(task["id"])
                flags = (
                    {"creationflags": subprocess.CREATE_NO_WINDOW | subprocess.CREATE_NEW_PROCESS_GROUP}
                    if os.name == "nt"
                    else {"start_new_session": True}
                )
                try:
                    with (self.home / "supervisor.log").open("ab") as output:
                        process = subprocess.Popen(
                            [sys.executable, "-m", "photosplat.background", str(self.store.root), task["id"]],
                            stdin=subprocess.DEVNULL,
                            stdout=output,
                            stderr=subprocess.STDOUT,
                            **flags,
                        )
                except Exception as exc:
                    update_task(self.store, task["id"], state="failed", error=str(exc))
                    raise
                return process, task["id"]
        finally:
            # The saved reservation covers the handoff until the supervisor takes
            # its own OS lock. A server crash cannot make it look like idle work.
            if lease:
                lease.release()

    def run(self, kind, command, log, **options):
        process, task_id = self.start(kind, command, log, **options)
        process.wait()
        task = read(result_path(self.store, task_id), {})
        if task.get("id") != task_id or task.get("state") in ACTIVE:
            raise RuntimeError("The task supervisor stopped unexpectedly. Review its recovery status.")
        return subprocess.CompletedProcess(command, 0 if task.get("state") == "complete" else 1)

    def stop(self, task_id):
        from .pipeline import terminate

        with self.store.lock:
            task = active_task(self.store)
            if not task or task.get("id") != task_id:
                return
            if alive(task.get("supervisor")) or task["state"] == "starting":
                update_task(self.store, task_id, stop_requested=True)
                return
            child = task.get("child")
            if task.get("spawn_started") and not child:
                raise RunConflictError(
                    "The supervisor stopped while launching its child. Review the process list before recovering the task record; automatic cleanup cannot prove which process owns it."
                )
            if alive(child):
                try:
                    process = psutil.Process(child["pid"])
                    if process.create_time() == child["created"]:
                        terminate(process)
                except psutil.NoSuchProcess:
                    pass
                except psutil.AccessDenied as exc:
                    raise RunConflictError(
                        "Cannot prove ownership of the remaining process. Review its permissions and process identity before recovery."
                    ) from exc
            update_task(
                self.store, task_id, state="interrupted", finished=now(), error="Stopped during recovery."
            )

    def close(self):
        self.closing.set()
        task = active_task(self.store)
        if task and task.get("id") in self.owned:
            self.stop(task["id"])
            deadline = time.monotonic() + 10
            while active_task(self.store) and time.monotonic() < deadline:
                time.sleep(0.1)
            # A slow child remains supervised and reserved after shutdown.


def supervise(root, task_id):
    from .pipeline import tail, terminate

    store = Store(Path(root))
    child = None
    lease = store.compute_lease()
    task = None
    error = None
    timed_out = False
    claimed = False
    state = "failed"
    try:
        with store.lock:
            task = read(task_path(store), {})
            if task.get("id") != task_id or task.get("state") != "starting":
                return 1
            claimed = True
            # The app may still be releasing its preflight lease after spawn.
            lease.acquire(timeout=10)
            task = update_task(store, task_id, supervisor=process_identity(os.getpid()), state="running")
        log = Path(task["log"])
        log.parent.mkdir(parents=True, exist_ok=True)
        if task["kind"] == "verification":
            (Path(task["home"]) / "diagnostics/gpu-verification.json").unlink(missing_ok=True)
        with log.open("w") as output:
            with store.lock:
                current = read(task_path(store))
                if current.get("stop_requested"):
                    raise RuntimeError("Stopped before starting the external tool.")
                update_task(store, task_id, spawn_started=True)
                child = subprocess.Popen(task["command"], stdout=output, stderr=subprocess.STDOUT)
                update_task(store, task_id, child=process_identity(child.pid))
            started = time.monotonic()
            while child.poll() is None:
                current = read(task_path(store))
                timed_out = bool(task.get("timeout") and time.monotonic() - started > task["timeout"])
                if current.get("stop_requested") or timed_out:
                    terminate(child)
                    raise RuntimeError(
                        "Task timed out." if timed_out else "Stopped safely; retry when ready."
                    )
                time.sleep(0.2)
        if child.returncode:
            raise RuntimeError(tail(log, 2400) or "The external tool failed.")
        if task["kind"] == "verification":
            report = read(Path(task["home"]) / "diagnostics/gpu-verification.json")
            if not isinstance(report, dict) or report.get("passed") is not True:
                raise RuntimeError("GPU execution did not produce a passing report.")
        state = "complete"
    except Exception as exc:
        error = str(exc)
        state = "interrupted" if task and read(task_path(store), {}).get("stop_requested") else "failed"
    finally:
        try:
            if child and child.poll() is None:
                terminate(child)
            if claimed:
                if task["kind"] == "verification":
                    report = (
                        read(Path(task["home"]) / "diagnostics/gpu-verification.json") if not error else None
                    )
                    write(
                        Path(task["home"]) / "diagnostics/verification.json",
                        {
                            "fingerprint": task.get("fingerprint"),
                            "passed": not error,
                            "checked": now(),
                            "report": report,
                            "error": error,
                        },
                    )
                update_task(store, task_id, state=state, finished=now(), error=error, timed_out=timed_out)
        finally:
            lease.release()
    return 0 if not error else 1


if __name__ == "__main__":
    raise SystemExit(supervise(sys.argv[1], sys.argv[2]))
