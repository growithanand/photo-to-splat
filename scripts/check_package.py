"""Check release contents before testing a wheel outside the checkout."""

import argparse
import tarfile
import zipfile
from pathlib import Path


def check(directory):
    wheel = next(directory.glob("*.whl"))
    source = next(directory.glob("*.tar.gz"))
    with zipfile.ZipFile(wheel) as archive:
        names = archive.namelist()
        required = [
            "web/index.html",
            "web/demo.mp4",
            "gpu/uv.lock",
            "gpu/native-linux-64.lock",
            "gpu/sfm-linux-64.lock",
            "setup-runtime.sh",
            "background.py",
        ]
        for name in required:
            assert f"photosplat/{name}" in names, f"Missing wheel file: {name}"
        for file in Path("src/photosplat/web").rglob("*"):
            if file.is_file():
                name = "photosplat/web/" + file.relative_to("src/photosplat/web").as_posix()
                assert archive.read(name) == file.read_bytes(), f"Stale bundled UI: {name}"
    with tarfile.open(source) as archive:
        source_names = archive.getnames()
    excluded = {
        "agents.md",
        "claude.md",
        "gemini.md",
        ".local",
        ".verification",
        ".local-workspace",
        ".venv",
        "node_modules",
        ".codex",
        ".agents",
    }
    for name in [*names, *source_names]:
        assert not any(part.lower() in excluded for part in name.split("/")), f"Local file in release: {name}"
    print("Release contents match the current UI; local helpers and workspaces are excluded.")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("directory", type=Path)
    check(parser.parse_args().directory)
