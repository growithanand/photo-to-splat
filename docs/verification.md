# Verification

The application tests run in [GitHub Actions](https://github.com/growithanand/photo-to-splat/actions/workflows/ci.yml).
GPU checks and reconstruction results were recorded separately on the system below.

## Automated checks

| Check | Result |
|---|---|
| Backend tests | 53 passing; CI runs on Windows and Linux |
| Frontend tests | 42 passing |
| TypeScript and frontend build | Passing |
| Python lint | Passing |
| Wheel and source distribution | Built with the UI and runtime locks; local workspace files excluded |

The tests cover photo imports, duplicate detection, input hashes, run recovery,
workspace changes, concurrent requests, viewer controls, Trash, and setup state.
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
