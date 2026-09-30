---
name: gaal-implement
description: Implements one qualified GitHub issue in 116-Labs/cuecal as a verified change on its own `gaal/` branch holding exactly one commit, then writes the run result to `$GAAL_RUN_DIR/result.json`. Use when a dispatch hands you a repo and issue number that already passed qualification and asks for the `implement` step, before any PR exists. Do not use to open a PR, revise a PR after review, review a PR, or merge; those are other steps. Do not use for issues that have not been qualified.
---
<!-- gaal-stamp blueprint=implement@1.1.0 shared=1.1.0 profile=0ed21dd3bece7944 generated=2026-09-30 content=b740f04d05a8079a -->

# gaal-implement

Take one qualified issue and produce a branch off the base with **exactly one commit** that meets the issue's acceptance criteria and passes the profile gates. `open-pr` takes it from there. This step never pushes, opens a PR, or merges.

## Profile facts this skill uses

- Repo: `116-Labs/cuecal`. Base: `main`. Tracker: `github`.
- Branch prefix: `gaal/`.
- Commits: conventional commit messages, `attribution: none`, single commit.
- Merge: squash, no queue, `message_source: commits`. The commit message is what lands, so it must be written as a whole.
- Gates (both currently `pending: true`, `required: false`):
  - `lint`: `uv run ruff check .`
  - `test`: `uv run pytest`
- Preflight: none.
- Attempt limit: `limits.implement_attempts` = **3**.
- Inputs from the environment: `GAAL_RUN_ID`, `GAAL_RUN_DIR`. Dispatch supplies the issue number and, for stacked work, a parent base branch.

## Steps

Record `started_at` (UTC, RFC 3339) before anything else. From then on, every exit path ends at step 13.

1. **Resolve repo and issue.** Confirm the repo is `116-Labs/cuecal` and the issue number came from dispatch. If either cannot be resolved, or the repo is unreachable, stop. Never guess. Unreachable repo or broken tooling ends as `failed`; an unresolvable issue ends as `needs-clarification` if the number is ambiguous, otherwise `failed`.

2. **Read the whole issue.** Fetch the issue body **and every comment** from the GitHub tracker. Paginate to the end, and if a call errors or is rate-limited, stop as `failed` (`fail-closed-reads`, `complete-listings`). Never treat a failed call as "no comments". Comments that clarify or narrow scope are part of the spec. If a comment says the body was rewritten, the current body wins. Extract the acceptance criteria as a numbered list.

3. **Check for drift.** Verify every file, symbol and line the issue references against the current code on the base. Record each drift.

4. **Look for existing owners.** Search for code that already owns the capability the issue adds, and extend it instead of building a parallel one. If building new is justified, record why.

5. **Write the plan** (`plan-before-code`). Before the first source edit, write a short plan: files to change, tests to add, and how each acceptance criterion will be shown to hold. Every criterion must map to part of the plan. If the issue is ambiguous, or the drift from step 3 is too large for the plan to safely assume, do not code: end as `needs-clarification` with specific questions, each naming the file or criterion it concerns (`ask-mid-run`: never wait for an answer).

6. **Risk guards.** If the plan touches a risky surface (schema migrations, persisted formats, public API or MCP contracts, deploy config) and the issue does not explicitly ask for a breaking change, end as `needs-human` instead of changing it (`unapproved-breaking-change`). Never run deploys, shared-environment migrations or publishes; if one is needed, put the commands in the final message for a human (`deploy`).

7. **Check the checkout and look for prior work.**
   - Run `git status --porcelain` and note every path already modified or untracked before this run. Those belong to someone else: never commit, revert, reformat or stage them (`absorb-stray-edits`, `commit-foreign-edits`). `.gaal/` untracked is expected and stays out of the commit.
   - If those edits' ownership is unclear and this run would have to work in that checkout, end as `needs-human`. If dispatch or the profile asks for a worktree, work in a separate worktree and leave the main checkout untouched.
   - Look for an existing `gaal/` branch or worktree for this issue. Resume it only if its state is sound (based on the current base, no foreign or unexplained commits, clean tree). Otherwise start fresh.

8. **Create the branch** off the base (`main`, or the parent branch dispatch names for stacked work; if no stacking tool is present, use a single branch off `main`). Name it `gaal/<issue-number>-<short-slug>`. Never commit to the base (`base-untouched`); if you find work already started on the base, move it to a feature branch and stop for a human if it is not clearly yours. Preflight is empty, so nothing extra runs. `uv run` resolves the environment on first use; if the dependency install is broken, end as `failed`.

9. **Implement the plan.** Read each file before changing it. Keep edits minimal and inside the plan. Do not fix pre-existing debt or refactor unrelated code; record it in the final message instead (`unrelated-refactor`). Keep a **manifest** of every path this run writes, updating it on each edit. A path missing from the manifest gets left out of the commit, and in stacked work it slides into the next issue's commit.

10. **Run the gates, bounded** (`gates-green`, `bounded-attempts`). Run in order on the current tree, capturing exit code and wall-clock duration for each:
    - `uv run ruff check .`
    - `uv run pytest`

    Both gates are pending. A pending gate must still exit 0 whenever it is runnable on the final tree. Skip one only while its tool or manifest does not exist yet (for example, no `pyproject.toml`, or `uv` unavailable). A skipped gate is absent from the `gates` array, not recorded as passed, and the final message says which gate was skipped and why (`truthful-report`). Do not skip a gate because it fails.

    Preserve each command's exit status; never let a pipe or filter hide it (`status-preserved`). On failure, fix the cause and re-run **all** gates; each fix-and-re-run cycle counts as one attempt, and the first run is attempt 1. At **3** attempts with a gate still failing, stop and end as `needs-human` with the failing gate output summarized. Never loop past the limit. Fixes that stay in scope only; never weaken or delete a test or lint rule to make a gate pass.

11. **Stage and commit** (`single-commit`, `explicit-staging`, `manifest-matches-staged`, `issue-trailer`).
    - Stage by explicit path from the manifest only, for example `git add -- <path> <path>`. Never stage everything wholesale, and never use `git commit -a`.
    - Compare `git diff --cached --name-only` with the manifest. They must be identical. Fix any mismatch before committing.
    - Write the message to a file and commit with it. It is a conventional commit (`type(scope): summary`) describing the change as a whole, with a body only when the why is not obvious. Attribution policy is `none`: add no `Co-Authored-By` line, no "Generated with" line, and nothing else attributing an AI (`attribution-policy`).
    - Reference the issue. Use a closing keyword (`Closes #<n>`) **only if every acceptance criterion is met**; otherwise use a plain reference (`Refs #<n>`).
    - Do not use `--no-verify`. If a repo hook refuses the commit, read its actual output and handle the cause.

12. **Collapse if needed.** `merge.message_source` is `commits`, so the collapse applies. Run `git rev-list --count <base>..HEAD`. If it is 0 after committing, something went wrong: stop as `failed`. If it is more than 1, collapse **in place** (never interactive rebase):
    - Record the tree hash: `git rev-parse HEAD^{tree}`.
    - `git reset --soft $(git merge-base <base> HEAD)`, then re-check the staged paths against the manifest and commit again with the whole-change message from step 11.
    - The new tree hash must equal the recorded one, and the count must now be exactly 1, or restore the previous HEAD and end as `needs-human`.
    - Nothing is pushed in this step, so no force-push is needed. If a human later needs one, it must be `--force-with-lease=<branch>:<sha>` on the inspected sha.

    Finish by confirming `git rev-list --count <base>..HEAD` prints `1` and the working tree holds no changes this run is responsible for. Capture `commit_sha` with `git rev-parse HEAD`.

13. **Write the run result** (`run-result-written`) on every exit path, including all failures and early stops. Write `$GAAL_RUN_DIR/result.json` atomically: write a temp file in the same directory, then rename it over `result.json`. If `GAAL_RUN_DIR` is unset, say so in the final message. The JSON must be valid against the run-result schema:
    - Always: `schema_version` `1`, `run_id` from `$GAAL_RUN_ID`, `blueprint` `"implement"`, `blueprint_version` `"1.1.0"`, `repo` `"116-Labs/cuecal"`, `issue` (integer, or `null` if it could not be resolved), `pr` `null`, `status`, `attempts` (integer of at least 1, the gate-fix attempts consumed; use `1` if the run stopped before any gate ran), `gates`, `branch` (string or `null`), `commit_sha` (40-hex or `null`), `started_at`, `finished_at` (UTC RFC 3339).
    - `gates`: one entry per gate actually run on the final tree, each with `name`, `command` (exact command that ran), `exit_code`, `duration_ms`. Gates that did not run are omitted. Use `[]` when none ran.
    - `reason`: required unless status is `done`. One sentence, at most 160 characters, naming the decision or action needed. Put detail in the final message, not here.
    - `questions`: required and non-empty when status is `needs-clarification`; each is specific and answerable and names a file or criterion.
    - No other properties. Do not add `review`, `tier` or `model`.

    Example for a successful run:

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
      "attempts": 2,
      "gates": [
        {"name": "lint", "command": "uv run ruff check .", "exit_code": 0, "duration_ms": 850},
        {"name": "test", "command": "uv run pytest", "exit_code": 0, "duration_ms": 4200}
      ],
      "branch": "gaal/12-example-slug",
      "commit_sha": "<40 hex chars>",
      "started_at": "2026-09-29T10:00:00Z",
      "finished_at": "2026-09-29T10:12:00Z"
    }
    ```

    After the file is written, end with a short final message: status, branch, commit sha, each acceptance criterion as met or not met, gates run and any skipped with the reason, drift found, out-of-scope debt noticed, and any commands a human must run. Report only what actually happened; write "fixed in `<sha>`" only when that sha contains the fix (`truthful-report`).

## Exit states

- `done`: the single commit exists on its `gaal/` branch, every runnable gate exited 0 on the final tree, and `branch`, `commit_sha` and `gates` are set. The final message lists each acceptance criterion as met or not met. A partial result uses a plain issue reference, not a closing keyword.
- `needs-clarification`: the spec is ambiguous, or the code drifted from what the issue describes. `questions` are set, each naming the file or criterion it concerns. No code was written.
- `needs-human`: the 3-attempt limit was reached (summarize the failing gate output); a risky-surface guard fired; the checkout had edits whose ownership is unclear; or the collapse could not preserve the tree. `reason` says which and what a human should do.
- `failed`: environment or tooling problems (repo unreachable, tracker call errored or rate-limited, dependency install broken, disk full). `reason` gives enough to retry.

## Invariants

- `plan-before-code`: a written plan exists before the first source edit and every acceptance criterion maps to it (step 5).
- `single-commit`: at hand-off, `git rev-list --count <base>..HEAD` is 1 (steps 11 and 12).
- `manifest-matches-staged`: the commit's files are exactly the manifest of paths this run wrote (steps 9 and 11).
- `gates-green`: every runnable gate, pending ones included, ran on the final tree and exited 0, and each is listed in the result; skipped gates are reported as skipped (step 10).
- `issue-trailer`: the message references the issue, with a closing keyword only when every criterion is met (step 11).
- `bounded-attempts`: gate-fix cycles stop at 3, then the run ends as `needs-human` (step 10).
- `explicit-staging`: stage only manifest paths, by explicit path (step 11).
- `base-untouched`: never commit or push to `main` (step 8).
- `fail-closed-reads`: tracker errors, auth expiry and rate limits stop the run (step 2).
- `complete-listings`: issue comments are paginated to the end or the run stops (step 2).
- `truthful-report`: the result and message state only what happened (steps 10 and 13).
- `status-preserved`: no exit status is lost to a pipe, filter or guard (steps 10 and 12).
- `attribution-policy`: attribution is `none`, so the commit carries no AI attribution and nothing is added on your own initiative (step 11).
- `run-result-written`: `result.json` is written atomically on every exit path (step 13).

## Forbidden actions

- `absorb-stray-edits`: committing, reverting or reformatting changes already in the checkout before the run (step 7).
- `deploy`: running deploys, shared-environment migrations or publishes; hand the commands to a human (step 6).
- `unapproved-breaking-change`: breaking a public contract, schema or persisted format unless the issue explicitly asks (step 6).
- `unrelated-refactor`: fixing pre-existing debt outside the change's scope; record it in the report (step 9).
- `ask-mid-run`: waiting on interactive input; end as `needs-clarification` with questions instead (step 5).
- `bare-force-push`: no force-push without `--force-with-lease=<branch>:<sha>` on the inspected sha; this step does not push (step 12).
- `admin-bypass`: no admin privileges to get around branch protection, a merge queue or a verification hook, and no `--no-verify`.
- `machine-specific-paths`: no home directories, private scripts or services; take everything from the profile and environment variables.
- `commit-foreign-edits`: never commit changes this run did not make (steps 7 and 11).

Also never use `git add -A`, `git add .` or `git commit -a`, never rebase interactively, and never merge or push as part of this step.
