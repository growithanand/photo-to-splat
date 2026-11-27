# When a scene needs attention

| Symptom | Check | Recovery |
|---|---|---|
| UI does not open | uv version and terminal output | Run from the repository root and keep the terminal open |
| Port 8765 is already in use | An earlier app instance may still be running | Open http://localhost:8765 first. If an unrelated program owns the port, use `uv run --locked --no-dev photosplat ui --port 8766` |
| WSL missing | `wsl --list --verbose` | Install WSL2/Ubuntu or select the installed distribution's name |
| GPU missing | Driver and WSL nvidia-smi | Use supported hardware/driver; do not guess torch wheel versions |
| Render test fails | Compiler, headers, architecture, log | Finish native setup and use the pinned profile; first build takes time |
| CUDA headers missing | Native prefix/include paths | Use the wrapper, not a bare Python activation |
| Open3D library failure | libusb/native library paths | Use the managed native prefix or a compatible explicit prefix |
| Files rejected | Format/bytes/dimensions | Convert HEIC/RAW; use ordinary JPEG working images |
| Duplicate not added | Content hash | Identical bytes intentionally share one imported photo |
| Poor camera registration | Overlap, blur, lighting, calibration | Review photos/grouping and create another run |
| Huge matching job rejected | Exhaustive matching above 500 images | Use capture-ordered sequential matching or a smaller subset |
| GPU out of memory | Resolution, Gaussian growth, other jobs | Stop GPU viewers/programs and create a lower-resolution run |
| Pixelated preview | Viewer Max res | Check the 1600px default; raising it cannot restore unlearned detail |
| Floating fragments | Coverage, reflections, inconsistent scene | Stay near captured viewpoints; improve capture or inspect/crop in viewer |
| Resume refuses data | Hash/runtime-version changes | Restore the exact snapshots/environment or create a new run |
| Viewer link not ready | Model still loading | Wait a few seconds; inspect the run's viewer.log if it never opens |
| Viewer freezes after connecting | viewer.log traceback / CUDA launch error | Stop and restart that viewer; retain the log. A small GPU test passing does not prove a long viewer session is stable |
| Scene disappeared after Delete | Trash | Restore the scene; imported files and saved runs are retained |
| Run page cannot load | Local terminal, current workspace, Trash | Retry connection or return through Workspace / My scenes; check that the scene belongs to this workspace |

**Stop** preserves completed stages and the latest saved checkpoint. **Resume**
continues those same inputs/settings. **New run** is for a changed configuration.
**Open viewer** consumes GPU memory; stop it before queuing reconstruction.

More training can refine detail, but cannot supply missing surfaces or make
reflections and moving shadows obey a static-scene model. No automatic blur
threshold deletes photographs: users review and exclude clear mistakes.

Logs live in `runs/<id>/logs/`. Also inspect camera-report.json, commands.json,
gpu-verification.json, and the training config. Manifests/logs can contain local
paths and photo names; review them before sharing publicly.
