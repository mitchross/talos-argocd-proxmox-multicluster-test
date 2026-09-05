# Agent instructions

Before working in this directory or its descendants, read and follow
[`CLAUDE.md`](CLAUDE.md) in this directory. It is the canonical project
guidance; load it yourself without waiting for the user to mention it.

Before editing a file, also read any deeper `CLAUDE.md` files along the path
to that file, in order from parent to child. More specific directory rules
apply within their scope.

# Agent Instructions

## Mink Knowledge Capture

Keep Mink updated during substantive work. Hooks may track session state automatically, but durable decisions, verified root causes, runbooks, and gotchas require explicit note capture with `mink note` or `/mink:note`.

Use `mink note --project talos-argocd-proxmox --category resources` for durable references and `--category projects` for active decisions or followups. Do not capture routine edits, raw command output, or unverified hypotheses. Mention saved Mink note paths in the final response.
