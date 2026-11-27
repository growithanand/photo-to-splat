#!/usr/bin/env bash
# Called only after the user reviews the setup explanation and starts installation.
set -euo pipefail
if [[ "$(uname -s)" != Linux || "$(uname -m)" != x86_64 ]]; then
  echo 'This training profile requires Linux x86_64 (Windows users: use WSL2 Ubuntu).' >&2
  exit 2
fi
glibc="$(getconf GNU_LIBC_VERSION | awk '{print $2}')"
if [[ "$(printf '%s\n' '2.39' "$glibc" | sort -V | head -1)" != '2.39' ]]; then
  echo 'The pinned native profile targets glibc 2.39 or newer (Ubuntu 24.04+). Use a compatible Linux/WSL distribution.' >&2
  exit 2
fi
dir="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
root="${PHOTOSPLAT_RUNTIME_ROOT:-$HOME/.local/share/photo-to-splat}"
if [[ "${1:-}" == --repair ]]; then shift; fi
# The dashboard supplies only missing components. Direct terminal setup and an
# explicit maintenance repair reconcile the whole managed profile.
components=" ${*:-compiler colmap training} "
needs() { [[ "$components" == *" $1 "* ]]; }
for component in "$@"; do
  case "$component" in compiler|colmap|training) ;; *) echo "Unknown setup component: $component" >&2; exit 2 ;; esac
done
mkdir -p "$root/bin"
if ! command -v uv >/dev/null 2>&1; then
  if [[ ! -x "$root/bin/uv" ]]; then
    curl --fail --location https://astral.sh/uv/0.13.10/install.sh -o "$root/install-uv.sh"
    UV_INSTALL_DIR="$root/bin" UV_NO_MODIFY_PATH=1 sh "$root/install-uv.sh"
  fi
  export PATH="$root/bin:$PATH"
fi
if [[ ! -x "$root/bin/micromamba" ]]; then
  curl --fail --location https://micro.mamba.pm/api/micromamba/linux-64/2.8.1 -o "$root/micromamba.tar.bz2"
  python3 - "$root" <<'PY'
from pathlib import Path
import sys, tarfile
root = Path(sys.argv[1])
with tarfile.open(root / 'micromamba.tar.bz2') as archive:
    target = root / 'bin/micromamba'
    target.write_bytes(archive.extractfile('bin/micromamba').read())
    target.chmod(0o755)
PY
fi
export MAMBA_ROOT_PREFIX="$root/mamba"
install_native() {
  local prefix="$1" lock="$2"
  [[ -f "$lock" ]] || { echo "Missing pinned native lock: $lock" >&2; exit 2; }
  if [[ -d "$prefix/conda-meta" ]]; then
    # A binary can exist while a shared library or package is damaged.
    "$root/bin/micromamba" install -y -p "$prefix" --file "$lock" --force-reinstall
  else
    "$root/bin/micromamba" create -y -p "$prefix" --file "$lock"
  fi
}
if needs compiler; then
  install_native "$root/native" "$dir/gpu/native-linux-64.lock"
  "$root/native/bin/nvcc" --version
fi
if needs colmap; then
  install_native "$root/sfm" "$dir/gpu/sfm-linux-64.lock"
  LD_LIBRARY_PATH="$root/sfm/lib${LD_LIBRARY_PATH:+:$LD_LIBRARY_PATH}" "$root/sfm/bin/colmap" -h
fi
# A few Python dependencies contain small C/C++ extensions. Use the isolated
# compiler during uv's build step as well as during gsplat's first GPU execution.
export PATH="$root/native/bin:$PATH"
export CC="$root/native/bin/x86_64-conda-linux-gnu-cc"
export CXX="$root/native/bin/x86_64-conda-linux-gnu-c++"
export CPATH="$root/native/targets/x86_64-linux/include${CPATH:+:$CPATH}"
export LIBRARY_PATH="$root/native/targets/x86_64-linux/lib:$root/native/lib${LIBRARY_PATH:+:$LIBRARY_PATH}"
export LD_LIBRARY_PATH="$root/native/lib${LD_LIBRARY_PATH:+:$LD_LIBRARY_PATH}"
if needs training; then
  UV_PROJECT_ENVIRONMENT="$root/train" uv sync --project "$dir/gpu" --python 3.11.18 --locked --no-dev
  bash "$dir/runtime.sh" train "$root/train" python -c 'import torch, nerfstudio, gsplat'
fi
[[ ! -d "$root/native/conda-meta" ]] || python3 "$dir/native_lock.py" "$root/native" "$root/native-explicit.txt"
[[ ! -d "$root/sfm/conda-meta" ]] || python3 "$dir/native_lock.py" "$root/sfm" "$root/sfm-explicit.txt"
echo 'Setup complete. Run the GPU render test in the application before reconstructing.'
