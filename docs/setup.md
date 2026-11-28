# Setup and environments

```text
Browser UI → lightweight Python .venv → Linux worker
                                       ├─ COLMAP environment
                                       └─ uv GPU environment + native CUDA/compiler
```

This page describes the recommended local uv route. The app opens before the
GPU tools are installed, so you can check your system and review the storage
requirements first. The training stack is still a separate, substantial download.
Installed tools are reused across scenes.

The optional [Docker walkthrough](docker.md) uses the same tools inside an image
and does not run the local installer.

## What each dependency does

The **NVIDIA driver** connects the OS to the GPU. Install it through NVIDIA or
the system manufacturer. The app does not replace it. The **PyTorch wheel** supplies
libraries for its CUDA build; a CPU wheel cannot train on your NVIDIA device.
The **development toolkit** supplies nvcc and headers for compiling gsplat.
The **host C++ compiler** builds bindings and must be compatible with nvcc.

The managed profile installs the training packages, toolkit, and compiler in
separate environments. Install the NVIDIA driver and WSL at system level first.

## Windows walkthrough

Confirm `uv --version` in PowerShell. From the repository folder, run
`uv sync --locked --no-dev`, then `uv run --locked --no-dev photosplat ui`.
The first sync can download a compatible Python without replacing another project.

Install WSL2 Ubuntu 24.04 or newer through Microsoft's instructions if missing.
The managed native profile requires x86_64 Linux with glibc 2.39 or newer;
the complete system check used Ubuntu 26.04 under WSL2.
The pinned COLMAP packages also require an x86-64-v3 CPU or newer, including
AVX2/FMA support. See [GCC's x86 architecture descriptions](https://gcc.gnu.org/onlinedocs/gcc/x86-Options.html).
`wsl --list --verbose` should show the intended distribution at version 2.
`wsl -d Ubuntu -- nvidia-smi` should show the device. Select a different installed
distribution name in Computer & setup when appropriate.

The app translates a path such as `D:\Captures\My room` to
`/mnt/d/Captures/My room` for the worker. Commands use argument lists, including
paths with spaces; photo filenames are never interpolated into shell programs.
The browser imports selected file contents to localhost. It does not expose a
dependable native source-folder path. Imported originals remain private workspace data.

## Native and Python setup

The page detects existing tools before offering installation. **Install missing
tools** appears only for a managed environment with missing components. The
requirements acknowledgment is saved for the current machine, route, and bundled
profile, so revisiting the page does not reset it. A changed profile asks for a
fresh review. Healthy setups lead to **Go to my scenes**; installed setups without
a matching GPU test offer **Verify GPU execution**.

After reviewing the requirements, start installation. The script downloads uv
inside Linux if needed, bootstraps micromamba, creates native/COLMAP prefixes,
and syncs the locked GPU project into `train`. Keep the terminal open during setup.
The standard root is `~/.local/share/photo-to-splat`. An explicit Linux
`PHOTOSPLAT_RUNTIME_ROOT` can choose another location.

The checked-in `native-linux-64.lock` and `sfm-linux-64.lock` pin native package
URLs and hashes. Setup installs those builds, then exports `native-explicit.txt`
and `sfm-explicit.txt` to record the installed prefixes. The Python profile has
a separate checked-in uv lock. The package locks record installed software;
the system driver and OS are separate parts of the environment.

Existing Linux prefixes can be configured in the app. A Conda training prefix
may own its toolkit; a plain uv prefix uses managed native tools. The runtime
requires an executable nvcc, not just a directory, before using a toolkit.
Find these fields under **Advanced / maintenance**. Managed installation refuses
to replace selected custom environments. Clear the paths explicitly if you
intend to switch to managed tools.

Normal installation rechecks the current environment, returns without starting a
process when tools are already installed, and passes only missing component IDs
to the installer. **Repair managed tools** is an explicit maintenance action with
a separate confirmation. It reconciles all components, keeps existing native
prefixes, reinstalls the native packages from their explicit locks, and synchronizes
the pinned Python packages. Compiler, COLMAP, and training imports are probed before
setup reports success. Inspect the log if a probe still fails. Neither action
changes source photos or scenes.

Setup and GPU verification run under a separate supervisor. Closing the app
requests a safe stop for tasks that app started. If the server crashes, the
supervisor retains the compute lock and saves its result. Reopening the same
workspace shows the active task and **Stop background task**. A lost supervisor
requires recovery before new GPU work; a recycled process ID is never sufficient
evidence for automatic termination.

## Actual execution check

Detection probes nvidia-smi, COLMAP, imports, compiler, and disk space. The explicit
GPU test then renders a Gaussian with gsplat and differentiates through it. It
checks nonempty output and finite gradients and saves the GPU, architecture,
Python/package versions, and PyTorch CUDA version. First execution may compile
kernels for minutes. Inspect errors instead of installing random alternative versions.

The app saves the test result under its application home at
`diagnostics/verification.json`. The fingerprint includes the selected route and
paths, machine, GPU identity and driver, reported Python/package/compiler/COLMAP
versions, resolved training prefix, and bundled worker/profile files. Ordinary
startup/tool checks compare this fingerprint before restoring the saved result.
Changing scenes or the photo workspace does not invalidate the same environment.
Low workspace space remains a separate warning.

A failed retest replaces a previous success; a missing or unreadable record asks
for verification. Older installations without a fingerprint need one new GPU
test to establish it. The comparison is based on detected identity and versions,
not a byte-level audit of every installed file. The UI shows the last test date;
it does not claim the GPU has been tested anew on every launch. The reconstruction
pipeline's own execution checks still run independently.

## Storage

Workspace space and Linux tool space can be on different volumes. A large Windows
photo drive does not guarantee free capacity in the WSL virtual disk. The dashboard
space number refers to the workspace; native installation can still fail if its
Linux volume is full.

Allow roughly 15–30 GB for tools/caches, plus scene data. The scene estimate uses
source bytes, resized pixel counts, and a checkpoint allowance. Gaussian growth
depends on the capture; the upper estimate is not a cap or disk reservation.
