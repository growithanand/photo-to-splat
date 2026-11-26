"""One boundary between the lightweight application and optional Linux GPU tools."""

from __future__ import annotations

import hashlib
import json
import os
import platform
import shutil
import subprocess
import sys
from pathlib import Path, PureWindowsPath

import psutil

from .models import RuntimeOptions


def linux_path(path: str | Path) -> str:
    text = str(path)
    if len(text) > 2 and text[1] == ":":
        p = PureWindowsPath(text)
        return "/mnt/" + p.drive[0].lower() + "/" + "/".join(p.parts[1:])
    return text


class Runtime:
    def __init__(self, settings: dict | None = None):
        self.options = RuntimeOptions(**(settings or {}))
        self.wsl = self.options.mode == "wsl" or (self.options.mode == "auto" and os.name == "nt")
        self.engine = Path(__file__).with_name("engine.py").resolve()
        self.script = Path(__file__).with_name("runtime.sh").resolve()

    def profile(self) -> str:
        """A review applies to this machine, route and bundled tool profile."""
        files = [
            "runtime.sh",
            "setup-runtime.sh",
            "engine.py",
            "gpu/uv.lock",
            "gpu/native-linux-64.lock",
            "gpu/sfm-linux-64.lock",
        ]
        payload = {
            "runtime": self.options.model_dump(),
            "host": [platform.node(), sys.platform, platform.machine()],
            "files": {
                name: hashlib.sha256((self.engine.parent / name).read_bytes()).hexdigest() for name in files
            },
        }
        return hashlib.sha256(json.dumps(payload, sort_keys=True).encode()).hexdigest()

    def command(self, kind: str, arguments: list[str]) -> list[str]:
        if kind not in ("train", "sfm", "probe"):
            raise ValueError("Unknown runtime kind.")
        prefix = self.options.sfm_prefix if kind == "sfm" else self.options.train_prefix
        command = [
            "bash",
            linux_path(self.script) if self.wsl else str(self.script),
            kind,
            prefix,
            *arguments,
        ]
        if self.wsl:
            return ["wsl", "-d", self.options.distro, "--", *command]
        if sys.platform != "linux":
            raise ValueError(
                "Training uses Linux or Windows with WSL2. This platform can inspect photos only."
            )
        return command

    def engine_command(self, action: str, root: Path, *extra: str) -> list[str]:
        return self.command(
            "train",
            [
                "python",
                linux_path(self.engine) if self.wsl else str(self.engine),
                action,
                linux_path(root) if self.wsl else str(root),
                *extra,
            ],
        )

    def capture(self, kind: str, arguments: list[str], timeout=30) -> str:
        result = subprocess.run(
            self.command(kind, arguments),
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=timeout,
        )
        if result.returncode:
            raise RuntimeError(result.stdout[-1800:].strip())
        return result.stdout.strip()

    def readiness(self, workspace: Path) -> dict:
        checks = []
        disk = shutil.disk_usage(workspace)
        checks.append(
            dict(
                id="storage",
                name="Workspace storage",
                state="ready" if disk.free > 5 * 1024**3 else "attention",
                detail=f"{disk.free / 1024**3:.1f} GiB available",
                hint="Choose a roomy local drive; checkpoints and downloads need extra space.",
            )
        )
        supported = (self.wsl and platform.machine().lower() in ("amd64", "x86_64")) or (
            sys.platform == "linux" and platform.machine() == "x86_64"
        )
        checks.append(
            dict(
                id="platform",
                name="Execution platform",
                state="ready" if supported else "unsupported",
                detail="Windows + WSL2" if self.wsl else platform.system(),
                hint="Training is supported on Linux x86_64 or Windows through WSL2.",
            )
        )
        memory = psutil.virtual_memory()
        checks.append(
            dict(
                id="memory",
                name="System memory",
                state="ready",
                detail=f"{memory.total / 1024**3:.1f} GiB RAM · {os.cpu_count()} logical CPU cores",
                hint="Memory use depends on the capture. The Linux/WSL worker may have a lower RAM limit.",
            )
        )
        gpu = None
        probes = [
            (
                "gpu",
                "NVIDIA graphics",
                "probe",
                ["nvidia-smi", "--query-gpu=name,memory.total,driver_version,uuid", "--format=csv,noheader"],
                "Install a compatible NVIDIA driver. An integrated GPU alone cannot train with this backend.",
            ),
            (
                "colmap",
                "Camera reconstruction",
                "sfm",
                ["colmap", "-h"],
                "Run the native-tools setup, or set the COLMAP environment path in Settings.",
            ),
            (
                "training",
                "Python training environment",
                "train",
                [
                    "python",
                    "-c",
                    "import json,sys,os,torch,nerfstudio,gsplat; from pathlib import Path; "
                    "from importlib.metadata import version; "
                    "print(json.dumps({'python':sys.version,'prefix':str(Path(sys.prefix).resolve()),"
                    "'cuda':torch.version.cuda,'runtime_root':os.getenv('PHOTOSPLAT_RUNTIME_ROOT',''),"
                    "'versions':{n:version(n) for n in "
                    "('torch','torchvision','nerfstudio','gsplat','numpy','tyro')}}))",
                ],
                "Run the training-environment setup. The application itself does not require these packages.",
            ),
            (
                "compiler",
                "CUDA compiler",
                "train",
                ["nvcc", "--version"],
                "A PyTorch CUDA wheel is not the CUDA compiler. Install the pinned native toolkit.",
            ),
        ]
        inventory = {}
        for key, name, kind, command, hint in probes:
            try:
                output = self.capture(kind, command, timeout=25)
                detail = output.splitlines()[0] if key != "compiler" else output.splitlines()[-1]
                if key == "gpu":
                    gpu = output
                if key == "training":
                    package = json.loads(output.splitlines()[-1])
                    detail = f"PyTorch {package['versions']['torch']} / CUDA {package['cuda']}"
                inventory[key] = package if key == "training" else output
                checks.append(dict(id=key, name=name, state="ready", detail=detail[:180], hint=hint))
            except (OSError, RuntimeError, ValueError, subprocess.TimeoutExpired) as exc:
                checks.append(dict(id=key, name=name, state="missing", detail=str(exc)[-400:], hint=hint))
        tool_ids = {"colmap", "training", "compiler"}
        missing = [c["id"] for c in checks if c["id"] in tool_ids and c["state"] != "ready"]
        installed = not missing
        ready = all(c["state"] == "ready" for c in checks)
        unsupported = not supported or gpu is None
        return dict(
            state="unsupported"
            if unsupported
            else "setup"
            if not installed
            else "verify"
            if ready
            else "attention",
            tools_installed=installed,
            missing_tools=missing,
            managed=not (self.options.train_prefix or self.options.sfm_prefix),
            fingerprint=hashlib.sha256(
                json.dumps({"profile": self.profile(), "inventory": inventory}, sort_keys=True).encode()
            ).hexdigest()
            if installed and not unsupported
            else None,
            checks=checks,
            gpu=gpu,
            free_bytes=disk.free,
            workspace=str(workspace),
            note="Tool detection is not GPU verification. Run the render test before training.",
        )
