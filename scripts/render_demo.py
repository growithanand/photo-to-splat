"""Render a real, trained synthetic splat into the welcome-screen assets.

This is a maintainer tool, not part of reconstruction. The input is a locally
trained synthetic turntable scene with world Z up. No personal photographs are
needed. Run it inside a compatible Nerfstudio environment.
"""

from __future__ import annotations

import argparse
import json
import math
from pathlib import Path

import av
import numpy as np
import torch
from PIL import Image


def unit(vector: np.ndarray) -> np.ndarray:
    return vector / np.linalg.norm(vector)


def focus_from_cameras(poses: np.ndarray) -> np.ndarray:
    # Find the point closest to all camera optical axes. For this synthetic
    # capture the axes meet exactly, so the orbit stays centered on the owl.
    centers, rays = poses[:, :3, 3], -poses[:, :3, 2]
    projectors = np.eye(3)[None] - rays[:, :, None] * rays[:, None, :]
    return np.linalg.lstsq(projectors.sum(0), np.einsum("nij,nj->i", projectors, centers), rcond=None)[0]


def orbit_pose(angle: float, elevation: float, radius: float, target: np.ndarray) -> np.ndarray:
    center = target + radius * np.array(
        [
            np.cos(elevation) * np.sin(angle),
            -np.cos(elevation) * np.cos(angle),
            np.sin(elevation),
        ]
    )
    back = unit(center - target)
    right = unit(np.cross([0.0, 0.0, 1.0], back))
    up = np.cross(back, right)
    matrix = np.eye(4)
    matrix[:3, :3] = np.column_stack([right, up, back])
    matrix[:3, 3] = center
    return matrix


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", type=Path, required=True)
    parser.add_argument("--dataset", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--frames", type=int, default=72)
    parser.add_argument("--size", type=int, default=480)
    parser.add_argument("--fps", type=int, default=12)
    args = parser.parse_args()
    if args.size % 2 or args.frames < 24:
        parser.error("Use an even resolution and at least 24 frames.")

    # Nerfstudio stores NumPy scheduler scalars in its own checkpoints. Keep
    # PyTorch's weights-only loading and allow only the required scalar types.
    torch.serialization.add_safe_globals(
        [
            np.dtype,
            np.core.multiarray.scalar,
            type(np.dtype("float64")),
            type(np.dtype("float32")),
            type(np.dtype("int64")),
        ]
    )
    from nerfstudio.cameras.cameras import Cameras, CameraType
    from nerfstudio.utils.eval_utils import eval_setup

    metadata = json.loads((args.dataset / "transforms.json").read_text())
    source_poses = np.array([frame["transform_matrix"] for frame in metadata["frames"]])
    target = focus_from_cameras(source_poses)
    radius = float(np.median(np.linalg.norm(source_poses[:, :3, 3] - target, axis=1)))
    saved = json.loads((args.config.parent / "dataparser_transforms.json").read_text())
    transform = np.eye(4)
    transform[:3] = saved["transform"]

    _, pipeline, _, step = eval_setup(args.config)
    pipeline.model.eval()
    args.output.mkdir(parents=True, exist_ok=True)
    destination = args.output / "demo.mp4"
    poster = args.output / "demo-poster.jpg"
    with av.open(str(destination), mode="w", options={"movflags": "+faststart"}) as container:
        stream = container.add_stream("libx264", rate=args.fps)
        stream.width = stream.height = args.size
        stream.pix_fmt = "yuv420p"
        stream.options = {"crf": "23", "preset": "slow"}
        with torch.no_grad():
            for index in range(args.frames):
                pose = transform @ orbit_pose(
                    2 * math.pi * index / args.frames, math.radians(23), radius, target
                )
                pose[:3, 3] *= saved["scale"]
                camera = Cameras(
                    camera_to_worlds=torch.tensor(pose[:3], dtype=torch.float32)[None],
                    fx=float(metadata["fl_x"]) * args.size / metadata["w"],
                    fy=float(metadata["fl_y"]) * args.size / metadata["h"],
                    cx=args.size / 2,
                    cy=args.size / 2,
                    width=args.size,
                    height=args.size,
                    camera_type=CameraType.PERSPECTIVE,
                ).to(pipeline.model.device)
                output = pipeline.model.get_outputs_for_camera(camera)
                pixels = (output["rgb"].clamp(0, 1).cpu().numpy() * 255).astype(np.uint8)
                if index == 0:
                    Image.fromarray(pixels).save(poster, quality=92)
                frame = av.VideoFrame.from_ndarray(pixels, format="rgb24")
                for packet in stream.encode(frame):
                    container.mux(packet)
                if index % 12 == 0:
                    print(f"Rendered {index + 1}/{args.frames}", flush=True)
        for packet in stream.encode():
            container.mux(packet)
    (args.output / "demo.provenance.json").write_text(
        json.dumps(
            {
                "kind": "actual Gaussian splatting output",
                "subject": "procedural synthetic golden owl; no personal photographs",
                "dataset": "owl-alpha",
                "method": "Nerfstudio Splatfacto",
                "training_iterations": step + 1,
                "frames": args.frames,
                "fps": args.fps,
                "resolution": [args.size, args.size],
                "camera_path": "full 360 degree orbit at 23 degree elevation",
                "generation_script": "scripts/render_demo.py",
                "note": "The clip is a prerecorded example, not a reconstruction of the visitor\u2019s photos.",
            },
            indent=2,
        ),
        encoding="utf-8",
    )
    print(f"Saved {destination} ({destination.stat().st_size:,} bytes)", flush=True)


if __name__ == "__main__":
    main()
