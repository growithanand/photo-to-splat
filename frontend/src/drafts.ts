import type { Scene } from "./api";

type Draft = {
  selected: string[];
  known: string[];
  preset: string;
  steps: number;
  maxSize: number;
  matching: string;
  cameraMode: string;
};
const key = (workspace: string, sceneId: string) =>
  `photosplat.draft:${workspace}:${sceneId}`;

export function readDraft(workspace: string, scene: Scene): Draft {
  const ids = scene.images.map((image) => image.id);
  const defaults = {
    selected: ids,
    known: ids,
    preset: "quick",
    steps: 7000,
    maxSize: 1600,
    matching: "exhaustive",
    cameraMode: "auto",
  };
  try {
    const saved = JSON.parse(
      sessionStorage.getItem(key(workspace, scene.id)) || "null",
    );
    if (!saved || !Array.isArray(saved.selected) || !Array.isArray(saved.known))
      return defaults;
    return {
      selected: saved.selected.filter((id: string) => ids.includes(id)),
      known: saved.known.filter((id: string) => ids.includes(id)),
      preset: ["quick", "balanced"].includes(saved.preset)
        ? saved.preset
        : defaults.preset,
      steps:
        Number.isInteger(saved.steps) &&
        saved.steps >= 100 &&
        saved.steps <= 100000
          ? saved.steps
          : defaults.steps,
      maxSize: [800, 1600, 2400].includes(saved.maxSize)
        ? saved.maxSize
        : defaults.maxSize,
      matching: ["exhaustive", "sequential"].includes(saved.matching)
        ? saved.matching
        : defaults.matching,
      cameraMode: ["auto", "shared", "per-image"].includes(saved.cameraMode)
        ? saved.cameraMode
        : defaults.cameraMode,
    };
  } catch {
    return defaults;
  }
}

export function saveDraft(workspace: string, sceneId: string, draft: Draft) {
  // A browser draft is a convenience. Saved runs remain in the local workspace.
  try {
    sessionStorage.setItem(key(workspace, sceneId), JSON.stringify(draft));
  } catch {
    /* Private browsing may deny storage. */
  }
}
