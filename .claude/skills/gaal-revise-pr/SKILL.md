---
name: gaal-revise-pr
description: >-
  Revises an open pull request in 116-Labs/cuecal after review. It answers every
  unresolved review thread, every actionable request in a review body and every
  request made on the linked GitHub issue since the PR opened. Each one gets a
  verified code change or a reasoned reply. It installs with `uv sync --locked`,
  runs the profile gates (`uv run ruff check .` and `uv run pytest`), checks base
  drift and pushes at most once per round with an explicit lease. When every
  thread will resolve, it collapses the branch to one Conventional Commits commit
  with no attribution, unless that would throw away approvals. It replies to
  threads, resolves them by rule, keeps the PR description true to the pushed
  head, requests review again and writes the run result to result.json in the run
  directory. Use it when a dispatch or the user names a repo and a PR number and
  asks for the revise-pr step ("revise the PR", "address the review comments",
  "fix the review feedback"). That includes imported feedback such as threads from
  another PR, a single comment URL or free-text notes. Do not use it to implement
  an issue (gaal-implement), open a PR (gaal-open-pr), review a PR
  (gaal-review-pr), merge, publish or deploy. When no PR can be determined, do not
  guess. End as needs-clarification instead.
---
<!-- gaal-stamp blueprint=revise-pr@1.8.0 shared=1.5.0 profile=6f85855df888e336 generated=2026-10-09 core=aee666ea0d453d32 forbidden=605730d3fee67b49 content=453266a2282fcd5b -->

# gaal-revise-pr

This skill closes the review loop on one open PR in `116-Labs/cuecal`. Every item gets either a code change or a reasoned reply. Items are the unresolved threads, the actionable review-body requests and the requests on the linked issue since the PR opened. The branch is pushed at most once per round, with green gates. Threads end in the state that matches what was done. The PR description describes the pushed head. Then review is requested again.

## Project facts (from `.gaal/project.yml`)

- Repo `116-Labs/cuecal`. Default branch `main`. Tracker is GitHub issues. Branch prefix `gaal/`.
- Install: `uv sync --locked`. It runs before every set of gate runs.
- Gates, both `required: true`, run in this order and exactly as written:
  - `lint`: `uv run ruff check .`
  - `test`: `uv run pytest`
- The profile names no preflight and no advisory commands.
- Commits:
  - one commit per PR (`commits.single_commit: true`);
  - Conventional Commits;
  - `attribution: none`. Commit messages and PR bodies carry no co-author trailer, no "generated with" line and no other AI attribution.
- Merge: method `squash`, no merge queue, `auto: true`, `message_source: commits`. The squash message comes from the commits, so the collapse routine applies.
- Review settings:
  - `required_approvals: 1`
  - `threads_block_merge: true`
  - `reviewers: []`
  - `start_signal: reaction`
  - review identity `separate`, login `116-labs-gaal-review[bot]`
  - `dismiss_stale_approvals: true`
  - `require_last_push_approval: false`
  - `code_owner_reviews: true`
  - required CI checks `test` and `zizmor`
- Limits: `limits.revise_rounds: 3`. A run makes at most 3 gate-fix rounds.
- Push identity: `116-labs-gaal-push[bot]`.
- Stacking: the profile names no stacking tool. A PR is stacked when its base is not `main`. Its parent is the PR whose head branch is that base.

Because both protection facts are set and `require_last_push_approval` is false, an approval of an earlier commit still counts while it has not been dismissed. Because `dismiss_stale_approvals` is true, any push dismisses the approvals the PR holds.

## How to run commands

The run is headless. It refuses every command outside its allowlist and records each refusal.

**Allowed commands**
- `git`, `gh`, `mkdir`, `mv`, `cp`, `ls`, `cat`, `date` and `pwd`, with any arguments.
- `cd` with a literal path.
- Exactly these three commands, with nothing added: `uv sync --locked`, `uv run ruff check .` and `uv run pytest`.

**Placeholders**
- `<run-dir>` stands for the literal run-directory path given in the run context. Write that path out in full. Never expand the run-directory or run-id environment variables inside a command.
- The run id is also taken from the run context.
- `<checkout>` is the literal path that `pwd` printed at the start.
- `<n>` is the PR number. `<branch>`, `<base>`, `<sha>` and the other placeholders stand for literal values you have read.
- Never use shell variables, `${…}`, `$(…)`, backticks or a `NAME=value` prefix in a command.

**Command rules**
- Run one command per call. Do not chain with `&&`, `;` or `|`.
- Quote every glob, for example `git branch --list 'gaal/*'`.
- To run a command in another directory, `cd` there first with a literal path. Never add a flag such as `--prefix` to an allowed command.
- Pass `--repo 116-Labs/cuecal` to every `gh pr` and `gh issue` command.
- Pass every `gh api` field with `-F`.
- List uncommitted paths with `git status --porcelain=v1 --untracked-files=all`.
- Read the time with `date -u +%Y-%m-%dT%H:%M:%SZ`.
- Time a gate by running `date -u +%s` just before it and just after it, as separate calls. Its `duration_ms` is the difference times 1000.

**Files and scratch space**
- Write every file with the file tool, never through shell redirection.
- Write every commit message, PR body, comment, reply and GraphQL query to a file under `<run-dir>/scratch/`. Pass it by its path:
  - `git commit -F <file>`
  - `--body-file <file>` for `gh pr edit`, `gh pr comment`, `gh issue create` and `gh issue comment`
  - `-F body=@<file>` and `-F query=@<file>` for `gh api`
- Never write a body inline. The run checks the whole command, quoted text included.
- Scratch files and throwaway worktrees live only inside `<run-dir>`, never in `/tmp`.

**Verification hooks**
- Hooks always stay enabled. Never skip or redirect verification. To find the hooks directory, run `git rev-parse --git-path hooks`.
- Never edit, move or restore a hook file or `.git/config`.
- When a hook rejects a commit or push, fix what it reports and try again (`bypass-hook`).
- Force-push only with `--force-with-lease=<branch>:<sha>`, where `<sha>` is the head you inspected (`bare-force-push`).
- Never use admin privileges to get around protection (`admin-bypass`).

**Reading GitHub**
- A failed read is never an empty answer (`fail-closed-reads`). An error, an auth failure or a rate limit ends the run `failed` naming the read. The mergeability check is the exception: there it ends `needs-human`.
- Paginate every listing to the end with `--paginate --slurp`. If a listing cannot be completed, end `failed` naming it (`complete-listings`).
- Check every exit code. Never let a pipe, filter or guard hide one (`status-preserved`).
- `gh pr view` may report `mergeable` as `UNKNOWN`. Read it again while it does, up to five reads in all. No `sleep` is allowed: the time between calls is the wait. A value still `UNKNOWN` after the fifth read is unreadable, never mergeable.

## Steps

The steps refer to each other by name:
- the **push step** commits the fixes, checks base drift and pushes;
- the **collapse step** applies the collapse routine;
- the **reply step** replies to every thread and posts the PR comment;
- the **description step** brings the PR description up to date;
- the **run result** is written last.

Every exit path goes to the clean-up and the run result, early failures included. After items have been decided, every exit also runs the reply step first.

### Start

1. Run `date -u +%Y-%m-%dT%H:%M:%SZ` and keep the value as `started_at`.
2. Run `pwd` and keep the value as `<checkout>`.
3. Run `mkdir -p <run-dir>/scratch`.
4. Set the round counter to 1. It becomes `attempts`.

### Confirm the PR

1. Take the PR number from the dispatch. If no PR can be determined, do not guess. End `needs-clarification` with a question asking which PR to revise.
2. Run:

   `gh pr view <n> --repo 116-Labs/cuecal --json number,state,headRefName,headRefOid,baseRefName,isCrossRepository,createdAt,body,closingIssuesReferences,author`

3. If `state` is `CLOSED` or `MERGED`, end `failed` with the reason "PR #<n> is not open".
4. If `headRefName` is `main` or equals `baseRefName`, end `failed`. This run never commits or pushes to a base branch (`base-untouched`).
5. Keep these values:
   - `<branch>` = `headRefName`
   - `<base>` = `baseRefName`
   - `<sha>` = `headRefOid`, the inspected head
   - `<head-before-run>` = `<sha>`

### Check out the head and install

1. Run `git fetch origin <branch>`.
2. Run `git rev-parse origin/<branch>`. It must equal `<sha>`. If it differs, read the PR again and take the head the remote has now.
3. Run `git worktree add --detach <run-dir>/worktree <sha>`.
4. Run `cd <run-dir>/worktree`. Work there until clean-up. The person's checkout and any parallel work in it stay untouched.
5. Run `uv sync --locked`. Run it every time, even when dependencies look present, because they may be stale (`install-before-gates`). If it fails, end `failed` naming `uv sync --locked`.
6. Run `git rev-parse HEAD^{tree}` and keep the result as the tree before the run.
7. Run `git fetch origin <base>`, then `git merge-base HEAD origin/<base>`. Keep the result as `<merge-base-before-run>`. For a stacked PR whose parent branch is gone, use `main` here instead of `<base>`.

### List unresolved review threads

Read the threads through GraphQL, which exposes resolution state and thread ids.

1. With the file tool, write `<run-dir>/scratch/threads.graphql`. It is a query with the variables `owner`, `name`, `number` and `endCursor`. `gh api graphql --paginate` needs the cursor variable to be named `endCursor`. The query reads `repository.pullRequest.reviewThreads(first: 100, after: endCursor)` with `pageInfo { hasNextPage endCursor }`. For each node it reads `id`, `isResolved`, `isOutdated`, `path`, `line` and `comments(first: 100)`. For the comments it reads `totalCount` and each comment's `id`, `databaseId`, `url`, `author { login }`, `body` and `createdAt`.
2. Run:

   `gh api graphql --paginate --slurp -F query=@<run-dir>/scratch/threads.graphql -F owner=116-Labs -F name=cuecal -F number=<n>`

3. A thread's `totalCount` may be larger than the comments returned. Then read that thread's comments to the end with a paginated `node(id:)` query. If you cannot, end `failed` (`complete-listings`).
4. Keep every thread whose `isResolved` is false, and tag it `this-pr`.
5. Record each thread `id` now, before any rebase or collapse. A history rewrite marks threads outdated. Replies go through the thread id, which works on outdated threads too.

**Imports.** Imported feedback is optional. Each form becomes items tagged `import`:
- **Another PR's threads.** Run the same query with that PR's number.
- **A single comment URL.** Check its shape before you extract any id:
  - `#discussion_r<id>` is a review comment. Read it with `gh api repos/116-Labs/cuecal/pulls/comments/<id>`. Find its thread id in the thread listing of its PR.
  - `#issuecomment-<id>` is an issue-level comment. Read it with `gh api repos/116-Labs/cuecal/issues/comments/<id>`. It has no thread, so it is answered in the PR comment.
- **Free-text notes.** Each note becomes an item with no thread.

### Read review bodies

1. Run `gh api repos/116-Labs/cuecal/pulls/<n>/reviews --paginate --slurp`.
2. For each reviewer, read the body of their latest review. Also read any earlier review body whose requests were never answered.
3. A review body has no thread. Reviewers sometimes put a real finding only there, with no thread to reply in. Each actionable request in a body becomes an item tagged `review-body`. That means a change asked for, or a finding listed only in the body.
4. Skip pure verdicts, praise, and requests already answered by a later commit or comment. To check, read:
   - `gh api repos/116-Labs/cuecal/issues/<n>/comments --paginate --slurp`
   - `gh api repos/116-Labs/cuecal/pulls/<n>/commits --paginate --slurp`

### Read requests on the linked issues

Maintainers ask for more on the issue as often as on the PR. They write "also handle X" in a comment or add a criterion to the body. If those are skipped, the PR converges on the old scope.

**Find the linked issues.** By the issue-link rule they are the union of three sources. Extract only the issue numbers.
1. Every issue in `closingIssuesReferences`.
2. Every line of the PR body that opens with a closing keyword (`Closes`, `Fixes`, `Resolves` and their forms) or with `Refs #N`.
3. The same kinds of lines in each commit message.

**Check each number.** Run `gh api repos/116-Labs/cuecal/issues/<N>`.
- An answer with a `pull_request` key names a PR. It is no issue link.
- A 404 answer names nothing. It brings no requests, and the report names it.
- Any other failure ends `failed` (`fail-closed-reads`).

**Pick the issue for the run result's `issue`.**
- An issue named in the dispatch wins.
- Otherwise take a reported closing issue first.
- Otherwise look in the PR body and then in each commit message. Take a closing-keyword line before a `Refs #N` line.
- Use `null` when there is none.

**Read each linked issue fresh.**
1. Read the body as it stands now from `gh api repos/116-Labs/cuecal/issues/<N>`.
2. Read its comments with `gh api repos/116-Labs/cuecal/issues/<N>/comments --paginate --slurp`.
3. Read its body edits over GraphQL. Write `<run-dir>/scratch/edits.graphql`: a query with the variables `owner`, `name`, `number` and `endCursor`. It reads `repository.issue.userContentEdits(first: 100, after: endCursor)` with `pageInfo { hasNextPage endCursor }`, and for each node `editedAt`, `editor { login }` and `diff`. Then run:

   `gh api graphql --paginate --slurp -F query=@<run-dir>/scratch/edits.graphql -F owner=116-Labs -F name=cuecal -F number=<N>`

   Each edit's `diff` holds the body that edit left. Compare it with the version before it.

**Set the cut-off.**
1. Note the PR's `createdAt`.
2. Find Gaal's newest done implement run for the issue: the creation time of the newest issue comment `Gaal finished implement …: done.`.
3. Requests count from the earlier of the two times. open-pr only published that work and read nothing new.

**Decide which comments and edits are requests.** A comment created after the cut-off is a request when its author is the issue's author or a maintainer. So is a body edit made after the cut-off by one of them. A maintainer is an admin of the repo: `gh api repos/116-Labs/cuecal/collaborators/<login>/permission` reports `admin`.

These are never requests:
- a comment that carries a `<!-- gaal:` marker;
- a comment or edit by a bot (a login ending in `[bot]`, or type `Bot`);
- a request a PR comment already answers;
- a body edit whose every added or removed line lies between an opening `<!-- gaal:plan-drift -->` line and the next closing `<!-- /gaal:plan-drift -->` line, the two marker lines included. That is implement's own record, even when it was written under a maintainer's login.

An edit with any changed line outside such a section is a request. That includes maintainer text appended after a section. A body that merely contains a marked section is still read.

Each actionable request becomes an item tagged `issue-request`: a change asked for in a comment, or a criterion or requirement that an edit added or changed. A status note or thanks is no item. Gaal does not ask again about a request this run has seen, so none may be lost (`issue-requests-answered`).

### Re-verify imports

Check each `import` item against this branch: it reproduces, it partly applies, or it does not apply. Never apply an imported finding that does not reproduce here (`apply-unreproduced-import`). It still gets a reply that says why (`every-thread-answered`).

### Decide each item

Give each item one decision:
- **fix**;
- **answer**: a question or an explanation;
- **defer**: a follow-up issue, with agreement recorded on the thread;
- **push back**: disagree, with reasons.

**Deferrals meet the follow-up bar.** File a follow-up issue only for a user-visible defect outside the diff: wrong output a user can see, in code this PR did not touch, that reproduces on the base. Everything else is fixed, answered or pushed back, never filed. That covers style points, refactors, hardening ideas, invisible pre-existing defects and requests that widen the issue. A deferral with no issue and no agreed owner is a pushback, and is answered as one.

**`review-body` and `issue-request` items** are decided the same way. A deferral there has no thread to carry agreement, so it is not resolved, and its reply names the follow-up issue. An `issue-request` that widens the issue beyond what this PR can reasonably carry is deferred. It becomes a follow-up issue only when the bar is met. Otherwise it is answered with the reason.

**Ambiguous requests.** A request may be so ambiguous that any fix would be a guess. It does not stop the round:
1. Answer it by asking its question. Ask on its thread, or in the PR comment for a `review-body`, `issue-request` or threadless `import` item.
2. Decide and handle every other item as usual: fixes pushed, replies and the PR comment.
3. End the run `needs-clarification`, with `questions` quoting the request.

### Make the fixes

1. Make every fix in `<run-dir>/worktree`. Code changes land only on this PR's branch (`target-branch-only`). A reply to a fixed `import` item names where the fix landed.
2. Keep a manifest of every path you write.
3. Never change or stage a path you did not write (`commit-foreign-edits`).

### Run the gates (when the round has fixes)

1. If a fix changed `pyproject.toml` or `uv.lock`, run `uv sync --locked` again first. If it fails, end `failed` naming it.
2. In `<run-dir>/worktree`, run each gate with timing, one command per call:
   1. `date -u +%s`
   2. `uv run ruff check .`
   3. `date -u +%s`
   4. `date -u +%s`
   5. `uv run pytest`
   6. `date -u +%s`
3. Record `name`, `command`, `exit_code` and `duration_ms` for each gate.
4. If a gate is red, fix it, add the paths to the manifest, add 1 to the round counter and run every gate again.
5. Stop after `limits.revise_rounds` = 3 rounds. If a gate is still red, end `needs-human` naming the red gate (`bounded-rounds`). Never push red (`push-red`).

**Pre-existing failures.** A failure that does not trace to this PR may already be red on the base. Confirm it on the base:
1. `git worktree add --detach <run-dir>/base origin/<base>`
2. `cd <run-dir>/base`
3. `uv sync --locked`
4. Run the gate with timing.
5. `cd <run-dir>/worktree`
6. `git worktree remove <run-dir>/base`

Report a gate that is red on the base as pre-existing. It still blocks a push.

Only runs on the final tree go into `gates` (`gates-final-tree`). A gate that went red and was fixed appears once, with its green run. A run on a tree that was later replaced is not listed.

### Push step

The push step runs every round, whether or not the round has fixes. The branch is pushed once, after all fixes, never once per comment (`one-push-per-round`, `piecemeal-push`).

**1. Commit the fixes**, if there are any, as one fixup commit:
1. Stage each manifest path on its own with `git add -- <path>` (`explicit-staging`).
2. Run `git status --porcelain=v1 --untracked-files=all`. Nothing this run is responsible for may be left unstaged.
3. Write a Conventional Commits message to `<run-dir>/scratch/fixup-msg.txt`, for example `fix: address review feedback on #<n>`. It carries no attribution (`attribution-policy`).
4. Run `git commit -F <run-dir>/scratch/fixup-msg.txt`. Hooks stay enabled.
5. If a hook rejects the commit, fix what it reports, stage the fix and commit again (`bypass-hook`). If the fix is beyond this run's remit, end `failed` naming the hook and quoting its output briefly.

**2. Find a stacked PR's parent.** This applies only when `<base>` is not `main`. Run:

`gh pr list --repo 116-Labs/cuecal --head <base> --state all --json number,state,headRefOid`

The parent is that PR. Keep its number and `headRefOid` as `<old-parent-tip>`.

**3. Fetch the base (`base-drift-checked`).** Do this every round, even with no fix.
- If the parent has merged, run only `git fetch origin main`. Never fetch `origin <base>`, because the parent branch may have been deleted at merge.
- Otherwise run `git fetch origin <base>`. For a stacked PR, also run `git fetch origin main`.

**4. Read mergeability.** Run `gh pr view <n> --repo 116-Labs/cuecal --json mergeable,mergeStateStatus,baseRefOid`. Read it again while `mergeable` is `UNKNOWN`. A failed read, or a value still unreadable, ends `needs-human` naming the check, with nothing pushed.

**5. Decide whether to rebase.** Rebase only in these cases:
- the PR is `CONFLICTING` or `DIRTY`;
- `mergeStateStatus` is `BEHIND`;
- the PR is stacked and its parent has merged.

GitHub reports `BEHIND` only when the base requires up-to-date branches. Never read branch protection for this. Do not rebase onto a base that merely moved while the PR stays `MERGEABLE` and is not `BEHIND`. A rebase rewrites history, so the reviewer would have to range-diff. On an approved PR it would also be a content-free push (`content-free-push-after-approval`).

**6. Rebase, when it is required.** Thread ids were recorded before this.
1. Keep `<old-head>` = `git rev-parse HEAD` and the old tree `git rev-parse HEAD^{tree}`.
2. Rebase onto the fresh base. Keep the branch's commits as they are, with no merge commit.
   - **Normal rebase.** Run `git merge-base <old-head> origin/<base>` and keep the result as `<old-merge-base>`. Then run `git rebase origin/<base>`.
   - **Merged stack parent.** If `<old-parent-tip>` is not local, run `git fetch origin pull/<parent>/head`.
     1. Run `git merge-base --is-ancestor <old-parent-tip> HEAD`. If it exits non-zero, the parent was rewritten after this branch left it, for example by a collapse. Do not rebase. End `needs-human` naming the parent PR, with nothing pushed.
     2. Run `git rebase --onto origin/main <old-parent-tip>`. Then `<old-merge-base>` is `<old-parent-tip>`.
     3. Run `gh pr edit <n> --repo 116-Labs/cuecal --base main`. From now on `<base>` is `main` for every later step, including the post-push check, the collapse's merge base and its author check.
3. If the rebase conflicts, list the conflicting paths with `git status --porcelain=v1 --untracked-files=all`. Then run `git rebase --abort` and end `needs-human` naming those paths.
4. Compare tree identity. Run `git rev-parse HEAD^{tree}`.
   - If the tree equals the old tree, record `tree unchanged`.
   - Otherwise run `git merge-base HEAD origin/<base>` to get `<new-merge-base>`. Then run `git range-diff <old-merge-base>..<old-head> <new-merge-base>..HEAD`. Check that the PR's own change survived, with every commit paired `=`. Record the summary.

   Both results go into the run result's `push` (`push-explained`).
5. Run `uv sync --locked` again, then run every gate again with timing on the rebased tree. A gate red there ends `needs-human` naming the gate and the base sha, with nothing pushed. The branch and the new base disagree, which is a person's call. These runs replace any earlier ones in `gates`.

**7. Decide whether to push.** With no fix and no required rebase, the push step pushes nothing. A required rebase with no fix is still pushed, after the install and gates above.

**8. Push once.** Run:

`git push --force-with-lease=<branch>:<sha> origin HEAD:refs/heads/<branch>`

Here `<sha>` is the inspected head. Hooks stay enabled.
- A hook rejection is fixed and pushed again. That is the same push (`bypass-hook`).
- Any other failed push is never retried (`push-failure-states`). Run `git reset --hard <old-head>` to restore the HEAD from before any rebase, and push nothing more. Then:
  - a push refused for permission ends `needs-human` naming it. That covers no write access, a protected branch, HTTP 403 and a server-side hook such as GH006 or GH013;
  - any other failure ends `failed` naming it. That covers a lease mismatch and a network error.
- After a successful push, keep `<pushed-sha>` = `git rev-parse HEAD`.

**9. Check again after the push.** Run `gh pr view <n> --repo 116-Labs/cuecal --json mergeable,mergeStateStatus` and read it again while `UNKNOWN`.
- If the PR is now `CONFLICTING` or `DIRTY`, never push again (`one-push-per-round`). Skip the collapse step. Send the replies, none of which claims the PR is ready. End `needs-human` naming the conflict.
- An unreadable or failed check is handled the same way.
- A base that moved again while the PR stays mergeable ends nothing. The next round or the merge path takes it.

### Settle the issue link

Do this before the collapse step. The single commit message must carry the same link as the PR body.

1. Check each linked issue's criteria against the head:
   - a round that completes deferred criteria removes them from the **Deferred** list;
   - a round that completes the last of them turns `Refs #N` into `Closes #N` and drops the list.
2. A **Deferred** list appears only under `Refs #N`, never next to a closing keyword.
3. The description step writes the settled link into the PR body. The collapse step writes it into the commit message.
4. If no collapse runs, leave the link and the **Deferred** list unchanged in both the body and the commit message, as the branch's commit carries them. Say so in the round's PR comment. No collapse runs when:
   - a thread stays open;
   - the push step skipped the collapse;
   - approvals kept it from running;
   - the routine refused or aborted.

### Collapse step

Collapse only when both hold:
- every thread on this PR will be resolved after the replies (`collapse-with-open-threads`);
- `merge.message_source` is `commits`, which it is here.

Otherwise keep the fixup commit separate, so the reviewer can diff just the delta. The collapse is the round's closing push. It rewrites the pushed commits into one without changing the tree. When the push step pushed nothing, it is the round's only push. Collapse after the push step's push, never before it, or the collapse ships without the fix.

**1. Approvals.** Read approvals just before the collapse, after the push step's push.
1. Run `gh api repos/116-Labs/cuecal/pulls/<n>/reviews --paginate --slurp`.
2. For each reviewer, take the latest review that approves or requests changes. Count it when it is `APPROVED` and not `DISMISSED`. With this profile's facts, an approval of an earlier commit still counts.
3. If the count meets `required_approvals` (1), do not collapse. A push would dismiss those approvals for no content (`content-free-push-after-approval`).
   - Keep the commits as they are.
   - Report that the collapse was skipped to keep the approvals, and that whoever merges supplies the message.
4. When the push step pushed fixes, the approvals were usually dismissed already, and then the collapse goes ahead.

**2. Gates when the collapse is the only push.** If the push step pushed nothing, run `uv sync --locked` and every gate with timing on the head first (`gates-green-before-push`). A gate red there ends `needs-human` naming it, with nothing pushed.

**3. Run the shared routine in PR mode.** The mode is declared, never inferred.
1. **Regime.** `message_source` is `commits`. For a stacked PR, the eventual target is `main`.
2. **Target.** Run `git fetch origin <branch>`, then `git rev-parse origin/<branch>`. The result must equal the head you pushed or inspected. Keep it as `<remote-head>`. Run `git worktree add --detach <run-dir>/collapse <remote-head>`, then `cd <run-dir>/collapse`.
3. **Idempotence.** Run `git merge-base HEAD origin/<base>` to get `<merge-base>`, then `git rev-list --count <merge-base>..HEAD`. With 0 or 1 commits, succeed without doing anything. Always count and reset against the merge base, never against the base's tip. A reset to a base that moved on would make the new commit revert the base's newer changes while the tree hash still matches.
4. **Soft gates.**
   - Approval dismissal is decided by the approval count above.
   - Knowingly override the unresolved-threads gate, because the threads just fixed resolve after the push. Print the count and name the override in the report.
5. **Hard gates.** These are never overridden. Any one of them refuses the collapse.
   - `isCrossRepository` is true, so the branch lives on a fork.
   - A commit was authored by someone else. Compare `git log --format=%ae <merge-base>..HEAD` with the email in `git var GIT_AUTHOR_IDENT`, never with `git config user.email`.
   - The remote head fails `collapse-remote-contained`. Read the remote head again just before the rewrite with `git ls-remote origin refs/heads/<branch>`. It must equal `<remote-head>`, and `git merge-base --is-ancestor <remote-head> HEAD` must exit 0. Never compare the remote head with the collapsed commit.
6. **Divergent local checkouts.** In `<checkout>`, run `git rev-list --count origin/<branch>..<branch>` when a local `<branch>` exists.
   - If it has local-only commits, back them up with `git branch gaal-backup/<branch>-<short-sha> <branch>` and verify the backup with `git rev-parse`.
   - If that checkout has uncommitted edits of unknown origin on `<branch>`, stop the collapse for a human. This counts as a refusal.
7. **Rewrite.**
   1. Keep `<pre-collapse-head>` = `git rev-parse HEAD` and its tree from `git rev-parse HEAD^{tree}`.
   2. Run `git reset --soft <merge-base>`.
   3. Run `git diff --cached --quiet`. If it exits 0, the rewrite nets to an empty change: abort.
   4. Write one Conventional Commits message for the whole change to `<run-dir>/scratch/collapse-msg.txt`. Drop process messages such as "wip" and "fix lint". Carry the issue link from the settle step, `Closes #N`, or `Refs #N` on a line of its own with its **Deferred** list (`collapse-keeps-link`). Add no attribution.
   5. Run `git commit -F <run-dir>/scratch/collapse-msg.txt`.
8. **Content preservation** (`collapse-content-preserved`). Run `git rev-parse HEAD^{tree}`. If it differs from the pre-collapse tree, abort. To abort, run `git reset --hard <pre-collapse-head>`, push nothing and never commit again.
9. **Push.** Run `git push --force-with-lease=<branch>:<remote-head> origin HEAD:refs/heads/<branch>`.
   - A hook rejection is fixed and pushed again.
   - On any other failure, restore with `git reset --hard <pre-collapse-head>` and end as `push-failure-states` says.
   - On success, `<pushed-sha>` is the new head.
10. **Local checkouts.** If a local `<branch>` ref exists in `<checkout>` and is not checked out, run `git update-ref refs/heads/<branch> <pushed-sha>`. Otherwise report the reset that checkout needs: `git fetch origin`, then `git reset --hard origin/<branch>`. Never pull into a checkout after a collapse, because a pull merges the old history back in (`pull-after-collapse`).
11. **Report.** Report the mode (PR), the regime, the commit count before and after, each gate that fired or was overridden, the tree hash, old and new sha, backup refs in full, and the reset each stale checkout needs.
12. **Clean up.** Run `cd <run-dir>/worktree`, then `git worktree remove <run-dir>/collapse`, on every exit path.

A refusal by a hard gate, or an abort by the content gate, has restored the pre-collapse HEAD. Send the replies, none of which claims a collapse, and end `failed` naming the gate.

### Reply step

The reply step runs on every exit after items were decided, not only on `done`. The round may stop before or at its push: the round limit, a rebase conflict, a gate red on the rebased tree, an unreadable mergeability check, a refused or failed push, a hook fix beyond this run's remit, or a refused collapse. The run still posts the thread replies and the PR comment before the run result. In that case:
- a fix that was not pushed is reported as prepared, not pushed, with the reason, and its thread stays open;
- no reply names a sha the remote does not have;
- no reply claims the PR is ready.

**Filing follow-ups.** File each deferral's follow-up issue first, before its reply. Write its body to `<run-dir>/scratch/followup-<k>.md` with the defect, the reproduction, the files and a link to where it was found. Then run:

`gh issue create --repo 116-Labs/cuecal --title "<title>" --body-file <run-dir>/scratch/followup-<k>.md`

**Thread replies.** Reply to every unresolved thread, imports that did not apply included (`every-thread-answered`). Each reply describes exactly what was done (`reply-matches-action`):
- a fix names the sha on the remote that contains it, which is `<pushed-sha>` after a push or collapse;
- a deferral names the follow-up issue;
- an answer explains;
- a pushback gives the reasons.

Write each reply to `<run-dir>/scratch/reply-<k>.md`. Write `<run-dir>/scratch/reply.graphql`: an `addPullRequestReviewThreadReply` mutation with the variables `threadId` and `body`. Then run:

`gh api graphql -F query=@<run-dir>/scratch/reply.graphql -F threadId=<thread-id> -F body=@<run-dir>/scratch/reply-<k>.md`

**The PR comment.** Answer every `review-body`, `issue-request` and threadless `import` item in one PR comment (`body-requests-answered`, `issue-requests-answered`). Quote or link each request: an issue request by its comment link or by the edit's time. Give its decision: a sha, an issue number, or the reasons. Include the questions for ambiguous items. Say whether the issue link was left unchanged because no collapse ran. Write it to `<run-dir>/scratch/pr-comment.md`, then run:

`gh pr comment <n> --repo 116-Labs/cuecal --body-file <run-dir>/scratch/pr-comment.md`

### Resolve threads

Resolve by rule (`resolve-by-rule`). Resolve a thread only when one of these holds:
- it was fixed and the fix is on the remote;
- it is outdated;
- it was deferred with agreement recorded on the thread.

Since `threads_block_merge` is true, deferral and pushback have opposite outcomes. Never resolve a pushback (`resolve-pushback`). Never resolve a deferral only this run decided on (`resolve-unagreed-deferral`). Both stay open for the reviewer. `review-body` and `issue-request` items have nothing to resolve.

To resolve, write `<run-dir>/scratch/resolve.graphql`: a `resolveReviewThread` mutation with the variable `threadId`. Then run:

`gh api graphql -F query=@<run-dir>/scratch/resolve.graphql -F threadId=<thread-id>`

Resolving another PR's imported thread may fail on permissions. The reply is what matters, and that failure is no blocker. Note it in the report.

### Description step

Bring the PR description up to date with the final head, after the last push (`description-matches-head`). Test counts and behaviour claims go stale across rounds.

1. Read the description against the pushed tree and the round's outcome: the summary, the test plan, and any test count, gate result or behavioural claim the round changed.
2. Edit only what is now false or missing.
3. Keep the issue reference, updated only by the settle step. Keep any attribution section as it is. Do not rewrite untouched prose.
4. The link in the body must match the head commit's link. Write `Closes #N` with no **Deferred** list, or `Refs #N` with its list.
5. Write the body to `<run-dir>/scratch/pr-body.md`, then run `gh pr edit <n> --repo 116-Labs/cuecal --body-file <run-dir>/scratch/pr-body.md`.

Skip this step when the round changed no code and no claim in the description became false. Editing the description pushes nothing. Do it before review is requested again.

### Request review again

Request review again per the profile's review settings. The profile lists no fixed reviewers.
- For each human reviewer whose review this round answered, run `gh pr edit <n> --repo 116-Labs/cuecal --add-reviewer <login>`. Exclude reviewers whose approvals this round's push dismissed.
- When this round's push dismissed approvals, Gaal itself re-requests exactly those reviewers, once per push. Its comment quotes the run result's `push`. Post no notice of your own about the dismissal, and do not re-request those reviewers yourself.
- Do not request the review identity `116-labs-gaal-review[bot]`. Gaal starts its review by the profile's start signal.

### Clean up

On every exit path:
1. Run `cd <checkout>`.
2. Run `git worktree remove <run-dir>/worktree` for each worktree this run created. Do the same for `<run-dir>/collapse` and `<run-dir>/base`.
3. If a removal is refused, report the path. Never change the hook configuration.

### Run result

Write the run result last, on every exit path, failures included (`run-result-written`).

1. Run `date -u +%Y-%m-%dT%H:%M:%SZ` and keep the value as `finished_at`.
2. If the run pushed, build `push`:
   - `why`: one sentence on the fixes the push carried, or on what required the rebase.
   - `changes`: compare `git rev-parse <head-before-run>^{tree}` with the final head's tree. If they are equal, write `tree unchanged`. Otherwise write a short summary of `git range-diff <merge-base-before-run>..<head-before-run> <final-merge-base>..<final-head>`.
3. With the file tool, write `<run-dir>/result.json.tmp` with these fields:
   - `schema_version`: 1
   - `run_id`: the GAAL_RUN_ID value from the run context
   - `blueprint`: `"revise-pr"`
   - `blueprint_version`: `"1.8.0"`
   - `repo`: `"116-Labs/cuecal"`
   - `issue`: the issue picked above, or `null`
   - `pr`: `<n>`, or `null` when no PR was determined
   - `status`: `done`, `needs-human`, `needs-clarification` or `failed`
   - `reason`: one sentence of at most 160 characters naming the decision or action needed. Required unless `done`.
   - `questions`: required and non-empty for `needs-clarification`, quoting each request
   - `attempts`: the round counter, at least 1
   - `gates`: the gate runs on the final tree in the order they ran, each with `name`, `command`, `exit_code` and `duration_ms` (`gates-final-tree`). A gate that did not run is absent (`truthful-report`). A `done` result never lists a non-zero `exit_code`. A result that is not `done` lists the runs on the tree it stopped on, and may include the red run that stopped it.
   - `branch`: `<branch>`, or `null`
   - `commit_sha`: the full 40-character PR head after the run. That is the unchanged head when nothing was pushed, and `null` when it was never read.
   - `push`: only when the run pushed
   - `started_at` and `finished_at`

   Add no other fields.
4. Run `mv <run-dir>/result.json.tmp <run-dir>/result.json`. Never leave the `.tmp` file behind.
5. In the final message, give the report: one row per item (source, decision, sha or issue), open pushbacks, the collapse report or why it was skipped, linked numbers that named no issue, and pre-existing gate failures. Keep it truthful (`truthful-report`).

## Exit states

- `done`: Every thread, every actionable review-body request and every issue request since the PR opened is answered. The description matches the head. The branch is pushed with green gates. `commit_sha` is the PR head after the run. When nothing needed changing (no fix, no required rebase, no collapse), it is the unchanged head, nothing is pushed and `gates` may be empty. The report has one row per item. Open pushbacks are normal and listed. A collapse skipped to keep approvals is reported, not an error.
- `needs-clarification`: No PR could be determined. Or a request was so ambiguous that any fix would be a guess. It was asked on its thread or in the PR comment after every other item was handled as usual. `questions` quote it.
- `needs-human`: One of these happened, and `reason` names it:
  - the 3-round limit was reached with red gates;
  - a gate was red on the head before a collapse that was the round's only push (nothing pushed);
  - a merged stack parent's last head is not an ancestor of the branch (nothing pushed);
  - a rebase conflict or an unmergeable PR blocked the push;
  - the push was refused for permission;
  - a mergeability check was unreadable;
  - a gate was red on the tree rebased onto a fresh base (nothing pushed);
  - after the push, the PR became `CONFLICTING` or `DIRTY`.
- `failed`: One of these happened, and `reason` names the step:
  - the PR is not open;
  - `uv sync --locked` failed;
  - the push failed for another reason, such as a lease mismatch or a network error (HEAD restored);
  - a hook fix was beyond this run's remit;
  - the collapse routine refused or its content gate aborted;
  - a read failed or a listing was truncated.

  Gates already red on the base are reported as pre-existing.

On every exit after items were decided, the reply step's replies and PR comment were still posted. Fixes that were not pushed are reported as prepared, not pushed.

## Invariants

- `every-thread-answered`: Every thread unresolved at the start has a reply at the end, imports that did not apply included.
- `one-push-per-round`: The push step pushes at most once per round, after all fixes. The only other push is the collapse step's tree-preserving closing push. There is never a second push to chase a moved base.
- `gates-green-before-push`: Every required gate exited 0 on the tree that was pushed.
- `reply-matches-action`: Each reply describes what was done: a sha containing the fix, an issue number for a deferral, or reasons for a pushback.
- `resolve-by-rule`: A thread is resolved only if it was fixed, is outdated, or was deferred with agreement recorded on the thread.
- `target-branch-only`: Code changes land only on this PR's branch. A fix for an import names where it landed.
- `bounded-rounds`: Gate-fix rounds stop at `limits.revise_rounds` (3), ending `needs-human`.
- `body-requests-answered`: Every actionable request in a latest review body is acted on or answered in the PR comment.
- `issue-requests-answered`: Every actionable request made on the linked issue since the cut-off, by its author or a maintainer, is acted on or answered in the PR comment.
- `description-matches-head`: After the round, the description states nothing the pushed head contradicts, and its issue link matches the head commit's. It is edited before review is re-requested.
- `base-drift-checked`: The base and mergeability were read before and after the push. A rebase happens only when the PR is conflicting, `BEHIND` or stacked on a merged parent. It keeps the commits as they are, and the gates are re-run on the rebased tree.
- `push-explained`: A run that pushed records `push.why` and `push.changes`. A rebase compared tree identity before and after it.
- `explicit-staging`: Only manifest paths are staged, one by one. Nothing is staged wholesale.
- `base-untouched`: Never commit or push to `main` or to the PR's base.
- `fail-closed-reads`: A failed read stops the run. It is never treated as "nothing there".
- `complete-listings`: Every listing is paginated to the end, or the run ends `failed`.
- `truthful-report`: The report and run result describe what happened. A gate that did not run is absent.
- `status-preserved`: No exit status is lost to a pipe, filter or guard.
- `attribution-policy`: `attribution: none`. Commits and PR bodies carry no attribution, and nothing is added or dropped on the agent's own initiative.
- `run-result-written`: `result.json` is written atomically on every exit path.
- `gates-final-tree`: `gates` lists only the runs on the final tree, in order.
- `install-before-gates`: `uv sync --locked` runs before every set of gate runs, again after a rebase, and again after a dependency file changed.
- `push-failure-states`: A hook rejection is fixed and pushed again. Any other push failure is never retried. HEAD is restored, and the run ends `needs-human` for a permission refusal or `failed` otherwise.
- `collapse-remote-contained`: Before the collapse rewrite, the remote head equals the inspected sha and is an ancestor of the pre-collapse head.
- `collapse-content-preserved`: A collapse with an empty net change, or a changed tree hash, aborts and pushes nothing.
- `collapse-keeps-link`: The collapsed message carries the issue link and any **Deferred** list settled for this collapse.

## Forbidden actions

- `push-red`: Pushing a branch with a failing required gate to clear comments.
- `piecemeal-push`: Pushing once per comment instead of once per round.
- `resolve-pushback`: Resolving a thread where the revision disagreed with the reviewer.
- `resolve-unagreed-deferral`: Resolving a deferral that only this run decided on. A deferral with no issue number is a pushback in disguise.
- `apply-unreproduced-import`: Applying an imported finding that does not reproduce on this branch.
- `collapse-with-open-threads`: Collapsing while any thread on this PR will remain open.
- `pull-after-collapse`: Pulling into a checkout after a collapse. Hard-reset it to the remote instead.
- `content-free-push-after-approval`: Pushing a collapse, or a rebase the push step does not require, while the PR holds the 1 required approval that a push would dismiss.
- `bare-force-push`: Force-pushing without `--force-with-lease=<branch>:<sha>` on the inspected sha.
- `admin-bypass`: Merging, pushing or rewriting with admin privileges to get around branch protection or a hook.
- `bypass-hook`: Committing or pushing with verification skipped or redirected, changing where git looks for hooks, or retrying a rejected commit or push through another route.
- `machine-specific-paths`: Hard-coding a home directory, private scripts or services instead of reading them from the profile and the run context.
- `commit-foreign-edits`: Committing changes this run did not make.
