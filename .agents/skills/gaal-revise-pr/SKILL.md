---
name: gaal-revise-pr
description: Revises an open pull request in 116-Labs/cuecal after review. It addresses every unresolved review thread and every actionable request in a review body with a code fix or a reasoned reply, runs the profile gates (`uv run ruff check .`, `uv run pytest`), pushes once per round, replies to and resolves threads by rule, keeps the PR description true to the new head, and writes the run result to `$GAAL_RUN_DIR/result.json`. Use when a dispatch hands you a repo and PR number and asks for the `revise-pr` step, including imported feedback from another PR, a comment URL, or free-text notes. Do not use to open a PR, implement an issue, review a PR, or merge; those are other steps. Do not use when no PR can be determined; end as `needs-clarification` instead of guessing.
---
<!-- gaal-stamp blueprint=revise-pr@1.4.0 shared=1.3.0 profile=7d4c49f36df8465f generated=2026-10-01 content=590f4e87c2fcd6b9 -->

# gaal-revise-pr

Close the review loop on an open PR in `116-Labs/cuecal`. Every unresolved thread, and every actionable request in a review body, gets a code change or a reasoned reply. The branch is pushed once per round with green gates. Threads end in a state that matches what was done. The PR description describes the head that was pushed. Then review is requested again.

## Run context

- The dispatch gives the repo (`116-Labs/cuecal`) and the PR number. It may also give imported feedback: threads from another PR, a single comment URL, or free-text notes.
- The run context gives the literal values of `GAAL_RUN_ID` and `GAAL_RUN_DIR`. In every command below, `<run-dir>` stands for the literal run directory path from the run context. Type the real path, never a variable. The run id goes into `result.json` as a literal string.
- Commands run headless and anything outside the allowlist is refused. Allowed: `git`, `gh`, `mkdir`, `mv`, `cp`, `ls`, `cat`, `date`, `pwd` with any arguments, plus exactly `uv run ruff check .` and `uv run pytest`.
- Run one command per call. Do not chain with `&&`, `;` or `|`. Do not use `$VAR`, `$(...)`, backticks, `NAME=value` prefixes or shell redirection.
- Write files with the file-editing tool. Scratch files and throwaway worktrees live inside `<run-dir>`, never in `/tmp`.
- The profile names no `install` commands and no preflight. Install nothing. Use the checkout's existing install and run the gates in the checkout itself. A throwaway worktree has no install, so never run gates there.

Project facts used below:

- Tracker: GitHub, `116-Labs/cuecal`. Default branch `main`.
- Branch prefix: `gaal/`.
- Commit convention: conventional. Attribution: `none`.
- Merge: squash, no queue, `message_source: commits`, no auto-merge.
- Review: 1 required approval; open threads do not block merge (`threads_block_merge: false`); `reviewers: []`.
- Round limit: `limits.revise_rounds` = 3.

## Steps

### 1. Start the clock and the manifest

1. Read the start time: `date -u +%Y-%m-%dT%H:%M:%SZ`. Keep it as `started_at`.
2. Run `mkdir -p <run-dir>/scratch`.
3. Keep a manifest: the list of paths this run writes. Stage only from it (`explicit-staging`).

### 2. Identify and confirm the PR

1. If the dispatch gives no PR number and none can be determined, do not guess. End as `needs-clarification` (step 15).
2. Read the PR: `gh pr view <pr> --repo 116-Labs/cuecal --json number,state,body,headRefName,headRefOid,baseRefName,isCrossRepository,commits,closingIssuesReferences`.
3. A failed call is a failure, not an empty answer. On an API error, auth expiry or rate limit, stop and end as `failed` (`fail-closed-reads`, `status-preserved`).
4. If `state` is not `OPEN`, end as `failed` with reason "PR is not open".
5. If `isCrossRepository` is true, the branch lives on a fork. You cannot push to it, so end as `needs-human` with that reason.
6. Record the head branch name, the head sha and the linked issue number. The linked issue comes from `closingIssuesReferences`; if that is empty, apply the issue-link rule's reading order to the PR body, then each commit message. Reading the link extracts only the number.
7. All code changes land only on this PR's branch (`target-branch-only`). Never commit or push to `main` (`base-untouched`). If the head branch is `main`, end as `failed`.

### 3. Check out the PR head

1. Run `git status --porcelain`. If the checkout has changes this run did not make, leave them alone. Never stage or commit them (`commit-foreign-edits`). If they block the checkout, end as `needs-human`.
2. Run `git fetch origin <branch>`.
3. Run `git checkout <branch>`.
4. If the local branch differs from the remote head and the extra commits are not already on the remote, back them up to a branch ref and verify it before resetting. Then run `git reset --hard origin/<branch>`. If the local edits are of unknown origin, end as `needs-human`.
5. Confirm `git rev-parse HEAD` equals the head sha from step 2. If not, re-read the PR; the head moved.
6. Do not install dependencies. Use the checkout's existing install.

### 4. Collect every unresolved review thread

1. Use GraphQL, which exposes resolution state and thread ids. Write the query with literal values and no `$` variables. For the first page run:

   `gh api graphql --raw-field query='query { repository(owner: "116-Labs", name: "cuecal") { pullRequest(number: <pr>) { reviewThreads(first: 100) { pageInfo { hasNextPage endCursor } nodes { id isResolved isOutdated path line comments(first: 50) { nodes { databaseId author { login } body url } } } } } } }'`

2. While `hasNextPage` is true, repeat with `reviewThreads(first: 100, after: "<endCursor>")`. Paginate to the end (`complete-listings`). If a page fails, stop and end as `failed` (`fail-closed-reads`).
3. Keep every thread with `isResolved: false`. Record each thread's `id` and the `databaseId` of its first comment now, before any history rewrite (history rewrites mark threads outdated). Tag each as source `this-pr`.
4. A thread whose comments hold more than 50 entries needs its own paginated read; do not trust a truncated list.

### 5. Collect actionable review-body requests

1. List the reviews: `gh api repos/116-Labs/cuecal/pulls/<pr>/reviews --paginate`.
2. Read the body of the latest review from each reviewer. Also read any earlier review body whose requests were never answered.
3. A review body has no thread. Make each actionable request an item tagged `review-body`. That means a change asked for, or a finding listed only in the body. Skip pure verdicts, praise, and requests already answered by a later commit or comment.
4. Also list the PR's issue-level comments with `gh api repos/116-Labs/cuecal/issues/<pr>/comments --paginate` to see which requests were already answered.

### 6. Bring in imported feedback, if any

- **Another PR's threads:** read them the same way as step 4 using that PR's number. Tag each `import`.
- **A comment URL:** check its shape first. A `#discussion_r<id>` URL is a review comment and has a thread. A `#issuecomment-<id>` URL is an issue-level comment and has no thread, so extract no thread id; treat it as a `review-body`-style item answered by a PR comment.
- **Free text notes:** each distinct request is one item tagged `import`.
- **Re-verify each imported item against this branch.** Read the code and, when it helps, reproduce it with the existing gates. Classify each as reproduces, partly applies, or does not apply. Never apply a finding that does not reproduce here (`apply-unreproduced-import`). Answer it with the reason instead.

### 7. Decide each item

For every item (thread, `review-body`, import) choose one:

- **fix:** change code or docs on this branch.
- **answer:** the item is a question or needs an explanation.
- **defer:** file a follow-up issue first, with `gh issue create --repo 116-Labs/cuecal --title <title> --body-file <run-dir>/scratch/<file>.md`. File it unassigned and with no milestone, so it lands in the backlog. Then ask for agreement on the thread. A deferral without an issue number is a pushback in disguise.
- **push back:** disagree, with reasons.

If a request is so ambiguous that any fix would be a guess, stop and end as `needs-clarification`. Put the quoted thread in `questions`.

A `review-body` deferral has no thread to carry agreement, so it is never resolved. Its reply names the follow-up issue.

### 8. Make all fixes

1. Edit files with the file tool. Record each written path in the manifest.
2. For an imported item, the fix lands only on this branch (`target-branch-only`); the reply names where it landed.
3. Do all fixes for the round before running gates or pushing.

### 9. Run every gate

Run each gate as its own command, in the checkout, exactly as written.

1. `date -u +%s` (start).
2. `uv run ruff check .` (gate `lint`, required).
3. `date -u +%s` (end). `duration_ms` is (end minus start) times 1000.
4. `date -u +%s` (start).
5. `uv run pytest` (gate `test`, required).
6. `date -u +%s` (end).

Record the exact command, the exit code and the duration of every gate that ran. A gate that did not run is absent from the result, not recorded as passed (`truthful-report`). Check the exit status of each gate; do not let a pipe or filter hide it (`status-preserved`).

On a failure, fix it, add the paths to the manifest, and run both gates again. Each full pass of both gates after fixes is one attempt. When the third attempt (`limits.revise_rounds` = 3) is still red, stop without pushing and end as `needs-human` (`bounded-rounds`). If the red traces to code this PR did not touch, say it is pre-existing. Never push to clear comments while a required gate is red (`push-red`).

### 10. Commit and push once

1. If nothing changed, skip to step 12: nothing is pushed and `commit_sha` is the unchanged head.
2. Stage by explicit path from the manifest: `git add <path> <path>`. Never stage everything wholesale (`explicit-staging`). After staging, run `git status --porcelain` and confirm no other change this run is responsible for is left.
3. Write the commit message to `<run-dir>/scratch/commit-msg.txt` with the file tool. It uses conventional format, for example `fix(scope): address review feedback`. Attribution is `none`: add no co-author or generated-by line (`attribution-policy`).
4. Commit with `git commit -F <run-dir>/scratch/commit-msg.txt`. Hooks stay enabled. If a hook rejects the commit, fix what it reports and commit again. Never skip, redirect or retry around a hook, and never touch the hooks directory or `.git/config` (`bypass-hook`). If the fix is beyond this run, end as `failed` naming the hook and quoting its output briefly.
5. Run `git rev-parse HEAD` and keep the fix sha.
6. Push the branch once: `git push origin <branch>`. If the push is rejected as non-fast-forward, fetch and re-inspect; never force it. Hooks stay enabled here too. A failed push is seen and handled: end as `failed` if the push fails, or `needs-human` if a conflict or permission problem blocks it. Push once per round, after all fixes (`one-push-per-round`, `piecemeal-push`). Every required gate must have exited 0 on this exact tree (`gates-green-before-push`).

### 11. Settle the issue link and decide on collapse

Settle the link before any collapse, because the commit message and the PR body must carry the same link.

1. Decide whether a collapse will run. It runs only if both are true:
   - Every thread on this PR will be resolved after the replies (step 13). A pushback or an unagreed deferral leaves a thread open, so no collapse (`collapse-with-open-threads`).
   - `merge.message_source` is `commits`. It is, so only the thread condition matters.
2. Settle the link under the shared issue-link rule:
   - A round that completes deferred criteria updates the **Deferred** list.
   - A round that completes the last deferred criterion turns `Refs #N` into `Closes #N` and drops the **Deferred** list.
   - A **Deferred** list appears only under `Refs`, and a closing keyword never sits next to one.
3. If no collapse will run, leave the link and the **Deferred** list unchanged and say so in the round's reply.

### 12. Collapse to one commit (PR mode), when step 11 says so

Collapse only on the final round, in PR mode, with the routine's safety gates in order. `commits.single_commit` is true. This collapse push follows the fix push from step 10 on purpose: the collapse reads the remote head, so the fix must land first.

1. **Regime:** `merge.message_source` is `commits`, so collapsing applies.
2. **Idempotence:** run `git rev-list --count origin/main..origin/<branch>` after `git fetch origin`. With 0 or 1 commits, there is nothing to do.
3. **Target:** PR mode. Read the remote head with `git ls-remote origin refs/heads/<branch>` and check it equals the sha you pushed in step 10.
4. **Soft gates:** an approval may be dismissed (required approvals is 1; an unreadable setting counts as yes). Unresolved threads exist now, because the threads just fixed resolve only after the push. Knowingly override these, print the unresolved count, and say so in the report.
5. **Hard gates, never overridden:** the branch is not on a fork (checked in step 2), and every commit on it is authored by the same person as the PR author or this run. Check with `git log --format=%an%x09%H origin/main..origin/<branch>`. A commit by someone else ends the collapse. The remote head must be an ancestor of what will be pushed. Check with `git merge-base --is-ancestor`.
6. **Rewrite in a throwaway worktree:**
   - `git worktree add --detach <run-dir>/worktree <remote-head-sha>`
   - `cd <run-dir>/worktree`
   - Record the pre-collapse tree with `git rev-parse HEAD^{tree}`.
   - `git reset --soft <merge-base-sha>` where the merge base comes from `git merge-base origin/main <remote-head-sha>`.
   - Write the single message as a whole for the change to `<run-dir>/scratch/collapse-msg.txt`: conventional format, process commits dropped, no attribution, and the issue link settled in step 11 (`Closes #N`, or `Refs #N` on its own line with a **Deferred** list).
   - `git commit -F <run-dir>/scratch/collapse-msg.txt`, hooks enabled.
7. **Content preservation:** the new commit's tree hash (`git rev-parse HEAD^{tree}`) must equal the pre-collapse tree hash. If the rewrite nets to an empty change or the hashes differ, abort before pushing.
8. **Push with a lease on the inspected sha:** `git push --force-with-lease=<branch>:<remote-head-sha> origin HEAD:refs/heads/<branch>`. On failure, restore the previous HEAD and end as `failed` ("the collapse refused"). Remove the worktree on every exit path with `git worktree remove --force <run-dir>/worktree`, after changing back to the checkout with `cd`.
9. **Stale checkout:** after a collapse, never pull. In the checkout run `git fetch origin`, then `git reset --hard origin/<branch>` (`pull-after-collapse`). Local-only commits are first backed up to a branch ref and verified. Uncommitted edits of unknown origin stop the run for a human.
10. Keep `commit_sha` as the new head from `git rev-parse HEAD`. The report lists mode, commit count before and after, tree hash, old and new sha, and any backup ref.

If a thread will stay open, keep the fixup commit separate so the reviewer can diff only the delta.

### 13. Reply to every item, then resolve by rule

Write every reply body to `<run-dir>/scratch/<name>.md` with the file tool.

1. **Thread replies.** Reply to every unresolved thread through its reply relation, which also works on outdated threads. Use the first comment's `databaseId` recorded in step 4:

   `gh api repos/116-Labs/cuecal/pulls/<pr>/comments/<comment-id>/replies --field body=@<run-dir>/scratch/<name>.md`

   Each reply says what was actually done (`reply-matches-action`, `every-thread-answered`):
   - **Fix:** name the sha that contains it. After a collapse, that is the collapsed head sha. Write "Fixed in `<sha>`" only when that sha contains the fix (`truthful-report`).
   - **Deferral:** name the follow-up issue number, filed first.
   - **Pushback:** give the reasons.
   - **Import that did not apply:** give the reason. The reviewer is owed it. For an imported fix, name where it landed.
2. **Review-body items.** Answer all of them in one PR comment: `gh pr comment <pr> --repo 116-Labs/cuecal --body-file <run-dir>/scratch/body-answers.md`. Quote or name each request and give its decision: a sha, an issue number, or reasons (`body-requests-answered`). A request in a review body is owed the same reply as one in a thread.
3. **Resolve by rule** (`resolve-by-rule`). Resolve a thread only if it was fixed, is outdated, or was deferred with agreement recorded on the thread:

   `gh api graphql --raw-field query='mutation { resolveReviewThread(input: {threadId: "<thread-id>"}) { thread { isResolved } } }'`

   - Leave pushbacks open for the reviewer (`resolve-pushback`).
   - Leave deferrals open when the reviewer has not agreed on the thread (`resolve-unagreed-deferral`).
   - Review-body items have nothing to resolve.
   - A failure to resolve a thread on another PR for lack of permission is not a blocker; the reply is what matters.
4. Use the thread ids recorded in step 4, since a history rewrite marks threads outdated.
5. Verify each write succeeded; an unseen failed API write is not allowed (`status-preserved`).

### 14. Update the PR description to match the head

Skip this step when the round changed no code and no claim in the description became false. Otherwise:

1. Read the current body with `gh pr view <pr> --repo 116-Labs/cuecal --json body`.
2. Re-read it against the pushed tree and this round's outcome: the summary, the test plan, and any test count, gate result or behavioural claim that the round changed. Check these after the last push, not before, because counts and claims go stale across rounds.
3. Edit only what is now false or missing. Keep the issue reference, and keep it identical to the head commit's link as settled in step 11. Do not rewrite untouched prose. No attribution section is added: `commits.attribution` is `none`.
4. A **Deferred** list appears only under `Refs`. Under `Closes` there is none. No `Refs` with a **Deferred** list remains once every criterion is met, unless no collapse could carry the change into the commit message and the reply says so (`description-matches-head`).
5. Write the body to `<run-dir>/scratch/pr-body.md` with the file tool, then run `gh pr edit <pr> --repo 116-Labs/cuecal --body-file <run-dir>/scratch/pr-body.md`. Editing the description pushes nothing. Do it before review is re-requested.

### 15. Request review again

`review.reviewers` is empty and the profile names no other re-request mechanism, so request re-review from each login that submitted a review on this PR (taken from step 5): `gh pr edit <pr> --repo 116-Labs/cuecal --add-reviewer <login>`. If there are none, or the request fails, post a short PR comment saying the revision is pushed and ready for another look. Do not invent a service or command. Merging is not part of this step, and no auto-merge is set.

### 16. Write the run result

Write the result on every exit path, including failures (`run-result-written`).

1. Read the finish time: `date -u +%Y-%m-%dT%H:%M:%SZ`.
2. Write `<run-dir>/result.json.tmp` with the file tool. Contents:
   - `schema_version`: `1`
   - `run_id`: the literal `GAAL_RUN_ID` value from the run context
   - `blueprint`: `revise-pr`
   - `blueprint_version`: `1.4.0`
   - `repo`: `116-Labs/cuecal`
   - `issue`: the linked issue number, or `null`
   - `pr`: the PR number, or `null` when none was determined
   - `status`: one of `done`, `needs-human`, `needs-clarification`, `failed`
   - `reason`: required unless `done`. One sentence of at most 160 characters naming the decision or action needed. Detail goes in the PR comment and the final message.
   - `questions`: required and non-empty for `needs-clarification`; quote the thread.
   - `attempts`: the gate-fix attempts used, a positive integer (at least 1)
   - `gates`: one entry per gate that ran, each with `name`, `command`, `exit_code`, `duration_ms`. Empty when nothing needed changing.
   - `branch`: the PR head branch, or `null`
   - `commit_sha`: the 40-hex PR head after the run (the unchanged head when nothing was pushed), or `null`
   - `started_at` and `finished_at`: the timestamps read from `date`
   - No other keys.
3. Move it into place: `mv <run-dir>/result.json.tmp <run-dir>/result.json`. Never leave the `.tmp` file behind.
4. In the final message, give a table with one row per item: source, decision, and sha or issue. Open pushbacks are normal and listed. Report the collapse details if one ran.

## Exit states

- `done`: Every thread and every actionable review-body request is answered, the description matches the head, and the branch is pushed with green gates. `commit_sha` is the PR head after the run. When nothing needed changing, it is the unchanged head, nothing was pushed, and `gates` may be empty. Open pushbacks are normal.
- `needs-clarification`: No PR could be determined, or a reviewer's request is so ambiguous that any fix would be a guess. `questions` quote the thread.
- `needs-human`: The round limit of 3 was reached with red gates, or a conflict, fork or permission problem blocks the push, or local edits of unknown origin stop a reset. `reason` names it.
- `failed`: The PR is not open, an API read failed, a hook rejected a commit beyond this run's remit, the push failed, or the collapse refused. `reason` names the step. Gates already red on the base are reported as pre-existing.

## Invariants

- `every-thread-answered`: Every unresolved thread at the start of the run has a reply at the end, including imports that did not apply.
- `one-push-per-round`: The branch is pushed once per round, after all fixes.
- `gates-green-before-push`: Every required gate (`lint`, `test`) exited 0 on the tree that was pushed.
- `reply-matches-action`: Each reply describes what was done: a sha containing the fix, an issue number for a deferral, reasons for a pushback.
- `resolve-by-rule`: A thread is resolved only if fixed, outdated, or deferred with agreement recorded on the thread.
- `target-branch-only`: Code changes land only on this PR's branch. A fix for an imported item names where it landed.
- `bounded-rounds`: Gate-fix cycles stop at 3 (`limits.revise_rounds`), ending as `needs-human`.
- `body-requests-answered`: Every actionable request in a latest review body is acted on or answered in a PR comment with the reason.
- `description-matches-head`: After a round that changed behaviour, tests or gate results, the PR description states nothing the pushed head contradicts, and its issue link matches the head commit's. It is edited before review is re-requested.
- `explicit-staging`: Stage only manifest paths. Never stage everything wholesale.
- `base-untouched`: Never commit or push to `main`.
- `fail-closed-reads`: An API error, auth expiry or rate limit stops the run. It is never read as "no threads" or "no PR".
- `complete-listings`: Threads, reviews, comments and checks are paginated to the end, or the run stops.
- `truthful-report`: The report and result describe what happened. A gate that did not run is absent. "Fixed in `<sha>`" appears only when that sha contains the fix.
- `status-preserved`: A command's success or failure is never lost to a pipe, filter or guard.
- `attribution-policy`: `commits.attribution` is `none`. Add no attribution line to commit messages or PR bodies.
- `run-result-written`: `result.json` is written atomically on every exit path.

## Forbidden actions

- `push-red`: Pushing a branch with a failing required gate to clear comments.
- `piecemeal-push`: Pushing once per comment instead of once per round.
- `resolve-pushback`: Resolving a thread where the revision disagreed with the reviewer.
- `resolve-unagreed-deferral`: Resolving a deferral that only the reviser decided on. A deferral with no issue number is a pushback in disguise.
- `apply-unreproduced-import`: Applying an imported finding that does not reproduce on this branch.
- `collapse-with-open-threads`: Collapsing while any thread on this PR will remain open.
- `pull-after-collapse`: Pulling into a checkout after a collapse. Hard-reset it to the remote instead.
- `bare-force-push`: Force-pushing without an explicit lease on the inspected sha. Only `--force-with-lease=<branch>:<sha>` is acceptable.
- `admin-bypass`: Merging, pushing or rewriting with admin privileges to get around branch protection or a verification hook.
- `bypass-hook`: Committing or pushing with the repository's verification skipped or redirected, changing where git looks for hooks, switching a hook manager off, or retrying a rejected commit or push through another route. Fix what the hook reports.
- `machine-specific-paths`: Hard-coding a person's home directory, private scripts or services.
- `commit-foreign-edits`: Committing changes this run did not make.
