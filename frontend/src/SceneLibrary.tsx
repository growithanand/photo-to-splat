import React, { useState } from "react";
import {
  FolderOpen,
  Image,
  Layers3,
  Pencil,
  Plus,
  Search,
  Trash2,
  Undo2,
} from "lucide-react";
import { type Scene, type Run } from "./api";
import { sceneLink } from "./navigation";
import { Button, cn } from "./components/ui";

export const active = (run: Run) => ["queued", "running"].includes(run.status);
export const statusLabel: Record<string, string> = {
  complete: "Ready to explore",
  queued: "In the queue",
  running: "Reconstructing",
  failed: "Needs attention",
  interrupted: "Stopped · resumable",
  cancelled: "Cancelled",
};

export function SceneLibrary({
  scenes,
  runs,
  create,
  manage,
  blocked,
  showTrash,
}: {
  scenes: Scene[];
  runs: Run[];
  create: () => void;
  manage: (scene: Scene, mode: "rename" | "delete") => void;
  blocked: (scene: Scene) => string;
  showTrash: () => void;
}) {
  const [search, setSearch] = useState("");
  const [sort, setSort] = useState("newest");
  const visible = scenes
    .filter((s) =>
      s.name.toLocaleLowerCase().includes(search.trim().toLocaleLowerCase()),
    )
    .sort((a, b) =>
      sort === "name"
        ? a.name.localeCompare(b.name)
        : b.created.localeCompare(a.created),
    );
  return (
    <section className="library" aria-label="Scene collection">
      <div className="section-heading">
        <div>
          <h2>
            Your scenes <span className="count-chip">{scenes.length}</span>
          </h2>
          <p>Each capture has a home. Every attempt keeps its own history.</p>
        </div>
        <div className="button-row">
          <Button variant="ghost" size="small" onClick={showTrash}>
            <Trash2 size={16} />
            Trash
          </Button>
          <Button variant="outline" size="small" onClick={create}>
            <Plus size={16} />
            New scene
          </Button>
        </div>
      </div>
      {!!scenes.length && (
        <div className="collection-toolbar">
          <label className="search-field">
            <Search size={18} />
            <input
              type="search"
              aria-label="Search scenes"
              placeholder="Search your scenes"
              value={search}
              onChange={(e) => setSearch(e.target.value)}
            />
          </label>
          <label className="sort-field">
            Sort by{" "}
            <select
              aria-label="Sort scenes"
              value={sort}
              onChange={(e) => setSort(e.target.value)}
            >
              <option value="newest">Newest first</option>
              <option value="name">Scene name</option>
            </select>
          </label>
        </div>
      )}
      {!scenes.length ? (
        <div className="empty-library">
          <div className="empty-stack">
            <Image size={28} />
            <Layers3 size={26} />
          </div>
          <div>
            <h3>Your first scene belongs here.</h3>
            <p>
              Create a scene to import photos, or restore an earlier scene from
              Trash.
            </p>
          </div>
          <Button variant="outline" onClick={create}>
            Create a scene
          </Button>
        </div>
      ) : !visible.length ? (
        <div className="subtle-empty" role="status">
          <h3>No scenes match “{search}”.</h3>
          <p>Try another name or clear the search.</p>
          <Button variant="ghost" onClick={() => setSearch("")}>
            Clear search
          </Button>
        </div>
      ) : (
        <div className="scene-grid">
          {visible.map((scene) => {
            const run = runs.find((r) => r.scene_id === scene.id);
            const reason = blocked(scene);
            return (
              <article
                className="scene-card"
                key={scene.id}
                aria-label={scene.name}
              >
                <a
                  className="scene-open"
                  href={sceneLink(scene.id)}
                  aria-label={`Open ${scene.name}`}
                >
                  <div className="scene-cover">
                    {scene.images.length ? (
                      <img
                        src={`/api/scenes/${scene.id}/thumb/${scene.images[0].id}`}
                        alt=""
                        loading="lazy"
                      />
                    ) : (
                      <FolderOpen size={38} />
                    )}
                    <span className="badge badge-glass">
                      {scene.images.length}{" "}
                      {scene.images.length === 1 ? "photo" : "photos"}
                    </span>
                  </div>
                  <div className="scene-card-body">
                    <h3>{scene.name}</h3>
                    <span
                      className={cn(
                        "scene-status",
                        run?.status === "complete" && "green",
                      )}
                    >
                      {run
                        ? statusLabel[run.status]
                        : scene.images.length
                          ? "Ready to configure a run"
                          : "Add photos to get started"}
                    </span>
                  </div>
                </a>
                <div className="scene-actions">
                  <Button
                    variant="ghost"
                    size="small"
                    aria-label={`Rename ${scene.name}`}
                    onClick={() => manage(scene, "rename")}
                  >
                    <Pencil size={15} />
                    Rename
                  </Button>
                  <Button
                    variant="ghost"
                    size="small"
                    className="delete-action"
                    disabled={!!reason}
                    aria-label={`Delete ${scene.name}`}
                    aria-describedby={
                      reason ? `blocked-${scene.id}` : undefined
                    }
                    onClick={() => manage(scene, "delete")}
                  >
                    <Trash2 size={15} />
                    Delete
                  </Button>
                </div>
                {reason && (
                  <p className="scene-action-hint" id={`blocked-${scene.id}`}>
                    {reason}
                  </p>
                )}
              </article>
            );
          })}
        </div>
      )}
    </section>
  );
}

export function TrashView({
  scenes,
  restore,
  pending,
  purge,
  blocked,
}: {
  scenes: Scene[];
  restore: (scene: Scene) => void;
  pending: boolean;
  purge: (scenes: Scene[]) => void;
  blocked: string;
}) {
  return (
    <section className="card trash-panel" aria-label="Deleted scenes">
      <div className="section-heading">
        <div>
          <h2>
            Trash <span className="count-chip">{scenes.length}</span>
          </h2>
          <p>Restore a scene, or permanently remove its workspace files.</p>
        </div>
        <Button
          variant="danger"
          size="small"
          disabled={pending || !scenes.length || !!blocked}
          onClick={() => purge([...scenes])}
        >
          <Trash2 size={16} />
          Empty Trash
        </Button>
      </div>
      {blocked && <p className="inline-error">{blocked}</p>}
      {!scenes.length ? (
        <div className="empty-library">
          <Trash2 size={32} />
          <div>
            <h2>Trash is empty.</h2>
            <p>Deleted scenes appear here so you can restore them.</p>
          </div>
          <a className="button button-outline" href="#/scenes">
            Go to my scenes
          </a>
        </div>
      ) : (
        <>
          <p className="muted">
            Scenes in Trash keep their imported photos, run history, and
            results. They still use disk space.
          </p>
          <div className="trash-list">
            {scenes.map((scene) => (
              <article key={scene.id}>
                <FolderOpen size={24} />
                <div>
                  <h3>{scene.name}</h3>
                  <p>
                    {scene.images.length} photos · Deleted{" "}
                    {new Date(scene.deleted_at!).toLocaleString()}
                  </p>
                  {scene.purging && (
                    <p className="purge-error" role="status">
                      Deletion incomplete.{" "}
                      {scene.purge_error ||
                        "Retry deletion to remove the remaining files."}
                    </p>
                  )}
                </div>
                <div className="trash-actions">
                  <Button
                    variant="outline"
                    disabled={pending || scene.purging}
                    onClick={() => restore(scene)}
                    aria-label={`Restore ${scene.name}`}
                  >
                    <Undo2 size={16} />
                    Restore
                  </Button>
                  <Button
                    variant="ghost"
                    className="delete-action"
                    disabled={pending || !!blocked}
                    aria-label={`Delete ${scene.name} permanently`}
                    onClick={() => purge([scene])}
                  >
                    <Trash2 size={16} />
                    {scene.purging ? "Retry deletion" : "Delete permanently"}
                  </Button>
                </div>
              </article>
            ))}
          </div>
        </>
      )}
    </section>
  );
}
