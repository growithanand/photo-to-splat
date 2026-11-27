"""Exercise the real shell flow with a fake package manager; never download tools."""

import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

pytestmark = pytest.mark.skipif(sys.platform != "linux", reason="Native setup runs on Linux/WSL.")


@pytest.mark.parametrize("repair_works", [True, False])
def test_existing_broken_native_tool_is_reconciled_and_probed(tmp_path, repair_works):
    source = Path(__file__).parents[1] / "src/photosplat"
    script_dir, runtime = tmp_path / "app", tmp_path / "runtime"
    (script_dir / "gpu").mkdir(parents=True)
    shutil.copyfile(source / "setup-runtime.sh", script_dir / "setup-runtime.sh")
    (script_dir / "gpu/sfm-linux-64.lock").write_text("@EXPLICIT\n")
    (script_dir / "native_lock.py").write_text("# No native package metadata in this fixture.\n")
    for folder in ("bin", "sfm/bin", "sfm/conda-meta"):
        (runtime / folder).mkdir(parents=True, exist_ok=True)
    (runtime / "sfm/bin/colmap").write_text("#!/bin/sh\nexit 99\n")
    (runtime / "bin/uv").write_text("#!/bin/sh\nexit 0\n")
    manager = runtime / "bin/micromamba"
    manager.write_text(
        '#!/bin/sh\nprintf "%s\\n" "$@" > "$PHOTOSPLAT_RUNTIME_ROOT/called"\n'
        + (
            'printf "#!/bin/sh\\nexit 0\\n" > "$PHOTOSPLAT_RUNTIME_ROOT/sfm/bin/colmap"\n'
            if repair_works
            else ""
        )
        + "exit 0\n"
    )
    for file in [manager, runtime / "bin/uv", runtime / "sfm/bin/colmap"]:
        file.chmod(0o755)
    env = {**os.environ, "PHOTOSPLAT_RUNTIME_ROOT": str(runtime), "PATH": f"{runtime / 'bin'}:/usr/bin:/bin"}
    # The fixture is about repair, independent of the CI runner's glibc version.
    (runtime / "bin/getconf").write_text("#!/bin/sh\necho 'glibc 2.39'\n")
    (runtime / "bin/getconf").chmod(0o755)
    result = subprocess.run(
        ["bash", str(script_dir / "setup-runtime.sh"), "--repair", "colmap"],
        env=env,
        capture_output=True,
        text=True,
    )
    arguments = (runtime / "called").read_text()
    assert "install" in arguments and "--force-reinstall" in arguments
    if repair_works:
        assert result.returncode == 0, result.stderr
        assert "Setup complete" in result.stdout
    else:
        assert result.returncode != 0
        assert "Setup complete" not in result.stdout
