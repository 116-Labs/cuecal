---
name: gaal-open-pr
description: Publishes a finished single-commit branch in 116-Labs/cuecal as one pull request against main, or against an open stacked parent branch, that links its GitHub issue. It then writes the run result to result.json in the run directory. Use it when a dispatch or the user asks for the open-pr step (open, send or publish a PR) for work that is already implemented, with the branch named in the dispatch or checked out. It checks that the branch is not a merged PR's old branch, reads every changed file for private content, runs the profile gates (uv run ruff check . and uv run pytest), collapses the branch in place to one Conventional Commits commit, checks base drift, pushes with an explicit lease, and creates or updates the PR. Do not use it to implement an issue (gaal-implement), revise a PR after review (gaal-revise-pr), review a PR (gaal-review-pr), merge or deploy. When no commit is ahead of the base, the run ends failed with "nothing to propose".
---
<!-- gaal-stamp blueprint=open-pr@1.6.0 shared=1.5.0 profile=833de6ae33df6d68 generated=2026-10-08 core=b5e6128298936ac3 forbidden=f9de5558e585a82c content=5fdbd9855ef213d3 -->

# gaal-open-pr

This skill publishes a finished change as a pull request on `116-Labs/cuecal`. The pushed branch holds one hand-written Conventional Commits commit, and the PR body links the issue with the same link as the commit. That gives reviewers and the squash merge a clean, traceable unit. It implements blueprint `open-pr` version `1.6.0`.

## Repository facts (from `.gaal/project.yml`)

- Repo: `116-Labs/cuecal` (private). Default branch: `main`. Tracker: GitHub issues.
- Gates, run in this order, both required:
  - `lint`: `uv run ruff check .`
  - `test`: `uv run pytest`
- Install: the profile names no `install` command, so this run installs nothing. It runs the gates in the checkout itself, using the checkout's existing environment. Never run the gates in a throwaway worktree, because a worktree has no installed dependencies.
- Preflight: the profile lists no preflight checks (`preflight: []`). No scanner runs, and no preflight entry ever goes into `gates`. The judgement pass therefore covers every changed file.
- Advisory checks: none named.
- Branch prefix: `gaal/`. Commits: single commit (`single_commit: true`), Conventional Commits, `attribution: none`. Never add `Co-Authored-By`, "Generated with" lines, a provenance section or any other AI or agent attribution to the commit or the PR body.
- Merge: squash, no merge queue, no auto-merge, `message_source: commits`. Because the merge takes its message from the commits, the collapse regime is active.
- Review: `required_approvals: 1`. `reviewers: []`. `request_when_empty` is absent, so it means `none`. `review.dismiss_stale_approvals` and `review.require_last_push_approval` are both absent, so:
  - assume any push invalidates approvals;
  - count an approval only when it is on the current head.
- Reviews come from the separate review identity `116-labs-gaal-review[bot]`. Pushes come from `116-labs-gaal-push[bot]`.
- Stacking: `stacking` is absent. A stacked PR (one given a base override) takes its parent branch as its base until the parent merges. No stacking tool exists, so publish stacks with plain `git` and `gh`.
- Limits: `implement_attempts: 3`, `revise_rounds: 3`, `review_rounds: 2`. This step consumes none of them. It makes one pass and records `attempts: 1`. Within that pass:
  - at most one second push, after the after-push check;
  - at most five reads of `mergeable` while it is `UNKNOWN`.

## Headless command rules

- Run only commands that start with `git`, `gh`, `mkdir`, `mv`, `cp`, `ls`, `cat`, `date` or `pwd`, plus exactly `uv run ruff check .` and `uv run pytest`, with nothing added to either.
- Run one command per call. Never chain with `&&`, `;` or `|`. Never use `$VAR`, `${VAR}`, `$(…)`, backticks or `NAME=value` prefixes.
- `<run-dir>` stands for the literal run directory path given in the run context (the value of `GAAL_RUN_DIR`). Take the run id the same way, from the run context (the value of `GAAL_RUN_ID`). Never expand either variable in a command.
- Other placeholders such as `<branch>`, `<base>`, `<sha>`, `<pr>` and `<n>` stand for literal values you read earlier. Substitute them before running the command.
- Scratch files go in `<run-dir>/scratch`. Create it first with `mkdir -p <run-dir>/scratch`.
- Write every file with the file-writing tool, never through shell redirection. This covers commit messages, PR bodies and `result.json.tmp`.
- Pass commit messages with `git commit -F <file>` and PR bodies with `--body-file <file>`, never inline.
- Quote every URL that contains `?` or `&`, and every glob.
- Read the time with `date -u +%Y-%m-%dT%H:%M:%SZ`.
- Time each gate with `date -u +%s` run just before and just after it, as separate commands. `duration_ms` is the difference times 1000.
- An exit status is never lost (`status-preserved`). Read the exit code of every command and act on it.
- For `git merge-base --is-ancestor`:
  - exit 0 means yes;
  - exit 1 means no;
  - any other exit is a failure.
- If you need the hooks directory, run `git rev-parse --git-path hooks`. Never write a command that names the hooks-path config key, and never edit, move or restore hook files or `.git/config`.

## Steps

Record `started_at` first: `date -u +%Y-%m-%dT%H:%M:%SZ`. Then `mkdir -p <run-dir>/scratch`.

Keep these values in mind as you go:

- branch, base and issue;
- the inspected remote sha;
- the pre-collapse sha and pre-collapse tree;
- the base sha fetched by the drift check;
- the sha of each push;
- PR number;
- every gate run on the current tree.

Every exit below goes to the **run result** step.

### 1. Resolve the repo, branch, base and issue

1. Run `gh repo view --json nameWithOwner` and confirm the answer is `116-Labs/cuecal`. If the read fails, end `failed` naming it (`fail-closed-reads`).
2. **Branch.**
   - **When the dispatch names a branch:** switch to it with `git switch <branch>`.
     - If it exists only on the remote (`git ls-remote origin refs/heads/<branch>` shows it), run `git fetch origin <branch>`, then `git switch --track origin/<branch>`.
     - If it exists nowhere, end `failed` naming it.
     - Never create a new branch for a dispatched name. Gaal starts runs on `main`, so a dispatched branch is never the one checked out at the start.
   - **Only without a dispatched branch:** use the current branch (`git branch --show-current`). If that branch is `main` and holds commits ahead of `origin/main` (`git fetch origin main`, then `git rev-list --count origin/main..HEAD`), protect the base (`base-untouched`):
     - move the work with `git switch -c gaal/<issue>-<short-slug>`;
     - reset `main` with `git branch -f main origin/main`.
   - Never commit to `main` or push it.
3. **Base.** The base is `main` unless the dispatch gives a base override, which marks a stacked PR.
   - For an override, look up the parent PR (the PR whose head branch is the override): `gh api --paginate "repos/116-Labs/cuecal/pulls?state=all&head=116-Labs:<override>"`.
   - **When the parent has merged** (`merged_at` set):
     - keep its number and its `head.sha` (the old parent tip) for the merged-parent rebase;
     - fetch only the default branch with `git fetch origin main`, never `git fetch origin <override>`, because the parent branch may have been deleted at merge;
     - from then on `<base>` is `main` for every step, including the merged-PR check, the collapse's merge base and the drift check.
   - **While the parent is open:** `<base>` is the override.
4. **Issue number.** Take it from the first of these that gives one:
   1. the dispatch;
   2. a link in a commit message on the branch (`git log --format=%B origin/<base>..HEAD`): a line that opens with a closing keyword (`Closes`, `Fixes`, `Resolves` and their forms) or with `Refs #N`;
   3. the branch name (`gaal/<N>-…`).

   Extract only the number.
5. **Check that the number names an issue:** `gh api repos/116-Labs/cuecal/issues/<n> --jq .pull_request`.
   - Output `null` means it is an issue.
   - A 404, or a non-null value (the number is a PR), means it names no issue.
   - Any other failure ends `failed` naming the read (`fail-closed-reads`).
   - What happens to a number that names no issue depends on where it came from:
     - from the dispatch or from a commit link: end `failed` naming it, with nothing pushed;
     - only from the branch name: drop it and note it in the report.
   - No issue number at all does not block. The report notes the missing link.

### 2. Check the working tree for edits this run did not make

1. Open-pr owns no uncommitted work at the start, so there is nothing for it to commit.
2. Run `git status --porcelain=v1 --untracked-files=all`.
   - Untracked (`??`) and ignored files never stop the run, because a harness may write its own settings there.
   - A **tracked** file with uncommitted changes (staged or unstaged) ends `needs-human` naming the file. This happens before any install or gate, because the gates would otherwise test a tree that is not the one pushed.
3. Never stage, stash, reset or discard changes this run did not make (`explicit-staging`, `commit-foreign-edits`). Never use `git add -A`, `git add .` or `git commit -a`.
4. If the run later has to write a file (for example to fix what a hook reports), stage that path alone with `git add -- <path>`, and keep a manifest of every such path.

### 3. Confirm there is something to propose

Run `git fetch origin <base>`, then `git rev-list --count origin/<base>..HEAD`. If the count is 0, end `failed` with reason "nothing to propose".

### 4. Merged-PR check (before anything is collapsed or pushed)

A squash-merged branch still looks one commit ahead of the base, and a branch name built from the issue number repeats. So this check looks at PRs in every state and judges the branch by its commits, not its name.

1. List the PRs whose head is this branch, in every state: `gh api --paginate "repos/116-Labs/cuecal/pulls?state=all&head=116-Labs:<branch>"`. A failed or truncated listing ends `failed` (`fail-closed-reads`, `complete-listings`). A merged PR reads `closed` with `merged_at` set.
2. If `git fetch origin <base>` fails, the branch counts as the old one.
3. For each merged PR, run both checks below. The branch counts as the old one if either check says so.

**Where it started** (run this check first). Looking only at the merged head's sha misses the most common stale branch:

- review-pr collapses in a throwaway worktree, so the local branch still points at the commit before the fix;
- a resumed branch that was re-collapsed in place gets a new sha.

The fork point does not change in either case.

1. Run `git merge-base HEAD origin/<base>` and record the result as `<fork-point>`.
2. Run `git merge-base --is-ancestor <merge_commit_sha> <fork-point>`.
3. Exit 1 means the branch started before that merge, so it is the old branch.

**Its head.**

1. If `head.sha` is not local (`git cat-file -e <head.sha>^{commit}` fails), run `git fetch origin pull/<number>/head`.
2. Run `git merge-base --is-ancestor <head.sha> HEAD`.
3. Exit 0 means the branch holds the merged head, so it is the old branch.

**Fail closed.** Each of these counts as the old branch:

- a missing `merge_commit_sha`;
- a base or head commit that cannot be fetched;
- any `--is-ancestor` exit other than 0 or 1.

**Outcome.**

- **Old branch:** end `failed` naming that PR, with nothing pushed. Its work is already in the base, and pushing again would re-submit it.
- **Passes both checks:** the branch is a fresh branch from the current base that reuses the name, and it proceeds. Record the merged PR's `head.sha` as cleared. The remote branch may have been deleted at merge, in which case the push recreates it. It may also still hold the merged commits, in which case the push replaces them with a lease, never a blind force.

### 5. Preflight and judgement pass

1. The profile lists no preflight checks, so no scanner runs.
2. Do the judgement pass over **every** changed file:
   1. List the files with `git diff --name-only <fork-point>..HEAD` and `git diff --numstat <fork-point>..HEAD`. In the numstat output, `-` marks a binary file.
   2. Read each changed file in full with the file-reading tool.
   3. Read every commit message on the branch.
   4. Look for what a scanner cannot decide: real people's names, emails, phone numbers or addresses, private strings, tokens or secrets, and content hidden in binaries or file metadata. Use `git show <sha>:<path>` for files not in the working tree.
3. Never trust a claim in commit or PR prose that content is clean. Check the content itself. Automated scanners cover only some surfaces, and a visual check misses hidden metadata, so this pass always runs.
4. Real-looking private content ends `needs-human`, with nothing pushed (`preflight-passed`, `push-private-content`). `reason` names the files, never the content.

### 6. Remote check (before any install, collapse or push)

Run these checks in the order written. Every read here fails closed: a failed call ends `failed` naming it, never "no branch" or "no PR" (`fail-closed-reads`).

**Remote head** (`remote-head-contained`).

1. Run `git ls-remote origin refs/heads/<branch>` and record the sha as the **inspected sha**. An empty answer means the branch does not exist on the remote.
2. When it exists:
   1. If the sha is not local, run `git fetch origin <branch>`.
   2. Run `git merge-base --is-ancestor <remote-sha> HEAD` against the pre-collapse HEAD.
   3. Exit 1 ends `needs-human` naming the remote sha, with nothing pushed, unless the remote sha is the `head.sha` the merged-PR check cleared.

**Open PRs** (`one-pr-per-issue`).

1. Find the open PR for this branch: `gh api --paginate "repos/116-Labs/cuecal/pulls?state=open&head=116-Labs:<branch>"`.
2. With an issue number, find any open PR **on another branch** that links the same issue:
   1. List the open PRs with `gh api --paginate "repos/116-Labs/cuecal/pulls?state=open&per_page=100"`.
   2. For each one on another branch, read its links:
      - closing issues: `gh pr view <n> --json closingIssuesReferences`;
      - its body: lines opening with a closing keyword or `Refs #N`;
      - each commit message: `gh api --paginate repos/116-Labs/cuecal/pulls/<n>/commits`.
3. An open PR for the issue on another branch ends `needs-human` naming it, with nothing pushed. This run cannot update a PR whose head it does not own, and must not open a second.

**Approved and unchanged** (`published-unchanged`, `content-free-push-after-approval`). This applies only when an open PR exists for this branch.

1. Read its reviews: `gh api --paginate repos/116-Labs/cuecal/pulls/<pr>/reviews`.
2. Count approvals. A reviewer counts when:
   - their latest review that is `APPROVED` or `CHANGES_REQUESTED` is `APPROVED`;
   - it is not dismissed;
   - its `commit_id` equals the current remote head. Both review settings are absent from the profile, so an approval of an earlier commit does not count.
3. When the count reaches 1 (`required_approvals: 1`), treat any push as one that would invalidate the approvals. Compare the trees:
   - `git rev-parse HEAD^{tree}`
   - `git rev-parse <remote-sha>^{tree}`
4. When the trees are equal, check mergeability with `gh pr view <pr> --json mergeable,mergeStateStatus`. Re-read while `mergeable` is `UNKNOWN`, up to five reads in all; a value still unknown or unreadable is not known to be clean.
5. Take the **published-and-unchanged path** when all of these hold:
   - the trees are equal;
   - the PR is known to be neither `CONFLICTING` nor `DIRTY`;
   - the PR is not a stacked child whose parent merged.

   On this path:
   - push nothing: no collapse, no rebase onto a base that merely moved, no install, no gate;
   - skip every step up to the run result, including the PR update and the reviewer request (an unchanged PR needs neither);
   - end `done` reporting the PR as published and unchanged.

   Collapsing before the first push is almost free. On an approved PR the same collapse throws the approval away for nothing.
6. Otherwise carry on. A rebase the PR needs goes ahead in the collapse step. Record the tree identity before and after it for the result's `push`.

### 7. Install and gates on the branch's own tree

1. The profile names no `install`, so install nothing (`install-before-gates`). Gate in this checkout.
2. Run each gate in order, timed:
   1. `date -u +%s`
   2. `uv run ruff check .`
   3. `date -u +%s`
   4. `date -u +%s`
   5. `uv run pytest`
   6. `date -u +%s`
3. Record `name`, `command`, `exit_code` and `duration_ms` for each run.
4. Both gates are required, and each must exit 0 before anything is pushed (`gates-green-before-push`).
5. A required gate that fails here, on the branch's own tree before any rebase, ends `failed`, with nothing pushed:
   - name the gate and quote its output briefly;
   - do not fix it, because fixing it is implement's work.

### 8. Collapse step and drift check

**Merged-parent rebase first** (only when the base resolution found the stacked parent merged). A collapse against `main` would otherwise fold the parent's commits into this one.

1. If the old parent tip is not local, run `git fetch origin pull/<parent-n>/head`.
2. Run `git merge-base --is-ancestor <old-parent-tip> HEAD`. Exit 1 means the parent was rewritten after this branch left it: do not rebase, and end `needs-human` naming the parent, with nothing pushed.
3. Run `git fetch origin main`, then `git rebase --onto origin/main <old-parent-tip>`. If it conflicts:
   1. list the paths with `git diff --name-only --diff-filter=U`;
   2. run `git rebase --abort`;
   3. end `needs-human` naming the paths.
4. Re-run both gates and the judgement pass on the rebased tree. A failure there ends `needs-human` naming it, with nothing pushed.
5. If the PR exists, run `gh pr edit <pr> --base main`. A PR created later takes `main` as its base.
6. From here on `<base>` is `main`, including for the collapse's merge base and author check, the drift check and the after-push check.

**Collapse in place.** This applies the shared collapse routine with the mode declared as **in-place**. Never infer PR mode from the existence of a PR: on a re-run against a branch whose PR already exists, inferring PR mode makes the collapse rewrite the remote head, skip the new local commits and reset them away as divergence.

1. **Regime.** `merge.message_source` is `commits`, so the collapse applies.
2. **Pre-collapse state.** Record the pre-collapse sha (`git rev-parse HEAD`) and tree (`git rev-parse HEAD^{tree}`).
3. **Idempotence.**
   1. Run `git fetch origin <base>`.
   2. Compute `<merge-base>` with `git merge-base HEAD origin/<base>`.
   3. Count the commits with `git rev-list --count <merge-base>..HEAD`.
   4. A count of 0 or 1 means there is nothing to rewrite.
4. **Soft gates.** Override both, and name each one that fired in the report:
   - an existing approval would be dismissed;
   - unresolved threads exist (print the count).
5. **Hard gates.** These are never overridden. A refusal ends `failed` naming the gate, with nothing pushed.
   - **Fork.** The branch lives on a fork (for an existing PR, `gh pr view <pr> --json isCrossRepository` is true).
   - **Foreign author.** Any commit on the branch has an author email (`git log --format=%ae <merge-base>..HEAD`) that differs from the email in `git var GIT_AUTHOR_IDENT`. Never compare with `git config user.email`.
   - **Remote moved** (`collapse-remote-contained`).
     1. Just before the rewrite, read `git ls-remote origin refs/heads/<branch>` again.
     2. It must equal the inspected sha.
     3. The inspected sha must pass `git merge-base --is-ancestor <inspected-sha> <pre-collapse-sha>`.

     The merged-PR head that the merged-PR check cleared is exempt. Never compare the remote head with the collapsed commit.
6. **Message** (`collapse-keeps-link`, `reference-consistent`, `attribution-policy`). Write the message as a whole for the change, with the file tool, at `<run-dir>/scratch/commit-msg.txt`:
   - a Conventional Commits subject;
   - a body that drops process messages ("wip", "fix lint");
   - the branch's issue-link line kept exactly as it was: `Closes #N`, or `Refs #N` on its own line plus the **Deferred** list;
   - no attribution of any kind.
7. **Rewrite.**
   1. Run `git reset --soft <merge-base>`. Never reset to the base's tip.
   2. If `git diff --cached --quiet` exits 0, the change nets to empty: abort.
   3. Run `git commit -F <run-dir>/scratch/commit-msg.txt`. The commit hook runs (`hook-ran`). If the hook rejects the commit, fix what it reports; never bypass it (`bypass-hook`).
8. **Content check** (`collapse-content-preserved`). `git rev-parse HEAD^{tree}` must equal the pre-collapse tree.
9. **Abort.** For an empty change or a different tree:
   1. restore the pre-collapse HEAD with `git reset --keep <pre-collapse-sha>`;
   2. never commit again;
   3. end `failed` naming the content gate, with nothing pushed.

**Settling a missing issue link.** If the branch already has one commit, but the issue number became known only from the dispatch and the message lacks the link:

1. Amend just the trailer. Read `git log -1 --format=%B`, then write the same message plus the link line to `<run-dir>/scratch/commit-msg.txt`.
2. Run `git commit --amend -F <run-dir>/scratch/commit-msg.txt`.
3. Diff the old and new messages to prove nothing else changed.
4. Confirm the tree is unchanged with `git rev-parse HEAD^{tree}`.
5. The push step then pushes with an explicit lease.

Choose the link this way:

- `Closes #N` only when nothing is deferred;
- otherwise `Refs #N` with a Deferred list worded from the issue.

**Drift check** (`base-drift-checked`).

1. Run `git fetch origin <base>`.
2. Record `git rev-parse origin/<base>` as the **base sha**. The after-push check compares against it.
3. Run `git merge-base --is-ancestor origin/<base> HEAD`:
   - **Exit 0:** no drift.
   - **Exit 1:** the base moved.
     1. Rebase the single commit with `git rebase origin/<base>`, never a merge commit.
     2. On conflict, list the paths with `git diff --name-only --diff-filter=U`, run `git rebase --abort`, and end `needs-human` naming the paths.
     3. After a clean rebase, re-run both gates and the judgement pass on the rebased tree. A failure ends `needs-human` naming it, with nothing pushed.
     4. Only runs on the rebased tree count in `gates` (`gates-final-tree`).
4. A stacked PR whose parent is still open is rebased onto its parent branch the same way.
5. For a branch that already has a PR, compare tree identity before and after any rebase. The result's `push` uses the comparison.

### 9. Push step

Push through the verification hook (`hook-ran`). Never use `--force`, `-f`, `--no-verify` or any form that skips or redirects hooks (`bypass-hook`, `bare-force-push`, `admin-bypass`).

1. Choose the push form:
   - **Branch existed on the remote:** `git push --force-with-lease=<branch>:<inspected-sha> origin <branch>`.
   - **Branch did not exist:** `git push --set-upstream origin <branch>`. A plain push refuses to overwrite anything that appeared there meanwhile.
2. Check that each push lands on `<branch>`, never on `main` (`single-commit-pushed`, `base-untouched`). Run `git rev-list --count origin/<base>..HEAD`: it must be 1.
3. Record the pushed sha (`git rev-parse HEAD`).
4. **Hook rejection** (`bypass-hook`):
   - fix what the hook reports and push again;
   - if the fix needs code changes beyond this blueprint's remit, end `failed` naming the hook and quoting its output briefly.
5. **Any other failed push** is never retried (`push-failure-states`):
   1. Restore the HEAD from before the rewrite made for that push with `git reset --keep <sha-before-rewrite>`. Before the first push, that is the sha before the collapse and any rebase.
   2. Push nothing more.
   3. End this way:
      - a permission refusal (no write access, protected branch, HTTP 403, a GH006 or GH013 server-side or pre-receive decline) ends `needs-human` naming it;
      - a lease mismatch, a network error or anything else ends `failed` naming it.

### 10. Update step

When the remote check found an open PR for this branch, update it rather than opening a second:

1. Write the body exactly as the create step describes, to `<run-dir>/scratch/pr-body.md`.
2. Run `gh pr edit <pr> --body-file <run-dir>/scratch/pr-body.md`.

### 11. Create step

Skip this step if the update step ran.

1. Write the PR body with the file tool to `<run-dir>/scratch/pr-body.md`. It has these sections:
   - **Summary:** what changed and why.
   - **Issue link:** the same link as the commit (`reference-consistent`).
     - `Closes #N` when the issue is fully resolved.
     - Otherwise `Refs #N` on its own line, plus a **Deferred** section naming each criterion left open, taken from the commit message, or from the issue when the commit names none.
     - Never use a closing keyword next to a Deferred list.
     - With no issue, say that no issue is linked.
   - **Review focus** (optional): questions about risk. It is a lead, never a boundary. Never tell reviewers what not to look at (`narrow-review-scope`).
   - **Test plan** (`test-plan-honest`):
     - `- [x] lint: uv run ruff check .`
     - `- [x] test: uv run pytest`

     Tick a box only for a gate that ran on the pushed tree and exited 0. Leave a gate that did not run unticked, with the reason beside it.
   - No attribution or provenance section, because `attribution: none`.
2. Run `gh pr create --repo 116-Labs/cuecal --base <base> --head <branch> --title "<conventional commit subject>" --body-file <run-dir>/scratch/pr-body.md`.
3. Read the PR number from the URL it prints.

### 12. After-push check (part of the push step, once the PR exists)

1. Run `gh pr view <pr> --json mergeable,mergeStateStatus,baseRefOid`.
   - Re-read while `mergeable` is `UNKNOWN`, up to five reads in all.
   - Still `UNKNOWN` after the fifth read, or a failed read, ends `needs-human` naming the check, with nothing more pushed. A failed or unreadable check is never mergeable.
2. Compare `baseRefOid` with the base sha the drift check recorded.
3. If the base moved, or the PR is `CONFLICTING` or `DIRTY`:
   1. Rebase within the single-commit rules.
      - Normally: `git fetch origin <base>`, then `git rebase origin/<base>`.
      - For a stacked PR whose parent has now merged, use the merged-parent rebase: `git rebase --onto origin/main <old-parent-tip>`, or end `needs-human` when that tip is not an ancestor. Then run `gh pr edit <pr> --base main`, and `<base>` is `main` from then on.
   2. A conflict means: list the paths with `git diff --name-only --diff-filter=U`, run `git rebase --abort`, and end `needs-human` naming them.
   3. A rebased tree is not the one the gates passed. Re-run both gates (timed) and the judgement pass on it. A failure ends `needs-human` naming it, with nothing more pushed.
   4. Push again, at most once, with a lease on the sha the first push left: `git push --force-with-lease=<branch>:<first-pushed-sha> origin <branch>`. A failure here follows the push step's failure rules, restoring the HEAD from before this rebase.
   5. Update the PR body's test plan to the gates that ran on the rebased tree: rewrite `<run-dir>/scratch/pr-body.md`, then run `gh pr edit <pr> --body-file <run-dir>/scratch/pr-body.md`.
   6. Read `gh pr view <pr> --json mergeable,mergeStateStatus,baseRefOid` again, with the same rules. If the base moved again, or the PR is `CONFLICTING` or `DIRTY`, end `needs-human` naming it.

### 13. Reviewer request

1. `review.reviewers` is empty and `review.request_when_empty` is absent, which means `none`. So request nobody.
2. Report what the PR needs before merging:
   - 1 approval (from the separate review identity `116-labs-gaal-review[bot]`);
   - green required checks;
   - a manual squash merge (no queue, no auto-merge).

### 14. Run result (every exit path, including failures)

1. Record `finished_at` with `date -u +%Y-%m-%dT%H:%M:%SZ`.
2. If a throwaway worktree was created, remove it with `git worktree remove --force <run-dir>/worktree`. Confirm the hook configuration is unchanged.
3. Write `<run-dir>/result.json.tmp` with the file tool, then run `mv <run-dir>/result.json.tmp <run-dir>/result.json`. Never leave the `.tmp` file behind (`run-result-written`).

The fields:

- `schema_version`: `1`.
- `run_id`: the value of `GAAL_RUN_ID` from the run context.
- `blueprint`: `"open-pr"`.
- `blueprint_version`: `"1.6.0"`.
- `repo`: `"116-Labs/cuecal"`.
- `issue`: the issue number, or `null`.
- `pr`: the PR number, or `null`.
- `status`: `done`, `needs-human` or `failed`.
- `reason`: required unless `done`. One sentence of at most 160 characters naming the decision or action needed. Name files, gates, shas or PRs, never private content.
- `attempts`: `1`.
- `gates`: the gate runs on the final tree only, in the order they ran, each with `name`, `command`, `exit_code` and `duration_ms` (`gates-final-tree`, `truthful-report`).
  - After a rebase, list only the runs on the rebased tree.
  - A gate that did not run is absent.
  - A `done` result never lists a non-zero exit.
  - A result that is not `done` lists the runs on the tree it stopped on, and may include the red run that stopped it.
  - No preflight entries ever appear, since the profile has none. On the published-and-unchanged path, `gates` is `[]`.
- `branch`: the branch name, or `null` if none was resolved.
- `commit_sha`: the 40-hex pushed head. On the published-and-unchanged path, the PR's head. Otherwise the current HEAD, or `null` if unknown.
- `push`: only when the run pushed to a PR that already existed. It is an object `{ "why": …, "changes": … }`:
  - `why`: why the run pushed, for example a collapse or a rebase onto a moved base;
  - `changes`: a short range-diff summary (`git range-diff <old-remote-sha>...<new-sha>`), or `tree unchanged`.

  Absent otherwise, and always absent on the published-and-unchanged path.
- `started_at`, `finished_at`: the recorded timestamps.

Do not add any other keys. Do not write `questions`, because this step never ends `needs-clarification`.

The final message gives:

- the PR URL;
- the collapse mode (in-place) and regime (`commits`);
- the commit count before and after;
- the soft gates overridden;
- the tree hash and old → new sha;
- the reset any stale checkout now needs (a hard reset to the remote, never a pull);
- the merge requirements;
- any dropped or missing issue link.

## Exit states

- `done`: the PR exists and `pr` is set. The report includes the URL, the collapse mode used, and what the PR needs before merging (1 approval, then a manual squash merge). On the published-and-unchanged path (`published-unchanged`):
  - nothing was pushed;
  - the report says the PR is published and unchanged;
  - `gates` holds no gate run;
  - `push` is absent.
- `needs-human`: nothing more is pushed, and `reason` names what applies:
  - a tracked file had uncommitted changes this run did not make (nothing installed, gated or pushed);
  - a merged stack parent's last head is not an ancestor of the branch (names the parent);
  - the judgement pass found real-looking private content (names the files, not the content);
  - the remote branch holds commits this branch lacks (`remote-head-contained`; names the sha);
  - an open PR for the issue exists on another branch (names it);
  - a rebase onto a moved base conflicted (names the paths);
  - a gate failed on a tree rebased before the push;
  - after the push, a gate or the judgement pass failed on the rebased tree, the base moved again, or the PR was unmergeable after the second push;
  - a mergeability check was unreadable;
  - the push was refused for permission (`push-failure-states`).
- `failed`: `reason` names the gate, hook, command or read and quotes its failing output briefly. It applies when:
  - there is nothing to propose;
  - the dispatched branch exists nowhere;
  - the issue number from the dispatch or a commit link names no issue;
  - the branch is a merged PR's old branch (names that PR, nothing pushed);
  - a required gate failed on the branch's own tree before any rebase (nothing pushed);
  - the hook rejected a commit or push and the fix is beyond this run's remit;
  - a push failed for another reason, such as a lease mismatch or a network error (HEAD restored);
  - the collapse refused (a hard gate fired) or its content gate aborted;
  - a read failed or a listing was truncated (`fail-closed-reads`, `complete-listings`).

## Invariants

- `single-commit-pushed`: whenever the run pushes, the pushed branch has exactly one commit ahead of the base. The published-and-unchanged path pushes nothing and leaves the commits as they are.
- `reference-consistent`: the commit message and the PR body carry the same issue link. `Closes #N` only when the issue is fully resolved; otherwise `Refs #N` plus a Deferred section. Never both.
- `preflight-passed`: every preflight check exited 0 on the final diff (there are none in this profile), and the judgement pass found nothing.
- `hook-ran`: commits and pushes went through the repository's verification hook. It was never skipped.
- `one-pr-per-issue`: at most one open PR exists for the branch or issue at the end. An open PR for the issue on another branch is found before any push and ends the run `needs-human`.
- `base-drift-checked`: the base was compared with the branch before and after the push. A moved base or an unmergeable PR ended rebased within the single-commit rules, or `needs-human`.
- `test-plan-honest`: every ticked test-plan box names a gate that ran on the pushed tree and exited 0.
- `gates-green-before-push`: `uv run ruff check .` and `uv run pytest` exited 0 on the pushed tree. A failure:
  - before any rebase: `failed`;
  - on a rebased tree: `needs-human`;
  - either way, nothing (more) is pushed.
- `remote-head-contained`: before any push, the remote head (if any) is an ancestor of the pre-collapse HEAD, or is the merged-PR head the merged-PR check cleared. Otherwise the run ends `needs-human`. The first push leases on that sha; a second push leases on the sha the first push left.
- `published-unchanged`: on an approved PR whose tree would not change, the run pushes nothing, runs no install, gate, collapse or rebase, and ends `done`.
- `explicit-staging`: stage only paths this run wrote, by explicit path, from its manifest. Never stage wholesale.
- `base-untouched`: never commit or push to `main`. Work found on `main` moves to a `gaal/` branch, and `main` is reset to `origin/main`.
- `fail-closed-reads`: a failed read stops the run `failed` naming it, except the mergeability check, which ends `needs-human`. A failed read never becomes "nothing".
- `complete-listings`: every listing of PRs, reviews or commits is paginated to the end (`gh api --paginate`), or the run ends `failed`.
- `truthful-report`: the report and the result describe what actually happened. A gate that did not run is absent.
- `status-preserved`: no exit status is lost to a pipe, a filter or a guard.
- `attribution-policy`: `attribution: none`. No attribution of any kind in commits or PR bodies.
- `run-result-written`: `result.json` is written atomically on every exit path.
- `gates-final-tree`: `gates` lists only the runs on the final tree, in the order they ran.
- `install-before-gates`: the install runs before each gate run. The profile names none, so nothing is installed and the gates run in the checkout.
- `push-failure-states`: a hook rejection is fixed. Any other failed push restores HEAD, is never retried, and ends:
  - `needs-human` for a permission refusal;
  - `failed` otherwise.
- `collapse-remote-contained`: just before the rewrite, the remote head equals the inspected sha and is an ancestor of the pre-collapse head. The cleared merged-PR head is exempt.
- `collapse-content-preserved`: an empty net change, or a tree that differs after the commit, aborts the collapse, restores HEAD and pushes nothing.
- `collapse-keeps-link`: the collapsed message keeps the issue-link line and any Deferred list, or carries the link this run settled.

## Forbidden actions

- `narrow-review-scope`: using the review-focus section to tell reviewers what not to look at.
- `push-private-content`: pushing real personal data, secrets or private strings, or trusting prose claims of cleanliness without checking the content.
- `content-free-push-after-approval`: pushing a content-free change (a collapse, or a rebase onto a base that merely moved) to a PR that holds 1 counted approval, since any push is assumed to dismiss it.
- `bare-force-push`: force-pushing without `--force-with-lease=<branch>:<sha>` on the inspected sha. Never `--force` or `-f`.
- `admin-bypass`: `gh pr merge --admin` or any admin route around protection or hooks.
- `bypass-hook`: `--no-verify`, `git commit -n`, `--no-gpg-sign`, redirecting the hooks path, disabling a hook manager, editing hook files or `.git/config`, or retrying a rejected commit or push by another route.
- `machine-specific-paths`: hard-coding home directories, drive letters, private scripts or services.
- `commit-foreign-edits`: committing changes this run did not make.
