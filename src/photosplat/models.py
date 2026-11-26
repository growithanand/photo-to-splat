from typing import Literal

from pydantic import BaseModel, Field


class SceneRequest(BaseModel):
    name: str = Field(min_length=1, max_length=100)


class RunOptions(BaseModel):
    preset: Literal["quick", "balanced"] = "quick"
    steps: int = Field(default=7000, ge=100, le=100000)
    max_size: int = Field(default=1600, ge=400, le=3200)
    matching: Literal["exhaustive", "sequential"] = "exhaustive"
    camera_mode: Literal["auto", "shared", "per-image"] = "auto"
    sfm_gpu: bool = True
    min_registration: float = Field(default=0.7, ge=0.3, le=1)
    seed: int = Field(default=42, ge=0, le=2147483647)
    image_ids: list[str] | None = None


class RuntimeOptions(BaseModel):
    mode: Literal["auto", "native", "wsl"] = "auto"
    distro: str = Field(default="Ubuntu", pattern=r"^[\w. -]{1,64}$")
    train_prefix: str = ""
    sfm_prefix: str = ""
