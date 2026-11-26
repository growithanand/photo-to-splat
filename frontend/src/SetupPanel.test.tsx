// @vitest-environment jsdom
import React from "react";
import { afterEach, beforeEach, expect, it, vi } from "vitest";
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
import { SetupContent } from "./SetupPanel";

vi.mock("./api", async (original) => ({
  ...(await original<typeof import("./api")>()),
  api: vi.fn(),
}));
const mockApi = vi.mocked(api);
let state: any;
const proceed = vi.fn(),
  storage = vi.fn();
beforeEach(() => {
  proceed.mockReset();
  storage.mockReset();
  mockApi.mockReset();
  state = {
    settings: { runtime: { train_prefix: "", sfm_prefix: "" } },
    diagnostic: {
      state: "ready",
      verified: true,
      tools_installed: true,
      checks: [],
      verified_at: "2026-11-26T12:00:00Z",
    },
    setup: { state: "idle" },
    setup_profile: "profile-a",
    setup_reviewed: false,
    runs: [],
    viewers: {},
  };
  mockApi.mockImplementation(async (path, body: any) => {
    if (path === "/setup/review") state.setup_reviewed = body.reviewed;
    if (path === "/setup") state.setup.state = "running";
    if (path === "/setup/log") return { text: "Test setup output" };
    return { started: true };
  });
});
afterEach(cleanup);

function missing() {
  state.diagnostic = {
    state: "setup",
    verified: false,
    tools_installed: false,
    missing_tools: ["colmap"],
    checks: [
      {
        id: "colmap",
        name: "Camera reconstruction",
        state: "missing",
        hint: "Install COLMAP.",
      },
    ],
  };
}
function mount() {
  let view: ReturnType<typeof render>;
  const act = async (task: () => Promise<any>) => {
    try {
      const result = await task();
      view.rerender(content());
      return result;
    } catch {
      return undefined;
    }
  };
  const content = () => (
    <SetupContent
      state={state}
      act={act}
      acting={false}
      proceed={proceed}
      storage={storage}
    />
  );
  view = render(content());
  return view;
}

it("takes verified users to scenes and keeps installation out of the normal flow", () => {
  mount();
  expect(
    screen.getByRole("heading", {
      name: "Your tools are installed and verified.",
    }),
  ).toBeVisible();
  expect(
    screen.queryByRole("button", { name: /Install/ }),
  ).not.toBeInTheDocument();
  expect(screen.queryByRole("checkbox")).not.toBeInTheDocument();
  expect(
    screen.queryByRole("button", { name: "Repair managed tools" }),
  ).not.toBeVisible();
  fireEvent.click(screen.getByRole("button", { name: "Go to my scenes" }));
  expect(proceed).toHaveBeenCalledOnce();
});

it("offers verification when tools are installed without suggesting installation", async () => {
  state.diagnostic = {
    ...state.diagnostic,
    state: "verify",
    verified: false,
    verification_changed: true,
  };
  mount();
  expect(
    screen.queryByRole("button", { name: /Install/ }),
  ).not.toBeInTheDocument();
  fireEvent.click(screen.getByRole("button", { name: "Verify GPU execution" }));
  await waitFor(() =>
    expect(mockApi).toHaveBeenCalledWith("/diagnostics?verify=true", {}),
  );
});

it("waits for detection before presenting installation", () => {
  state.diagnostic = { state: "checking", verified: false, checks: [] };
  mount();
  expect(
    screen.getByRole("heading", { name: "Checking your existing setup…" }),
  ).toBeVisible();
  expect(
    screen.queryByRole("button", { name: /Install/ }),
  ).not.toBeInTheDocument();
  expect(screen.getByRole("button", { name: "Recheck tools" })).toBeDisabled();
});

it("saves requirements review and keeps it checked when the panel is reopened", async () => {
  missing();
  let view = mount();
  expect(
    screen.getByRole("button", { name: "Install missing tools" }),
  ).toBeDisabled();
  fireEvent.click(screen.getByRole("checkbox"));
  await waitFor(() => expect(screen.getByRole("checkbox")).toBeChecked());
  expect(mockApi).toHaveBeenCalledWith("/setup/review", {
    profile: "profile-a",
    reviewed: true,
  });
  view.unmount();
  view = mount();
  expect(screen.getByRole("checkbox")).toBeChecked();
  expect(
    screen.getByRole("button", { name: "Install missing tools" }),
  ).toBeEnabled();
});

it("handles an old install prompt by showing already-installed feedback", async () => {
  missing();
  state.setup_reviewed = true;
  mockApi.mockImplementation(async () => {
    state.diagnostic = {
      state: "verify",
      tools_installed: true,
      verified: false,
      checks: [],
    };
    return {
      state: "already_installed",
      message: "Tools are already installed. No installation was started.",
    };
  });
  mount();
  fireEvent.click(
    screen.getByRole("button", { name: "Install missing tools" }),
  );
  expect(
    await screen.findByText(
      "Tools are already installed. No installation was started.",
    ),
  ).toBeVisible();
  expect(
    screen.queryByRole("button", { name: "Install missing tools" }),
  ).not.toBeInTheDocument();
});

it("requires an explicit maintenance confirmation before repairing", async () => {
  mount();
  fireEvent.click(screen.getByText("Advanced / maintenance"));
  fireEvent.click(screen.getByRole("button", { name: "Repair managed tools" }));
  let dialog = screen.getByRole("dialog");
  expect(
    within(dialog).getByRole("button", { name: "Start managed repair" }),
  ).toBeDisabled();
  fireEvent.click(within(dialog).getByRole("button", { name: "Cancel" }));
  expect(mockApi).not.toHaveBeenCalledWith("/setup", expect.anything());
  fireEvent.click(screen.getByRole("button", { name: "Repair managed tools" }));
  dialog = screen.getByRole("dialog");
  fireEvent.click(within(dialog).getByRole("checkbox"));
  fireEvent.click(
    within(dialog).getByRole("button", { name: "Start managed repair" }),
  );
  await waitFor(() =>
    expect(mockApi).toHaveBeenCalledWith("/setup", {
      profile: "profile-a",
      repair: true,
      reviewed: true,
    }),
  );
});

it("routes storage problems to storage instead of installation", () => {
  state.diagnostic = {
    ...state.diagnostic,
    state: "attention",
    checks: [{ id: "storage", state: "attention" }],
  };
  mount();
  expect(
    screen.getByRole("heading", { name: "Make room for reconstruction." }),
  ).toBeVisible();
  fireEvent.click(screen.getByRole("button", { name: "Choose storage" }));
  expect(storage).toHaveBeenCalledOnce();
  expect(
    screen.queryByRole("button", { name: /Install/ }),
  ).not.toBeInTheDocument();
});

it("shows a failed GPU test with retry and hides installation", () => {
  state.diagnostic = {
    ...state.diagnostic,
    state: "attention",
    verified: false,
    verification_error: "GPU test failed",
  };
  mount();
  expect(
    screen.getByRole("button", { name: "Verify GPU execution" }),
  ).toBeEnabled();
  expect(
    screen.queryByRole("button", { name: /Install/ }),
  ).not.toBeInTheDocument();
  fireEvent.click(screen.getByText("View GPU test error"));
  expect(screen.getByText("GPU test failed")).toBeVisible();
});

it("keeps custom environments and incomplete diagnostics out of managed installation", () => {
  missing();
  state.diagnostic.managed = false;
  const view = mount();
  expect(
    screen.queryByRole("button", { name: /Install/ }),
  ).not.toBeInTheDocument();
  fireEvent.click(screen.getByText("Advanced / maintenance"));
  expect(
    screen.queryByRole("button", { name: "Repair managed tools" }),
  ).not.toBeInTheDocument();
  view.unmount();
  state.diagnostic = {
    state: "attention",
    verified: false,
    checks: [],
    error: "Probe interrupted",
  };
  mount();
  expect(
    screen.queryByRole("button", { name: /Install/ }),
  ).not.toBeInTheDocument();
  expect(screen.getByRole("button", { name: "Recheck tools" })).toBeEnabled();
});
