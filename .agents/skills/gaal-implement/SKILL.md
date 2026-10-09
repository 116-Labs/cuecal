---
name: gaal-implement
description: Implements one qualified GitHub issue in 116-Labs/cuecal. The result is a verified change on its own `gaal/` branch, cut from `main` or from a parent branch that the dispatch names. The branch holds exactly one Conventional Commits commit with no attribution trailer. The tree must pass the profile gates (`uv run ruff check .` and `uv run pytest`) after `uv sync --locked`. The skill then writes the run result to `result.json` in the run directory. Use it when a dispatch hands over a repo and an issue number that already passed qualification (Gate 0) and asks for the `implement` step, with or without a resume marker or a merged-PR note. Do not use it for issues that have not been qualified. Do not use it to open a pull request (gaal-open-pr), revise a PR (gaal-revise-pr), review a PR (gaal-review-pr), merge, publish or deploy. This step pushes nothing and opens no pull request.
---
<!-- gaal-stamp blueprint=implement@1.8.0 shared=1.5.0 profile=6f85855df888e336 generated=2026-10-09 core=94c6e98ee17c8f14 forbidden=9e8b7e5b020ebd1e content=bccfe729012e221b -->

# gaal-implement

This skill implements blueprint `implement`, version `1.8.0`, for `116-Labs/cuecal`.

- **Input:** one issue that passed qualification (Gate 0).
- **Output:** a branch off the base that holds **exactly one commit**. That commit meets the issue's acceptance criteria and passes every profile gate.
- **Next step:** `gaal-open-pr` takes the branch from there.

This skill never pushes and never opens a pull request.

## Project facts (from `.gaal/project.yml`)

| Field | Value |
|---|---|
| Repo | `116-Labs/cuecal` (public) |
| Default branch | `main` |
| Tracker | GitHub issues (`tracker.kind: github`), read with `gh` |
| Install | `uv sync --locked` (name `uv`) |
| Gates, in order | `lint`: `uv run ruff check .` (required). `test`: `uv run pytest` (required) |
| Preflight | none. Implement runs no preflight |
| Advisory checks | none named in the profile |
| Commits | one commit (`single_commit: true`), `convention: conventional` (Conventional Commits), `attribution: none` |
| Branch prefix | `gaal/`. Name branches `gaal/<N>-<short-kebab-slug>`: `<N>` is the issue number and the slug comes from the issue title |
| Stacking | No stacking tool is named. Use a single branch. A stacked branch starts from the parent branch the dispatch names, using plain `git` |
| Merge (context only) | squash, `message_source: commits`, no merge queue, auto-merge on. The branch's one commit message becomes the message that lands on `main` |
| Review and protection (context only) | 1 required approval. Open threads block merge. Stale approvals are dismissed. Code-owner reviews are required. Required checks are `test` and `zizmor`. The reviewer is a separate identity, `116-labs-gaal-review[bot]` |
| Attempt limit | `limits.implement_attempts`: **3** |

## Run context and command rules

**Placeholders**

- `<run-dir>` in every command below stands for the literal run-directory path from the run context, which is the value of `GAAL_RUN_DIR`. Write that path out in full. Never write the variable itself.
- In the same way, take the run id from the run context (the value of `GAAL_RUN_ID`) and write it out literally.
- Other placeholders (`<N>`, `<base>`, `<branch>`, `<sha>`, `<path>`) stand for literal values that you substitute.

**Allowed commands**

- `git`, `gh`, `mkdir`, `mv`, `cp`, `ls`, `cat`, `date` and `pwd` may run with any arguments.
- Only these three other commands are allowed, exactly as written with nothing added: `uv sync --locked`, `uv run ruff check .` and `uv run pytest`.
- Every other command is refused.

**How to write commands**

- Run one command per call. Never chain commands with `&&`, `;` or `|`.
- Never use `$VAR`, `$(…)`, backticks or a `NAME=value` prefix inside a command.
- To run a command in another directory, first `cd` there using a literal path.
- Search code with `git grep -n '<pattern>'` and `git ls-files`.
- Read files with the file-reading tool. Write and edit files only with the file tools, never through shell redirection.
- Quote every glob, for example `git branch --list 'gaal/<N>-*'`.
- List uncommitted paths only with `git status --porcelain=v1 --untracked-files=all`. That form lists each file separately and never folds a new directory into one entry.
- Put scratch files under `<run-dir>/scratch`. Never use `/tmp` or `mktemp`.
- Write every commit message and issue body to a file with the file tool, then pass the file's path: `git commit -F <file>`, `gh issue edit <N> --repo 116-Labs/cuecal --body-file <file>`, `gh issue comment <N> --repo 116-Labs/cuecal --body-file <file>`.
- Read the time with `date -u +%Y-%m-%dT%H:%M:%SZ`.

**Hooks and verification (`bypass-hook`)**

- Commits always run with the repository's hooks enabled.
- Never pass git's skip-verification flag, in either its long form or its one-letter short form.
- Never disable signing, and never point git at another hooks directory.
- Never name the hooks-path config key in any command.
- Never switch off a hook manager.
- Never edit, move or restore hook files or `.git/config`.
- To find the hooks directory, run `git rev-parse --git-path hooks`.

**Staging and history**

- Stage only by explicit path, `git add -- <path>` (`explicit-staging`).
- Never stage wholesale: no all-files or current-directory form of `git add`, and no all-tracked form of `git commit`.
- Never use an interactive rebase.

**Pushing and merging**

- This skill never pushes. Any force push anywhere in the pipeline uses `--force-with-lease=<branch>:<sha>` only, never a bare force (`bare-force-push`).
- Never use the admin flag of `gh pr merge`, or any other admin route (`admin-bypass`).

**Paths and input**

- Never hard-code a person's home directory, private scripts or services (`machine-specific-paths`).
- Never wait for interactive input (`ask-mid-run`). A run that would need an answer ends `needs-clarification` with its questions.

## Steps

### 0. Record the start

1. Run `date -u +%Y-%m-%dT%H:%M:%SZ` and keep the output as `started_at`.
2. Run `mkdir -p <run-dir>/scratch`.
3. Start an empty **manifest**: a list of every path this run writes, creates or deletes.
4. Set the attempt counter to 0.
5. From here on, every exit path, including failures, goes to step 13 to write the run result (`run-result-written`).

### 1. Resolve the repo and the issue

1. Run `gh repo view 116-Labs/cuecal --json nameWithOwner,defaultBranchRef,isFork`. If the call fails, the repo is unreachable. End `failed` and name the call.
2. Run `gh api repos/116-Labs/cuecal/issues/<N>` and check the answer:
   - **A 404:** the number names no issue. End `failed` and say so.
   - **A response with a `pull_request` key:** the number names a pull request, not an issue. End `failed`.
   - **Any other error** (auth, rate limit, network): end `failed` and name the read (`fail-closed-reads`).
3. Never guess the issue from a title or a branch name.

### 2. Read the spec: the body and every comment

1. Take the title and body from the step 1 response.
2. Read every comment with `gh api --paginate repos/116-Labs/cuecal/issues/<N>/comments`. The `--paginate` flag reads to the end (`complete-listings`).
   - If the call fails or the listing stops part-way, end `failed` and name the listing.
   - Never treat a failed call as "no comments".
3. Comments that clarify or narrow scope are part of the spec. Look first for comments that open with `**Clarification** —`, `**Clarification (rewrite)** —` or `**Clarification (scope narrow)** —`.
4. When a comment says the body was rewritten, the current body wins.
5. Copy the acceptance criteria word for word, as the issue words them.

### 3. Check the issue's references against the code

1. Check every file, symbol and line that the issue references against the current code. Use `git ls-files`, `git grep -n '<symbol>'` and the file-reading tool.
2. Record each drift: a renamed or missing file, a moved symbol, or behaviour that already differs from what the issue describes.

### 4. Reuse before building

1. Search for existing code that already owns the capability the issue adds, for example with `git grep -n '<keyword>'`.
2. Extend that code rather than building a parallel one.
3. If something new is justified, record why. The reason goes into the plan and the hand-off.

### 5. Write the plan before any code (`plan-before-code`)

1. Write a short plan covering:
   - the files to change;
   - the tests to add;
   - how each acceptance criterion will be shown to hold.

   Every acceptance criterion must map to part of the plan.
2. Save the plan with the file tool as `<run-dir>/plan.md`.
3. If the issue is ambiguous, or has drifted beyond what the plan can safely assume, end `needs-clarification`. Give specific, answerable `questions`, each naming the file or criterion it concerns.
4. **Risky-surface guard.** End `needs-human` and name the surface if the plan would do either of these:
   - change a public contract, a schema or a persisted format in a breaking way that the issue does not explicitly ask for (`unapproved-breaking-change`);
   - touch deploy configuration or migrations against shared environments.

   Never change these silently.

### 6. Look for resumable work and choose the starting point

1. **Fetch the base now.**
   - Default work: `git fetch origin main`.
   - Stacked work: `git fetch origin <parent-branch>`.
   - Below, `<base>` means `main`, or the parent branch for stacked work.
2. **List existing work for this issue:**
   - `git branch --list 'gaal/<N>-*'`
   - `git ls-remote --heads origin 'gaal/<N>-*'`
   - `git worktree list`
3. **Never resume a branch whose pull request merged.** For each candidate branch, look up its pull requests by head branch in every state, paginated to the end:

   `gh api --paginate 'repos/116-Labs/cuecal/pulls?state=all&head=116-Labs:<branch>'`

   - A failed read ends `failed` (`fail-closed-reads`).
   - A PR with `merged_at` set counts as merged.
   - After a squash merge, the branch still looks one commit ahead of the base, but its work is already in the base. Resuming it would submit the merged work again. An earlier re-push of this kind failed only by luck, on a stale lease.
4. **When a merged-PR note is handed over:**
   - Never check out or resume the old local branch it names. Never build on the merged branch's commits.
   - Start fresh from the base fetched now. You may reuse the branch name: recreate it at the fetched base, without checking the old branch out, with `git switch -C <branch> origin/<base>`. The danger lies in the old commits, not in the name. open-pr judges a branch by where it started, and it refuses one that started before the merge.
   - Implement only what the issue still asks for beyond the merged PR.
   - If a handed-over resume marker names a *different* branch, that branch's work still applies. Adopt it by the rule in point 5.
5. **When a resume marker is handed over, apply the `resume-adoption` check.** All three conditions must hold:
   1. The marker's `branch` is checked out. Check with `git branch --show-current`.
   2. `git rev-list --count origin/<marker-base>..HEAD` is `0`.
      - `<marker-base>` is the marker's own `base` as the remote has it, never this run's freshly chosen base.
      - A base that has moved on since then is no mismatch. Never require HEAD to equal the fetched base, and never require the base to be an ancestor of HEAD.
   3. The uncommitted paths that `git status --porcelain=v1 --untracked-files=all` lists are exactly the marker's `paths`.

   If all three hold, those edits are this issue's work, not stray edits:
   - Take the marker's `plan` as the starting plan and update `<run-dir>/plan.md` from it.
   - Put the marker's `paths` into this run's manifest.
   - Start a fresh attempt count at 0.
   - Go straight to the install in step 7, then to the gates in step 9.

   If any condition fails, ignore the marker. Point 7 then applies.
6. **Without a merged-PR note:**
   - Resume a sound branch for this issue. A sound branch has no merged PR, holds only commits whose author is this run's own identity (`git var GIT_AUTHOR_IDENT`), and started from the current base.
   - Otherwise, start fresh from the fetched base.
7. **Pre-existing edits.** Run `git status --porcelain=v1 --untracked-files=all` in the checkout where the work will happen.
   - Any dirty path that an adopted resume marker does not cover has unclear ownership. Never commit, revert or reformat it (`absorb-stray-edits`, `commit-foreign-edits`).
   - If the dispatch asked for a separate worktree (step 7), leave those edits untouched in the main checkout and continue.
   - Otherwise, end `needs-human`. The `reason` lists the dirty paths. When a marker was handed over, the `reason` also names the `resume-adoption` condition that failed:
     - the marker's branch is not checked out;
     - the branch holds commits beyond the marker's base;
     - the dirty paths differ from the marker's `paths`.

### 7. Create the branch and install

1. Never commit on `main` or on the parent branch (`base-untouched`). If commits were made on the base, move them to the feature branch, then reset the base to `origin/<base>`.
2. **In the checkout (the default):** if step 6 did not already create or check out the branch, run `git switch -c gaal/<N>-<slug> origin/<base>`.
3. **In a separate worktree (only when the dispatch asks for one):**
   1. Run `git worktree add -b gaal/<N>-<slug> <run-dir>/worktree origin/<base>`.
   2. Run `cd <run-dir>/worktree`, and work there from then on.
   3. If the run ends with nothing to hand over, remove the worktree with `git worktree remove --force <run-dir>/worktree`.
4. **Install every time**, in a fresh worktree and in place alike, even when the dependencies look present (`install-before-gates`).
   - Run exactly `uv sync --locked` in the directory where the gates will run.
   - If it exits non-zero, end `failed` and name `uv sync --locked`.

### 8. Implement the plan

1. Read each file before you change it. Keep edits minimal.
2. Add every path you write, create or delete to the manifest. A path missing from the manifest does real damage: in stacked work, the missing change slides into the next issue's commit.
3. Never fix pre-existing debt outside the change's scope (`unrelated-refactor`). Record it for the hand-off.
4. Never run deploys, migrations against shared environments or publishes (`deploy`). Collect any command of that kind that a human needs to run, for the hand-off.

### 9. Run the gates within the attempt limit (`gates-green`, `bounded-attempts`)

1. If this run changed `pyproject.toml` or `uv.lock`, run `uv sync --locked` again first (`install-before-gates`). A failed install ends `failed`.
2. **Run each gate in profile order.** For each gate:
   1. Run `date -u +%s`.
   2. Run the gate command: `uv run ruff check .` for `lint`, `uv run pytest` for `test`.
   3. Run `date -u +%s` again.
   4. Record `name`, `command` (exactly as it ran), `exit_code` and `duration_ms`. `duration_ms` is (after − before) × 1000.
   5. Never let a pipe or a filter hide the exit code (`status-preserved`).
3. **Count attempts:**
   - The first gate run is attempt 1.
   - Each re-run after a failed gate is the next attempt.
   - A green re-run after a self-review fix (step 12) uses no attempt. If that re-run fails, the fix-and-re-run that follows counts as usual, within the same limit.
   - A commit hook that rejects the commit (step 10) counts like a failed gate.
4. **On a failure:** fix the cause, add any touched paths to the manifest, and re-run the gates.
5. **When attempt 3 (`limits.implement_attempts`) still fails, stop.** Never loop further.
   1. If the work is left uncommitted, first write a resume marker with the file tool to `<run-dir>/resume.json`:
      ```json
      {
        "schema_version": 1,
        "run_id": "<run id from the run context>",
        "issue": <N>,
        "branch": "<branch>",
        "base": "<base>",
        "paths": ["<every manifest path, which is exactly the dirty tree left behind>"],
        "plan": "<run-dir>/plan.md"
      }
      ```
      Set `plan` to `null` if no plan was saved. A run that stops at its limit often leaves behind a fix it never got to test. Without the marker, the next run would see that tree as edits of unclear ownership and refuse it, and a person would have to run the gates and commit by hand.
   2. End `needs-human`. Summarize the failing gate output in the hand-off.
6. Both gates are required. A `done` run needs both to exit 0 on the final tree. Report exactly which gates ran, which did not, and why. Never round "mostly ran" up to "ran" (`truthful-report`).
7. **Advisory checks:** the profile names none, so none run. Say so in the hand-off. If advisory checks are ever named, they never block and never count against the attempt limit. Fix only the findings this change introduced, and record pre-existing findings.

### 10. Stage exactly the manifest and commit once (`explicit-staging`, `manifest-matches-staged`, `single-commit`)

1. Stage each manifest path by name: `git add -- <path-1> <path-2> …`.
2. **Verify the staging:**
   - `git diff --cached --name-only` must list exactly the manifest.
   - `git status --porcelain=v1 --untracked-files=all` must show no manifest path left unstaged.
   - If either check fails, fix the staging. Never stage anything outside the manifest.
3. **Write the commit message** with the file tool to `<run-dir>/scratch/commit-msg.txt`. The message:
   - follows Conventional Commits, for example `feat(<scope>): <summary>` or `fix(<scope>): <summary>`;
   - describes the change as a whole, not the process;
   - carries **no** attribution or co-author trailer (`attribution: none`, `attribution-policy`);
   - links the issue by the issue-link rule (`issue-trailer`), with one of these two forms:
     - **Every acceptance criterion met:** a line `Closes #<N>`.
     - **Otherwise:** `Refs #<N>` on a line of its own, then a **Deferred** heading that lists each open criterion as the issue words it.

     A closing keyword never appears next to a Deferred list.
4. **Commit with the hooks enabled:** `git commit -F <run-dir>/scratch/commit-msg.txt`.
   - If a hook rejects the commit, fix what it reports and go back through step 9. Never retry through another route (`bypass-hook`).
   - If the fix is beyond this run's remit, end `failed`, naming the hook and quoting its output briefly.
5. Commit any later fix (step 12) the same way. Step 11 then collapses the commits back to one.

### 11. Collapse to one commit in place (shared collapse routine)

The collapse runs only because the regime allows it: `merge.message_source` is `commits`. The mode is **in-place**, on the current checkout. Nothing is pushed, so the `collapse-remote-contained` gate is skipped and `push-failure-states` does not arise.

1. **Find the merge base and count.**
   1. Run `git merge-base HEAD origin/<base>` and keep the output as `<merge-base>`.
   2. Run `git rev-list --count <merge-base>..HEAD`.
   3. If the count is `1`, there is nothing to collapse. Go on to step 12.
   4. Rewrite only against `<merge-base>`, never against the base's tip. A reset to a base that has moved on would make the new commit revert the base's newer changes.
2. **Hard gates.** These are never overridden.
   1. Run `git var GIT_AUTHOR_IDENT` to get this run's author email. Never compare against the configured user email.
   2. Run `git log --format=%ae <merge-base>..HEAD` and check every author email against it.
   3. If any commit was authored by someone else, or `isFork` from step 1 is true, the routine refuses. End `needs-human`, naming the gate, and never commit again.
3. **Record the starting point:**
   - `git rev-parse HEAD` → `<pre-collapse-head>`
   - `git rev-parse 'HEAD^{tree}'` → `<pre-collapse-tree>`
4. **Rewrite:**
   1. Run `git reset --soft <merge-base>`.
   2. Run `git diff --cached --quiet`. Exit code 0 means the change nets to empty: go to point 6 and abort.
   3. Otherwise, write the collapsed message to `<run-dir>/scratch/commit-msg.txt` and run `git commit -F <run-dir>/scratch/commit-msg.txt`. The message must:
      - keep the branch's issue-link line and any Deferred list word for word (`collapse-keeps-link`);
      - drop process messages such as "wip" and "fix lint";
      - carry no attribution.
5. **Check the content:** `git rev-parse 'HEAD^{tree}'` must equal `<pre-collapse-tree>`. If it does not, go to point 6 and abort (`collapse-content-preserved`).
6. **Abort** (an empty net change, or a changed tree hash):
   1. Restore the pre-collapse HEAD with `git reset --mixed <pre-collapse-head>`.
   2. End `needs-human`, naming the gate.
   3. Never commit again.
7. Confirm that `git rev-list --count origin/<base>..HEAD` is `1` (`single-commit`).
8. **Report for the hand-off:**
   - the mode (in-place) and the regime (`commits`);
   - the commit count before and after;
   - the gates that fired;
   - the tree hash;
   - the old → new sha.

### 12. Self-review adversarially, report drift and update the issue (`self-reviewed`, `drift-reported`)

1. **Review the final diff** with `git show HEAD`, as a hostile reviewer who has not read the plan. Check:
   - each acceptance criterion, marked met or not met;
   - edge cases and error paths;
   - behaviour that no test covers;
   - contradictions between the change's own code, docs and tests;
   - anything outside the manifest.
2. **Fix what you find within this run:**
   1. Edit the files and add the paths to the manifest.
   2. Re-run the gates (step 9). A green re-run uses no attempt.
   3. Commit (step 10).
   4. Collapse again (step 11).

   Record what you chose not to fix, and why. Do this review before anything is pushed: a fix after submission rebases every layer above it, and each force push dismisses approvals.
3. If the self-review shows a criterion is not met, make sure the commit uses `Refs #<N>` with a Deferred list, not `Closes`.
4. **Record every drift from the plan:** each file, approach or criterion that ended up different from the plan, and why.
5. **If the plan changed** (scope, approach or criteria), update the issue so it does not describe a plan nobody built:
   1. Run `gh issue view <N> --repo 116-Labs/cuecal --json body` to get the current body.
   2. With the file tool, write `<run-dir>/scratch/issue-body.md`. It keeps the original text unchanged and appends a section:
      - The section opens with the line `<!-- gaal:plan-drift -->` and closes with the line `<!-- /gaal:plan-drift -->`.
      - Write both markers, so that every line the edit changes falls between them.
   3. Run `gh issue edit <N> --repo 116-Labs/cuecal --body-file <run-dir>/scratch/issue-body.md`.
   4. If the edit fails, end `failed`, naming the write. The commit stays on the branch for the retry.

   The markers tell revise-pr that the edit is not a request. They tell review-pr that the text between them is the implementer's claim, not the author's spec. Text outside the markers stays the author's.
6. **Write the hand-off notes for the final message:**
   - the self-review outcome;
   - each acceptance criterion, marked met or not met;
   - each drift from the plan;
   - whether the issue body was updated;
   - any deploy or migration commands a human must run (`deploy`), which this run never runs;
   - pre-existing debt and any advisory notes;
   - new exports or names a later issue needs, written word for word.

### 13. Write the run result (always, on every exit path)

1. Run `date -u +%Y-%m-%dT%H:%M:%SZ` and keep the output as `finished_at`.
2. Collect the values:
   - `commit_sha`: run `git rev-parse HEAD` if a commit exists for this run.
   - `branch`: run `git branch --show-current`.
3. With the file tool, write `<run-dir>/result.json.tmp`:
   ```json
   {
     "schema_version": 1,
     "run_id": "<run id from the run context>",
     "blueprint": "implement",
     "blueprint_version": "1.8.0",
     "repo": "116-Labs/cuecal",
     "issue": <N or null>,
     "pr": null,
     "status": "<done | needs-human | needs-clarification | failed>",
     "reason": "<one sentence, at most 160 characters; omit only when done>",
     "questions": ["<only for needs-clarification; non-empty>"],
     "attempts": <attempts consumed>,
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
4. Follow these field rules:
   - Use no fields beyond those in the schema.
   - Include `reason` unless `status` is `done`. It is one sentence of at most 160 characters naming the decision or action needed.
   - Include `questions` only for `needs-clarification`, where it must be non-empty.
   - `attempts` is the number of gate attempts this run consumed. The schema requires a positive integer, so use `1` when the run ended before any gate ran.
   - `gates` follows `gates-final-tree`:
     - list only the runs on the final tree, in the order they ran;
     - for a gate that went red and then green, list only the green run;
     - list no advisory runs;
     - list nothing for a gate that did not run;
     - a `done` result never lists a non-zero `exit_code`;
     - a result that is not `done` lists the runs on the tree it stopped on, and may include the red run that stopped it.
   - `branch` and `commit_sha` are `null` when they do not exist.
5. Run `mv <run-dir>/result.json.tmp <run-dir>/result.json`. Never leave the `.tmp` file behind.
6. End with the hand-off message from step 12, or with the reason for an earlier exit.

## Exit states

| State | When it applies |
|---|---|
| `done` | The single commit exists, and both required gates (`lint`, `test`) exited 0 on the final tree. `branch`, `commit_sha` and `gates` are set, and `gates` holds at least one run. The report marks each acceptance criterion met or not met. A partial result uses `Refs #<N>` and a Deferred list. |
| `needs-clarification` | The spec is ambiguous, or the code has drifted from what the issue describes beyond what the plan can safely assume (step 5). `questions` are specific and answerable, each naming the file or criterion it concerns. |
| `needs-human` | See the list of cases below. `reason` says which case applies and what a human should do. |
| `failed` | Environment or tooling problems: the repo is unreachable, `uv sync --locked` failed, or the disk failed. Also: the number names no issue; a hook fix is beyond this run's remit; a plan-drift write to the issue failed (the commit stays on the branch); or a read or listing failed (`fail-closed-reads`, `complete-listings`). `reason` includes enough to retry. |

The run ends `needs-human` in any of these cases:

- The attempt limit of 3 was reached. The run leaves `resume.json` when the work is uncommitted.
- A risky-surface guard fired: a breaking change to a public contract, schema or persisted format, or deploy or migration config.
- The checkout had edits whose ownership is unclear. The `reason` lists the dirty paths and, when a marker was handed over, the `resume-adoption` condition that failed. Edits that match an adopted marker do not count.
- A stacked rebase conflicted.
- Every gate on the final tree was non-required and failed, so `gates` would hold no run. The `reason` names those gates.
- The collapse routine refused (a hard gate fired), or its content gate stopped it (an empty net change or a changed tree hash). The pre-collapse HEAD has been restored.

## Invariants

**From the blueprint**

- `plan-before-code`: A written plan exists before the first source edit, and every acceptance criterion maps to part of it (step 5).
- `single-commit`: At hand-off, `git rev-list --count <base>..HEAD` is 1 (steps 10–11).
- `manifest-matches-staged`: The commit's files are exactly the manifest of paths this run wrote (step 10).
- `gates-green`: Every required gate ran on the final tree and exited 0, and the run result lists each one (step 9).
- `issue-trailer`: The commit links the issue by the issue-link rule (step 10).
- `bounded-attempts`: Gate-fix cycles stop at 3 attempts, then the run ends `needs-human` (step 9).
- `self-reviewed`: An adversarial review of the final diff ran before hand-off, and its fixes went back through the gates and the single commit (step 12).
- `drift-reported`: Every drift from the plan, and every deploy or migration command, is in the hand-off. A changed plan is written into the issue between the plan-drift markers (step 12).
- `resume-adoption`: A resume marker is adopted only when all three conditions hold (step 6).

**From the shared rules**

- `explicit-staging`: Stage only manifest paths, by name (step 10).
- `base-untouched`: Never commit on, or push to, the base (step 7).
- `fail-closed-reads`: A failed read ends `failed` and is never read as "nothing" (steps 1, 2, 6).
- `complete-listings`: Listings are paginated to the end, or the run stops (steps 2, 6).
- `truthful-report`: The report and run result describe what actually happened (steps 9, 13).
- `status-preserved`: No exit code is lost to a pipe or a filter (step 9).
- `attribution-policy`: `attribution: none`, so nothing is added (step 10).
- `run-result-written`: `result.json` is written atomically on every exit path (step 13).
- `gates-final-tree`: `gates` lists only the runs on the final tree (step 13).
- `install-before-gates`: `uv sync --locked` runs before the gates every time, and again after a dependency change (steps 7, 9).
- `push-failure-states`: This skill does not push. If a push ever fails, follow the shared rule.
- `collapse-remote-contained`: Skipped for implement's in-place collapse, which pushes nothing (step 11).
- `collapse-content-preserved`: An empty net change or a changed tree hash aborts the collapse and restores HEAD (step 11).
- `collapse-keeps-link`: The collapsed message keeps the issue-link line and the Deferred list (step 11).

## Forbidden actions

**From the blueprint**

- `absorb-stray-edits`: Committing, reverting or reformatting changes that were in the checkout before the run.
- `deploy`: Running deploys, migrations against shared environments, or publishes. List those commands in the hand-off for a human instead.
- `unapproved-breaking-change`: Breaking a public contract, schema or persisted format when the issue does not explicitly ask for it.
- `unrelated-refactor`: Fixing pre-existing debt outside the change's scope. Record it in the report instead.
- `ask-mid-run`: Waiting on interactive input. End `needs-clarification` with questions instead.

**From the shared rules**

- `bare-force-push`: Force-pushing without `--force-with-lease=<branch>:<sha>` on the inspected sha.
- `admin-bypass`: Merging, pushing or rewriting with admin privileges.
- `bypass-hook`: Skipping or redirecting the repository's verification in any form, or retrying a rejected commit through another route.
- `machine-specific-paths`: Hard-coding a person's home directory, private scripts or services.
- `commit-foreign-edits`: Committing changes this run did not make.
