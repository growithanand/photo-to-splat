"""Runs only in the optional GPU environment; the dashboard imports none of this stack.

This file can also be invoked directly by a WSL worker, so it has no relative
imports from the lightweight application package.
"""

import json
import os
import sys
from importlib.metadata import distribution, version
from pathlib import Path


def versions():
    return {name: version(name) for name in ("torch", "torchvision", "nerfstudio", "gsplat", "numpy", "tyro")}


def setup_gpu():
    import numpy as np
    import torch

    if not torch.cuda.is_available():
        raise RuntimeError("PyTorch cannot execute CUDA. Check the NVIDIA driver and selected wheel build.")
    major, minor = torch.cuda.get_device_capability()
    os.environ.setdefault("TORCH_CUDA_ARCH_LIST", f"{major}.{minor}")
    # These concrete NumPy types are present in locally produced Nerfstudio
    # scheduler states. Keep weights-only loading enabled.
    torch.serialization.add_safe_globals(
        [
            np.dtype,
            np.core.multiarray.scalar,
            type(np.dtype("float64")),
            type(np.dtype("float32")),
            type(np.dtype("int64")),
        ]
    )
    return torch


def gpu_test(root):
    torch = setup_gpu()
    from gsplat import rasterization

    means = torch.tensor([[0.0, 0.0, 3.0]], device="cuda", requires_grad=True)
    colors = torch.tensor([[1.0, 0.6, 0.1]], device="cuda", requires_grad=True)
    image, alpha, _ = rasterization(
        means,
        torch.tensor([[1.0, 0.0, 0.0, 0.0]], device="cuda"),
        torch.full((1, 3), 0.15, device="cuda"),
        torch.tensor([0.8], device="cuda"),
        colors,
        torch.eye(4, device="cuda")[None],
        torch.tensor([[[40.0, 0.0, 16.0], [0.0, 40.0, 16.0], [0.0, 0.0, 1.0]]], device="cuda"),
        width=32,
        height=32,
        packed=False,
    )
    image.sum().backward()
    if not alpha.max().item() > 0 or not torch.isfinite(means.grad).all():
        raise RuntimeError("The Gaussian rasterization/backward check failed.")
    report = {
        "passed": True,
        "gpu": torch.cuda.get_device_name(),
        "torch": torch.__version__,
        "cuda": torch.version.cuda,
        "capability": list(torch.cuda.get_device_capability()),
        "versions": versions(),
        "python": sys.version,
    }
    root.mkdir(parents=True, exist_ok=True)
    (root / "gpu-verification.json").write_text(json.dumps(report, indent=2))
    print(json.dumps(report), flush=True)


def convert(root):
    import numpy as np
    from nerfstudio.data.utils.colmap_parsing_utils import read_images_binary, read_points3D_binary
    from nerfstudio.process_data.colmap_utils import colmap_to_json

    models = []
    for folder in (root / "dataset/colmap/sparse").iterdir():
        if (folder / "images.bin").exists():
            models.append((len(read_images_binary(folder / "images.bin")), folder))
    if not models:
        raise RuntimeError("No camera model was reconstructed. Check overlap, blur, and consistent lighting.")
    count, model = max(models, key=lambda item: item[0])
    run = json.loads((root / "record.json").read_text())
    points = read_points3D_binary(model / "points3D.bin")
    ratio = count / len(run["images"])
    if count < 12 or ratio < run["settings"]["min_registration"] or not points:
        raise RuntimeError(
            f"Only {count}/{len(run['images'])} photos registered. Review camera matching before training."
        )
    colmap_to_json(model, root / "dataset")
    meta_path = root / "dataset/transforms.json"
    meta = json.loads(meta_path.read_text())
    meta["frames"].sort(key=lambda f: f["file_path"])
    names = [f["file_path"] for f in meta["frames"]]
    # The photometric test set is separate. SfM uses all photos for pose estimation.
    meta["test_filenames"] = names[::12]
    meta["val_filenames"] = names[6::12]
    held = set(meta["test_filenames"] + meta["val_filenames"])
    meta["train_filenames"] = [n for n in names if n not in held]
    for frame in meta["frames"]:
        m = np.asarray(frame["transform_matrix"])
        if not np.isfinite(m).all() or not np.allclose(m[:3, :3].T @ m[:3, :3], np.eye(3), atol=1e-4):
            raise RuntimeError("A camera pose is invalid. Do not train on this model.")
    meta_path.write_text(json.dumps(meta, indent=2))
    report = {
        "registered": count,
        "source_count": len(run["images"]),
        "points": len(points),
        "mean_reprojection_error": float(np.mean([p.error for p in points.values()])),
        "median_track_length": float(np.median([len(p.image_ids) for p in points.values()])),
        "models": [{"registered": n, "model": p.name} for n, p in models],
        "split": {s: len(meta[s + "_filenames"]) for s in ("train", "val", "test")},
    }
    (root / "camera-report.json").write_text(json.dumps(report, indent=2))
    print(json.dumps(report), flush=True)


def entry(name, arguments):
    sys.argv = [name, *map(str, arguments)]
    next(e for e in distribution("nerfstudio").entry_points if e.name == name).load()()


def viewer_defaults():
    # Nerfstudio 1.1.5 hard-codes a 512 px preview. Change only this local process,
    # leaving installed package files untouched. Higher resolution costs latency.
    from nerfstudio.viewer import control_panel

    original = control_panel.ViewerSlider.__init__

    def slider(self, name, *args, **kwargs):
        if name == "Max res":
            if args:
                args = (1600, *args[1:])
            else:
                kwargs["default_value"] = 1600
        original(self, name, *args, **kwargs)

    control_panel.ViewerSlider.__init__ = slider


def main():
    action, root = sys.argv[1], Path(sys.argv[2])
    if action == "environment":
        print(json.dumps(versions()))
        return
    if action == "verify":
        return gpu_test(root)
    if action == "convert":
        return convert(root)
    setup_gpu()
    run = json.loads((root / "record.json").read_text())
    if action == "train":
        existing = sorted((root / "outputs").rglob("*.ckpt")) if (root / "outputs").exists() else []
        resume = (
            ["--load-dir", str(max(existing, key=lambda p: p.stat().st_mtime).parent)] if existing else []
        )
        entry(
            "ns-train",
            [
                "splatfacto",
                "--data",
                root / "dataset",
                "--output-dir",
                root / "outputs",
                "--experiment-name",
                "scene",
                "--max-num-iterations",
                run["settings"]["steps"],
                "--machine.seed",
                run["settings"]["seed"],
                "--steps-per-save",
                1000,
                "--save-only-latest-checkpoint",
                "True",
                "--vis",
                "tensorboard",
                "--pipeline.model.background-color",
                "black",
                *resume,
                "nerfstudio-data",
                "--center-method",
                "focus",
            ],
        )
    else:
        configs = [
            p
            for p in (root / "outputs").rglob("config.yml")
            if list((p.parent / "nerfstudio_models").glob("*.ckpt"))
        ]
        if not configs:
            raise RuntimeError("No saved checkpoint exists. Finish or resume training first.")
        config = max(configs, key=lambda p: p.stat().st_mtime)
        if action == "evaluate":
            entry(
                "ns-eval",
                [
                    "--load-config",
                    config,
                    "--output-path",
                    root / "metrics.json",
                    "--render-output-path",
                    root / "renders",
                ],
            )
        elif action == "export":
            entry("ns-export", ["gaussian-splat", "--load-config", config, "--output-dir", root / "export"])
        elif action == "view":
            viewer_defaults()
            entry(
                "ns-viewer",
                [
                    "--load-config",
                    config,
                    "--viewer.websocket-host",
                    "127.0.0.1",
                    "--viewer.websocket-port",
                    sys.argv[3],
                    "--viewer.jpeg-quality",
                    95,
                ],
            )
        else:
            raise ValueError("Unknown engine action.")


if __name__ == "__main__":
    main()
