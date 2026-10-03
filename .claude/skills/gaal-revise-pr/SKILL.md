---
name: gaal-revise-pr
description: Revises an open pull request in 116-Labs/cuecal after review. It addresses every unresolved review thread, every actionable request in a review body, and every request made on the linked issue since the PR opened with a code fix or a reasoned reply, runs the profile gates (`uv run ruff check .`, `uv run pytest`), pushes once per round, replies to and resolves threads by rule, keeps the PR description true to the new head, and writes the run result to `$GAAL_RUN_DIR/result.json`. Use when a dispatch hands you a repo and PR number and asks for the `revise-pr` step, including imported feedback from another PR, a comment URL, or free-text notes. Do not use to open a PR, implement an issue, review a PR, or merge; those are other steps. Do not use when no PR can be determined; end as `needs-clarification` instead of guessing.
---
<!-- gaal-stamp blueprint=revise-pr@1.7.0 shared=1.4.0 profile=7d4c49f36df8465f generated=2026-10-03 core=b92499e6abdd3fda forbidden=df8e4e73381d2451 content=9b7bc835788bb6e0 -->

# gaal-revise-pr

Close the review loop on an open PR in `116-Labs/cuecal`. Every unresolved thread, every actionable request in a review body, and every request made on the linked issue since the PR opened gets a code change or a reasoned reply. The branch is pushed once per round with green gates. Threads end in a state that matches what was done. The PR description describes the head that was pushed. Then review is requested again.

## Run context

- The dispatch gives the repo (`116-Labs/cuecal`) and the PR number. If no PR can be determined, end as `needs-clarification` without guessing. The dispatch may also provide optional imported feedback: threads from another PR, a single comment URL, or free-text notes.
- The run context provides the literal values of `GAAL_RUN_ID` and `GAAL_RUN_DIR`. In every command and file path below, `<run-dir>` stands for the literal run directory path from the run context. Type the real path, never an environment variable. The run id goes into `result.json` as a literal string.
- Commands run headless without interactive prompts. Anything outside the allowlist is refused. Allowed commands: `git`, `gh`, `mkdir`, `mv`, `cp`, `ls`, `cat`, `date`, `pwd` with any arguments, plus exactly `uv run ruff check .` and `uv run pytest`.
- Run one command per call. Do not chain commands with `&&`, `;` or `|`. Do not use `$VAR`, `${VAR}`, `$(...)`, backticks, `NAME=value` prefixes, or shell redirection.
- Write and edit files using the file tools, never through shell redirection. Pass text files to commands: `git commit -F <file>`, `--body-file <file>` for `gh pr` / `gh issue` commands, and `-F body=@<file>` for `gh api`. Scratch files and throwaway worktrees live inside `<run-dir>`, never in `/tmp`.
- The profile names no `install` commands and no preflight. Install nothing. Use the checkout's existing install and run all gates directly in the checkout. A throwaway worktree has no environment install, so never run gates inside a worktree.

Project facts used below:

- Tracker: GitHub, `116-Labs/cuecal`. Default branch: `main`.
- Branch prefix: `gaal/`.
- Commit convention: conventional. Attribution: `none` (`commits.attribution`).
- Merge: squash, no queue (`queue: false`), `message_source: commits`, auto-merge off (`auto: false`).
- Review: 1 required approval (`review.required_approvals: 1`); open threads do not block merge (`threads_block_merge: false`); `reviewers: []`; start signal reaction (`start_signal: reaction`). Protection facts `dismiss_stale_approvals` and `require_last_push_approval` are absent from the profile.
- Round limit: `limits.revise_rounds` = 3.

## Steps

### 1. Start the clock and the manifest

1. Read the start time: `date -u +%Y-%m-%dT%H:%M:%SZ`. Keep it as `started_at`.
2. Run `mkdir -p <run-dir>/scratch`.
3. Keep a manifest of paths this run writes. Stage only paths from this manifest (`explicit-staging`).

### 2. Identify and confirm the PR

1. If the dispatch gives no PR number and none can be determined, do not guess. End as `needs-clarification` (step 16).
2. Read the PR: `gh pr view <pr> --repo 116-Labs/cuecal --json number,state,body,headRefName,headRefOid,baseRefName,isCrossRepository,commits,closingIssuesReferences,createdAt`.
3. A failed API call is an error, not an empty answer. On an error, auth expiry or rate limit, stop and end as `failed` (`fail-closed-reads`, `status-preserved`).
4. If `state` is not `OPEN` (closed or merged), end as `failed` with reason "PR is not open".
5. If `isCrossRepository` is true, the branch lives on a fork. Pushing to it is not supported; end as `needs-human` with that reason.
6. Record the head branch name, head sha, PR `createdAt` timestamp, and the linked issue numbers. Linked issues come from `closingIssuesReferences`; if that is empty, apply the issue-link rule's reading order to the PR body, then to each commit message (`git log --format=%B origin/main..<head-sha>` after fetching). Extract only the issue numbers.
7. All code changes land only on this PR's branch (`target-branch-only`). Never commit or push to `main` (`base-untouched`). If the head branch is `main`, end as `failed`.

### 3. Check out the PR head

1. Run `git status --porcelain`. If the checkout has changes this run did not make, leave them alone. Never stage or commit them (`commit-foreign-edits`). If foreign edits block the checkout, end as `needs-human`.
2. Run `git fetch origin <branch>`.
3. Run `git checkout <branch>`.
4. If the local branch differs from the remote head and the extra commits are not already on the remote, back them up to a branch ref and verify it before resetting. Then run `git reset --hard origin/<branch>`. If uncommitted edits of unknown origin exist, end as `needs-human`.
5. Confirm `git rev-parse HEAD` equals the remote head sha from step 2. If not, re-read the PR; the head moved.
6. Do not install dependencies. Use the checkout's existing install.

### 4. Collect every unresolved review thread

1. Use GraphQL, which exposes resolution state and thread IDs. Write queries with literal values and no `$` variables. For the first page, run:

   `gh api graphql --raw-field query='query { repository(owner: "116-Labs", name: "cuecal") { pullRequest(number: <pr>) { reviewThreads(first: 100) { pageInfo { hasNextPage endCursor } nodes { id isResolved isOutdated path line comments(first: 50) { nodes { databaseId author { login } body url } } } } } } }'`

2. While `hasNextPage` is true, repeat with `reviewThreads(first: 100, after: "<endCursor>")`. Paginate to the end (`complete-listings`). If a page fails, stop and end as `failed` (`fail-closed-reads`).
3. Keep every thread with `isResolved: false`. Record each thread's `id` and the `databaseId` of its first comment now, before any history rewrite (rewriting history marks threads outdated). Tag each item as source `this-pr`.
4. If a thread's comments hold more than 50 entries, paginate its comments to the end; do not trust truncated listings.

### 5. Collect review-body requests and linked issue requests

1. **Review-body requests:**
   - List the reviews: `gh api repos/116-Labs/cuecal/pulls/<pr>/reviews --paginate` (`complete-listings`).
   - Read the body of the latest review from each reviewer, plus any earlier review body whose requests were never answered.
   - Reviewers sometimes list real findings only in the review body where no thread exists. Make each actionable request (a change asked for, a finding listed only in the body) an item tagged `review-body` (`body-requests-answered`). Skip pure verdicts, praise, and requests already answered by a later commit or comment.
   - List the PR's issue-level comments with `gh api repos/116-Labs/cuecal/issues/<pr>/comments --paginate` to verify which requests were already answered.
2. **Linked issue requests:**
   - Maintainers ask for changes on the issue as often as on the PR: "also handle X" in a comment, or a criterion added to the body. Read both since the PR opened, otherwise the PR converges on the old scope.
   - For each linked issue from step 2, read its body fresh: `gh issue view <issue> --repo 116-Labs/cuecal --json body,createdAt` and list its comments: `gh api repos/116-Labs/cuecal/issues/<issue>/comments --paginate` (`complete-listings`).
   - Note when the PR was created, and when Gaal's newest done implement run for the issue started (the creation timestamp of its `Gaal finished implement …: done.` comment on the issue). Requests count from the earlier of the two timestamps.
   - Every comment created after that cutoff by the issue's author or a maintainer (an admin of `116-Labs/cuecal`), and every edit of the issue body since then by one of them, is a request.
   - Read issue body edits over GraphQL: `gh api graphql --raw-field query='query { repository(owner: "116-Labs", name: "cuecal") { issue(number: <issue>) { userContentEdits(first: 100) { nodes { editedAt editor { login } diff } } } } }'`.
   - Skip comments carrying a `<!-- gaal:` marker, bot comments and bot edits, and requests a PR comment already answers.
   - Skip body edits whose changes lie entirely inside a marked plan-drift section (every added or removed line falls between an opening `<!-- gaal:plan-drift -->` and closing `<!-- /gaal:plan-drift -->` marker line: implement's record is not a request; an edit with any changed line outside such a section is a request).
   - Each actionable request (a change asked for in a comment, a criterion or requirement an edit added or changed) becomes an item tagged `issue-request` (`issue-requests-answered`). A comment that asks for nothing (a status note, thanks) is not an item.

### 6. Bring in and re-verify imported feedback, if any

1. Read imported feedback from dispatch according to its shape:
   - **Another PR's threads:** Read them via GraphQL as in step 4 using that PR's number. Tag each `import`.
   - **A comment URL:** Check its shape first. A `#discussion_r<id>` URL is a review comment and has a thread. A `#issuecomment-<id>` URL is an issue-level comment with no thread; treat it as a `review-body`-style item answered by a PR comment.
   - **Free-text notes:** Each distinct request is one item tagged `import`.
2. **Re-verify each imported item against this branch:** Read the code and verify whether it reproduces, partly applies, or does not apply. Never apply an imported finding that does not reproduce on this branch (`apply-unreproduced-import`). Answer it with the reason instead.

### 7. Decide each item

For every item (review thread, `review-body`, `issue-request`, or `import`), choose one decision:

- **fix:** Change code or tests on this branch.
- **answer:** The item is a question or needs an explanation.
- **defer:** A follow-up issue under the shared follow-up bar (file a follow-up issue only for a user-visible defect outside the diff that reproduces on `main`). File it with `gh issue create --repo 116-Labs/cuecal --title "<title>" --body-file <run-dir>/scratch/<file>.md` unassigned and with no milestone, so it lands in the backlog. Then request agreement on the thread. A deferral without an issue number and agreed owner is a pushback.
- **push back:** Disagree, with reasons.

Rules for decisions:
- Deferral and pushback have opposite outcomes: an agreed deferral is resolved, while a pushback remains open for the reviewer (`resolve-pushback`, `resolve-unagreed-deferral`).
- A `review-body` or `issue-request` item is decided the same way. Because there is no thread to carry agreement, a deferral there is not resolved and its follow-up issue is named in the reply comment.
- An `issue-request` that widens the issue beyond what this PR can reasonably carry is deferred rather than folded in: file a follow-up issue only when the shared follow-up bar is met, otherwise answer with the reason in the PR comment.
- If a request is so ambiguous that any fix would be a guess, stop and end as `needs-clarification`. Put the quoted request in `questions`.

### 8. Make all fixes

1. Edit files using the file tools. Record each written path in the manifest.
2. For an imported item, the fix lands only on this branch (`target-branch-only`); the reply names where it landed.
3. Complete all fixes for the round before running gates or pushing.

### 9. Run every gate

Run each required gate as its own command, in the checkout, exactly as written:

1. `date -u +%s` (start).
2. `uv run ruff check .` (gate `lint`, required).
3. `date -u +%s` (end). `duration_ms` is (end minus start) times 1000.
4. `date -u +%s` (start).
5. `uv run pytest` (gate `test`, required).
6. `date -u +%s` (end). `duration_ms` is (end minus start) times 1000.

Record the exact command, exit code, and duration of every gate that ran. A gate that did not run is absent from the result, not recorded as passed (`truthful-report`). Check the exit status of each command; never let a pipe hide a failure (`status-preserved`).

On a failure, fix the cause, add the changed paths to the manifest, and run both gates again. Each full pass of both gates after fixes is one attempt. When the 3rd attempt (`limits.revise_rounds` = 3) is still red, stop without pushing and end as `needs-human` (`bounded-rounds`). If the failure traces to code this PR did not touch, report it as pre-existing. Never push while a required gate is red (`push-red`).

### 10. Commit fixes, check base drift, and push once

1. If nothing changed and no base drift occurred, skip to step 12: nothing is pushed and `commit_sha` is the unchanged head.
2. Stage by explicit path from the manifest: `git add <path> <path>` (`explicit-staging`). After staging, run `git status --porcelain` and confirm no other change this run is responsible for remains unstaged.
3. Write the commit message to `<run-dir>/scratch/commit-msg.txt` with the file tool. It uses conventional format, for example `fix(scope): address review feedback`. Attribution is `none`: add no co-author or AI provenance line (`attribution-policy`).
4. Commit with `git commit -F <run-dir>/scratch/commit-msg.txt`. Hooks stay enabled. If a hook rejects the commit, fix what it reports and commit again. Never skip or redirect hooks (`bypass-hook`). If the fix is beyond this run, end as `failed` naming the hook and quoting its output briefly.
5. Record the fix sha: `git rev-parse HEAD`.
6. **Check for base drift before pushing (`base-drift-checked`):**
   - Run `git fetch origin main` and `gh pr view <pr> --repo 116-Labs/cuecal --json mergeable,mergeStateStatus,baseRefOid`. (If `mergeable` is `UNKNOWN`, wait briefly and query again).
   - Rebase only when: the PR is `CONFLICTING` or `DIRTY`, its `mergeStateStatus` is `BEHIND` (GitHub reports it only when the base requires branches to be up to date before merging), or it is a stacked PR whose parent has merged.
   - A base that merely moved while the PR stays `MERGEABLE` and is not `BEHIND` is not rebased onto: a rebase rewrites history the reviewer then has to range-diff.
   - If a rebase is required:
     - Capture thread IDs first (rewriting history marks threads outdated).
     - Record the head's tree before the rebase: `git rev-parse HEAD^{tree}` and the old head sha: `git rev-parse HEAD`.
     - Rebase onto the fresh base, keeping the branch's commits as they are (no merge commits): `git rebase origin/main`.
     - If the rebase conflicts, abort with `git rebase --abort` and end as `needs-human` naming the conflicting paths.
     - For a stacked PR whose parent merged, retarget its base: `gh pr edit <pr> --repo 116-Labs/cuecal --base main`.
     - Compare tree identity after rebase: record `git rev-parse HEAD^{tree}`. If the trees are equal, record `changes` as `tree unchanged`. If the trees differ, run `git range-diff <old-base>..<old-head> origin/main..HEAD` (every commit paired `=`) and keep the summary for `push.changes`.
     - Re-run every profile gate on the rebased tree (`uv run ruff check .`, `uv run pytest`). A gate that is red on the rebased tree ends as `needs-human` naming the gate and base sha, with nothing pushed: the branch and the new base disagree, which is a person's call.
7. **Push once (`one-push-per-round`, `piecemeal-push`, `bare-force-push`, `gates-green-before-push`):**
   - Push the branch once with an explicit lease on the inspected remote head sha: `git push origin <branch> --force-with-lease=<branch>:<remote-head-sha>` (or `git push origin <branch>` if fast-forward). Hooks stay enabled.
   - If the push fails, end as `failed` (or `needs-human` if blocked by permissions).
   - After the push, query `gh pr view <pr> --repo 116-Labs/cuecal --json mergeable,mergeStateStatus` again (wait briefly while `mergeable` is `UNKNOWN`).
   - If the PR is now `CONFLICTING` or `DIRTY`, do not push again (`one-push-per-round`): skip the step-11 collapse, proceed to step 12 replies, and end as `needs-human` naming the conflict.
   - A failed or unreadable check before push ends `needs-human` with nothing pushed; after push it is reported like a conflict.
8. Record the `push` details for the run result: `why` (one sentence explaining the fixes or rebase cause) and `changes` (`tree unchanged` or the range-diff summary) (`push-explained`).

### 11. Settle the issue link and decide on single-commit collapse

Settle the link before any collapse, because the commit message and PR body must carry the same link.

1. **Settle the link under the shared issue-link rule:**
   - Full change (all criteria met): `Closes #N`.
   - Partial change (criteria remaining): `Refs #N` on a line of its own, plus a **Deferred** heading listing open criteria as the issue words them.
   - A closing keyword never appears next to a **Deferred** list, and a **Deferred** list appears only under `Refs`.
   - A round that completes the last deferred criterion turns `Refs #N` into `Closes #N` and drops the list.
2. **Decide whether a collapse will run:**
   - A collapse runs only if all of the following hold:
     - Every thread on this PR will be resolved after replies (step 13). A pushback or an unagreed deferral leaves a thread open, so keep commits separate so the reviewer can diff only the delta (`collapse-with-open-threads`).
     - `merge.message_source` is `commits` (it is in `116-Labs/cuecal`).
     - **Approval preservation check (`content-free-push-after-approval`):** Read the reviews after step 10's push: `gh api repos/116-Labs/cuecal/pulls/<pr>/reviews --paginate` (`complete-listings`). Count reviewers whose latest review approves and is not dismissed. In this repository, protection facts `dismiss_stale_approvals` and `require_last_push_approval` are absent (which counts as true / unknown, so only approvals of the current head count). When the PR meets `review.required_approvals` (1 approval) on the current head and a content-free push would throw those approvals away, do not collapse: keep the commits as they are, state in the report that the collapse was skipped to preserve approvals, and note that whoever merges supplies the message. A round whose step-10 push carried fixes has already dismissed earlier approvals, so the collapse goes ahead.
3. **Execute single-commit collapse in PR mode (when approved by step 11.2):**
   - The fix push in step 10 has already landed, so the collapse reads the remote head.
   - **Idempotence:** Run `git fetch origin` and `git rev-list --count origin/main..origin/<branch>`. With 0 or 1 commit, there is nothing to collapse.
   - **Target:** PR mode. Read remote head with `git ls-remote origin refs/heads/<branch>` and verify it equals the sha pushed in step 10.
   - **Soft gates:** Override unresolved threads (which resolve in step 13) and print the unresolved count in the report.
   - **Hard gates (never overridden):** Confirm the branch is not on a fork, every commit is authored by the PR author or user (`git log --format=%an%x09%H origin/main..origin/<branch>`), and the remote head is an ancestor of what will be pushed (`git merge-base --is-ancestor`).
   - **Worktree rewrite:**
     - `git worktree add --detach <run-dir>/worktree <remote-head-sha>`
     - `cd <run-dir>/worktree`
     - Record pre-collapse tree hash: `git rev-parse HEAD^{tree}`.
     - Find merge base: `git merge-base origin/main <remote-head-sha>`.
     - `git reset --soft <merge-base-sha>`.
     - Write the single commit message for the change to `<run-dir>/scratch/collapse-msg.txt`: conventional format, process commits ("wip", "fix lint") dropped, attribution `none`, and the settled issue link (`Closes #N` or `Refs #N` with **Deferred** list).
     - Commit with `git commit -F <run-dir>/scratch/collapse-msg.txt`, hooks enabled.
   - **Content preservation:** `git rev-parse HEAD^{tree}` must equal the pre-collapse tree hash. If the hashes differ or the rewrite nets to an empty change, abort before pushing.
   - **Push with lease:** `git push --force-with-lease=<branch>:<remote-head-sha> origin HEAD:refs/heads/<branch>`. On failure, restore and end as `failed`.
   - Tear down the worktree on every exit path: `cd` back to checkout, then `git worktree remove --force <run-dir>/worktree`.
   - **Stale checkout:** In the checkout run `git fetch origin` and `git reset --hard origin/<branch>` (`pull-after-collapse`). Never use `git pull`.
   - Keep `commit_sha` as `git rev-parse HEAD`.
4. If no collapse runs, leave the issue link and **Deferred** list unchanged and say so in the round's reply.

### 12. Reply to every thread, review-body item, and issue request

Write all reply bodies to `<run-dir>/scratch/<name>.md` with the file tool.

1. **Thread replies:** Reply to every unresolved thread through its reply relation (works on outdated threads), using the first comment's `databaseId` from step 4 (`every-thread-answered`, `reply-matches-action`):

   `gh api repos/116-Labs/cuecal/pulls/<pr>/comments/<comment-id>/replies --field body=@<run-dir>/scratch/<name>.md`

   - **Fix:** Name the sha that contains it (the collapsed head sha after a collapse, or the fix sha). Write "Fixed in `<sha>`" only when that sha contains the fix (`truthful-report`).
   - **Deferral:** Name the follow-up issue number filed under the follow-up bar.
   - **Pushback:** Give the reasons.
   - **Import that did not apply:** Give the reason. For an imported fix, name where it landed (`target-branch-only`).
2. **Review-body and Issue-request replies:**
   - Answer all `review-body` items and `issue-request` items in one PR comment (`body-requests-answered`, `issue-requests-answered`):

     `gh pr comment <pr> --repo 116-Labs/cuecal --body-file <run-dir>/scratch/body-and-issue-answers.md`

   - Quote or link each request (issue requests by comment URL or edit timestamp) and state its decision: sha, follow-up issue number, or reasons.

### 13. Resolve threads by rule

Resolve threads using GraphQL (`resolve-by-rule`):

`gh api graphql --raw-field query='mutation { resolveReviewThread(input: {threadId: "<thread-id>"}) { thread { isResolved } } }'`

1. Resolve a thread only if it was fixed, is outdated, or was deferred with recorded agreement on the thread.
2. Leave pushbacks open for the reviewer (`resolve-pushback`).
3. Leave deferrals open when the reviewer has not agreed on the thread (`resolve-unagreed-deferral`).
4. Review-body and issue-request items have no thread to resolve.
5. If resolving a thread on an imported PR fails on permissions, the reply is what matters; do not block the run.
6. Verify each API write succeeded (`status-preserved`).

### 14. Update the PR description to match the head

Skip this step when the round changed no code and no claim in the description became false. Otherwise:

1. Read the current body: `gh pr view <pr> --repo 116-Labs/cuecal --json body`.
2. Re-read the description against the pushed tree and this round's outcome: summary, test plan, and any test count, gate result, or behavioural claim that the round changed. Check these after the last push, not before, because counts and claims go stale across rounds.
3. Edit only what is now false or missing. Keep the issue reference, matching the head commit's link settled in step 11. Do not rewrite untouched prose. Attribution is `none` (`attribution-policy`).
4. Ensure no **Deferred** list appears under `Closes`, and no `Refs` with a **Deferred** list remains once all criteria are met (`description-matches-head`), unless no collapse ran and the reply noted it.
5. Write the body to `<run-dir>/scratch/pr-body.md` with the file tool, then run `gh pr edit <pr> --repo 116-Labs/cuecal --body-file <run-dir>/scratch/pr-body.md`. Editing the description pushes nothing.

### 15. Request review again

1. `review.reviewers` is empty and no external service is configured. Request re-review from each login that submitted a review on this PR (from step 5): `gh pr edit <pr> --repo 116-Labs/cuecal --add-reviewer <login>`.
2. If there are none, or the request fails, post a short PR comment stating the revision is pushed and ready for review.
3. When this round's push dismissed approvals, Gaal itself re-requests those reviewers with a comment quoting `push`; post no notice of your own about the dismissal.

### 16. Write the run result

Write the result atomically on every exit path, including failures (`run-result-written`).

1. Read the finish time: `date -u +%Y-%m-%dT%H:%M:%SZ`.
2. Write `<run-dir>/result.json.tmp` with the file tool. Contents:
   - `schema_version`: `1`
   - `run_id`: the literal `GAAL_RUN_ID` string from the run context
   - `blueprint`: `"revise-pr"`
   - `blueprint_version`: `"1.7.0"`
   - `repo`: `"116-Labs/cuecal"`
   - `issue`: the linked issue number (integer), or `null`
   - `pr`: the PR number (integer), or `null` when none was determined
   - `status`: one of `"done"`, `"needs-human"`, `"needs-clarification"`, `"failed"`
   - `reason`: required unless `"done"`. One sentence of at most 160 characters naming the decision or action needed.
   - `questions`: required and non-empty for `"needs-clarification"`; quote the thread or ambiguous request.
   - `attempts`: positive integer (at least 1) representing the revise gate-fix attempts used.
   - `gates`: array of gate run objects (`name`, `command`, `exit_code`, `duration_ms`) that actually ran. Empty when nothing needed changing.
   - `branch`: the PR head branch name, or `null`
   - `commit_sha`: the 40-hex PR head sha after the run (the unchanged head when nothing was pushed), or `null`
   - `push`: required when the run pushed to the open PR: `why` (one sentence explaining the fixes or rebase cause) and `changes` (a short range-diff summary or `"tree unchanged"`).
   - `started_at` and `finished_at`: timestamps read from `date`.
   - No additional properties.
3. Move the file into place: `mv <run-dir>/result.json.tmp <run-dir>/result.json`. Never leave the `.tmp` file behind.
4. In the final message, provide a table with one row per item: source, decision, and sha or follow-up issue. Open pushbacks are normal and listed. Report collapse details if one ran.

## Exit states

- `done`: Every thread, every actionable review-body request, and every linked issue request since the PR opened is answered, the PR description matches the head, and the branch is pushed with green gates. `commit_sha` is the PR head after the run. When nothing needed changing, it is the unchanged head, nothing was pushed, and `gates` may be empty. Open pushbacks are normal and listed. A collapse skipped to preserve approvals is reported, not an error.
- `needs-clarification`: No PR could be determined, or a reviewer's request is ambiguous enough that any fix would be a guess. `questions` quotes the thread or request.
- `needs-human`: The round limit of 3 (`limits.revise_rounds`) was reached with red gates; a rebase conflict or fork/permission problem blocks the push; a gate was red on the tree rebased onto the fresh base (nothing was pushed); uncommitted edits of unknown origin block a reset; or after the push the PR became `CONFLICTING` or `DIRTY`. `reason` names the blocker.
- `failed`: The PR is not open (closed or merged); an API call failed; a hook rejected a commit or push beyond this run's remit; the push failed; or the single-commit collapse refused. `reason` names the step. Gates already red on the base are reported as pre-existing.

## Invariants

- `every-thread-answered`: Every unresolved thread at the start of the run has a reply at the end, including imports that did not apply.
- `one-push-per-round`: The branch is pushed at most once per round with changes (step 10), plus at most the step-11 single-commit collapse push. There is never a second push to chase a moved base or after an unmergeable status.
- `gates-green-before-push`: Every required gate (`lint`, `test`) exited 0 on the exact tree that was pushed.
- `reply-matches-action`: Each reply describes what was done: a sha containing the fix, an issue number for a deferral, or reasons for a pushback.
- `resolve-by-rule`: A thread is resolved only if it was fixed, is outdated, or was deferred with recorded agreement on the thread.
- `target-branch-only`: Code changes land only on this PR's branch. A fix for an imported item names where it landed in the reply.
- `bounded-rounds`: Gate-fix cycles stop at 3 (`limits.revise_rounds`), ending as `needs-human`.
- `body-requests-answered`: Every actionable request in a latest review body is acted on or answered in a PR comment with reasons.
- `issue-requests-answered`: Every actionable request made on the linked issue since the PR opened, by its author or a maintainer, is acted on or answered in a PR comment with a sha, a follow-up issue, or reasons.
- `description-matches-head`: After a round that changed behaviour, tests, or gate results, the PR description states nothing the pushed head contradicts, and its issue link matches the head commit's.
- `base-drift-checked`: Base drift and mergeability are checked before and after pushing. Rebasing is done only when conflicting, dirty, behind, or on a merged stacked parent, with gate verification on the rebased tree before pushing.
- `push-explained`: A run that pushed records `why` and `changes` (`tree unchanged` or a range-diff summary) in the run result's `push` object.
- `explicit-staging`: Stage only paths written by this run from the manifest. Never stage everything wholesale.
- `base-untouched`: Never commit or push to `main`.
- `fail-closed-reads`: An API error, auth expiry, or rate limit stops the run; it is never treated as "no threads" or "no PR".
- `complete-listings`: Every listing of threads, reviews, comments, and issue edits is paginated to the end or the run stops.
- `truthful-report`: The report and result describe what actually happened. An unrun gate is absent. "Fixed in `<sha>`" appears only when that sha contains the fix.
- `status-preserved`: A command's success or failure is never lost to a pipe, filter, or guard.
- `attribution-policy`: `commits.attribution` is `none`. Add no AI provenance or attribution lines to commit messages or PR bodies.
- `run-result-written`: `result.json` is written atomically on every exit path, including failures.

## Forbidden actions

- `push-red`: Pushing a branch with a failing required gate to clear comments.
- `piecemeal-push`: Pushing once per comment instead of once per round.
- `resolve-pushback`: Resolving a thread where the revision disagreed with the reviewer.
- `resolve-unagreed-deferral`: Resolving a deferral that only the reviser decided on. A deferral with no issue number is a pushback in disguise.
- `apply-unreproduced-import`: Applying an imported finding that does not reproduce on this branch.
- `collapse-with-open-threads`: Collapsing while any thread on this PR will remain open.
- `pull-after-collapse`: Pulling into a checkout after a collapse. Hard-reset to the remote instead.
- `content-free-push-after-approval`: Pushing a change that leaves the PR's tree unchanged (a collapse or unnecessary rebase) while the PR holds the required approvals and a push would invalidate them.
- `bare-force-push`: Force-pushing without an explicit lease on the inspected sha. The only allowed form is `--force-with-lease=<branch>:<sha>`.
- `admin-bypass`: Merging, pushing, or rewriting with admin privileges to bypass branch protection or verification hooks.
- `bypass-hook`: Committing or pushing with verification skipped or redirected (`--no-verify`, `git commit -n`, `--no-gpg-sign`, `core.hooksPath`), switching off a hook manager, or editing hook configurations.
- `machine-specific-paths`: Hard-coding a person's home directory, private paths, scripts, or services.
- `commit-foreign-edits`: Committing changes this run did not make.
