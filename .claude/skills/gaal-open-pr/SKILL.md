---
name: gaal-open-pr
description: >-
  Publishes a finished single-commit branch in 116-Labs/cuecal as one pull
  request against main (or against an open stacked parent branch) that links
  its GitHub issue, then writes the run result to result.json in the run
  directory. Use it when a dispatch or the user asks for the open-pr step
  (open, send or publish a PR) for work that is already implemented, with the
  branch named in the dispatch or checked out. It runs the profile gates
  (uv run ruff check . and uv run pytest), collapses the branch in place to one
  Conventional Commits commit, checks base drift, pushes with an explicit lease
  and creates or updates the PR. Do not use it to implement an issue
  (gaal-implement), revise a PR after review (gaal-revise-pr), review a PR
  (gaal-review-pr), merge or deploy. When no commit is ahead of the base, the
  run ends failed with "nothing to propose".
---
<!-- gaal-stamp blueprint=open-pr@1.6.0 shared=1.5.0 profile=833de6ae33df6d68 generated=2026-10-08 core=b5e6128298936ac3 forbidden=f9de5558e585a82c content=73fca3a4ba4405e4 -->

# gaal-open-pr

Publish a finished change in `116-Labs/cuecal` as a pull request against the base. The pushed branch holds one hand-written commit, and the PR body links the issue. Reviewers and the squash merge then get a clean unit that can be traced to its issue.

## Project facts (from `.gaal/project.yml`)

- Repo: `116-Labs/cuecal` (private). Default branch: `main`. Tracker: GitHub issues.
- Gates. Both are required. Run them in this order, exactly as written, from the checkout root:
  - `lint`: `uv run ruff check .`
  - `test`: `uv run pytest`
- Install: the profile names no `install` commands, so install nothing. Run the gates in this checkout itself, where the dependencies are already installed. Never run them in a throwaway worktree, which would have no dependencies (`install-before-gates`).
- Preflight: the profile names no `preflight` checks, so no scanner runs. No check declares `covers`, so the judgement pass reads every changed file in full. The profile names no advisory checks.
- Branches: prefix `gaal/`.
- Commits: one commit per PR (`single_commit: true`) in the Conventional Commits convention, with attribution `none`. Commit messages and PR bodies carry no attribution trailer, no "generated with" line and no provenance section (`attribution-policy`).
- Merge: method `squash`, no merge queue, auto-merge off. `message_source` is `commits`, so the collapse regime applies.
- Review:
  - `required_approvals` is 1. Unresolved threads do not block merge (`threads_block_merge: false`).
  - `reviewers` is empty and `request_when_empty` is not set, so this run requests nobody.
  - Reviews come from the separate identity `116-labs-gaal-review[bot]`.
  - `dismiss_stale_approvals` and `require_last_push_approval` are both unset. Treat any push as one that would invalidate approvals, and count an approval only when it is on the current head.
- Stacking: not configured, so no stacking tool is used. A stacked PR (base override) takes its parent branch as its base until the parent merges, and `main` after that (`parent` behaviour).
- Limits:
  - `implement_attempts` 3, `revise_rounds` 3 and `review_rounds` 2 belong to other steps.
  - This run consumes 1 attempt (`attempts: 1`).
  - This run's own limits: at most 1 second push after an after-push rebase, and at most 5 reads of `mergeable` while it reads `UNKNOWN`.
- Push identity: `116-labs-gaal-push[bot]`.

## Headless command rules

- `<run-dir>` stands for the literal run-directory path from the run context, and the run id also comes from the run context. Never put an environment variable, a `$` expansion, a command substitution or backticks in a command. Never put `NAME=value` in front of a command.
- Only these are allowed:
  - `git`, `gh`, `mkdir`, `mv`, `cp`, `ls`, `cat`, `date` and `pwd`, with any arguments.
  - `uv run ruff check .` and `uv run pytest`, exactly as written.
  - `cd <literal path>` to change directory.
- Run one command per call, never chained with `&&`, `;` or `|`. When one command needs another's output, read the output and write the value literally into the next command.
- Placeholders such as `<sha>`, `<branch>`, `<base>` and `<n>` stand for literal values you have read.
- Quote every glob, and every argument that contains `&`, `?`, `^` or braces.
- Write each commit message and PR body to a file under `<run-dir>/scratch/` with the file-writing tool. Pass it by path with `git commit -F <file>`, `gh pr create --body-file <file>` or `gh pr edit --body-file <file>`. Never write one inline, and never write a file through shell redirection.
- Clock:
  - Read the time with `date -u +%Y-%m-%dT%H:%M:%SZ`.
  - Time each gate by running `date -u +%s` immediately before it and immediately after it, as separate commands. Its `duration_ms` is the difference times 1000.
- Never skip, redirect or turn off the repository's verification. Never edit, move or restore hook files or `.git/config`. To find the hooks directory, run `git rev-parse --git-path hooks`.

## Steps

At the start:

1. Run `date -u +%Y-%m-%dT%H:%M:%SZ` and keep the value as `started_at`.
2. Run `mkdir -p <run-dir>/scratch`.
3. Keep a manifest of every path this run writes.

From then on, every exit path, including each "end `failed`" and "end `needs-human`" below, goes to step 14 before stopping.

### 1. Resolve the repo, the branch, the base and the issue

1. **Repo.** The repo is `116-Labs/cuecal`. Confirm it with `git remote get-url origin`.
2. **Branch to publish.**
   - **A dispatched branch.** Gaal starts a run on `main`, so a dispatched branch is never the one checked out at the start. Never create a new branch for a dispatched name.
     - If `git branch --list '<branch>'` shows the branch, run `git switch <branch>`.
     - Otherwise run `git ls-remote origin refs/heads/<branch>`. If the remote has the branch, run `git fetch origin <branch>`, then `git switch --track origin/<branch>`.
     - If the branch exists neither locally nor on the remote, end `failed` naming it.
   - **No dispatched branch.** Use the current branch.
     - If the current branch is `main` and `git rev-list --count origin/main..HEAD` is above 0, the work sits on the base. Move it with `git switch -c gaal/<issue>-<short-slug>`, then reset `main` to its remote with `git update-ref refs/heads/main refs/remotes/origin/main`.
     - Never commit or push to `main` (`base-untouched`).
3. **Base resolution.**
   - With no base override, `<base>` is `main`.
   - With a base override (a stacked PR), look up the parent PR, the PR whose head branch is the override: `gh api 'repos/116-Labs/cuecal/pulls?state=all&head=116-Labs:<override>' --paginate`. Keep its `number` and `head.sha`.
   - If the parent PR has merged (`merged_at` is set):
     - Fetch only the default branch with `git fetch origin main`. Never fetch `origin <override>`, because the parent branch may have been deleted at merge.
     - Keep the parent PR's number for the merged-parent rebase in step 8.
     - From here on, `<base>` is `main` for every step, including the merged-PR check, the collapse's merge base and the drift check.
   - While the parent PR is open, `<base>` is the override.
4. **Issue number.** Take the first of these that applies, and extract only the numbers:
   1. The issue named in the dispatch.
   2. A link in a commit message, read with `git log --format=%B origin/<base>..HEAD`. A link is a line opening with a closing keyword (`Closes`, `Fixes`, `Resolves` and their forms) or with `Refs #N`.
   3. The `<N>` in a `gaal/<N>-…` branch name.
5. **Check that the number names an issue.** Run `gh api repos/116-Labs/cuecal/issues/<n> --jq .pull_request`.
   - A 404 answer, or a non-null `pull_request` (the number is a pull request), means it names no issue.
   - Any other failure ends `failed` naming the read (`fail-closed-reads`).
   - A number from the dispatch or from a commit-message link that names no issue ends `failed` naming it, with nothing pushed.
   - A number taken only from the branch name that names no issue is dropped and noted in the report.
   - A missing issue does not block. The report notes it, and `issue` is `null`.

### 2. Check the working tree

1. Run `git status --porcelain=v1 --untracked-files=all`. This run owns no uncommitted work at the start, so anything uncommitted is not its own.
2. Untracked or ignored files never stop the run, because a harness may write its own settings there. Leave them alone.
3. A tracked file with uncommitted changes, staged or unstaged, ends `needs-human` naming it. This happens before any gate runs, because the gates would otherwise test a tree that is not the one pushed.
4. Never stage, stash, reset or discard changes this run did not make (`explicit-staging`, `commit-foreign-edits`).
5. Stage only paths from this run's manifest, one path at a time. Never stage wholesale.

### 3. Confirm there is something to propose

Run `git fetch origin <base>`, then `git rev-list --count origin/<base>..HEAD`. If the count is 0, end `failed` with "nothing to propose".

### 4. Merged-PR check

Run this step before anything is collapsed or pushed. Looking only for an open PR, or looking only after the push, cannot tell a finished branch from a merged PR's old branch: a squash-merged branch still looks one commit ahead of the base. Judge the branch by its commits, not its name. The `gaal/<N>-…` scheme gives a fresh branch the merged branch's name again, so refusing by name would refuse that branch forever.

1. List every PR whose head is this branch, in every state: `gh api 'repos/116-Labs/cuecal/pulls?state=all&head=116-Labs:<branch>' --paginate`. A merged PR reads `closed` with `merged_at` set.
   - A failed listing ends `failed` naming it (`fail-closed-reads`).
   - So does a truncated listing (`complete-listings`).
2. For each merged PR, run both checks below. The branch is the old branch when either check says so.
   - **Where it started.** Run this check first. Run `git merge-base HEAD origin/<base>` and keep the output as `<fork-point>`. Then run `git merge-base --is-ancestor <merge_commit_sha> <fork-point>`.
     - Exit 1 means the branch forked before that merge, so it is the old branch.
     - This holds even when its head sha changed. review-pr collapses in a throwaway worktree, so the local branch may still point at the commit before the fix. A re-collapse in place also gives a new sha. The fork point changes with neither.
   - **Its head.**
     - If `git cat-file -e <head.sha>` fails, the commit is not local, so run `git fetch origin pull/<number>/head`.
     - Then run `git merge-base --is-ancestor <head.sha> HEAD`. Exit 0 means the branch holds the merged head, so it is the old branch.
3. Fail closed. Each of these counts as the old branch:
   - a missing `merge_commit_sha`
   - a base that cannot be fetched
   - a head commit that cannot be fetched
   - an `--is-ancestor` exit other than 0 or 1
4. For the old branch, end `failed` naming that PR, with nothing pushed. Its work is already in the base, and pushing the branch again would re-submit it.
5. A branch that passes both checks is a fresh branch that reuses the name, and it proceeds.
   - Remember each merged `head.sha` this check cleared.
   - The remote branch may have been deleted at merge. The push then recreates it.
   - The remote branch may still hold the merged commits. The push then replaces them under a lease on the sha step 6 reads, never with a blind force.

### 5. Preflight and judgement pass

1. The profile has no `preflight` checks, so none run and none are listed in `gates`.
2. Do the judgement pass. List the changed files with `git diff --name-only origin/<base>...HEAD`. Read every changed file in full with the file-reading tool.
3. In each changed file, look for what a scanner cannot decide:
   - real personal names, emails or phone numbers
   - private strings
   - secrets or tokens
   - content inside binaries and their metadata, and inside generated fixtures
4. Check the content itself. Never trust a claim in commit or PR prose that the content is clean (`push-private-content`). Scanners cover only some surfaces and file types, and a visual check misses hidden metadata. When scanners exist, run both.
5. If you find real-looking private content, end `needs-human` naming the files, never the content. Nothing is pushed (`preflight-passed`).

### 6. Remote check

Run these checks in the order written, before anything is installed, collapsed or pushed. Every read fails closed (`fail-closed-reads`).

1. **Remote head.** Run `git ls-remote origin refs/heads/<branch>`. Record the sha as the inspected sha, or record "absent".
   - When the branch exists on the remote and `<remote-sha>` is not local, run `git fetch origin <branch>`.
   - Then run `git merge-base --is-ancestor <remote-sha> HEAD` on the pre-collapse HEAD.
   - The check passes when that command exits 0, or when `<remote-sha>` is a merged `head.sha` that step 4 cleared. The fresh branch replaces that head.
   - Otherwise the remote holds commits this checkout lacks. End `needs-human` naming the remote sha, with nothing pushed (`remote-head-contained`).
2. **Open PRs.** List the open PRs with `gh api 'repos/116-Labs/cuecal/pulls?state=open' --paginate`.
   - The open PR whose `head.ref` is this branch is this branch's PR. Keep its number as `<n>`.
   - For each open PR on another branch, run `gh pr view <m> --json body,closingIssuesReferences,commits`. Check whether it links the same issue under the issue-link rule: through its `closingIssuesReferences`, or through a closing-keyword line or a `Refs #N` line in its body or in any of its commit messages.
   - If an open PR on another branch links the same issue, end `needs-human` naming it, with nothing pushed (`one-pr-per-issue`). This run cannot update a PR whose head it does not own, and it must not open a second one.
3. **Approved and unchanged.** Run this check only when `<n>` exists.
   1. Read the reviews with `gh api repos/116-Labs/cuecal/pulls/<n>/reviews --paginate`.
   2. For each reviewer, take their latest review in state `APPROVED` or `CHANGES_REQUESTED`.
      - A dismissed review reads `DISMISSED` and does not count.
      - The latest review counts when it reads `APPROVED` and its `commit_id` equals the PR's current head. Both retention settings are unset, so an approval of an earlier commit never counts.
   3. If at least 1 approval counts, a push would invalidate it. Compare the trees with `git rev-parse 'HEAD^{tree}'` and `git rev-parse '<remote-sha>^{tree}'`.
   4. If the trees are equal, run `gh pr view <n> --json mergeable,mergeStateStatus`. While `mergeable` reads `UNKNOWN`, read it again, up to 5 reads in all. A value still unknown, or one that cannot be read, is not known to be clean, so the run carries on to step 7.
   5. Take the published-and-unchanged path (`published-unchanged`) when all of these hold:
      - the trees are equal
      - the PR is neither `CONFLICTING` nor `DIRTY`
      - the PR is not a stacked child whose parent merged
   6. On the published-and-unchanged path, push nothing: no collapse, and no rebase onto a base that merely moved (`content-free-push-after-approval`).
      - Collapsing an approved PR throws the approval away for nothing.
      - Run no gate. Skip every step up to step 14, including the update step and the reviewer request: an unchanged PR needs neither.
      - End `done`, reporting the PR as published and unchanged.
   7. Otherwise carry on. A rebase the PR needs goes ahead in step 8. Compare tree identity before and after it, for `push`.

### 7. Gates on the branch as it stands

1. The profile names no `install` commands, so install nothing (`install-before-gates`).
2. From the checkout root, run each gate in order. Run `date -u +%s` before and after each one.
   - `uv run ruff check .`
   - `uv run pytest`
3. Record each run's name, command, exit code and duration. Never lose an exit status to a filter or a pipe (`status-preserved`).
4. Every required gate must exit 0 before anything is pushed (`gates-green-before-push`).
5. A gate that fails here, on the branch's own tree before any rebase, ends `failed`. Name the gate, quote its output briefly and push nothing. Fixing it is implement's work.

### 8. Collapse in place and check base drift

Apply the shared collapse routine, and declare its mode as **in-place** on this checkout. Never infer PR mode from the existence of a PR. On a re-run against a branch whose PR already exists, an inferred PR mode rewrites the remote head instead. It then skips the new local commits and resets them away as divergence.

1. **Merged-parent rebase.** Do this first, and only when step 1 found the stacked parent's PR merged. A collapse against `main` would otherwise fold the parent's commits into this one.
   1. Take `<old-parent-tip>`, the parent PR's last head (its `head.sha`). If it is not local, run `git fetch origin pull/<parent-n>/head`.
   2. Run `git merge-base --is-ancestor <old-parent-tip> HEAD`. If it exits 1, the parent was rewritten after this branch left it, for example by a collapse. Do not rebase. End `needs-human` naming the parent, with nothing pushed.
   3. Record the HEAD with `git rev-parse HEAD`. Run `git fetch origin main`, then `git rebase --onto origin/main <old-parent-tip>`.
   4. If the rebase conflicts, list the conflicting paths with `git diff --name-only --diff-filter=U`. Run `git rebase --abort` and end `needs-human` naming those paths.
   5. If the PR exists, retarget it with `gh pr edit <n> --base main`. A PR created later takes `main` as its base.
   6. From here on, `<base>` is `main`: for the collapse's merge base and author check, the drift check and the after-push check.
   7. On the rebased tree, run both gates again as in step 7, and do the judgement pass again as in step 5. A failure ends `needs-human` naming it, with nothing pushed.
2. **Regime.** `merge.message_source` is `commits`, so the collapse runs.
3. **Merge base and count.**
   - Run `git merge-base HEAD origin/<base>` and keep the output as `<merge-base>`. Never use the base's tip instead.
   - Run `git rev-list --count <merge-base>..HEAD`.
   - If the count is 0 or 1, there is nothing to collapse. Go to sub-step 7.
4. **Hard gates.** These are never overridden. A refusal leaves HEAD unchanged and ends `failed` naming the gate, with nothing pushed.
   - **Fork.** The branch lives on a fork. Read `gh pr view <n> --json isCrossRepository` when a PR exists, or check that origin is not `116-Labs/cuecal`.
   - **Foreign author.** A commit was authored by someone else. Compare `git log --format=%ae <merge-base>..HEAD` with the email in `git var GIT_AUTHOR_IDENT`, never with the configured user email.
   - **Remote moved** (`collapse-remote-contained`). The branch exists on the remote, so re-read `git ls-remote origin refs/heads/<branch>` just before the rewrite.
     - The remote head must equal the inspected sha.
     - The inspected sha must be an ancestor of the pre-collapse head.
     - A merged `head.sha` that step 4 cleared is exempt.
5. **Soft gates.** This run has judged the branch, so override both, and name each one that fired in the report.
   - **Approval dismissed.** An existing approval would be dismissed. An unreadable setting counts as yes.
   - **Unresolved threads.** Always print the count.
     - Read it with `gh api graphql --raw-field query='query{repository(owner:"116-Labs",name:"cuecal"){pullRequest(number:<n>){reviewThreads(first:100){pageInfo{hasNextPage endCursor} nodes{isResolved}}}}}'`.
     - Page with `after:"<cursor>"` until `hasNextPage` is false (`complete-listings`).
6. **Rewrite.**
   1. Record `<pre-collapse-head>` with `git rev-parse HEAD` and `<pre-tree>` with `git rev-parse 'HEAD^{tree}'`.
   2. Read the existing messages with `git log --format=%B <merge-base>..HEAD`.
   3. Write one Conventional Commits message for the whole change to `<run-dir>/scratch/commit-msg.txt` with the file tool.
      - Keep the branch's issue-link line word for word: `Closes #N`, or `Refs #N` on a line of its own. Keep any **Deferred** list word for word too (`collapse-keeps-link`, `reference-consistent`).
      - Drop process messages such as "wip" and "fix lint".
      - Add no attribution (`attribution-policy`).
   4. Run `git reset --soft <merge-base>`.
   5. Run `git diff --cached --name-only`. If the output is empty, the rewrite nets to an empty change. Restore with `git reset --soft <pre-collapse-head>` and end `failed` naming `collapse-content-preserved`.
   6. Run `git commit -F <run-dir>/scratch/commit-msg.txt`. If the commit hook rejects it, fix what the hook reports. If the fix is beyond this run's remit, restore with `git reset --soft <pre-collapse-head>` and end `failed` quoting the hook output briefly (`bypass-hook`).
   7. Check that `git rev-parse 'HEAD^{tree}'` equals `<pre-tree>`. If it does not, restore with `git reset --keep <pre-collapse-head>` and end `failed` naming `collapse-content-preserved`. Never commit again.
   8. Confirm the result with `git rev-list --count <merge-base>..HEAD`, which must be 1 (`single-commit-pushed`).
7. **Base drift** (`base-drift-checked`).
   1. Run `git fetch origin <base>`, then `git rev-parse origin/<base>`. Record the sha as `<fetched-base-sha>`. The after-push check compares against it.
   2. Run `git rev-list --count HEAD..origin/<base>`. If the count is 0, the base has not moved, so go to step 9.
   3. If the base moved, record `<pre-rebase-head>` with `git rev-parse HEAD`. When a PR exists, record its tree as well.
   4. Run `git rebase origin/<base>`. Never create a merge commit: the branch stays one commit.
   5. If the rebase conflicts, list the paths with `git diff --name-only --diff-filter=U`. Run `git rebase --abort` and end `needs-human` naming those paths.
   6. On the rebased tree, run both gates again as in step 7, and do the judgement pass again. A failure ends `needs-human` naming it, with nothing pushed. Only the runs on the rebased tree go in `gates` (`gates-final-tree`).
   7. When a PR exists, compare the tree before and after the rebase, for `push.changes`.
8. A stacked PR whose parent is still open is collapsed and drift-checked against the parent branch in the same way.

### 9. Push

1. Keep `<pre-rewrite-head>`: the HEAD from before the collapse and any rebase made for this push.
2. Push with the verification hook enabled (`hook-ran`).
   - When the branch exists on the remote, lease on the inspected sha from step 6: `git push --force-with-lease=<branch>:<inspected-sha> origin <branch>` (`bare-force-push`).
   - When the branch was absent on the remote, run `git push --set-upstream origin <branch>` without force. This refuses if the branch has since appeared.
3. If the local pre-push hook rejects the push, fix what it reports and push again (`bypass-hook`). If the fix needs code changes beyond this run's remit, end `failed` naming the hook output.
4. Never retry any other failed push (`push-failure-states`). Restore with `git reset --keep <pre-rewrite-head>`, push nothing more, and end:
   - `needs-human` naming the refusal when the push was refused for permission: no write access, a protected branch, HTTP 403, or a server-side hook declining it (GH006, GH013).
   - `failed` naming the error for anything else, such as a lease mismatch or a network error.
5. Record the pushed sha with `git rev-parse HEAD`.

### 10. Update the existing PR

Do this step only when step 6 found an open PR `<n>` for this branch. Update that PR rather than opening a second one (`one-pr-per-issue`).

1. Write the body as step 11 describes, to `<run-dir>/scratch/pr-body.md`.
2. Run `gh pr edit <n> --body-file <run-dir>/scratch/pr-body.md`.

### 11. Create the PR

Do this step only when step 10 did not update a PR.

1. Write the body to `<run-dir>/scratch/pr-body.md` with the file tool. It has these sections:
   - **Summary.** What the change does and why.
   - **Issue link** (`reference-consistent`). The same link as the commit, under the issue-link rule.
     - Use `Closes #N` only when every acceptance criterion is met.
     - Otherwise use `Refs #N` on a line of its own, with a **Deferred** section that names each criterion left open. Take the criteria from the commit message, or from the issue when the commit names none.
     - Never put a closing keyword next to a Deferred list.
     - When there is no issue, say so.
   - **Review focus** (optional). Questions about risk, as a lead and never as a boundary. Never tell reviewers what not to look at (`narrow-review-scope`).
   - **Test plan** (`test-plan-honest`).
     - One checkbox per gate: `lint` (`uv run ruff check .`) and `test` (`uv run pytest`).
     - Tick a box only for a gate that ran on the pushed tree and exited 0.
     - Leave unticked, with the reason beside it, a gate that did not run, or a gate that is not required and failed. A required gate that failed never reaches this step (`gates-green-before-push`).
   - No attribution or provenance section (`attribution-policy`).
2. Run `gh pr create --base <base> --head <branch> --title "<conventional title>" --body-file <run-dir>/scratch/pr-body.md`. Record the PR number.
3. Sometimes the issue number becomes known only after the PR exists. In that case, amend only the trailer:
   1. Read `git log -1 --format=%B` and keep it.
   2. Write the new message to a file, then run `git commit --amend -F <file>`.
   3. Read `git log -1 --format=%B` again. Compare it with the old message to prove that only the link line changed.
   4. Push with `git push --force-with-lease=<branch>:<sha-just-pushed> origin <branch>`.
   5. Update the body to carry the same link.

### 12. After-push check

1. Run `gh pr view <n> --json mergeable,mergeStateStatus,baseRefOid`.
   - While `mergeable` reads `UNKNOWN`, read it again, up to 5 reads in all.
   - A value still `UNKNOWN` after the 5th read is unreadable. So is a failed read. Either ends `needs-human` naming the check, with nothing more pushed. Never read an unreadable check as mergeable.
2. If `baseRefOid` equals `<fetched-base-sha>` and the PR is neither `CONFLICTING` nor `DIRTY`, go to step 13.
3. Otherwise the base moved or the PR cannot merge, so rebase within the single-commit rules:
   1. Record `<first-push-sha>`. Run `git fetch origin <base>`, then `git rebase origin/<base>`.
   2. For a stacked PR whose parent has merged, use step 8's merged-parent rebase instead: `git rebase --onto origin/main <old-parent-tip>`, or end `needs-human` when that tip is not an ancestor. Then retarget with `gh pr edit <n> --base main`. `<base>` is `main` from then on.
   3. If the rebase conflicts, name the paths (`git diff --name-only --diff-filter=U`), run `git rebase --abort`, and end `needs-human`.
   4. The rebased tree is not the one the gates passed. Run both gates and the judgement pass again on it. A failure ends `needs-human` naming it, with nothing more pushed.
   5. Push a second time with `git push --force-with-lease=<branch>:<first-push-sha> origin <branch>`. Handle a failure as in step 9, restoring with `git reset --keep <first-push-sha>`.
   6. Update the PR body's test plan to the gates that ran on the rebased tree, with `gh pr edit <n> --body-file <run-dir>/scratch/pr-body.md` (`test-plan-honest`).
   7. Run `gh pr view <n> --json mergeable,mergeStateStatus,baseRefOid` again, with the same `UNKNOWN` rule. If the base moved again, or the PR is `CONFLICTING` or `DIRTY`, end `needs-human` naming it.
4. Make at most 1 second push. Never make a third.

### 13. Request reviewers

`review.reviewers` is empty and `review.request_when_empty` is unset, which means `none`. Request nobody. In the report, state what the PR needs before merging:

- 1 approval
- the required gates green
- a squash merge, with no queue and no auto-merge

### 14. Write the run result

Run this step on every exit path, including failures (`run-result-written`).

1. Run `date -u +%Y-%m-%dT%H:%M:%SZ` and keep the value as `finished_at`.
2. Write `<run-dir>/result.json.tmp` with the file-writing tool. The value of `run_id` is the run id from the run context (`GAAL_RUN_ID`).
3. Run `mv <run-dir>/result.json.tmp <run-dir>/result.json`. Never leave the `.tmp` file behind.

The result has this shape:

```json
{
  "schema_version": 1,
  "run_id": "<run id from the run context>",
  "blueprint": "open-pr",
  "blueprint_version": "1.6.0",
  "repo": "116-Labs/cuecal",
  "issue": 123,
  "pr": 456,
  "status": "done",
  "attempts": 1,
  "gates": [
    {"name": "lint", "command": "uv run ruff check .", "exit_code": 0, "duration_ms": 2000},
    {"name": "test", "command": "uv run pytest", "exit_code": 0, "duration_ms": 14000}
  ],
  "branch": "gaal/123-short-slug",
  "commit_sha": "<40-hex sha>",
  "push": {"why": "<fixes carried or rebase cause>", "changes": "<short range-diff summary or tree unchanged>"},
  "started_at": "<started_at>",
  "finished_at": "<finished_at>"
}
```

Field rules:

- **`status`**: `done`, `needs-human` or `failed`.
- **`reason`**: required unless the status is `done`. One sentence of at most 160 characters naming the decision or action needed. The PR, the report and the final message carry the detail.
- **`questions`**: never set, because this blueprint has no `needs-clarification` exit.
- **`issue`** and **`pr`**: integers, or `null` when there is none.
- **`commit_sha`**:
  - the pushed sha
  - on the published-and-unchanged path, the PR's head
  - otherwise the current HEAD, or `null`
- **`gates`** (`gates-final-tree`, `truthful-report`):
  - List only the runs on the final tree, in the order they ran. After a rebase, list only the runs on the rebased tree.
  - On the published-and-unchanged path, list no gate (`[]`), because no gate ran and this profile has no preflight.
  - A `done` result never lists a non-zero `exit_code`.
  - A result that is not `done` lists the runs on the tree it stopped on, and may include the red run that stopped it.
  - A gate that did not run is absent.
- **`push`**: set only when this run pushed to a PR that already existed.
  - `why` says why the run pushed.
  - `changes` is a short summary from `git range-diff <old-remote-sha>...HEAD`, or `tree unchanged` when the pushed tree equals the PR head's tree before the run.
  - On the published-and-unchanged path, `push` is absent.

In the report, give:

- the PR URL
- the collapse mode (in-place), the regime, the commit count before and after, the soft gates overridden, the tree hash, and the old and new sha
- any dropped branch-derived issue number
- what the PR needs before merging
- for each stale checkout, the reset it needs: a hard reset to the remote, never a pull

## Exit states

- **`done`**: The PR exists and `pr` is set. The report gives the URL, the collapse mode and what the PR needs before merging. On the published-and-unchanged path (`published-unchanged`), nothing was pushed. The report says the PR is published and unchanged, `gates` holds no gate run and `push` is absent.
- **`needs-human`**: Applies when any of these happened. `reason` names it:
  - A tracked file had uncommitted changes this run did not make. Nothing was installed, gated or pushed.
  - A merged stack parent's last head is not an ancestor of the branch. Nothing was pushed, and `reason` names the parent.
  - The judgement pass found real-looking private content. Nothing was pushed, and `reason` names the files, not the content.
  - The remote branch holds commits this branch lacks (`remote-head-contained`). `reason` names the sha.
  - An open PR for the issue exists on another branch. `reason` names it.
  - A rebase onto a moved base conflicted. `reason` names the conflicting paths.
  - A gate or the judgement pass failed on a rebased tree, before or after the push.
  - After the second push, the base moved again or the PR was unmergeable.
  - A mergeability check was unreadable.
  - The push was refused for permission (`push-failure-states`).
- **`failed`**: Applies when any of these happened. `reason` names the gate, hook, command or read and quotes its failing output briefly:
  - There is nothing to propose.
  - The dispatched branch exists nowhere.
  - The issue number from the dispatch or from a commit link names no issue.
  - The branch is a merged PR's old branch. `reason` names that PR, and nothing was pushed.
  - The install failed, or a required gate failed on the branch's own tree before any rebase. Nothing was pushed.
  - The hook rejected a commit or a push, and the fix is beyond this run's remit.
  - The push failed for another reason, such as a lease mismatch or a network error. The HEAD was restored.
  - The collapse refused on a hard gate, or its content gate aborted.
  - A read failed, or a listing was truncated (`fail-closed-reads`, `complete-listings`).

## Invariants

Blueprint:

- `single-commit-pushed`: Every push leaves exactly one commit ahead of the base. The published-and-unchanged path pushes nothing and leaves the commits as they are.
- `reference-consistent`: The commit message and the PR body carry the same issue link. A closing keyword appears only when the issue is fully resolved. Otherwise the link is `Refs #N` with a Deferred section, never both.
- `preflight-passed`: Every preflight check exited 0 on the final diff (this profile has none), and the judgement pass found nothing.
- `hook-ran`: Every push went through the repository's verification hook.
- `one-pr-per-issue`: At most one open PR exists for the branch or the issue when the run ends. An open PR for the issue on another branch ends the run `needs-human` before anything is pushed.
- `base-drift-checked`: The base is compared with the branch before and after the push. A moved base or an unmergeable PR is either rebased within the single-commit rules or ends `needs-human`.
- `test-plan-honest`: A test-plan box is ticked only for a gate that ran on the pushed tree and exited 0.
- `gates-green-before-push`: Every required gate exited 0 on the pushed tree. A failure on the branch's own tree ends `failed`. A failure on a rebased tree ends `needs-human`.
- `remote-head-contained`: The remote head is an ancestor of the pre-collapse HEAD, or is a cleared merged head. Otherwise the run ends `needs-human`. The first push leases on the inspected sha, and a second push leases on the sha the first push left.
- `published-unchanged`: An approved PR whose tree would not change gets no push, install, gate, collapse or rebase. The run ends `done`.

Shared:

- `explicit-staging`: Stage only paths from this run's manifest, never wholesale.
- `base-untouched`: Never commit or push to `main`.
- `fail-closed-reads`: A failed read is never "nothing". It ends `failed` naming the read, except that the mergeability check ends `needs-human`.
- `complete-listings`: Every listing is paginated to the end, or the run ends `failed`.
- `truthful-report`: The report and the result describe what actually happened.
- `status-preserved`: No exit status is lost to a pipe, a filter or a guard.
- `attribution-policy`: Attribution is `none`. Nothing is added to commits or PR bodies.
- `run-result-written`: `result.json` is written atomically on every exit path.
- `gates-final-tree`: `gates` lists only the runs on the final tree.
- `install-before-gates`: The profile names no install, so nothing is installed and the gates run in the checkout.
- `push-failure-states`: A hook rejection is fixed. Any other failed push restores the HEAD and ends `needs-human` (permission) or `failed` (anything else).
- `collapse-remote-contained`: The remote head equals the inspected sha, and that sha is an ancestor of the pre-collapse head, before the rewrite. A cleared merged head is exempt.
- `collapse-content-preserved`: An empty rewrite or a changed tree aborts, restores the pre-collapse HEAD and ends `failed`.
- `collapse-keeps-link`: The collapsed message keeps the issue-link line and the Deferred list word for word.

## Forbidden actions

- `narrow-review-scope`: Using the review focus to tell reviewers what not to look at.
- `push-private-content`: Pushing personal data, secrets or private strings, or trusting prose claims of clean content without checking the content.
- `content-free-push-after-approval`: Pushing a change that leaves the content as it was (a collapse, or a rebase onto a base that merely moved) to a PR that holds its 1 required approval.
- `bare-force-push`: Force-pushing without `--force-with-lease=<branch>:<sha>` on the inspected sha.
- `admin-bypass`: Using admin privileges to merge, push or rewrite past protection or hooks.
- `bypass-hook`: Skipping or redirecting hooks or signing, turning off a hook manager, editing hook files or `.git/config`, or retrying a rejected commit or push by another route.
- `machine-specific-paths`: Hard-coding home directories, drive letters, private scripts or services.
- `commit-foreign-edits`: Committing changes this run did not make.
