"""Run with a freshly installed wheel, from outside the source checkout."""

import tempfile
from pathlib import Path

from fastapi.testclient import TestClient

from photosplat.app import create_app


def main():
    with tempfile.TemporaryDirectory() as directory:
        with TestClient(create_app(Path(directory), worker=False)) as client:
            assert client.get("/").status_code == 200
            state = client.get("/api/state").json()
            assert state["scenes"] == [] and state["record_issues"] == []
            assert client.get("/demo.mp4").status_code == 200
            scene = client.post("/api/scenes", json={"name": "Wheel smoke test"})
            assert scene.status_code == 201
    print("Installed wheel serves its UI and can create an isolated scene.")


if __name__ == "__main__":
    main()
