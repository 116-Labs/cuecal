---
name: gaal-implement
description: Implements one qualified GitHub issue in 116-Labs/cuecal as a verified change on its own `gaal/` branch off `main` that holds exactly one Conventional Commits commit and passes the profile gates (`uv run ruff check .`, `uv run pytest`). It then writes the run result to `$GAAL_RUN_DIR/result.json`. Use it when a dispatch hands over a repo and an issue number that already passed qualification (Gate 0) and asks for the `implement` step, with or without a resume marker or a merged-PR note. Do not use it to open a PR (`gaal-open-pr`), revise a PR after review (`gaal-revise-pr`), review a PR (`gaal-review-pr`), merge, or deploy, and do not use it for issues that have not been qualified. This step pushes nothing and opens no pull request.
---
<!-- gaal-stamp blueprint=implement@1.8.0 shared=1.5.0 profile=833de6ae33df6d68 generated=2026-10-08 core=94c6e98ee17c8f14 forbidden=9e8b7e5b020ebd1e content=7da02f52a40f6c8c -->

# gaal-implement

This skill takes one qualified issue in `116-Labs/cuecal` and produces a branch off the base with **exactly one commit**. That commit meets the issue's acceptance criteria and passes every profile gate. `gaal-open-pr` takes the branch from there. This step never pushes, never opens a PR and never merges.

## Run context and conventions

- **Repo:** `116-Labs/cuecal`. **Default branch / base:** `main`. The profile names no stacking tool, so every issue gets a single branch off `origin/main` and there is no stacked base.
- **Tracker:** GitHub issues in `116-Labs/cuecal`, read with `gh`.
- **Gates**, in this order, both `required: true`, each run exactly as written with nothing added:
  1. `lint`: `uv run ruff check .`
  2. `test`: `uv run pytest`
- **Preflight:** none (`preflight: []`). **Advisory checks:** the profile names none, so no advisory check runs. The hand-off says so.
- **Install:** the profile names no `install` command, so install nothing. Work, and run the gates, in this checkout itself, where the dependencies are already installed. Do not create a throwaway worktree for the gates, because it would have no dependencies.
- **Branch name:** prefix `gaal/`, then `<N>-<short-kebab-slug-of-the-issue-title>`, for example `gaal/<N>-<slug>`.
- **Commits:** one commit per branch (`single_commit: true`) in Conventional Commits form (`<type>(<scope>): <summary>`, matching history such as `feat(queue): ...`). Attribution policy is `none`: add no `Co-Authored-By` trailer, no "Generated with" line and no other agent or model attribution (`attribution-policy`).
- **Downstream facts** (for the hand-off only; this step acts on none of them): the merge method is `squash`, the merge message comes from the commits (`message_source: commits`), there is no merge queue and no auto-merge, a PR needs 1 approval, unresolved threads do not block the merge, and reviews come from the separate identity `116-labs-gaal-review[bot]`.
- **Attempt limit:** `limits.implement_attempts` = **3**.
- **`<run-dir>`** in the commands below stands for the literal run-directory path from the run context (the value of `GAAL_RUN_DIR`). Write it out literally. Take the run id from the run context too (the value of `GAAL_RUN_ID`). Never write `$GAAL_RUN_DIR`, `$GAAL_RUN_ID`, any other `$` variable, `$(…)` or backticks inside a command. Placeholders such as `<N>`, `<sha>`, `<branch>` and `<path>` are filled in with literal values.

### Headless command rules (apply to every step)

- The only shell commands allowed are `git`, `gh`, `mkdir`, `mv`, `cp`, `ls`, `cat`, `date` and `pwd` (any arguments), plus exactly `uv run ruff check .` and `uv run pytest`. Nothing else runs.
- Run one command per call. Do not chain with `&&`, `;` or `|`, so that no exit status is lost to a pipe or filter (`status-preserved`). Read every command's exit code and act on it.
- Put no `NAME=value` prefixes in front of commands. Do not use `/tmp` or `mktemp`. Scratch files go in `<run-dir>/scratch` (`mkdir -p <run-dir>/scratch`).
- Write files with the file-editing tool, never through shell redirection.
- Every commit message and issue body is written to a file with the file tool and passed by path: `git commit -F <file>`, `gh issue edit ... --body-file <file>`. Never pass them inline.
- Quote every glob: `git branch --list 'gaal/<N>-*'`.
- List uncommitted paths only with `git status --porcelain=v1 --untracked-files=all`.
- Never use `--no-verify`, `git commit -n`, `--no-gpg-sign`, `-c core.hooksPath=…` (or any command naming `core.hooksPath`), `--force`, `-f`, `--admin`, `git add -A`, `git add .` or `git commit -a`. Never edit, move or restore hook files or `.git/config`. To locate the hooks directory, run `git rev-parse --git-path hooks`.
- Read time with `date -u +%Y-%m-%dT%H:%M:%SZ`. Time gates with `date -u +%s` before and after.
- Never wait for interactive input (`ask-mid-run`). If an answer is needed, end `needs-clarification` with the questions.

## Steps

### 0. Start the clock

1. Run `date -u +%Y-%m-%dT%H:%M:%SZ` and keep the value as `started_at`.
2. Run `mkdir -p <run-dir>/scratch`.
3. Keep these values in working memory for the result: `status`, `reason`, `questions`, `attempts` (0 so far), `gates` (empty), `branch` (null) and `commit_sha` (null).

From here on, **every exit path goes to step 13**, including failures.

### 1. Resolve the repo and the issue

1. Run `gh repo view 116-Labs/cuecal --json nameWithOwner,defaultBranchRef`. If the call fails (network, auth, rate limit), end `failed` naming the read (`fail-closed-reads`).
2. Run `gh api repos/116-Labs/cuecal/issues/<N>`.
   - A 404 means the number names no issue: end `failed`.
   - An answer carrying a `pull_request` key means the number names a pull request, not an issue: end `failed`.
   - Any other error ends `failed` naming the read.
   - Never guess another number.
3. Run `git remote get-url origin` and confirm that it points at `116-Labs/cuecal`. If not, end `failed` naming the mismatch.

### 2. Read the whole spec

1. Run `gh api --paginate repos/116-Labs/cuecal/issues/<N>/comments` to read **every** comment, paginated to the end. A failed or truncated listing ends `failed` naming the listing (`complete-listings`, `fail-closed-reads`).
2. Treat the body plus every comment as the spec. Comments that clarify or narrow scope count as spec. When a comment says the body was rewritten, the current body wins.
3. Text between `<!-- gaal:plan-drift -->` and `<!-- /gaal:plan-drift -->` is an earlier implementer's claim, not the author's spec. Everything outside those markers is the author's spec.
4. Extract the acceptance criteria as numbered items, worded as the issue words them.

### 3. Check for drift against the code

Use the search and file-reading tools to check every file, symbol and line the issue references against the current code (after `git fetch origin main`, read what `origin/main` holds). Record each drift: a missing or renamed file or symbol, moved lines, or behaviour that differs from what the issue describes.

### 4. Find existing owners of the capability

Search for code that already owns what the issue adds, for example an existing sink, store, CLI command or pipeline stage. Extend that code rather than building a parallel one. If something new is justified, record why.

### 5. Write the plan (`plan-before-code`)

1. Before any source edit, write a short plan with the file tool to `<run-dir>/plan.md`. It covers:
   - the files to change;
   - the tests to add;
   - for each acceptance criterion, how it will be shown to hold. Every criterion maps to part of the plan.
2. Apply the risky-surface guards while planning:
   - A change that would break a public contract, a schema or a persisted format (for example the SQLite store's schema, a CLI's flags or output, a sink's protocol) without the issue explicitly asking for it is forbidden (`unapproved-breaking-change`). End `needs-human` naming the surface instead of changing it silently.
   - Anything that would require running a deploy, a migration against a shared environment or a publish is never run (`deploy`). Plan to list those commands in the hand-off.
3. If the issue is ambiguous, or the drift recorded in step 3 goes beyond what the plan can safely assume, end `needs-clarification`. Each question must be specific, answerable and name the file or criterion it concerns. Never ask mid-run (`ask-mid-run`).

### 6. Look for resumable prior work

1. Run `git fetch origin main`. A failed fetch ends `failed`.
2. Run `git status --porcelain=v1 --untracked-files=all` and keep the listing.
3. Run `git branch --show-current`, then `git branch --list 'gaal/<N>-*'` and `git worktree list` to find any existing branch or worktree for this issue.
4. For each candidate branch, run `gh pr list --repo 116-Labs/cuecal --head <branch> --state all --limit 100 --json number,state,mergedAt,baseRefName`. A failed call ends `failed` naming the read. A listing of exactly 100 entries may be truncated: end `failed` (`complete-listings`). Never treat a failed read as "no PR".

**Merged PR on the branch, or a merged-PR note was handed over.** After a squash merge, the branch still looks one commit ahead of `main`, but its work is already in `main`.
- Never check out, resume or build on that branch's commits. Re-submitting them is the danger, not the name.
- Start fresh from the fetched base. The name may be reused: run `git switch -C <branch> origin/main` without checking the old branch out first. `gaal-open-pr` judges a branch by where it started, not by its name.
- Implement only what the issue still asks for beyond the merged PR.
- If a handed-over resume marker names a *different* branch, that branch's work still applies. Adopt it by the rule below.

**A resume marker was handed over.** Adopt it only if all three `resume-adoption` conditions hold:
1. The marker's `branch` is checked out (`git branch --show-current`).
2. The branch holds no commit beyond the marker's own base, as the remote has it. Run `git fetch origin <marker-base>`, then check that `git rev-list --count origin/<marker-base>..HEAD` prints `0`. Use the marker's `base`, never this run's freshly chosen base. If the base has moved on since then (`main` included), that is no mismatch: never require HEAD to equal the fetched base, or the base to be an ancestor of HEAD.
3. The paths listed by `git status --porcelain=v1 --untracked-files=all` are exactly the marker's `paths`, file by file.

When all three hold:
- The dirty edits are this issue's work, not stray edits.
- Take the marker's `plan` (read it with `cat <path>` when it names a file) as the starting plan, and save it as `<run-dir>/plan.md`.
- Seed this run's manifest with the marker's `paths`.
- Set `branch` to the marker's branch.
- Go straight to step 9 with a fresh attempt count. There is no install to run, because the profile names none (`install-before-gates`).

A marker that fails any condition is ignored, and the rule below on pre-existing edits applies.

**Pre-existing edits.** If the checkout has uncommitted changes that no adopted marker accounts for, their ownership is unclear. Never commit, revert, stash or reformat them (`absorb-stray-edits`, `commit-foreign-edits`). End `needs-human`. The `reason` lists the dirty paths and, when a marker was handed over, which `resume-adoption` condition failed:
- the marker's branch is not checked out;
- the branch holds commits beyond the marker's base;
- the dirty paths differ from the marker's `paths`.

Gates run in this checkout because no `install` exists, so another person's edits cannot be isolated from them.

**No note, no marker, clean tree.** Resume an existing `gaal/<N>-*` branch only if it is sound:
- no merged PR;
- not on a fork;
- every commit ahead of the merge base authored by this run's identity: compare each email from `git log --format=%ae <merge-base>..HEAD` with `git var GIT_AUTHOR_IDENT`;
- built for this issue.

Otherwise start fresh from `origin/main`.

### 7. Create the branch

1. Never work on `main` (`base-untouched`). If commits were made on `main` by mistake, move them to the feature branch with `git branch <branch>`, then `git reset --keep origin/main` on `main`.
2. To start fresh, run `git switch -c gaal/<N>-<slug> origin/main`, or `git switch -C <branch> origin/main` when reusing a name as step 6 allows. To resume a sound branch, run `git switch <branch>`.
3. Set `branch`.
4. Install nothing: the profile names no `install`, so the checkout's existing environment is used (`install-before-gates`).

### 8. Implement the plan

1. Read each file before changing it, and keep edits minimal and inside the plan's scope.
2. Fix no pre-existing debt outside the change. Record it for the hand-off instead (`unrelated-refactor`).
3. Keep a **manifest**: every path this run creates, modifies or deletes, written down at the moment it is written. A path missing from the manifest does real damage: the change is left behind, or slides into another issue's commit.
4. Add the tests that the plan names for each criterion.
5. If you change `pyproject.toml` or `uv.lock`, note it in the manifest and the hand-off. There is still no profile `install` to run.

### 9. Run the gates, bounded (`gates-green`, `bounded-attempts`, `gates-final-tree`)

One **attempt** runs every gate in profile order on the current tree. For each gate:

1. Run `date -u +%s` and keep it as the start time.
2. Run the gate command exactly, either `uv run ruff check .` or `uv run pytest`.
3. Run `date -u +%s` again. `duration_ms` = (end − start) × 1000.
4. Record `name`, `command`, `exit_code` and `duration_ms`.

Counting attempts:
- The first full gate run is attempt 1. Each re-run after a gate failed is the next attempt.
- A green re-run after a self-review fix (step 12) uses no attempt. If that re-run fails, the fix-and-re-run that follows counts as usual, within the same limit.
- A commit rejected by a hook (step 10) counts like a failing gate.

On a failure, read the output, fix the cause inside the plan's scope (adding any newly written paths to the manifest), and re-run every gate.

**Attempt limit reached.** When attempt **3** fails, stop and end `needs-human`, with the failing gate output summarized in the hand-off. If the work is left uncommitted, first write `<run-dir>/resume.json` with the file tool:

```json
{
  "schema_version": 1,
  "run_id": "<run id from the run context>",
  "issue": <N>,
  "branch": "<branch>",
  "base": "main",
  "paths": ["<every manifest path, which is exactly the dirty tree left behind>"],
  "plan": "<run-dir>/plan.md"
}
```

Write `plan` as `null` if no plan file was saved. Without this marker, the next run would see an untested fix as edits of unclear ownership and refuse it.

Report validation exactly as it happened: which gates ran, which did not, and why. A gate that did not run is never reported as passed (`truthful-report`). Only the runs on the final tree go into `gates`. An earlier red run that was fixed and run again is not listed (`gates-final-tree`).

**Advisory checks.** The profile configures no advisory checks, so none run. State that in the hand-off. A future advisory finding would never block and never count against the limit.

### 10. Stage exactly the manifest and commit once

1. Confirm the current branch is not `main` (`git branch --show-current`).
2. Stage only manifest paths: `git add -- <path> <path> ...`, with each path written out. Use `git rm -- <path>` for a deleted file that `git add` does not record. Never stage wholesale (`explicit-staging`).
3. Verify with `git diff --cached --name-only`: the staged set must equal the manifest exactly (`manifest-matches-staged`).
4. Run `git status --porcelain=v1 --untracked-files=all`. No other change this run is responsible for may remain. Gate caches such as `.pytest_cache` or `.ruff_cache` are never staged; note any that are not ignored.
5. Write the message with the file tool to `<run-dir>/commit-msg.txt`:
   - Subject: `<type>(<scope>): <summary>` in Conventional Commits form, describing the change as a whole.
   - Body: what changed and why.
   - Issue link, by the issue-link rule (`issue-trailer`):
     - **Every** acceptance criterion met: a final line `Closes #<N>`.
     - Otherwise: a line of its own `Refs #<N>`, then a `Deferred:` heading listing each open criterion worded as the issue words it.
     - Never put a closing keyword next to a Deferred list.
   - No attribution lines (`attribution: none`, `attribution-policy`).
   - Because the whole command is checked, never quote a refused flag in an inline message. Always use the file.
6. Run `git commit -F <run-dir>/commit-msg.txt` with hooks enabled.
   - If a hook rejects the commit, read its output, fix what it reports, and commit again. That cycle counts as a gate attempt within the limit of 3.
   - Never skip or redirect the hook (`bypass-hook`).
   - If the fix is beyond this run's remit, end `failed` naming the hook and quoting its output briefly.
7. Record `commit_sha` from `git rev-parse HEAD`.

### 11. Collapse to one commit if needed (`single-commit`)

The regime is `message_source: commits`, so the collapse routine applies. The mode is **in-place**, declared here and never inferred.

1. Run `git merge-base HEAD origin/main` → `<merge-base>`.
2. Run `git rev-list --count <merge-base>..HEAD`. If it prints `0` or `1`, there is nothing to do (idempotent). A resumed sound branch may hold several commits.
3. Check the hard gates, which are never overridden:
   - `origin` is a fork;
   - any commit's author email (`git log --format=%ae <merge-base>..HEAD`) differs from `git var GIT_AUTHOR_IDENT`.

   The `collapse-remote-contained` check is skipped, because implement's in-place collapse pushes nothing. The soft gates (approvals, unresolved threads) cannot fire, because no PR exists yet.

   If a hard gate fires, end `needs-human` naming it. HEAD is untouched.
4. Record `<pre-sha>` from `git rev-parse HEAD` and `<pre-tree>` from `git rev-parse HEAD^{tree}`.
5. Write the collapsed message with the file tool to `<run-dir>/commit-msg.txt`. Describe the change as a whole and drop process commits ("wip", "fix lint"). Keep the branch's `Closes #<N>` or `Refs #<N>` line and any Deferred list exactly as the issue-link rule writes them (`collapse-keeps-link`). Add no attribution.
6. Run `git reset --soft <merge-base>`, never to the base's tip.
7. Run `git diff --cached --quiet`. If it exits 0, the net change is empty: run `git reset --mixed <pre-sha>`, end `needs-human` naming `collapse-content-preserved`, and never commit again.
8. Run `git commit -F <run-dir>/commit-msg.txt` with hooks enabled.
9. Check that `git rev-parse HEAD^{tree}` equals `<pre-tree>`. If not, run `git reset --mixed <pre-sha>` and end `needs-human` naming the changed tree hash (`collapse-content-preserved`). Never retry the commit.
10. Confirm `git rev-list --count <merge-base>..HEAD` is `1` and update `commit_sha`.
11. Record for the report: mode, regime, count before and after, gates that fired, tree hash, and old → new sha.

Nothing is pushed in this step (`push-failure-states` does not arise). If a later step ever pushes, it uses `--force-with-lease=<branch>:<sha>` with the inspected sha, never a bare force (`bare-force-push`), and never admin rights (`admin-bypass`). Never use an interactive rebase.

### 12. Adversarial self-review, drift, and the issue body (`self-reviewed`, `drift-reported`)

**Review.** Review `git show HEAD` as a hostile reviewer who has not read the plan:

- against each acceptance criterion, marking each one met or not met;
- edge cases and error paths;
- behaviour no test covers;
- contradictions between the change's own code, docs and tests;
- anything outside the manifest.

**Fixes.** Fix what you find within this run:
1. Edit, adding the paths to the manifest.
2. Re-run all gates (step 9; a green re-run uses no attempt).
3. Stage the manifest paths explicitly.
4. Update the message file if the criteria status changed (for example `Closes` ↔ `Refs`/Deferred).
5. Run `git commit --amend -F <run-dir>/commit-msg.txt` so the branch keeps one commit.
6. Update `commit_sha`.

Then `gates` holds the runs on this final tree only. Record anything you chose not to fix, and why.

**Drift.** Record every drift from the plan: a file, approach or criterion that ended up different, and why.

**Issue body.** When the plan's scope, approach or criteria changed, update the issue body:
1. Run `gh issue view <N> --repo 116-Labs/cuecal --json body` to get the current body.
2. With the file tool, write `<run-dir>/scratch/issue-body.md`. Keep the original text unchanged, and append a section that opens with the line `<!-- gaal:plan-drift -->` and closes with the line `<!-- /gaal:plan-drift -->`, describing the change. Every changed line falls between the markers. These markers tell `gaal-revise-pr` that the edit is no request, and tell `gaal-review-pr` that the text is the implementer's claim. Text outside them, including a maintainer's later additions, stays the author's.
3. Run `gh issue edit <N> --repo 116-Labs/cuecal --body-file <run-dir>/scratch/issue-body.md`.
4. If the edit fails, end `failed` naming the write. The commit stays on the branch for the retry, because `drift-reported` cannot hold without the edit.

An issue left describing a plan nobody built misleads the reviewer.

### 13. Write the run result and hand off (`run-result-written`) — every exit path

1. Run `date -u +%Y-%m-%dT%H:%M:%SZ` → `finished_at`.
2. With the file tool, write `<run-dir>/result.json.tmp`:

```json
{
  "schema_version": 1,
  "run_id": "<run id from the run context>",
  "blueprint": "implement",
  "blueprint_version": "1.8.0",
  "repo": "116-Labs/cuecal",
  "issue": <N, or null if no positive issue number was dispatched>,
  "pr": null,
  "status": "<done | needs-human | needs-clarification | failed>",
  "reason": "<one sentence, at most 160 characters, naming the decision or action needed; omit only when done>",
  "questions": ["<only for needs-clarification: specific, answerable, each naming a file or criterion>"],
  "attempts": <gate attempts this run consumed; at least 1, which the schema requires even when no gate ran, in which case gates is empty>,
  "gates": [
    {"name": "lint", "command": "uv run ruff check .", "exit_code": 0, "duration_ms": 0},
    {"name": "test", "command": "uv run pytest", "exit_code": 0, "duration_ms": 0}
  ],
  "branch": "<branch or null>",
  "commit_sha": "<40-hex sha or null>",
  "started_at": "<started_at>",
  "finished_at": "<finished_at>"
}
```

Rules for the result:
- Include `reason` unless `status` is `done`. Include `questions` (non-empty) only for `needs-clarification`. Add no other fields.
- `gates` follows `gates-final-tree`: only runs on the final tree, in the order they ran, with real exit codes and durations.
- A `done` result lists both gates with `exit_code` 0 and never a non-zero one.
- A non-`done` result lists the runs on the tree it stopped on, and may include the red run that stopped it.
- A gate that did not run is absent.

3. Run `mv <run-dir>/result.json.tmp <run-dir>/result.json`. Never leave the `.tmp` file behind.
4. The final message (the hand-off) states:
   - each acceptance criterion as met or not met, and whether the commit says `Closes` or `Refs` plus Deferred;
   - the gates that ran and their results, and any that did not run and why;
   - that no advisory checks are configured;
   - the self-review outcome and anything left unfixed;
   - each drift from the plan;
   - whether the issue body was updated;
   - pre-existing debt noticed but not fixed;
   - the collapse report, if one ran;
   - any deploy or migration commands for a human, listed and never run (`deploy`);
   - hand-off notes for whoever works next (new exports, names, CLI flags), quoted word for word.

   The run result gains no field for these.

## Exit states

- `done`: The branch has exactly one commit ahead of `main`, and both required gates (`lint`, `test`) passed on that final tree. `branch`, `commit_sha` and `gates` are set, and `gates` holds at least one run. A partial result uses `Refs #<N>` plus a Deferred list, not a closing keyword. Since both gates are required, a red gate on the final tree can never end `done`. If every gate on the final tree were non-required and failed, the run would end `needs-human` naming them.
- `needs-clarification`: The spec is ambiguous, or the code has drifted from what the issue describes beyond what the plan can safely assume (step 5). `questions` are specific and answerable, and each names its file or criterion.
- `needs-human`, with `reason` saying which case applies and what a human should do:
  - the attempt limit of 3 was reached, with `resume.json` left when the work is uncommitted;
  - a risky-surface guard fired (an unrequested breaking change to a contract, schema or persisted format);
  - the checkout had edits of unclear ownership. `reason` lists the dirty paths and the failed `resume-adoption` condition when a marker was handed over. Edits matching an adopted marker do not count here;
  - every gate on the final tree was non-required and failed;
  - the collapse routine refused on a hard gate, or `collapse-content-preserved` stopped it (an empty net change or a changed tree hash), with the pre-collapse HEAD restored.

  A stacked-rebase conflict also belongs here, but cannot occur without a stacking tool.
- `failed`: An environment or tooling problem:
  - the repo is unreachable;
  - a fetch failed;
  - a tracker read or listing failed or was truncated (`fail-closed-reads`, `complete-listings`);
  - the issue number names no issue (or names a PR);
  - a hook rejection's fix is beyond this run's remit;
  - the plan-drift write to the issue failed (the commit stays on the branch).

  `reason` includes enough to retry. (An install failure would also end here, but the profile names no install.)

## Invariants

Blueprint invariants:
- `plan-before-code`: A written plan (`<run-dir>/plan.md`) exists before the first source edit, and every acceptance criterion maps to part of it (step 5).
- `single-commit`: At hand-off, `git rev-list --count <merge-base>..HEAD` is 1 (steps 10–12).
- `manifest-matches-staged`: The commit's files are exactly the manifest of paths this run wrote (step 10).
- `gates-green`: `uv run ruff check .` and `uv run pytest` ran on the final tree, exited 0, and are both listed in the result (steps 9, 12, 13). The profile has no pending gates.
- `issue-trailer`: The message carries `Closes #<N>` only when every criterion is met; otherwise it carries `Refs #<N>` plus a Deferred list (step 10).
- `bounded-attempts`: Gate-fix cycles stop at 3 attempts. The first run is attempt 1, and a green re-run after a self-review fix uses none. The run then ends `needs-human` (step 9).
- `self-reviewed`: An adversarial review of the final diff ran before hand-off, and its fixes went back through the gates and the single commit (step 12).
- `drift-reported`: Every drift from the plan, and every deploy or migration command for a human, is in the hand-off. A changed plan is written into the issue body between `<!-- gaal:plan-drift -->` and `<!-- /gaal:plan-drift -->` (step 12).
- `resume-adoption`: A resume marker is adopted only when its branch is checked out, `git rev-list --count origin/<marker-base>..HEAD` is 0, and the `git status --porcelain=v1 --untracked-files=all` paths are exactly its `paths`. Otherwise it is ignored (step 6).

Shared invariants:
- `explicit-staging`: Stage only manifest paths, never wholesale (step 10).
- `base-untouched`: Never commit or push to `main` (steps 7, 10).
- `fail-closed-reads`: A failed read is never treated as "nothing there". It ends `failed` naming the read (steps 1, 2, 6).
- `complete-listings`: Comment and PR listings are paginated to the end, or the run stops (steps 2, 6).
- `truthful-report`: The report and result describe only what happened. A gate that did not run is absent (steps 9, 13).
- `status-preserved`: One command per call, no pipes, and every exit code is checked (all steps).
- `attribution-policy`: `attribution: none`, so no attribution in commits (steps 10, 11).
- `run-result-written`: `result.json` is written atomically on every exit path (step 13).
- `gates-final-tree`: `gates` lists only runs on the final tree, in order (steps 9, 12, 13).
- `install-before-gates`: The profile names no `install`, so nothing is installed and gates run in this checkout (steps 7, 9).
- `push-failure-states`: This step pushes nothing. Any push belongs to later steps and their failure rules (step 11).
- `collapse-remote-contained`: Skipped for implement's in-place collapse, which pushes nothing (step 11).
- `collapse-content-preserved`: An empty net change or a changed tree hash restores `<pre-sha>` and ends `needs-human`, with no retry (step 11).
- `collapse-keeps-link`: The collapsed message keeps the issue-link line and the Deferred list unchanged (step 11).

## Forbidden actions

Blueprint:
- `absorb-stray-edits`: Never commit, revert or reformat changes that were in the checkout before the run (step 6).
- `deploy`: Never run deploys, migrations against shared environments or publishes. List the commands in the hand-off (steps 5, 13).
- `unapproved-breaking-change`: Never break a public contract, schema or persisted format unless the issue explicitly asks (step 5).
- `unrelated-refactor`: Never fix pre-existing debt outside scope. Record it instead (steps 8, 9).
- `ask-mid-run`: Never wait for input. End `needs-clarification` with questions (step 5).

Shared:
- `bare-force-push`: Never force-push without `--force-with-lease=<branch>:<sha>` on the inspected sha (step 11).
- `admin-bypass`: Never use `gh pr merge --admin` or any other admin route around protection or hooks.
- `bypass-hook`: Never use `--no-verify`, `git commit -n`, `--no-gpg-sign` or `core.hooksPath` redirection, never disable hook managers, and never edit hook files or `.git/config`. Fix what the hook reports (step 10).
- `machine-specific-paths`: Never hard-code home directories, drive letters, private scripts or services. Use the profile and `<run-dir>`.
- `commit-foreign-edits`: Never commit changes this run did not make (steps 6, 10).
