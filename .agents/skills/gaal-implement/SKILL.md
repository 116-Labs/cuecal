---
name: gaal-implement
description: Implements one qualified GitHub issue in 116-Labs/cuecal as a verified change on its own `gaal/` branch holding exactly one commit, then writes the run result to `$GAAL_RUN_DIR/result.json`. Use when a dispatch hands you a repo and issue number that already passed qualification and asks for the `implement` step, before any PR exists. Do not use to open a PR, revise a PR after review, review a PR, or merge; those are other steps. Do not use for issues that have not been qualified.
---
<!-- gaal-stamp blueprint=implement@1.7.0 shared=1.4.0 profile=7d4c49f36df8465f generated=2026-10-03 core=e7ca0d74f7c8e378 forbidden=e3a5c6b1ec65f2a7 content=dac0d133d2ef1523 -->

# gaal-implement

Take one qualified issue in `116-Labs/cuecal` and produce a branch off `main` (or a designated stacked base) holding **exactly one commit**. That commit must satisfy the issue's acceptance criteria and pass every profile gate (`uv run ruff check .` and `uv run pytest`). `open-pr` takes it from there. This run never pushes, never opens a PR, and never merges.

## Run context

- Dispatch inputs: repository `116-Labs/cuecal`, issue number `<N>`, base ref (`main` unless a stacked parent branch is given), optional resume marker, and optional merged-PR note.
- `<run-dir>` stands for the literal run directory path from the run context (the value of `GAAL_RUN_DIR`). The run id is the literal value of `GAAL_RUN_ID`. Write both out literally in every command and file. Never expand environment variables in a command, never put `NAME=value` before a command, and never use `$(...)` or backticks in commands.
- The run is headless and cannot ask anyone anything interactively (`ask-mid-run`). Anything requiring human input becomes `needs-clarification` with specific `questions`.
- Allowed shell commands: `git`, `gh`, `mkdir`, `mv`, `cp`, `ls`, `cat`, `date`, `pwd` with any arguments, plus exactly `uv run ruff check .` and `uv run pytest`. Run one command per call, with no `&&`, `;`, or `|` chains. Write files using the file-editing tool, never with shell redirection.
- Scratch files and throwaway worktrees go inside `<run-dir>/scratch` or `<run-dir>/worktree`, never in `/tmp` or via `mktemp`.
- The profile specifies no `install` command and no `preflight` command. Install nothing. Work and run all gates in this checkout where dependencies are already installed. (A throwaway worktree has no install, so gates must run in the checkout itself).
- Commit convention is conventional commits (`type(scope): subject`). Attribution policy (`commits.attribution`) is `none`: add no AI attribution and no `Co-Authored-By` trailer.
- Merge regime: squash merge with `message_source: commits`. Branch prefix: `gaal/`. Attempt limit: `limits.implement_attempts` = 3.

## Steps

1. **Start the clock and initialize records.**
   - Run `date -u +%Y-%m-%dT%H:%M:%SZ` and keep the timestamp as `started_at`.
   - Run `mkdir -p <run-dir>/scratch`.
   - Note the literal run id and issue number `<N>`.
   - Initialize an attempt counter at 0 and an empty list of gate execution records.
   - Every exit path from here on ends by writing the run result in step 13 (`run-result-written`).

2. **Resolve the repo and the issue.**
   - Run `git remote get-url origin` and verify it matches `116-Labs/cuecal`.
   - Run `gh issue view <N> --repo 116-Labs/cuecal --json number,title,body,state,labels`.
   - If the repo or issue cannot be resolved, or if an API call fails due to auth expiry, rate limit, or network error, stop and end as `failed` with enough in `reason` to retry. Never guess, and never convert a failed API call into an empty result (`fail-closed-reads`).

3. **Read the issue body and all comments.**
   - Fetch all comments to the end: `gh api repos/116-Labs/cuecal/issues/<N>/comments --paginate` (`complete-listings`).
   - Comments that clarify or narrow scope are part of the specification; prefer comments starting with `**Clarification**`, `**Clarification (rewrite)**`, or `**Clarification (scope narrow)**`. When a comment indicates the body was rewritten, the current body wins.
   - Explicitly list and number all acceptance criteria.

4. **Check checkout state, inspect code references, and search for reuse.**
   - Run `git status --porcelain` and `git branch --show-current`. Ignore untracked files located under `<run-dir>`. Any other pre-existing dirty path is unowned work (`absorb-stray-edits`, `commit-foreign-edits`): record dirty paths, and never commit, revert, or reformat them. Handle them in step 6.
   - Run `git fetch origin main`. If the fetch fails, end as `failed` (`fail-closed-reads`).
   - Check every file, symbol, and line referenced by the issue against the current code. Record any drift.
   - Search the codebase for existing modules and functions that already own the capability the issue introduces, and extend them rather than creating parallel implementations. If building new code is justified, record the rationale.
   - If the issue specification is ambiguous or the codebase has drifted beyond what a plan can safely assume, end as `needs-clarification` with specific, answerable questions naming the affected file or criterion (`ask-mid-run`).

5. **Write the plan before any code (`plan-before-code`).**
   - Write a concise plan detailing: files to change, tests to add, how each numbered acceptance criterion will be proven to hold, any recorded code drift, and reuse decisions.
   - Save the plan with the file-writing tool to `<run-dir>/plan.md`.
   - Do not edit any repository source file before `<run-dir>/plan.md` is saved (`plan-before-code`).
   - Validate the plan against repository guards; if a guard fires, end as `needs-human` explaining the guard and required human action:
     - Changing a public contract, CLI interface, config format, SQLite schema, or persisted data format in a breaking way without the issue explicitly requesting it (`unapproved-breaking-change`).
     - Executing deploys, shared environment migrations, or publishes (`deploy`). Return the commands for a human in the hand-off report instead of running them.

6. **Resolve resumable prior work, merged PRs, and resume markers.**
   - **Check for merged pull requests:** Run `gh pr list --repo 116-Labs/cuecal --state all --head gaal/<N>-<slug> --json number,state,mergedAt,headRefName`. Never resume a branch whose pull request has already merged. After a squash merge, the branch still appears one commit ahead of `main`, but its work is already in `main`. Resuming it re-submits work that already merged.
   - When a merged-PR note is handed over in the prompt or detected: never check out or resume the old local branch it names, and never build on the merged branch's commits. If a handed-over resume marker names a different branch, that branch's work still applies (adopt it by the marker rule below). Otherwise start fresh from the fetched base (`origin/main`). The fresh branch may reuse the branch scheme's name by recreating it at the fetched base (for example `git switch -C gaal/<N>-<slug> origin/main` without checking the old branch out). Implement only what the issue still requires beyond that merged PR.
   - **Without a merged-PR note:** Run `git branch --list 'gaal/*'` to check for an existing branch `gaal/<N>-<slug>`. Resume it if its state is sound (clean tree, commits based on top of current `origin/main`). Otherwise start fresh.
   - **Resume marker adoption:** If the prompt handed over a resume marker, adopt it only when all three conditions hold: its branch is checked out, its base matches the current base (`main`), and the uncommitted dirty paths in the checkout match the marker's `paths` exactly. Those edits are this issue's work, not stray edits. Take the marker's plan as the starting plan (`<run-dir>/plan.md`), put its `paths` into this run's manifest, reset the attempt counter to 0, and go straight to step 9 (running gates).
   - If a handed-over resume marker does not match the tree, ignore it. If the checkout then contains dirty paths that are not the run's own, end as `needs-human`. The `reason` must list the dirty paths and which adoption condition failed: branch not checked out, base differs, or dirty paths differ from marker's `paths`.
   - If the checkout is on `main` with commits ahead of `origin/main`, never commit on `main` (`base-untouched`). Move any work off the base only if it is clearly yours; otherwise end as `needs-human`.

7. **Create the branch off the base.**
   - Unless an existing sound branch or resume marker was adopted in step 6, run `git switch -c gaal/<N>-<slug> origin/main`, where `<slug>` is a short lowercase kebab-case summary of the issue title. For stacked work, branch off the parent branch.
   - Isolating each issue's context on its own branch is required for multi-issue runs. Never commit or push to `main` (`base-untouched`).
   - The profile names no `install` command, so install nothing and work within the checkout.

8. **Implement the plan.**
   - Read each file before modifying it. Keep edits minimal, precise, and in scope.
   - Do not fix pre-existing debt or refactor code outside the scope of the change (`unrelated-refactor`); note any observed debt in the final report.
   - Add covering tests for every new or modified behavior as specified in the plan.
   - Maintain a manifest of every path created or written by this run in `<run-dir>/manifest.txt` (written and updated with the file tool as files are created or modified).
   - A path missing from the manifest causes severe damage: in stacked work, missing changes slide into the next issue's commit or get lost (`manifest-matches-staged`). Never include files this run did not write (`commit-foreign-edits`).

9. **Run every profile gate and handle failures (`gates-green`, `bounded-attempts`).**
   - Run each profile gate in order on the current tree, as separate commands:
     1. Time and run `lint`: `date -u +%s`, then `uv run ruff check .`, then `date -u +%s`. Record name `lint`, command `uv run ruff check .`, exit code, and `duration_ms` as (end minus start) times 1000.
     2. Time and run `test`: `date -u +%s`, then `uv run pytest`, then `date -u +%s`. Record name `test`, command `uv run pytest`, exit code, and `duration_ms` as (end minus start) times 1000.
   - Increment the attempt counter for each full pass of both gates.
   - Both gates are required (`gates-green`). Run them exactly as written, with no flags or arguments added. A gate that did not run is absent from the result, never recorded as passed (`truthful-report`). Preserve each command's exit code without masking through pipes or filters (`status-preserved`).
   - If a gate fails, examine the error output, fix the root cause in code (never skip, weaken, or delete tests/checks), update `<run-dir>/manifest.txt`, and re-run both gates from the beginning on the new tree.
   - Gate-fix cycles stop at 3 attempts (`limits.implement_attempts` = 3; `bounded-attempts`).
   - If the third attempt still fails, end as `needs-human` with the failing gate output summarized in `reason` (one sentence, at most 160 characters; detail goes in the final message).
   - **Resume marker on attempt limit:** If stopping at the attempt limit with uncommitted work, write `<run-dir>/resume.json` with the file tool before exiting: `schema_version` 1, `run_id`, `issue`, `branch`, `base` (`main`), `paths` (the manifest matching the dirty tree left behind), and `plan` (`<run-dir>/plan.md`). Stopping at the attempt limit leaves a tree that a re-run would otherwise reject as unclear ownership; the resume marker enables clean adoption by the next run. Then proceed to step 13 with status `needs-human`.
   - Once required gates are green, if any advisory checks exist in the profile (none configured), run them over the changed surface. Fix only issues introduced by this change; pre-existing findings are recorded in the hand-off and not fixed here (`unrelated-refactor`). Advisory checks never block and do not count against the attempt limit.
   - A gate pass counts only when both required gates exit 0 on the final tree (`gates-green`).

10. **Stage the manifest and create one commit with verification hooks enabled.**
    - Stage only the manifest paths by explicit path: `git add -- <path1> <path2> ...` (`explicit-staging`). Never use `git add -A`, `git add .`, or `git commit -a`.
    - Verify staging with `git diff --cached --name-only` and compare against `<run-dir>/manifest.txt`. The staged files must equal the manifest exactly (`manifest-matches-staged`). Run `git status --porcelain`: confirm no other changes this run made remain unstaged, and foreign pre-existing edits remain untouched.
    - Write the commit message to `<run-dir>/commit-msg.txt` with the file tool:
      - Follow conventional commits format: `type(scope): subject` (subject in imperative mood, no trailing period).
      - Describe the change as a whole rather than recounting process steps.
      - Attribution policy is `none` (`attribution-policy`): add no AI attribution and no `Co-Authored-By` trailers.
      - Link the issue by the issue-link rule (`issue-trailer`):
        - Full change (all acceptance criteria met): append `Closes #N` on its own line.
        - Partial change (some criteria deferred): append `Refs #N` on its own line, followed by a **Deferred** heading listing each open criterion worded exactly as in the issue. Never put a closing keyword next to a Deferred list.
    - Commit with `git commit -F <run-dir>/commit-msg.txt`.
    - Verification hooks stay enabled. Never use `--no-verify`, `git commit -n`, `--no-gpg-sign`, `-c core.hooksPath=...`, switch off hook managers, or edit hook files or `.git/config` (`bypass-hook`). If a hook rejects the commit, treat it as a failing gate: fix what it reports, restage the manifest, re-run gates (step 9), and commit again, counting against the 3 attempts. If the fix is beyond this run, end as `failed`.

11. **Collapse to one commit in place, self-review, and report drift.**
    - **In-place collapse (`single-commit`):** Run `git rev-list --count origin/main..HEAD`. The merge regime uses `message_source: commits`, so the branch must hold exactly one commit ahead of `main`. If count is 1, proceed. If count > 1:
      - Record pre-collapse tree hash: `git rev-parse 'HEAD^{tree}'`, and old head sha: `git rev-parse HEAD`.
      - Check authorship with `git log --format=%an origin/main..HEAD`; if any commit was authored by someone else, stop and end as `needs-human`.
      - Run `git reset --soft origin/main`.
      - Write the whole-change commit message to `<run-dir>/commit-msg.txt` and run `git commit -F <run-dir>/commit-msg.txt`.
      - Verify that `git rev-parse 'HEAD^{tree}'` matches the pre-collapse tree hash. If the hashes differ or the change nets to empty, restore with `git reset --hard <old-sha>` and end as `failed`.
      - Confirm `git rev-list --count origin/main..HEAD` is 1 (`single-commit`).
    - **Adversarial self-review (`self-reviewed`):**
      - Inspect the final diff (`git diff origin/main...HEAD`) adversarially, as a hostile reviewer who has not read your plan.
      - Verify every acceptance criterion, check edge cases, error handling, un-tested code paths, contradictions between code, documentation, and tests, and verify nothing outside the manifest was touched.
      - Review before anything leaves the machine; fixing issues after submission causes rebases and dismisses approvals. Fix any issues found within this run, running fixes back through the gates (step 9) and preserving the single commit.
    - **Plan drift and issue update (`drift-reported`):**
      - Record every drift from the plan (files, approach, or criteria that diverged from `<run-dir>/plan.md`).
      - If the plan changed (scope, approach, or criteria), update the GitHub issue body: write the updated body to `<run-dir>/issue-body.md` and run `gh issue edit <N> --body-file <run-dir>/issue-body.md`. Retain the original issue text and enclose all changes strictly between drift markers:
        ```markdown
        <!-- gaal:plan-drift -->
        <drift-details>
        <!-- /gaal:plan-drift -->
        ```
        Every line modified must fall between the markers. (If the issue body cannot be edited, post a comment carrying the opening marker).

12. **Record final commit SHA and prepare hand-off.**
    - Run `git rev-parse HEAD` and record the 40-hex SHA as `commit_sha`.
    - This run does not push to any remote, open pull requests, or merge (`base-untouched`).
    - Prepare the final hand-off message: state the self-review outcome, list each acceptance criterion as met or deferred, report gates that ran, detail any plan drift and whether the issue was updated, note any pre-existing debt observed, and list any deploy or migration commands left for a human (`deploy`).

13. **Write the run result on every exit path (`run-result-written`).**
    - Run `date -u +%Y-%m-%dT%H:%M:%SZ` and record as `finished_at`.
    - Write `<run-dir>/result.json.tmp` using the file-writing tool.
    - Move it atomically into place: `mv <run-dir>/result.json.tmp <run-dir>/result.json`. Never leave the `.tmp` file behind (`run-result-written`).
    - The JSON object must match the run-result schema exactly:
      - `schema_version`: `1`
      - `run_id`: literal value of `GAAL_RUN_ID` from the run context
      - `blueprint`: `"implement"`
      - `blueprint_version`: `"1.7.0"`
      - `repo`: `"116-Labs/cuecal"`
      - `issue`: integer `<N>`, or `null` if unresolved
      - `pr`: `null`
      - `status`: one of `"done"`, `"needs-human"`, `"needs-clarification"`, `"failed"`
      - `reason`: required unless `status` is `"done"`; one sentence of at most 160 characters naming the decision or action needed
      - `questions`: required array of non-empty strings when `status` is `"needs-clarification"`; omit otherwise
      - `attempts`: positive integer of at least 1 (gate-fix passes consumed; use 1 if exiting before gates run)
      - `gates`: array of gate executions on the final tree, each with `name`, `command`, `exit_code`, `duration_ms` (empty array if no gates ran)
      - `branch`: the created/resumed branch name (e.g. `"gaal/<N>-<slug>"`), or `null` if none
      - `commit_sha`: the 40-hex commit SHA, or `null` if no commit was made
      - `started_at`: ISO 8601 timestamp
      - `finished_at`: ISO 8601 timestamp
    - Do not add extra fields. The result and report reflect only what actually happened (`truthful-report`).

## Exit states

- `done`: The single commit exists on the branch, all required gates (`lint`, `test`) exit 0 on the final tree, and `branch`, `commit_sha`, and `gates` are set. The hand-off report lists each acceptance criterion as met or deferred. A partial result uses `Refs #N` and a Deferred list, never a closing keyword.
- `needs-clarification`: The specification is ambiguous or the codebase has drifted from what the issue describes. `questions` are specific and answerable, each naming the affected file or criterion. No unowned source edits have been made.
- `needs-human`: The attempt limit of 3 was reached with failing gates (leaving a resume marker when work is uncommitted); a risky-surface guard fired (unapproved breaking change to contracts/schemas, or deploy/migration command); the checkout had edits of unclear ownership (unmatched by a resume marker); or a rebase conflicted. `reason` states what happened and what a human should do. For unclear-ownership refusals, `reason` lists the dirty paths and which adoption condition failed.
- `failed`: Environment, tooling, or repository failures (repository unreachable, API call failed, dependency install broken, verification hook rejection beyond this run's remit, collapse content-preservation failure, or disk full). `reason` provides enough detail to retry.

## Invariants

- `plan-before-code`: `<run-dir>/plan.md` exists before the first source edit, and every acceptance criterion maps to part of it (steps 5, 8).
- `single-commit`: At hand-off, the branch has exactly one commit ahead of the base (`git rev-list --count origin/main..HEAD` is 1; step 11).
- `manifest-matches-staged`: The files in the commit equal the manifest of paths this run wrote exactly (`git diff --cached --name-only` matches `<run-dir>/manifest.txt`; step 10).
- `gates-green`: Every required profile gate (`uv run ruff check .` and `uv run pytest`) ran on the final tree and exited 0, and the run result lists each one (step 9).
- `issue-trailer`: The commit message links the issue by the issue-link rule: `Closes #N` only if every acceptance criterion is met; otherwise `Refs #N` on its own line with a Deferred list naming each open criterion (step 10).
- `bounded-attempts`: Gate-fix cycles stop at 3 attempts (`limits.implement_attempts`), ending as `needs-human` rather than looping indefinitely (step 9).
- `self-reviewed`: An adversarial review of the final diff ran before hand-off, and any fixes went back through the gates and the single commit (step 11).
- `drift-reported`: Every drift from the plan, and every deploy or migration command left for a human, is reported in the hand-off message; if the plan changed, the issue body is updated between `<!-- gaal:plan-drift -->` and `<!-- /gaal:plan-drift -->` markers (steps 11, 12).
- `explicit-staging`: Stage only paths this run wrote, by explicit path from the manifest; never stage wholesale with `git add -A` or `git add .` (step 10).
- `base-untouched`: Never commit or push to `main` (steps 6, 7, 12).
- `fail-closed-reads`: Errors, auth expiry, and rate limits stop the run; they never become "no comments" or "no issue" (steps 2, 3, 4).
- `complete-listings`: All listings of comments, issues, and checks are paginated to the end or the run stops (step 3).
- `truthful-report`: The report and run result describe what actually happened; a gate that did not run is absent, not marked passed (steps 9, 13).
- `status-preserved`: A command's success or failure is never lost to a pipe, filter, or guard (steps 2, 9, 10).
- `attribution-policy`: `commits.attribution` is `none`: no AI attribution, no `Co-Authored-By` trailer, and no tool credits are added (step 10).
- `run-result-written`: `result.json` is written atomically on every exit path, including failures, via a `.tmp` file and rename (steps 1, 9, 13).

## Forbidden actions

- `absorb-stray-edits`: Committing, reverting, or reformatting changes that were already in the checkout before the run began (steps 4, 6).
- `deploy`: Running deploys, migrations against shared environments, or publishes. Return the commands for a human in the hand-off report instead of running them (steps 5, 12).
- `unapproved-breaking-change`: Changing a public contract, CLI surface, config format, SQLite schema, or persisted format in a breaking way without the issue explicitly requesting it (step 5).
- `unrelated-refactor`: Fixing pre-existing debt outside the change's scope. Record it in the hand-off report instead (steps 8, 9).
- `ask-mid-run`: Waiting on interactive input during a headless run. End as `needs-clarification` with specific questions instead (steps 2, 4).
- `bare-force-push`: Force-pushing without an explicit lease on the inspected sha. This run does not push; if force-pushing elsewhere, only `--force-with-lease=<branch>:<sha>` is permitted (never `--force` or `-f`).
- `admin-bypass`: Merging, pushing, or rewriting with admin privileges (`gh pr merge --admin`) to bypass branch protection or verification hooks.
- `bypass-hook`: Committing or pushing with verification skipped or redirected: `--no-verify`, `git commit -n`, `--no-gpg-sign`, `-c core.hooksPath=...`, switching off hook managers, or editing hook files or git config. Fix what the hook reports (step 10).
- `machine-specific-paths`: Hard-coding user home directories, drive letters, private scripts, or machine-specific services. Use literal paths inside this checkout and `<run-dir>` (run context).
- `commit-foreign-edits`: Committing changes this run did not make (steps 4, 8, 10).
