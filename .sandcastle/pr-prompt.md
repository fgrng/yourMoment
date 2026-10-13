# TASK

Write the title and body of the pull request that brings spec #{{SPEC}} from its integration branch `{{INTEGRATION_BRANCH}}` (your current branch) into `main`.

You only write text. Do not change, commit, push or comment on anything, and do not create the pull request; the driver script does that with your output.

# CONTEXT

<spec>

!`gh issue view {{SPEC}}`

</spec>

<diff-stat>

!`git diff origin/main...HEAD --stat`

Read the actual changes per file with `git diff origin/main...HEAD -- <path>`.

</diff-stat>

<commits>

!`git log origin/main..HEAD --oneline`

</commits>

# WRITE

Call the Skill tool with `pr` and write the body with its template. Write in German, in the domain language of `GLOSSARY.md` if the repo has one.

- The title names the spec in a few words and ends with `(Spec #{{SPEC}})`.
- Do not run tests. The merger and, if there were findings, the spec fix ran `pytest tests/unit -q` green on this branch (or skipped it because only Markdown files changed), State that as evidence; the repo has no CI, so the maintainer runs the suite before merging.
- Leave out open points and any `Closes` line. The driver script appends the spec review's open points and `Closes #{{SPEC}}` to your body.

# OUTPUT

Output a JSON object wrapped in `<pull-request>` tags. The body is Markdown inside a JSON string, so escape newlines and quotes:

<pull-request>
{"title": "...", "body": "## Summary\n\n..."}
</pull-request>

Always emit the `<pull-request>` tags.
