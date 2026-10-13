# TASK

Review the whole of spec #{{SPEC}} on its integration branch `{{INTEGRATION_BRANCH}}` (your current branch) against `main`. All its sub-issues are closed; the branch is about to become a pull request.

You only analyse. Do not change, commit or comment on anything: a fix-implementer acts on your findings afterwards, and spec findings go to a human in the PR text.

# CONTEXT

<spec>

!`gh issue view {{SPEC}} --comments`

</spec>

<sub-issues>

!`gh api repos/{owner}/{repo}/issues/{{SPEC}}/sub_issues --jq '[.[] | {number, title, state}]'`

</sub-issues>

Read each closed sub-issue with `gh issue view <n> --comments`.

<diff-stat>

!`git diff origin/main...HEAD --stat`

Read the actual changes per file with `git diff origin/main...HEAD -- <path>`.

</diff-stat>

<commits>

!`git log origin/main..HEAD --oneline`

</commits>

# REVIEW

Call the Skill tool with `code-review`. Hand it everything up front so it runs straight through without a question:

- **Fixed point:** `origin/main`. The diff is `git diff origin/main...HEAD`.
- **Spec:** spec #{{SPEC}} above together with its closed sub-issues. Judge the spec as a whole: does every user story land, and do the tickets fit together?
- **Standards:** `CODING_STANDARDS.md`, plus the skill's smell baseline, plus three checks: new or changed behaviour is covered by tests; exceptions are caught narrowly and assumptions are checked; the change keeps inputs safe from injection and secrets out of code and logs.

If you cannot start sub-agents, run the two axes one after the other and keep their reports separate.

# OUTPUT

Sort the findings of the report into three lists, each finding one self-contained sentence in German with the file (and line, where it helps):

- `standards`: findings of the Standards axis.
- `correctness`: bugs, including Spec findings where a requirement looks implemented but the implementation is wrong.
- `spec`: missing or partial requirements and work nobody asked for. Quote the spec line.

Leave out findings that are judgement calls you would not act on. Output the lists as a JSON object wrapped in `<spec-review>` tags:

<spec-review>
{"standards": ["..."], "correctness": ["..."], "spec": ["..."]}
</spec-review>

An empty list is fine. Always emit the `<spec-review>` tags.
