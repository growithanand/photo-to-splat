import type { State } from "./api";

export type Activity = {
  kind: string;
  message: string;
  run_id?: string;
  scene_id?: string;
};

export function getActivity(state: State | null | undefined): Activity | null {
  if (!state) return null;
  // Derive run admission from the latest records too. This keeps the UI safe
  // while an older server is still finishing work during a frontend upgrade.
  const run =
    state.runs.find((r) => r.status === "running") ||
    state.runs.find((r) => r.status === "queued");
  if (run)
    return {
      kind: "reconstruction",
      message: `Reconstruction ${run.status} for “${run.scene_name || "this scene"}”.`,
      run_id: run.id,
      scene_id: run.scene_id,
    };
  if (state.setup.state === "running")
    return {
      kind: "setup",
      message: "Wait for reconstruction-tool setup to finish.",
    };
  if (["checking", "verifying"].includes(state.diagnostic.state))
    return {
      kind: "diagnostics",
      message: "Wait for the tool and GPU checks to finish.",
    };
  const viewer = Object.keys(state.viewers || {})[0];
  if (viewer)
    return {
      kind: "viewer",
      message: "Stop the open 3D viewer before starting other GPU work.",
      run_id: viewer,
      scene_id: state.runs.find((r) => r.id === viewer)?.scene_id,
    };
  return state.activity || null;
}
