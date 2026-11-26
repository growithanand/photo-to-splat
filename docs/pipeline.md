# Practical implementation: photographs to a saved scene

```text
Import → immutable run → prepare → features → matches → cameras
                                                       ↓
Viewer ← export ← held-out renders ← Gaussian training ← conversion
```

This guide maps practical implementation to code. It assumes familiarity with
geometry but does not assume prior experience wiring reconstruction tools together.

## Start the application

`cli.py` launches FastAPI. `app.py` serves React's built assets, runs diagnostics
in background threads, and exposes scene/run actions. No startup import loads
torch or Nerfstudio. The welcome demonstration is a small prerecorded MP4.

`runtime.py` is the execution boundary. On Windows it invokes WSL; on Linux it
invokes `runtime.sh`. That wrapper selects prefixes and establishes native
compiler/include/library paths. The same boundary is used by UI and CLI.

## Import and snapshot

`images.py` validates formats/dimensions, applies orientation for thumbnails,
hashes accepted bytes, and saves originals under generated IDs. Identical content
is deduplicated within a scene; different bytes with the same filename are safe.

`store.py` uses atomic JSON replacement and a filesystem lock. Creating a run
copies selected photo records and settings into a run-local snapshot. Later
imports cannot silently change an existing run. Content hashes detect changed
bytes; they do not establish scene overlap, sharpness, or physical consistency.

## Prepare working images

The pipeline verifies GPU execution, then creates per-run image copies. A phone's
3,000 × 4,000 portrait becomes 1,200 × 1,600 at the standard maximum edge.
Orientation is normalized before resizing. Original bytes remain unchanged.
Working copies receive deterministic numbered names in the imported order and
their own hashes. Alpha is preserved where present.

## Find and match visual features

`pipeline.py` invokes COLMAP's feature extractor against a run-local database.
It queries supported options first and captures stdout **and stderr**, because
COLMAP can print help to stderr even on success.

Automatic camera grouping shares a SIMPLE_RADIAL calibration when dimensions
and focal metadata agree. When available, 35mm-equivalent metadata initializes
the resized pixel focal length; otherwise a conventional image-size prior is
used and refined. Mixed or missing metadata may need an explicit camera mode.

Exhaustive matching compares all pairs and verifies geometric consistency.
Sequential matching relies on ordered filenames and overlapping neighboring
captures. It is not a general substitute for image retrieval on shuffled large
albums. The app guards against accidental huge exhaustive jobs.

## Estimate cameras and sparse geometry

`colmap mapper` incrementally registers photographs, triangulates points, and
refines both with bundle adjustment. It can produce disconnected models. The
converter chooses the largest and reports model sizes rather than merging
incompatible coordinate systems.

`engine.py convert` gates the result on registration count/ratio, finite poses,
valid rotations, and a nonempty cloud. The default requires 12 registered views
and 70% of the selected set. Mean point reprojection error and track length help
diagnosis; low error alone does not prove physical accuracy.

## Convert camera conventions

The converter calls Nerfstudio's own `colmap_to_json`. This converts COLMAP's
OpenCV-style cameras to the OpenGL camera-to-world convention and applies the
same world-coordinate change to sparse points. Initialization fails if cameras
and points do not share a coordinate frame.

```text
World frame: camera centers and points use common coordinates

 C: camera center ───────────── optical axis (-Z camera)
       ╲
        ╲ viewing ray
         P: reconstructed point

Camera frame: +X right, +Y up, -Z forward
```

`P(t) = C + t d` describes the world ray. Pose rotation turns a camera direction
into `d`; translation locates `C`. The saved poses and initialization cloud must
agree on these conventions.

Explicit train/validation/test lists hold out every twelfth photometric image,
with a separate validation offset. SfM still uses the full capture to estimate
poses/initial geometry. These are appearance holdouts, not a strict benchmark
that reconstructs geometry from training images alone.

## Train the representation

`engine.py train` invokes Splatfacto using the run's step budget, seed, input
dataset, output directory, and fixed background. Sparse points initialize
Gaussians. Optimization adjusts position, scale, orientation, opacity, and
view-dependent appearance. Densification and culling change the Gaussian count.

Nerfstudio schedules image resolution during optimization. The selected edge is
the maximum input edge, not the resolution of every training iteration. Quick
and detailed presets are iteration budgets, not equal compute or quality guarantees.

TensorBoard stays local. Checkpoints are saved periodically; the latest checkpoint
is retained to limit disk growth. Separate runs preserve independent results.

## Failures and resume

The queue takes a workspace worker lock and commits a stage only after successful
exit. Errors keep previous outputs and stage logs. Resume checks original and
prepared hashes, recorded camera artifacts, and training versions when available.
Different inputs/settings should create a new run.

Training restarts from its latest checkpoint; work since that save can be lost.
A crashed server's still-running managed child must be stopped before competing
work starts. The browser polls state and does not own the job. Keep the application
terminal alive; stopping it interrupts its worker. Workspaces have independent
queues, so multiple app instances can still compete for one GPU.

New submissions now follow a one-active-run policy. Admission checks and the run
reservation share the record lock; a separate compute lock spans training,
viewer, verification and installer work. Existing legacy queue entries remain
sequential. [Action coordination](concurrency.md) describes the exact policy.

## Evaluate, export, and inspect

`ns-eval` writes held-out reference/render pairs plus PSNR, SSIM, and LPIPS.
Metrics cover the whole frame, including background; inspect the object too.
They do not measure dimensional accuracy or reliability outside captured views.

`ns-export gaussian-splat` writes a Gaussian PLY, not a triangle mesh. The viewer
loads the saved checkpoint on loopback. Its preview starts at 1600px, a local
compatibility hook for Nerfstudio 1.1.5's lower default. Package upgrades must
retest this hook along with camera conversion and checkpoint restoration.

The engine adds the concrete NumPy dtype/scalar types found in our own checkpoints
to PyTorch's restricted loader. It does not globally disable weights-only loading.
Loading arbitrary externally supplied checkpoints is outside the UI workflow.
