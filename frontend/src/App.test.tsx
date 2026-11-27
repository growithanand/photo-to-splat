// @vitest-environment jsdom
import React from "react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import {
  cleanup,
  fireEvent,
  render,
  screen,
  waitFor,
  within,
} from "@testing-library/react";
import "@testing-library/jest-dom/vitest";
import { api } from "./api";
import { App } from "./App";
import { readRoute, runLink } from "./navigation";

vi.mock("./api", async (original) => ({
  ...(await original<typeof import("./api")>()),
  api: vi.fn(),
}));
const sceneId = "a".repeat(32),
  runId = "c".repeat(32);
let data: any;
let failRun = false;
let failState = false;
const mockApi = vi.mocked(api);

beforeEach(() => {
  sessionStorage.clear();
  history.replaceState(null, "", "/#/scenes");
  window.scrollTo = vi.fn();
  window.matchMedia = vi.fn().mockReturnValue({
    matches: false,
    addEventListener: vi.fn(),
    removeEventListener: vi.fn(),
  });
  failRun = failState = false;
  data = {
    scenes: [
      {
        id: sceneId,
        name: "Vase",
        images: [],
        created: "2026-01-01T00:00:00Z",
      },
    ],
    runs: [],
    trash: [],
    viewers: {},
    diagnostic: { state: "unsupported", verified: false, checks: [] },
    settings: {
      workspace: "C:\\UX test",
      runtime: {
        mode: "auto",
        distro: "Ubuntu",
        train_prefix: "",
        sfm_prefix: "",
      },
    },
    setup: { state: "idle" },
    setup_profile: "test-profile",
    setup_reviewed: false,
    stages: [
      { id: "verify", label: "Verifying GPU execution" },
      { id: "train", label: "Learning the Gaussian scene" },
    ],
  };
  mockApi.mockReset();
  mockApi.mockImplementation(async (path, body: any, method) => {
    if (path === "/state") {
      if (failState) throw new Error("Cannot reach the local app.");
      return structuredClone({
        ...data,
        runs: data.runs.filter((r: any) =>
          data.scenes.some((s: any) => s.id === r.scene_id),
        ),
      });
    }
    if (path === "/scenes") {
      const scene = {
        id: "b".repeat(32),
        name: body.name,
        images: [],
        created: new Date().toISOString(),
      };
      data.scenes.unshift(scene);
      return scene;
    }
    if (path === "/setup/review") {
      data.setup_reviewed = body.reviewed;
      return { reviewed: body.reviewed };
    }
    if (path === "/setup") {
      data.setup = { state: "running" };
      return data.setup;
    }
    if (path === "/setup/log") return { text: "Temporary installation log" };
    if (path.startsWith("/diagnostics")) return { started: true };
    if (path.endsWith("/restore")) {
      const scene = data.trash.shift();
      delete scene.deleted_at;
      data.scenes.push(scene);
      return scene;
    }
    if (path === "/trash/purge") {
      const ids = body.scene_ids as string[];
      data.trash = data.trash.filter((scene: any) => !ids.includes(scene.id));
      data.runs = data.runs.filter((run: any) => !ids.includes(run.scene_id));
      return { deleted_scene_ids: ids, failed: [] };
    }
    if (method === "DELETE") {
      const scene = data.scenes.shift();
      scene.deleted_at = new Date().toISOString();
      data.trash.push(scene);
      return scene;
    }
    if (method === "PATCH") {
      data.scenes[0].name = body.name;
      return data.scenes[0];
    }
    if (path.endsWith("/estimate"))
      return {
        working_low_bytes: 1024 ** 3,
        working_high_bytes: 3 * 1024 ** 3,
        free_bytes: 100 * 1024 ** 3,
      };
    if (path === `/runs/${runId}`) {
      if (failRun) throw new Error("The run could not be loaded.");
      return {
        ...data.runs[0],
        images: [],
        camera_report: null,
        metrics: null,
        renders: [],
        export_ready: false,
      };
    }
    throw new Error(`Unexpected request ${method || "GET"} ${path}`);
  });
});
afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
});

describe("workspace navigation and scene management", () => {
  it("makes Workspace clickable and supports browser Back", async () => {
    render(<App />);
    await screen.findByRole("link", { name: "Open Vase" });
    fireEvent.click(
      within(screen.getByRole("navigation", { name: "Breadcrumb" })).getByRole(
        "link",
        { name: "Workspace" },
      ),
    );
    await screen.findByRole("heading", {
      name: "Your reconstruction workspace.",
    });
    history.back();
    await screen.findByRole("heading", {
      name: "My scenes",
    });
  });
  it("restores a deep run URL after refresh and links back to its scene", async () => {
    data.runs = [
      {
        id: runId,
        scene_id: sceneId,
        scene_name: "Vase",
        status: "complete",
        stage: "complete",
        completed: ["verify", "train"],
        created: "2026-01-01",
        settings: { steps: 7000, max_size: 1600 },
      },
    ];
    history.replaceState(null, "", `/${runLink(sceneId, runId)}`);
    render(<App />);
    await screen.findByRole("heading", { name: "Vase" });
    expect(screen.getByRole("button", { name: "Back to scene" })).toBeVisible();
    fireEvent.click(
      within(screen.getByRole("navigation", { name: "Breadcrumb" })).getByRole(
        "link",
        { name: "Vase" },
      ),
    );
    await screen.findByRole("heading", { name: "Bring your photos together." });
    expect(location.hash).toBe(`#/scenes/${sceneId}`);
  });
  it("can cancel deletion, move a scene to Trash, and undo", async () => {
    render(<App />);
    fireEvent.click(await screen.findByRole("button", { name: "Delete Vase" }));
    fireEvent.click(
      within(screen.getByRole("dialog")).getByRole("button", {
        name: "Cancel",
      }),
    );
    expect(mockApi.mock.calls.some((call) => call[2] === "DELETE")).toBe(false);
    fireEvent.click(screen.getByRole("button", { name: "Delete Vase" }));
    fireEvent.click(
      within(screen.getByRole("dialog")).getByRole("button", {
        name: "Move to Trash",
      }),
    );
    await waitFor(() =>
      expect(
        screen.queryByRole("link", { name: "Open Vase" }),
      ).not.toBeInTheDocument(),
    );
    fireEvent.click(await screen.findByRole("button", { name: "Undo" }));
    await screen.findByRole("heading", { name: "Vase" });
    expect(data.trash).toHaveLength(0);
    expect(data.scenes).toHaveLength(1);
  });
  it("renames scenes and rejects whitespace-only names", async () => {
    render(<App />);
    fireEvent.click(await screen.findByRole("button", { name: "Rename Vase" }));
    const dialog = within(screen.getByRole("dialog"));
    fireEvent.change(dialog.getByRole("textbox", { name: "Scene name" }), {
      target: { value: "   " },
    });
    expect(dialog.getByRole("button", { name: "Save name" })).toBeDisabled();
    fireEvent.change(dialog.getByRole("textbox", { name: "Scene name" }), {
      target: { value: "  Desk sculpture  " },
    });
    fireEvent.click(dialog.getByRole("button", { name: "Save name" }));
    await screen.findByRole("link", { name: "Open Desk sculpture" });
    expect(data.scenes[0].name).toBe("Desk sculpture");
  });
  it("explains when an active reconstruction prevents deletion", async () => {
    data.runs = [{ id: runId, scene_id: sceneId, status: "queued" }];
    render(<App />);
    expect(
      await screen.findByRole("button", { name: "Delete Vase" }),
    ).toBeDisabled();
    expect(
      screen.getByText("Stop this scene’s active runs before deleting it."),
    ).toBeVisible();
  });
  it("offers a clear search reset and recovery from stale scene links", async () => {
    const view = render(<App />);
    fireEvent.change(
      await screen.findByRole("searchbox", { name: "Search scenes" }),
      { target: { value: "missing" } },
    );
    expect(
      screen.queryByRole("link", { name: "Open Vase" }),
    ).not.toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Clear search" }));
    expect(screen.getByRole("link", { name: "Open Vase" })).toBeVisible();
    view.unmount();
    history.replaceState(null, "", `/#/scenes/${"d".repeat(32)}`);
    render(<App />);
    await screen.findByRole("heading", { name: "This page is unavailable." });
    expect(screen.getByRole("link", { name: "Check Trash" })).toHaveAttribute(
      "href",
      "#/trash",
    );
  });
  it("recovers from a run request failure instead of spinning forever", async () => {
    data.runs = [
      {
        id: runId,
        scene_id: sceneId,
        scene_name: "Vase",
        status: "complete",
        stage: "complete",
        completed: ["train"],
        settings: { steps: 7000, max_size: 1600 },
      },
    ];
    failRun = true;
    history.replaceState(null, "", `/${runLink(sceneId, runId)}`);
    render(<App />);
    const retry = await screen.findByRole("button", { name: "Retry run" });
    failRun = false;
    fireEvent.click(retry);
    await screen.findByRole("heading", { name: "Vase" });
    expect(screen.queryByText("Opening run…")).not.toBeInTheDocument();
  });
  it("can retry the connection when the local app was stopped", async () => {
    failState = true;
    render(<App />);
    const retry = await screen.findByRole("button", {
      name: "Retry connection",
    });
    failState = false;
    fireEvent.click(retry);
    await screen.findByRole("link", { name: "Open Vase" });
  });
});

it("keeps importing while the user returns to the scene library", async () => {
  history.replaceState(null, "", `/#/scenes/${sceneId}`);
  let release!: () => void;
  const gate = new Promise<void>((resolve) => {
    release = resolve;
  });
  let requests = 0;
  vi.stubGlobal(
    "fetch",
    vi.fn(async (_url, options) => {
      requests++;
      if (requests === 1) await gate;
      const files = (options.body as FormData).getAll("files") as File[];
      const imported = files.map((file) => ({
        id: String(
          data.scenes[0].images.length + files.indexOf(file) + 1,
        ).padStart(32, "0"),
        name: file.name,
        width: 80,
        height: 60,
        bytes: 1,
      }));
      data.scenes[0].images.push(...imported);
      return { ok: true, json: async () => ({ imported, errors: [] }) };
    }),
  );
  render(<App />);
  const input = await screen.findByLabelText("Import individual photos");
  fireEvent.change(input, {
    target: {
      files: Array.from(
        { length: 16 },
        (_, i) => new File(["photo"], `photo-${i}.jpg`, { type: "image/jpeg" }),
      ),
    },
  });
  await screen.findByText(/Importing: 0\/16 files/);
  fireEvent.click(screen.getByRole("button", { name: /My scenes/ }));
  await screen.findByRole("heading", {
    name: "My scenes",
  });
  release();
  await screen.findByText(/Import checked: 16\/16 files/);
  expect(requests).toBe(2);
  expect(data.scenes[0].images).toHaveLength(16);
});

it("shows an already running viewer after reopening a run URL", async () => {
  data.runs = [
    {
      id: runId,
      scene_id: sceneId,
      scene_name: "Vase",
      status: "complete",
      stage: "complete",
      completed: ["train"],
      settings: { steps: 7000, max_size: 1600 },
    },
  ];
  data.viewers[runId] = { url: "http://localhost:7010" };
  history.replaceState(null, "", `/${runLink(sceneId, runId)}`);
  render(<App />);
  expect(
    await screen.findByRole("link", { name: "Open interactive scene" }),
  ).toHaveAttribute("href", "http://localhost:7010");
  expect(screen.getByRole("button", { name: "Stop viewer" })).toBeVisible();
});

it("rejects malformed routes and retains valid scene/run identifiers", () => {
  expect(readRoute("#/unknown").page).toBe("missing");
  expect(readRoute("#/scenes/not-a-scene").page).toBe("missing");
  expect(readRoute(runLink(sceneId, runId))).toEqual({
    page: "scenes",
    sceneId,
    runId,
  });
});

it("keeps excluded photos and working settings after navigation and refresh", async () => {
  data.scenes[0].images = [
    { id: "e".repeat(32), name: "photo.jpg", width: 80, height: 60, bytes: 50 },
  ];
  history.replaceState(null, "", `/#/scenes/${sceneId}`);
  const view = render(<App />);
  fireEvent.click(await screen.findByRole("button", { name: "Deselect all" }));
  fireEvent.change(screen.getByLabelText("Training steps"), {
    target: { value: "4321" },
  });
  fireEvent.click(screen.getByRole("button", { name: /My scenes/ }));
  fireEvent.click(await screen.findByRole("link", { name: "Open Vase" }));
  await screen.findByText(/0 selected for the next run/);
  expect(screen.getByLabelText("Training steps")).toHaveValue(4321);
  view.unmount();
  render(<App />);
  await screen.findByText(/0 selected for the next run/);
  expect(screen.getByLabelText("Training steps")).toHaveValue(4321);
});

it("shows an action failure inside the open dialog", async () => {
  render(<App />);
  fireEvent.click(await screen.findByRole("button", { name: "Rename Vase" }));
  mockApi.mockRejectedValueOnce(new Error("The workspace is read-only."));
  fireEvent.click(
    within(screen.getByRole("dialog")).getByRole("button", {
      name: "Save name",
    }),
  );
  expect(
    await within(screen.getByRole("dialog")).findByRole("alert"),
  ).toHaveTextContent("The workspace is read-only.");
  expect(screen.getByRole("dialog")).toBeVisible();
});

function readyCapture() {
  data.diagnostic = { state: "ready", verified: true, checks: [] };
  data.scenes[0].images = Array.from({ length: 12 }, (_, index) => ({
    id: String(index + 1).padStart(32, "0"),
    name: `photo-${index}.jpg`,
    width: 80,
    height: 60,
    bytes: 50,
  }));
  history.replaceState(null, "", `/#/scenes/${sceneId}`);
}

function trashScenes(count = 1) {
  data.trash = Array.from({ length: count }, (_, index) => ({
    id: String(index + 7).padStart(32, "0"),
    name: `Discarded ${index + 1}`,
    images: [],
    created: "2026-01-01",
    deleted_at: "2026-01-02",
  }));
  history.replaceState(null, "", "/#/trash");
}

it("keeps Empty Trash visible but disabled when nothing is deleted", async () => {
  history.replaceState(null, "", "/#/trash");
  render(<App />);
  expect(
    await screen.findByRole("button", { name: "Empty Trash" }),
  ).toBeDisabled();
});

it("can cancel Empty Trash without deleting anything", async () => {
  trashScenes(2);
  render(<App />);
  fireEvent.click(await screen.findByRole("button", { name: "Empty Trash" }));
  const dialog = within(screen.getByRole("dialog"));
  expect(
    dialog.getByRole("button", { name: "Delete permanently" }),
  ).toBeDisabled();
  fireEvent.click(dialog.getByRole("button", { name: "Cancel" }));
  expect(mockApi.mock.calls.some(([path]) => path === "/trash/purge")).toBe(
    false,
  );
  expect(data.trash).toHaveLength(2);
});

it("requires DELETE before emptying the listed scenes", async () => {
  trashScenes(2);
  render(<App />);
  fireEvent.click(await screen.findByRole("button", { name: "Empty Trash" }));
  const dialog = within(screen.getByRole("dialog"));
  fireEvent.change(
    dialog.getByRole("textbox", { name: "Type DELETE to confirm" }),
    { target: { value: "delete" } },
  );
  expect(
    dialog.getByRole("button", { name: "Delete permanently" }),
  ).toBeDisabled();
  fireEvent.change(
    dialog.getByRole("textbox", { name: "Type DELETE to confirm" }),
    { target: { value: "DELETE" } },
  );
  fireEvent.click(dialog.getByRole("button", { name: "Delete permanently" }));
  await screen.findByRole("heading", { name: "Trash is empty." });
  expect(data.scenes).toHaveLength(1);
});

it("does not include scenes newly trashed after the confirmation was opened", async () => {
  trashScenes();
  render(<App />);
  fireEvent.click(await screen.findByRole("button", { name: "Empty Trash" }));
  const original = data.trash[0].id;
  data.trash.push({
    id: "f".repeat(32),
    name: "Arrived later",
    images: [],
    created: "2026-01-01",
    deleted_at: "2026-01-02",
  });
  const dialog = within(screen.getByRole("dialog"));
  fireEvent.change(
    dialog.getByRole("textbox", { name: "Type DELETE to confirm" }),
    { target: { value: "DELETE" } },
  );
  fireEvent.click(dialog.getByRole("button", { name: "Delete permanently" }));
  await screen.findByRole("heading", { name: "Arrived later" });
  expect(
    mockApi.mock.calls.find(([path]) => path === "/trash/purge")?.[1],
  ).toMatchObject({ scene_ids: [original] });
});

it("can permanently delete one trash entry while retaining another", async () => {
  trashScenes(2);
  render(<App />);
  fireEvent.click(
    await screen.findByRole("button", {
      name: "Delete Discarded 1 permanently",
    }),
  );
  const dialog = within(screen.getByRole("dialog"));
  fireEvent.change(
    dialog.getByRole("textbox", { name: "Type DELETE to confirm" }),
    { target: { value: "DELETE" } },
  );
  fireEvent.click(dialog.getByRole("button", { name: "Delete permanently" }));
  await waitFor(() =>
    expect(screen.queryByRole("dialog")).not.toBeInTheDocument(),
  );
  expect(screen.getByRole("heading", { name: "Discarded 2" })).toBeVisible();
});

it("offers retry and blocks restoring a partially deleted scene", async () => {
  trashScenes();
  const normal = mockApi.getMockImplementation()!;
  mockApi.mockImplementation(async (path, body, method) => {
    if (path === "/trash/purge") {
      data.trash[0].purging = true;
      data.trash[0].purge_error = "A file is still open.";
      return {
        deleted_scene_ids: [],
        failed: [
          { scene_id: data.trash[0].id, message: "A file is still open." },
        ],
      };
    }
    return normal(path, body, method);
  });
  render(<App />);
  fireEvent.click(await screen.findByRole("button", { name: "Empty Trash" }));
  let dialog = within(screen.getByRole("dialog"));
  fireEvent.change(
    dialog.getByRole("textbox", { name: "Type DELETE to confirm" }),
    { target: { value: "DELETE" } },
  );
  fireEvent.click(dialog.getByRole("button", { name: "Delete permanently" }));
  await waitFor(() =>
    expect(
      within(screen.getByRole("dialog")).getByRole("alert"),
    ).toHaveTextContent("A file is still open."),
  );
  dialog = within(screen.getByRole("dialog"));
  fireEvent.click(dialog.getByRole("button", { name: "Cancel" }));
  expect(
    screen.getByRole("button", { name: "Restore Discarded 1" }),
  ).toBeDisabled();
  expect(screen.getByText("Retry deletion")).toBeVisible();
});

it("blocks permanent deletion when another unidentified task owns the workspace", async () => {
  trashScenes();
  data.activity = { kind: "external", message: "Another task is active." };
  render(<App />);
  expect(
    await screen.findByRole("button", { name: "Empty Trash" }),
  ).toBeDisabled();
  expect(
    screen.getByRole("button", { name: "Delete Discarded 1 permanently" }),
  ).toBeDisabled();
});

it("allows unrelated trash cleanup while a saved-model viewer is open", async () => {
  trashScenes();
  data.runs = [
    {
      id: runId,
      scene_id: sceneId,
      scene_name: "Vase",
      status: "complete",
      settings: { steps: 7000, max_size: 1600 },
    },
  ];
  data.viewers[runId] = { url: "http://localhost:7010" };
  render(<App />);
  expect(
    await screen.findByRole("button", { name: "Empty Trash" }),
  ).toBeEnabled();
});

it.each(["running", "queued"])(
  "blocks a new reconstruction while another scene is %s",
  async (status) => {
    readyCapture();
    const otherScene = "d".repeat(32);
    data.scenes.push({
      id: otherScene,
      name: "Other scene",
      images: [],
      created: "2026-01-01",
    });
    data.runs = [
      {
        id: runId,
        scene_id: otherScene,
        scene_name: "Other scene",
        status,
        settings: { steps: 7000, max_size: 1600 },
      },
    ];
    render(<App />);
    expect(
      await screen.findByRole("button", { name: "Reconstruction in progress" }),
    ).toBeDisabled();
    expect(
      screen
        .getAllByRole("link", { name: "View active run" })
        .every(
          (link) => link.getAttribute("href") === runLink(otherScene, runId),
        ),
    ).toBe(true);
    fireEvent.click(
      screen.getByRole("button", { name: "Reconstruction in progress" }),
    );
    expect(mockApi.mock.calls.some(([path]) => path.endsWith("/runs"))).toBe(
      false,
    );
  },
);

it("admits only one start request during rapid clicks", async () => {
  readyCapture();
  let release!: () => void;
  const gate = new Promise<void>((resolve) => {
    release = resolve;
  });
  const normal = mockApi.getMockImplementation()!;
  mockApi.mockImplementation(async (path, body, method) => {
    if (path === `/scenes/${sceneId}/runs`) {
      await gate;
      const run = {
        id: runId,
        scene_id: sceneId,
        scene_name: "Vase",
        status: "queued",
        stage: "queued",
        completed: [],
        settings: body,
        created: "2026-01-01",
      };
      data.runs = [run];
      return run;
    }
    return normal(path, body, method);
  });
  render(<App />);
  const start = await screen.findByRole("button", {
    name: "Start reconstruction",
  });
  expect(start).toBeEnabled();
  fireEvent.click(start);
  fireEvent.click(start);
  expect(
    await screen.findByRole("button", { name: "Starting…" }),
  ).toBeDisabled();
  expect(
    mockApi.mock.calls.filter(([path]) => path === `/scenes/${sceneId}/runs`),
  ).toHaveLength(1);
  release();
  await screen.findByRole("heading", { name: "In the queue" });
});

it.each(["setup", "verification", "viewer", "external"])(
  "disables Start while %s owns the workspace",
  async (kind) => {
    readyCapture();
    data.activity = { kind, message: "The workspace is occupied." };
    render(<App />);
    expect(
      await screen.findByRole("button", { name: "Start reconstruction" }),
    ).toBeDisabled();
    expect(
      screen.getAllByText("The workspace is occupied.").length,
    ).toBeGreaterThan(0);
  },
);

it("keeps Resume, tool checks and settings changes disabled during other work", async () => {
  readyCapture();
  data.runs = [
    {
      id: runId,
      scene_id: sceneId,
      scene_name: "Vase",
      status: "failed",
      stage: "train",
      completed: [],
      settings: { steps: 7000, max_size: 1600 },
    },
  ];
  data.activity = { kind: "setup", message: "Setup is still running." };
  history.replaceState(null, "", `/${runLink(sceneId, runId)}`);
  const view = render(<App />);
  expect(
    await screen.findByRole("button", { name: "Resume run" }),
  ).toBeDisabled();
  view.unmount();
  history.replaceState(null, "", "/#/hardware");
  render(<App />);
  expect(
    await screen.findByRole("button", { name: "Recheck tools" }),
  ).toBeDisabled();
  fireEvent.click(screen.getByText("Advanced / maintenance"));
  expect(
    screen.getByRole("button", { name: "Save runtime settings" }),
  ).toBeDisabled();
  expect(
    screen.getByRole("button", { name: "Repair managed tools" }),
  ).toBeDisabled();
});

it("refreshes activity after the server rejects a stale Start request", async () => {
  readyCapture();
  const normal = mockApi.getMockImplementation()!;
  mockApi.mockImplementation(async (path, body, method) => {
    if (path === `/scenes/${sceneId}/runs`) {
      data.runs = [
        {
          id: runId,
          scene_id: sceneId,
          scene_name: "Vase",
          status: "running",
          settings: { steps: 7000, max_size: 1600 },
        },
      ];
      throw new Error("Another reconstruction started in a different tab.");
    }
    return normal(path, body, method);
  });
  render(<App />);
  fireEvent.click(
    await screen.findByRole("button", { name: "Start reconstruction" }),
  );
  expect(
    await screen.findByRole("button", { name: "Reconstruction in progress" }),
  ).toBeDisabled();
  expect(screen.getByRole("alert")).toHaveTextContent(
    "Another reconstruction started in a different tab.",
  );
});

it("keeps missing tools visible in the compact system summary and links to all checks", async () => {
  history.replaceState(null, "", "/#/overview");
  data.diagnostic = {
    state: "setup",
    verified: false,
    checks: [
      {
        id: "gpu",
        name: "NVIDIA graphics",
        state: "ready",
        detail: "NVIDIA Test GPU, 8192 MiB, driver-1, uuid-test",
      },
      {
        id: "colmap",
        name: "Camera reconstruction",
        state: "ready",
        detail: "COLMAP",
      },
      {
        id: "training",
        name: "Python training environment",
        state: "missing",
        detail: "Not installed",
      },
      {
        id: "compiler",
        name: "CUDA compiler",
        state: "missing",
        detail: "Not installed",
      },
    ],
  };
  render(<App />);
  expect(await screen.findByText("Python training environment")).toBeVisible();
  expect(screen.getByText("CUDA compiler")).toBeVisible();
  expect(screen.queryByText("Camera reconstruction")).not.toBeInTheDocument();
  fireEvent.click(screen.getByRole("link", { name: "View all system checks" }));
  expect(await screen.findByText("Camera reconstruction")).toBeVisible();
});
