"""Test container networking and persistence with disposable, labeled volumes.

Pass --gpu only on a host with Docker GPU access. It runs the real gsplat render
test; the default target checks delivery without installing or using CUDA.
"""

import argparse
import io
import json
import subprocess
import time
import uuid
from urllib.request import Request, urlopen

from PIL import Image


def docker(*arguments):
    return subprocess.check_output(["docker", *arguments], text=True).strip()


def request(url, body=None):
    data = json.dumps(body).encode() if body is not None else None
    with urlopen(
        Request(url, data=data, headers={"Content-Type": "application/json"}), timeout=10
    ) as response:
        return json.load(response)


def wait_for_state(base, predicate, timeout=180):
    deadline = time.monotonic() + timeout
    last = None
    while time.monotonic() < deadline:
        try:
            last = request(base + "/api/state")
            if predicate(last):
                return last
        except OSError:
            pass
        time.sleep(1)
    raise AssertionError(f"Container did not become ready: {last}")


def upload_photo(base, scene_id):
    photo = io.BytesIO()
    Image.new("RGB", (64, 48), color=(180, 120, 50)).save(photo, format="PNG")
    boundary = "photosplat-" + uuid.uuid4().hex
    payload = (
        (
            f'--{boundary}\r\nContent-Disposition: form-data; name="files"; filename="fixture.png"\r\n'
            "Content-Type: image/png\r\n\r\n"
        ).encode()
        + photo.getvalue()
        + f"\r\n--{boundary}--\r\n".encode()
    )
    with urlopen(
        Request(
            f"{base}/api/scenes/{scene_id}/photos",
            data=payload,
            headers={"Content-Type": f"multipart/form-data; boundary={boundary}"},
        ),
        timeout=10,
    ) as response:
        result = json.load(response)
    assert not result["errors"] and len(result["imported"]) == 1, result
    return result["imported"][0]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--image", default="photo-to-splat:cpu-check")
    parser.add_argument("--gpu", action="store_true")
    args = parser.parse_args()
    name = "photosplat-smoke-" + uuid.uuid4().hex[:12]
    label = "com.photosplat.smoke=" + name
    volumes = [name + "-data", name + "-cache"]
    created_volumes = []
    created = False

    def start():
        nonlocal created
        docker(
            "run",
            "-d",
            "--name",
            name,
            "--label",
            label,
            "--read-only",
            "--tmpfs",
            "/tmp:size=2g,mode=1777",
            "--cap-drop",
            "ALL",
            "--security-opt",
            "no-new-privileges:true",
            "--shm-size",
            "2g",
            "-p",
            "127.0.0.1::8765",
            "-v",
            f"{volumes[0]}:/data",
            "-v",
            f"{volumes[1]}:/cache",
            *(["--gpus", "all"] if args.gpu else []),
            args.image,
        )
        created = True
        port = docker("port", name, "8765/tcp").rsplit(":", 1)[1]
        return f"http://127.0.0.1:{port}"

    def remove_container():
        nonlocal created
        if created:
            info = json.loads(docker("inspect", name))[0]
            assert info["Config"]["Labels"].get("com.photosplat.smoke") == name
            docker("stop", "--time", "60", name)
            docker("rm", name)
            created = False

    try:
        for volume in volumes:
            docker("volume", "create", "--label", label, volume)
            created_volumes.append(volume)
        base = start()
        state = wait_for_state(base, lambda s: s["diagnostic"]["state"] not in {"checking", "verifying"})
        assert state["delivery"]["mode"] == "docker" and state["settings"]["workspace"] == "/data"
        assert not state["scenes"] and not state["record_issues"]
        with urlopen(base, timeout=10) as response:
            assert b"Photo to Splat" in response.read()
        scene = request(base + "/api/scenes", {"name": "Container smoke test"})
        photo = upload_photo(base, scene["id"])
        if args.gpu:
            assert state["diagnostic"]["tools_installed"], state["diagnostic"]
            assert state["diagnostic"]["state"] == "verify", state["diagnostic"]
            request(base + "/api/diagnostics?verify=true", {})
            state = wait_for_state(
                base, lambda s: s["diagnostic"]["state"] not in {"checking", "verifying"}, timeout=1000
            )
            assert state["diagnostic"]["verified"], state["diagnostic"]
            print("GPU render and gradient test passed.", flush=True)
            # Training also uses PyTorch's compiler, whose caches must be writable.
            compile_test = (
                "import torch; x=torch.randn(32,device='cuda',requires_grad=True); "
                "y=torch.compile(lambda z: (z.sin()*z).sum())(x); y.backward(); "
                "assert torch.isfinite(x.grad).all(); print('PyTorch compiler and cache test passed.')"
            )
            print(
                docker(
                    "exec",
                    name,
                    "python",
                    "-c",
                    "from photosplat.runtime import Runtime; "
                    f"print(Runtime().capture('train', ['python', '-c', {compile_test!r}], timeout=180))",
                ),
                flush=True,
            )
        remove_container()
        base = start()
        restored = wait_for_state(base, lambda s: s["diagnostic"]["state"] not in {"checking", "verifying"})
        assert restored["scenes"][0]["id"] == scene["id"]
        assert restored["scenes"][0]["images"][0]["sha256"] == photo["sha256"]
        with urlopen(f"{base}/api/scenes/{scene['id']}/thumb/{photo['id']}", timeout=10) as response:
            assert response.status == 200 and response.headers["Content-Type"].startswith("image/")
        if args.gpu:
            assert restored["diagnostic"]["verified"], restored["diagnostic"]
        print("Container UI, photo import, named-volume persistence, and restart checks passed.")
    finally:
        if created:
            print(docker("logs", "--tail", "25", name))
            remove_container()
        for volume in created_volumes:
            info = json.loads(docker("volume", "inspect", volume))[0]
            assert info["Labels"].get("com.photosplat.smoke") == name
            docker("volume", "rm", volume)


if __name__ == "__main__":
    main()
