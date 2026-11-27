export async function api<T = any>(
  path: string,
  body?: unknown,
  method = "POST",
): Promise<T> {
  let response: Response;
  try {
    response = await fetch(
      `/api${path}`,
      body === undefined
        ? undefined
        : {
            method,
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify(body),
          },
    );
  } catch {
    throw new Error(
      "Cannot reach the local app. Keep its terminal running, then retry.",
    );
  }
  const result = await response.json().catch(() => {
    throw new Error(
      "The local app returned an unexpected response. Restart it and retry.",
    );
  });
  if (!response.ok)
    throw new Error(
      typeof result.detail === "string"
        ? result.detail
        : JSON.stringify(result.detail),
    );
  return result;
}
export const bytes = (value = 0) =>
  value >= 1024 ** 3
    ? `${(value / 1024 ** 3).toFixed(1)} GB`
    : `${(value / 1024 ** 2).toFixed(0)} MB`;
export type Photo = {
  id: string;
  name: string;
  width: number;
  height: number;
  bytes: number;
};
export type Scene = {
  id: string;
  name: string;
  images: Photo[];
  created: string;
  deleted_at?: string;
  purging?: boolean;
  purge_error?: string | null;
};
export type Run = {
  id: string;
  scene_id: string;
  scene_name: string;
  status: string;
  stage: string;
  completed: string[];
  error: string | null;
  created: string;
  settings: any;
};
export type State = {
  record_issues?: { kind: string; path: string; message: string }[];
  background?: {
    id?: string;
    kind: string;
    state: string;
    error?: string;
    stop_requested?: boolean;
  } | null;
  activity?: import("./activity").Activity | null;
  scenes: Scene[];
  runs: Run[];
  diagnostic: any;
  settings: any;
  stages: { id: string; label: string }[];
  setup: any;
  setup_profile?: string;
  setup_reviewed?: boolean;
  trash?: Scene[];
  viewers?: Record<string, { url: string }>;
};
