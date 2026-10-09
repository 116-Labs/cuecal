---
name: gaal-implement
description: Implements one qualified GitHub issue in 116-Labs/cuecal. The result is a verified change on its own `gaal/` branch off `main` (or off a parent branch the dispatch names). The branch holds exactly one Conventional Commits commit with no attribution trailer, and the tree passes the profile gates (`uv run ruff check .`, `uv run pytest`) after `uv sync --locked`. The skill then writes the run result to `result.json` in the run directory. Use it when a dispatch hands over a repo and an issue number that already passed qualification (Gate 0) and asks for the `implement` step, with or without a resume marker or a merged-PR note. Do not use it for issues that have not been qualified. Do not use it to open a pull request (`gaal-open-pr`), revise a PR after review (`gaal-revise-pr`), review a PR (`gaal-review-pr`), merge, publish or deploy. This step pushes nothing and opens no pull request.
---
<!-- gaal-stamp blueprint=implement@1.8.0 shared=1.5.0 profile=6f85855df888e336 generated=2026-10-09 core=94c6e98ee17c8f14 forbidden=9e8b7e5b020ebd1e content=b68fafdadd17ea78 -->

# gaal-implement

Turn one qualified issue into a branch off the base holding **exactly one commit**. That commit meets the issue's acceptance criteria and passes every profile gate. `gaal-open-pr` takes it from there. This is blueprint `implement` version `1.8.0`.

## Run context and command rules

- **Repository:** `116-Labs/cuecal`. Default branch: `main`. Tracker: GitHub issues (`tracker.kind: github`).
- **Inputs from the dispatch:** the issue number `<N>`, an optional parent branch for stacked work, an optional resume marker and an optional merged-PR note. The run context also gives `GAAL_RUN_ID` and `GAAL_RUN_DIR`.
- **Placeholders:** `<run-dir>` stands for the literal path of `GAAL_RUN_DIR`, taken from the run context. Never write `$GAAL_RUN_DIR`, `$GAAL_RUN_ID` or any other `$` variable, `$(…)` or backticks in a command. Write every placeholder (`<N>`, `<sha>`, `<branch>`, `<base>`, `<path>`) out as its literal value.
- **Allowed commands:** `git`, `gh`, `mkdir`, `mv`, `cp`, `ls`, `cat`, `date`, `pwd` and `cd <literal-path>`. Besides those, only these three run, exactly as written:
  - `uv sync --locked`
  - `uv run ruff check .`
  - `uv run pytest`
- **One command per call.** Do not chain with `&&`, `;` or `|`. Do not use shell redirection. Never put `NAME=value` in front of a command.
- **Files:** write every file with the file-writing tool. That covers the plan, the manifest, commit messages, issue bodies, `resume.json` and `result.json.tmp`. Scratch files go in `<run-dir>/scratch/`; create it first with `mkdir -p <run-dir>/scratch`. Never use `/tmp` or `mktemp`. Files in the run directory are never part of the manifest and are never staged.
- **Time:** read it with `date -u +%Y-%m-%dT%H:%M:%SZ`. Time each gate with `date -u +%s` immediately before and immediately after it, as separate calls; `duration_ms` is the difference times 1000.
- **Globs:** quote every glob you pass to a command, for example `git branch --list 'gaal/<N>-*'`.
- **Listing dirty paths:** always use `git status --porcelain=v1 --untracked-files=all`. Never use a form that folds a new directory into one entry.
- **Hooks:** if you need the hooks directory, run `git rev-parse --git-path hooks`. Never run a command that names `core.hooksPath`. Never edit, move or restore a hook file or `.git/config`.
- **No run directory:** if the run context gives no run directory, skip writing `plan.md`, `resume.json` and `result.json`. Put their content in the final message instead.

**Profile facts this skill relies on:**
- **Gates, in order:** `lint` = `uv run ruff check .` (required), then `test` = `uv run pytest` (required).
- **Advisory checks:** none configured. **Preflight:** none (preflight is not an implement concern).
- **Install:** `uv sync --locked` (name `uv`).
- **Commits:** `single_commit: true`, `convention: conventional`, `attribution: none`.
- **Branches:** prefix `gaal/`. Branches are named `gaal/<N>-<slug>`, where `<slug>` is a short kebab-case slug of the issue title.
- **Stacking:** the profile names no stacking tool. Work on a single branch. When the dispatch names a parent branch, use plain git to start the branch from `origin/<parent>`.
- **Merge:** squash, `message_source: commits`, no merge queue, auto-merge on. The single commit's message therefore becomes the permanent record on `main`.
- **Branch protection on `main`:** 1 approving review, code-owner review, stale approvals dismissed, open threads block merge, and the `test` and `zizmor` checks are required.
- **Attempt limit:** `limits.implement_attempts` is **3**.

Record the start time first: run `date -u +%Y-%m-%dT%H:%M:%SZ` and keep the value as `started_at`.

## Steps

### 1. Resolve the repo and the issue

1. Run `gh repo view 116-Labs/cuecal --json nameWithOwner,defaultBranchRef`.
2. Run `gh api repos/116-Labs/cuecal/issues/<N>`.

End `failed` in these cases, naming the cause in `reason`:
- either call errors, times out, hits an auth problem or a rate limit (`fail-closed-reads`);
- the answer is a 404;
- the object carries a `pull_request` key, so the number names a pull request and not an issue.

Never guess a repo or an issue number.

### 2. Read the whole spec

1. Read the issue body from step 1.
2. Read **every** comment: `gh api --paginate repos/116-Labs/cuecal/issues/<N>/comments`. A failed or truncated listing ends `failed` naming the listing (`complete-listings`). Never work from a partial comment list.

Comments that clarify or narrow scope are part of the spec. Comments that open with `**Clarification** —`, `**Clarification (rewrite)** —` or `**Clarification (scope narrow)** —` are load-bearing. When a comment says the body was rewritten, the current body wins. Text between `<!-- gaal:plan-drift -->` and `<!-- /gaal:plan-drift -->` is an earlier implementer's claim, not the author's spec.

List each acceptance criterion as the issue words it.

### 3. Check for drift against the code

Check every file, symbol and line the issue references against the current code, using the file-reading tool and `git grep`. Record each drift: a path that moved, a symbol that was renamed, or behaviour that has already changed.

### 4. Reuse before building

Search (`git grep`, file reads) for existing code that already owns the capability the issue adds. Extend that code rather than building a parallel version. If building something new is justified, record why in the plan.

### 5. Write the plan (`plan-before-code`)

Before any source edit, write a short plan:
- the files to change;
- the tests to add;
- for each acceptance criterion, how it will be shown to hold. Every criterion must map to part of the plan.

When a run directory exists, save the plan as `<run-dir>/plan.md`.

End `needs-clarification` when the issue is ambiguous, or has drifted further than the plan can safely assume. Never wait for an answer (`ask-mid-run`). Put specific, answerable `questions` in the result, each naming the file or criterion it concerns.

These surfaces end `needs-human`, naming the surface, instead of being changed silently:
- a breaking change to a public contract, schema or persisted format that the issue does not explicitly ask for (`unapproved-breaking-change`);
- a deploy, migration or publish step (`deploy`).

### 6. Look for resumable prior work

1. Run `git fetch origin`. A failed fetch ends `failed`.
2. Record the pre-run dirty tree: `git status --porcelain=v1 --untracked-files=all`.
3. List existing branches for this issue:
   - `git branch --list 'gaal/<N>-*'`
   - `git ls-remote --heads origin 'refs/heads/gaal/<N>-*'`
4. For every candidate branch, look up its pull requests in every state before considering a resume:
   `gh pr list --repo 116-Labs/cuecal --head <branch> --state all --json number,state,mergedAt,headRefOid,baseRefName --limit 100`
   A failed read ends `failed` naming it (`fail-closed-reads`). **Never resume a branch whose pull request merged.** After a squash merge, the branch still looks one commit ahead of `main`, but its work is already in `main`. One earlier re-push of such a branch was stopped only by luck, on a stale lease. The danger is the old commits, not the branch name.

Then take the first case that applies.

**Resume marker handed over (`resume-adoption`).** Adopt the marker only when all three of these hold:
1. The marker's `branch` is checked out: `git branch --show-current` prints it.
2. `git rev-list --count origin/<marker-base>..HEAD` prints `0`. `<marker-base>` is the marker's own `base` as the remote has it. Never compare against this run's freshly chosen base. Never require HEAD to equal the fetched base, or the base to be an ancestor of HEAD: a base that has moved on since, `main` included, is no mismatch.
3. The paths listed by `git status --porcelain=v1 --untracked-files=all` are exactly the marker's `paths`.

When all three hold, those edits are this issue's work and are not stray edits:
- take the marker's `plan` as the starting plan;
- seed this run's manifest with the marker's `paths`;
- go straight to step 7's install and then to the gates in step 9, with a fresh attempt count.

The marker may name a different branch from the merged one in a merged-PR note. That branch's work still applies, through this same check.

When any condition fails, ignore the marker and apply the pre-existing-edits rule below. If the tree is dirty, the `reason` must also say which condition failed:
- the marker's branch is not checked out;
- the branch holds commits beyond the marker's base;
- the dirty paths differ from the marker's `paths`.

**Merged-PR note handed over.** Never check out or resume the old local branch the note names, and never build on that branch's commits. Start fresh from the fetched base. You may reuse the scheme's name, even the merged branch's name: recreate it at the fetched base without checking the old branch out, with `git switch -C <branch> origin/<base>`. `gaal-open-pr` judges a branch by where it started, not by its name. Implement only what the issue still asks for beyond that pull request.

**Otherwise:**
- Resume a sound existing branch for `<N>`: its PR is not merged and it has no foreign commits.
- If there is no sound branch, start fresh in step 7.

**Pre-existing edits.** If the recorded pre-run tree is dirty and an adopted resume marker does not account for it, the ownership of those edits is unclear. End `needs-human`, listing the dirty paths in `reason`. Never commit, revert or reformat them (`absorb-stray-edits`, `commit-foreign-edits`).

### 7. Create the branch and install

- **Never work on `main`** (`base-untouched`). Base the branch on `origin/main`, or on `origin/<parent>` for stacked work.
- **Fresh branch:** `git switch -c gaal/<N>-<slug> origin/<base>`. When reusing a merged branch's name, use `git switch -C gaal/<N>-<slug> origin/<base>` instead.
- **Resumed branch:** `git switch <branch>`. A stacked branch that has to be rebased onto its parent and conflicts ends `needs-human`. Abort the rebase with `git rebase --abort` before ending.
- **Isolation:** work in this checkout unless the dispatch asks for a separate worktree. In that case run `git worktree add <run-dir>/worktree -b gaal/<N>-<slug> origin/<base>`, then `cd <run-dir>/worktree`. Leave that worktree in place for the dispatcher.
- **Install (`install-before-gates`):** run `uv sync --locked` in the directory where the gates will run, every time. That includes a resumed branch and an existing environment, because the installed dependencies may be stale. A non-zero exit ends `failed`, naming `uv sync --locked`.

### 8. Implement the plan

Read each file before you change it, and keep edits minimal and inside the issue's scope (`unrelated-refactor`). Record pre-existing debt you notice for the hand-off instead of fixing it.

Keep a manifest of every path you create, modify or delete in `<run-dir>/manifest.txt`, updated as you go. A path missing from the manifest does real damage: in stacked work, the missing change slides into the next issue's commit.

Never run deploys, migrations against shared environments or publishes (`deploy`). Collect any such command for the hand-off.

### 9. Run the gates (`gates-green`, `bounded-attempts`)

If this run changed `pyproject.toml` or `uv.lock`, run `uv sync --locked` again first (`install-before-gates`).

An **attempt** is one pass through both gates, in profile order:
1. `date -u +%s`
2. `uv run ruff check .`
3. `date -u +%s`
4. `date -u +%s`
5. `uv run pytest`
6. `date -u +%s`

For each gate, keep `name`, the exact `command`, `exit_code` and `duration_ms`. Never lose an exit status (`status-preserved`).

**Counting attempts:**
- The first pass is attempt 1.
- Each re-run after a gate failed is the next attempt.
- A green re-run after a self-review fix (step 11) uses no attempt. If that re-run fails, the fix-and-re-run that follows counts as usual, within the same limit.

**On failure:** fix the cause and re-run.

**When attempt 3 fails (the limit):**
1. If the work is left uncommitted and a run directory exists, first write `<run-dir>/resume.json` with the file tool. Without this marker, the next run would see the tree as edits of unclear ownership and refuse it, and a person would have to run the gates and commit by hand.
   ```json
   {"schema_version": 1, "run_id": "<run id>", "issue": <N>, "branch": "<branch>", "base": "<base>", "paths": ["<every manifest path, exactly the dirty tree left behind>"], "plan": "<run-dir>/plan.md or null"}
   ```
2. End `needs-human`, with the failing gate output summarized in the hand-off.

**Advisory checks:** the profile configures none, so none run. Say so in the hand-off. Advisory runs never go into `gates`.

**Reporting:** report validation exactly, whether or not it "mostly ran": which gates ran, which did not, and why.

### 10. Commit once

1. Confirm you are not on `main`: `git branch --show-current`.
2. Stage exactly the manifest, by explicit path (`explicit-staging`): `git add -- <path> <path> …`. Never use `git add -A`, `git add .` or `git commit -a`.
3. Verify with `git diff --cached --name-only` that the staged set equals the manifest (`manifest-matches-staged`).
4. Verify with `git status --porcelain=v1 --untracked-files=all` that no path this run wrote is left unstaged.
5. Write the message to `<run-dir>/scratch/commit-msg.txt` with the file tool.
6. Commit with hooks enabled: `git commit -F <run-dir>/scratch/commit-msg.txt`.

**Message rules:**
- Conventional Commits, for example `feat(<scope>): <summary>` or `fix(<scope>): <summary>`, describing the change as a whole.
- `attribution: none`: no `Co-Authored-By`, no AI or tool attribution, nothing added or dropped on your own initiative (`attribution-policy`).
- Issue link (`issue-trailer`):
  - when every acceptance criterion is met, write `Closes #<N>`;
  - otherwise write `Refs #<N>` on a line of its own, followed by a `Deferred` heading that lists each open criterion as the issue words it.
  - Never put a closing keyword next to a Deferred list.

**Hook rejections:** if a hook rejects the commit, treat it like a failing gate. Fix what it reports and commit again; the fix counts as an attempt within the limit of 3. Never skip or redirect the hook (`bypass-hook`). If the fix is beyond this run's remit, end `failed`, naming the hook and quoting its output briefly.

### 11. Collapse, self-review, report drift

**Collapse (in place).** The regime is `message_source: commits`, so the collapse applies.

1. Run `git merge-base HEAD origin/<base>` to get `<merge-base>`.
2. Run `git rev-list --count <merge-base>..HEAD`. If it prints 0 or 1, there is nothing to collapse.
3. Otherwise check the hard gates. The routine refuses when:
   - `git remote get-url origin` is not `116-Labs/cuecal` (the branch lives on a fork); or
   - any author email from `git log --format=%ae <merge-base>..HEAD` differs from the email in `git var GIT_AUTHOR_IDENT` (never compare with `git config user.email`).

   This in-place collapse pushes nothing, so the `collapse-remote-contained` gate is skipped.
4. Record `<pre-head>` with `git rev-parse HEAD` and `<pre-tree>` with `git rev-parse HEAD^{tree}`.
5. Run `git reset --soft <merge-base>`.
6. Run `git diff --cached --quiet`. Exit 0 means the change nets to nothing: abort.
7. Otherwise commit with `git commit -F <run-dir>/scratch/commit-msg.txt`. The message is written for the whole change, drops process messages such as "wip" or "fix lint", and keeps the issue-link line and any Deferred list worded exactly as before (`collapse-keeps-link`).
8. Check that `git rev-parse HEAD^{tree}` equals `<pre-tree>`. If it differs, abort (`collapse-content-preserved`).

**Abort or refusal:**
- Restore the pre-collapse HEAD: `git reset --soft <pre-head>` for an empty net change, `git reset --keep <pre-head>` for a tree mismatch.
- Never commit again. End `needs-human`, naming the gate that fired.

**Collapse report:** record the mode (in-place), the regime, commit counts before and after, the tree hash, and old → new sha for the hand-off.

**Adversarial self-review (`self-reviewed`).** Do this before anything is pushed. Fixing a lower layer after submission rebases every layer above it, and each force-push dismisses approvals.

Read `git diff origin/<base>...HEAD` as a hostile reviewer who has not read the plan, and check:
- each acceptance criterion;
- edge cases and error paths;
- behaviour no test covers;
- contradictions between the change's code, docs and tests;
- anything outside the manifest.

Fix what you find within this run:
1. Edit and add each path to the manifest.
2. Run the gates again (step 9 counting rules apply).
3. Stage the manifest paths explicitly.
4. Run `git commit --amend -F <run-dir>/scratch/commit-msg.txt`.
5. Re-check `git rev-list --count <merge-base>..HEAD` is 1 (`single-commit`).

Record what you chose not to fix, and why.

**Drift (`drift-reported`).** Record every drift from the plan: a file, approach or criterion that ended up different, and why.

When the scope, approach or criteria changed, update the issue body:
1. Read the current body: `gh issue view <N> --repo 116-Labs/cuecal --json body --jq .body`.
2. Write `<run-dir>/scratch/issue-body.md` with the original text kept verbatim, plus a section that opens with the line `<!-- gaal:plan-drift -->` and closes with the line `<!-- /gaal:plan-drift -->`. Every changed line must fall between the two markers.
3. Run `gh issue edit <N> --repo 116-Labs/cuecal --body-file <run-dir>/scratch/issue-body.md`.

The markers tell `gaal-revise-pr` the edit is not a request, and tell `gaal-review-pr` that the text is the implementer's claim. Text outside them, including a maintainer's later additions, stays the author's.

A failed edit ends `failed`, naming the write. The commit stays on the branch for the retry. Never leave the issue describing a plan nobody built.

### 12. Write the run result (every exit path)

On every exit, including `failed` and early exits:
1. Run `date -u +%Y-%m-%dT%H:%M:%SZ` for `finished_at`.
2. When a commit exists, get the 40-character `commit_sha` from `git rev-parse HEAD`.
3. Write `<run-dir>/result.json.tmp` with the file tool.
4. Run `mv <run-dir>/result.json.tmp <run-dir>/result.json`. Never leave the `.tmp` file behind (`run-result-written`).

```json
{
  "schema_version": 1,
  "run_id": "<GAAL_RUN_ID value from the run context>",
  "blueprint": "implement",
  "blueprint_version": "1.8.0",
  "repo": "116-Labs/cuecal",
  "issue": <N or null if unresolved>,
  "pr": null,
  "status": "done | needs-human | needs-clarification | failed",
  "reason": "<one sentence, at most 160 characters, naming the decision or action needed; omit only when done>",
  "questions": ["<only for needs-clarification: non-empty, each naming a file or criterion>"],
  "attempts": <gate attempts consumed, at least 1; write 1 when the run ended before any gate ran>,
  "gates": [{"name": "lint", "command": "uv run ruff check .", "exit_code": 0, "duration_ms": 0}, {"name": "test", "command": "uv run pytest", "exit_code": 0, "duration_ms": 0}],
  "branch": "<branch or null>",
  "commit_sha": "<40-hex sha or null>",
  "started_at": "<started_at>",
  "finished_at": "<finished_at>"
}
```

**`gates` rule (`gates-final-tree`, `truthful-report`):**
- List only the runs on the final, committed tree, in the order they ran.
- A gate that went red and then green appears once, with its green run.
- Leave out runs on a tree that was later replaced.
- Never list a gate that did not run.
- A `done` result never lists a non-zero `exit_code`, and must hold at least one run.
- A non-`done` result lists the runs on the tree it stopped on, and may include the red run that stopped it.

Add no other fields (`tier`, `model` and `tier_signals` are Gaal's).

**The final message (hand-off)** states:
- each acceptance criterion as met or not met;
- the self-review outcome and what was left unfixed;
- each drift from the plan;
- whether the issue body was updated;
- the collapse report;
- any pre-existing debt or advisory note;
- any deploy or migration commands for a human (never run);
- new exports and names, word for word, so later work in a multi-issue run can pick them up from isolated context.

## Exit states

- `done`: the single commit exists on `gaal/<N>-<slug>` and both required gates exited 0 on the final tree. `branch`, `commit_sha` and `gates` are set, and `gates` holds at least one run. A partial result uses `Refs #<N>` and a Deferred list, never a closing keyword. A final tree whose every gate is non-required and failed would leave `gates` empty and end `needs-human` instead; here both gates are required, so that case does not arise.
- `needs-clarification`: the spec is ambiguous, or the code has drifted from what the issue describes. `questions` are specific and answerable, each naming the file or criterion it concerns.
- `needs-human`: any of these, with `reason` saying which and what a human should do:
  - the limit of 3 implement attempts was reached (with `resume.json` written when the work is uncommitted);
  - a risky-surface guard fired (an unrequested breaking change, a deploy or migration surface);
  - the checkout had edits of unclear ownership (`reason` lists the dirty paths and any failed `resume-adoption` condition);
  - a stacked rebase conflicted;
  - the collapse routine refused on a hard gate, or its content gate aborted, with the pre-collapse HEAD restored.
- `failed`: any of these, with `reason` including enough to retry:
  - the repo is unreachable, or a tracker read or listing failed or was truncated;
  - the number names no issue (a 404, or a pull request);
  - `uv sync --locked` failed;
  - a hook fix is beyond this run's remit;
  - the plan-drift issue edit failed (the commit stays on the branch);
  - a disk or tooling error.

## Invariants

- `plan-before-code`: the written plan exists before the first source edit, and every acceptance criterion maps to part of it (step 5).
- `single-commit`: at hand-off, `git rev-list --count <merge-base>..HEAD` is 1 (steps 10–11).
- `manifest-matches-staged`: the commit's files are exactly the manifest of paths this run wrote (step 10).
- `gates-green`: `lint` and `test` ran on the final tree, exited 0, and are listed in the result (steps 9 and 12).
- `issue-trailer`: `Closes #<N>` only when every criterion is met; otherwise `Refs #<N>` plus a Deferred list (step 10).
- `bounded-attempts`: gate-fix cycles stop at 3 attempts and end `needs-human` (step 9).
- `self-reviewed`: an adversarial review of the final diff ran, and its fixes went back through the gates and the single commit (step 11).
- `drift-reported`: every drift and every human-only deploy or migration command is in the hand-off, and a changed plan is written into the issue body between the plan-drift markers (steps 11–12).
- `resume-adoption`: a resume marker is adopted only when all three conditions hold; otherwise it is ignored (step 6).
- `explicit-staging`: stage only manifest paths, by explicit path (step 10).
- `base-untouched`: never commit or push to `main` or the parent base (steps 7 and 10).
- `fail-closed-reads`: failed reads end `failed` and never become "nothing there" (steps 1, 2 and 6).
- `complete-listings`: comment and pull-request listings are paginated to the end, or the run ends `failed` (steps 2 and 6).
- `truthful-report`: the report and result describe only what happened (steps 9 and 12).
- `status-preserved`: no exit status is lost to a pipe, a filter or a guard (step 9).
- `attribution-policy`: `attribution: none` is followed exactly (step 10).
- `run-result-written`: `result.json` is written atomically on every exit path (step 12).
- `gates-final-tree`: `gates` holds only the runs on the final tree (step 12).
- `install-before-gates`: `uv sync --locked` runs before the gates every time, and again after a dependency-manifest or lockfile change (steps 7 and 9).
- `push-failure-states`: this step pushes nothing. If a push ever happened, a hook rejection would be fixed and other failures never retried.
- `collapse-remote-contained`: skipped for this in-place collapse, which pushes nothing (step 11).
- `collapse-content-preserved`: an empty net change or a tree-hash mismatch aborts the collapse and restores the pre-collapse HEAD (step 11).
- `collapse-keeps-link`: the collapsed message keeps the issue-link line and any Deferred list unchanged (step 11).

## Forbidden actions

- `absorb-stray-edits`: committing, reverting or reformatting changes that were in the checkout before the run.
- `deploy`: running deploys, migrations against shared environments or publishes. List the commands in the hand-off instead.
- `unapproved-breaking-change`: breaking a public contract, schema or persisted format without the issue explicitly asking for it.
- `unrelated-refactor`: fixing pre-existing debt outside the change's scope. Record it instead.
- `ask-mid-run`: waiting on interactive input. End `needs-clarification` with questions instead.
- `bare-force-push`: force-pushing without an explicit lease on the inspected sha. This step never pushes; any force-push anywhere uses `--force-with-lease=<branch>:<sha>` only.
- `admin-bypass`: using admin privileges, such as `gh pr merge --admin`, to get around protection, a queue or a hook.
- `bypass-hook`: `--no-verify`, `git commit -n`, `--no-gpg-sign`, anything touching `core.hooksPath`, turning a hook manager off, editing hooks or `.git/config`, or retrying a rejected commit by another route.
- `machine-specific-paths`: hard-coding home directories, private scripts or services. Use only what the profile and run context give.
- `commit-foreign-edits`: committing changes this run did not make.
