---
name: gaal-revise-pr
description: Revises an open pull request in 116-Labs/cuecal after review. It addresses every unresolved review thread with a code fix or a reasoned reply, runs the profile gates, pushes once per round, then replies to and resolves threads by rule. Use when a dispatch hands you a repo and PR number and asks for the `revise-pr` step, including imported feedback from another PR, a comment URL, or free-text notes. Do not use to open a PR, implement an issue, review a PR, or merge; those are other steps. Do not use when no PR can be determined; end as `needs-clarification` instead of guessing.
---
<!-- gaal-stamp blueprint=revise-pr@1.2.0 shared=1.1.0 profile=0ed21dd3bece7944 generated=2026-09-30 content=ac7ccea01a6e5f15 -->

# gaal-revise-pr

Close the review loop on an open PR in `116-Labs/cuecal`. Every unresolved thread gets a code change or a reasoned reply. The branch is pushed once per round with gates run and passing. Threads end in a state that matches what was done. Then review is requested again.

Inputs: repo and PR number from dispatch. Optional imported feedback: threads from another PR, a single comment URL, or free-text notes. `GAAL_RUN_ID` and `GAAL_RUN_DIR` come from the environment.

Project facts (from the project profile):
- Tracker: GitHub. Default branch: `main`. Branch prefix: `gaal/`.
- Commit convention: conventional. Attribution: `none`. Single commit per PR.
- Merge: squash, no merge queue, message taken from the commits (`message_source: commits`).
- Review: 1 approval required. Open threads do not block merge (`threads_block_merge: false`). No reviewers are listed.
- Limit: `limits.revise_rounds` = 3.
- Preflight: none.
- Gates, both `required: false` and `pending: true`:
  - `lint`: `uv run ruff check .`
  - `test`: `uv run pytest`

## Steps

Record `started_at` (UTC, RFC 3339) before anything else. Keep a manifest of every path this run writes, a list of gate runs (name, exact command, exit code, duration in ms), and a round counter starting at 0.

### 1. Confirm the PR is open

Read the PR state through the GitHub API. Distinguish "the API said the PR is closed or merged" from "the call failed" (`fail-closed-reads`). An error, auth expiry or rate limit stops the run. Do not treat any of them as "no PR".

- No PR number can be determined: end as `needs-clarification`. Never guess.
- PR is closed or merged: end as `failed`.
- The PR head branch lives on a fork, or the API call failed: see exit states.

Never change the base branch (`base-untouched`). All code changes land on this PR's branch only (`target-branch-only`).

### 2. Check out the PR head

Fetch the PR head branch from the remote and check out exactly the fetched commit. Note the fetched head sha, which is the lease sha for later pushes. If the lockfile (`uv.lock`) differs from the last install, run `uv sync`. Run the preflight commands; the profile lists none.

If the working tree has uncommitted changes this run did not make, stop and end as `needs-human` (`commit-foreign-edits`).

### 3. List every unresolved review thread

Use the GitHub GraphQL API (`reviewThreads` on the pull request), which exposes `isResolved`, `isOutdated` and thread ids. Page to the end using `pageInfo.hasNextPage` and `endCursor`. If a page fails or pagination cannot finish, stop the run (`complete-listings`, `fail-closed-reads`). Truncated data is never trusted.

Record every thread id, with its comments and source (this PR or an import), before any history rewrite. Rewriting history marks threads outdated, and the ids are what you reply through later.

For imported feedback:
- Another PR's threads: list them the same way, paginated, and tag them as imports.
- A comment URL: check its shape first. An `issuecomment-` URL points at an issue-level comment, which has no thread and no thread id. Treat it as an item to answer with a PR comment. A `discussion_r` URL is a review comment inside a thread.
- Free-text notes: treat each distinct request as an item.

If there are no unresolved threads and no imports, nothing needs changing. Go to step 12 and end as `done` with the unchanged head.

### 4. Re-verify imported items

For each imported item, check whether it reproduces, partly applies, or does not apply on this branch. Read the code and, where useful, run the relevant command. Never apply a finding that does not reproduce here (`apply-unreproduced-import`). An item that does not apply still gets a reply with the reason (`every-thread-answered`).

### 5. Decide each item

Assign exactly one decision to each item:
- **fix**: change the code.
- **answer**: the item is a question or needs an explanation.
- **defer**: the work belongs in a follow-up issue and the thread will show agreement. File the follow-up issue on GitHub first and get its number. Leave it unassigned and outside any milestone. A deferral with no issue number is a pushback in disguise (`resolve-unagreed-deferral`).
- **push back**: you disagree, with reasons.

If a reviewer's request is so ambiguous that any fix would be a guess, do not guess. End as `needs-clarification` with `questions` quoting the thread. Still write the result file.

### 6. Make all fixes

Make every fix in the working tree before running any gate or pushing. Add each written path to the manifest. Keep changes to what threads ask for. Fixes for imported items land on this PR's branch only (`target-branch-only`).

### 7. Run the gates

Increment the round counter. Run `uv run ruff check .` (`lint`) and `uv run pytest` (`test`) on the tree that will be pushed. Both are `pending`, and a pending gate runnable on this tree must exit 0 (`gates-green-before-push`).

- Skip a gate only while its tool or manifest does not exist yet (for example no `pyproject.toml`, or `uv` is not installed). Say so in the PR comment and final message. A gate that did not run is absent from the result, never recorded as passed (`truthful-report`).
- Capture each command's exit status directly. Never let a pipe, filter or `|| true` hide it (`status-preserved`).
- Record every run in the gates list, including failed ones.
- On failure, fix the cause, add changed paths to the manifest, and re-run every gate. Each fix-and-re-run cycle counts as a round.
- If the round counter reaches 3 (`limits.revise_rounds`) and gates are still red, stop without pushing and end as `needs-human` (`bounded-rounds`).
- If a failing gate also fails on the untouched base, it is pre-existing. Do not push red to work around it (`push-red`). End as `failed` and name the gate as pre-existing in `reason`.

### 7a. Guard against piecemeal work

Do not push between fixes or after each comment (`piecemeal-push`). One round means one push after all fixes and green gates (`one-push-per-round`).

### 8. Commit and push once

Skip this step if nothing changed.

1. Stage only paths in the manifest, by explicit path: `git add -- <path> [<path> ...]`. Never stage wholesale, and never use `git commit -a` (`explicit-staging`). Afterwards `git status --porcelain` must show no other change this run is responsible for.
2. Commit the fixes as one fixup commit with a conventional message, for example `fix(<scope>): address review feedback`. The commit and later PR text follow `commits.attribution: none`. Add no `Co-Authored-By` line, no "generated by" line and no AI mention of any kind (`attribution-policy`).
3. Push to the PR branch once. A plain `git push` of a fast-forward is fine. Check its exit status. A failed push is `failed`, or `needs-human` when a conflict or permission problem blocks it. Record the reason. Never use `--no-verify`.

Never commit or push to `main` (`base-untouched`).

### 9. Collapse to one commit, only on the final round

Run this only if all of these hold:
- Every thread on this PR will be resolved after replies. Pushbacks and unagreed deferrals count as staying open. If any thread on this PR will remain open, do not collapse, and keep the fixup commit separate so the reviewer can diff only the delta (`collapse-with-open-threads`).
- `merge.message_source` is `commits`. It is, so the regime gate passes.

The fix push in step 8 must land first. The collapse reads the remote head, and collapsing before the push would ship without the fix.

Apply the shared single-commit collapse routine in **PR mode**. Declare the mode explicitly. Never infer it.
1. Idempotence: if the branch is zero or one commit ahead of the merge base, do nothing and succeed.
2. Read the head sha from the remote and check it equals the sha you pushed. Rewrite in a throwaway detached worktree, never in the local checkout.
3. Soft gates: knowingly override the unresolved-threads gate, because the threads just fixed resolve after the push. Print the unresolved count. Treat an unreadable approval setting as "an approval would be dismissed" and note the override in the report.
4. Hard gates, never overridden: the branch is on a fork, or any commit on it was authored by someone else, or the remote head is not an ancestor of what will be pushed. If one fires, do not collapse, and end as `failed` naming the gate. The fix push already landed. Say so in `reason`.
5. Divergent local checkouts: back up local-only commits to a permanent branch ref, verify the backup, then reset. Uncommitted edits of unknown origin stop the collapse for a human (`needs-human`).
6. Content preservation: if the rewrite nets to an empty change, restore and stop. After committing, the tree hash must equal the pre-collapse tree hash, or abort before pushing.
7. Write one commit message for the whole change: conventional, a subject that describes the change as landed, no process commits ("wip", "fix lint", "address review"), and no attribution (`commits.attribution: none`).
8. Push with an explicit lease on the inspected sha: `git push --force-with-lease=<branch>:<sha> origin HEAD:<branch>`. Never use `--force`, `-f`, or a lease with no expected sha (`bare-force-push`). This push is the collapse routine's own and does not count as a second round push. On failure, restore the previous HEAD. Remove only the throwaway worktree, on every exit path. Never use an interactive rebase and never merge or push with admin privileges (`admin-bypass`).
9. Report mode, regime, commit count before and after, gates that fired, tree hash, old and new sha, backup refs in full.
10. After a collapse, hard-reset the local checkout to the remote head: `git fetch origin <branch>` then `git reset --hard origin/<branch>`. Never pull (`pull-after-collapse`). Any other stale checkout needs the same reset.

If the collapse refuses or fails, end as `failed` naming the step.

### 10. Reply to every thread

Reply through each thread's reply relation using the thread id recorded in step 3 (the GraphQL `addPullRequestReviewThreadReply` mutation). It works on outdated threads. Every thread that was unresolved at the start gets a reply, including imports that did not apply (`every-thread-answered`). For an issue-level comment with no thread, post a PR comment.

Each reply describes what was actually done (`reply-matches-action`):
- **fix**: names the sha that contains the fix. After a collapse, that is the collapsed head sha. Say "fixed in `<sha>`" only when that sha contains the fix (`truthful-report`). For an imported item, also name the branch and PR where it landed.
- **answer**: gives the explanation.
- **defer**: names the follow-up issue number, which was filed first.
- **push back**: gives the reasons.
- **import that does not apply**: says why it does not reproduce here.

Check the exit status of every API write (`status-preserved`).

### 11. Resolve threads by rule

Resolve a thread (the GraphQL `resolveReviewThread` mutation) only if it was fixed, is outdated, or was deferred with agreement recorded on the thread (`resolve-by-rule`).

- Leave pushbacks open for the reviewer (`resolve-pushback`).
- Leave a deferral open if agreement is not recorded on the thread (`resolve-unagreed-deferral`). Because `threads_block_merge` is false, an open deferral does not block merge, but the rule still holds.
- Resolving another PR's thread may fail on permissions. The reply is what matters. Note the failure and continue; it is not a blocker.

### 12. Request review again

The profile lists no reviewers and no re-request command, so do not invent one. Post one PR comment (`comms.github_comments: true`) with a per-item table: source, decision, and sha or issue. Say the PR is ready for another look. List open pushbacks. Also state any gates that were skipped and why. Use no attribution. If nothing changed, say so. State in the final message that no reviewer was re-requested because the profile names none.

### 13. Write the run result

Do this on every exit path, including failures and early exits (`run-result-written`). If `GAAL_RUN_DIR` is set, write `$GAAL_RUN_DIR/result.json` atomically: write to a temp file in the same directory, then rename it over `result.json`.

Fields, and only these (additional properties are rejected):
- `schema_version`: `1`
- `run_id`: the value of `$GAAL_RUN_ID`
- `blueprint`: `"revise-pr"`
- `blueprint_version`: `"1.2.0"`
- `repo`: `"116-Labs/cuecal"`
- `issue`: the linked issue number, or `null`
- `pr`: the PR number, or `null` if none could be determined
- `status`: one of `done`, `needs-human`, `needs-clarification`, `failed`
- `reason`: required unless `status` is `done`. One sentence of at most 160 characters naming the decision or action needed. Detail goes in the PR comment and final message.
- `questions`: required and non-empty when `status` is `needs-clarification`, each quoting the thread
- `attempts`: rounds used, an integer of at least 1
- `gates`: only gates that actually ran, each with `name`, `command`, `exit_code`, `duration_ms`. It may be empty when nothing changed.
- `branch`: the PR head branch, or `null`
- `commit_sha`: the PR head after the run as a 40-character lowercase hex sha, or `null` if unknown. When nothing changed, it is the unchanged head.
- `started_at`, `finished_at`: RFC 3339 timestamps with a timezone

Example, for a `done` run:

```
{
  "schema_version": 1,
  "run_id": "<value of $GAAL_RUN_ID>",
  "blueprint": "revise-pr",
  "blueprint_version": "1.2.0",
  "repo": "116-Labs/cuecal",
  "issue": null,
  "pr": 42,
  "status": "done",
  "attempts": 1,
  "gates": [
    {"name": "lint", "command": "uv run ruff check .", "exit_code": 0, "duration_ms": 850},
    {"name": "test", "command": "uv run pytest", "exit_code": 0, "duration_ms": 4200}
  ],
  "branch": "gaal/<slug>",
  "commit_sha": "<40 hex characters>",
  "started_at": "2026-09-29T10:00:00Z",
  "finished_at": "2026-09-29T10:06:00Z"
}
```

Add `reason` for any status other than `done`. Add `questions` for `needs-clarification`.

## Exit states

- `done`: every thread is answered and the branch is pushed with gates run and passing. `commit_sha` is the PR head after the run. When nothing needed changing, it is the unchanged head, nothing was pushed, and `gates` may be empty. The report has one row per item (source, decision, sha or issue). Open pushbacks are normal and listed.
- `needs-clarification`: no PR could be determined, or a reviewer's request is ambiguous enough that any fix would be a guess. `questions` quote the thread.
- `needs-human`: the round limit (3) was reached with red gates, or a conflict or permission problem blocks the push, or uncommitted edits of unknown origin block a reset. `reason` names it.
- `failed`: the PR is not open, the push failed, the collapse refused, or a gate is red on the base as well (reported as pre-existing). `reason` names the step. API errors, auth expiry and rate limits also end here or as `needs-human`. They never become "no PR", "no threads" or "no checks".

## Invariants

Blueprint invariants:
- `every-thread-answered`: every thread unresolved at the start has a reply at the end, including imports that did not apply.
- `one-push-per-round`: one push per round, after all fixes.
- `gates-green-before-push`: every runnable gate, including pending ones, exited 0 on the pushed tree. Skip one only while its tool or manifest does not exist, and say so.
- `reply-matches-action`: each reply states what was done: a sha containing the fix, an issue number for a deferral, or reasons for a pushback.
- `resolve-by-rule`: resolve only fixed, outdated, or agreed-deferral threads.
- `target-branch-only`: code changes land only on this PR's branch.
- `bounded-rounds`: gate-fix cycles stop at 3 rounds and end as `needs-human`.

Shared invariants:
- `explicit-staging`: stage only manifest paths, by explicit path.
- `base-untouched`: never commit or push to `main`.
- `fail-closed-reads`: an API error is never "nothing there".
- `complete-listings`: paginate to the end or stop.
- `truthful-report`: report only what happened. A gate that did not run is absent, not passed.
- `status-preserved`: never lose a command's exit status to a pipe, filter or guard.
- `attribution-policy`: commits and PR text follow `commits.attribution: none`. Add nothing and drop nothing.
- `run-result-written`: write `$GAAL_RUN_DIR/result.json` on every exit path.

## Forbidden actions

Blueprint:
- `push-red`: pushing a branch with a failing gate to clear comments.
- `piecemeal-push`: pushing once per comment instead of once per round.
- `resolve-pushback`: resolving a thread where the revision disagreed with the reviewer.
- `resolve-unagreed-deferral`: resolving a deferral only the reviser decided on. A deferral with no issue number is a pushback in disguise.
- `apply-unreproduced-import`: applying an imported finding that does not reproduce on this branch.
- `collapse-with-open-threads`: collapsing while any thread on this PR will remain open.
- `pull-after-collapse`: pulling into a checkout after a collapse. Hard-reset it to the remote instead.

Shared:
- `bare-force-push`: force-pushing without `--force-with-lease=<branch>:<sha>` on the inspected sha.
- `admin-bypass`: merging, pushing or rewriting with admin privileges to get around branch protection or a verification hook.
- `machine-specific-paths`: hard-coding a person's home directory, private scripts or services.
- `commit-foreign-edits`: committing changes this run did not make.

Also never use `--force`, `-f`, `--no-verify`, `--admin`, `git add -A`, `git add .` or `git commit -a`.
