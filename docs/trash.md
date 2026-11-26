# Trash and storage

```text
My scenes → Delete → Trash ── Restore → My scenes
                       │
                       └── Delete permanently / Empty Trash
                              Review names → Type DELETE → Remove files
```

Moving a scene to Trash hides it and its runs. Its files remain on disk so that
**Restore** can bring back its photos, settings, and saved reconstructions.

To reclaim space, open **My scenes → Trash**. Use **Delete permanently** beside
one scene or **Empty Trash** above the list. The dialog lists every selected
scene. Type **DELETE** and confirm only when you are ready to remove those files.
Cancel leaves everything in place. There is no Undo after permanent deletion.

## What gets removed

The application removes the selected scene's generated folder under
`workspace/scenes/<scene-id>` and its runs under `workspace/runs/<run-id>`. These
contain imported photo copies, thumbnails, working datasets, camera solutions,
checkpoints, comparison renders, and exported results. Keep another copy of
anything you want to retain before confirming.

The source paths recorded during import are not deletion targets. Photos outside
these managed folders, other scenes, tool environments, and download caches stay
in place. Deleting a scene will not uninstall reconstruction tools or necessarily
reduce the size of a WSL virtual disk file on the Windows drive.

The confirmation captures exact scene IDs and a workspace location. Scenes moved
to Trash later are excluded. If a selected scene is restored in another tab or
the workspace changes, the request is refused so you can review the selection
again. Queued/running reconstructions and managed viewers protect their own
scene. An unrelated scene's viewer can stay open.

## If cleanup fails

Large folders can take time to remove. Keep the app running until it reports the
result. A locked file or permission error may leave part of a scene behind. The
entry stays in Trash with an explanation and **Retry deletion**. Close programs
using its files, check folder permissions, and retry.

Once cleanup starts, **Restore** is disabled for that entry: some of its data may
already be gone. A small cleanup record retains the run IDs so a later retry can
remove the remaining files even if a run's own record was already deleted.

Deletion validates managed root paths before recursively removing files. It
refuses redirected scene/run roots and removes nested links without traversing
their targets. These guards assume ordinary local use; they do not provide an
atomic defense against another program maliciously replacing filesystem entries
during cleanup. Tests exercise Windows links/junctions and preserve an external
sentinel file.
