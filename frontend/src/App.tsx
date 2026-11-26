import React, { useEffect, useRef, useState } from "react";
import {
  Aperture,
  Box,
  Check,
  CheckCircle2,
  ChevronRight,
  CircleHelp,
  Cpu,
  Download,
  ExternalLink,
  Film,
  Folder,
  FolderOpen,
  HardDrive,
  Image,
  Layers3,
  Loader2,
  Monitor,
  Pause,
  Play,
  Plus,
  RefreshCw,
  Settings2,
  ShieldCheck,
  Sparkles,
  Terminal,
  Upload,
  X,
  CircleAlert,
  Trash2,
  Pencil,
  Undo2,
} from "lucide-react";
import { api, bytes, type State, type Scene, type Run } from "./api";
import { Button, Modal, cn } from "./components/ui";
import "./style.css";
import "./refinements.css";
import "./workspace.css";
import { useRoute, sceneLink, runLink } from "./navigation";
import { SceneLibrary, TrashView, active, statusLabel } from "./SceneLibrary";
import { readDraft, saveDraft } from "./drafts";
import { getActivity, type Activity } from "./activity";
import { SetupContent } from "./SetupPanel";

export function App() {
  const [state, setState] = useState<State | null>(null);
  const { route, go } = useRoute();
  const { page, sceneId, runId } = route;
  const [newScene, setNewScene] = useState(false);
  const [name, setName] = useState("");
  const [setupOpen, setSetupOpen] = useState(false);
  const [error, setError] = useState("");
  const [notice, setNotice] = useState("");
  const [connectionError, setConnectionError] = useState("");
  const [pending, setPending] = useState(0);
  const [management, setManagement] = useState<{
    scene: Scene;
    mode: "rename" | "delete";
  } | null>(null);
  const [editName, setEditName] = useState("");
  const [undoScene, setUndoScene] = useState<Scene | null>(null);
  const [purgeTarget, setPurgeTarget] = useState<{
    scenes: Scene[];
    workspace: string;
  } | null>(null);
  const [purgeConfirm, setPurgeConfirm] = useState("");
  const [purgeError, setPurgeError] = useState("");
  const purgeGate = useRef(false);
  const [importTask, setImportTask] = useState<any>(null);
  const importing = importTask?.status === "running";
  const main = useRef<HTMLElement>(null);
  const refresh = async () => {
    try {
      setState(await api("/state"));
      setConnectionError("");
    } catch (e) {
      setConnectionError(e instanceof Error ? e.message : String(e));
    }
  };
  useEffect(() => {
    refresh();
    const timer = setInterval(refresh, 2500);
    const visible = () => {
      if (document.visibilityState === "visible") refresh();
    };
    window.addEventListener("focus", refresh);
    document.addEventListener("visibilitychange", visible);
    return () => {
      clearInterval(timer);
      window.removeEventListener("focus", refresh);
      document.removeEventListener("visibilitychange", visible);
    };
  }, []);
  useEffect(() => {
    window.scrollTo({ top: 0, behavior: "instant" });
    main.current?.focus({ preventScroll: true });
  }, [page, sceneId, runId]);
  useEffect(() => {
    if (!importing) return;
    const warn = (event: BeforeUnloadEvent) => {
      event.preventDefault();
      event.returnValue = "";
    };
    window.addEventListener("beforeunload", warn);
    return () => window.removeEventListener("beforeunload", warn);
  }, [importing]);
  const scene = state?.scenes.find((s) => s.id === sceneId);
  const currentRun = state?.runs.find(
    (r) => r.id === runId && r.scene_id === sceneId,
  );
  const missing =
    page === "missing" || (!!sceneId && !scene) || (!!runId && !currentRun);
  const activity = getActivity(state);
  const busy = !!activity || pending > 0;
  const purgeBlocked = importing
    ? "Wait for photo import to finish before emptying Trash."
    : activity && !["reconstruction", "viewer"].includes(activity.kind)
      ? activity.message
      : "";
  const act = async (task: () => Promise<any>, success?: string) => {
    setPending((value) => value + 1);
    try {
      setError("");
      const value = await task();
      if (success) {
        setNotice(success);
        setUndoScene(null);
      }
      await refresh();
      return value;
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
      await refresh();
    } finally {
      setPending((value) => value - 1);
    }
  };
  const navigate = (target: string) => {
    go(`#/${target}`);
  };
  const openScene = (item: Scene) => {
    go(sceneLink(item.id));
  };
  const beginScene = () => {
    setName("");
    setError("");
    setNewScene(true);
  };
  const create = async (event: React.FormEvent) => {
    event.preventDefault();
    if (pending || !name.trim()) return;
    const result = await act(() => api("/scenes", { name: name.trim() }));
    if (result) {
      setNewScene(false);
      setName("");
      openScene(result);
    }
  };
  const blocked = (item: Scene) => {
    if (importing && importTask.sceneId === item.id)
      return "Wait for this scene’s photo import to finish.";
    if (state?.runs.some((r) => r.scene_id === item.id && active(r)))
      return "Stop this scene’s active runs before deleting it.";
    if (
      state?.runs.some((r) => r.scene_id === item.id && state.viewers?.[r.id])
    )
      return "Stop this scene’s 3D viewer before deleting it.";
    return "";
  };
  const manage = (item: Scene, mode: "rename" | "delete") => {
    setError("");
    setEditName(item.name);
    setManagement({ scene: item, mode });
  };
  const restore = async (item: Scene) => {
    const result = await act(
      () => api(`/scenes/${item.id}/restore`, {}),
      `“${item.name}” restored.`,
    );
    if (result) {
      setUndoScene(null);
      openScene(result);
    }
  };
  const beginPurge = (scenes: Scene[]) => {
    if (!state || !scenes.length) return;
    setError("");
    setPurgeError("");
    setPurgeConfirm("");
    setPurgeTarget({
      scenes: [...scenes],
      workspace: state.settings.workspace,
    });
  };
  const confirmPurge = async (event: React.FormEvent) => {
    event.preventDefault();
    if (
      !purgeTarget ||
      purgeGate.current ||
      pending ||
      purgeConfirm.trim() !== "DELETE"
    )
      return;
    purgeGate.current = true;
    setPurgeError("");
    try {
      const result = await act(() =>
        api("/trash/purge", {
          scene_ids: purgeTarget.scenes.map((scene) => scene.id),
          workspace: purgeTarget.workspace,
          confirmation: purgeConfirm.trim(),
        }),
      );
      if (!result) return;
      const deleted = result.deleted_scene_ids as string[];
      setNotice(
        `${deleted.length} ${deleted.length === 1 ? "scene" : "scenes"} permanently deleted.`,
      );
      if (undoScene && deleted.includes(undoScene.id)) setUndoScene(null);
      if (result.failed.length) {
        setPurgeTarget({
          ...purgeTarget,
          scenes: purgeTarget.scenes.filter((scene) =>
            result.failed.some((failure: any) => failure.scene_id === scene.id),
          ),
        });
        setPurgeError(
          result.failed.map((failure: any) => failure.message).join("\n"),
        );
        setPurgeConfirm("");
      } else {
        setPurgeTarget(null);
        setPurgeConfirm("");
      }
    } finally {
      purgeGate.current = false;
    }
  };
  const saveManagement = async (event: React.FormEvent) => {
    event.preventDefault();
    if (!management || pending) return;
    const { scene: item, mode } = management;
    const result = await act(() =>
      api(
        `/scenes/${item.id}`,
        mode === "rename" ? { name: editName.trim() } : {},
        mode === "rename" ? "PATCH" : "DELETE",
      ),
    );
    if (!result) return;
    setManagement(null);
    setNotice(
      mode === "delete" ? `“${item.name}” moved to Trash.` : "Scene renamed.",
    );
    setUndoScene(mode === "delete" ? item : null);
    if (mode === "delete" && importTask?.sceneId === item.id)
      setImportTask(null);
    if (mode === "delete" && sceneId === item.id) navigate("scenes");
  };
  // Imports belong to the application, so changing pages does not abandon a batch.
  const uploadPhotos = async (item: Scene, list: FileList | null) => {
    if (!list?.length || importing) return;
    const selected = Array.from(list);
    const task = {
      sceneId: item.id,
      name: item.name,
      total: selected.length,
      done: 0,
      status: "running",
      errors: [] as string[],
    };
    setImportTask({ ...task });
    try {
      for (let i = 0; i < selected.length; i += 8) {
        const body = new FormData();
        selected
          .slice(i, i + 8)
          .forEach((file) => body.append("files", file, file.name));
        const response = await fetch(`/api/scenes/${item.id}/photos`, {
          method: "POST",
          body,
        });
        const result = await response.json();
        if (!response.ok)
          throw new Error(
            result.detail || "Import failed. Retry the remaining files.",
          );
        task.errors.push(...result.errors);
        task.done = Math.min(i + 8, selected.length);
        setImportTask({ ...task });
        await refresh();
      }
    } catch (error) {
      task.errors.push(
        error instanceof Error
          ? error.message
          : "Import interrupted. Check that the local app is still running.",
      );
    } finally {
      task.status = "finished";
      setImportTask({ ...task });
      await refresh();
    }
  };

  return (
    <div className="app-shell">
      <a
        className="skip-link"
        href="#main-content"
        onClick={(e) => {
          e.preventDefault();
          main.current?.focus();
        }}
      >
        Skip to content
      </a>
      <aside className="sidebar">
        <a
          className="brand"
          href="#/overview"
          onClick={(e) => {
            e.preventDefault();
            navigate("overview");
          }}
        >
          <span className="brand-mark">
            <Aperture size={25} />
          </span>
          <span>
            photo<span className="brand-light">to</span>splat
            <small>LOCAL RECONSTRUCTION STUDIO</small>
          </span>
        </a>
        <div className="sidebar-label">YOUR WORKSPACE</div>
        <nav aria-label="Main navigation">
          {[
            { id: "overview", label: "Overview", icon: Box },
            { id: "scenes", label: "My scenes", icon: Layers3 },
            { id: "hardware", label: "Computer & setup", icon: Cpu },
            { id: "storage", label: "Storage", icon: HardDrive },
            { id: "trash", label: "Trash", icon: Trash2 },
          ].map((item) => (
            <button
              key={item.id}
              className={cn("nav-item", page === item.id && "selected")}
              aria-label={item.label}
              aria-current={page === item.id ? "page" : undefined}
              onClick={() => navigate(item.id)}
            >
              <item.icon size={19} />
              <span className="nav-label-full">{item.label}</span>
              <span className="nav-label-short" aria-hidden="true">
                {item.id === "hardware" ? "Setup" : item.label}
              </span>
              {item.id === "scenes" && (
                <span className="nav-count">{state?.scenes.length || 0}</span>
              )}
            </button>
          ))}
        </nav>
        <div className="sidebar-note">
          <ShieldCheck size={22} />
          <strong>Made on your machine.</strong>
          <p>
            Your photos and reconstructions stay local. You own the results.
          </p>
        </div>
        <button
          className={cn("nav-item help-nav", page === "help" && "selected")}
          onClick={() => navigate("help")}
        >
          <CircleHelp size={19} />
          How it works
        </button>
        <div className="sidebar-footer">
          <span className="local-light" />
          Local workspace <span>v0.1</span>
        </div>
      </aside>
      <div className="main-shell">
        <header className="topbar">
          <nav className="breadcrumb" aria-label="Breadcrumb">
            <ol>
              {[
                { label: "Workspace", href: "#/overview" },
                ...(sceneId
                  ? [
                      { label: "My scenes", href: "#/scenes" },
                      {
                        label: scene?.name || "Scene unavailable",
                        href: runId ? sceneLink(sceneId) : undefined,
                      },
                      ...(runId
                        ? [{ label: "Run details", href: undefined }]
                        : []),
                    ]
                  : [
                      {
                        label: {
                          overview: "Overview",
                          scenes: "My scenes",
                          hardware: "Computer & setup",
                          storage: "Storage",
                          help: "How it works",
                          trash: "Trash",
                          missing: "Page unavailable",
                        }[page],
                        href: undefined,
                      },
                    ]),
              ].map((crumb, index) => (
                <li key={index}>
                  {index > 0 && <ChevronRight size={14} aria-hidden="true" />}
                  {crumb.href ? (
                    <a href={crumb.href}>{crumb.label}</a>
                  ) : (
                    <span aria-current="page">{crumb.label}</span>
                  )}
                </li>
              ))}
            </ol>
          </nav>
          <div className="topbar-right">
            <span className="privacy">
              <ShieldCheck size={15} />
              Private by design
            </span>
            <Button size="small" onClick={beginScene}>
              <Plus size={16} />
              New scene
            </Button>
          </div>
        </header>
        <main id="main-content" ref={main} tabIndex={-1}>
          <ActivityNotice activity={activity} />
          {connectionError && (
            <div role="alert" className="alert alert-error">
              <CircleAlert size={19} />
              <span>{connectionError}</span>
              <Button variant="outline" size="small" onClick={refresh}>
                Retry connection
              </Button>
            </div>
          )}
          {error && (
            <div role="alert" className="alert alert-error">
              <CircleAlert size={19} />
              <span>{error}</span>
              <button aria-label="Dismiss error" onClick={() => setError("")}>
                <X size={17} />
              </button>
            </div>
          )}
          {notice && (
            <div role="status" className="alert alert-success">
              <CheckCircle2 size={19} />
              <span>{notice}</span>
              {undoScene && (
                <Button
                  variant="ghost"
                  size="small"
                  disabled={pending > 0}
                  onClick={() => restore(undoScene)}
                >
                  <Undo2 size={15} />
                  Undo
                </Button>
              )}
              <button
                aria-label="Dismiss notice"
                onClick={() => {
                  setNotice("");
                  setUndoScene(null);
                }}
              >
                <X size={17} />
              </button>
            </div>
          )}
          {importTask && (
            <div role="status" className="alert import-status">
              <Upload size={18} />
              <span>
                <strong>
                  {importing ? "Importing" : "Import checked"}:{" "}
                  {importTask.done}/{importTask.total} files
                </strong>{" "}
                ·{" "}
                <a href={sceneLink(importTask.sceneId)}>
                  {state?.scenes.find((s) => s.id === importTask.sceneId)
                    ?.name || importTask.name}
                </a>
                {importing && (
                  <small>
                    {" "}
                    You can change pages. Keep this browser tab and the app
                    terminal open.
                  </small>
                )}
                {!!importTask.errors.length && (
                  <details>
                    <summary>
                      {importTask.errors.length} files need attention
                    </summary>
                    <ul>
                      {importTask.errors.map(
                        (message: string, index: number) => (
                          <li key={index}>{message}</li>
                        ),
                      )}
                    </ul>
                  </details>
                )}
              </span>
              {!importing && (
                <button
                  aria-label="Dismiss import status"
                  onClick={() => setImportTask(null)}
                >
                  <X size={17} />
                </button>
              )}
            </div>
          )}
          {!state ? (
            <div className="loading-page">
              <Loader2 className="spin" />
              {connectionError
                ? "Waiting for the local application. Start it in your terminal, then retry."
                : "Opening your local workspace…"}
            </div>
          ) : missing ? (
            <section className="card missing-page">
              <FolderOpen size={32} />
              <h1>This page is unavailable.</h1>
              <p>
                The scene may be in Trash, or this link belongs to a different
                workspace.
              </p>
              <div className="button-row">
                <a className="button button-primary" href="#/scenes">
                  Go to my scenes
                </a>
                <a className="button button-outline" href="#/trash">
                  Check Trash
                </a>
                <a className="button button-ghost" href="#/storage">
                  Choose workspace
                </a>
              </div>
            </section>
          ) : runId ? (
            <RunView
              key={runId}
              id={runId}
              state={state}
              act={act}
              acting={pending > 0}
              back={() => go(sceneLink(sceneId!))}
            />
          ) : scene ? (
            <SceneView
              key={scene.id}
              scene={scene}
              state={state}
              act={act}
              importTask={importTask}
              uploadPhotos={uploadPhotos}
              acting={pending > 0}
              manage={manage}
              blocked={blocked(scene)}
              openRun={(id: string) => go(runLink(scene.id, id))}
              setup={() => setSetupOpen(true)}
            />
          ) : page === "overview" ? (
            <>
              <div className="page-heading">
                <div>
                  <div className="eyebrow">A DIFFERENT PERSPECTIVE</div>
                  <h1>Your photos. Another dimension.</h1>
                  <p>
                    Bring an object or a place back to life, one photograph at a
                    time.
                  </p>
                </div>
              </div>
              <div className="welcome-grid">
                <section className="hero-card">
                  <div className="hero-copy">
                    <span className="hero-pill">
                      <Sparkles size={14} />
                      FROM PHOTOS TO PRESENCE
                    </span>
                    <h2>
                      A scene you can <br />
                      step back into.
                    </h2>
                    <p>
                      Choose your overlapping photos. We’ll guide you from a
                      first camera check to a 3D scene you can explore.
                    </p>
                    <Button className="button-light" onClick={beginScene}>
                      <Plus size={17} />
                      {state.scenes.length
                        ? "Create another scene"
                        : "Create your first scene"}
                    </Button>
                    <span className="hero-footnote">
                      No code to write. No photos sent to the cloud.
                    </span>
                  </div>
                  <div className="hero-media">
                    <Demo />
                    <div className="demo-caption">
                      <span>
                        <Film size={14} />
                        Actual Gaussian reconstruction
                      </span>
                      <small>Synthetic example · prerecorded orbit</small>
                    </div>
                  </div>
                </section>
                <Readiness
                  diagnostic={state.diagnostic}
                  busy={busy}
                  open={() => setSetupOpen(true)}
                  verify={() => act(() => api("/diagnostics?verify=true", {}))}
                  proceed={() => navigate("scenes")}
                />
              </div>
              <section className="journey">
                <div className="journey-intro">
                  <span className="eyebrow">
                    A LITTLE GUIDANCE, ALL THE WAY
                  </span>
                  <h3>From a folder to a feeling of being there.</h3>
                </div>
                <div className="journey-step">
                  <div className="step-icon">
                    <FolderOpen />
                  </div>
                  <div>
                    <strong>Bring your photos</strong>
                    <p>One object or scene, from overlapping viewpoints.</p>
                  </div>
                </div>
                <div className="journey-step">
                  <div className="step-icon">
                    <Aperture />
                  </div>
                  <div>
                    <strong>Let the scene take shape</strong>
                    <p>We find cameras, then learn the 3D appearance.</p>
                  </div>
                </div>
                <div className="journey-step">
                  <div className="step-icon">
                    <Box />
                  </div>
                  <div>
                    <strong>Make room to explore</strong>
                    <p>Orbit, compare, export, and return whenever you like.</p>
                  </div>
                </div>
              </section>
              <SceneLibrary
                scenes={state.scenes}
                runs={state.runs}
                manage={manage}
                blocked={blocked}
                showTrash={() => navigate("trash")}
                create={beginScene}
              />
            </>
          ) : page === "scenes" ? (
            <>
              <PageTitle
                eyebrow="YOUR COLLECTION"
                title="A place for every perspective."
                text="Keep different captures separate. Try new settings without overwriting a result."
              />
              <SceneLibrary
                scenes={state.scenes}
                runs={state.runs}
                manage={manage}
                blocked={blocked}
                showTrash={() => navigate("trash")}
                create={beginScene}
              />
            </>
          ) : page === "hardware" ? (
            <>
              <PageTitle
                eyebrow="BEFORE THE HEAVY LIFTING"
                title="Your reconstruction environment."
                text="Check this computer once, then reuse its tools across your scenes."
              />
              <div className="settings-grid">
                <Readiness
                  diagnostic={state.diagnostic}
                  busy={busy}
                  open={() => setSetupOpen(true)}
                  verify={() => act(() => api("/diagnostics?verify=true", {}))}
                  proceed={() => navigate("scenes")}
                  actionless
                />
                <SetupContent
                  state={state}
                  act={act}
                  acting={pending > 0}
                  proceed={() => navigate("scenes")}
                  storage={() => navigate("storage")}
                  runtimeSettings={
                    <RuntimeSettings
                      state={state}
                      act={act}
                      acting={pending > 0}
                    />
                  }
                />
              </div>
            </>
          ) : page === "storage" ? (
            <Storage
              state={state}
              act={act}
              importing={importing}
              acting={pending > 0}
            />
          ) : page === "trash" ? (
            <>
              <PageTitle
                eyebrow="A PLACE TO RECOVER"
                title="Deleted scenes, kept within reach."
                text="Restore a scene with its photos, settings, and saved reconstructions."
              />
              <TrashView
                scenes={state.trash || []}
                restore={restore}
                pending={pending > 0}
                purge={beginPurge}
                blocked={purgeBlocked}
              />
            </>
          ) : (
            <Help />
          )}
          <footer className="page-footer">
            <span>
              <Aperture size={15} /> photo to splat
            </span>
            <span>Photographs in. Perspectives out.</span>
          </footer>
        </main>
      </div>
      <Modal
        open={newScene}
        onOpenChange={(value) => {
          if (!pending) setNewScene(value);
        }}
        title="A new scene starts here"
        description="Give this capture a name. Keep photos of different places or objects in separate scenes."
      >
        <form onSubmit={create}>
          {error && (
            <p role="alert" className="inline-error">
              {error}
            </p>
          )}
          <label className="field-label" htmlFor="scene-name">
            Scene name
          </label>
          <input
            id="scene-name"
            autoFocus
            placeholder="e.g. My ceramic vase"
            value={name}
            onChange={(e) => setName(e.target.value)}
            maxLength={100}
            required
          />
          <div className="modal-actions">
            <Button
              variant="outline"
              type="button"
              onClick={() => setNewScene(false)}
            >
              Cancel
            </Button>
            <Button type="submit" disabled={pending > 0 || !name.trim()}>
              {pending ? (
                <Loader2 className="spin" size={16} />
              ) : (
                <Plus size={16} />
              )}
              {pending ? "Creating…" : "Create scene"}
            </Button>
          </div>
        </form>
      </Modal>
      <Modal
        open={!!management}
        onOpenChange={(value) => {
          if (!value && !pending) setManagement(null);
        }}
        title={
          management?.mode === "delete" ? "Delete this scene?" : "Rename scene"
        }
        description={
          management?.mode === "delete"
            ? "The scene moves to Trash. You can restore it with its imported photos and saved runs."
            : "Choose a name that helps you recognize this capture."
        }
      >
        <form onSubmit={saveManagement}>
          {error && (
            <p role="alert" className="inline-error">
              {error}
            </p>
          )}
          {management?.mode === "rename" ? (
            <label className="field-label">
              Scene name
              <input
                autoFocus
                value={editName}
                onChange={(e) => setEditName(e.target.value)}
                maxLength={100}
                required
              />
            </label>
          ) : (
            <div className="delete-summary">
              <strong>{management?.scene.name}</strong>
              <p>
                {management?.scene.images.length} imported photos ·{" "}
                {state?.runs.filter((r) => r.scene_id === management?.scene.id)
                  .length || 0}{" "}
                saved runs
              </p>
              <p>
                Your source photos stay in their original folder. Trash retains
                local files and still uses disk space.
              </p>
            </div>
          )}
          {management?.mode === "delete" && blocked(management.scene) && (
            <p className="inline-error">{blocked(management.scene)}</p>
          )}
          <div className="modal-actions">
            <Button
              type="button"
              variant="outline"
              disabled={pending > 0}
              onClick={() => setManagement(null)}
            >
              Cancel
            </Button>
            <Button
              type="submit"
              variant={management?.mode === "delete" ? "danger" : "default"}
              disabled={
                pending > 0 ||
                (management?.mode === "rename"
                  ? !editName.trim()
                  : !!management && !!blocked(management.scene))
              }
            >
              {pending
                ? "Saving…"
                : management?.mode === "delete"
                  ? "Move to Trash"
                  : "Save name"}
            </Button>
          </div>
        </form>
      </Modal>
      <Modal
        open={!!purgeTarget}
        onOpenChange={(value) => {
          if (!value && !pending) setPurgeTarget(null);
        }}
        title={`Permanently delete ${purgeTarget?.scenes.length === 1 ? "this scene" : `${purgeTarget?.scenes.length || 0} scenes`}?`}
        description="This cannot be undone. Imported workspace copies, saved reconstructions, checkpoints, and run history will be removed. Source photos outside these managed folders are left alone."
      >
        <form onSubmit={confirmPurge}>
          <ul className="purge-selection">
            {purgeTarget?.scenes.map((scene) => (
              <li key={scene.id}>
                <strong>{scene.name}</strong>
                <span>
                  {scene.images.length} imported photos and any saved runs
                </span>
              </li>
            ))}
          </ul>
          <p className="small muted">
            Only the scenes listed here will be removed. Large folders may take
            a while to delete.
          </p>
          {(purgeError || error) && (
            <p className="inline-error purge-error" role="alert">
              {purgeError || error}
            </p>
          )}
          {purgeBlocked && <p className="inline-error">{purgeBlocked}</p>}
          <label className="field-label">
            Type DELETE to confirm
            <input
              autoFocus
              autoComplete="off"
              spellCheck={false}
              value={purgeConfirm}
              disabled={pending > 0}
              onChange={(event) => setPurgeConfirm(event.target.value)}
            />
          </label>
          <div className="modal-actions">
            <Button
              type="button"
              variant="outline"
              disabled={pending > 0}
              onClick={() => setPurgeTarget(null)}
            >
              Cancel
            </Button>
            <Button
              type="submit"
              variant="danger"
              disabled={
                pending > 0 ||
                purgeConfirm.trim() !== "DELETE" ||
                !!purgeBlocked
              }
            >
              {pending ? (
                <>
                  <Loader2 className="spin" size={16} />
                  Deleting…
                </>
              ) : (
                "Delete permanently"
              )}
            </Button>
          </div>
        </form>
      </Modal>
      <Modal
        open={setupOpen}
        onOpenChange={setSetupOpen}
        title="Computer & setup"
        description="Review detected tools, GPU verification, and optional maintenance. Use the same environment across your scenes."
        wide
      >
        {state && (
          <SetupContent
            state={state}
            act={act}
            acting={pending > 0}
            proceed={() => {
              setSetupOpen(false);
              navigate("scenes");
            }}
            storage={() => {
              setSetupOpen(false);
              navigate("storage");
            }}
          />
        )}
        <Button
          variant="outline"
          onClick={() => {
            setSetupOpen(false);
            navigate("hardware");
          }}
        >
          <Settings2 size={17} />
          Open computer settings
        </Button>
      </Modal>
    </div>
  );
}

function ActivityNotice({
  activity,
  compact = false,
}: {
  activity: Activity | null;
  compact?: boolean;
}) {
  if (!activity) return null;
  return (
    <div
      className={compact ? "activity-notice compact" : "activity-notice"}
      role="status"
    >
      <Loader2 size={18} className={activity.kind === "viewer" ? "" : "spin"} />
      <span>
        {activity.message}{" "}
        {activity.kind === "reconstruction" &&
          "Only one reconstruction can be active at a time."}
      </span>
      {activity.run_id && activity.scene_id ? (
        <a href={runLink(activity.scene_id, activity.run_id)}>
          {activity.kind === "viewer"
            ? "Open viewer controls"
            : "View active run"}
        </a>
      ) : (
        <a href="#/hardware">View setup</a>
      )}
    </div>
  );
}

function Demo() {
  const [paused, setPaused] = useState(
    window.matchMedia("(prefers-reduced-motion: reduce)").matches,
  );
  const video = useRef<HTMLVideoElement>(null);
  return (
    <>
      <video
        ref={video}
        autoPlay={!paused}
        muted
        loop
        playsInline
        poster="/demo-poster.jpg"
        aria-label="Prerecorded orbit of a trained synthetic golden owl Gaussian reconstruction"
      >
        <source src="/demo.mp4" type="video/mp4" />
      </video>
      <button
        className="demo-play"
        aria-label={paused ? "Play demonstration" : "Pause demonstration"}
        onClick={() => {
          if (paused) video.current?.play();
          else video.current?.pause();
          setPaused(!paused);
        }}
      >
        {paused ? <Play size={15} /> : <Pause size={15} />}
      </button>
    </>
  );
}

function PageTitle({
  eyebrow,
  title,
  text,
}: {
  eyebrow: string;
  title: string;
  text: string;
}) {
  return (
    <div className="page-heading">
      <div className="eyebrow">{eyebrow}</div>
      <h1>{title}</h1>
      <p>{text}</p>
    </div>
  );
}

function Readiness({
  diagnostic: d,
  busy,
  open,
  verify,
  proceed,
  actionless,
}: any) {
  const checking = ["checking", "verifying"].includes(d.state);
  const title =
    d.state === "ready"
      ? "Your computer is ready."
      : checking
        ? "Getting to know your computer."
        : d.state === "verify"
          ? "One last check."
          : d.state === "attention" && d.tools_installed
            ? "Your setup needs attention."
            : d.state === "unsupported"
              ? "Training needs a supported GPU route."
              : "Let’s get you set up.";
  return (
    <section className="readiness card">
      <div className="card-topline">
        <span className="icon-box">
          <Cpu size={21} />
        </span>
        <span
          className={cn("badge", d.verified ? "badge-green" : "badge-neutral")}
        >
          {checking ? "Checking" : d.verified ? "Verified" : "Readiness check"}
        </span>
      </div>
      <h3>{title}</h3>
      <p className="muted">
        {d.verified
          ? `A Gaussian render and gradient check passed${d.verified_at ? ` on ${new Date(d.verified_at).toLocaleDateString()}` : ""}.`
          : "We check your tools before asking your GPU to work."}
      </p>
      <div className="check-list">
        {(d.checks.length
          ? d.checks
          : [
              { id: "gpu", name: "NVIDIA graphics" },
              { id: "platform", name: "Execution platform" },
              { id: "storage", name: "Available storage" },
            ]
        ).map((check: any) => (
          <div className="check-row" key={check.id}>
            <span>
              {check.state === "ready" ? (
                <CheckCircle2 className="green" size={17} />
              ) : checking ? (
                <Loader2 className="spin muted" size={17} />
              ) : (
                <CircleAlert className="amber" size={17} />
              )}
            </span>
            <div>
              <strong>{check.name}</strong>
              {check.detail && (
                <small title={check.detail}>
                  {check.state === "ready"
                    ? check.detail
                    : check.id === "storage"
                      ? check.detail
                      : "Needs attention"}
                </small>
              )}
            </div>
          </div>
        ))}
      </div>
      {d.error && (
        <p className="inline-error">
          The execution check needs attention. Open setup for the details.
        </p>
      )}
      {!actionless && (
        <Button
          variant={d.verified ? "outline" : "default"}
          disabled={checking || busy}
          onClick={
            d.state === "verify"
              ? verify
              : d.state === "ready" && proceed
                ? proceed
                : open
          }
        >
          {checking ? (
            <Loader2 size={16} className="spin" />
          ) : d.state === "verify" ? (
            <Play size={16} />
          ) : (
            <Settings2 size={16} />
          )}
          {checking
            ? d.state === "verifying"
              ? "Testing GPU rendering…"
              : "Checking your setup…"
            : d.state === "verify"
              ? "Verify GPU execution"
              : d.state === "ready" && proceed
                ? "Go to my scenes"
                : d.verified
                  ? "View setup details"
                  : "Review setup"}
        </Button>
      )}
      <small className="privacy-note">
        <ShieldCheck size={12} />
        Checks run locally on your computer.
      </small>
    </section>
  );
}

function SceneView({
  scene,
  state,
  act,
  importTask,
  uploadPhotos,
  acting,
  manage,
  blocked,
  openRun,
  setup,
}: any) {
  const [draft] = useState(() => readDraft(state.settings.workspace, scene));
  const activity = getActivity(state);
  const starting = useRef(false);
  const [startPending, setStartPending] = useState(false);
  const [selected, setSelected] = useState<Set<string>>(
    new Set(draft.selected),
  );
  const known = useRef(new Set<string>(draft.known));
  const importingAnywhere = importTask?.status === "running";
  const uploading = importingAnywhere && importTask.sceneId === scene.id;
  const [preset, setPreset] = useState(draft.preset);
  const [steps, setSteps] = useState(draft.steps);
  const [maxSize, setMaxSize] = useState(draft.maxSize);
  const [matching, setMatching] = useState(draft.matching);
  const [cameraMode, setCameraMode] = useState(draft.cameraMode);
  const [space, setSpace] = useState<any>(null);
  const folder = useRef<HTMLInputElement>(null);
  const files = useRef<HTMLInputElement>(null);
  useEffect(() => {
    const added = scene.images.filter(
      (image: any) => !known.current.has(image.id),
    );
    if (added.length)
      setSelected(
        (previous) =>
          new Set([...previous, ...added.map((image: any) => image.id)]),
      );
    known.current = new Set(scene.images.map((image: any) => image.id));
  }, [scene.images]);
  const upload = (event: React.ChangeEvent<HTMLInputElement>) => {
    uploadPhotos(scene, event.target.files);
    event.target.value = "";
  };
  const options = {
    preset,
    steps,
    max_size: maxSize,
    matching,
    camera_mode: cameraMode,
    image_ids: [...selected],
  };
  useEffect(() => {
    saveDraft(state.settings.workspace, scene.id, {
      selected: [...selected],
      known: [...known.current],
      preset,
      steps,
      maxSize,
      matching,
      cameraMode,
    });
  }, [
    selected,
    preset,
    steps,
    maxSize,
    matching,
    cameraMode,
    scene.id,
    state.settings.workspace,
  ]);
  useEffect(() => {
    api(`/scenes/${scene.id}/estimate`, {
      max_size: maxSize,
      image_ids: [...selected],
    })
      .then(setSpace)
      .catch(() => setSpace(null));
  }, [scene.id, scene.images.length, maxSize, selected]);
  const runs = state.runs.filter((r: Run) => r.scene_id === scene.id);
  const start = async () => {
    if (acting || starting.current || activity) return;
    starting.current = true;
    setStartPending(true);
    try {
      const run = await act(() => api(`/scenes/${scene.id}/runs`, options));
      if (run) openRun(run.id);
    } finally {
      starting.current = false;
      setStartPending(false);
    }
  };
  return (
    <>
      <div className="scene-heading-actions">
        <a className="button button-ghost" href="#/scenes">
          Back to my scenes
        </a>
        <div className="button-row">
          <Button
            variant="outline"
            size="small"
            onClick={() => manage(scene, "rename")}
          >
            <Pencil size={15} />
            Rename scene
          </Button>
          <Button
            variant="outline"
            size="small"
            className="delete-action"
            disabled={!!blocked}
            title={blocked || "Move this scene to Trash"}
            onClick={() => manage(scene, "delete")}
          >
            <Trash2 size={15} />
            Delete scene
          </Button>
        </div>
      </div>
      <PageTitle
        eyebrow="SCENE WORKSPACE"
        title={scene.name}
        text="One capture, many possibilities. New runs preserve all your previous results."
      />
      <section className="import-card card">
        <span className="icon-box">
          <FolderOpen size={24} />
        </span>
        <div>
          <h3>Bring your photos together.</h3>
          <p>
            Select a folder, or choose individual photos of this same scene. We
            import local copies and leave your originals alone.
          </p>
        </div>
        <div className="import-buttons">
          <Button
            onClick={() => folder.current?.click()}
            disabled={importingAnywhere}
          >
            <Folder size={17} />
            {uploading ? "Importing…" : "Select photo folder"}
          </Button>
          <Button
            variant="outline"
            onClick={() => files.current?.click()}
            disabled={importingAnywhere}
          >
            <Upload size={16} />
            Select photos
          </Button>
        </div>
        <input
          className="sr-only"
          ref={folder}
          type="file"
          multiple
          {...({ webkitdirectory: "" } as any)}
          aria-label="Import photo folder"
          onChange={upload}
        />
        <input
          className="sr-only"
          ref={files}
          type="file"
          multiple
          accept="image/jpeg,image/png,image/tiff,image/webp"
          aria-label="Import individual photos"
          onChange={upload}
        />
      </section>
      <div className="scene-layout">
        <section>
          <div className="section-heading">
            <div>
              <h2>
                Photo collection{" "}
                <span className="count-chip">{scene.images.length}</span>
              </h2>
              <p>
                {selected.size} selected for the next run. Uncheck photos to
                exclude them.
              </p>
            </div>
            <div className="button-row">
              <Button
                variant="ghost"
                size="small"
                disabled={!selected.size}
                onClick={() => setSelected(new Set())}
              >
                Deselect all
              </Button>
              <Button
                variant="ghost"
                size="small"
                onClick={() =>
                  setSelected(new Set(scene.images.map((i: any) => i.id)))
                }
              >
                Select all
              </Button>
            </div>
          </div>
          {scene.images.length ? (
            <div className="photo-grid">
              {scene.images.map((photo: any) => (
                <label
                  className={cn(
                    "photo-tile",
                    selected.has(photo.id) && "photo-selected",
                  )}
                  key={photo.id}
                >
                  <img
                    loading="lazy"
                    src={`/api/scenes/${scene.id}/thumb/${photo.id}`}
                    alt={photo.name}
                  />
                  <input
                    type="checkbox"
                    checked={selected.has(photo.id)}
                    onChange={(e) =>
                      setSelected((previous) => {
                        const next = new Set(previous);
                        if (e.target.checked) next.add(photo.id);
                        else next.delete(photo.id);
                        return next;
                      })
                    }
                  />
                  <span>{photo.name}</span>
                </label>
              ))}
            </div>
          ) : (
            <div className="empty-photos">
              <Image size={34} />
              <h3>Choose a capture to begin.</h3>
              <p>
                Around 80–200 sharp, overlapping photos make a useful first
                experiment.
              </p>
            </div>
          )}
        </section>
        <aside className="run-config card">
          <div className="eyebrow">MAKE A NEW RECONSTRUCTION</div>
          <h3>Find your first perspective.</h3>
          <p className="muted">
            Start small. You can always make a longer run later.
          </p>
          <div className="preset-grid">
            {[
              {
                id: "quick",
                title: "Quick preview",
                text: "7,000 steps · a first look",
                steps: 7000,
              },
              {
                id: "balanced",
                title: "Detailed run",
                text: "30,000 steps · more refinement",
                steps: 30000,
              },
            ].map((p) => (
              <button
                key={p.id}
                className={cn("preset", preset === p.id && "preset-selected")}
                onClick={() => {
                  setPreset(p.id);
                  setSteps(p.steps);
                }}
              >
                <span>
                  <strong>{p.title}</strong>
                  <small>{p.text}</small>
                </span>
                {preset === p.id && <CheckCircle2 size={17} />}
              </button>
            ))}
          </div>
          <details>
            <summary>
              <Settings2 size={15} />
              Advanced settings
            </summary>
            <label className="field-label">
              Training steps
              <input
                type="number"
                min={100}
                max={100000}
                value={steps}
                onChange={(e) => setSteps(+e.target.value)}
              />
            </label>
            <label className="field-label">
              Maximum working image edge
              <select
                value={maxSize}
                onChange={(e) => setMaxSize(+e.target.value)}
              >
                <option value={800}>800 px · lighter</option>
                <option value={1600}>1600 px · standard</option>
                <option value={2400}>2400 px · more memory</option>
              </select>
            </label>
            <label className="field-label">
              Photo matching
              <select
                value={matching}
                onChange={(e) => setMatching(e.target.value)}
              >
                <option value="exhaustive">
                  All pairs · small collections
                </option>
                <option value="sequential">
                  Capture order · larger collections
                </option>
              </select>
            </label>
            <label className="field-label">
              Camera calibration
              <select
                value={cameraMode}
                onChange={(e) => setCameraMode(e.target.value)}
              >
                <option value="auto">Automatic grouping</option>
                <option value="shared">One lens, consistent dimensions</option>
                <option value="per-image">Separate camera per image</option>
              </select>
            </label>
            <p className="small muted">
              Sequential matching needs capture-ordered filenames. Mixed cameras
              can need manual calibration.
            </p>
          </details>
          <div className="config-note">
            <HardDrive size={16} />
            <span>
              {space ? (
                <>
                  <strong>
                    {bytes(space.working_low_bytes)}–
                    {bytes(space.working_high_bytes)}
                  </strong>{" "}
                  working-space estimate.
                  <br />
                  {bytes(space.free_bytes)} available on this volume.
                  Tools/caches need separate space.
                </>
              ) : (
                "Planning range depends on selected images and working resolution."
              )}
              <br />
              Large scenes can exceed this estimate.
            </span>
          </div>
          {!state.diagnostic.verified && (
            <p className="inline-error">
              Verify your GPU in Computer & setup before starting.
            </p>
          )}
          <Button
            disabled={
              acting ||
              startPending ||
              !!activity ||
              uploading ||
              selected.size < 12 ||
              !state.diagnostic.verified ||
              state.setup.state === "running" ||
              Object.keys(state.viewers || {}).length > 0
            }
            onClick={start}
          >
            <Play size={16} />
            {startPending
              ? "Starting…"
              : activity?.kind === "reconstruction"
                ? "Reconstruction in progress"
                : "Start reconstruction"}
          </Button>
          {!state.diagnostic.verified && (
            <Button variant="ghost" onClick={setup}>
              Check my setup
            </Button>
          )}
          <small className="muted">
            At least 12 photos required. Existing runs are never overwritten.
          </small>
          <ActivityNotice activity={activity} compact />
          {!!Object.keys(state.viewers || {}).length && (
            <p className="inline-error">
              Stop the open 3D viewer from its run page before starting
              training.
            </p>
          )}
          {state.setup.state === "running" && (
            <p className="inline-error">
              Wait for reconstruction-tool installation to finish.
            </p>
          )}
        </aside>
      </div>
      <section className="library">
        <div className="section-heading">
          <div>
            <h2>Run history</h2>
            <p>Each attempt keeps its own inputs, settings, and checkpoints.</p>
          </div>
        </div>
        {runs.length ? (
          <div className="run-list">
            {runs.map((run: Run) => (
              <button key={run.id} onClick={() => openRun(run.id)}>
                <span className="icon-box">
                  {run.status === "complete" ? (
                    <Box size={20} />
                  ) : active(run) ? (
                    <Loader2 size={20} className="spin" />
                  ) : (
                    <CircleAlert size={20} />
                  )}
                </span>
                <div>
                  <strong>
                    {run.settings.steps.toLocaleString()} steps ·{" "}
                    {run.settings.max_size}px
                  </strong>
                  <small>{new Date(run.created).toLocaleString()}</small>
                </div>
                <span
                  className={cn(
                    "badge",
                    run.status === "complete" ? "badge-green" : "badge-neutral",
                  )}
                >
                  {statusLabel[run.status]}
                </span>
                <ChevronRight size={18} />
              </button>
            ))}
          </div>
        ) : (
          <div className="subtle-empty">
            Your reconstruction history will appear here.
          </div>
        )}
      </section>
    </>
  );
}

function RunView({ id, state, act, back, acting }: any) {
  const [run, setRun] = useState<any>(null);
  const [log, setLog] = useState("");
  const [showLog, setShowLog] = useState(false);
  const viewer = state.viewers?.[id]?.url || "";
  const activity = getActivity(state);
  const actionGate = useRef(false);
  const [actionPending, setActionPending] = useState(false);
  const runAction = async (path: string) => {
    if (actionGate.current) return;
    actionGate.current = true;
    setActionPending(true);
    try {
      return await act(() => api(path, {}));
    } finally {
      actionGate.current = false;
      setActionPending(false);
    }
  };
  const [render, setRender] = useState(0);
  const [loadError, setLoadError] = useState("");
  const [attempt, setAttempt] = useState(0);
  const [logStage, setLogStage] = useState("");
  useEffect(() => {
    let mounted = true;
    const load = async () => {
      try {
        const result = await api(`/runs/${id}`);
        if (mounted) {
          setRun(result);
          setLoadError("");
        }
      } catch (error) {
        if (mounted)
          setLoadError(
            error instanceof Error ? error.message : "Cannot load this run.",
          );
      }
    };
    load();
    const timer = setInterval(load, 2500);
    return () => {
      mounted = false;
      clearInterval(timer);
    };
  }, [id, attempt]);
  useEffect(() => {
    if (!showLog || !run) return;
    let mounted = true;
    const load = async () => {
      try {
        const stage =
          logStage ||
          (run.stage === "complete"
            ? "train"
            : run.stage === "queued"
              ? "verify"
              : run.stage);
        const result = await api(`/runs/${id}/log?stage=${stage}`);
        if (mounted) setLog(result.text);
      } catch (error) {
        if (mounted)
          setLog(
            error instanceof Error ? error.message : "The log is unavailable.",
          );
      }
    };
    load();
    const timer = setInterval(load, 2500);
    return () => {
      mounted = false;
      clearInterval(timer);
    };
  }, [showLog, run?.stage, id, logStage]);
  if (!run)
    return (
      <div className="loading-page" role={loadError ? "alert" : "status"}>
        {loadError ? (
          <>
            <CircleAlert />
            <p>{loadError}</p>
            <Button
              variant="outline"
              onClick={() => setAttempt((value) => value + 1)}
            >
              Retry run
            </Button>
            <Button variant="ghost" onClick={back}>
              Back to scene
            </Button>
          </>
        ) : (
          <>
            <Loader2 className="spin" />
            Opening run…
          </>
        )}
      </div>
    );
  const openViewer = async () => {
    await runAction(`/runs/${id}/viewer`);
  };
  return (
    <>
      <Button variant="ghost" onClick={back}>
        Back to scene
      </Button>
      {loadError && (
        <p role="alert" className="inline-error">
          Updates paused: {loadError}
        </p>
      )}
      <PageTitle
        eyebrow="RECONSTRUCTION RUN"
        title={run.scene_name}
        text={`${run.images.length} selected photos · ${run.settings.steps.toLocaleString()} training steps · ${run.settings.max_size}px working edge`}
      />
      <div className="run-layout">
        <section className="card pipeline-card">
          <div className="section-heading">
            <h2>{statusLabel[run.status]}</h2>
            <span
              className={cn(
                "badge",
                run.status === "complete" ? "badge-green" : "badge-neutral",
              )}
            >
              {run.status}
            </span>
          </div>
          <p className="muted">
            {run.status === "running"
              ? "You can leave this browser tab. Keep the application terminal running."
              : run.status === "queued"
                ? "Waiting for the worker to pick up this reconstruction. Keep the app terminal running."
                : run.status === "complete"
                  ? "Your scene is saved. Compare a held-out view or explore it interactively."
                  : "Completed stages and the latest checkpoint are preserved."}
          </p>
          <div className="pipeline-stages">
            {state.stages.map((stage: any) => {
              const done = run.completed.includes(stage.id);
              const current = run.stage === stage.id;
              return (
                <div
                  key={stage.id}
                  className={cn(
                    "pipeline-stage",
                    done && "done",
                    current && "current",
                  )}
                >
                  <span>
                    {done ? (
                      <Check size={16} />
                    ) : current && run.status === "running" ? (
                      <Loader2 size={16} className="spin" />
                    ) : (
                      <span className="stage-dot" />
                    )}
                  </span>
                  <div>
                    <strong>{stage.label}</strong>
                    {current && run.status === "running" && (
                      <small>
                        In progress · real tool output is available below
                      </small>
                    )}
                  </div>
                </div>
              );
            })}
          </div>
          {run.error && (
            <div role="alert" className="error-detail">
              {run.error}
            </div>
          )}
          <div className="button-row">
            {active(run) && (
              <Button
                variant="outline"
                disabled={acting || actionPending || run.cancel_requested}
                onClick={() => runAction(`/runs/${id}/stop`)}
              >
                <Pause size={16} />
                {run.cancel_requested ? "Stopping…" : "Stop safely"}
              </Button>
            )}
            {["failed", "interrupted", "cancelled"].includes(run.status) && (
              <Button
                disabled={acting || actionPending || !!activity}
                onClick={() => runAction(`/runs/${id}/resume`)}
              >
                <RefreshCw size={16} />
                Resume run
              </Button>
            )}
            <Button variant="ghost" onClick={() => setShowLog(!showLog)}>
              <Terminal size={16} />
              {showLog ? "Hide" : "Show"} stage log
            </Button>
          </div>
          {showLog && (
            <div>
              <label className="field-label">
                Stage log
                <select
                  value={
                    logStage ||
                    (run.stage === "complete"
                      ? "train"
                      : run.stage === "queued"
                        ? "verify"
                        : run.stage)
                  }
                  onChange={(event) => setLogStage(event.target.value)}
                >
                  {state.stages.map((stage: any) => (
                    <option key={stage.id} value={stage.id}>
                      {stage.label}
                    </option>
                  ))}
                </select>
              </label>
              <pre className="log">{log || "No stage output yet."}</pre>
            </div>
          )}
        </section>
        <aside className="card results-card">
          <div className="eyebrow">YOUR SAVED RESULT</div>
          <h3>A new way to see it.</h3>
          {run.completed.includes("train") ? (
            <>
              <p>
                Open the GPU viewer after queued work finishes. It starts at a
                clear 1600px preview.
              </p>
              <Button
                onClick={openViewer}
                disabled={acting || actionPending || !!activity || !!viewer}
              >
                <Box size={17} />
                Start 3D viewer
              </Button>
              {viewer && (
                <div className="viewer-link">
                  <p>Allow a few seconds for the model to load.</p>
                  <a href={viewer} target="_blank" rel="noreferrer">
                    Open interactive scene <ExternalLink size={14} />
                  </a>
                  <Button
                    size="small"
                    variant="ghost"
                    disabled={acting || actionPending}
                    onClick={() => {
                      runAction("/viewers/stop");
                    }}
                  >
                    {actionPending ? "Stopping…" : "Stop viewer"}
                  </Button>
                </div>
              )}
            </>
          ) : (
            <div className="result-placeholder">
              <Box size={40} />
              <p>Your interactive scene will be available after training.</p>
            </div>
          )}
          {run.export_ready && (
            <Button variant="outline" asChild>
              <a href={`/api/runs/${id}/download/splat`}>
                <Download size={16} />
                Download Gaussian PLY
              </a>
            </Button>
          )}
          <p className="small muted">
            A Gaussian PLY is a splat representation. Mesh extraction and
            physical measurements are outside this version.
          </p>
          <a className="text-link" href={`/api/runs/${id}/download/manifest`}>
            Download run manifest
          </a>
        </aside>
      </div>
      {run.camera_report && (
        <div className="metric-row">
          <Metric
            value={`${run.camera_report.registered}/${run.camera_report.source_count}`}
            label="Photos registered"
          />
          <Metric
            value={run.camera_report.points.toLocaleString()}
            label="Sparse 3D points"
          />
          <Metric
            value={`${run.camera_report.mean_reprojection_error.toFixed(2)} px`}
            label="Mean reprojection error"
          />
          {run.metrics && (
            <Metric
              value={`${run.metrics.results.psnr.toFixed(2)} dB`}
              label="Held-out PSNR · whole image"
            />
          )}
        </div>
      )}
      {run.renders?.length > 0 && (
        <section className="library">
          <div className="section-heading">
            <div>
              <h2>How close did we get?</h2>
              <p>
                Left: held-out reference. Right: reconstruction. These photos
                were excluded from photometric training.
              </p>
            </div>
            <select
              aria-label="Comparison viewpoint"
              value={render}
              onChange={(e) => setRender(+e.target.value)}
            >
              {run.renders.map((_: any, i: number) => (
                <option key={i} value={i}>
                  View {i + 1}
                </option>
              ))}
            </select>
          </div>
          <img
            className="comparison"
            src={`/api/runs/${id}/render/${run.renders[render]}`}
            alt="Held-out photograph on the left and Gaussian reconstruction on the right"
          />
          <p className="small muted">
            Camera estimation uses the full capture. These comparisons measure
            appearance near captured viewpoints, not dimensional accuracy or
            unseen geometry.
          </p>
        </section>
      )}
    </>
  );
}
function Metric({ value, label }: any) {
  return (
    <div className="metric card">
      <strong>{value}</strong>
      <span>{label}</span>
    </div>
  );
}

function RuntimeSettings({ state, act, acting }: any) {
  const activity = getActivity(state);
  const [options, setOptions] = useState(state.settings.runtime);
  return (
    <section className="card settings-card">
      <span className="icon-box">
        <Settings2 size={21} />
      </span>
      <h3>Use your own environments</h3>
      <p className="muted">
        Optional. Leave paths blank for the managed setup. These are Linux
        environment prefixes, not Python executable paths.
      </p>
      <form
        onSubmit={(e) => {
          e.preventDefault();
          act(() => api("/runtime", options, "PUT"));
        }}
      >
        <label className="field-label">
          Execution route
          <select
            value={options.mode}
            onChange={(e) => setOptions({ ...options, mode: e.target.value })}
          >
            <option value="auto">Automatic</option>
            <option value="wsl">Windows + WSL2</option>
            <option value="native">Native Linux</option>
          </select>
        </label>
        <label className="field-label">
          WSL distribution
          <input
            value={options.distro}
            onChange={(e) => setOptions({ ...options, distro: e.target.value })}
          />
        </label>
        <label className="field-label">
          Training environment
          <input
            placeholder="Default managed environment"
            value={options.train_prefix}
            onChange={(e) =>
              setOptions({ ...options, train_prefix: e.target.value })
            }
          />
        </label>
        <label className="field-label">
          COLMAP environment
          <input
            placeholder="Default managed environment"
            value={options.sfm_prefix}
            onChange={(e) =>
              setOptions({ ...options, sfm_prefix: e.target.value })
            }
          />
        </label>
        <Button variant="outline" type="submit" disabled={acting || !!activity}>
          Save runtime settings
        </Button>
      </form>
    </section>
  );
}

function Storage({ state, act, importing, acting }: any) {
  const [path, setPath] = useState(state.settings.workspace);
  const [picking, setPicking] = useState(false);
  useEffect(
    () => setPath(state.settings.workspace),
    [state.settings.workspace],
  );
  return (
    <>
      <PageTitle
        eyebrow="ROOM FOR YOUR PERSPECTIVES"
        title="A workspace that stays yours."
        text="Choose a local folder with room for imported photos, working copies, checkpoints, and exports."
      />
      <section className="card storage-card">
        <HardDrive size={35} />
        <h2>
          {state.diagnostic.free_bytes == null
            ? "Checking available space…"
            : `${bytes(state.diagnostic.free_bytes)} available`}
        </h2>
        <p>
          Free space on the selected workspace volume. Linux tool environments
          may live on a different volume.
        </p>
        <form
          onSubmit={(e) => {
            e.preventDefault();
            act(
              () => api("/storage", { path }, "PUT"),
              "Workspace switched. Existing files were not moved.",
            );
          }}
        >
          <label className="field-label">
            Workspace folder
            <input
              value={path}
              onChange={(e) => setPath(e.target.value)}
              required
            />
          </label>
          {importing && (
            <p className="inline-error">
              Wait for photo import to finish before switching workspaces.
            </p>
          )}
          {(state.runs.some(active) ||
            Object.keys(state.viewers || {}).length > 0 ||
            state.setup.state === "running") && (
            <p className="inline-error">
              Finish setup and stop active runs or viewers before switching
              workspaces.
            </p>
          )}
          <p className="small muted">
            Use an absolute folder path. Switching opens a separate workspace;
            it does not move or delete previous scenes.
          </p>
          <div className="button-row">
            <Button
              type="button"
              variant="outline"
              onClick={() => setPicking(true)}
            >
              <FolderOpen size={16} />
              Browse folders
            </Button>
            <Button
              type="submit"
              disabled={
                acting ||
                importing ||
                state.setup.state === "running" ||
                !!getActivity(state) ||
                !!Object.keys(state.viewers || {}).length
              }
            >
              Use this workspace
            </Button>
          </div>
        </form>
        <div className="storage-breakdown">
          <div>
            <strong>Original imports</strong>
            <p>Stable local copies, recorded by content hash.</p>
          </div>
          <div>
            <strong>Per-run working data</strong>
            <p>Prepared images, camera database, and training artifacts.</p>
          </div>
          <div>
            <strong>Saved results</strong>
            <p>
              Latest checkpoints, comparisons, metrics, and exported splats.
            </p>
          </div>
        </div>
      </section>
      <FolderPicker
        open={picking}
        close={() => setPicking(false)}
        initial={path}
        choose={(value: string) => {
          setPath(value);
          setPicking(false);
        }}
      />
    </>
  );
}

function FolderPicker({ open, close, initial, choose }: any) {
  const [listing, setListing] = useState<any>(null);
  const [error, setError] = useState("");
  const [child, setChild] = useState("");
  const load = async (path: string) => {
    try {
      setError("");
      setListing(await api(`/folders?path=${encodeURIComponent(path)}`));
    } catch (e) {
      setError(String(e));
    }
  };
  useEffect(() => {
    if (open) load(initial);
  }, [open]);
  return (
    <Modal
      open={open}
      onOpenChange={close}
      title="Choose a workspace location"
      description="Browse folders visible to the local application. Nothing is moved or created until you save the workspace."
      wide
    >
      {error && <p className="inline-error">{error}</p>}
      {listing ? (
        <>
          <div className="button-row">
            {listing.roots.map((root: string) => (
              <Button
                variant="outline"
                size="small"
                key={root}
                onClick={() => load(root)}
              >
                {root}
              </Button>
            ))}
          </div>
          <p className="folder-current">{listing.path}</p>
          <Button
            variant="ghost"
            size="small"
            onClick={() => load(listing.parent)}
          >
            Parent folder
          </Button>
          <div className="folder-list">
            {listing.folders.map((folder: any) => (
              <button key={folder.path} onClick={() => load(folder.path)}>
                <Folder size={17} />
                {folder.name}
                <ChevronRight size={15} />
              </button>
            ))}
          </div>
          <label className="field-label">
            Optional new subfolder name
            <input
              value={child}
              onChange={(e) => setChild(e.target.value)}
              placeholder="PhotoToSplat"
            />
          </label>
          <div className="modal-actions">
            <Button variant="outline" onClick={close}>
              Cancel
            </Button>
            <Button
              disabled={/[\\/:]/.test(child) || child === ".."}
              onClick={() =>
                choose(
                  listing.path +
                    (child
                      ? (listing.path.includes("\\") ? "\\" : "/") + child
                      : ""),
                )
              }
            >
              Choose this location
            </Button>
          </div>
        </>
      ) : (
        <p>Reading folders…</p>
      )}
    </Modal>
  );
}

function Help() {
  return (
    <>
      <PageTitle
        eyebrow="A PRACTICAL LITTLE FIELD GUIDE"
        title="A new perspective, explained."
        text="You bring the photos. The studio connects the reconstruction tools and keeps each attempt reproducible."
      />
      <div className="help-grid">
        {[
          {
            icon: Image,
            title: "Capture with overlap",
            text: "Move the camera around a stationary scene. Keep the lens and lighting consistent. Start with 80–200 sharp photos from several heights. Glass, mirrors, moving subjects, and missing coverage are harder.",
          },
          {
            icon: Cpu,
            title: "Give the GPU the right tools",
            text: "Training uses an NVIDIA CUDA GPU on Linux or Windows through WSL2. The dashboard itself is lightweight. A successful graphics-card detection is followed by an actual render and gradient test.",
          },
          {
            icon: Aperture,
            title: "Find the cameras first",
            text: "COLMAP finds matching visual features, estimates camera calibration and positions, and builds sparse 3D points. Registration quality is checked before training starts.",
          },
          {
            icon: Box,
            title: "Learn the scene’s appearance",
            text: "Splatfacto optimizes many soft, colored 3D ellipsoids to reproduce the photographs. It creates an appearance representation, rather than a CAD mesh.",
          },
          {
            icon: RefreshCw,
            title: "Keep every experiment",
            text: "A scene holds your imported photos. Each run snapshots its selection and settings. Resuming preserves completed stages; changing settings means making a new run.",
          },
          {
            icon: ShieldCheck,
            title: "Know the practical limits",
            text: "World scale is arbitrary without measurement references. Hidden surfaces cannot be reliably recovered. GPU versions can produce small numerical differences even with the same seed.",
          },
        ].map((item) => (
          <section className="card help-card" key={item.title}>
            <span className="icon-box">
              <item.icon size={23} />
            </span>
            <h3>{item.title}</h3>
            <p>{item.text}</p>
          </section>
        ))}
      </div>
      <div className="config-note">
        <Monitor size={24} />
        <span>
          In the interactive viewer, the preview starts at 1600px. Reducing it
          makes navigation lighter; increasing it cannot restore detail that the
          model did not learn.
        </span>
      </div>
    </>
  );
}
