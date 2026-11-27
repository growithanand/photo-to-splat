"""Container defaults keep browser access local and results on persistent storage."""

import os
from pathlib import Path


def containerized():
    return os.getenv("PHOTOSPLAT_CONTAINER") == "1"


def bind_host():
    return "0.0.0.0" if containerized() else "127.0.0.1"


def data_root():
    return Path(os.getenv("PHOTOSPLAT_DATA_ROOT", "/data")).expanduser().resolve()


def workspace_path(path):
    target = Path(path).expanduser().resolve()
    if containerized() and not target.is_relative_to(data_root()):
        raise ValueError(
            "Docker workspaces must stay under /data so saved scenes survive container replacement."
        )
    return target


def viewer_ports():
    return [7010] if containerized() else range(7010, 7030)


def viewer_url(port):
    public_port = int(os.getenv("PHOTOSPLAT_VIEWER_PORT", "7010")) if containerized() else port
    if not 1024 <= public_port <= 65535:
        raise ValueError("Choose a viewer port between 1024 and 65535.")
    return f"http://localhost:{public_port}"
