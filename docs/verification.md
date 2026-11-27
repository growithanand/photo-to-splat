# Verification

The application tests run in [GitHub Actions](https://github.com/growithanand/photo-to-splat/actions/workflows/ci.yml).
GPU checks and reconstruction results were recorded separately on the system below.

## Automated checks

| Check | Result |
|---|---|
| Backend tests | 75 passing on Linux/WSL; 73 passing and 2 Linux-only repair tests skipped on Windows |
| Frontend tests | 46 passing |
| TypeScript and frontend build | Passing |
| Python lint | Passing |
| Wheel and source distribution | Built with the UI and runtime locks; local workspace files excluded |
| Dependency advisory scans | No known findings in the lightweight app environment or frontend lockfile at the time of the check |
| Container delivery | UI/import/restart checks, GPU execution, and photo-to-export reconstruction pass; details below |

The tests cover photo imports, duplicate detection, input hashes, run recovery,
workspace changes, concurrent requests, viewer controls, Trash, and setup state.
Process tests use real CPU children to exercise shutdown, supervisor failure,
restart discovery, the reservation handoff, timeout cleanup, and durable GPU test
results. Fake native tools exercise package reconciliation and failed post-repair
probes without installing CUDA. Recovery tests cover damaged records, natural
capture ordering, and palette/RGBA transparency. Wheel smoke tests run from
outside the checkout. The advisory checks above do not cover the optional GPU
environment or establish that no undisclosed vulnerabilities exist.
Browser checks covered desktop and narrow layouts, folder/file selection,
navigation, and confirmation dialogs. The dark interface was checked at 390px
and desktop widths, including setup maintenance fields, empty Trash, scene
controls, and a saved run. Public interface captures use an empty workspace and
the included synthetic demo.

## Tested GPU environment

| Component | Configuration |
|---|---|
| Host | Windows with WSL2 Ubuntu 26.04 |
| GPU | NVIDIA GeForce RTX 5090 Laptop GPU, 24 GB |
| Training Python | 3.11.18 |
| PyTorch | 2.7.1+cu128 |
| CUDA toolkit | 12.8 |
| Nerfstudio / gsplat | 1.1.5 / 1.4.0 |
| COLMAP | 3.13.0, CUDA 12.9 build |

The managed environment rendered a Gaussian image and backpropagated through it.
It also loaded a saved reconstruction in the interactive viewer at the 1600px
preview setting. Rechecking tools and restarting the app preserved the saved
GPU test when the environment fingerprint matched. A repeated install request
returned `already_installed` without launching the installer.

## Reconstruction check

A private 27-photo capture completed all nine pipeline stages using an existing
compatible environment. The fresh managed installation was checked separately
with the GPU test and checkpoint loading described above.

| Measurement | Result |
|---|---|
| Registered cameras | 27 / 27 |
| Sparse points | 3,983 |
| Training budget | 1,200 steps at an 800px image edge |
| Train / validation / test split | 22 / 2 / 3 photos |
| Gaussian PLY export | 6.1 MiB |
| Held-out PSNR | 19.29 |
| Held-out SSIM | 0.720 |
| Held-out LPIPS | 0.425 |

This was a short integration run. The app's Quick preview preset uses 7,000
steps. Metrics cover the whole image, including the background. COLMAP uses the
full capture for camera estimation; held-out images are excluded from appearance
training, not from the camera solution.

Recovery was checked after failed camera-tool detection and an interrupted setup.
Those checks led to fixes for COLMAP help printed to stderr, compiler exports
during package builds, and selection of an incomplete CUDA toolkit.

## Container verification

The Docker route was checked on 27 November 2026 using Docker Desktop 29.8.2,
Compose 5.6.0, and the GPU above. The image uses Ubuntu 24.04 and the same locked
training tools. It runs as UID/GID 10001 with a read-only root filesystem.

Checks covered a first-use gsplat compilation and render/gradient test, PyTorch's
training compiler, browser photo imports, and scene/GPU-test persistence after
container replacement. Compilation caches use the writable `/cache` volume.

A separate 27-photo capture completed all nine stages through Compose:

| Measurement | Container result |
|---|---|
| Registered cameras / sparse points | 26 / 27 cameras; 3,525 points |
| Training budget | 1,200 steps at an 800px image edge |
| Train / validation / test split | 21 / 2 / 3 photos |
| Gaussian PLY export | 5.7 MiB |
| Held-out PSNR / SSIM / LPIPS | 20.10 / 0.726 / 0.436 |

The saved checkpoint rendered in the browser at the 1600px preview setting
through a remapped host viewer port. This was a short viewer check on the same
GPU system; it does not resolve the longer-session limitation below.

## Known limits

- The complete workflow has been exercised on one GPU system. Minimum VRAM and
  compatibility with other GPU models or Linux distributions have not been established.
- A CUDA launch error occurred in a viewer render thread during follow-up use on
  26 November 2026. Its cause is unresolved. The small GPU test can pass while a
  longer viewer session still fails; keep the viewer log when reporting this.
- CI runs application tests without CUDA. It does not validate GPU training or
  the driver/toolkit combination on another system.
- Changing torch, gsplat, Nerfstudio, or native tools requires checking camera
  conversion, rendering, checkpoint loading, and viewer defaults again.
- Reconstruction quality depends on coverage, reflections, blur, and scene
  consistency. The prerecorded public demo uses a synthetic scene.
