---
name: gaal-open-pr
description: Publishes a finished branch in 116-Labs/cuecal as one pull request against `main`, or against an open stacked parent branch, linked to the branch's GitHub issue. Before it pushes anything, it checks that the branch is not the old branch of a merged PR and checks the remote side. It runs `uv sync --locked`, then the required gates `uv run ruff check .` and `uv run pytest`. It collapses the branch in place to one Conventional Commits commit with no attribution, checks base drift and pushes with an explicit lease through the repository's verification hook. It then creates or updates the PR, checks mergeability and writes the run result to `result.json` in the run directory. Use it when a dispatch or the user asks for the open-pr step ("open a pull request for branch `<branch>`", "open / send / publish a PR") for work that is already implemented. Do not use it to implement an issue (gaal-implement), revise a PR after review (gaal-revise-pr), review a PR (gaal-review-pr), merge, publish or deploy.
---
<!-- gaal-stamp blueprint=open-pr@1.6.0 shared=1.5.0 profile=6f85855df888e336 generated=2026-10-09 core=b5e6128298936ac3 forbidden=f9de5558e585a82c content=6cda92ca9f2a10e1 -->

# gaal-open-pr

This skill publishes a finished change in `116-Labs/cuecal` as a pull request. The pushed branch holds one hand-written Conventional Commits commit and the PR body links the issue, so reviewers and the squash merge get a clean unit that can be traced back to its issue. Blueprint `open-pr`, version `1.6.0`.

## Run context and command rules

- In every command below, `<run-dir>` stands for the literal path of the run directory from the run context (the value of GAAL_RUN_DIR). Write that path out in full and never type the variable name in a command. Take the run id (the value of GAAL_RUN_ID) from the run context too; it is written only into `result.json`.
- Fill placeholders such as `<branch>`, `<base>`, `<sha>`, `<pr>` and `<n>` by hand, with the literal values you read earlier. Never use shell variables, `$(…)`, backticks or a `NAME=value` prefix in a command.
- Run one command per call, with no `&&`, `;` or `|`. Read each command's exit code and output directly. Never let a filter or guard hide whether a command failed (`status-preserved`).
- Apart from the file tools, only these commands are allowed: `git`, `gh`, `mkdir`, `mv`, `cp`, `ls`, `cat`, `date`, `pwd` (with any arguments), and these three, exactly as written with nothing added: `uv sync --locked`, `uv run ruff check .`, `uv run pytest`. Run them in this checkout. The work happens in place, so no throwaway worktree is needed.
- Write every file (commit message, PR body, GraphQL query, `result.json.tmp`) with the file-writing tool, never through shell redirection. Pass each one by its path: `git commit -F <file>`, `gh pr create --body-file <file>`, `gh pr edit --body-file <file>`, `-F query=@<file>` for `gh api graphql`.
- Quote every glob, and every API path that contains `?`, `&` or `^`.
- Scratch files go in `<run-dir>/scratch`, never in `/tmp`. Nothing under `<run-dir>` is ever staged.
- Never skip or redirect the repository's verification (`bypass-hook`). That means no `--no-verify` (or its short commit form), no `--no-gpg-sign`, no change to where git looks for hooks, no hook manager switched off, and no edit, move or restore of a hook file or `.git/config`. Never merge, push or rewrite with admin privileges (`admin-bypass`). To find the hooks directory, run `git rev-parse --git-path hooks`.
- A force-push always takes an explicit lease on the inspected sha, `--force-with-lease=<branch>:<sha>` (`bare-force-push`). Plain force flags are never used. Stage only by explicit path. Never stage everything wholesale and never commit all tracked changes in one sweep (`explicit-staging`).
- Write no machine-specific paths, private scripts or secrets into any file or command (`machine-specific-paths`).

## Profile facts used by this skill

- Repo: `116-Labs/cuecal`, which is public. Default branch: `main`. Tracker: GitHub issues.
- Install: `uv sync --locked`, run before the gates every time (`install-before-gates`).
- Gates, both required, run in this order:
  - `lint`: `uv run ruff check .`
  - `test`: `uv run pytest`
- Preflight: none. No check declares `covers`, so the judgement pass reads every changed file in full. The profile names no advisory checks, and none run.
- Commits: one commit per PR, Conventional Commits (`type(scope): subject`), attribution `none`. The commit and the PR body carry no AI attribution, no agent `Co-Authored-By` trailer and no provenance section (`attribution-policy`).
- Branch prefix: `gaal/`.
- Merge:
  - Method `squash`, no merge queue, `auto: true`.
  - `message_source: commits`, so the squash message comes from the single commit and the collapse routine applies. This skill does not merge and does not turn on auto-merge.
- Review:
  - `required_approvals: 1`.
  - `dismiss_stale_approvals: true` and `require_last_push_approval: false`. A push dismisses approvals. An approval of an earlier commit that has not been dismissed still counts.
  - Code-owner reviews are required (`code_owner_reviews: true`), unresolved threads block merge, and the required checks are `test` and `zizmor`.
  - `reviewers: []`, and `request_when_empty` is absent, which means `none`.
  - Reviews come from the separate review identity `116-labs-gaal-review[bot]`. Pushes are made as `116-labs-gaal-push[bot]`.
- Stacking: not configured, so `stacking.base` is `parent`. A stacked PR (base override) takes its parent branch as its base until the parent merges, then `main`. No stacking tool is set, so a stack is published with plain `git` and `gh`.
- Limits: `implement_attempts: 3`, `revise_rounds: 3`, `review_rounds: 2`. Other steps use those. This step's own bounds are 1 first push, at most 1 second push after an after-push rebase, and at most 5 mergeability reads per check. Record `attempts: 1`.

## Steps

"End `failed`", "end `needs-human`" or "end `done`" anywhere below means stop the current work and go straight to the **run result** step. The run result is written on every exit path.

### 1. Start, then resolve the branch, base and issue

1. Run `date -u +%Y-%m-%dT%H:%M:%SZ` and keep the value as `started_at`.
2. Run `mkdir -p <run-dir>/scratch`.
3. Run `git rev-parse --git-path hooks`, then `ls <hooks-dir>`, and note which local hooks exist (such as `pre-commit` or `pre-push`). The report cites them for `hook-ran`. Never change them.
4. **Get onto the branch.**
   - When the dispatch names a branch:
     1. Check for it locally with `git rev-parse --verify --quiet refs/heads/<branch>` and on the remote with `git ls-remote origin refs/heads/<branch>`.
     2. If it exists locally, run `git switch <branch>`.
     3. If it exists only on the remote, run `git fetch origin <branch>`, then `git switch <branch>`. This creates a local branch that tracks `origin/<branch>`.
     4. If it exists nowhere, end `failed` naming the branch.
     5. Never create a new branch for a dispatched name.
   - Without a dispatched branch, use the current branch (`git branch --show-current`). If that branch is `main` and holds commits ahead of `origin/main`, move the work off the base (`base-untouched`):
     1. Read `git rev-parse main` as `<old-main>` and `git rev-parse origin/main` as `<origin-main>`.
     2. Run `git branch <new-branch>`, with a name under the prefix such as `gaal/<n>-<slug>`.
     3. Run `git switch <new-branch>`.
     4. Run `git update-ref refs/heads/main <origin-main> <old-main>`.
   - Never commit or push to `main`.
5. **Resolve the base.** Without an override, `<base>` is `main`. A base override (a stacked PR) names the parent branch:
   1. Look up the parent PR with `gh pr list --repo 116-Labs/cuecal --head <override> --state all --json number,state,mergedAt,headRefOid`.
   2. If the parent PR has merged:
      - Run `git fetch origin main` only. Never run `git fetch origin <override>`, because the parent branch may have been deleted at merge.
      - Keep the parent's number as `<parent-n>` and its `headRefOid` as `<old-parent-tip>` for the merged-parent rebase.
      - From then on, `<base>` is `main` for every step: the merged-PR check, the collapse's merge base and author check, the drift check and the after-push check.
   3. Otherwise `<base>` is the override.
   4. Run `git fetch origin <base>`. A lookup or fetch that fails ends `failed` naming it (`fail-closed-reads`).
6. **Resolve the issue number.** Use the dispatch first. Otherwise take the number from the branch name (`gaal/<n>-…`) or from a link in the commits.
   1. Read the messages with `git log --format=%B origin/<base>..HEAD`. By the issue-link rule, a link is a line that opens with a closing keyword (`Closes`, `Fixes`, `Resolves` and their forms) or with `Refs #N`. Extract only the numbers.
   2. Check each candidate with `gh api repos/116-Labs/cuecal/issues/<n> --jq .pull_request`:
      - `null` means it is an issue.
      - A 404 answer, or a non-null value (the number is a pull request), means it names no issue.
      - Any other failure ends `failed` naming the read.
   3. A number from the dispatch or from a commit-message link that names no issue ends `failed` naming it, with nothing pushed.
   4. A number taken only from the branch name that names no issue is dropped and noted in the report.
   5. No issue at all does not block the run. The report notes the missing link.

### 2. Check the working tree

1. Run `git status --porcelain=v1 --untracked-files=all`.
2. This run owns no uncommitted work at the start, so it commits nothing here.
3. Untracked (`??`) and ignored files never stop the run, because a harness may write its own settings there. Leave them alone.
4. A tracked file with uncommitted changes ends `needs-human` naming that file, before any install or gate runs. Otherwise the gates would test a tree that is not the one pushed.
5. Never stage, stash, reset or discard changes this run did not make (`explicit-staging`, `commit-foreign-edits`).

### 3. Confirm there is something to propose

Run `git rev-list --count origin/<base>..HEAD`. If the count is 0, end `failed` with "nothing to propose".

### 4. Merged-PR check

Before anything is collapsed or pushed, make sure this branch is not the old branch of a PR that already merged. An open-PR lookup after the push cannot tell the two apart, and a squash-merged branch still looks one commit ahead of the base. So look at every state, and judge the branch by its commits, never by its name. A branch scheme built from the issue gives a fresh branch the merged branch's name again, and refusing by name would refuse that branch forever.

1. List every PR whose head is this branch:

   `gh api --paginate 'repos/116-Labs/cuecal/pulls?state=all&head=116-Labs:<branch>&per_page=100' --jq 'map({number, merged_at, merge_commit_sha, head_sha: .head.sha})'`

   A failed or truncated listing ends `failed` (`fail-closed-reads`, `complete-listings`). A merged PR reads `closed` with `merged_at` set.
2. Run `git fetch origin <base>`. If that fetch fails, treat the branch as the old one.
3. For each merged PR, run both checks. The branch is the old one when either check says so.
   - **Where it started (check this first).** The fork point catches the most common stale branch. review-pr collapses in a throwaway worktree, which leaves the local branch on the commit before the fix, and a branch re-collapsed in place gets a new sha. Neither changes the fork point.
     1. Run `git merge-base HEAD origin/<base>` and keep the result as `<fork-point>`.
     2. If `merge_commit_sha` is missing, the branch is the old one.
     3. If `git cat-file -e '<merge_commit_sha>^{commit}'` fails, run `git fetch origin <merge_commit_sha>`. If that fetch fails, the branch is the old one.
     4. Run `git merge-base --is-ancestor <merge_commit_sha> <fork-point>`:
        - Exit 0 passes.
        - Exit 1 means the branch started before that merge, so it is the old branch even with a different head sha.
        - Any other exit counts as the old branch.
   - **Its head.**
     1. If `git cat-file -e '<head_sha>^{commit}'` fails, run `git fetch origin pull/<number>/head`. If that fetch fails, the branch is the old one.
     2. Run `git merge-base --is-ancestor <head_sha> HEAD`:
        - Exit 1 passes.
        - Exit 0 means the branch holds the merged head, so it is the old branch.
        - Any other exit counts as the old branch.
4. If the branch is the old one, end `failed` naming that PR, with nothing pushed. Its work is already in the base, and pushing the branch again would re-submit it.
5. A branch that passes both checks for every merged PR is a fresh branch that reuses the name, and it proceeds. Record each such merged PR's `head_sha` as **cleared**.
6. Expect care on the remote side. The remote branch may have been deleted at merge, and then the push recreates it. Or it may still hold the merged commits, and then the push replaces them with a lease on the sha that the remote check reads, never a blind force.

### 5. Preflight and judgement pass

Automated scanners cover only some surfaces and file types, and a visual check misses hidden metadata, so normally both run. Never trust a claim in commit or PR prose that content is clean (`push-private-content`).

1. The profile declares no `preflight` checks, so no scanner runs and `gates` holds no preflight entries.
2. Do the judgement pass on the diff:
   1. List the changed files with `git diff --name-only origin/<base>...HEAD`.
   2. Read each changed file in full with the file-reading tool. No check declares `covers`, so every changed file is in scope.
   3. Run `git diff --stat origin/<base>...HEAD` to spot binaries.
   4. In every file, look for what a scanner cannot decide: real people's names or contact details, private strings, internal hostnames, tokens, keys, and secrets in binaries or file metadata.
3. If real-looking private content turns up, end `needs-human` with nothing pushed. The `reason` names the files, never the content (`preflight-passed`).

### 6. Remote check

Run these checks before anything is installed, collapsed or pushed, in the order written. Every read fails closed: an error, an auth failure or a rate limit ends `failed` naming the read.

1. **Remote head** (`remote-head-contained`).
   1. Run `git ls-remote origin refs/heads/<branch>`.
   2. Record the sha as the **inspected sha**, or record that the branch is absent on the remote. The first push leases on this value.
   3. If the branch is present:
      1. If `git cat-file -e '<remote-sha>^{commit}'` fails, run `git fetch origin <branch>`.
      2. On the branch as it stands, before any collapse, run `git merge-base --is-ancestor <remote-sha> HEAD`:
         - Exit 0: proceed.
         - Exit 1: if `<remote-sha>` is a cleared merged-PR head, proceed, because the fresh branch replaces it. Otherwise the remote holds commits this checkout lacks, so end `needs-human` naming the remote sha, with nothing pushed.
         - Any other exit ends `failed`.
2. **Open PRs** (`one-pr-per-issue`).
   1. Find this branch's open PR with `gh pr list --repo 116-Labs/cuecal --head <branch> --state open --json number,url,body,headRefOid,baseRefName,isCrossRepository`.
   2. When an issue is known, list every open PR with `gh pr list --repo 116-Labs/cuecal --state open --limit 1000 --json number,headRefName,body,closingIssuesReferences,commits`.
      - If the listing returns exactly 1000 entries, it may be truncated, so end `failed` (`complete-listings`).
      - Re-read any PR that shows 100 commits with `gh api --paginate repos/116-Labs/cuecal/pulls/<n>/commits`.
   3. By the issue-link rule, a PR links the issue when the issue is in `closingIssuesReferences`, or appears on a closing-keyword or `Refs #N` line in the PR body or in any commit message.
   4. An open PR that links the same issue from another branch ends `needs-human` naming it, with nothing pushed. This run cannot update a PR whose head it does not own, and it must not open a second one.
3. **Approved and unchanged** (`published-unchanged`, `content-free-push-after-approval`). This check applies only to this branch's own open PR. Collapsing before the first push costs almost nothing, but on an approved PR the same collapse throws the approval away for nothing.
   1. Count approvals:
      1. Run `gh api --paginate repos/116-Labs/cuecal/pulls/<pr>/reviews`.
      2. For each reviewer, take their latest review whose state is `APPROVED`, `CHANGES_REQUESTED` or `DISMISSED`. The reviewer counts when that review is `APPROVED`.
      3. Both review settings are set and `require_last_push_approval` is false, so an approval of an earlier commit that has not been dismissed still counts.
   2. If at least 1 approval counts, a push would invalidate it (`dismiss_stale_approvals: true`). Compare `git rev-parse 'HEAD^{tree}'` with `git rev-parse '<remote-sha>^{tree}'`.
   3. When the trees are equal, read `gh pr view <pr> --repo 116-Labs/cuecal --json mergeable,mergeStateStatus`. While `mergeable` is `UNKNOWN`, read it again, up to 5 reads in all.
   4. Take the **published-and-unchanged path** when the trees are equal, the PR is known to be neither `CONFLICTING` nor `DIRTY`, and the PR is not a stacked child whose parent merged. On that path:
      - Push nothing. Run no install, no gate, no collapse and no rebase onto a base that merely moved.
      - Skip every later step, the update step and the reviewer request included. This is intended: an unchanged PR needs neither.
      - Go to the run result with `status: done`, `pr` set, `commit_sha` set to the PR's `headRefOid`, `gates: []` (the profile has no preflight runs to list) and no `push`.
   5. If mergeability is still `UNKNOWN` after 5 reads, or cannot be read, the PR is not known to be clean. Carry on to the next step.
   6. In every other case, carry on. Any rebase the PR needs happens in the collapse step.

### 7. Install and gates

1. Run `uv sync --locked` (`install-before-gates`). If it fails, end `failed` naming the command and quoting its output briefly.
2. Time and run each gate, in profile order:
   1. Run `date -u +%s`.
   2. Run the gate: `uv run ruff check .` (lint), then `uv run pytest` (test).
   3. Run `date -u +%s` again.
   4. Record `name`, `command`, `exit_code` and `duration_ms`, which is the difference between the two readings times 1000.
3. Both gates are required, and both must exit 0 before anything is pushed (`gates-green-before-push`). A gate that fails here, on the branch's own tree before any rebase, ends `failed` naming it and quoting its output briefly, with nothing pushed. The change is not finished, and fixing it is implement's work.

### 8. Collapse step

The collapse runs **in place**, in this checkout. The mode is declared here and never inferred from whether a PR exists. On a re-run against a branch whose PR already exists, inferring "PR mode" sends the collapse to rewrite the remote head, which skips the new local commits and resets them away as divergence.

1. **Merged-parent rebase first.** This applies only when the base resolution found the stacked parent merged. Without it, a collapse against `main` would fold the parent's commits into this one.
   1. Run `git fetch origin main`.
   2. If `git cat-file -e '<old-parent-tip>^{commit}'` fails, run `git fetch origin pull/<parent-n>/head`.
   3. Run `git merge-base --is-ancestor <old-parent-tip> HEAD`. On any exit other than 0, do not rebase, because the parent was rewritten after this branch left it (for example, collapsed). End `needs-human` naming the parent, with nothing pushed.
   4. Record `git rev-parse HEAD` as `<pre-rewrite-head>` and `git rev-parse 'HEAD^{tree}'` as `<tree-before>`.
   5. Run `git rebase --onto origin/main <old-parent-tip>`. If it conflicts:
      1. Collect the paths with `git diff --name-only --diff-filter=U`.
      2. Run `git rebase --abort`.
      3. End `needs-human` naming those paths.
   6. Run the install and both gates again on the rebased tree, as in step 7, and redo the judgement pass on any file the rebase changed. The new gate runs replace the earlier ones in `gates`. A failure ends `needs-human` naming it, with nothing pushed.
   7. If the PR exists, run `gh pr edit <pr> --repo 116-Labs/cuecal --base main`. A PR created later takes `main` as its base. From now on, `<base>` is `main`.
2. **Regime.** `merge.message_source` is `commits`, so the collapse applies. For a stacked PR, the eventual target is `main`, which uses the same regime. The collapse counts against the merge base with the current `<base>`.
3. **Idempotence.**
   1. Run `git fetch origin <base>`.
   2. Run `git merge-base HEAD origin/<base>` and keep the result as `<merge-base>`.
   3. Run `git rev-list --count <merge-base>..HEAD`.
   4. If the count is 1, the collapse succeeds without rewriting anything, so continue at "Drift check" below. Never reset to the base's tip. A reset to a base that has moved on makes the new commit revert the base's newer changes, even though the tree hash still matches.
4. **Hard gates.** These are never overridden. If one fires, end `failed` naming it, with nothing pushed.
   - **Fork.** The PR has `isCrossRepository: true`, or `git remote get-url origin` does not name `116-Labs/cuecal`.
   - **Foreign author.** Read this run's identity with `git var GIT_AUTHOR_IDENT`, never with `git config user.email`. The gate fires if any author email listed by `git log --format=%ae <merge-base>..HEAD` differs from it.
   - **Remote moved** (`collapse-remote-contained`). When the branch exists on the remote, read `git ls-remote origin refs/heads/<branch>` again. The gate fires if that sha no longer equals the inspected sha, or if `git merge-base --is-ancestor <inspected-sha> HEAD` does not exit 0. A cleared merged-PR head is exempt from the ancestor check. Never compare the remote head with the collapsed commit, because a squash never contains it.
5. **Soft gates.** This run has already judged the branch, so it overrides both soft gates and the report names each one that fired.
   - **Approval would be dismissed.** This fires when an approval counted in the remote check exists, since `dismiss_stale_approvals` is true.
   - **Unresolved threads.** Always print the count. When a PR exists:
     1. Write this query to `<run-dir>/scratch/threads.graphql` with the file tool:

        ```graphql
        query($owner:String!,$name:String!,$number:Int!,$endCursor:String){repository(owner:$owner,name:$name){pullRequest(number:$number){reviewThreads(first:100,after:$endCursor){nodes{isResolved}pageInfo{hasNextPage endCursor}}}}}
        ```

     2. Run `gh api graphql --paginate -F owner=116-Labs -F name=cuecal -F number=<pr> -F query=@<run-dir>/scratch/threads.graphql`.
     3. Count the threads with `isResolved: false`. A failed read ends `failed` (`fail-closed-reads`, `complete-listings`).
6. **Message** (`collapse-keeps-link`, `reference-consistent`, `attribution-policy`). Write `<run-dir>/scratch/commit-msg.txt` with the file tool.
   - Write one Conventional Commits subject (`type(scope): subject`) and a body that describes the change as a whole. Drop process commits such as "wip" and "fix lint".
   - Keep the branch's issue-link line word for word: `Closes #N`, or `Refs #N` on a line of its own together with its **Deferred** list. Never drop, add or reword either on your own.
   - When the commits carry no link but the issue is known:
     1. Read the issue with `gh issue view <n> --repo 116-Labs/cuecal --json title,body` and judge the diff against its acceptance criteria.
     2. Write `Closes #N` only when every criterion is met.
     3. Otherwise write `Refs #N` on its own line, plus a **Deferred** heading that lists each open criterion as the issue words it.
     4. Never put a closing keyword next to a Deferred list.
   - Add no attribution trailer and no provenance text, because `commits.attribution` is `none`.
   - **Link learned after the PR exists.** If the issue number became known only after the PR existed, and the branch already holds one commit, amend only the link line:
     1. Read `git log -1 --format=%B` before the amend.
     2. Run `git commit --amend -F <run-dir>/scratch/commit-msg.txt`.
     3. Read `git log -1 --format=%B` again and compare the two messages, to prove that nothing else changed.
     4. Push with the explicit lease from step 9.
7. **Rewrite.**
   1. Record `git rev-parse HEAD` as `<pre-collapse-head>` and `git rev-parse 'HEAD^{tree}'` as `<pre-collapse-tree>`.
   2. Run `git reset --soft <merge-base>`.
   3. Run `git commit -F <run-dir>/scratch/commit-msg.txt`. The commit goes through the repository's hooks. If a hook rejects it, fix what the hook reports and commit again, without bypassing it. If the fix is beyond this run's remit, run `git reset --keep <pre-collapse-head>` and end `failed` naming the hook and quoting its output briefly.
8. **Content preservation** (`collapse-content-preserved`).
   1. If `git diff --quiet <merge-base> HEAD` exits 0, the rewrite nets to an empty change.
   2. If `git rev-parse 'HEAD^{tree}'` differs from `<pre-collapse-tree>`, the content changed.
   3. Either case aborts the collapse. Run `git reset --keep <pre-collapse-head>` and end `failed` naming `collapse-content-preserved`, with nothing pushed. Never commit again.
9. **Drift check** (`base-drift-checked`).
   1. Run `git fetch origin <base>`. Record `git rev-parse origin/<base>` as `<base-sha>`. The after-push check compares against it.
   2. If `git rev-list --count HEAD..origin/<base>` is above 0, the base moved:
      1. Record `<pre-rewrite-head>` from `git rev-parse HEAD`, if this push has none yet, and record `<tree-before>`.
      2. Run `git rebase origin/<base>`. Never create a merge commit. The branch stays one commit.
      3. On a conflict, collect `git diff --name-only --diff-filter=U`, run `git rebase --abort`, run `git reset --keep <pre-rewrite-head>`, and end `needs-human` naming the conflicting paths.
      4. Run the install and both gates again on the rebased tree, as in step 7, and redo the judgement pass on any file the rebase changed. The new gate runs replace the earlier ones in `gates`. A failure ends `needs-human` naming it, with nothing pushed.
   3. A stacked PR whose parent is still open rebases onto `origin/<parent>` the same way.
   4. Around any rebase of a branch that already has a PR, compare `<tree-before>` with `git rev-parse 'HEAD^{tree}'`. The comparison feeds the run result's `push`.
10. Confirm that `git rev-list --count origin/<base>..HEAD` is exactly 1 (`single-commit-pushed`).

### 9. Push step

1. Push with the verification hook enabled (`hook-ran`):
   - If the branch exists on the remote: `git push --force-with-lease=<branch>:<inspected-sha> origin <branch>`.
   - If the branch did not exist on the remote: `git push --set-upstream origin <branch>`. A plain push is refused if the branch has appeared in the meantime, which leases on its absence.
2. **Hook rejection.** If the local verification hook rejects the push, fix what it reports and push again, without bypassing it (`bypass-hook`). If the fix needs code changes beyond this blueprint's remit, run `git reset --keep <pre-collapse-head>` (or `<pre-rewrite-head>` when that is the earlier one) and end `failed` naming the hook output.
3. **Any other failure** (`push-failure-states`). Never retry. Restore the HEAD from before this push's rewrites with `git reset --keep <pre-rewrite-head-or-pre-collapse-head>`, push nothing more, and classify the failure:
   - A permission refusal ends `needs-human` naming it. That covers no write access, a protected branch, HTTP 403, and a server-side hook such as a pre-receive or protected-branch hook declining the push (GH006, GH013).
   - Anything else ends `failed` naming it. That covers a lease mismatch, a network error and any other error.
4. Record `git rev-parse HEAD` as `<pushed-sha>`.

### 10. Update step

When the remote check found an open PR for this branch, update that PR instead of opening a second one:

1. Write the body to `<run-dir>/scratch/pr-body.md`, worded as step 11 describes.
2. Run `gh pr edit <pr> --repo 116-Labs/cuecal --body-file <run-dir>/scratch/pr-body.md`.

An open PR for the issue on another branch already ended the run in the remote check.

### 11. Create step

Unless the update step already updated a PR:

1. Write `<run-dir>/scratch/pr-body.md` with the file tool. It contains these sections:
   - **Summary**: what changed and why.
   - **Issue link**: the same link as the commit, by the issue-link rule (`reference-consistent`). Either `Closes #N`, or `Refs #N` on its own line with a **Deferred** section that names each open criterion, taken from the commit message (or from the issue when the commit names none). When no issue is known, say so.
   - **Review focus** (optional): questions about risk, such as "Could X break when Y?". Focus is a lead, never a boundary. Never tell reviewers what not to look at (`narrow-review-scope`).
   - **Test plan**: `- [x] lint: uv run ruff check .` and `- [x] test: uv run pytest`. Tick a box only for a gate that ran on the pushed tree and exited 0 (`test-plan-honest`). Leave unticked any gate that did not run, with the reason beside it.
   - **Before merge**: 1 approval, a code-owner review, every thread resolved, the required checks `test` and `zizmor` green, squash merge.
   - No attribution or provenance section.
2. Run `gh pr create --repo 116-Labs/cuecal --base <base> --head <branch> --title "<conventional-commit-subject>" --body-file <run-dir>/scratch/pr-body.md`. Record the PR number and URL.

### 12. After-push check

1. Read `gh pr view <pr> --repo 116-Labs/cuecal --json mergeable,mergeStateStatus,baseRefOid`. While `mergeable` is `UNKNOWN`, read it again, up to 5 reads in all.
2. If it is still `UNKNOWN` after the fifth read, or the read fails, end `needs-human` naming the check, with nothing more pushed. A failed or unreadable check is never read as mergeable.
3. If `baseRefOid` equals `<base-sha>` and the PR is neither `CONFLICTING` nor `DIRTY`, continue to step 13.
4. Otherwise the base moved or the PR is unmergeable. Do the second push, which happens at most once:
   1. Record `<pushed-sha>` as the lease sha and `git rev-parse 'HEAD^{tree}'` as `<tree-before>`.
   2. Run `git fetch origin <base>` and record `git rev-parse origin/<base>` as the new `<base-sha>`.
   3. Rebase, keeping the branch at one commit:
      - Normally, run `git rebase origin/<base>`.
      - For a stacked PR whose parent has merged, use the merged-parent rebase from step 8: `git rebase --onto origin/main <old-parent-tip>`. If that tip is not an ancestor, end `needs-human` naming the parent. Then run `gh pr edit <pr> --repo 116-Labs/cuecal --base main`, and `<base>` is `main` from then on.
   4. On a conflict, collect `git diff --name-only --diff-filter=U`, run `git rebase --abort`, run `git reset --keep <pushed-sha>`, and end `needs-human` naming the paths.
   5. Run the install and both gates again on the rebased tree, as in step 7, and redo the judgement pass on the changed files. A failure ends `needs-human` naming it, with nothing more pushed. The new runs replace the earlier ones in `gates`.
   6. Run `git push --force-with-lease=<branch>:<pushed-sha> origin <branch>`. Handle a failure as in step 9, restoring `<pushed-sha>`. Then record the new `<pushed-sha>`.
   7. Update the body's test plan to the gates that ran on the rebased tree, using `gh pr edit <pr> --repo 116-Labs/cuecal --body-file <run-dir>/scratch/pr-body.md`.
   8. Read `gh pr view <pr> --repo 116-Labs/cuecal --json mergeable,mergeStateStatus,baseRefOid` again, under the same 5-read rule. If the base moved again, the PR is `CONFLICTING` or `DIRTY`, or the read is unreadable, end `needs-human` naming it. No third push is ever made.

### 13. Request reviewers

`review.reviewers` is empty and `request_when_empty` is absent, so it means `none`: request nobody. GitHub requests the code owners from CODEOWNERS by itself. The report says that a code-owner review and 1 approval are still needed.

### 14. Run result

Write this step on every exit path, failures included (`run-result-written`).

1. Read `finished_at` with `date -u +%Y-%m-%dT%H:%M:%SZ`.
2. Write `<run-dir>/result.json.tmp` with the file-writing tool:

   ```json
   {
     "schema_version": 1,
     "run_id": "<value of GAAL_RUN_ID>",
     "blueprint": "open-pr",
     "blueprint_version": "1.6.0",
     "repo": "116-Labs/cuecal",
     "issue": <issue number or null>,
     "pr": <PR number or null>,
     "status": "<done | needs-human | failed>",
     "reason": "<one sentence, at most 160 characters; omit only when done>",
     "attempts": 1,
     "gates": [
       {"name": "lint", "command": "uv run ruff check .", "exit_code": 0, "duration_ms": <ms>},
       {"name": "test", "command": "uv run pytest", "exit_code": 0, "duration_ms": <ms>}
     ],
     "branch": "<branch or null>",
     "commit_sha": "<40-hex sha or null>",
     "push": {"why": "<why it pushed>", "changes": "<short range-diff summary, or tree unchanged>"},
     "started_at": "<started_at>",
     "finished_at": "<finished_at>"
   }
   ```

3. Follow these rules for the fields:
   - **`reason`.** It is required unless `status` is `done`. It names the decision or action needed, in one sentence. Detail goes in the PR and the final message.
   - **`questions`.** This blueprint has no `needs-clarification` exit, so `questions` is never written.
   - **No extra fields.** Add no field that the schema lacks.
   - **`gates`** (`gates-final-tree`, `truthful-report`). List only the runs on the final tree (the pushed tree, or the tree the run stopped on), in the order they ran. Leave out runs on a tree that was later replaced by a rebase. A gate that did not run is absent. A `done` result never lists a non-zero `exit_code`. A result that is not `done` may include the red run that stopped it. The profile has no preflight checks, so no preflight entries appear. On the published-and-unchanged path, `gates` is `[]`.
   - **`commit_sha`.** It is the pushed sha. On the published-and-unchanged path, it is the PR's head. When nothing was pushed on a failure, use `git rev-parse HEAD`, or `null` if no branch was resolved.
   - **`push`.** Include it only when the run pushed to a PR that already existed. `why` is what required the push (collapse, rebase onto a moved base, merged parent, new commits). `changes` is a short range-diff summary from `git range-diff <old-remote-sha>...<pushed-sha>`, or `tree unchanged` when the pushed tree equals the PR head's tree before the run. Leave it out otherwise, and always on the published-and-unchanged path.
4. Run `mv <run-dir>/result.json.tmp <run-dir>/result.json`. Never leave the `.tmp` file behind.
5. In the final message, report these items:
   - The outcome.
   - The PR URL.
   - The collapse mode (in place), the regime (`commits`), the commit count before and after, each gate that fired and each soft gate overridden, the unresolved-thread count, the tree hash, and old → new sha.
   - The reset any stale checkout now needs: hard-reset it to `origin/<branch>`, never pull it.
   - The local hooks that ran.
   - Any missing or dropped issue link.
   - What the PR needs before merging: 1 approval, a code-owner review, every thread resolved, and the required checks `test` and `zizmor`.

## Exit states

- `done`: The PR exists and `pr` is set. The report gives the URL, the collapse mode and what the PR needs before merging. On the published-and-unchanged path (`published-unchanged`), nothing was pushed, the report says the PR is published and unchanged, `gates` holds no gate run and `push` is absent.
- `needs-human`: `reason` names what applies. These are the cases:
  - A tracked file had uncommitted changes this run did not make. Nothing was installed, gated or pushed.
  - A merged stack parent's last head is not an ancestor of the branch. Nothing was pushed.
  - The judgement pass found real-looking private content. Nothing was pushed, and `reason` names the files, not the content.
  - The remote branch holds commits this branch lacks (`remote-head-contained`). Nothing was pushed, and `reason` names the sha.
  - An open PR for the issue exists on another branch. Nothing was pushed.
  - A rebase onto a moved base conflicted. `reason` names the paths.
  - A gate or the judgement pass failed on a rebased tree, before or after the first push.
  - The base moved again, or the PR was unmergeable, after the second push.
  - A mergeability check after the push was unreadable.
  - The push was refused for permission (`push-failure-states`).
- `failed`: `reason` names the gate, hook, command or read, and quotes its output briefly. These are the cases:
  - Nothing to propose.
  - The dispatched branch exists nowhere.
  - An issue number from the dispatch or a commit link names no issue.
  - The branch is a merged PR's old branch, because it started before that PR's merge commit or holds its head commit. Nothing was pushed, and `reason` names that PR.
  - The install failed, or a required gate failed on the branch's own tree before any rebase. Nothing was pushed.
  - The hook rejected the commit or push, and the fix is beyond this run's remit.
  - The push failed for another reason, such as a lease mismatch or a network error. The HEAD was restored.
  - The collapse refused on a hard gate, or its content gate aborted.
  - A read failed or a listing was truncated (`fail-closed-reads`, `complete-listings`).

## Invariants

Blueprint invariants:

- `single-commit-pushed`: Whenever the run pushes, the branch has exactly one commit ahead of the base. When the run pushes nothing to keep an approved PR's approvals, it leaves the branch's commits as they are.
- `reference-consistent`: The commit message and the PR body carry the same issue link: `Closes #N` only when the issue is fully resolved, otherwise `Refs #N` plus a Deferred section, never both.
- `preflight-passed`: Every preflight check exited 0 on the final diff (this profile has none), and the judgement pass found nothing.
- `hook-ran`: Every push went through the repository's verification hook.
- `one-pr-per-issue`: At most one open PR exists for the branch or the issue when the run ends. An open PR for the issue on another branch is found before anything is pushed, and it ends the run as `needs-human`.
- `base-drift-checked`: The base is compared with the branch before and after the push. A moved base or an unmergeable PR ends either rebased within the single-commit rules or `needs-human`.
- `test-plan-honest`: Every ticked box in the test plan names a gate that ran on the pushed tree and exited 0.
- `gates-green-before-push`: Both required gates exited 0 on the pushed tree, after `uv sync --locked` ran on it. A gate failure on the branch's own tree ends `failed`. A gate failure on a rebased tree ends `needs-human`. Either way, nothing more is pushed.
- `remote-head-contained`: Before any push, the remote head (when there is one) is an ancestor of the pre-collapse HEAD, or is a cleared merged-PR head. Otherwise the run ends `needs-human`. The first push leases on that sha, and a second push leases on the sha the first push left.
- `published-unchanged`: On an approved PR whose content would not change, the run pushes nothing and runs no install, gate, collapse or rebase. It ends `done` with no gate runs and no `push`.

Shared invariants:

- `explicit-staging`: Stage only paths this run wrote. Never stage wholesale.
- `base-untouched`: Never commit or push to `main`. Work found on the base moves to a feature branch, and the base is reset to its remote.
- `fail-closed-reads`: A failed read is never treated as "nothing". It ends `failed`, except for the after-push mergeability check, which ends `needs-human`.
- `complete-listings`: Every listing is paginated to the end, or the run ends `failed`.
- `truthful-report`: The report and the result describe what actually happened. A gate that did not run is absent.
- `status-preserved`: No command's success or failure is lost.
- `attribution-policy`: The commit and the PR body follow `commits.attribution: none` exactly.
- `run-result-written`: `result.json` is written atomically on every exit path.
- `gates-final-tree`: `gates` lists only the runs on the final tree, in order. A `done` result never lists a non-zero exit code.
- `install-before-gates`: `uv sync --locked` runs before every gate run, including the runs after a rebase.
- `push-failure-states`: A hook rejection is fixed. Any other failed push is never retried: the HEAD is restored, and the run ends `needs-human` for a permission refusal or `failed` for anything else.
- `collapse-remote-contained`: The remote head, read again just before the rewrite, equals the inspected sha and is an ancestor of the pre-collapse head. A cleared merged-PR head is exempt.
- `collapse-content-preserved`: A collapse that nets to an empty change, or that changes the tree, aborts, restores the HEAD and is never retried.
- `collapse-keeps-link`: The collapsed message keeps the issue-link line and any Deferred list, word for word.

## Forbidden actions

- `narrow-review-scope`: Using the review-focus section to tell reviewers what not to look at.
- `push-private-content`: Pushing real personal data, secrets or private strings, or trusting prose that claims the content is clean.
- `content-free-push-after-approval`: Pushing a collapse, or a rebase onto a base that merely moved, to a PR that holds its 1 required approval when the tree would not change.
- `bare-force-push`: Force-pushing without `--force-with-lease=<branch>:<inspected-sha>`.
- `admin-bypass`: Merging, pushing or rewriting with admin privileges to get around protection, checks or hooks.
- `bypass-hook`: Skipping or redirecting verification by any route, or retrying a rejected commit or push another way.
- `machine-specific-paths`: Hard-coding home directories, private scripts or services.
- `commit-foreign-edits`: Committing changes this run did not make.
