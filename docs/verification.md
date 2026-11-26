# Verification record

This distinguishes software tests from actual reconstruction evidence. CI has
not run on GitHub until the repository is reviewed and published.

## Automated checks

Backend tests cover content deduplication, concurrent imports, orientation,
preserving originals, immutable selections, input tampering, partial-stage
recovery, API guards, runtime changes, folder browsing, orphan workers,
native lock export, CLI worker ownership, scene rename/Trash/restore, active-work
guards, deletion/queue concurrency, and tool help printed to stderr.
All 53 tests passed locally, including simultaneous Start/Resume requests from
independent app instances, idempotent viewer launch/stop, background-task guards,
and reservation release after failure. Trash tests cover exact selection and
workspace confirmation, preserving unrelated scenes and external files, invalid
batches, linked folders on Windows, restore/deletion races, and retry after a
partial filesystem failure. Setup tests cover persistent verification, environment
changes, failed retests, damaged caches, fresh report requirements, saved review
receipts, stale installation requests, targeted components, and custom environment
protection. Stand-in processes are CPU-only.
All 41 frontend tests passed. They cover navigation, browser Back, deep links,
deletion/cancel/undo, rename validation, drafts, background imports, viewer controls,
request retries, dialog errors, blocked concurrency controls, rapid clicks,
stale-state recovery, permanent-deletion confirmation/cancellation, partial cleanup
errors, selection snapshots, setup state transitions, requirements review,
maintenance confirmation, storage guidance, and accessible primitives. TypeScript and the
production frontend build passed.
These tests do not claim CUDA support on CPU-only CI runners.

## Live checks

- Windows dashboard exercised at mobile and desktop breakpoints.
- Scene creation and runtime settings tested through the UI.
- Workspace folder browsing exercised through the UI. A later browser check
  completed individual-photo and directory selection, accepted a valid photo,
  and reported unsupported files from a mixed folder.
- An isolated workspace exercised clickable breadcrumbs, browser Back, run-page
  refresh, rename, recoverable deletion/restoration, and queued-run cancellation.
  Photo exclusions stayed excluded after returning to a scene. Desktop and 390px
  layouts were inspected; thumbnail overflow and cramped mobile navigation were
  corrected. No real user scenes were modified for these checks.
- Trash controls were inspected in a separate browser fixture: Empty Trash
  opened a named-scene confirmation, the final action stayed disabled until
  DELETE was typed, and Cancel kept the entry. The updated live workspace showed
  Empty Trash and per-scene Delete permanently controls. Its real Trash entry
  was left untouched; actual deletion was tested only with temporary fixtures.
- Actual gsplat rasterization and differentiation passed on RTX 5090 Laptop.
- Setup follow-up on 26 November passed a new real GPU render/gradient test with
  the managed environment. Recheck and a full app restart reused the exact saved
  test timestamp and fingerprint. An ordinary install request returned
  `already_installed` without starting an installer. Desktop (1440px) and narrow
  (390px) layouts, scenes navigation, browser Back, and repair cancellation were
  inspected. No tool reinstallation was performed for these checks.
- A 27-photo private local capture completed all nine stages in a 1,200-step,
  800px integration run: 27/27 cameras registered, 3,983 sparse points, and a
  6,366,016-byte Gaussian PLY export. The split was 22 train / 2 validation / 3 test.
  Held-out metrics were PSNR 19.29, SSIM 0.720, and LPIPS 0.425. This short run
  verifies integration; it is not the final-quality preset.
- Recovery was exercised after correcting stderr-only COLMAP help parsing and
  toolkit selection during a concurrent managed setup. These were defects found
  during integration, not successful first-attempt results.
- Clean managed setup completed separately from the compatible older environment
  used for the complete reconstruction. Its first attempt exposed missing host
  compiler exports during a dependency build; those exports were corrected.
  The resulting locked uv environment passed actual Gaussian rendering and
  backpropagation with torch 2.7.1+cu128, CUDA 12.8, gsplat 1.4.0, and GPU
  compute capability 12.0. Native explicit locks were also accepted by micromamba.
- The fresh managed runtime loaded the integration checkpoint in the interactive
  viewer. Its rendered resolution and Max res control both showed 1600px.
- Wheel and source distributions built successfully, including the bundled UI,
  demo and GPU locks, with no private workspace or temporary files included.

## Limits

One tested laptop does not establish minimum VRAM, support for every distro, or
unlimited collection size. Updating native tools/torch/gsplat requires retesting
camera conversion, rendering, checkpoint loading, and viewer defaults.
Follow-up use on 26 November exposed a CUDA launch error in a viewer render thread.
Its root cause remains unresolved. The initial GPU check and successful viewer
load do not establish that every camera movement or long viewer session is reliable.
Restricted test sandboxes can block even the local socket pair needed by async
test clients; normal development/CI needs ordinary loopback access.

The public demo is prerecorded trained synthetic output. It does not show a
user's live reconstruction or promise the same quality for every collection.
