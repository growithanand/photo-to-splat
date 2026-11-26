# Everyday interaction checks

```text
Workspace / Overview → My scenes → Scene → Run details
                         ↓          ↓
                      Search     Rename / Delete → Trash → Restore
                                                     ↓
                                             Delete permanently
```

These are explicit behaviors, not a claim that every possible device or input
has been tested. Tests use isolated fixtures, never a person's real scenes.

| Flow | Expected behavior | Verification |
|---|---|---|
| Click Workspace | Opens Overview | Component + browser |
| Open a scene or run | URL identifies the selected item | Component + browser |
| Back / Forward / refresh | Returns to the corresponding page | Hash routing; Back and refresh exercised |
| Bookmark a missing/deleted item | Shows recovery links instead of an endless spinner | Component |
| Rename | Trims whitespace; updates names without changing run inputs | Component + API + browser |
| Cancel Delete | Keeps the scene in the collection | Component |
| Confirm Delete | Moves scene to Trash; hides its runs from normal actions | Component + API + browser |
| Undo / Restore | Returns photos, run history and results | Component + API + browser |
| Empty Trash / Delete permanently | Names the selected scenes; requires typing DELETE; Cancel preserves them | Component + API; browser confirmation inspected |
| Trash changes during confirmation | Only the listed scene IDs in the original workspace can be removed | Component + API |
| Partial permanent deletion | Shows the error and Retry deletion; prevents restoring incomplete data | Component + filesystem failure test |
| Linked managed folders | Refuses redirected scene/run roots; preserves targets of nested links | Windows filesystem tests |
| Delete active work | Explains that runs/viewers must stop first | API + component; queued case inspected |
| Concurrent Delete / new run | Only one operation wins | Store concurrency test |
| Search with no matches | Offers Clear search | Component |
| Select individual photos or folder | Imports supported photos; reports rejected files | Browser + API |
| Navigate during import | Import continues in the same tab with visible progress | Component |
| Refresh during import | Browser warns; unfinished batches may need retry | beforeunload guard; not crash recovery |
| Deselect photos / change run options | Draft survives page navigation and refresh | Component; selection exercised in browser |
| Reopen viewer's run | Open/Stop controls come from backend state | Component |
| Failed request | Shows an error and Retry or Cancel | Component |
| Mobile navigation | All five primary sections remain reachable | Browser at 390px |
| Scene thumbnails | Stay within their cover and do not hide names/actions | Browser layout inspection |
| Start during another run | Disabled, with a link to the active run; API refuses another submission | Component + concurrent API tests |
| Simultaneous Start / Resume | Exactly one request is admitted | Two-app-instance and request-race tests |
| Setup / verification / viewer overlap | Conflicting actions are disabled and rejected; failures release their locks | Component + CPU-only backend tests |
| Return to an installed setup | Offers scenes or GPU verification; installation stays out of the normal flow | Component + lifecycle tests |
| Restart / recheck tools | Reuses a passing test only for a matching detected environment | Backend lifecycle tests |
| Review installation requirements | Remembers acknowledgment for the current machine/runtime/profile | Component + backend tests |
| Repair managed tools | Available under maintenance with an explicit confirmation; custom paths are protected | Component + API tests |
| Low space / failed GPU test | Gives storage or test guidance, rather than a generic reinstall prompt | Component + backend tests |

The browser draft uses session storage and is scoped to a scene and workspace.
If storage is unavailable, the app still works; unsaved drafts are best-effort.
Immutable runs and imported originals live on disk, independently of browser
storage. Moving a scene to Trash preserves its files and does not free disk space.
**Delete permanently** or **Empty Trash** frees the selected scenes' managed
files after confirmation. Source files outside those folders stay unchanged.
This action has no Undo. See [Trash and storage](trash.md).

GPU rendering/training reliability is a separate concern. See
[verification limits](verification.md); UI tests do not resolve a CUDA launch error.
