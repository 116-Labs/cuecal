---
name: gaal-implement
description: Implements one qualified GitHub issue in 116-Labs/cuecal as a verified change on its own `gaal/` branch holding exactly one commit, then writes the run result to `$GAAL_RUN_DIR/result.json`. Use when a dispatch hands you a repo and issue number that already passed qualification and asks for the `implement` step, before any PR exists. Do not use to open a PR, revise a PR after review, review a PR, or merge; those are other steps. Do not use for issues that have not been qualified.
---
<!-- gaal-stamp blueprint=implement@1.1.0 shared=1.1.0 profile=0ed21dd3bece7944 generated=2026-09-30 content=e470e3fb08feaeb0 -->

# gaal-implement

Turn one qualified issue into a verified change on its own branch, holding exactly one commit ahead of the base. `open-pr` takes over from there. This run never pushes and never opens a PR.

## Project facts

- Repo: `116-Labs/cuecal`. Base branch: `main`. Tracker: GitHub issues.
- Branch prefix: `gaal/`. Name the branch `gaal/<issue-number>-<short-slug>`.
- Commit convention: conventional commits (`type(scope): subject`). Attribution policy: `none`. Add no AI attribution, no `Co-Authored-By` line and no "generated with" line to the message.
- Merge method: squash, taking its message from the commits (`merge.message_source: commits`), no merge queue. The single commit is therefore the permanent record.
- Review policy: one approval is required. That is for later steps and does not change what you do here.
- Attempt limit: `limits.implement_attempts` = 3.
- Preflight: none defined. Do not invent any.
- Gates, in this order. Both are pending (planned, not yet required):
  1. `lint`: `uv run ruff check .`
  2. `test`: `uv run pytest`

## Inputs

- Repo and issue number from the dispatch. If a base ref other than `main` is given for stacked work, use it. No stacked-branch tool is named in the profile, so use a plain single branch.
- Environment: `GAAL_RUN_ID`, `GAAL_RUN_DIR`.

## Steps

0. Record the start time (UTC, RFC 3339) for `started_at`. Start an attempt counter at 0. Start an empty manifest of every path this run writes.

1. **Resolve repo and issue.** Confirm the checkout is `116-Labs/cuecal` and that the issue exists. If either cannot be resolved, stop and go to Step 12 with `needs-clarification` (dispatch gave nothing usable) or `failed` (tracker or repo unreachable). Never guess. Under `fail-closed-reads`, an API error, auth expiry or rate limit is `failed`, never "no comments".

2. **Read the whole spec.** Read the issue body and every comment, paginating to the end (`complete-listings`). If any page fails to load, stop as `failed`. Comments that clarify or narrow scope are part of the spec. If a comment says the body was rewritten, the current body wins. List the acceptance criteria explicitly.

3. **Check for drift.** Compare every file, symbol and line the issue references with the current code on the base. Record each mismatch.

4. **Reuse before building.** Search the repo for code that already owns the capability the issue adds, and extend it rather than writing a parallel version. If building new is justified, record why.

5. **Write the plan (`plan-before-code`).** Before the first source edit, write a short plan: files to change, tests to add, and how each acceptance criterion will be shown to hold. Every criterion must map to part of the plan. If the issue is ambiguous, or the drift from Step 3 is too large for the plan to assume safely, end as `needs-clarification` with specific, answerable questions that each name the file or criterion concerned (`ask-mid-run`: never wait for an answer). Check the plan against the guards below; a hit ends the run as `needs-human`.
   - Guard: a change to a public contract, schema or persisted format that the issue does not explicitly ask for is `unapproved-breaking-change`. Stop as `needs-human` and say what a person must approve.
   - Guard: anything that needs a deploy, a migration against a shared environment, or a publish is `deploy`. Do not run it. Put the commands in the final message for a person, and end as `needs-human` if the issue cannot be satisfied without them.

6. **Inspect the checkout and look for prior work.**
   - Run `git status`. Note every change already present before this run (currently `.claude/` and `.gaal/` are untracked). Those belong to someone else: do not commit, revert, reformat or stage them (`absorb-stray-edits`, `commit-foreign-edits`). If a pre-existing edit touches a file the plan must change and you cannot tell who owns it, stop as `needs-human`.
   - Look for an existing branch or worktree for this issue (`gaal/<issue-number>-*`). Resume it only if it is based on the current base, all its commits are yours, and its tree is clean. Otherwise start fresh under a new branch name and leave the old one alone.

7. **Create the branch (`base-untouched`).** Branch off the base. Use a separate worktree if the dispatcher or profile asks for one, or if the main checkout has pre-existing uncommitted edits. Never commit to `main`. If commits land on `main` by mistake, move them to the feature branch and reset `main` to its remote. Gates run through `uv run`, which builds the project environment; if that environment cannot be built, or `uv` or the disk is broken, end as `failed` with enough detail to retry. Do not share installed dependencies between worktrees unless lockfiles match and the source install is complete.

8. **Implement.** Read each file before changing it. Keep edits minimal and tied to the plan. Add each path you write to the manifest as you write it (a path missing from the manifest is silently dropped from the commit). Do not fix pre-existing debt outside the change's scope (`unrelated-refactor`); note it for the final message instead.

9. **Run the gates (`gates-green`, `bounded-attempts`).** Each pass of implement-then-gates counts as one attempt; increment the counter for every pass.
   - Run `lint` then `test` on the final tree, timing each and keeping its exact command and exit code.
   - Both gates are pending. A pending gate must still exit 0 whenever it can run. Skip one only while its tool or manifest does not exist yet (for example `uv` is not installed, or the project has no `pyproject.toml`). Say so in the final message, and leave a skipped gate out of the result's `gates` array; it is absent, not passed.
   - If a gate fails, fix the cause and re-run all gates on the new tree. Never bypass a hook or skip a check to get a green result.
   - When the counter reaches 3 and a gate still fails, stop with `needs-human`, and summarize the failing gate output in the final message. Never loop past the limit.

10. **Self-review, then commit.** Before committing, read your own diff for correctness against each acceptance criterion, stray files and leftover debug code; fixing a lower layer after submission would rebase everything above it. Then:
    - Stage exactly the manifest, by explicit path (`explicit-staging`). Never stage everything wholesale.
    - Confirm the staged file list equals the manifest (`manifest-matches-staged`) and that no other change this run is responsible for remains in the working tree.
    - Create one conventional-commit message that describes the change as a whole. Follow the attribution policy: none. Put the issue reference in the message (`issue-trailer`): `Closes #<n>` only if every acceptance criterion is met; otherwise the plain reference `Refs #<n>`.

11. **Collapse to one commit (`single-commit`).** `merge.message_source` is `commits`, so the collapse applies. Count with `git rev-list --count <base>..HEAD`. If the count is 0 or 1, do nothing. If it is greater than 1, collapse in place (the mode is in-place; no PR exists): record the current HEAD sha and tree hash (`git rev-parse HEAD^{tree}`), soft-reset to the merge base, and commit the same staged content once with a whole-change message (drop process messages such as "wip" or "fix lint"). Never use an interactive rebase. After committing, the tree hash must equal the pre-collapse one. If it differs, or the result is empty, restore the recorded HEAD and stop as `needs-human`. Re-check that the count is exactly 1. If any commit on the branch has a different author, do not rewrite it; stop as `needs-human`. If the commit changed the tree after the gates ran, re-run the gates.

12. **Write the run result (`run-result-written`, `truthful-report`).** This is the last step and happens on every exit path, including failures and early stops. See "Run result" below. Then give a final message with: the outcome, each acceptance criterion marked met or not met, each gate that ran and each one skipped with the reason, out-of-scope debt you noticed, and any new exports or names a later issue needs, stated word for word so they can be passed forward.

## Exit states

- `done`: The single commit exists, `git rev-list --count <base>..HEAD` is 1, and every gate that could run exited 0. `branch`, `commit_sha` and `gates` are set. A partial result still ends `done` only if it is honest: use `Refs #<n>`, not a closing keyword, and list the unmet criteria in the final message.
- `needs-clarification`: The spec is ambiguous, or the code has drifted from what the issue describes. `questions` is non-empty, specific and answerable, and each question names its file or criterion.
- `needs-human`: The attempt limit of 3 was reached; a risky-surface guard fired (breaking change, deploy or migration need); the checkout has edits whose ownership is unclear; or a collapse safety check failed. `reason` says which, and what a person should do.
- `failed`: Environment or tooling problems: repo or tracker unreachable, dependency or environment build broken, disk full, or a tracker read that errored. `reason` includes enough to retry.

## Run result

Write JSON to `$GAAL_RUN_DIR/result.json` atomically: write `result.json.tmp` in the same directory, then rename it over `result.json`. Do this only when `GAAL_RUN_DIR` is set; if it is unset, say so in the final message. Fields:

- `schema_version`: `1`
- `run_id`: the value of `$GAAL_RUN_ID`
- `blueprint`: `"implement"`, `blueprint_version`: `"1.1.0"`
- `repo`: `"116-Labs/cuecal"`, `issue`: the issue number (or `null` if it could not be resolved), `pr`: `null`
- `status`: one of `done`, `needs-human`, `needs-clarification`, `failed`
- `reason`: required unless the status is `done`. One sentence, at most 160 characters, naming the decision or action needed. Put detail in the final message, not here.
- `questions`: required and non-empty when the status is `needs-clarification`; omit otherwise.
- `attempts`: integer of at least 1, the number of implement-and-gate passes consumed
- `gates`: array of `{name, command, exit_code, duration_ms}` for each gate that actually ran (empty array if none ran)
- `branch`: the branch name, or `null` if none was created; `commit_sha`: the 40-character lowercase hex sha of the single commit when `done`, otherwise `null`
- `started_at` and `finished_at`: RFC 3339 UTC timestamps

No other fields. Example for `done`:

```json
{
  "schema_version": 1,
  "run_id": "<value of GAAL_RUN_ID>",
  "blueprint": "implement",
  "blueprint_version": "1.1.0",
  "repo": "116-Labs/cuecal",
  "issue": 12,
  "pr": null,
  "status": "done",
  "attempts": 1,
  "gates": [
    {"name": "lint", "command": "uv run ruff check .", "exit_code": 0, "duration_ms": 850},
    {"name": "test", "command": "uv run pytest", "exit_code": 0, "duration_ms": 4200}
  ],
  "branch": "gaal/12-example-slug",
  "commit_sha": "0123456789abcdef0123456789abcdef01234567",
  "started_at": "2026-01-01T00:00:00Z",
  "finished_at": "2026-01-01T00:05:00Z"
}
```

## Invariants

- `plan-before-code`: A written plan exists before the first source edit, and every acceptance criterion maps to part of it (Step 5).
- `single-commit`: At hand-off the branch has exactly one commit ahead of the base (Steps 10 and 11).
- `manifest-matches-staged`: The files in the commit are exactly the manifest of paths this run wrote (Step 10).
- `gates-green`: Every gate that can run exited 0 on the final tree, and the result lists each one that ran. A skipped pending gate is stated as skipped and left out of `gates` (Step 9).
- `issue-trailer`: The commit message references the issue, with a closing keyword only when every acceptance criterion is met (Step 10).
- `bounded-attempts`: Gate-fix cycles stop at 3 attempts; the run then ends as `needs-human` (Step 9).
- `explicit-staging`: Stage only manifest paths, by name (Steps 8 and 10).
- `base-untouched`: Never commit or push to `main` (Step 7).
- `fail-closed-reads`: Errors, auth expiry and rate limits stop the run and are never treated as empty results (Steps 1 and 2).
- `complete-listings`: Comment listings are read to the end or the run stops (Step 2).
- `truthful-report`: The result and final message describe what actually happened. A gate that did not run is absent, and no sha is claimed that does not contain the change (Steps 9 and 12).
- `status-preserved`: Never hide a command's exit status behind a pipe or filter. Check every gate and git command result (Steps 9 to 11).
- `attribution-policy`: The message follows `commits.attribution: none` exactly. Nothing is added and nothing is dropped on your own initiative (Step 10).
- `run-result-written`: `result.json` is written atomically on every exit path (Step 12).

## Forbidden actions

- `absorb-stray-edits`: Do not commit, revert or reformat changes that were in the checkout before the run (Step 6).
- `deploy`: Do not run deploys, migrations against shared environments, or publishes. Return the commands for a person (Step 5).
- `unapproved-breaking-change`: Do not break a public contract, schema or persisted format unless the issue explicitly asks (Step 5).
- `unrelated-refactor`: Do not fix pre-existing debt outside the change's scope; record it in the final message (Step 8).
- `ask-mid-run`: Do not wait on interactive input; end as `needs-clarification` with questions (Step 5).
- `bare-force-push`: This run does not push. If a force-push were ever unavoidable, it must use `--force-with-lease=<branch>:<sha>` with the sha you inspected, and never `--force` or `-f`.
- `admin-bypass`: Do not merge, push or rewrite with admin privileges, and do not skip hooks with `--no-verify`.
- `machine-specific-paths`: Do not write home directories, drive letters, private scripts or secrets into files, commits or the result.
- `commit-foreign-edits`: Do not commit changes this run did not make. Never use `git add -A`, `git add .` or `git commit -a`.
