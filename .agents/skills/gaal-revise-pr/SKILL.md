---
name: gaal-revise-pr
description: Revises an open pull request in 116-Labs/cuecal after review. It answers every unresolved review thread, every actionable request in a review body and every request made on the linked GitHub issue since the PR opened, each with a verified code change or a reasoned reply. It runs the profile gates (`uv run ruff check .` and `uv run pytest`), checks base drift and pushes at most once per round with an explicit lease. When every thread will resolve, it collapses the branch to one Conventional Commits commit, unless that would throw away approvals. It replies to threads and resolves them by rule, keeps the PR description true to the pushed head, requests review again and writes the run result to result.json in the run directory. Use it when a dispatch or the user names a repo and PR number and asks for the revise-pr step ("revise the PR", "address the review comments"). This includes imported feedback from another PR, a single comment URL or free-text notes. Do not use it to implement an issue (gaal-implement), open a PR (gaal-open-pr), review a PR (gaal-review-pr), merge or deploy. When no PR can be determined, do not guess; end as needs-clarification.
---
<!-- gaal-stamp blueprint=revise-pr@1.8.0 shared=1.5.0 profile=833de6ae33df6d68 generated=2026-10-08 core=aee666ea0d453d32 forbidden=605730d3fee67b49 content=b50b7a5fcb89f721 -->

# gaal-revise-pr

Closes the review loop on one open PR in `116-Labs/cuecal` (blueprint `revise-pr` 1.8.0). Every unresolved thread, every actionable review-body request and every linked-issue request made since the PR opened gets a code change or a reasoned reply. The branch is pushed at most once per round with green gates. Threads end in the state that matches what was done, and the PR description describes the pushed head. Then review is requested again.

## Project facts (from `.gaal/project.yml`)

| Field | Value |
|---|---|
| Repo / default branch | `116-Labs/cuecal` / `main` (private) |
| Tracker | GitHub issues |
| Gates (both required, run in this order) | `lint`: `uv run ruff check .`; `test`: `uv run pytest` |
| Preflight / advisory | none / none |
| Install | none named. Install nothing. Run the gates in the checkout itself, where the dependencies are already installed, and never in a throwaway worktree, which has no install. |
| Branch prefix | `gaal/` |
| Commits | one commit per PR (`single_commit: true`), Conventional Commits, attribution `none`: add no `Co-Authored-By`, no "Generated with" line and no AI or tool attribution to commit messages or PR bodies |
| Merge | `squash`, no merge queue, no auto-merge, `message_source: commits`. This skill never merges. |
| Review | `required_approvals: 1`, `threads_block_merge: false`, `reviewers: []`, `start_signal: reaction`, separate review identity `116-labs-gaal-review[bot]` |
| Branch protection facts | `dismiss_stale_approvals` and `require_last_push_approval` are **absent**. Treat both as true: any push dismisses approvals, and only approvals of the current head count. |
| Push identity | `116-labs-gaal-push[bot]` |
| Limits | `revise_rounds: 3` (the only limit this step uses; `implement_attempts: 3` and `review_rounds: 2` belong to other steps) |

## Conventions for every command

- `<run-dir>` stands for the literal run directory path from the run context (the value of `GAAL_RUN_DIR`). Write it out literally. Never write `$GAAL_RUN_DIR`, `$GAAL_RUN_ID`, any other `$VAR`, `$(…)` or backticks in a command. Take the run id from the run context too.
- Other placeholders: `<n>` is the PR number, `<branch>` the PR head branch, `<base>` the PR base branch, and `<sha>`, `<N>`, `<login>`, `<path>` and `<file>` are literal values you substitute.
- Run one command per call. Do not chain with `&&`, `;` or `|`. Filter with `gh --jq`, never a pipe. Put no `NAME=value` before a command.
- Allowed commands are `git`, `gh`, `mkdir`, `mv`, `cp`, `ls`, `cat`, `date`, `pwd` and `cd <literal path>`, plus exactly `uv run ruff check .` and `uv run pytest`, with nothing added. Run nothing else.
- Write every commit message, PR body, comment body, reply body and GraphQL query to a file under `<run-dir>/scratch/` with the file-writing tool. Pass it by path: `git commit -F <file>`, `--body-file <file>`, `-F body=@<file>`, `-F query=@<file>`. Never write such text inline and never use shell redirection.
- Scratch files and throwaway worktrees live only inside `<run-dir>`, never in `/tmp`, and never through `mktemp`.
- Quote every glob passed to a command (`git branch --list 'gaal/*'`).
- List uncommitted paths only with `git status --porcelain=v1 --untracked-files=all`.
- While `mergeable` reads `UNKNOWN`, read it again, up to five reads in all (no `sleep`). If it is still `UNKNOWN` after the fifth read, it is unreadable, never mergeable.
- `fail-closed-reads`: tell "the API returned nothing" apart from "the call failed". A failed read, auth expiry or rate limit ends the run `failed` naming the read, except the mergeability check, which ends `needs-human`. A failure never becomes "no PR", "no threads" or "no reviews".
- `complete-listings`: paginate every listing of threads, reviews, comments, edits or checks to the end. Use `gh api --paginate` for REST. For GraphQL, use a query file with a `$endCursor` variable and `pageInfo { hasNextPage endCursor }`, run with `gh api graphql --paginate`. When a nested connection's `totalCount` exceeds what was fetched, or pagination fails, end `failed` naming the listing.
- `status-preserved`: check the exit status of every command. A failed push, gate or API write is seen and handled, never hidden.
- Find the hooks directory, if needed, only with `git rev-parse --git-path hooks`. Never name `core.hooksPath` in any command, not even to read it.

## Steps

The steps below are referred to by name. The *push step* commits the fixes, checks base drift and pushes. The *collapse step* applies the collapse routine. The *reply step* replies to every thread. The *description step* updates the PR description. The *run result* is the last step and runs on every exit path.

### Start

1. Record the start time with `date -u +%Y-%m-%dT%H:%M:%SZ` (`started_at`).
2. Create scratch space with `mkdir -p <run-dir>/scratch`.
3. Take the run id from the run context.
4. Determine the PR number from the dispatch. If no PR can be determined, do not guess: go straight to the run result with `needs-clarification`, `pr: null` and a question asking which PR to revise.

### 1. Confirm the PR is open

Run `gh pr view <n> --repo 116-Labs/cuecal --json number,state,isDraft,isCrossRepository,headRefName,headRefOid,baseRefName,baseRefOid,createdAt,url,body,closingIssuesReferences,commits`.

- If the read fails, end `failed` naming it (`fail-closed-reads`).
- If `state` is `CLOSED` or `MERGED`, end `failed` with the reason "PR #<n> is not open".
- If `headRefName` is `main`, end `failed`: this step never commits or pushes to the base branch (`base-untouched`).
- Record `<branch>` (`headRefName`), `<base>` (`baseRefName`), `createdAt` and the inspected head `<sha>` (`headRefOid`). Also record `<start-head>`, which is that same sha (the head before the run).

### 2. Check out the PR head

1. Run `git status --porcelain=v1 --untracked-files=all` and note any existing changes. They are not this run's work: never stage or commit them (`commit-foreign-edits`, `explicit-staging`), and never discard them.
2. Run `git fetch origin <branch>`, then `gh pr checkout <n>`.
3. Confirm with `git rev-parse HEAD` that the checkout equals `headRefOid`.
   - If the local branch carries commits that are not on the remote, back them up first with `git branch gaal/backup/<n>-<short-sha> HEAD`. Verify the backup with `git rev-parse gaal/backup/<n>-<short-sha>`, then run `git reset --keep origin/<branch>`. Name the backup ref in full in the report.
4. Install: the profile names no `install` command, so nothing is installed (`install-before-gates`). Use the checkout's existing environment and run every gate in this checkout.

### 3. List unresolved review threads

1. Write `<run-dir>/scratch/threads.graphql` with the file tool. Use a query on `repository(owner:$owner,name:$name){pullRequest(number:$number){reviewThreads(first:100,after:$endCursor){pageInfo{hasNextPage endCursor} nodes{id isResolved isOutdated path line comments(first:100){totalCount nodes{id databaseId url author{login} body createdAt}}}}}}`.
2. Run `gh api graphql --paginate -F owner=116-Labs -F name=cuecal -F number=<n> -F query=@<run-dir>/scratch/threads.graphql`.
3. Keep the threads with `isResolved: false`. Record every thread id now, before any history rewrite: a rebase or collapse marks threads outdated, and replies go through the thread id (this works on outdated threads). Tag each thread with source `this-pr`.
4. Imported feedback from the dispatch:
   - **Another PR's threads:** list them with the same query and that PR's number. Tag each one `import`.
   - **A single comment URL:** check its shape before extracting ids. A `#discussion_r<id>` URL is a review comment: read it with `gh api repos/116-Labs/cuecal/pulls/comments/<id>` and find its thread. A `#issuecomment-<id>` URL is an issue-level comment with no thread: read it with `gh api repos/116-Labs/cuecal/issues/comments/<id>` and answer it in the PR comment, not in a thread.
   - **Free-text notes:** each point becomes an `import` item with no thread.

### 4. Read review bodies

1. Run `gh api --paginate repos/116-Labs/cuecal/pulls/<n>/reviews`.
2. Read the body of the latest review from each reviewer, plus any earlier review body whose requests were never answered by a later commit or comment.
3. Each actionable request in a body (a change asked for, or a finding listed only in the body) becomes an item tagged `review-body`. Reviewers sometimes put a real finding only in the body, where no thread exists to reply in.
4. Skip pure verdicts, praise, and requests already answered.

### 5. Read the linked issues' requests

1. Find the linked issues by the issue-link rule. They are the union of:
   - `closingIssuesReferences`;
   - each `Closes`, `Fixes` or `Resolves` line (and their forms) and each `Refs #N` line in the PR body;
   - the same lines in each commit message (from the `commits` field read in step 1).

   An issue named in the dispatch takes precedence. To pick the run result's `issue`, prefer a reported closing issue. Then look in the body, then in each commit message, and take a closing-keyword line before a `Refs #N` line. Extract only the numbers.
2. For each `<N>`, run `gh api repos/116-Labs/cuecal/issues/<N>`:
   - A 404 or a `pull_request` key means it is not an issue. It brings no requests, and the report names it.
   - Any other failure ends the run `failed`.
3. Read the issue fresh. Comments: `gh api --paginate repos/116-Labs/cuecal/issues/<N>/comments`. Body edits: write `<run-dir>/scratch/edits.graphql` with `repository(owner:$owner,name:$name){issue(number:$number){author{login} body userContentEdits(first:100,after:$endCursor){pageInfo{hasNextPage endCursor} nodes{editedAt editor{login} diff}}}}` and run `gh api graphql --paginate -F owner=116-Labs -F name=cuecal -F number=<N> -F query=@<run-dir>/scratch/edits.graphql`.
4. Find the cutoff. It is the earlier of:
   - the PR's `createdAt`;
   - the creation time of the newest `Gaal finished implement …: done.` comment on the issue, which marks when Gaal's done implement run started.
5. After the cutoff, every comment and every body edit by the issue's author or a maintainer is a request. A maintainer is an admin of the repository: check with `gh api repos/116-Labs/cuecal/collaborators/<login>/permission --jq .permission` and look for `admin`. To see what an edit changed, compare its `diff` with the version before it. Skip:
   - comments that carry a `<!-- gaal:` marker;
   - edits in which every added or removed line lies between an opening `<!-- gaal:plan-drift -->` line and the next `<!-- /gaal:plan-drift -->` line, both marker lines included (implement's own record, even when written under a maintainer's login). An edit with any changed line outside such a section is a request, including text a maintainer appended after one.
   - comments and edits by bots;
   - requests that a PR comment already answers.
6. Each actionable request (a change asked for, or a criterion added or changed) becomes an item tagged `issue-request`. A status note or thanks is not an item. Maintainers ask for more on the issue as often as on the PR. Without this step the PR converges on the old scope, and a request this run saw but left unanswered is never asked about again (`issue-requests-answered`).

### 6. Re-verify imports

For each `import` item, check this branch and classify it: **reproduces**, **partly applies** or **does not apply**. Never apply an imported finding that does not reproduce here (`apply-unreproduced-import`). It still gets a reply that gives the reason (`every-thread-answered`).

### 7. Decide each item

Decide each item as one of:

- **fix**;
- **answer**: a question or explanation;
- **defer**: only under the follow-up bar below, with agreement recorded on the thread;
- **push back**: disagree, with reasons.

The follow-up bar: file a follow-up issue only for a user-visible defect outside this PR's diff that reproduces on `main`. Name the defect, the reproduction and the files, and link back to this PR. Anything else is fixed, answered or pushed back, never filed. A deferral with no issue number and no agreed owner is a pushback and is answered as one (`resolve-unagreed-deferral`).

- `review-body` and `issue-request` items are decided the same way. Their deferrals have no thread to carry agreement, so they are never resolved, and the reply names the follow-up issue.
- An `issue-request` that widens the issue beyond what this PR can carry is deferred (only if it meets the bar) or answered with the reason.
- `threads_block_merge` is false here, so open threads do not block the merge. Still resolve only by rule: an agreed deferral is resolved, and a pushback stays open for the reviewer.
- A request so ambiguous that any fix would be a guess does not stop the round. Answer it by asking its question, on its thread or in the PR comment. Handle every other item as usual, then end `needs-clarification`, with `questions` quoting that request.

### 8. Make the fixes

1. Edit the files with the file tools.
2. Keep a manifest of every path this run writes, under `<run-dir>/scratch/` (for example `manifest.txt`).
3. A fix for an imported item lands only on this PR's branch (`target-branch-only`).

### 9. Run the gates

Run this step when the round has fixes.

1. Run each gate in the checkout, in profile order. Time each one by running `date -u +%s` just before and just after it, as separate commands. Its `duration_ms` is the difference times 1000.
   - `uv run ruff check .`
   - `uv run pytest`
2. If a gate fails, fix the cause, add any newly written paths to the manifest and re-run every gate. Each gate-fix cycle is one round.
3. Stop at **3 rounds** (`limits.revise_rounds`, `bounded-rounds`). If the gates are still red after the third round, end `needs-human` with the reason "gates still red after 3 revise rounds". The reply step still runs, and the fixes are reported as prepared, not pushed.
4. Never push a red tree to clear comments (`push-red`, `gates-green-before-push`).
5. A fix that changes `pyproject.toml` or `uv.lock` still installs nothing, because the profile names no `install` command.
6. A gate that is already red on `main` is reported as pre-existing.

### 10. Push step

This step runs every round, with or without fixes.

**Commit.** When there are fixes:

1. Stage each manifest path explicitly with `git add -- <path>`, one call per path. Never use `git add -A`, `git add .` or `git commit -a`.
2. Confirm with `git status --porcelain=v1 --untracked-files=all` that nothing else this run is responsible for is left over (`explicit-staging`).
3. Write a Conventional Commits message, for example `fix(<scope>): address review on #<n>`, with no attribution trailers, to `<run-dir>/scratch/fixup-msg.txt`.
4. Commit with `git commit -F <run-dir>/scratch/fixup-msg.txt`. This makes one fixup commit, with hooks enabled.
5. If a hook rejects the commit, fix what it reports and commit again. If the fix is beyond this run's remit, end `failed` naming the hook and briefly quoting its output (`bypass-hook`).

**Check base drift** (`base-drift-checked`). Do this even in a round with no fix.

1. For a stacked PR (`<base>` is not `main`), first look up the parent PR: `gh pr list --repo 116-Labs/cuecal --head <base> --state all --json number,state,headRefOid`.
   - If the parent has merged, fetch only `git fetch origin main`. Never fetch `origin <base>`: the parent branch may have been deleted at merge.
   - Otherwise run `git fetch origin <base>` and `git fetch origin main`.
2. For a PR on `main`, run `git fetch origin main`.
3. Read `gh pr view <n> --json mergeable,mergeStateStatus,baseRefOid`. Re-read while `mergeable` is `UNKNOWN`, up to five reads.
4. If the check fails or stays unreadable, end `needs-human` naming the check, with nothing pushed.

**Rebase only when required.** A rebase is required only when:

- the PR is `CONFLICTING` or `DIRTY`;
- `mergeStateStatus` is `BEHIND` (GitHub reports this only when the base requires up-to-date branches; never read branch protection for this);
- it is a stacked PR whose parent has merged.

A base that only moved while the PR stays `MERGEABLE` and not `BEHIND` is not rebased onto. A rebase rewrites history that the reviewer then has to range-diff, and an unneeded rebase on an approved PR is a content-free push (`content-free-push-after-approval`).

To rebase:

1. The thread ids were captured in step 3.
2. Record `<old-head>` with `git rev-parse HEAD` and the old tree with `git rev-parse HEAD^{tree}`.
3. Rebase:
   - **Ordinary:** set `<old-merge-base>` to the output of `git merge-base <old-head> origin/<base>`, then run `git rebase origin/<base>`. This keeps the branch's commits and makes no merge commit.
   - **Merged stack parent:** `<old-parent-tip>` is the parent's last `headRefOid`. Fetch it with `git fetch origin pull/<parent>/head` if it is not local. Run `git merge-base --is-ancestor <old-parent-tip> HEAD`. If that exits non-zero, the parent was rewritten (for example collapsed) after this branch left it: do not rebase, and end `needs-human` naming the parent PR, with nothing pushed. Otherwise run `git rebase --onto origin/main <old-parent-tip>`, then `gh pr edit <n> --base main`. From here on, `<base>` is `main` for the post-push check, the collapse's merge base and its author check. `<old-merge-base>` is `<old-parent-tip>`.
4. If the rebase conflicts:
   1. List the conflicting paths with `git diff --name-only --diff-filter=U`.
   2. Run `git rebase --abort`.
   3. End `needs-human` naming the paths.
5. Compare the trees with `git rev-parse HEAD^{tree}`.
   - If the trees are equal, record `tree unchanged`.
   - Otherwise set `<new-merge-base>` to the output of `git merge-base HEAD origin/<base>` and run `git range-diff <old-merge-base>..<old-head> <new-merge-base>..HEAD`. Record its summary: every commit should be paired `=`.

   Both outcomes feed the run result's `push` (`push-explained`).
6. Install nothing (no `install` command), and re-run every gate on the rebased tree, timed as in step 9. If a gate is red there, restore with `git reset --keep <old-head>`. Then end `needs-human` naming the gate and the base sha, with nothing pushed: the branch and the new base disagree, and that is a person's call.

With no fix and no required rebase, the push step pushes nothing.

**Push once** (`one-push-per-round`, `piecemeal-push`). Run `git push --force-with-lease=<branch>:<sha> origin HEAD:refs/heads/<branch>`, where `<sha>` is the inspected remote head. Hooks stay enabled.

- Never use `--force`, `-f` or a lease with no expected sha (`bare-force-push`).
- If the local pre-push hook rejects the push, fix what it reports and push again (`bypass-hook`).
- Never retry any other failure. Restore the pre-rebase HEAD with `git reset --keep <old-head>`, push nothing more, and end as `push-failure-states` says:
  - `needs-human` naming the refusal for a permission refusal: no write access, a protected branch, HTTP 403, or a server-side hook decline such as GH006 or GH013.
  - `failed` naming the error for a lease mismatch, a network error or anything else.
- Never use `--admin` or any route around protection (`admin-bypass`).

**After the push:**

1. Record the pushed sha.
2. Read `gh pr view <n> --json mergeable,mergeStateStatus` again, re-reading while `UNKNOWN`, up to five reads.
3. If the PR is now `CONFLICTING` or `DIRTY`, or the check is unreadable:
   1. Do not push again.
   2. Skip the collapse step.
   3. Send the replies, and make sure none of them claims the PR is ready.
   4. End `needs-human` naming the conflict or the check.
4. If the base moved again while the PR stays mergeable, do nothing: the next round or the merge path takes it.

### 11. Settle the issue link

Settle the link before the collapse step, so that the commit message and the PR body carry the same link (`collapse-keeps-link`).

- If this round completed some deferred criteria, the new **Deferred** list drops them.
- If it completed the last of them, `Refs #N` becomes `Closes #N` and the list is dropped.
- A **Deferred** list appears only under `Refs #N`, never next to a closing keyword.

### 12. Collapse step

`merge.message_source` is `commits`, so this step runs only when every thread on this PR will be resolved after replies, and the push step did not end the round. If any thread will stay open, keep the fixup commit separate so the reviewer can diff only the delta (`collapse-with-open-threads`).

**Approval check.** Run this just before the collapse, after the push step's push.

1. Run `gh api --paginate repos/116-Labs/cuecal/pulls/<n>/reviews`.
2. For each reviewer, take their latest review whose state is `APPROVED` or `CHANGES_REQUESTED`.
3. Count it if it approves, is not dismissed, and its `commit_id` equals the current remote head. The protection facts are absent, so only approvals of the current head count.
4. If the count meets `required_approvals` (1), do not collapse. A push here would dismiss those approvals for no content change (`content-free-push-after-approval`). Keep the commits, and report that the collapse was skipped to keep the approvals and that whoever merges supplies the message.

A round whose push carried fixes has already lost its approvals on this repo, so the collapse goes ahead.

**Gates when the collapse is the round's only push.** If the push step pushed nothing, run every gate in the checkout on the head first, timed. If a gate is red, end `needs-human` naming it, with nothing pushed (`gates-green-before-push`). The fix push always lands before a collapse that reads the remote head; otherwise the collapse would ship without the fix.

**Collapse routine (PR mode).**

1. **Regime:** `commits`, so the collapse applies.
2. **Merge base:** `<merge-base>` is the output of `git merge-base HEAD origin/<base>`, with `<base>` the current base (`main` after a retarget). Count with `git rev-list --count <merge-base>..HEAD`. If the count is 0 or 1, do nothing.
3. **Soft gates:** override the unresolved-threads gate, print the unresolved-thread count, and name the override in the report. The approval count above decides the approval gate.
4. **Hard gates (never overridden):**
   - If `isCrossRepository` is true (the branch lives on a fork), refuse.
   - Run `git log --format=%ae <merge-base>..HEAD` and compare each email with the email in `git var GIT_AUTHOR_IDENT` (never `git config user.email`). If any commit has a different author, refuse.
   - `collapse-remote-contained`: run `git ls-remote origin refs/heads/<branch>` just before the rewrite. The remote head must equal the inspected sha, and `git merge-base --is-ancestor <remote-head> <pre-collapse-head>` must exit 0. If not, refuse.
5. **Rewrite in a throwaway worktree:**
   1. Run `git worktree add --detach <run-dir>/worktree <pre-collapse-head>`, then `cd <run-dir>/worktree`.
   2. Record `git rev-parse HEAD^{tree}`.
   3. Write `<run-dir>/scratch/collapse-msg.txt` as one Conventional Commits message for the whole change. Base it on `git log --format=%B <merge-base>..HEAD`. Drop process messages such as "wip" or "fix lint". Keep the issue link settled in step 11 and any **Deferred** list. Add no attribution (`collapse-keeps-link`, `attribution-policy`).
   4. Run `git reset --soft <merge-base>`. Always reset to the merge base, never to the base's tip.
   5. If `git diff --cached --quiet` exits 0, the change nets to empty: abort.
   6. Otherwise run `git commit -F <run-dir>/scratch/collapse-msg.txt` with hooks enabled. Compare `git rev-parse HEAD^{tree}` with the recorded tree. If they differ, abort and never commit again (`collapse-content-preserved`).
6. **Push:** run `git push --force-with-lease=<branch>:<pre-collapse-head> origin HEAD:refs/heads/<branch>`. This is the round's closing push and changes no tree. Handle failures as in the push step: a hook fix is pushed again; a permission refusal ends `needs-human`; anything else ends `failed`. The original HEAD is untouched in the checkout.
7. **Teardown:** `cd` back to the checkout and run `git worktree remove --force <run-dir>/worktree` on every exit path.
8. **Sync the checkout:** run `git fetch origin <branch>`, then `git reset --keep origin/<branch>`. Never pull after a collapse (`pull-after-collapse`).
9. **Report:** mode (PR), regime, commit count before and after, the gates that fired or were overridden, the tree hash, old → new sha, any backup refs in full, and the reset any other stale checkout now needs (a hard reset to `origin/<branch>`).

**On a refusal or abort:** a hard gate fired, or the content gate aborted. The pre-collapse HEAD stands and nothing more is pushed. Send the replies, none of which claims a collapse, and end `failed` naming the gate.

### 13. Reply step

This step runs on every exit after items were decided, not only on `done`.

**Thread replies** (`every-thread-answered`, `reply-matches-action`).

1. Write each reply body to a file.
2. Write `<run-dir>/scratch/reply.graphql` with an `addPullRequestReviewThreadReply(input:{pullRequestReviewThreadId:$threadId, body:$body})` mutation.
3. Run `gh api graphql -F query=@<run-dir>/scratch/reply.graphql -F threadId=<thread-id> -F body=@<file>`.

What each reply says:

- **Fix:** name the sha on the remote that contains the fix: the collapsed sha after a collapse, otherwise the fixup sha.
- **Imported fix:** also name where the fix landed.
- **Import that does not apply:** say why.
- **Deferral:** file the follow-up issue first with `gh issue create --repo 116-Labs/cuecal --title "<title>" --body-file <file>`, then name its number. A point that does not meet the follow-up bar is fixed, answered or pushed back instead.
- **Pushback:** give the reasons.
- **Fix not pushed:** if the round stopped before or at its push (the round limit, a rebase conflict, a gate red on the rebased tree, an unreadable mergeability check, a refused or failed push, a hook fix beyond remit, or a refused collapse), say the fix was prepared, not pushed, and give the reason. Leave the thread open. No reply names a sha the remote does not have or claims the PR is ready.
- **No collapse, link changed:** if no collapse ran (a thread stays open, the push step skipped it, the approvals kept it from running, or it was refused or aborted), say that the link and the **Deferred** list stay as the branch's commit carries them.

**One PR comment.** Answer every `review-body` and `issue-request` item, and every threadless import, in one PR comment written to a file and posted with `gh pr comment <n> --body-file <file>`. Quote or link each request: an issue request by its comment link or the edit's time. Give each decision: a sha, an issue number, or the reasons (`body-requests-answered`, `issue-requests-answered`).

### 14. Resolve threads by rule

`resolve-by-rule`: write `<run-dir>/scratch/resolve.graphql` with a `resolveReviewThread(input:{threadId:$threadId})` mutation and run `gh api graphql -F query=@<run-dir>/scratch/resolve.graphql -F threadId=<thread-id>`. Resolve a thread only when:

- it was fixed and the fix is on the remote;
- it is outdated;
- it was deferred with agreement recorded on the thread.

Pushbacks and unagreed deferrals stay open (`resolve-pushback`, `resolve-unagreed-deferral`). `review-body` and `issue-request` items have nothing to resolve. Resolving another PR's thread may fail on permissions. The reply is what matters: note the failure, but it does not block the run.

### 15. Description step

Run this step after the last push. Test counts and behaviour claims go stale across rounds, so check them only now (`description-matches-head`).

1. Re-read the PR body against the pushed tree and the round's outcome: the summary, the test plan, and any test count, gate result or behavioural claim the round changed.
2. Edit only what is now false or missing, and keep untouched prose.
3. Keep any attribution section as it is. The profile's attribution is `none`, so add none.
4. Keep the issue link true to the issue-link rule:
   - **If a collapse ran,** write the link settled in step 11 into the body, matching the head commit.
   - **If no collapse ran,** leave the link and the **Deferred** list as the branch's commit carries them.
5. Write the body to `<run-dir>/scratch/pr-body.md` and run `gh pr edit <n> --body-file <run-dir>/scratch/pr-body.md`.
6. Skip this step when the round changed no code and no claim became false. Editing the description pushes nothing.

### 16. Request review again

The profile names no fixed reviewers (`reviewers: []`). The review identity `116-labs-gaal-review[bot]` is started by Gaal's `reaction` start signal, so do not request it yourself.

- Re-request each human who reviewed this PR with `gh pr edit <n> --add-reviewer <login>`.
- When this round's push dismissed approvals, Gaal itself re-requests exactly those reviewers, once per push, quoting the run result's `push`. Post no notice of your own about the dismissal.

### 17. Run result

Write the run result on every exit path, including `failed`, `needs-human` and `needs-clarification` (`run-result-written`).

1. Read `finished_at` with `date -u +%Y-%m-%dT%H:%M:%SZ`.
2. For `commit_sha`, read the PR head with `gh pr view <n> --json headRefOid` when a PR is known.
3. Write `<run-dir>/result.json.tmp` with the file tool, then run `mv <run-dir>/result.json.tmp <run-dir>/result.json`. Never leave the `.tmp` file behind.

```json
{
  "schema_version": 1,
  "run_id": "<run id from the run context>",
  "blueprint": "revise-pr",
  "blueprint_version": "1.8.0",
  "repo": "116-Labs/cuecal",
  "issue": 123,
  "pr": 45,
  "status": "done",
  "attempts": 1,
  "gates": [
    {"name": "lint", "command": "uv run ruff check .", "exit_code": 0, "duration_ms": 2000},
    {"name": "test", "command": "uv run pytest", "exit_code": 0, "duration_ms": 14000}
  ],
  "branch": "gaal/123-example",
  "commit_sha": "<40-hex head sha>",
  "push": {"why": "Carried fixes for 3 review threads.", "changes": "<range-diff summary or tree unchanged>"},
  "started_at": "2026-01-01T00:00:00Z",
  "finished_at": "2026-01-01T00:05:00Z"
}
```

Field rules:

| Field | Rule |
|---|---|
| `issue` | The routed linked issue, or `null`. |
| `pr` | `null` only when no PR was determined. |
| `branch` | `<branch>`, or `null`. |
| `commit_sha` | The PR head after the run, or `null` when no PR is known. When nothing needed changing (no fix, no required rebase, no collapse), it is the unchanged head. |
| `attempts` | The rounds used, at least 1 and at most 3. |
| `gates` | Follows `gates-final-tree`: only the runs on the final tree (the pushed tree, the rebased tree after a rebase), in the order they ran, each gate once with its green run. A gate that did not run is absent. A `done` result never lists a non-zero `exit_code`, and `gates` may be empty when nothing was run. A result that is not `done` lists the runs on the tree it stopped on, and may include the red run that stopped it. |
| `push` | Only when the run pushed. `why`: the fixes carried, or what required the rebase, in one sentence. `changes`: a short range-diff summary of `<start-head>` against the final head, or `tree unchanged` when their trees (`git rev-parse <sha>^{tree}`) are equal. |
| `reason` | Required unless `done`: one sentence of at most 160 characters naming the decision or action needed. |
| `questions` | Required and non-empty for `needs-clarification`, quoting each ambiguous request or asking for the PR. |

Add no other fields.

The final message reports one row per item (source, decision, sha or issue). It also lists open pushbacks, any skipped or overridden collapse gates, linked numbers that named no issue, pre-existing red gates, and gates that are not required and failed. Keep the report truthful (`truthful-report`).

## Exit states

- `done`: every thread, every actionable review-body request and every issue request since the PR opened is answered, the description matches the head, and the branch was pushed with green gates. If nothing needed changing, nothing is pushed and `commit_sha` is the unchanged head. Open pushbacks are normal and are listed. A collapse skipped to keep approvals is reported, not treated as an error.
- `needs-clarification`: no PR could be determined, or a request is too ambiguous to fix without guessing. In the second case, its question was asked on its thread or in the PR comment after every other item was handled. `questions` quote it.
- `needs-human`: any of the following:
  - the gates are still red after 3 rounds;
  - a gate was red on the head before a collapse that would have been the only push (nothing pushed);
  - a merged stack parent's last head is not an ancestor of the branch (nothing pushed);
  - a rebase conflict or an unmergeable PR blocks the push;
  - the push was refused for permission;
  - a mergeability check was unreadable;
  - a gate was red on the rebased tree (nothing pushed);
  - the PR became `CONFLICTING` or `DIRTY` after the push.

  `reason` names which.
- `failed`: any of the following:
  - the PR is not open;
  - the PR head is the base branch;
  - the install failed (not possible here, since no `install` command is named);
  - the push failed for another reason, such as a lease mismatch or a network error (HEAD restored);
  - the collapse routine refused or its content gate aborted;
  - a hook fix was beyond this run's remit;
  - a read failed or a listing was truncated.

  `reason` names the step. On every exit after items were decided, the reply step's replies and PR comment were still posted, with unpushed fixes reported as prepared, not pushed.

## Invariants

Blueprint invariants:

- `every-thread-answered`: every unresolved thread at the start, including imports that did not apply, has a reply at the end.
- `one-push-per-round`: at most one push with changes per round, after all fixes. The only other push allowed is the collapse step's closing push, which leaves the tree unchanged. A moved base never causes a second push.
- `gates-green-before-push`: every required gate exited 0 on the pushed tree.
- `reply-matches-action`: each reply states what was done: a sha containing the fix, an issue number, or reasons.
- `resolve-by-rule`: resolve only threads that were fixed, are outdated, or were deferred with agreement recorded on the thread.
- `target-branch-only`: code changes land only on this PR's branch. Imported fixes name where they landed.
- `bounded-rounds`: gate-fix cycles stop at 3 rounds, ending `needs-human`.
- `body-requests-answered`: every actionable request in a latest review body is acted on or answered in the PR comment.
- `issue-requests-answered`: every request on the linked issue since the PR opened, by its author or a maintainer, is acted on or answered with a sha, a follow-up issue or a reason.
- `description-matches-head`: the description states nothing the pushed head contradicts. Its issue link matches the head commit's, and a **Deferred** list appears only under `Refs`. It is edited before review is re-requested.
- `base-drift-checked`: mergeability was read before and after the push. A rebase happens only when required, the gates are re-run on the rebased tree, and a conflict after the push ends `needs-human`.
- `push-explained`: a run that pushed records `push.why` and `push.changes`. A rebase compares tree identity before and after it.

Shared invariants:

- `explicit-staging`: stage only manifest paths, one by one.
- `base-untouched`: never commit or push to `main` or the base branch.
- `fail-closed-reads`: a failed read ends the run (the mergeability check ends `needs-human`).
- `complete-listings`: listings are paginated to the end, or the run ends `failed`.
- `truthful-report`: the report and result describe only what happened.
- `status-preserved`: no command's status is lost.
- `attribution-policy`: attribution is `none`, so add nothing.
- `run-result-written`: the result is written atomically on every exit path.
- `gates-final-tree`: `gates` lists only the final tree's runs.
- `install-before-gates`: the profile names no install, so install nothing and run the gates in the checkout.
- `push-failure-states`: a hook rejection is fixed and pushed again. A permission refusal ends `needs-human`. Anything else ends `failed` after restoring HEAD, and is never retried.
- `collapse-remote-contained`: the remote head equals the inspected sha and is an ancestor of the pre-collapse head.
- `collapse-content-preserved`: an empty rewrite or a tree mismatch aborts, with nothing pushed.
- `collapse-keeps-link`: the collapsed message keeps the settled link and any **Deferred** list.

## Forbidden actions

Blueprint:

- `push-red`: pushing with a failing required gate.
- `piecemeal-push`: pushing once per comment instead of once per round.
- `resolve-pushback`: resolving a thread where the revision disagreed with the reviewer.
- `resolve-unagreed-deferral`: resolving a deferral only the reviser decided on, or one with no issue number.
- `apply-unreproduced-import`: applying an imported finding that does not reproduce here.
- `collapse-with-open-threads`: collapsing while any thread on this PR will stay open.
- `pull-after-collapse`: pulling into a checkout after a collapse. Reset it to the remote instead.
- `content-free-push-after-approval`: pushing a collapse or an unrequired rebase while the PR holds the 1 required approval on its current head.

Shared:

- `bare-force-push`: force-pushing without `--force-with-lease=<branch>:<sha>`. Never use `--force` or `-f`.
- `admin-bypass`: never use `gh pr merge --admin` or any other admin route around protection.
- `bypass-hook`: never use `--no-verify`, `git commit -n`, `--no-gpg-sign` or `-c core.hooksPath=…`. Never turn off the hook manager, edit or move hook files or `.git/config`, or retry a rejected commit or push by another route.
- `machine-specific-paths`: no home directories, drive letters, private scripts or services. Use only `<run-dir>` and checkout-relative paths.
- `commit-foreign-edits`: never commit changes this run did not make. Never use `git add -A`, `git add .` or `git commit -a`.
