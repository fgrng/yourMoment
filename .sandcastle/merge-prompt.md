# TASK

Merge the following branches into the current branch, `{{INTEGRATION_BRANCH}}`:

{{BRANCHES}}

For each branch:

1. Run `git merge <branch> --no-edit`
2. If there are merge conflicts, resolve them intelligently by reading both sides and choosing the correct resolution

After all branches are merged, run `uv run pytest tests/unit -q` once and fix whatever fails; skip the run if the merged branches change only Markdown files. Commit any fixes in one commit; the merge commits need no extra summary commit.

Do not close any issues; the driver script closes them after verifying each merge.

Once you've merged everything you can, output <promise>COMPLETE</promise>.
