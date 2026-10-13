# TASK

Fix the findings of the spec review of spec #{{SPEC}} on its integration branch `{{INTEGRATION_BRANCH}}` (your current branch). It becomes a pull request to `main` once you are done.

<findings>

{{FINDINGS}}

</findings>

Read the spec with `gh issue view {{SPEC}} --comments` for context. Fix only these findings; do not pick up other work.

# EXECUTION

- **Standards findings:** fix them. Behaviour stays exactly as it is; only the shape of the code changes.
- **Correctness findings:** write a test that shows the bug first, then fix it.

Do not comment on or close any issue; the driver script opens the pull request.

# FEEDBACK LOOPS

The merger left the branch green, so there is no starting run.

1. Make the changes and commit them in one commit whose message starts with `RALPH: Spec-Review -` and references `(Spec #{{SPEC}})`.
2. Run `pytest tests/unit -q` and fix whatever fails. The branch must end green. Skip this if your commit changes only Markdown files.

Once complete, and only if these tests are green or were skipped, output <promise>COMPLETE</promise>.
