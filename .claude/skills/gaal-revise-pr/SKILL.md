---
name: gaal-revise-pr
description: Revises an open pull request in 116-Labs/cuecal after review. It addresses every unresolved review thread and every actionable request in a review body with a code fix or a reasoned reply, runs the profile gates (`uv run ruff check .`, `uv run pytest`), pushes once per round, replies to and resolves threads by rule, keeps the PR description true to the new head, and writes the run result to `$GAAL_RUN_DIR/result.json`. Use when a dispatch hands you a repo and PR number and asks for the `revise-pr` step, including imported feedback from another PR, a comment URL, or free-text notes. Do not use to open a PR, implement an issue, review a PR, or merge; those are other steps. Do not use when no PR can be determined; end as `needs-clarification` instead of guessing.
---
<!-- gaal-stamp blueprint=revise-pr@1.4.0 shared=1.3.0 profile=7d4c49f36df8465f generated=2026-10-01 content=6424cf5f1093424b -->

# gaal-revise-pr

Close the review loop on an open PR in `116-Labs/cuecal`. Every unresolved thread and every actionable request in a review body gets a code change or a reasoned reply. The branch is pushed once per round with green gates. Threads end in a state that matches what was done, and the PR description describes the head that was pushed.

## Run context

- `<run-dir>` stands for the literal run directory path given in the run context (the value of `GAAL_RUN_DIR`). Write the real path into commands and files. Never write an environment variable reference inside a command.
- The run id is the value of `GAAL_RUN_ID` from the run context. Copy that literal value into `result.json` as `run_id`. Never write an environment variable reference inside a command.
- Inputs from dispatch: the PR number, and optionally imported feedback (threads from another PR, a single comment URL, or free-text notes). The dispatch may also name the issue.
- Run one command per call. Never chain commands with `&&`, `;` or `|`.
- Scratch files go in `<run-dir>/scratch` (create it with `mkdir -p <run-dir>/scratch`). Write files with the file tools, never through shell redirection.
- Profile facts used below: repo `116-Labs/cuecal`, default branch `main`, tracker GitHub, branch prefix `gaal/`, conventional commits, `commits.attribution: none`, `commits.single_commit: true`, merge method `squash` with `merge.message_source: commits`, no merge queue, no auto-merge, `review.required_approvals: 1`, `review.threads_block_merge: false`, `review.reviewers: []`, `limits.revise_rounds: 3`. The profile names no `install` command and `preflight` is empty: install nothing and run the gates in this checkout.

## Steps

### 0. Start

Read the start time with `date -u +%Y-%m-%dT%H:%M:%SZ` and keep it for `started_at`. Keep a manifest of every path this run writes and an item list (source, decision, sha or issue). When you must stop, go to step 15 with the matching exit state.

### 1. Identify and confirm the PR

If no PR number can be determined from the dispatch, end as `needs-clarification` with a question asking for it. Never guess.

Run `gh pr view <pr> --repo 116-Labs/cuecal --json state,headRefName,headRefOid,baseRefName,isCrossRepository,reviewDecision,closingIssuesReferences,body`. A failed call stops the run (`fail-closed-reads`): an error, auth expiry or rate limit is never read as "no PR", "no threads" or "no checks". See the exit status of every `gh` and `git` call and handle a failure (`status-preserved`).

If `state` is not `OPEN`, end as `failed` with a reason naming this step. Record the head branch, head sha, base branch, and whether the branch is on a fork (`isCrossRepository`).

### 2. Check out the PR head from the remote

Run `git status --porcelain`. Changes you did not make belong to someone else: never stage, commit or discard them (`commit-foreign-edits`, `explicit-staging`). If switching branches would overwrite them, end as `needs-human`.

Run `git fetch origin <head-branch>`, then `git switch <head-branch>`. Compare `git rev-parse HEAD` with `git rev-parse origin/<head-branch>`. If the local branch holds commits that are not on the remote, end as `needs-human` instead of guessing; otherwise run `git reset --hard origin/<head-branch>` so you work on the head as fetched. Never work on `main` (`base-untouched`, `target-branch-only`).

Install nothing: the profile has no `install` command, so the gates run here in the checkout.

### 3. List every unresolved review thread

Use GraphQL, which exposes resolution state and thread ids. Write the literal PR number into the query:

`gh api graphql -F query='query { repository(owner: "116-Labs", name: "cuecal") { pullRequest(number: <pr>) { reviewThreads(first: 100) { pageInfo { hasNextPage endCursor } nodes { id isResolved isOutdated comments(first: 100) { pageInfo { hasNextPage } nodes { databaseId author { login } body path line url } } } } } } }'`

While `hasNextPage` is true, repeat with `reviewThreads(first: 100, after: "<endCursor>")` using the literal cursor (`complete-listings`). If a thread's `comments` has another page, end as `needs-human`: truncated data is never trusted.

For each thread with `isResolved: false`, record the thread `id`, the `databaseId` of its first comment (the reply anchor), path, line and text. Record every thread id now, before any history rewrite, because a collapse marks threads outdated. Tag each item with its source: `this-pr`.

### 4. Read the review bodies

Run `gh api repos/116-Labs/cuecal/pulls/<pr>/reviews --paginate`. Read the body of the latest review from each reviewer, plus any earlier review body whose requests were never answered. A review body has no thread, so each actionable request in one (a change asked for, a finding listed only in the body) becomes an item tagged `review-body`. Skip pure verdicts, praise, and requests already answered by a later commit or comment. Each actionable request is owed an answer (`body-requests-answered`).

### 5. Gather and re-verify imported feedback

If the dispatch carries imports, tag each item `import` and re-verify it against this branch before deciding anything: it reproduces, partly applies, or does not apply.

- Threads from another PR: list that PR's unresolved threads the same way as step 3 with its number, and keep their thread ids and first-comment ids.
- A comment URL: check its shape first. A `#discussion_r<id>` fragment is a review comment: read it with `gh api repos/116-Labs/cuecal/pulls/comments/<id>`. A `#issuecomment-<id>` fragment is an issue-level comment with no thread: read it with `gh api repos/116-Labs/cuecal/issues/comments/<id>`, and answer it with a PR comment, not a thread reply.
- Free-text notes: treat each distinct request as an item.

Open the code and try to reproduce each finding. Never apply an imported finding that does not reproduce on this branch (`apply-unreproduced-import`); it gets a reply giving the reason (`every-thread-answered`). Fix only the part of a partly applying finding that reproduces.

### 6. Decide each item

For every item from steps 3 to 5 choose one:

- **fix**: change the code on this PR's branch.
- **answer**: a question or explanation needs only a reply.
- **defer**: a follow-up issue carries it, with agreement recorded on the thread. A deferral with no issue number is a pushback in disguise.
- **push back**: you disagree; give reasons.

A `review-body` item is decided the same way. A deferral there has no thread to carry agreement, so it is not resolved, and its follow-up issue is named in the reply.

If a reviewer's request is so ambiguous that any fix would be a guess, end as `needs-clarification` with `questions` that quote the thread.

### 7. Make the fixes

Make every fix in the working tree on the PR branch (`target-branch-only`). A fix for an imported item lands only on this branch, and the reply names where. Add each path you write to the manifest. Make no edit that no item asks for.

### 8. Run every gate

Run each gate in this checkout, one command per call, exactly as written. Time each: run `date -u +%s` as its own command just before the gate and again just after; `duration_ms` is the difference times 1000. Record `name`, `command`, `exit_code` and `duration_ms` per run.

1. `uv run ruff check .` (gate `lint`, required)
2. `uv run pytest` (gate `test`, required)

Run both even if the first fails. A gate that did not run is absent from the result, never passed (`truthful-report`). A gate may be skipped only while its tool or manifest does not exist yet, and the report says so; otherwise it must exit 0.

On failure, fix and re-run all gates. Each such cycle is one attempt; `attempts` counts the cycles used. When `limits.revise_rounds` (3) attempts have run without green gates, end as `needs-human` naming the failing gate (`bounded-rounds`). Never push a tree with a failing required gate (`push-red`, `gates-green-before-push`). A failure that was already red on the base is reported as pre-existing.

If no item needed a code change, no gate run is required and `gates` may be empty.

### 9. Commit once, push once

If there are fixes, stage only manifest paths, each by explicit path with `git add <path>` (`explicit-staging`). Confirm with `git diff --cached --name-only` that exactly the manifest paths are staged and with `git status --porcelain` that nothing else this run wrote is left over.

Write the commit message to `<run-dir>/scratch/commit-msg.txt` with the file tool: a conventional subject (for example `fix(<scope>): address review feedback`) and a short body. No attribution line and no AI trailer (`attribution-policy`, `commits.attribution: none`). Run `git commit -F <run-dir>/scratch/commit-msg.txt` with the hooks enabled as the one fixup commit. If a hook rejects it, fix what it reports and commit again; never skip, redirect or disable it (`bypass-hook`).

Push exactly once with `git push origin HEAD:<head-branch>` (`one-push-per-round`, `piecemeal-push`). If a hook rejects the push, fix what it reports; if that is beyond this run, end as `failed` naming the hook. A conflict or permission problem that blocks the push ends as `needs-human`; any other failed push ends as `failed`. The push may dismiss existing approvals (`review.required_approvals` is 1); say so in the report.

Run `git rev-parse HEAD` and record the fix sha. If nothing needed committing, nothing is pushed and the fix sha is the unchanged head.

### 10. Settle the issue link and decide on the collapse

The collapse runs only when every thread on this PR will be resolved after step 13 (no pushback, no unagreed deferral, no other open thread) and `merge.message_source` is `commits`. Otherwise keep the fixup commit separate so the reviewer can diff only the delta, and never collapse with a thread left open (`collapse-with-open-threads`).

Settle the issue link before collapsing, by the issue-link rule (`description-matches-head`):

- Find the PR's issue: the dispatch first, then `closingIssuesReferences`, then the PR body, then each commit message (`git log --format=%B origin/main..HEAD`), reading closing-keyword lines before `Refs #N` lines. Extract only the numbers.
- A round that completes some deferred criteria updates the **Deferred** list. A round that completes the last of them turns `Refs #N` into `Closes #N` and drops the list. A **Deferred** list appears only under `Refs`, never next to `Closes`.
- When no collapse runs, leave the link and the **Deferred** list unchanged and say so in the round's reply.

### 11. Collapse, when step 10 says so

This is the shared single-commit collapse routine in PR mode. Knowingly override its unresolved-threads soft gate: the threads just fixed resolve after the push. Print the unresolved-thread count in the report. The collapse must follow the fix push, because it reads the remote head; collapsing first would ship without the fix.

1. Regime: `merge.message_source` is `commits`, so it applies.
2. Idempotence: `git rev-list --count origin/main..<fix-sha>`; zero or one means do nothing.
3. Target (PR mode): run `git fetch origin <head-branch>` and `git rev-parse origin/<head-branch>`; it must equal the sha pushed in step 9, else stop. Run `git worktree add --detach <run-dir>/worktree <fix-sha>`, then `cd <run-dir>/worktree`.
4. Hard gates, never overridden: the branch is on a fork (`isCrossRepository`); any commit on it has another author (`git log --format=%an origin/main..<fix-sha>` against the git user); the remote head is not an ancestor of what will be pushed. Refuse and end as `failed` naming this step.
5. Record `git merge-base origin/main <fix-sha>` and the pre-collapse tree `git rev-parse <fix-sha>^{tree}`, then `git reset --soft <merge-base>`.
6. Write the whole-change message to `<run-dir>/scratch/collapse-msg.txt`: a conventional subject, a body for the change as a whole, and the link settled in step 10 (`Closes #N`, or `Refs #N` on its own line plus the **Deferred** list). Drop process commits. No attribution. Run `git commit -F <run-dir>/scratch/collapse-msg.txt` with hooks enabled.
7. Content preservation: `git rev-parse HEAD^{tree}` must equal the pre-collapse tree hash, and the rewrite must not be empty; otherwise abort before pushing.
8. Push with an explicit lease on the inspected sha: `git push --force-with-lease=<head-branch>:<fix-sha> origin HEAD:<head-branch>` (`bare-force-push` forbids anything weaker). On failure the remote still holds the previous head.
9. Run `git rev-parse HEAD` for the new sha. `cd` back to the checkout and run `git worktree remove --force <run-dir>/worktree` on every exit path.
10. In this checkout run `git fetch origin <head-branch>` and `git reset --hard origin/<head-branch>`. Never pull after a collapse (`pull-after-collapse`). The report names any other stale checkout that needs the same hard reset.

If the collapse refuses, end as `failed` naming this step. The final head sha (after the collapse if one ran) is the sha every reply names and the result's `commit_sha`.

### 12. File deferrals, then reply

File every follow-up issue first, with no milestone and no assignee so it lands in the backlog: write the body to a file in `<run-dir>/scratch` and run `gh issue create --repo 116-Labs/cuecal --title "<title>" --body-file <run-dir>/scratch/<file>`. Note the issue number.

Reply to every thread through its reply relation, which works on outdated threads too: write the text to a file and run `gh api repos/116-Labs/cuecal/pulls/<pr>/comments/<first-comment-id>/replies -F body=@<run-dir>/scratch/<reply-file>` with the first-comment id from step 3 (`every-thread-answered`). For an imported thread from another PR, use that PR's number and comment id. If that reply fails on permissions, the reply was the point; note it and continue. An issue-level import comment is answered with a PR comment.

Each reply describes what was done (`reply-matches-action`):

- A fix reply names the final sha that contains the fix, only when that sha really contains it (`truthful-report`). For an imported item it also says where the fix landed (`target-branch-only`).
- A deferral reply names the follow-up issue number.
- A pushback reply gives reasons.
- An imported item that did not reproduce gets the reason it does not apply.

Answer every `review-body` item in one PR comment: write it to `<run-dir>/scratch/body-reply.md`, naming or quoting each request with its decision (sha, issue number, or reasons), and post it with `gh pr comment <pr> --repo 116-Labs/cuecal --body-file <run-dir>/scratch/body-reply.md` (`body-requests-answered`). When it applies, say there that the issue link and **Deferred** list were left unchanged because no collapse ran.

### 13. Resolve threads by rule

Resolve a thread only if it was fixed, is outdated, or was deferred with agreement recorded on the thread (`resolve-by-rule`). Run `gh api graphql -F query='mutation { resolveReviewThread(input: {threadId: "<thread-id>"}) { thread { isResolved } } }'` with the id from step 3, one call per thread, and check the returned `isResolved`.

- Leave open every thread where the revision disagreed with the reviewer (`resolve-pushback`).
- Leave open every deferral the reviser decided alone (`resolve-unagreed-deferral`). Deferral and pushback have opposite outcomes when threads block merge: an agreed deferral resolves, a pushback does not.
- Review-body items have nothing to resolve.
- If resolving another PR's thread fails on permissions, that is not a blocker; the reply stands.

Open pushbacks are normal; list them in the report.

### 14. Update the PR description, then request review again

Skip the edit when the round changed no code and no claim in the description became false. Otherwise, after the last push (counts and claims go stale across rounds, so check them then, not before), read the body with `gh pr view <pr> --repo 116-Labs/cuecal --json body` against the pushed tree and this round's outcome: the summary, the test plan, and any test count, gate result or behavioural claim the round changed. Edit only what is now false or missing. Keep the issue reference (changed only as step 10 settled) and any attribution section, and do not rewrite untouched prose. The link in the body must equal the one in the head commit message (`description-matches-head`). Write the new body to `<run-dir>/scratch/pr-body.md` and run `gh pr edit <pr> --repo 116-Labs/cuecal --body-file <run-dir>/scratch/pr-body.md`. This pushes nothing. Do it before re-requesting review.

Request review again per `review`: the profile lists no reviewers and names no re-request mechanism, so there is no call to make; the replies and resolved threads are the signal, and the report says so. Do not merge, enable auto-merge or touch a queue.

### 15. Write the run result

Do this on every exit path, including failures and early stops (`run-result-written`, `truthful-report`). Read the finish time with `date -u +%Y-%m-%dT%H:%M:%SZ`. Write `<run-dir>/result.json.tmp` with the file tool, then run `mv <run-dir>/result.json.tmp <run-dir>/result.json`. Never leave the `.tmp` file behind.

The file is a JSON object with exactly these fields:

- `schema_version`: `1`
- `run_id`: taken from `$GAAL_RUN_ID`, the literal value from the run context
- `blueprint`: `"revise-pr"`
- `blueprint_version`: `"1.4.0"`
- `repo`: `"116-Labs/cuecal"`
- `issue`: the PR's issue number, or `null`
- `pr`: the PR number, or `null` if none could be determined
- `status`: one of `done`, `needs-human`, `needs-clarification`, `failed`
- `reason`: required unless `status` is `done`; one sentence of at most 160 characters naming the decision or action needed. Detail belongs in the PR comment and the final message.
- `questions`: required and non-empty when `status` is `needs-clarification`; each question quotes the thread
- `attempts`: integer of at least 1, the gate cycles used
- `gates`: the gate runs from step 8 with `name`, `command`, `exit_code`, `duration_ms`; empty when none ran
- `branch`: the PR head branch, or `null`
- `commit_sha`: the PR head after the run, 40 lowercase hex characters (the unchanged head when nothing was pushed), or `null`
- `started_at` and `finished_at`: UTC timestamps such as `2026-01-01T00:00:00Z`

Example for a finished run:

```json
{
  "schema_version": 1,
  "run_id": "<value of GAAL_RUN_ID from the run context>",
  "blueprint": "revise-pr",
  "blueprint_version": "1.4.0",
  "repo": "116-Labs/cuecal",
  "issue": 12,
  "pr": 34,
  "status": "done",
  "attempts": 1,
  "gates": [
    {"name": "lint", "command": "uv run ruff check .", "exit_code": 0, "duration_ms": 1200},
    {"name": "test", "command": "uv run pytest", "exit_code": 0, "duration_ms": 8400}
  ],
  "branch": "gaal/12-example",
  "commit_sha": "0123456789abcdef0123456789abcdef01234567",
  "started_at": "2026-01-01T00:00:00Z",
  "finished_at": "2026-01-01T00:05:00Z"
}
```

For any status other than `done`, add `reason`; for `needs-clarification`, add `questions` too.

## Exit states

- `done`: every thread and every actionable review-body request is answered, the description matches the head, and the branch is pushed with green gates. `commit_sha` is the PR head after the run; when nothing needed changing it is the unchanged head, nothing was pushed, and `gates` may be empty. The report has one row per item (source, decision, sha or issue). Open pushbacks are normal and listed.
- `needs-clarification`: no PR could be determined, or a reviewer's request is so ambiguous that any fix would be a guess. `questions` quote the thread.
- `needs-human`: the round limit (3) was reached with red gates, or a conflict, a permission problem, foreign uncommitted edits, local-only commits or truncated listings block the run. `reason` names it.
- `failed`: the PR is not open, the push failed, or the collapse refused. `reason` names the step. Gates already red on the base are reported as pre-existing.

## Invariants

From `revise-pr`:

- `every-thread-answered`: every unresolved thread at the start has a reply at the end, imports that did not apply included.
- `one-push-per-round`: the branch is pushed once per round, after all fixes.
- `gates-green-before-push`: every required gate exited 0 on the pushed tree; a runnable pending gate too.
- `reply-matches-action`: a sha that contains the fix, an issue number for a deferral, reasons for a pushback.
- `resolve-by-rule`: resolve only fixed, outdated, or agreed-deferral threads.
- `target-branch-only`: code changes land only on this PR's branch; a fix for an imported item names where it landed.
- `bounded-rounds`: gate-fix cycles stop at `limits.revise_rounds` (3), ending as `needs-human`.
- `body-requests-answered`: every actionable review-body request is acted on or answered in a PR comment.
- `description-matches-head`: the description states nothing the pushed head contradicts, and its issue link equals the head commit's, edited before review is re-requested.

Shared:

- `explicit-staging`: stage only manifest paths, by explicit path.
- `base-untouched`: never commit or push to `main`.
- `fail-closed-reads`: an error, auth expiry or rate limit stops the run; it is never "nothing found".
- `complete-listings`: paginate threads, reviews, comments and checks to the end or stop.
- `truthful-report`: report only what happened; a gate that did not run is absent.
- `status-preserved`: never lose a command's success or failure to a pipe or guard.
- `attribution-policy`: follow `commits.attribution: none` exactly; add no attribution to commits or PR bodies.
- `run-result-written`: write `result.json` atomically on every exit path.

## Forbidden actions

From `revise-pr`:

- `push-red`: pushing with a failing required gate to clear comments.
- `piecemeal-push`: pushing once per comment instead of once per round.
- `resolve-pushback`: resolving a thread where the revision disagreed with the reviewer.
- `resolve-unagreed-deferral`: resolving a deferral only the reviser decided on; a deferral with no issue number is a pushback.
- `apply-unreproduced-import`: applying an imported finding that does not reproduce on this branch.
- `collapse-with-open-threads`: collapsing while any thread on this PR will remain open.
- `pull-after-collapse`: pulling into a checkout after a collapse; hard-reset it to the remote.

Shared:

- `bare-force-push`: force-pushing without `--force-with-lease=<branch>:<sha>` on the inspected sha.
- `admin-bypass`: merging or pushing with admin privileges to get around protection, a queue or a hook.
- `bypass-hook`: skipping or redirecting hooks or signing in any way; fix what the hook reports, or end as `failed` naming it.
- `machine-specific-paths`: hard-coding a person's home directory, private scripts or services.
- `commit-foreign-edits`: committing changes this run did not make.
