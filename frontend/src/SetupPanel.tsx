import React, { useEffect, useRef, useState } from "react";
import {
  CheckCircle2,
  Download,
  Loader2,
  Play,
  RefreshCw,
  Settings2,
  ShieldCheck,
  Terminal,
} from "lucide-react";
import { api, type State } from "./api";
import { Button, Modal } from "./components/ui";
import { getActivity } from "./activity";

export function SetupContent({
  state,
  act,
  acting,
  runtimeSettings,
  proceed,
  storage,
}: {
  state: State;
  act: any;
  acting: boolean;
  runtimeSettings?: React.ReactNode;
  proceed?: () => void;
  storage?: () => void;
}) {
  const d = state.diagnostic;
  const container =
    state.delivery?.mode === "docker" || d.delivery === "docker";
  const checking = ["checking", "verifying"].includes(d.state);
  const installed =
    d.tools_installed ?? (d.verified || ["verify", "ready"].includes(d.state));
  const managed =
    !container &&
    (d.managed ??
      !(
        state.settings.runtime.train_prefix || state.settings.runtime.sfm_prefix
      ));
  const storageProblem = d.checks.some(
    (c: any) => c.id === "storage" && c.state !== "ready",
  );
  const unsupported = d.state === "unsupported";
  const missingTools = d.state === "setup" || !!d.missing_tools?.length;
  const running = state.setup.state === "running";
  const busy = acting || !!getActivity(state);
  const [showLog, setShowLog] = useState(false);
  const [setupLog, setSetupLog] = useState("");
  const [repairOpen, setRepairOpen] = useState(false);
  const [repairConfirmed, setRepairConfirmed] = useState(false);
  const [actionError, setActionError] = useState("");
  const [message, setMessage] = useState("");
  const gate = useRef(false);
  const logVisible = showLog || running;
  useEffect(() => {
    if (!logVisible) return;
    const load = () =>
      api("/setup/log")
        .then((result) => setSetupLog(result.text))
        .catch(() => {});
    load();
    const timer = setInterval(load, 2500);
    return () => clearInterval(timer);
  }, [logVisible]);
  const request = async (path: string, body: unknown) => {
    if (gate.current || acting) return;
    gate.current = true;
    setActionError("");
    setMessage("");
    try {
      return await act(async () => {
        try {
          const result = await api(path, body);
          if (result.message) setMessage(result.message);
          return result;
        } catch (error) {
          setActionError(
            error instanceof Error ? error.message : String(error),
          );
          throw error;
        }
      });
    } finally {
      gate.current = false;
    }
  };
  const title = running
    ? "Installing the selected tools…"
    : checking
      ? "Checking your existing setup…"
      : unsupported
        ? "Resolve your computer's prerequisites."
        : storageProblem
          ? "Make room for reconstruction."
          : container && !installed
            ? "This container image needs attention."
            : installed && d.verified
              ? "Your tools are installed and verified."
              : installed
                ? "Your tools are installed."
                : !missingTools
                  ? "We could not finish checking this setup."
                  : managed
                    ? "Install the missing reconstruction tools."
                    : "Check your custom environment paths.";

  return (
    <section className="setup-content setup-panel">
      <div className="setup-status" role="status">
        <span className="icon-box">
          {checking || running ? (
            <Loader2 className="spin" size={22} />
          ) : installed && d.verified ? (
            <CheckCircle2 size={22} />
          ) : (
            <Settings2 size={22} />
          )}
        </span>
        <div>
          <h3>{title}</h3>
          <p className="muted">
            {running
              ? "Keep the app running. Existing environments are reused where possible."
              : checking
                ? "We look for tools already on this computer before offering installation."
                : unsupported
                  ? container
                    ? "Check Docker GPU access and the host NVIDIA driver. The image supplies the reconstruction tools."
                    : "Check the platform and NVIDIA-driver results. Installing Python packages will not resolve those prerequisites."
                  : storageProblem
                    ? "Choose a workspace with more free space. Your installed tools do not need reinstalling."
                    : installed && d.verified
                      ? "Use this setup for every scene. No installation is needed."
                      : installed
                        ? d.verification_error
                          ? "The GPU execution test failed. Review the error and retry the test; reinstalling is not the default next step."
                          : d.verification_changed
                            ? "Your environment changed since the last GPU test. Verify the current setup before reconstructing."
                            : "Run the Gaussian render and gradient test once to confirm this environment works."
                        : container
                          ? "Use the GPU image and recreate the container from a tested version. Tool installation is handled when the image is built."
                          : !missingTools
                            ? "Review the check error and retry tool detection before deciding whether installation is needed."
                            : managed
                              ? "Only the components below need setup. Installed components are kept."
                              : "Fix the selected paths under Advanced / maintenance, or clear them to use managed tools. Managed setup does not replace custom environments."}
          </p>
          {installed && d.verified_at && (
            <p className="small muted">
              Last GPU test: {new Date(d.verified_at).toLocaleString()}
              {d.verified
                ? ". Current environment matches that test."
                : ". Last attempt failed."}
            </p>
          )}
        </div>
      </div>
      {actionError && (
        <p role="alert" className="inline-error">
          {actionError}
        </p>
      )}
      {message && (
        <p role="status" className="config-note">
          {message}
        </p>
      )}
      {d.verification_error && (
        <details className="setup-error">
          <summary>View GPU test error</summary>
          <pre className="log">{d.verification_error}</pre>
        </details>
      )}
      {d.error && (
        <details className="setup-error">
          <summary>View check error</summary>
          <pre className="log">{d.error}</pre>
        </details>
      )}
      {!checking &&
        !running &&
        !installed &&
        missingTools &&
        !unsupported &&
        managed && (
          <>
            <ul className="setup-missing">
              {d.checks
                .filter(
                  (c: any) =>
                    ["colmap", "training", "compiler"].includes(c.id) &&
                    c.state !== "ready",
                )
                .map((c: any) => (
                  <li key={c.id}>
                    <strong>{c.name}</strong>
                    <span>{c.hint}</span>
                  </li>
                ))}
            </ul>
            <div className="setup-allowance">
              <ShieldCheck size={19} />
              <p>
                Allow roughly <strong>15–30 GB</strong> for managed tools,
                downloads and caches, in addition to scene data. Tools live in
                Linux under <code>~/.local/share/photo-to-splat</code>. Your
                NVIDIA driver and system Python are managed separately.
              </p>
            </div>
            <label className="confirm-line">
              <input
                type="checkbox"
                checked={!!state.setup_reviewed}
                disabled={busy}
                onChange={(event) =>
                  request("/setup/review", {
                    profile: state.setup_profile,
                    reviewed: event.target.checked,
                  })
                }
              />
              I have reviewed the requirements and have space for the separate
              environments.
            </label>
            <Button
              disabled={busy || !state.setup_reviewed || storageProblem}
              onClick={() =>
                request("/setup", { profile: state.setup_profile })
              }
            >
              <Download size={17} />
              Install missing tools
            </Button>
          </>
        )}
      <div className="button-row">
        {storageProblem && storage && (
          <Button onClick={storage}>Choose storage</Button>
        )}
        {!checking &&
          !running &&
          installed &&
          !unsupported &&
          !storageProblem &&
          !d.verified && (
            <Button
              disabled={busy}
              onClick={() => request("/diagnostics?verify=true", {})}
            >
              <Play size={16} />
              Verify GPU execution
            </Button>
          )}
        {installed && d.verified && !storageProblem && proceed && (
          <Button onClick={proceed}>Go to my scenes</Button>
        )}
        <Button
          variant="outline"
          disabled={busy}
          onClick={() => request("/diagnostics", {})}
        >
          <RefreshCw size={16} />
          Recheck tools
        </Button>
      </div>
      <details className="setup-maintenance">
        <summary>
          <Settings2 size={18} />
          Advanced / maintenance
        </summary>
        <p className="muted">
          {container
            ? "Creating another scene reuses the tools already packaged in this container."
            : "Review environment paths, inspect installation logs, or explicitly rerun managed setup. Creating another scene does not require setup again."}
        </p>
        {!container && runtimeSettings}
        {container ? (
          <p className="small muted">
            Tools are supplied by the image. To update or repair them, pull a
            tested image version and recreate the container. Keep the scenes
            volume attached to retain your results.
          </p>
        ) : managed ? (
          <>
            <p className="small muted">
              Managed repair restores missing tools and synchronizes pinned
              Python packages. It reuses existing native environments and does
              not erase their folders.
            </p>
            <Button
              variant="outline"
              disabled={busy || unsupported || storageProblem || checking}
              onClick={() => {
                setRepairConfirmed(false);
                setActionError("");
                setRepairOpen(true);
              }}
            >
              Repair managed tools
            </Button>
          </>
        ) : (
          <p className="small muted">
            Managed repair is unavailable while custom environment paths are
            selected.
          </p>
        )}
        {!container && (
          <Button variant="ghost" onClick={() => setShowLog(!showLog)}>
            <Terminal size={16} />
            {showLog ? "Hide" : "Show"} installation log
          </Button>
        )}
      </details>
      {logVisible && (
        <pre className="log" aria-label="Installation log">
          {setupLog || "Waiting for installation output…"}
        </pre>
      )}
      {state.setup.state === "failed" && !installed && (
        <p className="inline-error">
          Setup did not finish. Review the installation log, resolve the
          reported issue, then retry missing tools.
        </p>
      )}
      <Modal
        open={repairOpen}
        onOpenChange={(value) => {
          if (!acting) setRepairOpen(value);
        }}
        title="Repair managed reconstruction tools?"
        description="This reruns managed setup and may download packages. Existing native environments are reused; pinned Python packages are synchronized. Your scenes and source photos are left alone."
      >
        {actionError && (
          <p role="alert" className="inline-error">
            {actionError}
          </p>
        )}
        <label className="confirm-line">
          <input
            type="checkbox"
            checked={repairConfirmed}
            disabled={acting}
            onChange={(event) => setRepairConfirmed(event.target.checked)}
          />
          I want to repair the managed tools and have space for downloads.
        </label>
        <div className="modal-actions">
          <Button
            variant="outline"
            disabled={acting}
            onClick={() => setRepairOpen(false)}
          >
            Cancel
          </Button>
          <Button
            disabled={busy || !repairConfirmed}
            onClick={async () => {
              const result = await request("/setup", {
                profile: state.setup_profile,
                repair: true,
                reviewed: true,
              });
              if (result) setRepairOpen(false);
            }}
          >
            Start managed repair
          </Button>
        </div>
      </Modal>
    </section>
  );
}
