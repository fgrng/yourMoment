# TASK

Review branch `{{BRANCH}}` for issue #{{TASK_ID}}: {{ISSUE_TITLE}}

You improve the code on this branch yourself; a review that only lists findings is half done.

# CONTEXT

<issue>

!`gh issue view {{TASK_ID}} --comments`

</issue>

<diff-stat>

A summary of the diff, changed files with line counts only:

!`git diff {{INTEGRATION_BRANCH}}...{{BRANCH}} --stat`

Read the actual changes per file with `git diff {{INTEGRATION_BRANCH}}...{{BRANCH}} -- <path>`.

</diff-stat>

<commits>

!`git log {{INTEGRATION_BRANCH}}..{{BRANCH}} --oneline`

</commits>

Fetch the parent spec with `gh api repos/{owner}/{repo}/issues/{{TASK_ID}}/parent`; HTTP 404 means the issue has no parent. If it has one, read it with `gh issue view <parent>` and list its sub-issues with `gh api repos/{owner}/{repo}/issues/<parent>/sub_issues --jq '[.[] | {number, title, state}]'`.

# REVIEW

## 1. Analyse with the `code-review` skill

Call the Skill tool with `code-review`. Its report is your worklist. Hand it everything up front so it runs straight through without a question:

- **Fixed point:** `{{INTEGRATION_BRANCH}}`. The diff is `git diff {{INTEGRATION_BRANCH}}...{{BRANCH}}`.
- **Spec:** issue #{{TASK_ID}} above. The parent spec is context. Code that belongs to another *open* sub-issue of that spec is scope creep.
- **Standards:** `CODING_STANDARDS.md`, plus the skill's smell baseline, plus three checks: new or changed behaviour is covered by tests; exceptions are caught narrowly and assumptions are checked; the change keeps inputs safe from injection and secrets out of code and logs.
- **Tests:** check every new or changed test against "What Tests Never Check" in `CODING_STANDARDS.md`: no wording of documentation, no source code outside import-graph guards and lint-style rules over all files, no expected values from the module's own constants or calculations, no absence of fields or methods.

If you cannot start sub-agents, run the two axes one after the other and keep their reports separate.

## 2. Act on the findings

- **Standards:** fix them on this branch. Behaviour stays exactly as it is; only the shape of the code changes.
- **Correctness:** write a test that shows the bug first, then fix it.
- **Spec** (missing requirement, scope creep, misread requirement): report it for a human to decide. Post one comment on the issue, in German, listing every spec finding with the quoted spec line: `gh issue comment {{TASK_ID}} --body-file -`. Leave the code for these findings as it is.

# EXECUTION

The implementer left the branch green, so there is no starting run.

1. Make the changes and commit them in one commit whose message starts with `RALPH: Review -`.
2. Run `pytest tests/unit -q` and fix whatever fails, so the branch ends green, also when you made no commit: a branch that fast-forwards lands without another test run. Skip this only if the branch changes only Markdown files.

If the skill reports nothing to fix, make no commit.

Once complete, output <promise>COMPLETE</promise>.
