# Coordinating GPU work

```text
Start / Resume → lock workspace records → check active work → reserve queued run
                              ↓ conflict                        ↓
                     HTTP 409 + current activity       worker holds compute lock
                                                                ↓
                                                   completion / stop / failure
                                                                ↓
                                                           release lock
```

Each workspace allows one reconstruction or managed GPU task at a time. A second
Start or Resume request returns the current activity so the user can open the
running job instead of accidentally adding another one.

| Action | Allowed when |
|---|---|
| Start a reconstruction | No queued/running reconstruction, setup, check, or viewer owns the workspace |
| Resume | Same idle rule; target is stopped/failed and its runtime still matches |
| Open a viewer | Training produced a checkpoint and the workspace is idle; reopening the same managed viewer reuses it |
| GPU verification | No active reconstruction, viewer, setup or other check |
| Install tools | No active reconstruction, viewer, check or other installation |
| Change runtime/workspace | Active operations have ended; workspace switching also waits for in-flight imports |
| Stop current work | Always reachable from the active run; repeated stop requests are safe |
| Review/import photos or download results | Available during reconstruction; existing run inputs remain immutable |

`Store.create_run` and `Store.resume_run` check and reserve a run inside the same
filesystem lock. This covers CLI callers and independent app processes using the
same workspace. Sync API actions also share a control lock and consistent lock
order. GPU work, viewers, verification and installation retain `.compute.lock`
until they exit. Exception paths release the reservation.

The UI derives active work from run records as well as the server's activity
response. It refreshes on focus and after rejected requests, displays a link to
the active run, and uses immediate click guards while Start/Resume is pending.
The server checks every request again. This also covers requests from another
tab or app instance, where the displayed status may be out of date.

Tests send simultaneous requests through two app instances and simulate failures
while a background task holds the lock. They use CPU processes and temporary
workspaces, so no CUDA work or package installation is needed.

This is coordination within one workspace, not a machine-wide GPU scheduler.
Another workspace, a direct third-party training command, or a forcibly orphaned
Linux process can still occupy the device. Keep one workspace active per GPU and
inspect the process list and logs after an abnormal shutdown. Any older queued
records are preserved and processed sequentially.
