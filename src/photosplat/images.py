from __future__ import annotations

import io
import warnings
from pathlib import Path

from PIL import Image, ImageOps, UnidentifiedImageError

from .store import Store, digest, identity, now

SUPPORTED = {".jpg", ".jpeg", ".png", ".tif", ".tiff", ".webp"}
MAX_BYTES = 50 * 1024 * 1024
Image.MAX_IMAGE_PIXELS = 80_000_000


def import_image(store: Store, scene_id: str, name: str, payload: bytes) -> dict:
    suffix = Path(name.replace("\\", "/")).suffix.lower()
    if suffix not in SUPPORTED:
        raise ValueError(f"{name}: use JPEG, PNG, TIFF, or WebP. Convert HEIC/RAW before import.")
    if len(payload) > MAX_BYTES:
        raise ValueError(f"{name}: files must be smaller than 50 MB; use a working JPEG copy.")
    try:
        with warnings.catch_warnings():
            warnings.simplefilter("error", Image.DecompressionBombWarning)
            with Image.open(io.BytesIO(payload)) as raw:
                if raw.width * raw.height > Image.MAX_IMAGE_PIXELS:
                    raise ValueError("Use photos smaller than 80 megapixels.")
                raw.verify()
            with Image.open(io.BytesIO(payload)) as raw:
                exif = raw.getexif()
                details = exif.get_ifd(34665)
                image = ImageOps.exif_transpose(raw)
                info = dict(
                    width=image.width,
                    height=image.height,
                    model=str(exif.get(272, "Unknown camera")),
                    focal_35mm=float(details.get(41989) or 0),
                )
                thumb = image.convert("RGB")
                thumb.thumbnail((360, 280))
    except (
        UnidentifiedImageError,
        OSError,
        Image.DecompressionBombError,
        Image.DecompressionBombWarning,
    ) as exc:
        raise ValueError(f"{name}: this image cannot be safely decoded ({exc}).") from exc
    folder = store.path("scenes", scene_id)
    originals = folder / "originals"
    originals.mkdir(exist_ok=True)
    temporary = originals / f".{identity()}.upload"
    temporary.write_bytes(payload)
    checksum = digest(temporary)
    try:
        with store.lock:
            scene = store.get("scenes", scene_id)
            duplicate = next((i for i in scene["images"] if i["sha256"] == checksum), None)
            if duplicate:
                return {**duplicate, "duplicate": True}
            item_id = identity()
            filename = f"{item_id}{suffix}"
            temporary.replace(originals / filename)
            (folder / "thumbs").mkdir(exist_ok=True)
            thumb.save(folder / "thumbs" / f"{item_id}.jpg", quality=85)
            record = dict(
                id=item_id,
                filename=filename,
                name=Path(name.replace("\\", "/")).name,
                sha256=checksum,
                bytes=len(payload),
                imported=now(),
                **info,
            )
            scene["images"].append(record)
            store.save("scenes", scene)
            return record
    finally:
        temporary.unlink(missing_ok=True)


def prepare(store: Store, run: dict) -> None:
    from .store import write

    root = store.path("runs", run["id"])
    images = root / "dataset" / "images"
    images.mkdir(parents=True, exist_ok=True)
    manifest = []
    for index, item in enumerate(run["images"]):
        source = store.path("scenes", run["scene_id"]) / "originals" / item["filename"]
        if digest(source) != item["sha256"]:
            raise ValueError(
                f"Imported photo changed: {item['name']}. Create a new scene instead of editing snapshots."
            )
        with Image.open(source) as raw:
            image = ImageOps.exif_transpose(raw)
            transparent = "A" in image.getbands() or "transparency" in image.info
            image = image.convert("RGBA" if transparent else "RGB")
            image.thumbnail((run["settings"]["max_size"],) * 2, Image.Resampling.LANCZOS)
            name = f"frame_{index:06d}.{'png' if transparent else 'jpg'}"
            image.save(images / name, **({} if transparent else {"quality": 95, "subsampling": 0}))
            manifest.append(
                {
                    **item,
                    "prepared": name,
                    "prepared_width": image.width,
                    "prepared_height": image.height,
                    "prepared_sha256": digest(images / name),
                }
            )
    write(root / "dataset" / "capture.json", {"images": manifest})


def estimate(images: list[dict], max_size: int) -> dict:
    source = sum(i["bytes"] for i in images)
    pixels = sum(
        min(1, max_size / max(i["width"], i["height"])) ** 2 * i["width"] * i["height"] for i in images
    )
    # Checkpoints depend strongly on densification. Present a planning range, never a guarantee.
    low = source + pixels * 2 + 3 * 1024**3
    high = source + pixels * 10 + 15 * 1024**3
    return {
        "source_bytes": source,
        "working_low_bytes": int(low),
        "working_high_bytes": int(high),
        "note": "Working-space planning range, excluding environments and downloads; large scenes can exceed it.",
    }
