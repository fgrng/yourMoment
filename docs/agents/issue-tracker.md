# Issue tracker: GitHub

Issues and specs for this repo live as GitHub issues. Use the `gh` CLI for all operations.

## Conventions

- **Create an issue**: `gh issue create --title "..." --body "..."`. Use a heredoc for multi-line bodies.
- **Read an issue**: `gh issue view <number> --json number,title,body,labels,comments`.
- **List issues**: `gh issue list --state open --json number,title,body,labels,comments --jq '[.[] | {number, title, body, labels: [.labels[].name], comments: [.comments[].body]}]'` with appropriate `--label` and `--state` filters.
- **Make an issue a sub-issue of a parent**: `gh issue create --parent <parent> ...`, or `gh issue edit <parent> --add-sub-issue <child>` afterwards (`gh` 2.94+). Older `gh`: `gh api --method POST repos/<owner>/<repo>/issues/<parent>/sub_issues -F sub_issue_id=<child-db-id>` (database id, as in **Blocking** below). Without sub-issues, put `Part of #<parent>` at the top of the child body.
- **Comment on an issue**: `gh issue comment <number> --body "..."`
- **Apply / remove labels**: `gh issue edit <number> --add-label "..."` / `--remove-label "..."`
- **Close**: `gh issue close <number> --comment "..."`

Infer the repo from `git remote -v`; `gh` does this automatically when run inside a clone.

## Pull requests as a triage surface

**PRs as a request surface: no.** _(Set to `yes` if this repo treats external PRs as feature requests; `/triage` reads this flag.)_

When set to `yes`, PRs run through the same labels and states as issues, using the `gh pr` equivalents:

- **Read a PR**: `gh pr view <number> --comments` and `gh pr diff <number>` for the diff.
- **List external PRs for triage**: `gh api --paginate 'repos/{owner}/{repo}/pulls?state=open' --jq '.[] | select(.author_association | IN("OWNER","MEMBER","COLLABORATOR") | not) | {number, title, author: .user.login, author_association, labels: [.labels[].name]}'`.
- **Comment / label / close**: `gh pr comment`, `gh pr edit --add-label`/`--remove-label`, `gh pr close`.

GitHub shares one number space across issues and PRs, so a bare `#42` may be either: resolve with `gh pr view 42` and fall back to `gh issue view 42`.

## When a skill says "publish to the issue tracker"

Create a GitHub issue.

## When a skill says "fetch the relevant ticket"

Read it as in **Read an issue** above.

## Finishing work

Code from Sandcastle reaches `main` only through a pull request from an **integration branch**:

- Spec `<n>` (label `Spec`) has its own integration branch `spec/<n>`, created from `main` on first use. Its tickets branch off it and are merged back into it.
- Tickets without a parent spec share the rolling integration branch `sandcastle/standalone`.

Tickets without a spec that are implemented interactively instead of via Sandcastle land directly on `main`. The commit message references the ticket as `(#<n>`; that is how Sandcastle recognises such a blocker as done on `main`.

Sandcastle runs `git fetch origin` at the start of every run and measures everything against `origin/main`; "`main`" below means `origin/main`. It never touches the checkout the run was started from: an integration branch checked out there is skipped for the whole run (no update, none of its tickets, no closing phase), and the log says so.

`npm run sandcastle -- --spec <n>` acts only on spec `<n>`: the run plans only its sub-issues, updates only `spec/<n>` and finishes only this spec. `sandcastle/standalone` and other `spec/<m>` stay untouched: no update, no restart, no push, no PR.

Every issue closes on its own merge:

- **Ticket**: closes once its branch is in the integration branch, not only on `main`. Sandcastle closes it itself after verifying the merge with `git merge-base --is-ancestor`; agents leave it open. If the merger ends without a completion signal, Sandcastle resets the integration branch to its state before the merger and closes none of its tickets.
- **Blocker from the same spec**: counts as done once merged into `spec/<n>` (the script closes it then).
- **Blocker from another spec**: counts as done only once that spec is closed and merged into `main`, via its PR or, after a manual merge, because `spec/<m>` is contained in `main`.
- **Blocker without a spec**: counts as done once it is on `main`: its branch `sandcastle/issue-<n>` is contained there, or a commit there references it as `(#<n>` (keep this commit convention).
- **Spec**: closes when its PR is merged into `main`, via the `Closes #<n>` at the end of the PR body. This PR is the only way a spec closes. Parent issues therefore stay untouched (state, text, labels) while tickets are written, implemented and closed.

Once all sub-issues of a spec are closed and `spec/<n>` has no open PR, Sandcastle runs the spec's **closing phase**: `code-review` over the whole spec against `main`, fixing the standards and correctness findings, a PR body written with the `pr` skill with the spec findings as "Offene Punkte", then push and PR from `spec/<n>` to `main`. A failed closing phase is retried by the next run, not by a later iteration of the same run. From then on the spec is **locked**: Sandcastle comments on its remaining tickets and swaps `ready-for-agent` for `ready-for-human`. Later work belongs in a new spec.

`sandcastle/standalone` has no closing phase. When the branch has commits that are not on `main`, Sandcastle pushes it and opens or updates its PR; after that PR is merged, the branch restarts from `main` in the next run.

The maintainer merges every PR by hand, with a merge commit, after running the test suite. The merge commit keeps the per-ticket commits with their issue references in the history of `main`, for `code-review` and `retro`.

## Relations: sub-issues and blocker edges

Both endpoints expect the numeric **database `id`** of the other issue (`gh api repos/{owner}/{repo}/issues/<n> --jq .id`, not the `#number` and not the `node_id`) as a typed integer (`-F`, not `-f`). Create parent issues and blockers first. `gh api` fills in `{owner}/{repo}` itself.

```bash
# child as sub-issue of a spec or a wayfinder map
gh api --method POST repos/{owner}/{repo}/issues/<parent>/sub_issues -F sub_issue_id=<child-id>
# blocker edge (native dependency, no "Blocked by #N" in the text)
gh api --method POST repos/{owner}/{repo}/issues/<blocked>/dependencies/blocked_by -F issue_id=<blocker-id>
# check (gh issue view --json blockedBy returns no .number)
gh api repos/{owner}/{repo}/issues/<blocked>/dependencies/blocked_by --jq '[.[].number]'
```

A ticket is unblocked when `issue_dependencies_summary.blocked_by` is 0 (only open blockers count).

## Wayfinding operations

Used by `/wayfinder`. The **map** is a single issue with **child** issues as tickets.

- **Map**: a single issue labelled `wayfinder:map`, holding the Notes / Decisions-so-far / Fog body. `gh issue create --label wayfinder:map`.
- **Child ticket**: an issue linked to the map as a GitHub sub-issue (see **Make an issue a sub-issue of a parent**). Where sub-issues aren't enabled, add the child to a task list in the map body and put `Part of #<map>` at the top of the child body. Labels: `wayfinder:<type>` (`research`/`prototype`/`grilling`/`task`). Once claimed, the ticket is assigned to the driving dev.
- **Blocking**: GitHub's **native issue dependencies**, the canonical, UI-visible representation. Add an edge with `gh api --method POST repos/<owner>/<repo>/issues/<child>/dependencies/blocked_by -F issue_id=<blocker-db-id>`, where `<blocker-db-id>` is the blocker's numeric **database id** (`gh api repos/<owner>/<repo>/issues/<n> --jq .id`, _not_ the `#number` or `node_id`). GitHub reports `issue_dependencies_summary.blocked_by` (open blockers only, the live gate). Where dependencies aren't available, fall back to a `Blocked by: #<n>, #<n>` line at the top of the child body. A ticket is unblocked when every blocker is closed.
- **Frontier query**: list the map's open children (`gh issue list --state open`, scoped to the map's sub-issues / task list), drop any with an open blocker (`issue_dependencies_summary.blocked_by > 0`, or an open issue in the `Blocked by` line) or an assignee; first in map order wins.
- **Claim**: `gh issue edit <n> --add-assignee @me`, the session's first write.
- **Resolve**: `gh issue comment <n> --body "<answer>"`, then `gh issue close <n>`, then append a context pointer (gist + link) to the map's Decisions-so-far.
