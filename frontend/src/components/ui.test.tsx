// @vitest-environment jsdom
import React from "react";
import { describe, it, expect } from "vitest";
import { render, screen, fireEvent } from "@testing-library/react";
import "@testing-library/jest-dom/vitest";
import { Button, Modal } from "./ui";

describe("local studio controls", () => {
  it("keeps a disabled action unavailable while prerequisites are missing", () => {
    render(<Button disabled>Start reconstruction</Button>);
    expect(
      screen.getByRole("button", { name: "Start reconstruction" }),
    ).toBeDisabled();
  });
  it("exposes the dialog name and returns a close action", () => {
    let closed = false;
    render(
      <Modal
        open
        onOpenChange={(value) => {
          closed = !value;
        }}
        title="Create a scene"
      >
        <input aria-label="Scene name" />
      </Modal>,
    );
    expect(screen.getByRole("dialog")).toHaveAccessibleName("Create a scene");
    fireEvent.click(screen.getByRole("button", { name: "Close dialog" }));
    expect(closed).toBe(true);
  });
});
