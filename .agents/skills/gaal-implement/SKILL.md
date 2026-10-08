---
name: gaal-implement
description: Implements one qualified GitHub issue in 116-Labs/cuecal as a verified change on its own `gaal/` branch off `main` (or off a parent branch named for stacked work). The branch holds exactly one Conventional Commits commit with no attribution trailer, and that commit passes both required profile gates, `uv run ruff check .` and `uv run pytest`. The run writes a plan before it edits code, keeps a manifest of every path it writes and stages only those paths, reviews its own final diff adversarially, and records any drift from the plan on the issue between `<!-- gaal:plan-drift -->` markers. On every exit path, including failures, it writes the run result to `result.json` in the run directory. Use it when a dispatch hands over the repo and an issue number that passed qualification (Gate 0) and asks for the `implement` step, with or without a resume marker or a merged-PR note. Do not use it to open a PR (`gaal-open-pr`), revise a PR (`gaal-revise-pr`), review a PR (`gaal-review-pr`), merge or deploy. This step pushes nothing and opens no pull request.
---
<!-- gaal-stamp blueprint=implement@1.8.0 shared=1.5.0 profile=833de6ae33df6d68 generated=2026-10-08 core=94c6e98ee17c8f14 forbidden=9e8b7e5b020ebd1e content=77bd64177f660f9a -->

# gaal-implement

Take one qualified issue in `116-Labs/cuecal` and produce a branch off the base that holds **exactly one commit**. That commit meets the issue's acceptance criteria and passes every profile gate. `gaal-open-pr` takes the branch from there. This run never pushes, never opens a pull request and never merges.

## Repository facts (from `.gaal/project.yml`)

| Field | Value |
|---|---|
| Repo | `116-Labs/cuecal` (private), remote `origin` |
| Default branch / base | `main`. A stacked run uses the parent branch the dispatch names. |
| Tracker | GitHub issues, read and written with `gh` |
| Gates (in order, both required) | `lint`: `uv run ruff check .` · `test`: `uv run pytest` |
| Pending gates | none |
| Preflight | none (`preflight: []`). Preflight belongs to open-pr and review-pr, not to this step. |
| Advisory checks | none configured |
| Install commands | none configured |
| Commits | one commit per branch (`single_commit: true`), `conventional` convention, attribution `none` |
| Branch prefix | `gaal/`, named `gaal/<N>-<slug>`, where `<slug>` is a short kebab-case form of the issue title |
| Stacking | no stacking tool configured. Use one plain git branch. A stacked branch starts from its parent branch. |
| Merge (later steps, for context) | `squash`, no merge queue, `message_source: commits`, no auto-merge |
| Review policy (later steps, for context) | 1 required approval. Unresolved threads do not block merge. A separate review identity (`116-labs-gaal-review[bot]`) reviews. |
| Attempt limit | `limits.implement_attempts` = **3** |

Because `message_source` is `commits`, this branch's single commit message becomes the permanent squash message. Write it with that in mind.

## Headless command rules

- The run refuses any command outside its allowlist. The allowlist covers `git`, `gh`, `mkdir`, `mv`, `cp`, `ls`, `cat`, `date` and `pwd` with any arguments. It also covers exactly two other commands, each written exactly as shown with nothing added: `uv run ruff check .` and `uv run pytest`. You cannot narrow either gate to a single file or test.
- `<run-dir>` in a command stands for the literal run-directory path from the run context (the value of `GAAL_RUN_DIR`). Take the run id from `GAAL_RUN_ID` in the same way. Never write `$GAAL_RUN_DIR`, `$GAAL_RUN_ID`, any other `$VAR`, `$(…)` or backticks in a command. Never put `NAME=value` in front of a command.
- Write every other `<placeholder>` (for example `<N>`, `<sha>`, `<branch>` or `<base>`) out literally before you run the command.
- Run one command per call. Do not chain commands with `&&`, `;` or `|`. Never use shell redirection. Create and change files with the file tools.
- Scratch files go in `<run-dir>/scratch`, never in `/tmp` or through `mktemp`.
- Quote every glob, for example `'gaal/<N>-*'`.
- Write every commit message and issue body to a file with the file tool, then pass the file: `git commit -F <file>`, `gh issue edit --body-file <file>`. Never write one inline.
- Read the clock with `date -u +%Y-%m-%dT%H:%M:%SZ`. To time a gate, run `date -u +%s` as a separate command just before the gate and again just after it.
- The profile names no `install` command, so this run installs nothing (`install-before-gates`). The work and both gates run in this checkout itself, where the dependencies are already installed. Never move gate runs into a throwaway worktree, because a fresh worktree has no dependencies.
- If you need the hooks directory, run `git rev-parse --git-path hooks`. Never name `core.hooksPath` in any command, even one that only reads it. Never edit, move or restore a hook file or `.git/config`.
- List uncommitted paths file by file with `git status --porcelain=v1 --untracked-files=all`. Leave out any path inside the run directory: it holds this run's own scratch and is never staged.

## Steps

### 0. Start

1. Run `date -u +%Y-%m-%dT%H:%M:%SZ` and keep the output as `started_at`.
2. Run `mkdir -p <run-dir>/scratch`.
3. Hold these values for the whole run:
   - `attempts = 0`.
   - An empty **manifest**: every path this run writes outside the run directory.
   - An empty **gate log**.
   - A note of the **exit path**.
4. If any step below ends the run, go straight to step 12 and write the result. Never stop without writing it (`run-result-written`).

### 1. Resolve the repo and the issue

1. Run `gh repo view 116-Labs/cuecal --json nameWithOwner,defaultBranchRef`.
2. Run `git remote get-url origin` and confirm that the remote is `116-Labs/cuecal`.
3. Run `gh api repos/116-Labs/cuecal/issues/<N>`.

End the run `failed` and name the problem in these cases:
- The repo is unreachable.
- The remote does not match.
- The issue read fails for any reason (auth, rate limit, network), or answers 404. This is `fail-closed-reads`: a failed call never counts as "no issue".
- The answer carries a `pull_request` field, so the number names a pull request and not an issue.

Never guess a repo or an issue number.

### 2. Read the issue body and every comment

1. Run `gh api --paginate repos/116-Labs/cuecal/issues/<N>/comments`. Paginate to the end; a truncated or failed listing ends the run `failed` and names the listing (`complete-listings`).
2. Treat comments that clarify or narrow scope as part of the spec.
3. When a comment says the body was rewritten, the current body wins.
4. Extract the acceptance criteria, worded exactly as the issue words them.

### 3. Check references against the current code

1. Run `git fetch origin <base>`.
2. Check every file, symbol and line the issue references against the code at `origin/<base>`.
3. Record each mismatch as **drift**: the path or symbol is gone, renamed or moved, or the line contents differ.

### 4. Find the existing owner of the capability

1. Search the codebase for code that already does what the issue adds. Examples: an existing CLI command group, store module, sink adapter, pipeline stage or dedupe tier.
2. Plan to extend that code rather than build a parallel one.
3. If new code is truly justified, record why in the plan.

### 5. Write the plan (`plan-before-code`)

1. Before the first source edit, write a short plan. Cover:
   - the files to change;
   - the tests to add;
   - for each acceptance criterion, how the change will show that it holds.
   Every criterion must map to part of the plan.
2. Save the plan with the file tool as `<run-dir>/plan.md`.

End the run `needs-clarification` in these cases:
- The issue is ambiguous.
- The code has drifted beyond what the plan can safely assume.

In that case, write `questions` that are specific and answerable, each naming the file or criterion it concerns. Never wait for an answer (`ask-mid-run`): a headless run cannot ask.

**Guards for risky surfaces.** End the run `needs-human` instead of changing these surfaces silently:
- a public contract, such as the `cuecal` CLI's commands and flags or the Sink protocol;
- a persisted format or schema, such as the pending-approval SQLite store;
- deploy configuration.

The exception is an issue that explicitly asks for the change. A breaking change the issue does not ask for is `unapproved-breaking-change`.

### 6. Check the tree and look for prior work

#### 6a. Dirty tree

1. Run `git status --porcelain=v1 --untracked-files=all`.
2. Run `git branch --show-current`.

#### 6b. Resume marker handed over (`resume-adoption`)

Adopt the marker only when all three of these conditions hold:

1. **The marker's `branch` is checked out.** `git branch --show-current` prints it.
2. **The branch holds no commit beyond the marker's base.**
   - Run `git fetch origin <marker-base>`, then `git rev-list --count origin/<marker-base>..HEAD`. The output must be `0`.
   - Count against the marker's own `base` as the remote has it. Never count against this run's freshly chosen base.
   - A base that has moved on since the marker was written still passes. Never require that HEAD equals the fetched base, or that the base is an ancestor of HEAD.
3. **The dirty paths match.** The uncommitted paths from `git status --porcelain=v1 --untracked-files=all` are exactly the marker's `paths`, file by file.

When the marker is adopted:
- Those edits are this issue's work, not stray edits.
- Take the marker's `plan` file as the starting plan, and copy it into `<run-dir>/plan.md` if it lives elsewhere.
- Put the marker's `paths` into this run's manifest.
- Reset `attempts` to 0.
- Skip to step 9 (gates). This step installs nothing, because the profile names no `install` command.

When any condition fails, ignore the marker and apply the rule in 6c.

#### 6c. Edits of unclear ownership

These are any uncommitted paths that an adopted marker does not cover. Never commit, revert, stash or reformat them (`absorb-stray-edits`, `commit-foreign-edits`). End the run `needs-human`. The `reason` lists the dirty paths and, when a marker was handed over, which condition failed:
- the marker's branch is not checked out; or
- the branch holds commits beyond the marker's base; or
- the dirty paths differ from the marker's `paths`.

#### 6d. Existing branches and worktrees for this issue

1. Run `git branch --list 'gaal/<N>-*'`.
2. Run `git ls-remote --heads origin 'gaal/<N>-*'`.
3. Run `git worktree list`.
4. For every candidate branch, look up its pull requests in every state before you resume it:
   `gh pr list --repo 116-Labs/cuecal --head <branch> --state all --json number,state,mergedAt,headRefOid,baseRefName --limit 100`

   If the call fails, end the run `failed` and name the read. If it returns 100 entries, the listing may be truncated: end the run `failed` (`complete-listings`).
5. **Never resume a branch whose pull request merged.** After a squash merge, the branch still looks one commit ahead of `main`, but its work is already in `main`. Re-pushing it re-submits merged work; one such re-push failed only by luck, on a stale lease.

#### 6e. Merged-PR note handed over

1. Never check out or resume the old local branch that the note names, and never build on its commits.
2. If a handed-over resume marker names a *different* branch, that branch's work still applies, adopted by the rule in 6b.
3. Otherwise, start fresh from the base, fetched now. You may reuse the scheme's name, even the merged branch's name. The danger is the old commits, not the name. Recreate the name at the fetched base without checking out the old branch:
   `git switch -C <branch> origin/<base>`

   open-pr judges a branch by where it started, not by its name.
4. Implement only what the issue still asks for beyond the merged PR.

#### 6f. Otherwise

Resume a sound branch for this issue: one with no merged PR and no foreign commits. If there is none, start fresh.

### 7. Create the branch

1. Run `git fetch origin <base>`.
2. Run `git switch -c gaal/<N>-<slug> origin/<base>`. If you are recreating an existing name per step 6, use `git switch -C …` instead.

Rules for this step:
- `<base>` is `main`, unless the dispatch names a parent branch for stacked work. A stacked branch starts from `origin/<parent>`.
- No stacking tool is configured, so use plain git. If a rebase onto a stacked parent conflicts, end the run `needs-human` and name the conflicting paths.
- Never commit to `main` or to the base branch (`base-untouched`). If you find you are on the base with work committed, move the commits to the feature branch, then run `git reset --hard origin/<base>` on the base. Do this only when the base has no uncommitted edits.
- Work in this checkout, not in a separate worktree. No `install` command is named, so the dependencies live only here.

### 8. Implement the plan

1. Read each file before you change it.
2. Keep edits minimal and within the issue's scope. Pre-existing debt you notice goes in the report, not in the diff (`unrelated-refactor`).
3. Add the tests the plan names.
4. Record **every** path you create, modify or delete in the manifest as you go. In stacked work, a path missing from the manifest slides into the next issue's commit, so the manifest must be complete.
5. Never run deploys, migrations against shared environments, or publishes (`deploy`). Collect any such command a human must run for the hand-off.

### 9. Run the gates (`gates-green`, `bounded-attempts`)

**Install.** No `install` command is named, so nothing is installed before the gates, not even after a dependency manifest or lockfile changes (`install-before-gates`). If this run changes `pyproject.toml` or `uv.lock`, say so in the hand-off.

**Run the gates.** Run them in this order, each timed:

1. `date -u +%s`
2. `uv run ruff check .`
3. `date -u +%s`
4. `date -u +%s`
5. `uv run pytest`
6. `date -u +%s`

For each gate, record `name`, `command` (exactly as written above), `exit_code` and `duration_ms`, where `duration_ms` is (after − before) × 1000. Never estimate a duration or copy it from elsewhere. Never let a filter or wrapper hide an exit code (`status-preserved`).

**Count attempts.**
- The first gate run is attempt 1.
- Each re-run after a gate failed is the next attempt.
- A green re-run after a self-review fix (step 11) uses no attempt. If that re-run fails, the fix-and-re-run that follows counts as usual, within the same limit.

**On a failure:** fix the cause and re-run, until both gates exit 0 or `attempts` reaches **3**.

**When attempt 3 fails:**

1. If the work is uncommitted, first write a resume marker to `<run-dir>/resume.json` with the file tool:

   ```json
   {
     "schema_version": 1,
     "run_id": "<GAAL_RUN_ID value>",
     "issue": <N>,
     "branch": "gaal/<N>-<slug>",
     "base": "<base>",
     "paths": ["<every manifest path, exactly the dirty tree left behind>"],
     "plan": "<run-dir>/plan.md"
   }
   ```

   Use `null` for `plan` when no plan was saved. Without this marker, the next run would see the untested fix as edits of unclear ownership and refuse it, and a person would have to run the gates and commit by hand.
2. End the run `needs-human`, with the failing gate output summarized.

**Advisory checks.** None are configured. Record "no advisory checks configured" in the hand-off. An advisory check never blocks and never counts as an attempt.

**Non-required gates.** Both gates are required, so the "every gate non-required and failed" case cannot arise here.

### 10. Commit exactly the manifest (`single-commit`, `manifest-matches-staged`, `issue-trailer`)

1. Run `git branch --show-current` and confirm that you are on `gaal/<N>-<slug>`, never on the base.
2. Stage only the manifest paths, by name: `git add -- <path> <path> …` (`explicit-staging`). Never use `git add -A`, `git add .` or `git commit -a`.
3. Check the staged set:
   - `git diff --cached --name-only` must equal the manifest exactly.
   - `git status --porcelain=v1 --untracked-files=all` must show no other change this run is responsible for.

   If a manifest path is missing, add it. If a path outside the manifest is staged, unstage it with `git restore --staged -- <path>`.
4. Write the message with the file tool to `<run-dir>/scratch/commit-msg.txt`:
   - A Conventional Commits subject: `<type>(<scope>): <summary>`, for example `feat(queue): …` or `fix(sinks): …`.
   - A body that describes the change as a whole.
   - The issue link on a line of its own:
     - `Closes #<N>` only when **every** acceptance criterion is met.
     - Otherwise `Refs #<N>`, followed by a `Deferred` heading that lists each open criterion, worded as the issue words it.
   - Never put a closing keyword next to a Deferred list.
   - Attribution is `none`: add no `Co-Authored-By`, "Generated with" or any other attribution line (`attribution-policy`).
5. Run `git commit -F <run-dir>/scratch/commit-msg.txt` with hooks enabled. A hook that rejects the commit is handled like a failing gate: fix what it reports and commit again, counting the attempt (`bypass-hook`). Never use `--no-verify`, `git commit -n`, `--no-gpg-sign` or any change to where git finds hooks. If the fix is beyond this run's remit, end the run `failed`, name the hook and quote its output briefly.

### 11. Collapse, self-review, report drift

#### 11a. Collapse in place

Use the shared single-commit routine, in-place mode. The regime applies, because `message_source` is `commits`.

1. Run `git fetch origin <base>`, then `git merge-base HEAD origin/<base>`, giving `<merge-base>`.
2. Run `git rev-list --count <merge-base>..HEAD`. A result of 0 or 1 means nothing to do.
3. When the count is more than 1, collapse:
   1. **Hard gate: authorship.**
      - Run `git var GIT_AUTHOR_IDENT` to get this run's author email. Never use `git config user.email`.
      - Run `git log --format='%H %ae' <merge-base>..HEAD`.
      - Any commit by another author means **refuse**.
   2. **Hard gate: fork.** If the branch lives on a fork, **refuse**.
   3. The `collapse-remote-contained` gate does not apply. This collapse pushes nothing.
   4. The soft gates (approvals that would be dismissed, unresolved threads) cannot fire, because no PR exists yet. Record that in the report.
   5. Record the pre-collapse state:
      - `git rev-parse HEAD` gives `<pre-collapse-head>`.
      - `git rev-parse HEAD^{tree}` gives `<pre-tree>`.
   6. Run `git reset --soft <merge-base>`. Never reset to the base's tip: a base that moved on would make the new commit revert its newer changes.
   7. Check that the net change is not empty: `git diff --cached --quiet` must exit 1. If it exits 0, the change is empty: **abort**.
   8. Write the collapsed message to the file and run `git commit -F <run-dir>/scratch/commit-msg.txt`.
      - Keep the issue-link line (`Closes #<N>` or `Refs #<N>`) and any Deferred list exactly as the issue-link rule writes them (`collapse-keeps-link`).
      - Drop process messages such as "wip" or "fix lint".
      - Add no attribution.
   9. Check the tree: `git rev-parse HEAD^{tree}` must equal `<pre-tree>`. Otherwise **abort** (`collapse-content-preserved`).
4. **On refuse or abort:** run `git reset --soft <pre-collapse-head>` to restore the pre-collapse HEAD. Never commit again. End the run `needs-human`, naming the gate that fired.
5. Note the old and new sha, the commit count before and after, and the tree hash for the report.

#### 11b. Adversarial self-review (`self-reviewed`)

This is the last review before anything is pushed. A fix after submission would force-push and dismiss approvals.

1. Run `git show HEAD`.
2. Read the final diff as a hostile reviewer who has not read your plan. Check:
   - each acceptance criterion;
   - edge cases and error paths;
   - behaviour with no covering test;
   - contradictions between the change's code, docs and tests;
   - anything outside the manifest.
3. Fix what you find in this run:
   1. Edit the files and add any new paths to the manifest.
   2. Re-run both gates. A green re-run uses no attempt (step 9 says how failures count).
   3. Stage the fixed paths by name.
   4. Run `git commit --amend -F <run-dir>/scratch/commit-msg.txt`, updating the message if the change's scope moved.
   5. Repeat the `single-commit` check: `git rev-list --count <merge-base>..HEAD` must be 1.
4. Record what you chose not to fix, and why.

#### 11c. Final-tree check

1. The gate runs recorded for the result must be runs on this final committed tree. If anything changed after the last green run, run both gates again (`gates-final-tree`).
2. Run `git show --name-only --format= HEAD`. The output must equal the manifest (`manifest-matches-staged`).

#### 11d. Drift (`drift-reported`)

1. Record every drift from the plan: each file, approach or criterion that ended up different, and why. Include the reference drift found in step 3.
2. When the plan changed in scope, approach or criteria, update the issue body:
   1. Run `gh issue view <N> --repo 116-Labs/cuecal --json body` to read the current body.
   2. Write a new body with the file tool to `<run-dir>/scratch/issue-body.md`. Keep the original text unchanged and append a section that:
      - opens with the line `<!-- gaal:plan-drift -->`;
      - describes the change;
      - closes with the line `<!-- /gaal:plan-drift -->`.

      Every changed line must fall between the two markers. Gaal may write under the maintainer's login, so the markers are what tell revise-pr that the edit is no request, and tell review-pr that the text is the implementer's claim, not the author's spec.
   3. Run `gh issue edit <N> --repo 116-Labs/cuecal --body-file <run-dir>/scratch/issue-body.md`.

   If the edit fails, end the run `failed` and name the write. The commit stays on the branch for the retry.

### 12. Write the run result and hand off (`run-result-written`, `truthful-report`)

1. Run `date -u +%Y-%m-%dT%H:%M:%SZ` and keep the output as `finished_at`.
2. Run `git rev-parse HEAD` to get `commit_sha`. Use `null` when no commit of this run exists.
3. Write `<run-dir>/result.json.tmp` with the file tool. Follow the field rules below.
4. Run `mv <run-dir>/result.json.tmp <run-dir>/result.json`. Never leave the `.tmp` file behind.

```json
{
  "schema_version": 1,
  "run_id": "<GAAL_RUN_ID value>",
  "blueprint": "implement",
  "blueprint_version": "1.8.0",
  "repo": "116-Labs/cuecal",
  "issue": <N>,
  "pr": null,
  "status": "done",
  "attempts": 1,
  "gates": [
    {"name": "lint", "command": "uv run ruff check .", "exit_code": 0, "duration_ms": 4000},
    {"name": "test", "command": "uv run pytest", "exit_code": 0, "duration_ms": 21000}
  ],
  "branch": "gaal/<N>-<slug>",
  "commit_sha": "<40-hex sha>",
  "started_at": "<started_at>",
  "finished_at": "<finished_at>"
}
```

**Field rules:**

- **`status`** is one of the exit states below.
  - Every status except `done` adds `reason`: one sentence of at most 160 characters naming the decision or action needed.
  - `needs-clarification` also adds `questions`, a non-empty array.
- **`attempts`** is the number of gate attempts this run consumed. The schema requires a positive integer, so write `1` when the run stopped before its first gate run.
- **`gates`** lists only the runs on the final tree, in the order they ran, each gate once with its last run (`gates-final-tree`).
  - An earlier red run that was fixed is not listed.
  - A gate that did not run is absent, never listed as passed.
  - A `done` result lists both gates, each with `exit_code` 0, and at least one run.
  - A result that is not `done` lists the runs on the tree it stopped on, and may include the red run that stopped it. Use `[]` when no gate ran.
- **`branch`** is `null` when no branch was created.
- **Never add** `review`, `push`, `tier`, `model` or `tier_signals`.

**Final message (the hand-off).** Report:

- Each acceptance criterion, marked met or not met.
- Which gates ran, which did not, and why. Report validation that "mostly ran" exactly.
- The self-review outcome, including what you chose not to fix.
- Each drift from the plan.
- Whether the issue body was updated.
- The collapse report: count before and after, old → new sha, tree hash, and which gates fired.
- Pre-existing debt you noticed but did not fix.
- Any change to dependency manifests or lockfiles.
- Any deploy or migration command for a human to run (`deploy`).
- Hand-off notes for any later issue in a multi-issue run (new exports, renamed symbols), written word for word.

The run result gains no field for any of these.

## Exit states

- **`done`:** the single commit exists on `gaal/<N>-<slug>`, and both required gates passed on the final tree. `branch`, `commit_sha` and `gates` (at least one run) are set. A partial result uses `Refs #<N>` and a Deferred list, never `Closes`.
- **`needs-clarification`:** the spec is ambiguous, or the code has drifted from what the issue describes beyond what the plan can safely assume. `questions` are specific and answerable, each naming its file or criterion.
- **`needs-human`:** one of the following happened. `reason` says which and what a human should do.
  - The attempt limit of 3 was reached. A resume marker was left when the work was uncommitted.
  - A risky-surface guard fired.
  - The checkout had edits of unclear ownership. `reason` lists the paths and any failed `resume-adoption` condition.
  - A stacked rebase conflicted.
  - Every gate on the final tree was non-required and failed. This cannot arise with this profile.
  - The collapse refused (a hard gate fired) or aborted on its content gate (an empty net change, or a changed tree hash), with the pre-collapse HEAD restored.
- **`failed`:** one of the following happened. `reason` includes enough to retry.
  - The repo was unreachable, or an issue or comment read failed (`fail-closed-reads`).
  - The issue number names no issue.
  - A listing was truncated.
  - A tooling or environment problem stopped the run, such as a broken environment or a full disk.
  - A hook rejected the commit, and its fix is beyond this run's remit.
  - The plan-drift edit to the issue failed. The commit stays on the branch.

## Invariants

- `plan-before-code`: a written plan (`<run-dir>/plan.md`) exists before the first source edit, and every acceptance criterion maps to part of it (step 5).
- `single-commit`: at hand-off, `git rev-list --count <merge-base>..HEAD` is 1 (steps 10–11).
- `manifest-matches-staged`: the files in the commit are exactly the manifest of paths this run wrote (steps 8, 10, 11c).
- `gates-green`: both required gates ran on the final tree, exited 0, and are listed in the result. There are no pending gates (steps 9, 11c).
- `issue-trailer`: the commit message carries `Closes #<N>` only when every criterion is met. Otherwise it carries `Refs #<N>` and a Deferred list (step 10).
- `bounded-attempts`: gate-fix cycles stop at 3 attempts, then the run ends `needs-human` (step 9).
- `self-reviewed`: an adversarial review of the final diff ran, and its fixes went back through the gates and the single commit (step 11b).
- `drift-reported`: every drift and every deploy or migration command is in the hand-off. A changed plan is written into the issue between the `gaal:plan-drift` markers (step 11d).
- `resume-adoption`: a resume marker is adopted only when all three conditions hold (step 6b).
- `explicit-staging`: stage only manifest paths, by name (step 10).
- `base-untouched`: never commit to `main` or to the base (steps 7, 10).
- `fail-closed-reads`: a failed read ends the run `failed`. It never counts as "nothing there" (steps 1, 2, 6d).
- `complete-listings`: comment and PR listings are paginated to the end, or the run ends `failed` (steps 2, 6d).
- `truthful-report`: the result and hand-off describe what actually happened (step 12).
- `status-preserved`: no exit code is lost to a pipe, filter or guard (step 9).
- `attribution-policy`: attribution is `none`, so the commit carries no attribution line (step 10).
- `run-result-written`: `result.json` is written atomically on every exit path (step 12).
- `gates-final-tree`: `gates` lists only the runs on the final tree, in order, with no advisory runs (steps 9, 11c, 12).
- `install-before-gates`: the profile names no install, so nothing is installed and the gates run in this checkout (steps 7, 9).
- `push-failure-states`: this step never pushes. If a later step's push fails, it follows the shared rule.
- `collapse-remote-contained`: skipped, because this in-place collapse pushes nothing (step 11a).
- `collapse-content-preserved`: an empty net change or a changed tree hash aborts the collapse and restores the pre-collapse HEAD (step 11a).
- `collapse-keeps-link`: the collapsed message keeps the issue-link line and the Deferred list unchanged (step 11a).

## Forbidden actions

- `absorb-stray-edits`: committing, reverting or reformatting edits that were in the checkout before the run.
- `deploy`: running deploys, migrations against shared environments, or publishes. List them for a human instead.
- `unapproved-breaking-change`: breaking a public contract, schema or persisted format without the issue explicitly asking for it.
- `unrelated-refactor`: fixing pre-existing debt outside the change's scope. Record it instead.
- `ask-mid-run`: waiting on interactive input. End `needs-clarification` with questions instead.
- `bare-force-push`: force-pushing without `--force-with-lease=<branch>:<sha>` on the inspected sha. This step pushes nothing at all.
- `admin-bypass`: using `gh pr merge --admin` or any admin route around protection.
- `bypass-hook`: using `--no-verify`, `git commit -n`, `--no-gpg-sign`, any change to where git looks for hooks, disabling a hook manager, editing a hook file or `.git/config`, or retrying a rejected commit by another route.
- `machine-specific-paths`: hard-coding a home directory, drive letter, private script or private service.
- `commit-foreign-edits`: committing changes this run did not make. Never use `git add -A`, `git add .` or `git commit -a`.
