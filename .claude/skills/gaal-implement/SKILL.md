---
name: gaal-implement
description: Implements one qualified GitHub issue in 116-Labs/cuecal as a verified change on its own `gaal/` branch holding exactly one commit, then writes the run result to `$GAAL_RUN_DIR/result.json`. Use when a dispatch hands you a repo and issue number that already passed qualification and asks for the `implement` step, before any PR exists. Do not use to open a PR, revise a PR after review, review a PR, or merge; those are other steps. Do not use for issues that have not been qualified.
---
<!-- gaal-stamp blueprint=implement@1.4.0 shared=1.3.0 profile=7d4c49f36df8465f generated=2026-10-01 content=32e8a434fa05a9f1 -->

# gaal-implement

Turn one qualified issue in `116-Labs/cuecal` into a branch off the base holding **exactly one commit** that meets the issue's acceptance criteria and passes every profile gate. `open-pr` takes it from there. This skill never pushes and never opens a PR.

## Run context

- `<run-dir>` in every command below stands for the literal run directory path given in the run context (the value of `GAAL_RUN_DIR`, the directory that holds `$GAAL_RUN_DIR/result.json`). Substitute the literal path. Never write `$GAAL_RUN_DIR` or `$GAAL_RUN_ID` inside a command.
- `run_id` is the literal value of `GAAL_RUN_ID` from the run context.
- Base ref: `main` (`default_branch`), or the parent branch when the dispatch says the work is stacked.
- Tracker: GitHub. Branch prefix: `gaal/`. Commit convention: conventional. Attribution: none. Merge method: squash, message taken from the commits (`merge.message_source: commits`), no merge queue. Attempt limit: **3** (`limits.implement_attempts`).
- Gates, in order, both required:
  1. `lint`: `uv run ruff check .`
  2. `test`: `uv run pytest`
- Preflight: none. Install: the profile names no install command, so install nothing. Use the checkout's existing install and run the gates in the checkout itself. A throwaway worktree would have no install, so do not create one for this work.
- Headless rules: one command per call, with no chains, pipes or redirection. Use literal paths inside this checkout. Put scratch files under `<run-dir>/scratch`. Write files with the file tools, not shell redirection. Run gate commands exactly as written above, with nothing added.

## Steps

1. **Start the clock.** Run `date -u +%Y-%m-%dT%H:%M:%SZ` and keep the output as `started_at`. Run `mkdir -p <run-dir>/scratch`. Keep a running list of gates run (name, command, exit code, duration) and an attempt counter. From here on, every exit path ends in step 13.

2. **Resolve the repo and the issue.** Take the issue number from the dispatch. Run `git remote get-url origin` and confirm it points at `116-Labs/cuecal`. If the repo or issue cannot be resolved, stop without guessing: end as `needs-clarification` if the dispatch is ambiguous, or `failed` if the repo or tracker is unreachable.

3. **Read the full spec.** Fetch the body with `gh issue view <N> --repo 116-Labs/cuecal`. Fetch every comment with `gh api repos/116-Labs/cuecal/issues/<N>/comments --paginate` (`complete-listings`). A failed call, auth expiry or rate limit ends the run as `failed`; never treat a failed read as "no comments" (`fail-closed-reads`). Comments that clarify or narrow scope are part of the spec. When a comment says the body was rewritten, the current body wins. Extract the acceptance criteria as a numbered list.

4. **Check for drift.** Open every file, symbol and line the issue references and compare with the current code on the base. Record any drift. If the issue is ambiguous, or the code has drifted beyond what a plan can safely assume, end as `needs-clarification` with specific, answerable `questions`, each naming the file or criterion it concerns (`ask-mid-run`: never wait for input).

5. **Look for existing code to extend.** Search the repo for code that already owns the capability the issue adds, and extend it rather than building a parallel one. If building new is justified, note why in the plan. Pre-existing debt you notice goes in the report, not the diff (`unrelated-refactor`).

6. **Write the plan before any source edit** (`plan-before-code`). With the file tool, save `<run-dir>/plan.md` listing the files to change, the tests to add, and, for each numbered acceptance criterion, how it will be shown to hold. Every criterion must map to part of the plan. Note any drift and any reuse decision. If a criterion cannot be mapped, end as `needs-clarification`. If the plan would break a public contract, schema or persisted format (CLI surface, config, SQLite state) and the issue does not explicitly ask for it, end as `needs-human` (`unapproved-breaking-change`). If it requires a deploy, publish or migration against a shared environment, leave that out and put the commands in the report for a human (`deploy`).

7. **Check the checkout and look for resumable work.**
   - Run `git status --porcelain`, `git branch --show-current` and `git branch --list "gaal/*"`.
   - **Resume marker handed over in the prompt:** adopt it only if all three hold: the marker's branch is checked out, the base matches the marker's base, and the uncommitted paths are exactly the marker's `paths`. Those edits are this issue's work, not stray edits. Take the marker's plan as the starting plan (copy it to `<run-dir>/plan.md`), seed the manifest with the marker's paths, and go to step 10 with a fresh attempt count of 0. If a condition fails, ignore the marker and apply the rules below.
   - **Existing branch for this issue with a clean tree:** resume it if its commits are sound and based on the base. Otherwise start fresh.
   - **Dirty tree not matching an adopted marker:** the edits predate this run and ownership is unclear. Do not commit, revert, reformat or stash them (`absorb-stray-edits`, `commit-foreign-edits`). End as `needs-human`, with `reason` naming the dirty paths and, if a marker was handed over, which adoption condition failed (branch not checked out, base differs, or dirty paths differ from the marker's `paths`).

8. **Create the branch off the base.** Run `git fetch origin main` (or the parent branch for stacked work), then `git checkout -b gaal/<N>-<short-slug> origin/main`, using the parent ref in place of `origin/main` for stacked work. Never commit or push to `main` (`base-untouched`). If work somehow started on the base, move it to a feature branch and reset the base to its remote. Install nothing. A stacked rebase conflict ends the run as `needs-human`.

9. **Implement the plan.** Read each file before changing it. Keep edits minimal and within the plan. Keep the manifest at `<run-dir>/manifest.txt` with the file tool, one repo-relative path per line, updated every time you write a path. A path missing from the manifest slides into the next issue's commit, so record every file you create or edit, tests included.

10. **Run the gates, counting attempts.** One attempt is one full pass through the gates, followed by fixes when anything failed.
    - Increment the attempt counter.
    - For each gate in order: run `date -u +%s`, then the gate command (`uv run ruff check .`, then `uv run pytest`) as its own call, then `date -u +%s` again. `duration_ms` is the difference times 1000. Record name, exact command, exit code and duration. Replace earlier records for that gate with the latest so the result describes the final tree (`truthful-report`). A gate that did not run is absent, never recorded as passed. Run every gate even if an earlier one failed, so all failures are seen (`status-preserved`).
    - If every gate exits 0 on the final tree, go to step 11 (`gates-green`). Any edit after a green run means the gates run again.
    - If a gate fails and the counter is below 3, fix the cause (update the manifest) and repeat.
    - **At 3 attempts with a gate still failing** (`bounded-attempts`), stop and end as `needs-human` with the failing gate output summarized in the final message and a one-sentence `reason` naming the gate. If work is uncommitted, first write the resume marker with the file tool at `<run-dir>/resume.json`: `{"schema_version": 1, "run_id": "<run_id>", "issue": <N>, "branch": "<branch>", "base": "<base>", "paths": [<the manifest, exactly the dirty tree left behind>], "plan": "<run-dir>/plan.md"}` (`plan` is null if no plan was saved). Do not commit.

11. **Stage and commit exactly the manifest.**
    - Stage by explicit path: `git add <path> <path> ...` listing manifest paths only (`explicit-staging`). Never stage wholesale.
    - Verify with `git diff --cached --name-only` that the staged set equals the manifest exactly, and with `git status --porcelain` that nothing else this run is responsible for is left (`manifest-matches-staged`). Fix any mismatch before committing.
    - Write the commit message with the file tool to `<run-dir>/scratch/commit-msg.txt`. It describes the change as a whole, follows conventional commits (`type(scope): summary`), and carries **no attribution lines** (`commits.attribution: none`; nothing added, nothing dropped, `attribution-policy`). Link the issue by the issue-link rule (`issue-trailer`):
      - every acceptance criterion met: a line `Closes #<N>`.
      - some criteria left open: a line `Refs #<N>` on its own, never a closing keyword, plus a **Deferred** heading listing each open criterion worded as the issue words it. A closing keyword never appears next to a Deferred list.
    - Commit with the hooks enabled: `git commit -F <run-dir>/scratch/commit-msg.txt`. Use no other commit form. A hook that rejects the commit is handled like a failing gate: read its output, fix what it reports (update the manifest, re-run the gates if files changed), and commit again, counting it against the limit of 3. Never skip, redirect or disable hooks, and never retry through another route (`bypass-hook`). If the fix is beyond this run's remit, end as `failed`, naming the hook and quoting its output briefly.

12. **Enforce one commit.** Run `git rev-list --count origin/main..HEAD` (parent ref for stacked work). If it is 0, end as `failed`. If it is more than 1, collapse in place (`single-commit`; the regime is `commits`, so collapse applies):
    - Record the tree with `git rev-parse HEAD^{tree}` and keep a backup with `git branch gaal/backup-<N>-<short-sha> HEAD`.
    - Run `git reset --soft origin/main` (or the parent ref), then commit once with `git commit -F <run-dir>/scratch/commit-msg.txt`, the message rewritten as a whole for the change: process commits ("wip", "fix lint") dropped, no attribution, issue link per the rule above.
    - Check that `git rev-parse HEAD^{tree}` equals the recorded tree. If not, or if the change nets to empty, restore with `git reset --hard <backup-branch>` and end as `failed`. Never use an interactive rebase.
    - Re-check that `git rev-list --count origin/main..HEAD` is 1. Run `git rev-parse HEAD` to get `commit_sha` (40 hex chars) and `git branch --show-current` for `branch`. Confirm `git status --porcelain` is empty. The tree is identical, so the earlier green gate run still holds.

13. **Write the run result to `$GAAL_RUN_DIR/result.json` on every exit path**, failures included (`run-result-written`). Run `date -u +%Y-%m-%dT%H:%M:%SZ` for `finished_at`. With the file tool, write `<run-dir>/result.json.tmp` as one JSON object, then run `mv <run-dir>/result.json.tmp <run-dir>/result.json`. Never leave the `.tmp` file behind. Fields:
    - `schema_version`: `1`; `run_id`: the literal run id from the run context; `blueprint`: `"implement"`; `blueprint_version`: `"1.4.0"`; `repo`: `"116-Labs/cuecal"`; `issue`: the number (null if it could not be resolved); `pr`: `null`.
    - `status`: one of the exit states below.
    - `attempts`: gate-fix attempts consumed, at least 1 (use 1 when the run ended before any gate ran).
    - `gates`: every gate actually run on the final tree, each with `name`, `command`, `exit_code`, `duration_ms`; an empty array if none ran.
    - `branch` and `commit_sha`: set on `done`; otherwise the branch if one exists, and `null` for the sha when no commit exists.
    - `reason`: required unless `done`; one sentence of at most 160 characters naming the decision or action needed. Detail goes in the final message.
    - `questions`: required and non-empty for `needs-clarification`.
    - `started_at`, `finished_at`: as read from the clock.

    In the final message, list each acceptance criterion as met or not met, the gates that ran and any that did not and why, drift found, pre-existing debt noticed but left alone, hand-off notes (new exports, names) word for word, and any deploy or migration commands left for a human.

## Exit states

- `done`: the single commit exists, every gate exited 0 on the final tree, and `branch`, `commit_sha` and `gates` are set. A partial result uses `Refs #N` and a Deferred list, never a closing keyword.
- `needs-clarification`: the spec is ambiguous, the code drifted from what the issue describes, or a criterion cannot be mapped to the plan. `questions` are specific and answerable, each naming the file or criterion it concerns.
- `needs-human`: the attempt limit of 3 was reached (with `resume.json` written when the work is uncommitted); a risky-surface guard fired (breaking contract, schema or persisted-format change the issue did not ask for); the checkout had edits of unclear ownership (`reason` lists the dirty paths and, if a marker was handed over, the failed adoption condition); or a stacked rebase conflicted. `reason` says which and what a human should do.
- `failed`: environment or tooling problems (repo or tracker unreachable, auth or rate-limit errors, disk, a hook rejection beyond this run's remit, a collapse that failed its tree check). `reason` includes enough to retry.

## Invariants

- `plan-before-code`: `<run-dir>/plan.md` exists, mapping every acceptance criterion, before the first source edit (step 6).
- `single-commit`: at hand-off `git rev-list --count <base>..HEAD` is 1 (step 12).
- `manifest-matches-staged`: the commit holds exactly the paths in the manifest (steps 9 and 11).
- `gates-green`: `lint` and `test` both ran on the final tree and exited 0, and the result lists each (step 10).
- `issue-trailer`: the message carries `Closes #N` only when every criterion is met, else `Refs #N` plus a Deferred list (step 11).
- `bounded-attempts`: gate-fix cycles stop at 3 and end as `needs-human` (step 10).
- `explicit-staging`: stage only manifest paths by explicit name (step 11).
- `base-untouched`: never commit or push to `main` (step 8).
- `fail-closed-reads`: a failed API read stops the run (step 3).
- `complete-listings`: comments are paginated to the end (step 3).
- `truthful-report`: the result and final message state only what happened; an unrun gate is absent (steps 10 and 13).
- `status-preserved`: no command's failure is hidden by a chain, pipe or filter (steps 10 and 11).
- `attribution-policy`: the message follows `commits.attribution: none` exactly (step 11).
- `run-result-written`: `$GAAL_RUN_DIR/result.json` is written atomically on every exit path (step 13).

## Forbidden actions

- `absorb-stray-edits`: never commit, revert or reformat changes that were in the checkout before the run (step 7).
- `deploy`: no deploys, migrations against shared environments, or publishes; hand the commands to a human (step 6).
- `unapproved-breaking-change`: no breaking change to a public contract, schema or persisted format unless the issue explicitly asks (step 6).
- `unrelated-refactor`: no fixing of pre-existing debt outside the change's scope; record it in the report (steps 5 and 9).
- `ask-mid-run`: never wait on interactive input; end as `needs-clarification` with questions (step 4).
- `bare-force-push`: this skill never pushes. If a force-push ever became necessary, only `--force-with-lease=<branch>:<sha>` on the inspected sha is acceptable.
- `admin-bypass`: never merge, push or rewrite with admin privileges to get around branch protection or a hook.
- `bypass-hook`: never skip, redirect or disable verification: no flag that skips hooks, no signing bypass, no change to where git looks for hooks, no hook manager switched off, no edit to hook files or `.git/config`, no retry through another route. Fix what the hook reports (step 11).
- `machine-specific-paths`: no home directories, drive letters, private scripts or services in commands, plan or messages.
- `commit-foreign-edits`: never commit changes this run did not make (steps 7 and 11).
