#!/usr/bin/env bash
# Native dependencies stay outside the dashboard's uv environment.
set -eo pipefail
kind="$1"; prefix="$2"; shift 2
root="${PHOTOSPLAT_RUNTIME_ROOT:-$HOME/.local/share/photo-to-splat}"
if [[ "$kind" == probe ]]; then exec "$@"; fi
if [[ -z "$prefix" ]]; then prefix="$root/$kind"; fi
if [[ "$prefix" == '~/'* ]]; then prefix="$HOME/${prefix:2}"; fi
if [[ ! -d "$prefix" ]]; then
  echo "Missing $kind environment: $prefix. Open Setup instructions in the application." >&2
  exit 2
fi
export PATH="$prefix/bin:$PATH"
export LD_LIBRARY_PATH="$prefix/lib${LD_LIBRARY_PATH:+:$LD_LIBRARY_PATH}"
if [[ "$kind" == train ]]; then
  # A custom Conda prefix may already own its toolkit. Do not borrow a partly
  # installed managed prefix simply because its directory exists.
  native="$prefix"
  [[ -x "$native/bin/nvcc" ]] || native="$root/native"
  if [[ ! -x "$native/bin/nvcc" ]]; then
    echo 'CUDA compiler is not ready. Let native setup finish, then recheck.' >&2
    exit 2
  fi
  export CUDA_HOME="$native"
  export PATH="$native/bin:$PATH"
  export CPATH="$native/targets/x86_64-linux/include${CPATH:+:$CPATH}"
  export LIBRARY_PATH="$native/targets/x86_64-linux/lib${LIBRARY_PATH:+:$LIBRARY_PATH}"
  export LD_LIBRARY_PATH="$native/lib:$LD_LIBRARY_PATH"
  if [[ -x "$native/bin/x86_64-conda-linux-gnu-cc" ]]; then
    export CC="$native/bin/x86_64-conda-linux-gnu-cc"
    export CXX="$native/bin/x86_64-conda-linux-gnu-c++"
  fi
  export MAX_JOBS=2
fi
exec "$@"
