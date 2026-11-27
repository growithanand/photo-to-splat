from __future__ import annotations

import argparse
import json
import os
import sys
import time
import webbrowser
from contextlib import nullcontext
from pathlib import Path


def main():
    parser = argparse.ArgumentParser(description="A local studio for Gaussian scene reconstruction.")
    parser.add_argument(
        "--workspace",
        type=Path,
        default=Path(os.getenv("PHOTOSPLAT_WORKSPACE", str(Path.home() / "PhotoToSplat"))),
        help="Application home. Place this option before the command.",
    )
    commands = parser.add_subparsers(dest="command", required=True)
    ui = commands.add_parser("ui", help="Open the guided local application.")
    ui.add_argument("--port", type=int, default=8765)
    ui.add_argument("--no-browser", action="store_true")
    check = commands.add_parser("doctor", help="Detect tools and optionally test a real GPU render.")
    check.add_argument("--verify", action="store_true")
    commands.add_parser("list", help="List scenes and runs in the current workspace.")
    start = commands.add_parser("run", help="Import a folder and reconstruct it without the frontend.")
    start.add_argument("--photos", type=Path, required=True)
    start.add_argument("--name", default="My scene")
    start.add_argument("--steps", type=int, default=7000)
    start.add_argument("--matching", choices=("exhaustive", "sequential"), default="exhaustive")
    resume = commands.add_parser("resume", help="Resume a failed or interrupted run.")
    resume.add_argument("run_id")
    view = commands.add_parser("view", help="Launch the viewer for a trained run.")
    view.add_argument("run_id")
    args = parser.parse_args()
    from .app import Services, create_app, port_free
    from .deployment import bind_host, viewer_ports
    from .store import RunConflictError

    if args.command == "ui":
        if not 1024 <= args.port <= 65535:
            parser.error("Choose a local port between 1024 and 65535.")
        import uvicorn

        print(f"Photo to Splat: http://localhost:{args.port}", flush=True)
        if not args.no_browser:
            import threading

            threading.Timer(1.5, lambda: webbrowser.open(f"http://localhost:{args.port}")).start()
        uvicorn.run(create_app(args.workspace), host=bind_host(), port=args.port)
        return
    services = Services(args.workspace)
    if args.command == "doctor":
        from filelock import FileLock, Timeout

        ownership = (
            FileLock(str(services.store.root / ".worker.lock"), timeout=0) if args.verify else nullcontext()
        )
        try:
            with ownership:
                services.check(args.verify)
                while services.diagnostic_lock.locked():
                    time.sleep(0.2)
        except Timeout:
            parser.error("Close this workspace's UI first, or use its GPU verification button.")
        except RunConflictError as exc:
            parser.error(str(exc))
        print(json.dumps(services.diagnostic, indent=2))
        if services.diagnostic["state"] not in ("ready", "verify"):
            sys.exit(1)
    elif args.command == "list":
        print(
            json.dumps(
                {"scenes": services.store.list("scenes"), "runs": services.store.list("runs")}, indent=2
            )
        )
    elif args.command == "view":
        import subprocess

        from filelock import FileLock, Timeout

        run = services.store.get("runs", args.run_id)
        if "train" not in run["completed"]:
            parser.error("Finish training before opening this run's viewer.")
        if services.busy():
            parser.error("Finish or stop queued reconstruction work before opening the viewer.")
        port = next((p for p in viewer_ports() if port_free(p)), None)
        if port is None:
            parser.error("No local viewer port is available between 7010 and 7029.")
        root = services.store.path("runs", args.run_id)
        try:
            # Keep the workspace worker out while this foreground viewer owns the GPU.
            with FileLock(str(services.store.root / ".worker.lock")).acquire(timeout=0):
                with services.store.lock:
                    services.store.require_idle()
                    lease = services.reserve_compute()
                try:
                    subprocess.run(services.runtime().engine_command("view", root, str(port)), check=True)
                finally:
                    lease.release()
        except Timeout:
            parser.error("Close this workspace's UI first, or launch the viewer from its result screen.")
        except RunConflictError as exc:
            parser.error(str(exc))
    else:
        if args.command == "run":
            from .images import SUPPORTED, import_image

            if not args.photos.is_dir():
                parser.error("The photo folder does not exist.")
            try:
                with services.store.lock:
                    services.store.require_idle()
            except RunConflictError as exc:
                parser.error(str(exc))
            scene = services.store.create_scene(args.name)
            for path in sorted(args.photos.rglob("*")):
                if path.is_file() and path.suffix.lower() in SUPPORTED:
                    import_image(services.store, scene["id"], path.name, path.read_bytes())
            try:
                run = services.store.create_run(scene["id"], {"steps": args.steps, "matching": args.matching})
            except RunConflictError as exc:
                parser.error(str(exc))
        else:
            try:
                run = services.store.resume_run(args.run_id, services.runtime().options.model_dump())
            except RunConflictError as exc:
                parser.error(str(exc))
        services.queue.start()
        try:
            last = None
            while True:
                run = services.store.get("runs", run["id"])
                if run["stage"] != last:
                    print(f"[{run['status']}] {run['stage']}", flush=True)
                    last = run["stage"]
                if run["status"] in ("complete", "failed", "interrupted", "cancelled"):
                    print(json.dumps(run, indent=2))
                    if run["status"] != "complete":
                        sys.exit(1)
                    break
                time.sleep(1)
        finally:
            services.queue.close()
