# Optional Docker setup

```text
Your system                          Photo to Splat container
NVIDIA GPU + compatible driver  →    Linux + Python + reconstruction tools
Docker with GPU access                UI and queue
                                      ↓
Browser at localhost:8765        ←    persistent scenes volume at /data
```

The Dockerfile and Compose files live in this repository. The GPU image packages
the same native and Python locks used by the local installer. Host drivers and
GPU access remain prerequisites.

The [uv setup](../README.md#run-locally-with-uv) is the recommended delivery route.
Use Docker if you prefer a container and already have working Docker GPU access.
Its large image and build caches require additional storage.

## Current availability

This route builds from source; no public prebuilt image is provided.
`docker compose pull` is not a working first-install command. Build the image
locally using the command below. No personal photos or workspaces belong in it.

## Host prerequisites

- Windows x86_64: Docker Desktop using its WSL2 backend and a compatible NVIDIA
  driver. Follow [Docker's Windows GPU guide](https://docs.docker.com/desktop/features/gpu/).
- Linux x86_64: Docker Engine, Compose, a compatible NVIDIA driver, and the
  [NVIDIA Container Toolkit](https://docs.nvidia.com/datacenter/cloud-native/container-toolkit/latest/install-guide.html).
- For a source build, allow roughly 60–100 GB for the image and build caches,
  plus imported photos and runs. This is a planning allowance, not a fixed size.
  Docker Desktop's virtual disk can fill independently of the host photo drive.
- The selected GPU still needs enough VRAM for the capture. Containers do not
  add GPU memory or enable this CUDA workflow on AMD, integrated GPUs, or macOS.
- The CPU must support x86-64-v3 or newer, including AVX2/FMA. The pinned COLMAP
  environment includes an `x86_64_v3` package requirement; Docker uses your host CPU.

Run one studio instance per GPU. The app coordinates its own jobs, but separate
Docker projects or a second local uv instance have independent queues.

Python, uv, Node.js, COLMAP, and a host CUDA development toolkit are not needed
for this route. They are included or used during the container build instead.
Internet access is needed for the build and first-use metric downloads.

## Build and start

Download/extract or clone the repository, open a terminal in its folder, and run:

```bash
docker compose -f compose.yaml -f compose.build.yaml up -d --build
```

The override builds the `gpu` target and tags it `photo-to-splat:local`. The first
build downloads the locked tools. Later builds can reuse unchanged layers while
Docker retains the build cache.
Open **http://localhost:8765** and verify the GPU through **Computer & setup**.
GPU detection alone does not establish successful Gaussian rendering.

After the first build, start the existing image with `docker compose up -d`.
There is no need to rebuild the image for each scene or each application launch.

```bash
docker compose ps
docker compose logs --tail 100 studio
docker compose down
```

`down` stops the container and retains its named volumes. **`down --volumes`
permanently deletes those volumes and their scene data.** Export results and back
up the scenes volume before deliberately removing it.

## Photos and persistent storage

The `photo-to-splat_scenes` volume is mounted at `/data` and stores application
settings, imports, run records, checkpoints, comparisons, and exports. The
`photo-to-splat_cache` volume is mounted at `/cache` and stores compilation and
model-download caches. Recreating the container preserves attached volumes.

Use the browser's photo/folder selector to import from your host system. The
application's workspace folder browser shows paths inside `/data`, not arbitrary
host folders. Workspaces outside `/data` are rejected to prevent saving results
in a disposable container layer. Docker volume storage is separate from your
existing local uv workspace; this setup does not migrate its trained runs.

Docker Desktop's **Volumes** page can inspect and back up named volumes. Keep
backups outside Docker's virtual disk. On Linux, follow Docker's
[volume backup guidance](https://docs.docker.com/engine/storage/volumes/).

## Ports and updates

The UI and viewer are published only on host loopback. The viewer uses one
container port, 7010. If a host port is already taken, copy `.env.example` to
`.env`, change the relevant value, and recreate the container:

```text
PHOTOSPLAT_UI_PORT=8876
PHOTOSPLAT_VIEWER_PORT=17010
```

The UI is then at `http://localhost:8876`; viewer links use port 17010.
Use these variables rather than changing only the port mapping, so the generated
viewer URL stays correct. Server logs still show the internal UI port, 8765;
open the host port you configured. Do not expose the ports on a public interface.

For a local-source update, stop active work and rebuild using the original build
command. `PHOTOSPLAT_IMAGE` can select an image you have built or obtained
separately; the default is the local build. Recreate the container to replace
packaged tools; the UI does not offer an installer or custom runtime paths in
Docker mode.

## Common startup problems

| What you see | What to check |
|---|---|
| Docker cannot connect to its engine | Start Docker Desktop, or start Docker Engine on Linux. |
| No NVIDIA device driver / GPU request fails | Check the host driver and Docker GPU setup in the guides above. Installing tools inside the image will not fix host GPU access. |
| Port is already allocated | Change the host ports in `.env`, then recreate the container. |
| The container is healthy but the GPU is unverified | Health checks cover the web server. Open **Computer & setup** and run **Verify GPU execution**. |
| First GPU check is taking several minutes | CUDA kernels compile on first use. Keep the cache volume attached for later runs. |
| A custom bind mount reports permission errors | Check that UID/GID 10001 can write to it, or use the default named volumes. |

## Build and test details

The Ubuntu and uv base images are pinned by digest. Native package URLs/hashes
and Python dependencies use the repository locks. Ubuntu security packages can
change on rebuild; a released image digest identifies a particular built artifact.

The image runs as UID/GID 10001, with a read-only root filesystem. `/data`,
`/cache`, and temporary files are writable. The default named volumes receive the
image's directory ownership; custom bind mounts require matching permissions.
No host Docker socket or privileged container is needed.

The lightweight `app` target exists for CPU CI; it does not include reconstruction
tools and is not the image intended for users. Maintainers can test it with:

```bash
docker build --target app -t photo-to-splat:cpu-check .
uv run python scripts/smoke_container.py --image photo-to-splat:cpu-check
```

On a GPU-enabled host, validate the full image with:

```bash
uv run python scripts/smoke_container.py --image photo-to-splat:local --gpu
```

The script uses labeled disposable volumes, imports a generated test photo, and
checks persistence across container replacement. With `--gpu`, it runs the real
Gaussian render/gradient check, tests PyTorch compilation with writable caches,
and checks saved verification reuse. It removes only its own test resources.
See the [verification record](verification.md) for the separate photo-to-export
integration run. These checks do not establish compatibility with another GPU
model or reliability of every long viewer session.
