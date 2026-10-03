---
name: gaal-implement
description: Implements one qualified GitHub issue in 116-Labs/cuecal as a verified change on its own `gaal/` branch holding exactly one commit, then writes the run result to `$GAAL_RUN_DIR/result.json`. Use when a dispatch hands you a repo and issue number that already passed qualification and asks for the `implement` step, before any PR exists. Do not use to open a PR, revise a PR after review, review a PR, or merge; those are other steps. Do not use for issues that have not been qualified.
---
<!-- gaal-stamp blueprint=implement@1.7.0 shared=1.4.0 profile=7d4c49f36df8465f generated=2026-10-03 core=e7ca0d74f7c8e378 forbidden=e3a5c6b1ec65f2a7 content=5648b82cee1f17ee -->

# gaal-implement

Take one qualified issue of `116-Labs/cuecal` and produce a branch off `main` holding **exactly one commit**. The commit satisfies the issue's acceptance criteria and passes every profile gate. `open-pr` takes it from there. This run never pushes, never opens a PR and never merges.

## Run context

- Inputs from dispatch: issue number `<N>`. Repository is `116-Labs/cuecal`, base branch is `main` (or a specified parent branch for stacked work), and tracker is GitHub (`tracker.kind: github`).
- Base branch: `main`. Default branch: `main`. Branch prefix: `gaal/` (`branches.prefix: gaal/`).
- Commit convention: conventional (`commits.convention: conventional`). Attribution policy: `none` (`commits.attribution: none`). Single commit per PR (`commits.single_commit: true`).
- Merge configuration: squash (`method: squash`), no queue (`queue: false`), commit message source from commits (`message_source: commits`), auto-merge off (`auto: false`).
- Review policy: 1 required approval, open threads do not block merge (`threads_block_merge: false`), `reviewers: []`, start signal reaction.
- Attempt limit: `limits.implement_attempts` = 3 gate-fix attempts.
- `<run-dir>` stands for the literal run directory path from the run context (the value of `GAAL_RUN_DIR`). The run id is the literal value of `GAAL_RUN_ID`. Write both out literally in every command and file path. Never expand environment variables such as `$GAAL_RUN_DIR` or `$GAAL_RUN_ID` in a command, never put `NAME=value` before a command, and never use `$(...)` or backticks.
- Headless execution: the run cannot ask questions interactively mid-run (`ask-mid-run`). If an issue is ambiguous or blocked, end as `needs-clarification` or `needs-human`.
- Allowed shell commands: `git`, `gh`, `mkdir`, `mv`, `cp`, `ls`, `cat`, `date`, `pwd` with any arguments, plus exactly `uv run ruff check .` and `uv run pytest`. Run one command per call, with no `&&`, `;` or `|` chains. Write files with the file-editing tool, never with shell redirection.
- Preflight & Advisory: the profile defines no preflight commands and no advisory commands.
- Dependencies: the profile defines no `install` command. Install nothing. Work and run the gates in this checkout where dependencies are already installed. A throwaway worktree would have no install, so do not run gates in a throwaway worktree.
- Scratch files and throwaway worktrees live inside `<run-dir>/scratch` and `<run-dir>/worktree` (create `<run-dir>/scratch` with `mkdir -p <run-dir>/scratch`), never in `/tmp`.

## Steps

### 1. Start the clock and initialize tracking

1. Run `date -u +%Y-%m-%dT%H:%M:%SZ` and keep the timestamp as `started_at`.
2. Note the literal run id from the run context and the issue number `<N>`.
3. Run `mkdir -p <run-dir>/scratch`.
4. Initialize an empty gate ledger to record every gate that runs (name, command, exit code, duration in milliseconds).
5. Initialize the attempt counter at 0.
6. From this point forward, all exit paths terminate by atomically writing the run result at step 14 (`run-result-written`).

### 2. Resolve the repository and the issue

1. Run `git remote get-url origin` and verify it points to `116-Labs/cuecal`.
2. Run `gh issue view <N> --repo 116-Labs/cuecal --json number,title,body,state,labels`.
3. If the repository or issue cannot be resolved, or if an API call fails due to network, auth expiration, or rate limits, stop and end as `failed` (`fail-closed-reads`, `status-preserved`). Never guess, and never treat an API error as an empty result.

### 3. Read the issue body and every comment

1. Fetch all issue comments to the end: `gh api repos/116-Labs/cuecal/issues/<N>/comments --paginate` (`complete-listings`). If the call fails, stop and end as `failed` (`fail-closed-reads`).
2. Comments that clarify or narrow scope are part of the specification. Give precedence to comments opening with `**Clarification**`, `**Clarification (rewrite)**`, or `**Clarification (scope narrow)**`.
3. If a comment indicates that the body was rewritten, the current body takes precedence.
4. List all acceptance criteria explicitly and number them for verification.

### 4. Check checkout state and fetch the base

1. Run `git status --porcelain` and `git branch --show-current`. Ignore untracked files located under `<run-dir>`.
2. Any pre-existing dirty edits outside `<run-dir>` belong to someone else (`absorb-stray-edits`, `commit-foreign-edits`): record the dirty paths; never commit, revert, or reformat them.
3. Run `git fetch origin main`. If the fetch fails, end as `failed` (`fail-closed-reads`).
4. If currently on `main` with unpushed commits ahead of `origin/main`, never commit on `main` (`base-untouched`). Move those commits off `main` only if they are unambiguously yours; otherwise end as `needs-human`.

### 5. Check code references and inspect for reuse

1. Check every file, symbol, function, class, and line referenced in the issue against the current code. Record any drift.
2. Search the codebase for existing modules or classes that already own the capability the issue adds, and extend them rather than introducing parallel implementations. If building a new module is justified, document the rationale in the plan.
3. If the issue is ambiguous or the codebase has drifted beyond what can be safely assumed, do not guess or prompt interactively (`ask-mid-run`); end as `needs-clarification` with specific, answerable questions in `questions`, each naming the file or criterion concerned.

### 6. Resolve resumable prior work, merged PRs, and resume markers

1. **Check for prior merged PRs:**
   - Search for pull requests associated with this issue's branch across all states: `gh pr list --repo 116-Labs/cuecal --head <branch> --state all --json number,state,mergedAt`.
   - Never resume a branch whose pull request has already merged. After a squash merge, a local or remote branch still appears 1 commit ahead of the base, but its changes are already part of `main`. Resuming it re-submits work that already merged.
   - When a merged-PR note is handed over in the prompt:
     - Never check out or resume the old local branch it names, and never resume or build on the merged branch's commits.
     - If a handed-over resume marker names a different branch, that branch's work still applies and may be adopted under the resume marker rules below.
     - Otherwise, start fresh from the current base (`origin/main`), fetched now. The fresh branch may keep the branch scheme's name (e.g. recreate it at the fetched base with `git switch -C gaal/<N>-<slug> origin/main` without checking out the old branch). Implement only what the issue still asks for beyond the merged PR.
2. **Without a merged-PR note:**
   - Check for existing local branches for this issue: `git branch --list 'gaal/<N>-*'`. Resume an existing branch only if its state is sound (clean tree, commits cleanly on top of fetched `origin/main`).
3. **Adopt a resume marker:**
   - If the prompt handed over a resume marker (from an earlier implement run that reached the attempt limit with uncommitted work), inspect the checkout.
   - Adopt the marker ONLY when all three conditions hold:
     1. The marker's branch is checked out.
     2. The base matches the marker's base (`main`).
     3. The uncommitted dirty paths in the checkout match the marker's `paths` exactly.
   - When adopted: these edits are this issue's work, not stray edits. Read the marker's saved plan (copying it to `<run-dir>/plan.md` to satisfy `plan-before-code`), place its `paths` into this run's manifest, reset the attempt counter to 0, and go directly to running the gates in step 10.
   - If the marker fails any of the three conditions, ignore the marker. If the checkout then has dirty paths that are not this run's own, end as `needs-human`. In `reason`, list the dirty paths and specify which condition failed: the marker's branch is not checked out, the base differs, or the dirty paths differ from the marker's `paths`.

### 7. Write the plan before any source edits (`plan-before-code`)

1. Write a short, concrete implementation plan:
   - List files to create or modify.
   - List tests to add or update.
   - For every numbered acceptance criterion, specify how it will be verified.
   - Include notes on code references drift and existing code reuse from step 5.
2. Save the plan using the file-editing tool to `<run-dir>/plan.md`. Never edit any source files before `<run-dir>/plan.md` exists (`plan-before-code`).
3. Verify the plan against repository guards. If the plan requires any of the following, end as `needs-human` naming the guard and the required human action:
   - An unapproved breaking change to a public API, CLI contract, configuration structure, SQLite schema, or persisted data format not explicitly requested by the issue (`unapproved-breaking-change`).
   - Running any deployment, release publish, or migration against a shared environment (`deploy`). Record the commands for a human in the hand-off message, but never execute them.

### 8. Create or switch to the isolated feature branch

1. Unless an existing sound branch was resumed in step 6, create a fresh branch from `origin/main`:
   `git switch -c gaal/<N>-<slug> origin/main`
   where `<N>` is the issue number and `<slug>` is a short lowercase kebab-case summary of the issue title (`branches.prefix: gaal/`). (For stacked work, base the branch on the designated parent branch).
2. Never work or commit directly on `main` (`base-untouched`).
3. Dependency installation: the profile names no `install` command, so install nothing. Work in this checkout where dependencies are already installed.

### 9. Implement the plan and track the manifest

1. Read each file before making any edits. Keep all changes minimal, clean, and strictly scoped to the issue.
2. Do not fix pre-existing debt or refactor unrelated code outside the issue's scope (`unrelated-refactor`); note pre-existing findings in the hand-off message instead.
3. Add the unit and integration tests specified in the plan.
4. Maintain a manifest of every file path created, modified, or written at `<run-dir>/manifest.txt` (written and updated with the file tool).
5. Ensure every touched path is recorded in the manifest. A missing path from the manifest causes damage by sliding uncommitted edits into later stacked commits or dropping changes. Never include files this run did not write (`commit-foreign-edits`).

### 10. Run profile gates and fix errors within attempt limits

1. Run each required profile gate in order as separate commands. Increment the attempt counter before each full pass.
   - **Gate 1 (`lint`):**
     1. Run `date -u +%s`.
     2. Run `uv run ruff check .`.
     3. Run `date -u +%s`.
     4. Record the `lint` gate entry: `name: "lint"`, `command: "uv run ruff check ."`, `exit_code`, and `duration_ms` = (end - start) * 1000.
   - **Gate 2 (`test`):**
     1. Run `date -u +%s`.
     2. Run `uv run pytest`.
     3. Run `date -u +%s`.
     4. Record the `test` gate entry: `name: "test"`, `command: "uv run pytest"`, `exit_code`, and `duration_ms` = (end - start) * 1000.
2. Both gates are required (`gates-green`). Run them exactly as written with no additional flags or arguments. Never mask an exit code through pipes or subshells (`status-preserved`). An unrun gate is absent from the result, never marked as passed (`truthful-report`).
3. If any gate fails (non-zero exit code):
   - Inspect the failure output, fix the root cause, update `<run-dir>/manifest.txt`, and re-run all gates from the beginning.
   - Count each cycle against the limit of 3 attempts (`limits.implement_attempts` = 3, `bounded-attempts`).
   - If the 3rd attempt fails, stop and end as `needs-human` with the failing gate output summarized in `reason` (one sentence, at most 160 characters). If uncommitted work remains, write the resume marker in step 11 before exiting.
4. Gates pass only when both `lint` and `test` exit 0 on the final tree with no subsequent modifications.
5. If advisory checks exist, fix only findings introduced by this run; base findings are left untouched and noted in the report (`unrelated-refactor`).

### 11. Write resume marker (on attempt limit exit with uncommitted work)

1. When stopping at the attempt limit (attempt 3 reached) and the working tree has uncommitted edits:
   - Write `<run-dir>/resume.json` using the file-editing tool with:
     - `schema_version`: `1`
     - `run_id`: literal `GAAL_RUN_ID` string
     - `issue`: issue number (integer)
     - `branch`: current branch name
     - `base`: `"main"`
     - `paths`: array of strings matching `<run-dir>/manifest.txt` (must match the dirty working tree exactly; remove any extraneous untracked files so the tree and manifest agree)
     - `plan`: `<run-dir>/plan.md` path (or `null`)
2. Proceed directly to step 14 with status `needs-human`. Do not commit or revert the uncommitted work; Gaal will provide the resume marker to the next implement run.

### 12. Stage explicitly and commit with verification hooks enabled

1. Stage only the paths recorded in `<run-dir>/manifest.txt` using explicit path arguments:
   `git add -- <path1> <path2> ...` (`explicit-staging`).
   Never use `git add -A`, `git add .`, or `git commit -a`.
2. Compare `git diff --cached --name-only` against `<run-dir>/manifest.txt`. The staged set must match the manifest exactly (`manifest-matches-staged`).
3. Check `git status --porcelain` to confirm no other modifications from this run remain unstaged, and all pre-existing foreign files remain untouched.
4. Write the commit message to `<run-dir>/commit-msg.txt` using the file tool:
   - Follow the conventional commit format: `<type>(<scope>): <subject>` in the imperative mood without a trailing period.
   - Describe the overall change rather than process steps ("wip", "fixed lint").
   - Attribution policy is `none` (`commits.attribution: none`): do NOT include AI attribution, `Co-Authored-By`, or tool credits (`attribution-policy`).
   - Follow the issue-link rule (`issue-trailer`):
     - **Full change (all acceptance criteria met):** end with `Closes #N` on its own line.
     - **Partial change (some criteria deferred):** end with `Refs #N` on its own line (never a closing keyword), followed by a `## Deferred` heading listing each open criterion worded exactly as in the issue. Never combine `Closes` with a Deferred list.
5. Commit using `git commit -F <run-dir>/commit-msg.txt`.
6. Verification hooks must remain enabled (`bypass-hook`). Never use `--no-verify`, `git commit -n`, `--no-gpg-sign`, or alter hook paths. If a hook rejects the commit, fix the reported issue, re-stage the manifest, and commit again, counting it as a gate-fix cycle. If the hook error is beyond this run's remit, end as `failed` quoting the hook output. If a fix modifies code, re-run all gates (step 10) before committing.

### 13. Collapse in place and perform adversarial self-review

1. **In-place collapse routine:**
   - Check the commit count ahead of base: `git rev-list --count origin/main..HEAD`.
   - The merge regime is `message_source: commits`, requiring exactly one commit on the branch (`single-commit`).
   - If the count is 1, collapse is already satisfied.
   - If the count is greater than 1, execute in-place collapse:
     - Verify commit authorship: `git log --format=%an origin/main..HEAD`. If any commit was authored by someone else, stop and end as `needs-human`.
     - Record the pre-collapse tree hash: `git rev-parse 'HEAD^{tree}'` and the old head SHA: `git rev-parse HEAD`.
     - Reset softly to base: `git reset --soft origin/main`.
     - Re-commit the unified change: `git commit -F <run-dir>/commit-msg.txt`.
     - Content preservation: verify `git rev-parse 'HEAD^{tree}'` matches the pre-collapse tree hash. If the tree hash differs or the rewrite nets to an empty change, restore with `git reset --hard <old-sha>` and end as `failed`.
     - Never use an interactive rebase, and never merge as admin (`admin-bypass`).
     - Confirm `git rev-list --count origin/main..HEAD` outputs `1`.
     - Record the 40-hex commit SHA with `git rev-parse HEAD` as `commit_sha`.
2. **Adversarial self-review (`self-reviewed`):**
   - Review the complete diff (`git diff origin/main...HEAD`) adversarially, as an independent reviewer who has not seen the plan.
   - Verify each acceptance criterion, inspect edge cases, error handling, test coverage, consistency across code, docstrings, and tests, and ensure no changes exist outside the manifest.
   - Fix any defects found within this run, running all gates (step 10) and updating the single commit (step 12-13). Record any items deliberately not fixed.
3. **Plan drift reporting and issue update (`drift-reported`):**
   - Identify every divergence from the plan in files, approach, or criteria.
   - If the plan changed (scope, approach, or criteria), update the GitHub issue body to keep it aligned with the code:
     Write the updated body to `<run-dir>/scratch/issue-body.md` with the file tool and execute `gh issue edit <N> --body-file <run-dir>/scratch/issue-body.md`.
     Preserve the original issue text, placing all modifications between these exact marker lines:
     `<!-- gaal:plan-drift -->`
     `... drift details / updated criteria ...`
     `<!-- /gaal:plan-drift -->`
     (If issue body editing is unavailable, post a comment containing the opening marker).

### 14. Write the run result atomically on every exit path

1. Run `date -u +%Y-%m-%dT%H:%M:%SZ` and record the timestamp as `finished_at`.
2. Write `<run-dir>/result.json.tmp` using the file-editing tool (`run-result-written`).
3. Ensure the JSON is valid and contains exactly these fields:
   - `schema_version`: `1`
   - `run_id`: literal `GAAL_RUN_ID` string from the run context
   - `blueprint`: `"implement"`
   - `blueprint_version`: `"1.7.0"`
   - `repo`: `"116-Labs/cuecal"`
   - `issue`: issue number (integer), or `null` if unresolved
   - `pr`: `null`
   - `status`: `"done"`, `"needs-human"`, `"needs-clarification"`, or `"failed"`
   - `reason`: required string unless status is `"done"`; exactly one sentence of at most 160 characters describing the required action or decision
   - `questions`: required non-empty array of strings when status is `"needs-clarification"`, omitted otherwise
   - `attempts`: positive integer (>= 1) representing gate-fix cycles consumed (use 1 if stopped before running gates)
   - `gates`: array of gate executions on the final tree, each containing `name`, `command`, `exit_code`, and `duration_ms` (empty array `[]` if none ran)
   - `branch`: branch name string (e.g. `"gaal/<N>-<slug>"`), or `null`
   - `commit_sha`: 40-hex SHA string from `git rev-parse HEAD`, or `null`
   - `started_at`: timestamp string from step 1
   - `finished_at`: timestamp string from step 14
4. Atomically move the file: `mv <run-dir>/result.json.tmp <run-dir>/result.json`. Never leave the `.tmp` file behind.
5. In the final hand-off response (not in `reason`):
   - State the self-review outcome and list each acceptance criterion as met or unmet.
   - List the gates that ran and their status (`truthful-report`).
   - State any plan drift and whether the issue body was updated with `<!-- gaal:plan-drift -->`.
   - List any human-required migration, deploy, or follow-up commands (`deploy`).

## Exit states

- `done`: The single commit exists on the feature branch, passes all required profile gates (`uv run ruff check .`, `uv run pytest`), and `branch`, `commit_sha`, and `gates` are recorded in `result.json`. The hand-off message lists all acceptance criteria as met or unmet (using `Refs #N` with a Deferred list if partial).
- `needs-clarification`: The issue specification is ambiguous or code references have drifted beyond safe assumptions. `questions` contains specific, answerable questions naming the relevant files or criteria. No source changes were committed.
- `needs-human`: The gate-fix attempt limit (3) was reached (leaving `<run-dir>/resume.json` when work is uncommitted); a risky-surface guard fired (`unapproved-breaking-change`, `deploy`); or the checkout contained pre-existing edits of unclear ownership. `reason` states what happened and what a person should do (listing dirty paths and which resume marker adoption condition failed if applicable).
- `failed`: Environment or tooling failure occurred (network error, API failure, dependency issue, hook failure beyond this run's remit, collapse content-preservation failure, or disk error). `reason` provides sufficient detail to retry.

## Invariants

- `plan-before-code`: `<run-dir>/plan.md` exists before the first source edit is made, and every acceptance criterion maps to part of it.
- `single-commit`: At hand-off, the branch holds exactly one commit ahead of `main` (`git rev-list --count origin/main..HEAD` outputs 1).
- `manifest-matches-staged`: The files in the commit match `<run-dir>/manifest.txt` exactly.
- `gates-green`: Every required profile gate (`lint`: `uv run ruff check .`, `test`: `uv run pytest`) ran on the final tree and exited 0.
- `issue-trailer`: The commit message links the issue: `Closes #N` only when every acceptance criterion is met, otherwise `Refs #N` with a `Deferred` heading listing open criteria.
- `self-reviewed`: An adversarial review of the final diff ran before hand-off, and its fixes were verified through the gates and folded into the single commit.
- `drift-reported`: Every drift from the plan is documented in the hand-off message; if the plan changed, the issue body was updated with `<!-- gaal:plan-drift -->` markers.
- `bounded-attempts`: Gate-fix cycles stop at 3 attempts (`limits.implement_attempts`), ending as `needs-human`.
- `explicit-staging`: Stage only paths this run wrote by explicit path arguments from `<run-dir>/manifest.txt`, never staging wholesale.
- `base-untouched`: Never commit or push directly to `main`.
- `fail-closed-reads`: A failed API call or command stops the run; errors are never treated as empty results or missing PRs.
- `complete-listings`: Issue comments and metadata listings are paginated to the end or the run stops.
- `truthful-report`: The report and run result describe only what actually occurred; unrun gates are omitted, never reported as passed.
- `status-preserved`: Command exit codes are never lost or masked by pipes, filters, or subshells.
- `attribution-policy`: The profile attribution policy is `none`; no AI attribution, co-author trailers, or tool credits are added.
- `run-result-written`: `<run-dir>/result.json` is written atomically on every exit path, including failures.

## Forbidden actions

- `absorb-stray-edits`: Committing, reverting, or reformatting changes that were already present in the checkout before the run.
- `deploy`: Executing deploys, publishes, or migrations against shared environments. Return commands in the hand-off for a human instead.
- `unapproved-breaking-change`: Breaking a public API, CLI contract, SQLite schema, or persisted data format without explicit issue instructions.
- `unrelated-refactor`: Fixing pre-existing debt or refactoring code outside the change's direct scope. Record it in the report instead.
- `ask-mid-run`: Waiting for interactive user input during a headless run. End as `needs-clarification` with specific questions instead.
- `bare-force-push`: Force-pushing without `--force-with-lease=<branch>:<sha>`. (This run does not push).
- `admin-bypass`: Merging, pushing, or rewriting with admin privileges (`--admin`) to bypass branch protection, merge queues, or hooks.
- `bypass-hook`: Committing or pushing with hooks skipped (`--no-verify`, `git commit -n`, `--no-gpg-sign`), editing hook files, or altering `core.hooksPath`. Fix hook errors directly.
- `machine-specific-paths`: Hard-coding user home directories, drive letters, or machine-specific paths.
- `commit-foreign-edits`: Committing files or edits not authored by this run.
