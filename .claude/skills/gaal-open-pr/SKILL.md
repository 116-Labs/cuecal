---
name: gaal-open-pr
description: Publishes a finished single-commit branch in 116-Labs/cuecal as one pull request against `main` (or a specified stacked base) that links its issue, verifies base drift and mergeability, then writes the run result to `$GAAL_RUN_DIR/result.json`. Use when a dispatch or the user asks for the `open-pr` step (open, send or publish a PR) for work that is already implemented and verified, with the branch given or checked out. Do not use to implement an issue, revise a PR after review, review a PR, or merge; those are other steps. Do not use when there is no commit ahead of `main`; end as `failed` instead.
---
<!-- gaal-stamp blueprint=open-pr@1.5.0 shared=1.4.0 profile=7d4c49f36df8465f generated=2026-10-03 core=8e0af7dc54831991 forbidden=f5c350c8651b613b content=4eb3aa8e68b5d29e -->

# gaal-open-pr

Publish a finished change as a pull request against the base. The pushed branch holds one hand-written commit and the PR body links the issue, so reviewers and the merge path get a clean, traceable unit.

## Run context

- Repo: `116-Labs/cuecal`. Base: `main` unless the dispatch gives a base override for a stacked PR (by default `stacking.base` is `parent` when `stacking` is absent).
- Branch prefix: `gaal/`. Commit convention: conventional commits (`commits.convention: conventional`). Attribution policy (`commits.attribution`): `none`.
- Merge regime: `method: squash`, `queue: false` (no merge queue), `message_source: commits`, `auto: false` (auto-merge off).
- Review policy: `required_approvals: 1`, `threads_block_merge: false`, `reviewers: []` (request nobody, following `request_when_empty: none`), `start_signal: reaction`.
- Profile attempt limits: `implement_attempts: 3`, `revise_rounds: 3`, `review_rounds: 2`. This step consumes none of them, so it records `attempts` as 1.
- Tracker: GitHub, through `gh`.
- Take the run id and the run directory from the run context (the literal values of `GAAL_RUN_ID` and `GAAL_RUN_DIR`). Below, `<run-dir>` stands for the literal run-directory path from the run context, and `<run-id>` stands for the literal run id. Write those literal paths in every command and file. Never expand an environment variable (`$VAR`, `${VAR}`, `$(...)`, backticks) in a command, never put `NAME=value` in front of one, and never hard-code machine-specific paths (`machine-specific-paths`).
- Headless execution: Run one command per call. No `&&`, `;` or `|` chains. Read every command's exit status and handle failures (`status-preserved`). Only `git`, `gh`, `mkdir`, `mv`, `cp`, `ls`, `cat`, `date`, `pwd` with any arguments, plus exactly `uv run ruff check .` and `uv run pytest` are allowed.
- Scratch files and throwaway worktrees live inside `<run-dir>` (e.g. `<run-dir>/scratch`), never in `/tmp` or via `mktemp`. Write files with the file-editing tool, not shell redirection.
- Install nothing: the profile names no `install` commands. Run the gates in this checkout, where the dependencies are already installed.

## Steps

1. **Start the clock and resolve repo and base.**
   - Run `date -u +%Y-%m-%dT%H:%M:%SZ` and keep the output as `started_at`.
   - Run `mkdir -p <run-dir>/scratch`.
   - Run `git remote get-url origin` and confirm it points to `116-Labs/cuecal`.
   - Run `git fetch origin`. A failed fetch stops the run as `failed` (`fail-closed-reads`).
   - Base is `main` unless a base override was given for a stacked PR.
   - Run `git branch --show-current`. If the branch is the base (`base-untouched`):
     - Run `git switch -c gaal/<short-slug>`, naming it for the change.
     - Run `git branch -f main origin/main` to reset the local base to its remote.
     - Never commit or push to the base branch.
   - Find the issue number, in this order: the dispatch, the branch name (e.g. `gaal/<N>-...`), or a `Closes #N` or `Refs #N` line in `git log -1 --format=%B`. A missing issue link does not block; record `issue` as `null` in the run result and note it in the report.

2. **Commit any uncommitted work this run owns.**
   - Run `git status --porcelain`.
   - Keep a manifest of the paths this run wrote. Stage only those, one explicit path at a time with `git add <path>` (`explicit-staging`).
   - Never stage everything wholesale (`git add .`, `git add -A`). Parallel worktrees and a person's in-progress edits may be in this checkout. Never commit changes this run did not make (`commit-foreign-edits`).
   - Write the commit message to `<run-dir>/scratch/commit-msg.txt` with the file tool, and commit with `git commit -F <run-dir>/scratch/commit-msg.txt`.
   - Follow the conventional commit convention (`type(scope): subject`). Add no trailer, no provenance section, and no tool credit (`attribution-policy`, `none`).
   - If a commit hook rejects the commit, fix what it reports and commit again; never bypass or redirect hooks (`bypass-hook`).

3. **Confirm at least one commit is ahead of the base.**
   - Run `git rev-list --count origin/main..HEAD` (or `origin/<base>..HEAD` if a stacked base is specified).
   - If the count is 0, end as `failed` with `reason` "nothing to propose" (skip to step 11).

4. **Check for already merged pull requests on this branch.**
   - Before anything is collapsed or pushed, make sure this is not the branch of a pull request that already merged. Looking only for an open PR, and only after the push, cannot tell a finished branch from one whose PR already merged; a squash-merged branch still looks one commit ahead of the base. The branch must be judged by its commits, not its name: a branch scheme built from the issue gives a fresh branch the merged one's name again, and refusing by name refuses it forever.
   - Look up pull requests whose head is this branch across all states: `gh api "repos/116-Labs/cuecal/pulls?state=all&head=116-Labs:<branch>"`. A failed call stops the run as `failed` (`fail-closed-reads`, `complete-listings`).
   - For every pull request that is merged (`state` is `closed` and `merged_at` is non-null), fetch the base (`git fetch origin main`, or `origin/<base>`) and run two checks:
     - **Where it started:** Run `git merge-base HEAD origin/main` to find the fork point sha `<fork-point-sha>`. Then run `git merge-base --is-ancestor <merge_commit_sha> <fork-point-sha>`. If the exit code is not 0 (`merge_commit_sha` is not contained in the fork point), the branch started before that merge, so it is the old branch even when a re-collapse or review fix pushed from another checkout gave it a different head sha.
     - **Its head:** Fetch the merged PR head if not local: `git fetch origin pull/<number>/head`. Then run `git merge-base --is-ancestor <head.sha> HEAD`. If the exit code is 0 (`head.sha` is contained in HEAD), it is the old branch.
   - Fail closed (`fail-closed-reads`): A missing `merge_commit_sha`, a base that cannot be fetched, a head commit that cannot be fetched, or any command failure (exit code other than 0 or 1 for `--is-ancestor`) counts as the old branch.
   - If either check identifies the branch as the old merged branch, push nothing, end as `failed` with `reason` naming that merged PR (e.g. "Branch is from already merged PR #<number>"), and go to step 11.
   - A branch that passes both checks is a fresh branch from the current base that reuses the merged branch's name, and it proceeds. Note the remote state: if the remote branch still exists, read its head sha with `git ls-remote --heads origin <branch>` to prepare for a leased push.

5. **Run preflight and judgement pass** (`preflight-passed`, `push-private-content`).
   - The profile defines `preflight: []` (no automated scanners configured). Do not invent scanner tools or commands.
   - Because no automated check declares `covers`, the judgement pass covers every changed file in full and is mandatory. Automated scanners cover only some surfaces and file types, and a visual check misses hidden metadata; both aspects must be evaluated.
   - Read the full diff with `git diff origin/main...HEAD`. Run `git diff --numstat origin/main...HEAD` to identify binary files (marked `-`), and read commit messages with `git log --format=%B origin/main..HEAD`.
   - Inspect every changed file in full (using `cat <path>` or `git show HEAD:<path>`). Look for real names, emails, phone numbers, calendar details in fixtures or sample files, private strings, credentials, tokens, secrets in binaries or file metadata, and hidden metadata that visual inspection misses.
   - Never trust a claim in commit or PR prose that content is clean; inspect the content itself (`push-private-content`).
   - If any real-looking private content is found, push nothing and end as `needs-human` with a `reason` naming the files (never quoting the private content itself), and go to step 11.

6. **Check base drift and collapse to one commit in place** (`single-commit-pushed`, `base-drift-checked`, `content-free-push-after-approval`).
   - The collapse routine is applied **in place** (this checkout is the target). Never infer PR mode from whether a PR exists: inferring PR mode flips the collapse to rewriting the remote head and resets local commits away as divergence. Collapsing before the first push is almost free; on an approved PR, a content-free collapse throws approvals away for nothing.
   - Regime: `merge.message_source` is `commits`, so the collapse applies. For a stacked PR, collapse against the current base.
   - **Approved PR check:** Before collapsing, check if an open PR for this branch already exists:
     `gh pr list --repo 116-Labs/cuecal --state open --head <branch> --limit 200 --json number,url,headRefName,headRefOid` (`fail-closed-reads`, `complete-listings`).
     - If an open PR exists, read its reviews with `gh api repos/116-Labs/cuecal/pulls/<n>/reviews --paginate` (`complete-listings`). Count approvals per `review.required_approvals: 1`: each reviewer whose latest review approves, is not dismissed, and is on the current head commit (since `dismiss_stale_approvals` / `require_last_push_approval` are not explicitly defined, any push is assumed to dismiss approvals).
     - If the PR holds the required approvals (≥ 1), compare the local tree hash with the remote head tree hash (`git rev-parse HEAD^{tree}` and `git rev-parse <remote-head-sha>^{tree}`).
     - Check PR merge status: `gh pr view <n> --repo 116-Labs/cuecal --json mergeable,mergeStateStatus`.
     - When the tree hashes are equal and the PR is neither `CONFLICTING` nor `DIRTY` nor a stacked child whose parent merged, push nothing: skip the collapse and skip rebasing onto a base that merely moved (`content-free-push-after-approval`). Proceed directly to step 8 and report the PR as published and unchanged.
   - **Base drift check:** Fetch the base with `git fetch origin main` (or `origin/<base>`). Record `<base-sha>` from `git rev-parse origin/main`.
     - Check if the base moved: test whether `origin/main` has commits HEAD does not contain (`git merge-base --is-ancestor origin/main HEAD`).
     - If the base moved, rebase the commit onto the fresh base: `git rebase origin/main` (never create a merge commit; the branch must remain one commit). If rebase encounters conflicts, abort with `git rebase --abort` and end as `needs-human` naming the conflicting paths.
     - If rebase succeeds, run both profile gates (`uv run ruff check .` and `uv run pytest`) on the rebased tree. If any gate fails, push nothing and end as `needs-human` naming the failing gate.
   - **Single-commit collapse:**
     - Idempotence: If `git rev-list --count origin/main..HEAD` is 1, the branch already has exactly one commit; proceed to step 7.
     - Hard gates (never overridden): Confirm origin URL is `116-Labs/cuecal` (`git remote get-url origin`), all commits are authored by the user (`git log --format=%ae origin/main..HEAD` matches `git config user.email`), and if the branch exists on remote, confirm `git ls-remote --heads origin <branch>` is an ancestor with `git merge-base --is-ancestor <remote-sha> HEAD`. Any hard-gate failure ends as `failed`.
     - Soft gates: Check unresolved review threads using `gh api graphql --paginate` (`complete-listings`). Print the count. If an existing approval would be dismissed, refuse the collapse and end as `failed`.
     - Collapse in place: Record old sha with `git rev-parse HEAD` and pre-collapse tree hash with `git rev-parse HEAD^{tree}`.
     - Run `git merge-base origin/main HEAD` to get `<merge-base-sha>`, then run `git reset --soft <merge-base-sha>`.
     - Write the single commit message to `<run-dir>/scratch/commit-msg.txt` using the file tool: conventional format, process commits dropped, attribution `none` (`attribution-policy`), and the issue link per the issue-link rule.
     - Commit with `git commit -F <run-dir>/scratch/commit-msg.txt`.
     - Content preservation: Verify `git rev-parse HEAD^{tree}` equals the pre-collapse tree hash. If the change nets to empty or tree hash changed, run `git reset --hard <old-sha>` and end as `failed` ("collapse refused"). Never use interactive rebase, and never merge as admin (`admin-bypass`).

7. **Push with verification hook enabled and check post-push mergeability** (`hook-ran`, `bypass-hook`, `bare-force-push`, `base-drift-checked`, `test-plan-honest`).
   - Run the required gates on the final commit before pushing:
     - Run `date -u +%s`, `uv run ruff check .` (lint), and `date -u +%s`. Record `name: "lint"`, `command: "uv run ruff check ."`, `exit_code`, and `duration_ms` (difference times 1000).
     - Run `date -u +%s`, `uv run pytest` (test), and `date -u +%s`. Record `name: "test"`, `command: "uv run pytest"`, `exit_code`, and `duration_ms`.
     - If any required gate fails, push nothing and end as `failed` with `reason` quoting the failure.
   - Look up the remote branch with `git ls-remote --heads origin <branch>`.
   - If the branch does not exist on remote, run `git push -u origin <branch>`.
   - If the branch exists on remote, push with an explicit lease on the inspected sha: `git push --force-with-lease=<branch>:<remote-sha> origin <branch>`. Never use a bare force push (`bare-force-push`).
   - Verification hooks must remain enabled (`hook-ran`). Never use `--no-verify`, `git commit -n`, `--no-gpg-sign`, or modify hook settings (`bypass-hook`). If a hook rejects the push, fix what it reports and retry; if the fix is beyond remit, end as `failed` naming the hook output.
   - Confirm exactly one commit is ahead of the base: `git rev-list --count origin/main..HEAD`.
   - **Post-push drift and mergeability check:** Once the PR exists (check step 8/9 for newly created PRs), read merge status: `gh pr view <n> --repo 116-Labs/cuecal --json mergeable,mergeStateStatus,baseRefOid`. Wait briefly while `mergeable` is `UNKNOWN`.
     - Compare `baseRefOid` with the `<base-sha>` fetched in step 6.
     - If `baseRefOid` differs (the base moved while the run worked), or the PR is `CONFLICTING` or `DIRTY`:
       - Rebase the single commit onto the fresh base: `git fetch origin main` then `git rebase origin/main`. If rebase conflicts, abort with `git rebase --abort` and end as `needs-human` naming the conflicting paths.
       - Re-run every gate (`uv run ruff check .` and `uv run pytest`) and the preflight judgement pass on the rebased tree. If any check fails, push nothing and end as `needs-human` naming it.
       - Push again with an explicit lease on the sha just pushed: `git push --force-with-lease=<branch>:<just-pushed-sha> origin <branch>`.
       - Update the PR body's test plan to reflect the gates that ran on the rebased tree (`test-plan-honest`).
       - At most one such second push: if the base moves again after it, end as `needs-human`.
     - For a stacked PR whose parent merged: rebase the child onto `main`, push with lease, and retarget: `gh pr edit <n> --repo 116-Labs/cuecal --base main`.

8. **Check for existing open PR and update or create** (`one-pr-per-issue`, `fail-closed-reads`, `complete-listings`).
   - Search for an open PR for this branch: `gh pr list --repo 116-Labs/cuecal --state open --head <branch> --limit 200 --json number,url,headRefName`. If an issue number is known, also search by issue: `gh pr list --repo 116-Labs/cuecal --state open --search "#<N>" --limit 200 --json number,url,headRefName`.
   - A failed API call stops the run as `failed` (`fail-closed-reads`).
   - If an open PR already exists, update its body with `gh pr edit <n> --repo 116-Labs/cuecal --body-file <run-dir>/scratch/pr-body.md` rather than creating a duplicate (`one-pr-per-issue`).

9. **Create or update the PR with a structured body** (`reference-consistent`, `narrow-review-scope`, `test-plan-honest`, `attribution-policy`).
   - Write the PR body to `<run-dir>/scratch/pr-body.md` using the file tool:
     - **Summary:** Clear, concise description of the change.
     - **Issue link** (`reference-consistent`):
       - Full change (all criteria met): `Closes #N`.
       - Partial change: `Refs #N` on its own line, followed by a **Deferred** section listing each criterion left open as worded in the issue. Take them from the commit message, or from `gh issue view <N> --repo 116-Labs/cuecal --json body`.
       - Never place a closing keyword next to a Deferred list. Commit message and PR body must carry the exact same link.
     - **Review focus** (optional): Phrased as questions about risk. It is a lead, never a boundary; never use it to tell reviewers what not to look at (`narrow-review-scope`).
     - **Test plan** (`test-plan-honest`): Checklist of gates that ran on the pushed tree: `uv run ruff check .` and `uv run pytest`. Tick `[x]` only for gates that ran on the pushed tree and exited 0. Leave unticked `[ ]` with an explanation for any gate that did not run or failed.
     - Attribution: Add no AI attribution, no provenance section, and no tool credits (`attribution-policy: none`).
   - If creating a new PR: `gh pr create --repo 116-Labs/cuecal --base main --head <branch> --title "<commit subject>" --body-file <run-dir>/scratch/pr-body.md` (or `--base <base>` for stacked PRs). Keep the returned PR number and URL.
   - If the issue number only becomes known after the PR exists:
     - Save current commit message with `git log -1 --format=%B`.
     - Write amended message with the issue trailer to `<run-dir>/scratch/commit-msg.txt`.
     - Amend commit: `git commit --amend -F <run-dir>/scratch/commit-msg.txt`.
     - Diff message before and after to verify only the link changed, and verify tree hash is identical (`git rev-parse HEAD^{tree}`).
     - Push with explicit lease: `git push --force-with-lease=<branch>:<inspected-sha> origin <branch>`.
     - Update PR body via `gh pr edit <n> --repo 116-Labs/cuecal --body-file <run-dir>/scratch/pr-body.md`.
   - Perform the post-push drift and mergeability check from step 7 now that the PR number is known.
   - Confirm with `gh pr list` that exactly one open PR exists for the branch and issue (`one-pr-per-issue`).

10. **Reviewers and merge requirements.**
    - Profile `review.reviewers` is `[]` (empty), and `review.request_when_empty` defaults to `none`, so request nobody. Do not invent reviewers or review bots.
    - State in the final report what the PR needs before merging: 1 required approval (`review.required_approvals: 1`), required checks (`uv run ruff check .` and `uv run pytest`), squash merge method taking message from commits (`merge.method: squash`, `merge.message_source: commits`), no merge queue (`merge.queue: false`), auto-merge off (`merge.auto: false`).

11. **Write the run result on every exit path** (`run-result-written`, `truthful-report`).
    - Run `date -u +%Y-%m-%dT%H:%M:%SZ` for `finished_at`.
    - Run `git rev-parse HEAD` for the 40-hex `commit_sha` (or `null` if no commit exists).
    - Write `<run-dir>/result.json.tmp` with the file tool. The JSON object must contain:
      - `schema_version`: 1
      - `run_id`: the literal run id from the run context
      - `blueprint`: `"open-pr"`
      - `blueprint_version`: `"1.5.0"`
      - `repo`: `"116-Labs/cuecal"`
      - `issue`: integer issue number or `null`
      - `pr`: integer PR number or `null`
      - `status`: `"done"`, `"needs-human"`, `"needs-clarification"`, or `"failed"`
      - `reason`: required unless `status` is `"done"`; one sentence of at most 160 characters naming the decision or action needed
      - `questions`: array of non-empty strings, required if `status` is `"needs-clarification"`
      - `attempts`: 1
      - `gates`: array of `{name, command, exit_code, duration_ms}` for each gate that actually ran on the pushed tree (empty array if none)
      - `branch`: string branch name or `null`
      - `commit_sha`: 40-hex commit sha or `null`
      - `push`: required if the run pushed to an open PR that already existed: `{ "why": "<reason>", "changes": "<range-diff summary or 'tree unchanged'>" }`
      - `started_at` and `finished_at`: ISO 8601 timestamps from `date`
    - Atomically rename: `mv <run-dir>/result.json.tmp <run-dir>/result.json`. Never leave a `.tmp` file behind (`run-result-written`).
    - Emit a concise final report: PR URL, collapse mode (in-place), tree hash, old → new sha, gates that ran, merge requirements, and note that any stale checkout must hard-reset to the remote, never pull.

## Exit states

- `done`: The PR exists, `pr` is set, and the branch is pushed with green gates (or confirmed unchanged on an approved PR). The final report includes the PR URL, the collapse mode used, and what the PR needs before merging. No `reason` is needed.
- `needs-human`: The preflight judgement pass found real-looking private content (`reason` names the files, not the content). Or a rebase onto a moved base conflicted (`reason` names the conflicting paths). Or a gate failed on the tree rebased in step 6, or after the push a gate/preflight check failed on the rebased tree, or the base moved again after the second push (`reason` names it).
- `needs-clarification`: The dispatch or checkout state is ambiguous, or no PR/issue could be resolved. `questions` list the specific missing information.
- `failed`: Nothing to propose; the branch is a merged pull request's old branch because it started before that PR's merge commit or holds its head commit (`reason` names the merged PR); a required gate failed; the verification hook rejected the push; or the collapse refused (hard/soft gate failure, empty or tree-changing rewrite); or an API read failed. `reason` names the gate, hook, or step and quotes output briefly.

## Invariants

- `single-commit-pushed`: Whenever the run pushes, the pushed branch has exactly one commit ahead of the base. A run that pushes nothing to preserve an approved PR's approvals leaves the branch's commits as they are (steps 6, 7).
- `reference-consistent`: The commit message and PR body carry the same issue link: `Closes #N` only when fully resolved, otherwise `Refs #N` and a Deferred section, never both (step 9).
- `preflight-passed`: Every `preflight` check exited 0 on the final diff, and the judgement pass found nothing. The profile has no automated preflight commands, so the judgement pass is the whole check (step 5).
- `hook-ran`: The push went through the repository's verification hook and was not skipped (step 7).
- `one-pr-per-issue`: At most one open PR exists for the branch or issue when the run ends (steps 8, 9).
- `base-drift-checked`: The base was compared with the branch before and after the push. A moved base or unmergeable PR ended rebased within single-commit rules, or `needs-human` naming the conflict (steps 6, 7).
- `test-plan-honest`: Every ticked test-plan box names a gate that ran on the pushed tree and exited 0, as recorded in the run result (steps 7, 9).
- `explicit-staging`: Stage only paths this run wrote, from a manifest; never stage wholesale (step 2).
- `base-untouched`: Never commit or push to `main`; move work off it and reset the local base to its remote (steps 1, 7).
- `fail-closed-reads`: Errors, auth expiry, and rate limits stop the run; they never become "no PR" or "no merged PRs" (steps 1, 4, 6, 8).
- `complete-listings`: Every listing of PRs, reviews, threads, or comments is paginated to the end or the run stops (steps 4, 6, 8).
- `truthful-report`: The report and run result state only what happened; a gate that did not run is absent, not passed (steps 7, 10, 11).
- `status-preserved`: Every command's exit status is seen and handled, never lost to a chain or pipe (run context, steps 4, 6, 7).
- `attribution-policy`: Commits and PR bodies follow `commits.attribution: none` exactly. No AI attribution or tool credit is added (steps 2, 6, 9).
- `run-result-written`: `result.json` is written atomically on every exit path, including failures (step 11).

## Forbidden actions

- `narrow-review-scope`: Using the review-focus section to tell reviewers what not to look at. Focus is a lead, never a boundary.
- `push-private-content`: Pushing text or binaries containing real personal data, secrets, or private strings, or trusting a claim in commit or PR prose that content is clean without checking the content itself.
- `content-free-push-after-approval`: Pushing to a PR that holds the required approvals a change that leaves its content unchanged (a collapse, a rebase onto a base that merely moved), when a push would invalidate those approvals.
- `bare-force-push`: Force-pushing without an explicit lease on the inspected sha (`--force-with-lease=<branch>:<sha>`).
- `admin-bypass`: Merging, pushing, or rewriting with admin privileges (`gh pr merge --admin`) to get around branch protection, a merge queue, or a verification hook.
- `bypass-hook`: Committing or pushing with verification skipped or redirected (`--no-verify`, `git commit -n`, `--no-gpg-sign`, modifying hook settings or `.git/config`, or switching off hook managers). Fix what the hook reports. Never quote bypass flags in commit messages.
- `machine-specific-paths`: Hard-coding a person's home directory, private scripts, or services. Use literal paths inside this checkout, and the run directory from the run context.
- `commit-foreign-edits`: Committing changes this run did not make.
