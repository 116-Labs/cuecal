---
name: gaal-revise-pr
description: >-
  Revises an open pull request in 116-Labs/cuecal after review. It answers every
  unresolved review thread, every actionable request in a review body and every
  request made on the linked GitHub issue since the PR opened, each with a
  verified code change or a reasoned reply. It runs the profile gates
  (`uv run ruff check .` and `uv run pytest`), checks base drift and pushes at
  most once per round with an explicit lease. When every thread will resolve,
  it collapses the branch to one Conventional Commits commit, unless that would
  throw away approvals. It replies to threads and resolves them by rule, keeps
  the PR description true to the pushed head, requests review again and writes
  the run result to result.json in the run directory. Use it when a dispatch or
  the user names a repo and PR number and asks for the revise-pr step ("revise
  the PR", "address the review comments"), including imported feedback from
  another PR, a single comment URL or free-text notes. Do not use it to
  implement an issue (gaal-implement), open a PR (gaal-open-pr), review a PR
  (gaal-review-pr), merge or deploy. When no PR can be determined, do not guess;
  end as needs-clarification.
---
<!-- gaal-stamp blueprint=revise-pr@1.8.0 shared=1.5.0 profile=833de6ae33df6d68 generated=2026-10-08 core=aee666ea0d453d32 forbidden=605730d3fee67b49 content=7fbecdc90ae807ad -->

# gaal-revise-pr

Closes the review loop on one open PR in `116-Labs/cuecal` (default branch `main`, tracker: GitHub issues). Each unresolved thread, actionable review-body request and issue request gets either a fix or a reasoned reply. The branch is pushed once per round with green gates. Threads end in a state that matches what was done, the PR description describes the pushed head, and review is requested again.

Blueprint: `revise-pr` version `1.8.0` (shared rules `1.5.0`).

## Project facts used by this skill

- Repo `116-Labs/cuecal`, default branch `main`, private. Gaal branches use the `gaal/` prefix. This skill never creates a working branch. It changes only the PR's own head branch (`target-branch-only`) and never commits or pushes to `main` or any other base branch (`base-untouched`).
- Gates, both `required: true`, run from the checkout root exactly as written:
  - `lint`: `uv run ruff check .`
  - `test`: `uv run pytest`
- `preflight`: none. Advisory commands: none. `install`: none. Nothing is ever installed (`install-before-gates`). The gates run in the checkout itself, where dependencies are already installed, never in a throwaway worktree (which has no install).
- Commits: `single_commit: true`, Conventional Commits (`type(scope): subject`). Attribution policy is `none`: no `Co-Authored-By` line, no "generated with" line, no AI or tool attribution in any commit message, PR body or comment (`attribution-policy`).
- Merge: `method: squash`, `message_source: commits`, `queue: false`, `auto: false`. Because `message_source` is `commits`, the collapse regime applies. This skill never merges.
- Review: `required_approvals: 1`, `threads_block_merge: false`, `reviewers: []`, `start_signal: reaction`, separate reviewer identity `116-labs-gaal-review[bot]`. The protection facts `dismiss_stale_approvals` and `require_last_push_approval` are absent from the profile, so both count as true: every push is treated as dismissing approvals, and only approvals of the current head count.
- Push identity: `116-labs-gaal-push[bot]`.
- Limits: `revise_rounds: 3`. At most **3** gate-fix cycles per run (`bounded-rounds`).
- Stacking: the profile names no stacking tool. A PR is stacked when its base branch is not `main`.

## Headless command rules

- Only these commands may run: `git`, `gh`, `mkdir`, `mv`, `cp`, `ls`, `cat`, `date`, `pwd` (any arguments), plus `uv run ruff check .` and `uv run pytest` exactly as written, nothing added. Change directory with `cd` and a literal path. Run one command per call; no chains with `&&`, `;` or `|` unless every part is allowed on its own.
- `<run-dir>` stands for the literal run directory path from the run context (the value of `GAAL_RUN_DIR`), and `<run-id>` for the literal run id (the value of `GAAL_RUN_ID`). `<checkout>` stands for the literal checkout root path recorded with `pwd` at the start. Other placeholders (`<n>`, `<sha>`, `<branch>`, `<base>`, `<path>`) stand for literal values read earlier. Never write a dollar-sign variable, a command substitution or backticks in a command, and never put `NAME=value` in front of one.
- Scratch files live in `<run-dir>/scratch`; the throwaway collapse worktree is `<run-dir>/worktree`. Never use `/tmp` or `mktemp`.
- Write every commit message, comment body, PR body and GraphQL query to a file with the file-writing tool, then pass it by path: `git commit -F <file>`, `gh pr comment <n> --body-file <file>`, `gh pr edit <n> --body-file <file>`, `gh issue create --body-file <file>`, `gh api <endpoint> -F body=@<file>`, `gh api graphql -F query=@<file>`. Never write files through shell redirection. GraphQL query files contain literal values (owner, name, numbers, cursors, thread ids), no query variables; paginate by writing the next page's query with `after:"<endCursor>"` until `hasNextPage` is false.
- Quote every glob passed to a command. List uncommitted paths with `git status --porcelain=v1 --untracked-files=all`.
- Force-push only as `git push --force-with-lease=<branch>:<sha> origin HEAD:refs/heads/<branch>` (`bare-force-push`). Never skip or redirect verification: no skip-verify flag, no `git commit -n`, no signing bypass, no change to where git looks for hooks, no hook manager switched off, no hook file or `.git/config` edited, moved or restored, no admin merge (`bypass-hook`, `admin-bypass`). To find the hooks directory, run `git rev-parse --git-path hooks`; never write a command that names the hooks-path setting. Never stage wholesale and never commit all tracked changes at once; stage named paths only.
- Read the time only with `date -u +%Y-%m-%dT%H:%M:%SZ`. Time a gate by running `date -u +%s` just before and just after it, as separate calls; `duration_ms` is the difference times 1000.
- Every failed read (an error, expired auth, a rate limit) is a failure, never "nothing there" (`fail-closed-reads`). Paginate every listing to the end (`--paginate` for REST, the `pageInfo` loop for GraphQL); a listing that cannot be completed ends `failed` naming it (`complete-listings`). Never let a pipe or filter hide a command's exit status (`status-preserved`).
- When GitHub reports `mergeable` as `UNKNOWN`, read it again, up to five reads in all. There is no `sleep`; the time between calls is the wait. Still `UNKNOWN` after the fifth read means unreadable, never mergeable.

## Steps

The *push step* commits the fixes, checks base drift and pushes. The *collapse step* applies the single-commit collapse routine. The *reply step* replies to every thread and posts the one PR comment. The *description step* brings the PR description up to date. The *run result* is the last step. Once items are decided (the decide step), every exit path still runs the reply step before the run result. Every exit path, without exception, ends with the run result.

### 1. Start and confirm the PR is open

1. Run `date -u +%Y-%m-%dT%H:%M:%SZ` and keep it as `started_at`. Run `pwd` and keep it as `<checkout>`. Run `mkdir -p <run-dir>/scratch`.
2. Take the PR number from the dispatch. If no PR can be determined, do not guess: go to the run result with `needs-clarification`, `pr: null`, and a question asking which PR to revise.
3. Run `gh pr view <n> --repo 116-Labs/cuecal --json number,state,isCrossRepository,headRefName,headRefOid,baseRefName,baseRefOid,createdAt,body,closingIssuesReferences,commits,url`. A failed read ends `failed` naming it.
4. If `state` is `CLOSED` or `MERGED`, end `failed` ("PR #<n> is not open").
5. Keep `<branch>` = `headRefName`, `<base>` = `baseRefName`, `<inspected-sha>` = `headRefOid`, and `createdAt`. If `<branch>` is `main`, end `failed` (`base-untouched`).

### 2. Check out the PR head

1. Run `git status --porcelain=v1 --untracked-files=all`. If the checkout has uncommitted changes, do not discard, stash or commit them; they may be a person's in-progress work (`commit-foreign-edits`). End `failed` naming the dirty checkout.
2. Run `git fetch origin <branch>`, then `git rev-parse origin/<branch>`. It must equal `<inspected-sha>`; if not, re-read the PR and take the fresh `headRefOid` as `<inspected-sha>`.
3. If a local `<branch>` exists (`git branch --list '<branch>'`), count its local-only commits with `git rev-list --count origin/<branch>..<branch>`. If any, back them up with `git branch gaal/backup/<branch>-<short-sha> <branch>`, verify with `git rev-parse gaal/backup/<branch>-<short-sha>`, and report the full ref.
4. Run `git checkout -B <branch> origin/<branch>`. Keep `<start-head>` from `git rev-parse HEAD` and `<start-tree>` from `git rev-parse 'HEAD^{tree}'`.
5. Install: the profile names no `install` command, so install nothing and use this checkout's existing environment (`install-before-gates`). A failed install would end `failed` naming the command; with no install command none can fail.

### 3. List every unresolved review thread

1. Write `<run-dir>/scratch/threads-1.graphql` with the file tool: `repository(owner:"116-Labs", name:"cuecal") { pullRequest(number:<n>) { reviewThreads(first:100) { pageInfo { hasNextPage endCursor } nodes { id isResolved isOutdated path line comments(first:100) { totalCount nodes { id databaseId author { login } body url createdAt } } } } } }`.
2. Run `gh api graphql -F query=@<run-dir>/scratch/threads-1.graphql`. While `hasNextPage` is true, write the next query file with `reviewThreads(first:100, after:"<endCursor>")` and run it. If a thread's `totalCount` exceeds the comments returned, the listing is truncated: end `failed` naming it (`complete-listings`).
3. Keep the threads with `isResolved: false`. Record every thread `id` and its first comment's `databaseId` in `<run-dir>/scratch/threads.json` now, before any history rewrite: a rebase or collapse marks threads outdated, and replies then still work through the thread's reply relation.
4. Tag each item `pr-thread`.
5. Load imported feedback from the dispatch, tagging each item with its source:
   - **Another PR:** list that PR's unresolved threads the same way.
   - **A comment URL:** check its shape before extracting ids. `#discussion_r<id>` is a review comment inside a thread. `#issuecomment-<id>` is an issue-level comment with no thread; it is answered in the PR comment.
   - **Free-text notes:** each distinct point becomes an item.

### 4. Read review bodies

1. Run `gh api repos/116-Labs/cuecal/pulls/<n>/reviews --paginate` and `gh api repos/116-Labs/cuecal/issues/<n>/comments --paginate` (to see what was already answered).
2. For each reviewer, read the body of their latest review, plus any earlier review body whose requests were never answered by a later commit or comment.
3. Each actionable request in a body (a change asked for, a finding listed only in the body) becomes an item tagged `review-body`. Reviewers sometimes list a real finding only in the body, where no thread exists to reply in; it is owed a reply in the PR comment (`body-requests-answered`).
4. Skip pure verdicts, praise and requests already answered by a later commit or comment.

### 5. Read requests on the linked issue

1. **Find the linked issues** by the issue-link rule: the union of `closingIssuesReferences` (GitHub fills it only for a PR based on `main`), every PR-body line opening with a closing keyword (`Closes`, `Fixes`, `Resolves` and their forms) or `Refs #N`, and every such line in each commit message (`commits` from the first step). Extract only the numbers.
2. **Check each number** with `gh api repos/116-Labs/cuecal/issues/<N>`. An answer with a `pull_request` key is a PR, and a 404 names nothing; neither is an issue link, neither brings requests, and the report names the number. Any other failed read ends `failed`.
3. **Pick the run result's `issue`:** the dispatch issue if one was named; else a reported closing issue; else, in the body and then each commit message, a closing-keyword line before a `Refs #N` line; else `null`.
4. **Read each issue fresh:** its body now, its comments with `gh api repos/116-Labs/cuecal/issues/<N>/comments --paginate`, and its body edits by writing `<run-dir>/scratch/issue-edits-1.graphql` (`repository(owner:"116-Labs", name:"cuecal") { issue(number:<N>) { author { login } userContentEdits(first:100) { pageInfo { hasNextPage endCursor } nodes { editedAt editor { login } diff } } } }`) and running `gh api graphql -F query=@<run-dir>/scratch/issue-edits-1.graphql`, paging with `after:"<endCursor>"` to the end.
5. **Cutoff:** the earlier of the PR's `createdAt` and the creation time of the newest `Gaal finished implement …: done.` comment on the issue (when Gaal's newest done implement run started; open-pr only published that work).
6. **Who counts:** the issue's author, or a maintainer, meaning a repository admin: `gh api repos/116-Labs/cuecal/collaborators/<login>/permission` reports `admin`. A 404 there means not a collaborator; any other failure ends `failed`.
7. **Requests:** every comment created after the cutoff by one of them, and every body edit by one of them since then (compare each edit's `diff`, the body it left, with the version before it).
8. **Skip:** comments carrying a `<!-- gaal:` marker; any bot's comments and edits (author type `Bot` or a login ending in `[bot]`); requests a PR comment already answers; and body edits whose every added or removed line lies between an opening `<!-- gaal:plan-drift -->` line and the next closing `<!-- /gaal:plan-drift -->` line, both marker lines included (implement's record of its plan, even under a maintainer's login). An edit with any changed line outside such a section is a request, including maintainer text appended after one.
9. **Tag** each actionable request (a change asked for in a comment, a criterion or requirement an edit added or changed) as `issue-request`. A comment asking for nothing (a status note, thanks) is no item.

Maintainers ask for more on the issue as often as on the PR; without this step the PR converges on the old scope. Gaal will not ask about a request this run saw again, so one left unanswered is lost (`issue-requests-answered`).

### 6. Re-verify imported items

For each imported item, check against this branch whether it reproduces, partly applies or does not apply. An import that does not reproduce is never applied (`apply-unreproduced-import`), but its thread still gets a reply giving the reason (`every-thread-answered`).

### 7. Decide each item

Give each item one decision:

- **fix:** change the code.
- **answer:** a question or explanation, no change.
- **defer:** only under the follow-up bar, meaning a user-visible defect outside the diff, in code this PR did not touch, that reproduces on `main`. Anything else is fixed, answered or pushed back, never filed. A deferral with no issue number and no agreed owner is a pushback in disguise (`resolve-unagreed-deferral`).
- **push back:** disagree, with reasons.

A `review-body` or `issue-request` item is decided the same way; its deferral has no thread to carry agreement, so nothing is resolved and the PR comment names the follow-up issue. An `issue-request` that widens the issue beyond what this PR can reasonably carry is deferred (with a follow-up issue only when the bar is met), otherwise answered with the reason.

A request ambiguous enough that any fix would be a guess does not stop the round: answer it by asking its question (on its thread, or in the PR comment for a `review-body` or `issue-request` item), handle every other item as usual, and end `needs-clarification` with `questions` quoting it, unless a `failed` or `needs-human` exit applies first.

From here on, every exit runs the reply step before the run result.

### 8. Make the fixes

1. Make every fix on `<branch>` in `<checkout>` with the file-editing tool. A fix for an imported item lands here too, and its reply says so (`target-branch-only`).
2. Record every path written in `<run-dir>/scratch/manifest.txt` (`explicit-staging`).
3. Note when a fix changes `pyproject.toml` or `uv.lock`; the profile has no install to re-run, so report it.

### 9. Run the gates (rounds with fixes)

1. In `<checkout>`, run `uv run ruff check .`, then `uv run pytest`, timing each with `date -u +%s` before and after. Record `name`, `command`, `exit_code`, `duration_ms`.
2. On a red gate, fix what it reports (add paths to the manifest) and run both gates again.
3. Each run of the gates is one cycle. After **3** cycles (`limits.revise_rounds`) without both green, stop: commit nothing and push nothing (`bounded-rounds`, `push-red`). Run the reply step, reporting the fixes as prepared, not pushed, and end `needs-human` ("revise round limit 3 reached with <gate> red").
4. A gate already red on `<start-head>` for reasons outside the diff is reported as pre-existing.
5. Keep only the final runs on the tree that will be pushed for `gates` (`gates-final-tree`); a gate that went red and was fixed appears once, with its green run.

### 10. Push step: commit, check base drift, push once

The push step runs every round, with or without fixes.

**Commit (when there are fixes)**

1. Stage each manifest path by name with `git add -- <path> <path>` (`explicit-staging`).
2. Run `git status --porcelain=v1 --untracked-files=all`: nothing this run wrote is left unstaged, and nothing foreign is staged (`commit-foreign-edits`).
3. Write `<run-dir>/scratch/fixup-msg.txt`: a Conventional Commits message such as `fix(<scope>): address review on #<n>` with a short body, no attribution.
4. Run `git commit -F <run-dir>/scratch/fixup-msg.txt` with hooks enabled: one fixup commit. If a hook rejects it, fix what it reports and commit again (`bypass-hook`); if the fix is beyond this run's remit, run the reply step and end `failed` naming the hook and quoting its output briefly.

Keep `<pre-rebase-head>` from `git rev-parse HEAD` and `<pre-rebase-tree>` from `git rev-parse 'HEAD^{tree}'`.

**Check base drift (`base-drift-checked`, also with no fix)**

1. Stacked PR (`<base>` is not `main`): find the parent with `gh pr list --repo 116-Labs/cuecal --head <base> --state all --json number,state,mergedAt,headRefOid`.
   - Parent merged: run only `git fetch origin main`, never `git fetch origin <base>` (the parent branch may be deleted). Keep `<old-parent-tip>` = the parent's `headRefOid`; if it is not local, run `git fetch origin pull/<parent-n>/head`.
   - Otherwise: `git fetch origin <base>` and `git fetch origin main`.
2. Not stacked: `git fetch origin main`.
3. Run `gh pr view <n> --repo 116-Labs/cuecal --json mergeable,mergeStateStatus,baseRefOid`, re-reading while `mergeable` is `UNKNOWN` (five reads at most). A failed or unreadable check ends `needs-human` naming the check, with nothing pushed (run the reply step first).

**Rebase only when required**: `mergeable` is `CONFLICTING`, `mergeStateStatus` is `DIRTY` or `BEHIND` (GitHub reports `BEHIND` only when the base requires up-to-date branches; never read branch protection for this), or the PR is stacked and its parent has merged. A base that only moved while the PR stays `MERGEABLE` and not `BEHIND` is not rebased onto: a rebase rewrites history the reviewer must range-diff, and an unrequired rebase on an approved PR is a content-free push (`content-free-push-after-approval`). A required rebase goes ahead even with no fix, and is then installed (nothing to install here), gated and pushed. With no fix and no required rebase, the push step pushes nothing.

**Rebase** (thread ids already saved; never interactive; branch commits kept as they are, no merge commit):

1. Merged stack parent:
   1. Run `git merge-base --is-ancestor <old-parent-tip> HEAD`. If it exits non-zero (the parent was rewritten, for example collapsed), do not rebase: end `needs-human` naming the parent PR, with nothing pushed.
   2. Run `git rebase --onto origin/main <old-parent-tip>`.
   3. Run `gh pr edit <n> --repo 116-Labs/cuecal --base main`. From now on `<base>` is `main` everywhere: the post-push check, the collapse's merge base and its author check.
   4. `<old-merge-base>` is `<old-parent-tip>`.
2. Otherwise: keep `<old-merge-base>` from `git merge-base <pre-rebase-head> origin/<base>`, then run `git rebase origin/<base>`.
3. If the rebase conflicts, list the conflicting paths with `git status --porcelain=v1 --untracked-files=all`, run `git rebase --abort`, and end `needs-human` naming them, with nothing pushed.
4. Compare tree identity: `git rev-parse 'HEAD^{tree}'` against `<pre-rebase-tree>`. Equal: record `tree unchanged`. Different: keep `<new-merge-base>` from `git merge-base HEAD origin/<base>` and run `git range-diff <old-merge-base>..<pre-rebase-head> <new-merge-base>..HEAD`; record its summary (every commit should pair `=`). Both go into the run result's `push` (`push-explained`).
5. Re-run both gates on the rebased tree (nothing to install; the profile has no `install`). A gate red here ends `needs-human` naming the gate and the base sha, with nothing pushed; run `git reset --hard <pre-rebase-head>` first. These runs replace the earlier ones in `gates`.

**Push once** (`one-push-per-round`, `gates-green-before-push`):

1. Run `git push --force-with-lease=<branch>:<inspected-sha> origin HEAD:refs/heads/<branch>` with hooks enabled.
2. A local hook rejection is fixed and pushed again (`bypass-hook`).
3. Any other failure is never retried (`push-failure-states`): run `git reset --hard <pre-rebase-head>`, push nothing more, run the reply step (fixes reported as prepared, not pushed), and end `needs-human` naming it for a permission refusal (no write access, protected branch, HTTP 403, a server-side hook declining it, GH006, GH013) or `failed` naming it for anything else (lease mismatch, network error).
4. After a successful push, `<inspected-sha>` becomes the pushed sha. Read `gh pr view <n> --repo 116-Labs/cuecal --json mergeable,mergeStateStatus` again (re-reading while `UNKNOWN`). `CONFLICTING` or `DIRTY`, or a failed or unreadable check: never push again, skip the collapse step, run the reply step (no reply claims the PR is ready) and end `needs-human` naming it. A base that moved again while the PR stays mergeable ends nothing; the next round or the merge path takes it.

### 11. Collapse step

Apply the shared collapse routine in PR mode only when every thread on this PR will be resolved after replies (`collapse-with-open-threads`) and `merge.message_source` is `commits` (it is). Otherwise keep the fixup commit separate so the reviewer diffs just the delta.

1. **Approval check** (after the push step's push): run `gh api repos/116-Labs/cuecal/pulls/<n>/reviews --paginate`. For each reviewer take their latest `APPROVED` or `CHANGES_REQUESTED` review; count those that are `APPROVED`, not dismissed, and whose `commit_id` equals the current remote head (the protection facts are absent, so only approvals of the current head count). If the count is at least 1 (`required_approvals`), do not collapse: a collapse changes no content and would throw the approvals away (`content-free-push-after-approval`). Keep the commits and report that the collapse was skipped to keep the approvals and that whoever merges supplies the message. A round whose push carried fixes has already lost its approvals on this repo, so the collapse then goes ahead.
2. **Settle the issue link first**, as the description step defines it (`Closes #N`, or `Refs #N` on its own line with the **Deferred** list), so the collapsed message carries the same link as the body (`collapse-keeps-link`, open-pr's `reference-consistent`).
3. **Gates when the collapse is the round's only push:** run both gates in `<checkout>` on the head first (`gates-green-before-push`). A red gate ends `needs-human` naming it, with nothing pushed.
4. **Soft gates:** the unresolved-threads gate is knowingly overridden (the threads just fixed resolve after the push); print the unresolved count and name the override in the report. The approval check above decides the other soft gate.
5. **Hard gates (never overridden):** `isCrossRepository` true (fork); any commit in `<merge-base>..HEAD` (`<merge-base>` from `git merge-base HEAD origin/<base>`) whose author email (`git log --format=%ae <merge-base>..HEAD`) differs from this run's identity in `git var GIT_AUTHOR_IDENT`; or `collapse-remote-contained` failing: `git ls-remote origin refs/heads/<branch>` must equal `<inspected-sha>`, and `git merge-base --is-ancestor <inspected-sha> HEAD` must exit 0.
6. **Idempotence:** `git rev-list --count <merge-base>..HEAD` of 0 or 1 means nothing to do.
7. **Rewrite in a throwaway worktree:** `git worktree add --detach <run-dir>/worktree <inspected-sha>`, then `cd <run-dir>/worktree`. Keep `<pre-collapse-tree>` from `git rev-parse 'HEAD^{tree}'`. Run `git reset --soft <merge-base>` (never to the base tip). Run `git diff --cached --quiet`; exit 0 means the rewrite nets to an empty change: abort. Write `<run-dir>/scratch/collapse-msg.txt`: one Conventional Commits message for the whole change, process messages dropped, the settled issue-link line and any **Deferred** list, no attribution. Run `git commit -F <run-dir>/scratch/collapse-msg.txt`; a hook rejection is fixed, never skipped. Compare `git rev-parse 'HEAD^{tree}'` with `<pre-collapse-tree>`; a difference aborts (`collapse-content-preserved`).
8. **Push:** `git push --force-with-lease=<branch>:<inspected-sha> origin HEAD:refs/heads/<branch>`. This is the round's closing push (`one-push-per-round`). A failure follows `push-failure-states` as in the push step.
9. **Teardown on every exit:** `cd <checkout>`, then `git worktree remove <run-dir>/worktree` (after an abort, first `git reset --hard <inspected-sha>` inside the worktree so it is clean). Then bring the checkout to the remote with `git fetch origin <branch>` and `git reset --hard origin/<branch>`, never a pull (`pull-after-collapse`).
10. A refusal (a hard gate fired) or an abort leaves the remote at the pre-collapse head: run the reply step (no reply claims a collapse) and end `failed` naming the gate.
11. Report: mode `PR`, regime `commits`, commit count before and after, gates that fired or were overridden, tree hash, old → new sha, backup refs in full, and that any other stale checkout must be hard-reset to the remote.

### 12. Reply step

1. Reply to every thread through its reply relation, which works on outdated threads: write `<run-dir>/scratch/reply-<k>.md` and run `gh api repos/116-Labs/cuecal/pulls/<n>/comments/<first-comment-databaseId>/replies -F body=@<run-dir>/scratch/reply-<k>.md`. For an imported thread on another PR, reply on that PR the same way and say where the fix landed (`target-branch-only`).
2. Each reply matches what was done (`reply-matches-action`): a fix names the sha on the remote that contains it (the collapsed sha after a collapse); a deferral names the follow-up issue, filed first with `gh issue create --repo 116-Labs/cuecal --title <title> --body-file <file>` naming the defect, reproduction and files, and linking this PR; a pushback gives reasons; an answer answers.
3. On an exit before or at the push (round limit, rebase conflict, red gate on the rebased tree, unreadable check, refused or failed push, hook fix beyond remit, refused collapse), a fix not pushed is reported as prepared, not pushed, with the reason. No reply names a sha the remote does not have or claims the PR is ready.
4. Answer every `review-body` and `issue-request` item, and every issue-level imported comment, in one PR comment: write `<run-dir>/scratch/pr-comment.md`, quoting or linking each request (an issue request by its comment link or the edit's time) with its decision (sha, issue number or reasons), and run `gh pr comment <n> --repo 116-Labs/cuecal --body-file <run-dir>/scratch/pr-comment.md`.
5. When no collapse ran, the reply says that the issue link and **Deferred** list stay as the branch's commit carries them. Every unresolved thread at the start has a reply now (`every-thread-answered`, `body-requests-answered`, `issue-requests-answered`).

### 13. Resolve threads by rule

Resolve a thread only when it was fixed and the fix is on the remote, it is outdated, or it was deferred with the reviewer's agreement recorded on the thread (`resolve-by-rule`). Write `<run-dir>/scratch/resolve-<k>.graphql` containing `mutation { resolveReviewThread(input:{threadId:"<thread-id>"}) { thread { isResolved } } }` and run `gh api graphql -F query=@<run-dir>/scratch/resolve-<k>.graphql`. Pushbacks and unagreed deferrals stay open for the reviewer (`resolve-pushback`, `resolve-unagreed-deferral`). With `threads_block_merge: false`, an open pushback does not block merge, but it still stays open. A failed resolve of another PR's thread (permissions) is reported, not a blocker; the reply is what matters. `review-body` and `issue-request` items have nothing to resolve.

### 14. Description step

Run after the last push, since test counts and behaviour claims go stale across rounds. Skip it when the round changed no code and no claim became false; editing the description pushes nothing.

1. Re-read the body (`gh pr view <n> --repo 116-Labs/cuecal --json body`) against the pushed tree and the round's outcome: summary, test plan, any test count, gate result or behavioural claim the round changed.
2. Edit only what is now false or missing. Keep the issue reference and any attribution section; do not rewrite untouched prose.
3. Issue link: a round that completes deferred criteria updates the **Deferred** list; one that completes the last of them turns `Refs #N` into `Closes #N` and drops the list. A **Deferred** list appears only under `Refs`. When no collapse ran (a thread stays open, the push step skipped it, approvals kept it from running, or the routine refused or aborted), leave the link and **Deferred** list unchanged in body and commit, as the branch's commit carries them (`description-matches-head`).
4. Write `<run-dir>/scratch/pr-body.md` and run `gh pr edit <n> --repo 116-Labs/cuecal --body-file <run-dir>/scratch/pr-body.md`, before review is requested again.

### 15. Request review again

The profile lists no fixed reviewers (`reviewers: []`); Gaal starts its own reviewer `116-labs-gaal-review[bot]` through the `reaction` start signal, so add nothing for it. Re-request each human reviewer who left a review or thread this round with `gh pr edit <n> --repo 116-Labs/cuecal --add-reviewer <login>`, except the reviewers whose approvals this round's push dismissed: Gaal itself re-requests exactly those, once per push, quoting the run result's `push`. Post no notice of your own about a dismissal.

### 16. Run result

Always the last step, on every exit path, including failures before any item was decided (`run-result-written`).

1. Run `date -u +%Y-%m-%dT%H:%M:%SZ` for `finished_at`.
2. Read `commit_sha` with `git rev-parse HEAD` after the remote-matching reset (the PR head after the run; the unchanged head when nothing was pushed; `null` only when no PR was found).
3. Write `<run-dir>/result.json.tmp` with the file tool, then run `mv <run-dir>/result.json.tmp <run-dir>/result.json`. Never leave the `.tmp` file behind.

Fields (no others allowed):

```json
{
  "schema_version": 1,
  "run_id": "<run-id>",
  "blueprint": "revise-pr",
  "blueprint_version": "1.8.0",
  "repo": "116-Labs/cuecal",
  "issue": 42,
  "pr": 57,
  "status": "done",
  "attempts": 1,
  "gates": [
    { "name": "lint", "command": "uv run ruff check .", "exit_code": 0, "duration_ms": 3000 },
    { "name": "test", "command": "uv run pytest", "exit_code": 0, "duration_ms": 21000 }
  ],
  "branch": "gaal/42-example",
  "commit_sha": "<40-hex sha>",
  "push": { "why": "Carried fixes for 2 review threads.", "changes": "1 commit added on top of 1 unchanged (=)" },
  "started_at": "<started_at>",
  "finished_at": "<finished_at>"
}
```

- `run_id` is the literal run id from the run context. `issue` is the picked issue or `null`; `pr` the PR number or `null`; `branch` is `<branch>` or `null`.
- `attempts`: gate-fix cycles used, at least 1, at most 3.
- `gates`: by `gates-final-tree`, only the runs on the final tree (the rebased one after a rebase), in run order, with real timings. A gate that did not run is absent (`truthful-report`). A `done` result never lists a non-zero `exit_code`. A non-`done` result lists the runs on the tree it stopped on, and may include the red run that stopped it. `gates` may be empty when nothing needed changing.
- `push`: only when the run pushed. `why` in one sentence (the fixes, or what required the rebase); `changes` is `tree unchanged` when the pushed tree equals `<start-tree>`, else a short range-diff summary of `<start-head>` against the final head (`push-explained`).
- `reason`: required unless `status` is `done`; one sentence, at most 160 characters, naming the decision or action needed. Detail goes in the PR comment and the final message.
- `questions`: required and non-empty for `needs-clarification`, quoting each ambiguous request or thread.
- Status precedence when several apply: `failed`, then `needs-human`, then `needs-clarification`, then `done`.

Final message: one row per item (source, decision, sha or issue), open pushbacks listed, collapse outcome or reason it was skipped, overridden soft gates, pre-existing red gates, linked numbers that were no issue.

## Exit states

- `done`: every thread, every actionable review-body request and every issue request since the PR opened is answered; the description matches the head; the branch is pushed with green gates. When nothing needed changing (no fix, no required rebase, no collapse), nothing is pushed, `commit_sha` is the unchanged head and `gates` may be empty. Open pushbacks are normal and listed. A collapse skipped to keep approvals is reported, not an error.
- `needs-clarification`: no PR could be determined, or a request was ambiguous enough that any fix would be a guess (asked on its thread or in the PR comment after every other item was handled as usual). `questions` quote it.
- `needs-human`: the round limit (3) was reached with red gates; a gate was red on the head before a collapse that was the round's only push; a merged stack parent's last head is not an ancestor of the branch; a rebase conflicted or the PR was unmergeable before the push; the push was refused for permission; a mergeability check was unreadable; a gate was red on the rebased tree; or the PR became `CONFLICTING` or `DIRTY` after the push. Nothing was pushed in the pre-push cases. `reason` names it.
- `failed`: the PR is not open; the install failed; the checkout was dirty; a hook fix was beyond this run's remit; the push failed for another reason (lease mismatch, network error; HEAD restored); the collapse routine refused or its content gate aborted; or a read failed or a listing was truncated (`fail-closed-reads`, `complete-listings`). `reason` names the step. Gates already red on the base are reported as pre-existing.

On every exit after items were decided, the reply step's replies and PR comment were posted, and fixes not pushed were reported as prepared, not pushed.

## Invariants

- `every-thread-answered`: every unresolved thread at the start has a reply at the end, including imports that did not apply.
- `one-push-per-round`: at most one push with changes per round, after all fixes; the only other push is the collapse's tree-preserving closing push. Never a second push to chase a moved base.
- `gates-green-before-push`: both gates exited 0 on the tree that was pushed.
- `reply-matches-action`: each reply describes what was done: a sha containing the fix, an issue number for a deferral, reasons for a pushback.
- `resolve-by-rule`: a thread is resolved only if fixed, outdated, or deferred with agreement recorded on the thread.
- `target-branch-only`: code changes land only on this PR's branch; a fix for an imported item names where it landed.
- `bounded-rounds`: gate-fix cycles stop at 3 (`limits.revise_rounds`), ending `needs-human`.
- `body-requests-answered`: every actionable request in a latest review body is acted on or answered in the PR comment with the reason.
- `issue-requests-answered`: every actionable request on the linked issue since the cutoff, by its author or a maintainer, is acted on or answered in the PR comment.
- `description-matches-head`: after a round that changed behaviour, tests or gate results, the description states nothing the pushed head contradicts, and its issue link matches the head commit's; edited before review is re-requested.
- `base-drift-checked`: base and mergeability read before and after the push; rebase only when required, branch commits kept, gates re-run; after the push, a conflict ends `needs-human`, never a second push.
- `push-explained`: a run that pushed records `push.why` and `push.changes`; a rebase compared tree identity.
- `explicit-staging`: stage only manifest paths, never wholesale.
- `base-untouched`: never commit or push to `main` or any base branch.
- `fail-closed-reads`: a failed read stops the run, `failed` naming it (the mergeability check ends `needs-human`).
- `complete-listings`: every listing paginated to the end, or the run ends `failed`.
- `truthful-report`: report and result describe what happened; "fixed in `<sha>`" only when that sha contains the fix.
- `status-preserved`: no command's failure is lost to a pipe, filter or guard.
- `attribution-policy`: attribution `none`; nothing added or dropped.
- `run-result-written`: `result.json` written atomically on every exit path.
- `gates-final-tree`: `gates` lists only the runs on the final tree.
- `install-before-gates`: the profile's `install` runs before gates; here it names none, so nothing is installed and gates run in the checkout.
- `push-failure-states`: hook rejection fixed and retried; anything else restores HEAD and ends `needs-human` (permission) or `failed`.
- `collapse-remote-contained`: before the collapse, the remote head equals the inspected sha and is an ancestor of the pre-collapse head.
- `collapse-content-preserved`: an empty rewrite or a tree mismatch aborts, restores and pushes nothing.
- `collapse-keeps-link`: the collapsed message carries the settled issue-link line and any **Deferred** list.

## Forbidden actions

- `push-red`: pushing with a failing required gate to clear comments.
- `piecemeal-push`: pushing once per comment instead of once per round.
- `resolve-pushback`: resolving a thread where the revision disagreed with the reviewer.
- `resolve-unagreed-deferral`: resolving a deferral only the reviser decided on.
- `apply-unreproduced-import`: applying an imported finding that does not reproduce on this branch.
- `collapse-with-open-threads`: collapsing while any thread on this PR will stay open.
- `pull-after-collapse`: pulling into a checkout after a collapse; hard-reset to the remote instead.
- `content-free-push-after-approval`: pushing a change that leaves content as it was (a collapse, an unrequired rebase) while the PR holds its 1 required approval on the current head.
- `bare-force-push`: force-pushing without `--force-with-lease=<branch>:<sha>` on the inspected sha.
- `admin-bypass`: merging, pushing or rewriting with admin privileges.
- `bypass-hook`: committing or pushing with verification skipped or redirected, or retrying a rejected commit or push by another route.
- `machine-specific-paths`: hard-coding a person's home directory, private scripts or services.
- `commit-foreign-edits`: committing changes this run did not make.
