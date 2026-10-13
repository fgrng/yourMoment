# Triage Labels

The skills speak in terms of five canonical triage roles. This file maps those roles to the actual label strings used in this repo's issue tracker.

| Label in mattpocock/skills | Label in our tracker | Meaning                                  |
| -------------------------- | -------------------- | ---------------------------------------- |
| `needs-triage`             | `needs-triage`       | Maintainer needs to evaluate this issue  |
| `needs-info`               | `needs-info`         | Waiting on reporter for more information |
| `ready-for-agent`          | `ready-for-agent`    | Fully specified, ready for an AFK agent  |
| `ready-for-human`          | `ready-for-human`    | Requires human implementation            |
| `wontfix`                  | `wontfix`            | Will not be actioned                     |

When a skill mentions a role (e.g. "apply the AFK-ready triage label"), use the corresponding label string from this table.

Edit the "Label in our tracker" column to match whatever vocabulary you actually use.

## Spec

Label every spec issue (from `/to-spec`) **`Spec`**, alongside `ready-for-agent`. Sandcastle (`.sandcastle/tracker.mts`) hands the planner `ready-for-agent` issues minus `Spec` minus `is:blocked`, so AFK agents run a spec's unblocked tickets, never the spec itself; both would touch the same files and collide. Ticket order comes from native blocked-by edges, not from the planner: a blocker in the same spec releases its ticket once merged into the spec branch, a blocker from another spec only once that spec is closed and merged into `main` (details in `issue-tracker.md#finishing-work`). `npm run sandcastle -- --spec <n>` limits a run to spec `<n>`: only its sub-issues, only `spec/<n>`; `sandcastle/standalone` and other spec branches stay untouched. Tickets are sub-issues of their spec and carry no type label.

Sandcastle changes a label only at the lock: once spec `<n>` has an open PR, Sandcastle comments on its remaining tickets and swaps `ready-for-agent` for `ready-for-human`. Integration branches, when tickets and specs close, and the PR flow are in [issue-tracker.md](issue-tracker.md#finishing-work).

## Other labels

- **`Sandcastle`**: legacy label of the earlier sequential-reviewer setup. Sandcastle now selects by `ready-for-agent`; the label has no effect.
