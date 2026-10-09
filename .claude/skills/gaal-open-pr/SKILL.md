---
name: gaal-open-pr
description: Publishes a finished branch in 116-Labs/cuecal as one pull request against `main`, or against an open stacked parent branch. The pull request links the branch's GitHub issue. Before pushing, the skill checks that the branch is not the old branch of a merged PR and checks the remote side. It runs `uv sync --locked`, then the profile gates (`uv run ruff check .` and `uv run pytest`). It collapses the branch in place to one Conventional Commits commit with no attribution, checks base drift and pushes with an explicit lease through the repository's verification hook. It then creates or updates the PR and writes the run result to `result.json` in the run directory. Use it when a dispatch or the user asks for the open-pr step ("open a pull request for branch `<branch>`", "open / send / publish a PR") for work that is already implemented, with the branch named in the dispatch or checked out. Do not use it to implement an issue (`gaal-implement`), revise a PR after review (`gaal-revise-pr`), review a PR (`gaal-review-pr`), merge, publish or deploy. When no commit is ahead of the base, the run ends `failed` with "nothing to propose".
---
<!-- gaal-stamp blueprint=open-pr@1.6.0 shared=1.5.0 profile=6f85855df888e336 generated=2026-10-09 core=b5e6128298936ac3 forbidden=f9de5558e585a82c content=8c09784585d4ef9c -->

# gaal-open-pr

Publish a finished change as a pull request. The pushed branch holds one hand-written commit, and the PR body carries the same issue link as that commit. Reviewers and the merge path then get a clean unit they can trace.

## Run context and command conventions

- `<run-dir>` in every command below stands for the literal run directory path from the run context (the value of `GAAL_RUN_DIR`). Write it out literally. Never type `$GAAL_RUN_DIR`, `$GAAL_RUN_ID` or any other `$` variable, `$(…)` or backticks in a command. Take the run id from the run context too.
- Other `<placeholder>`s (`<branch>`, `<base>`, `<sha>`, `<n>`, …) stand for literal values you read earlier in the run. Substitute them before running anything.
- Only these commands may run: `git`, `gh`, `mkdir`, `mv`, `cp`, `ls`, `cat`, `date`, `pwd` (any arguments), plus exactly `uv sync --locked`, `uv run ruff check .` and `uv run pytest`, with nothing added. Run one command per call. Never chain with `&&`, `;` or `|`, and never put `NAME=value` in front of a command.
- Quote every URL or argument that contains `?`, `&` or a glob, for example `'gaal/<n>-*'`.
- Scratch files go in `<run-dir>/scratch`. Create it first with `mkdir -p <run-dir>/scratch`. Write files only with the file-writing tool, never through shell redirection.
- Every commit message and PR body is written to a file and passed by its path: `git commit -F <file>`, `gh pr create --body-file <file>`, `gh pr edit --body-file <file>`.
- Read timestamps with `date -u +%Y-%m-%dT%H:%M:%SZ`. Time each gate with `date -u +%s` run on its own just before the gate and again just after it. `duration_ms` is the difference times 1000.
- Record `started_at` with `date -u +%Y-%m-%dT%H:%M:%SZ` before doing anything else.
- Keep a manifest of the paths this run writes inside the checkout (`explicit-staging`). open-pr normally writes none. The run directory is never staged.

## Project facts (from `.gaal/project.yml`)

- Repo: `116-Labs/cuecal` (public). Default branch: `main`. Tracker: GitHub issues.
- Install: `uv sync --locked`, run before the gates every time (`install-before-gates`).
- Gates, all required, in this order:
  - `lint`: `uv run ruff check .`
  - `test`: `uv run pytest`
- Preflight: none configured (`preflight: []`). No scanner runs, so no preflight entries go into `gates`. The judgement pass covers every changed file.
- Commits: single commit, Conventional Commits (`type(scope): subject`), attribution `none`. No `Co-Authored-By` or other trailer, no provenance section and no AI attribution in commits or the PR body (`attribution-policy`).
- Branch prefix: `gaal/`.
- Merge: squash, `message_source: commits`, so the collapse regime is active. No merge queue. Auto-merge is on.
- Review:
  - `required_approvals: 1`, `dismiss_stale_approvals: true`, `require_last_push_approval: false`.
  - `code_owner_reviews: true`, `threads_block_merge: true`.
  - Required checks: `test`, `zizmor`.
  - `reviewers: []`, `request_when_empty` absent, so the run requests no reviewer.
  - Reviews come from the separate identity `116-labs-gaal-review[bot]`. The push identity is `116-labs-gaal-push[bot]`.
- Stacking: no tool, `stacking.base` absent. A stacked PR targets its parent branch until the parent merges, then `main`.
- Attempt limits (for context; this run makes one attempt and records `attempts: 1`):
  - `implement_attempts: 3`
  - `revise_rounds: 3`
  - `review_rounds: 2`
  - open-pr's own limit: at most **one** second push after the after-push check.

## Steps

### 1. Resolve repo, branch, base and issue

1. Confirm the repo with `git remote get-url origin`. It must name `116-Labs/cuecal`.
2. **Branch to publish.**
   - **Dispatch names `<branch>`:**
     - Run `git switch <branch>`.
     - If it does not exist locally, run `git ls-remote origin refs/heads/<branch>`. If that lists it, run `git fetch origin <branch>`, then `git switch -c <branch> --track origin/<branch>`.
     - If it exists nowhere, end `failed` naming the branch.
     - Never create a new branch for a dispatched name.
     - If `git switch` refuses because of local changes, those are foreign edits: end `needs-human` naming the files (see step 2).
   - **No dispatched branch:** use the current branch (`git branch --show-current`).
     - If that is `main` and it has commits ahead of `origin/main` (`git fetch origin main`, then `git rev-list --count origin/main..HEAD`), move the work. Run `git switch -c gaal/<n>-<short-slug>` (use `gaal/<short-slug>` when no issue is known), then `git branch -f main origin/main`.
     - Never commit or push to `main` (`base-untouched`).
3. **Base resolution.** `<base>` is `main` unless the dispatch gives a base override (a stacked PR).
   - For an override, look up the parent PR first:
     `gh api --paginate 'repos/116-Labs/cuecal/pulls?state=all&head=116-Labs:<override>'`
   - **Parent merged** (`merged_at` set):
     - Run only `git fetch origin main`, never `git fetch origin <override>`: the parent branch may have been deleted at merge.
     - Keep the parent PR's number and its last head (`head.sha`, the `<old-parent-tip>`) for the merged-parent rebase in step 8.
     - From here on `<base>` is `main` for every step: the merged-PR check, the collapse's merge base and author check, the drift check and the after-push check.
   - **Parent open:** `<base>` is the override branch.
4. **Issue number.** Take it from the dispatch first. Otherwise read the branch name (`gaal/<n>-…`). Otherwise read the commit messages: `git log --format=%B origin/<base>..HEAD`, after `git fetch origin <base>`.
   - In commit messages, a link is a line opening with a closing keyword (`Closes`, `Fixes`, `Resolves` and their forms) or with `Refs #N`, per the issue-link rule. Extract only the number.
   - Check that the number names an issue: `gh api repos/116-Labs/cuecal/issues/<n> --jq .pull_request`
     - An HTTP 404 answer, or a non-null `pull_request`, means it names no issue.
     - Any other failure ends `failed` naming the read (`fail-closed-reads`).
   - A number from the dispatch or from a commit-message link that names no issue ends `failed` naming it, with nothing pushed.
   - A number taken only from the branch name that names no issue is dropped and noted in the report. No issue at all does not block either: the report notes the missing link and the result's `issue` is `null`.

### 2. Check the working tree

1. Run `git status --porcelain=v1 --untracked-files=all`.
2. Untracked entries (`??`) never stop the run: a harness may write its own settings there, and the run directory may sit there.
3. open-pr owns no uncommitted work at the start. Any tracked file with uncommitted changes was not made by this run.
   - Never stage, stash, reset or discard it (`explicit-staging`, `commit-foreign-edits`).
   - End `needs-human` naming the file, before any install or gate: the gates would test a tree that is not the one pushed.

### 3. Confirm there is something to propose

Run `git fetch origin <base>`, then `git rev-list --count origin/<base>..HEAD`. If the count is 0, end `failed` with reason "nothing to propose".

### 4. Merged-PR check (before any collapse or push)

A squash-merged branch still looks one commit ahead of the base, and a branch name built from the issue can be reused by a fresh branch. So list PRs in **every** state and judge the branch by its commits, never by its name.

1. Run:
   `gh api --paginate 'repos/116-Labs/cuecal/pulls?state=all&head=116-Labs:<branch>'`
   A merged PR reads `closed` with `merged_at` set. A failed read ends `failed` (`fail-closed-reads`). The listing must be paginated to the end (`complete-listings`).
2. Run `git fetch origin <base>`. If it fails, treat the branch as the old one.
3. For each merged PR, run both checks. If either says so, the branch is the old one.
   - **Where it started.** This check comes first because it survives a re-collapse or a review fix pushed from another checkout. A review-pr collapse in a throwaway worktree leaves the local branch on the pre-fix commit, and a resumed branch re-collapsed in place gets a new sha, but neither moves the fork point.
     1. Run `git merge-base HEAD origin/<base>` and record the result as `<fork-point>`.
     2. Run `git merge-base --is-ancestor <merge_commit_sha> <fork-point>`.
     3. Exit 1 means the branch started before that merge, so it is the old branch.
   - **Its head.**
     1. If `<head.sha>` is not local (`git cat-file -e <head.sha>` fails), run `git fetch origin pull/<number>/head`.
     2. Run `git merge-base --is-ancestor <head.sha> HEAD`.
     3. Exit 0 means the branch holds the merged head, so it is the old branch.
4. Fail closed. Each of these counts as the old branch:
   - a missing `merge_commit_sha`
   - a base or head commit that cannot be fetched
   - any `--is-ancestor` exit other than 0 or 1
5. **Old branch:** end `failed` naming that PR, with nothing pushed. Its work is already in the base.
6. **Branch passes both checks:** it is a fresh branch that reuses the name, and it proceeds. Remember each cleared merged PR's `head.sha`. The remote branch may still hold it, and the push replaces it with a lease on the sha read in step 6, never a blind force.

### 5. Preflight and judgement pass

The profile configures no `preflight` scanner. Automated scanners would cover only some surfaces anyway, and a quick visual check misses hidden metadata, so this pass does both jobs by hand.

1. List the changed files: `git diff --name-status <fork-point>..HEAD`.
2. Read **every** changed file in full, because no check declares `covers`. Use the file-reading tool, or `git show HEAD:<path>`.
3. In every changed file, look for what a scanner cannot decide: real personal names, emails, phone numbers or addresses, private strings, internal hostnames or paths, tokens and keys, and secrets inside binaries or file metadata. For binaries, inspect `git show HEAD:<path>` output and note anything embedded.
4. Check the content itself. Never trust a commit or PR claim that it is clean (`push-private-content`). The repo is public.
5. Anything real-looking ends `needs-human` with nothing pushed. `reason` names the files, never the content (`preflight-passed`).

### 6. Remote check (before install, collapse or push)

Run these in the order written. Every read fails closed (`fail-closed-reads`), and every listing is paginated to the end (`complete-listings`).

1. **Remote head.**
   1. Run `git ls-remote origin refs/heads/<branch>` and record the sha as `<inspected-sha>`. Empty output means the branch does not exist there.
   2. When it exists and is not local, run `git fetch origin <branch>`.
   3. Run `git merge-base --is-ancestor <inspected-sha> HEAD` on the pre-collapse HEAD.
   4. Exit 1 means the remote holds commits this checkout lacks. Then end `needs-human` naming `<inspected-sha>`, with nothing pushed (`remote-head-contained`). The one exception is when `<inspected-sha>` is the `head.sha` of a merged PR cleared in step 4: the fresh branch replaces it.
2. **Open PRs.**
   - This branch's open PR:
     `gh api --paginate 'repos/116-Labs/cuecal/pulls?state=open&head=116-Labs:<branch>'`
   - Open PRs that link the same issue from another branch:
     `gh pr list --repo 116-Labs/cuecal --state open --limit 1000 --json number,headRefName,url,body,closingIssuesReferences,commits`
     1. Exactly 1000 results means the listing may be truncated: end `failed` (`complete-listings`).
     2. A PR links the issue when it is in `closingIssuesReferences`, or when a closing-keyword or `Refs #N` line names it in the body or in any commit message.
     3. An open PR for the issue on another branch ends `needs-human` naming it, with nothing pushed (`one-pr-per-issue`). This run cannot update a PR whose head it does not own, and must not open a second one.
3. **Approved and unchanged.** This applies only when this branch has an open PR `<n>`.
   1. **Count approvals.** Run:
      `gh api --paginate repos/116-Labs/cuecal/pulls/<n>/reviews`
      For each reviewer, take the latest review that is `APPROVED` or `CHANGES_REQUESTED`. It counts when it is `APPROVED` and not dismissed. This profile sets both `dismiss_stale_approvals` and `require_last_push_approval` (to `false`), so an approval of an earlier commit still counts.
   2. **Would a push invalidate them?** Yes, because `dismiss_stale_approvals` is true. Collapsing before the first push costs nothing: there is no approval to dismiss and no thread to strand. On a PR that is already approved, the same collapse throws the approval away for nothing.
   3. **Compare trees.** When at least 1 approval counts, run `git rev-parse HEAD^{tree}` and `git rev-parse <inspected-sha>^{tree}`.
   4. **Read mergeability.** Run `gh pr view <n> --json mergeable,mergeStateStatus`. While `mergeable` is `UNKNOWN`, read again, up to five reads in all. A value still `UNKNOWN`, or unreadable, is not known to be clean, so the run carries on.
   5. **Decide.** Take the `published-unchanged` path only when all of these hold:
      - the trees are equal
      - the PR is neither `CONFLICTING` nor `DIRTY`
      - the PR is not a stacked child whose parent merged
   6. **On that path**, push nothing: no collapse and no rebase onto a base that merely moved (`content-free-push-after-approval`). Run no install and no gate. Skip the update step and the reviewer request too: an unchanged PR needs neither. Go straight to step 13 with `status: done`, `gates: []`, no `push`, and `commit_sha` set to the PR head (`gh pr view <n> --json headRefOid,url`).
   7. **Otherwise** carry on. Any rebase the PR needs happens in step 8. Compare tree identity before and after it for the result's `push`.

### 7. Install and gates on the branch as it stands

1. Run `uv sync --locked`. A failure ends `failed` naming the command and quoting its output briefly, with nothing pushed (`install-before-gates`).
2. Time and run each gate in profile order:
   1. `date -u +%s`
   2. `uv run ruff check .`
   3. `date -u +%s`
   4. `date -u +%s`
   5. `uv run pytest`
   6. `date -u +%s`
3. Record `name`, `command`, `exit_code` and `duration_ms` for each gate.
4. Every required gate must exit 0 before anything is pushed (`gates-green-before-push`). A failing gate here, on the branch's own tree before any rebase, ends `failed` naming it and quoting its output briefly, with nothing pushed. Fixing it is implement's work, not this run's. Never hide an exit code behind a pipe or filter (`status-preserved`).

### 8. Collapse step, merged-parent rebase and drift check

**Merged-parent rebase first.** Do this when step 1 found the stacked parent merged. Otherwise a collapse against `main` would fold the parent's commits into this one.

1. If `<old-parent-tip>` is not local, run `git fetch origin pull/<parent-n>/head`.
2. Run `git merge-base --is-ancestor <old-parent-tip> HEAD`. Exit 1 means the parent was rewritten after this branch left it (for example, collapsed). Then do not rebase: end `needs-human` naming the parent, with nothing pushed.
3. Record `git rev-parse HEAD` as the pre-rewrite head, and its tree with `git rev-parse HEAD^{tree}`.
4. Run `git fetch origin main`.
5. Run `git rebase --onto origin/main <old-parent-tip>`. On conflict, list the paths with `git diff --name-only --diff-filter=U`, run `git rebase --abort`, and end `needs-human` naming the paths.
6. When the PR exists, retarget it with `gh pr edit <n> --base main`. A PR created later takes `main`. `<base>` is `main` from here on.
7. Run the install, both gates and the judgement pass again on the rebased tree, timed as in step 7. A failure ends `needs-human` naming it, with nothing pushed.

**Collapse, in place.** Apply the shared single-commit collapse routine in place against the current checkout. The run declares the mode. Never infer "PR mode" from the fact that a PR exists: on a re-run, that flips the collapse to rewriting the remote head, which skips the new local commits and resets them away as divergence.

1. **Regime.** `merge.message_source` is `commits`, so the collapse runs.
2. **Idempotence.** Run `git fetch origin <base>`, then `git merge-base HEAD origin/<base>` and record the result as `<merge-base>`. Count with `git rev-list --count <merge-base>..HEAD`. A count of 1 means nothing to do: record mode "in place, no-op". Always rewrite against `<merge-base>`, never against the base's tip.
3. **Soft gates, overridden.** This run has already judged the branch. Name each gate that fired in the report:
   - an existing approval would be dismissed
   - unresolved threads exist. Always print the count. With a PR, read it via `gh api graphql --paginate -F query=@<run-dir>/scratch/threads.graphql -F owner=116-Labs -F name=cuecal -F number=<n>`, with the query written to that file by the file tool.
4. **Hard gates, never overridden.** Any of these is a refusal:
   - **The branch lives on a fork.** Check `gh pr view <n> --json isCrossRepository` when a PR exists; the origin remote is `116-Labs/cuecal`.
   - **A commit has another author.** Compare `git log --format=%ae <merge-base>..HEAD` with the email in `git var GIT_AUTHOR_IDENT`. Never use `git config user.email`.
   - **The remote head moved.** When the branch exists on the remote, read `git ls-remote origin refs/heads/<branch>` again just before the rewrite. It must equal `<inspected-sha>`, and `git merge-base --is-ancestor <inspected-sha> <pre-collapse-head>` must exit 0 (`collapse-remote-contained`). A merged-PR head cleared in step 4 is exempt.
5. **Record the pre-collapse state.** Run `git rev-parse HEAD` and record `<pre-collapse-head>`. Run `git rev-parse HEAD^{tree}` and record `<pre-collapse-tree>`.
6. **Message.** Read the existing messages with `git log --format=%B <merge-base>..HEAD`. Write one Conventional Commits message for the whole change to `<run-dir>/scratch/commit-msg.txt`:
   - Drop process commits ("wip", "fix lint").
   - Keep the issue-link line (`Closes #N`, or `Refs #N` on a line of its own) and any **Deferred** list, worded as before (`collapse-keeps-link`).
   - Never put a closing keyword next to a Deferred list (`reference-consistent`).
   - Add no attribution or trailer (`attribution-policy`).
7. **Settling a missing link.** When step 1 resolved an issue but no commit carries its link, settle it here and amend only that link. This also covers an issue that became known only after the PR existed. Use `Closes #N` only when the diff meets every acceptance criterion of the issue. Otherwise use `Refs #N` plus a **Deferred** list of the open criteria, worded as the issue words them. Prove nothing else in the message changed:
   1. Write the old and new messages to scratch files.
   2. Run `git diff --no-index <run-dir>/scratch/msg-before.txt <run-dir>/scratch/msg-after.txt`.
   3. The diff must show only the link and Deferred lines.
8. **Rewrite.**
   1. Run `git reset --soft <merge-base>`.
   2. Run `git diff --cached --quiet`. Exit 0 means the change nets to empty: abort.
   3. Run `git commit -F <run-dir>/scratch/commit-msg.txt`, with hooks enabled.
   4. Run `git rev-parse HEAD^{tree}`. It must equal `<pre-collapse-tree>`, or abort (`collapse-content-preserved`).
9. **Commit hook rejection.** If a commit hook rejects the commit, the fix would change the content, which is beyond this run's remit. Restore and end `failed` naming the hook and quoting its output (`bypass-hook`).
10. **Refusal or abort.** Restore the pre-collapse HEAD with `git reset --soft <pre-collapse-head>`, never commit again, push nothing, and end `failed` naming the gate.

**Drift check.**

1. Run `git fetch origin <base>`, then `git rev-parse origin/<base>`. Record the result as `<base-sha-fetched>` for the after-push check.
2. Run `git merge-base --is-ancestor origin/<base> HEAD`. Exit 0 means no drift.
3. **The base moved:**
   1. Record the pre-rewrite head and tree.
   2. Run `git rebase origin/<base>`. Never create a merge commit; the branch stays one commit.
   3. On conflict, collect the paths with `git diff --name-only --diff-filter=U`, run `git rebase --abort`, and end `needs-human` naming them.
   4. Run the install, both gates and the judgement pass again on the rebased tree, timed. A failure ends `needs-human` naming it, with nothing pushed (`gates-green-before-push`).
   5. Only the runs on the rebased tree go into `gates` (`gates-final-tree`).
4. **Open stacked parent:** rebase onto `origin/<override>` the same way.
5. **Existing PR:** compare tree identity before and after any rewrite. Equal trees mean `push.changes` is `tree unchanged`.

### 9. Push step

1. Run `git rev-parse --git-path hooks` and `ls <hooks-dir>` to note which local hooks exist. Never edit, move or disable them (`hook-ran`, `bypass-hook`).
2. Confirm one commit ahead with `git rev-list --count origin/<base>..HEAD`, which must print 1 (`single-commit-pushed`).
3. Push:
   - **Branch existed on the remote:** `git push --force-with-lease=<branch>:<inspected-sha> --set-upstream origin <branch>` (`bare-force-push`).
   - **Branch did not exist:** `git push --set-upstream origin <branch>`, a non-force push. A non-fast-forward rejection counts as a lease mismatch.
4. **Hook rejection.** When the local pre-push hook rejects, fix what it reports and push again. If the fix needs code changes beyond this run's remit, end `failed` naming the hook and quoting its output.
5. **Any other failed push** is never retried (`push-failure-states`):
   1. Restore the HEAD from before this push's rewrites (the collapse and any rebase) with `git reset --keep <pre-rewrite-head>`, and push nothing more.
   2. Permission refusals end `needs-human` naming the refusal: no write access, a protected branch, HTTP 403, a declined pre-receive or protected-branch hook, GH006 or GH013.
   3. A lease mismatch, a network error or anything else ends `failed` naming it.
6. Never use `--admin` or any other bypass (`admin-bypass`).

### 10. Update step

When step 6 found an open PR for this branch, rewrite its body as the create step words it, write it to `<run-dir>/scratch/pr-body.md`, and run `gh pr edit <n> --body-file <run-dir>/scratch/pr-body.md`. Never open a second PR (`one-pr-per-issue`).

### 11. Create step

Unless the update step ran, run:
`gh pr create --repo 116-Labs/cuecal --base <base> --head <branch> --title "<commit subject>" --body-file <run-dir>/scratch/pr-body.md`

The body has these sections:

- **Summary**: what changed and why.
- **Issue link**: the same `Closes #N` or `Refs #N` line as the commit (`reference-consistent`). For `Refs`, add a **Deferred** section naming each criterion left open, taken from the commit message, or from the issue when the commit names none.
- **Review focus** (optional): questions about risk. It is a lead, never a boundary. Never tell reviewers what not to look at (`narrow-review-scope`).
- **Test plan**: one checkbox per gate (`lint`: `uv run ruff check .`, `test`: `uv run pytest`). Tick a box only for a gate that ran on the pushed tree and exited 0. Leave a gate that did not run unticked, with the reason beside it (`test-plan-honest`).
- No attribution or provenance section (`attribution-policy`).

### After-push check (part of the push step; for a new PR, run it right after the create step)

1. Read `gh pr view <n> --json mergeable,mergeStateStatus,baseRefOid,url`. While `mergeable` is `UNKNOWN`, read again, up to five reads. A value still `UNKNOWN` after the fifth read, or a failed read, ends `needs-human` naming the check, with nothing more pushed. It is never read as mergeable.
2. If `baseRefOid` differs from `<base-sha-fetched>`, or the PR is `CONFLICTING` or `DIRTY`, rebase within the single-commit rules:
   - an ordinary base: as in the drift check
   - a stacked PR whose parent has merged: by the merged-parent rebase, then `gh pr edit <n> --base main`
   - a conflict, or an `<old-parent-tip>` that is not an ancestor, ends `needs-human` naming it
3. Before the second push, run the install, both gates and the judgement pass on the rebased tree, timed. A failure ends `needs-human` naming it, with nothing more pushed.
4. Push again with `git push --force-with-lease=<branch>:<sha-just-pushed> origin <branch>`. Failures follow step 9.
5. Update the PR body's test plan to the gates that ran on the rebased tree, with `gh pr edit <n> --body-file <run-dir>/scratch/pr-body.md` (`test-plan-honest`).
6. Allow at most **one** second push (`base-drift-checked`). After it, read the PR again as in point 1. If the base moved again or the PR is `CONFLICTING` or `DIRTY`, end `needs-human` naming it.

### 12. Reviewer request

`review.reviewers` is empty and `review.request_when_empty` is absent, which means `none`. Request nobody. GitHub's CODEOWNERS requests happen on their own (`code_owner_reviews: true`).

### 13. Run result (every exit path, including failures)

1. Run `date -u +%Y-%m-%dT%H:%M:%SZ` and record `finished_at`.
2. Write `<run-dir>/result.json.tmp` with the file-writing tool. It must be valid against the run-result schema:

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
    {"name": "test", "command": "uv run pytest", "exit_code": 0, "duration_ms": 9000}
  ],
  "branch": "gaal/123-short-slug",
  "commit_sha": "<40-hex sha of the pushed head>",
  "push": {"why": "collapse to one commit and rebase onto moved main", "changes": "tree unchanged"},
  "started_at": "2026-10-08T12:00:00Z",
  "finished_at": "2026-10-08T12:05:00Z"
}
```

Field rules:

- `issue` and `pr` are integers, or `null` when unknown or not created.
- `branch` is a string, or `null` if the run never got a branch.
- `commit_sha` is a 40-character lowercase hex sha, or `null`.
  - After a push: the pushed head.
  - On the `published-unchanged` path: the PR's head.
  - When nothing was pushed: the local HEAD, or `null`.
- `gates` follows `gates-final-tree`:
  - Only runs on the final tree, in the order they ran.
  - After a rebase, only the runs on the rebased tree.
  - `[]` on the `published-unchanged` path. The profile has no preflight runs to list.
  - A `done` result never lists a non-zero exit.
  - A result that is not `done` lists the runs on the tree it stopped on, and may include the red run that stopped it.
- `reason` is required unless `status` is `done`. It is one sentence of at most 160 characters naming the decision or action needed (`run-result-written`). Detail belongs in the PR and the final message.
- `questions` is never used: this blueprint has no `needs-clarification` exit.
- `push` is present only when the run pushed to a PR that already existed. Give `why`, and `changes` as a short range-diff summary (`git range-diff <inspected-sha>...HEAD`) or `tree unchanged`. It is absent on the `published-unchanged` path and for a newly created PR.
- No extra fields (`truthful-report`).

3. Run `mv <run-dir>/result.json.tmp <run-dir>/result.json`. Never leave the `.tmp` file behind.

In the final message, report:

- the PR URL
- the collapse mode ("in place"), regime, commit count before and after, soft gates overridden, old → new sha and tree hash
- any merged PR cleared in step 4, and any issue-number note
- what the PR needs before merging: 1 approval, a code-owner review, required checks `test` and `zizmor`, and all threads resolved. Auto-merge squashes; there is no merge queue.

## Exit states

- `done`: the PR exists and `pr` is set. The report includes the URL, the collapse mode, and what the PR needs before merging. On the `published-unchanged` path nothing was pushed: the report says the PR is published and unchanged, `gates` holds no gate run, and `push` is absent.
- `needs-human`: nothing more is pushed, and `reason` names the cause. The cases:
  - a tracked file had uncommitted changes this run did not make (nothing installed, gated or pushed)
  - a merged stack parent's last head is not an ancestor of the branch (`reason` names the parent)
  - the judgement pass found real-looking private content (`reason` names the files, not the content)
  - the remote branch holds commits this branch lacks (`remote-head-contained`; `reason` names the sha)
  - an open PR for the issue exists on another branch (`reason` names it)
  - a rebase onto a moved base conflicted (`reason` names the paths)
  - a gate or judgement pass failed on a rebased tree, before or after the push
  - the base moved again, or the PR was unmergeable, after the second push
  - a mergeability check was unreadable
  - the push was refused for permission (`push-failure-states`)
- `failed`: `reason` names the gate, hook, command or read and quotes its output briefly. The cases:
  - nothing to propose
  - the dispatched branch exists nowhere
  - the issue number from the dispatch or a commit link names no issue
  - the branch is a merged PR's old branch (nothing pushed; `reason` names the PR)
  - the install failed, or a required gate failed on the branch's own tree before any rebase (nothing pushed)
  - the hook rejected the commit or push and the fix is beyond this run's remit
  - the push failed for another reason, such as a lease mismatch or a network error (HEAD restored)
  - the collapse refused or its content gate aborted
  - a read failed or a listing was truncated (`fail-closed-reads`, `complete-listings`)

## Invariants

- `single-commit-pushed`: whenever the run pushes, the branch has exactly one commit ahead of the base. The `published-unchanged` path leaves the commits as they are.
- `reference-consistent`: the commit message and PR body carry the same issue link: `Closes #N` only when the issue is fully resolved, otherwise `Refs #N` plus Deferred, never both.
- `preflight-passed`: no preflight check is configured here, and the judgement pass found nothing on the final diff.
- `hook-ran`: every commit and push went through the repository's verification hook.
- `one-pr-per-issue`: at most one open PR for the branch or issue when the run ends. One on another branch ends the run `needs-human` before any push.
- `base-drift-checked`: the base is compared before and after the push. A moved base or an unmergeable PR is rebased within the single-commit rules, or ends `needs-human`.
- `test-plan-honest`: every ticked box names a gate that ran on the pushed tree and exited 0.
- `gates-green-before-push`: `uv run ruff check .` and `uv run pytest` exit 0 on the pushed tree, after `uv sync --locked`. A failure on the branch's own tree ends `failed`; a failure on a rebased tree ends `needs-human`.
- `remote-head-contained`: the remote head, when there is one, is an ancestor of the pre-collapse HEAD, or is a cleared merged-PR head. The first push leases on it; a second push leases on the sha the first push left.
- `published-unchanged`: an approved PR with equal trees gets no push, install, gate, collapse or rebase, and ends `done` with no gate run in `gates` and no `push`.
- `explicit-staging`: stage only paths this run wrote, from its manifest. Never stage wholesale.
- `base-untouched`: never commit or push to `main`. Work found on it is moved to a `gaal/` branch, and `main` is reset to `origin/main`.
- `fail-closed-reads`: a failed read stops the run `failed`, except the mergeability check, which ends `needs-human`. Never read a failure as "nothing".
- `complete-listings`: listings are paginated to the end, or the run ends `failed`.
- `truthful-report`: the report and result describe what happened. A gate that did not run is absent.
- `status-preserved`: no exit code is lost to a pipe or filter.
- `attribution-policy`: `commits.attribution: none`, so no trailers, provenance or AI attribution in commits or the PR.
- `run-result-written`: `result.json` is written atomically on every exit path.
- `gates-final-tree`: `gates` lists only runs on the final tree, in order.
- `install-before-gates`: `uv sync --locked` runs before every gate run, including after a rebase.
- `push-failure-states`: hook rejections are fixed. Other failures are not retried: HEAD is restored, permission refusals end `needs-human`, and the rest end `failed`.
- `collapse-remote-contained`: the remote head, re-read just before the rewrite, equals `<inspected-sha>` and is an ancestor of the pre-collapse head, unless it is a cleared merged-PR head.
- `collapse-content-preserved`: an empty net change, or a tree mismatch after the collapse, aborts: HEAD is restored, nothing is pushed, and the commit is never retried.
- `collapse-keeps-link`: the collapsed message keeps, or carries the settled, issue-link line and Deferred list.

## Forbidden actions

- `narrow-review-scope`: using the review focus to tell reviewers what not to look at.
- `push-private-content`: pushing personal data, secrets or private strings, or trusting prose claims of cleanliness without checking the content.
- `content-free-push-after-approval`: pushing a content-free change (a collapse, or a rebase onto a base that merely moved) to a PR with 1 or more counted approvals. Here `dismiss_stale_approvals` is true, so such a push would dismiss them.
- `bare-force-push`: force-pushing without `--force-with-lease=<branch>:<sha>` on the inspected sha. Never `--force` or `-f`.
- `admin-bypass`: `gh pr merge --admin` or any privileged route around protection or hooks.
- `bypass-hook`: `--no-verify`, `git commit -n`, `--no-gpg-sign`, any change to where git looks for hooks, disabling a hook manager, editing hook files or `.git/config`, or retrying a rejection by another route.
- `machine-specific-paths`: hard-coding home directories, private scripts or services instead of reading them from the profile.
- `commit-foreign-edits`: committing changes this run did not make. Never `git add -A`, `git add .` or `git commit -a`.
