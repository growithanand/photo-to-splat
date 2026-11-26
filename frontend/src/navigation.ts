import { useEffect, useState } from "react";

export type Page =
  | "overview"
  | "scenes"
  | "hardware"
  | "storage"
  | "help"
  | "trash"
  | "missing";
export type Route = {
  page: Page;
  sceneId: string | null;
  runId: string | null;
};
const pages: Page[] = [
  "overview",
  "scenes",
  "hardware",
  "storage",
  "help",
  "trash",
];
const identifier = /^[a-f0-9]{32}$/;

export function readRoute(hash: string): Route {
  const parts = hash.replace(/^#\/?/, "").split("/").filter(Boolean);
  if (!parts.length) return { page: "overview", sceneId: null, runId: null };
  if (parts.length === 1 && pages.includes(parts[0] as Page))
    return { page: parts[0] as Page, sceneId: null, runId: null };
  if (parts[0] === "scenes" && identifier.test(parts[1] || "")) {
    if (parts.length === 2)
      return { page: "scenes", sceneId: parts[1], runId: null };
    if (parts.length === 4 && parts[2] === "runs" && identifier.test(parts[3]))
      return { page: "scenes", sceneId: parts[1], runId: parts[3] };
  }
  return { page: "missing", sceneId: null, runId: null };
}

export const sceneLink = (id: string) => `#/scenes/${id}`;
export const runLink = (sceneId: string, runId: string) =>
  `${sceneLink(sceneId)}/runs/${runId}`;

export function useRoute() {
  const [route, setRoute] = useState(() => readRoute(window.location.hash));
  useEffect(() => {
    const update = () => setRoute(readRoute(window.location.hash));
    window.addEventListener("hashchange", update);
    return () => window.removeEventListener("hashchange", update);
  }, []);
  return {
    route,
    go: (hash: string) => {
      window.location.hash = hash;
      setRoute(readRoute(hash));
    },
  };
}
