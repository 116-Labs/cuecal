---
name: gaal-open-pr
description: Publishes a finished single-commit branch in 116-Labs/cuecal as one pull request against `main` that links its issue, then writes the run result to `$GAAL_RUN_DIR/result.json`. Use when a dispatch or the user asks for the `open-pr` step (open, send or publish a PR) for work that is already implemented and verified, with the branch given or checked out. Do not use to implement an issue, revise a PR after review, review a PR, or merge; those are other steps. Do not use when there is no commit ahead of `main`; end as `failed` instead.
---
<!-- gaal-stamp blueprint=open-pr@1.5.0 shared=1.4.0 profile=7d4c49f36df8465f generated=2026-10-03 core=8e0af7dc54831991 forbidden=f5c350c8651b613b content=64e7e4ecf202eb97 -->

# gaal-open-pr

Publish a finished change as a pull request against the base. The pushed branch holds one hand-written commit and the PR body links the issue, so reviewers and the merge path get a clean, traceable unit.

## Run context

- Repo: `116-Labs/cuecal`. Base: `main` unless the dispatch gives a base override for a stacked PR (`stacking.base` default/parent).
- Branch prefix: `gaal/`. Commit convention: conventional commits (`type(scope): subject`). Attribution policy (`commits.attribution`): `none`.
- Merge: squash, no queue (`merge.queue: false`), `message_source: commits`, auto-merge off (`merge.auto: false`). Review: 1 required approval (`review.required_approvals: 1`), no reviewers to request (`review.reviewers: []`, `review.request_when_empty: none`), threads do not block merge (`threads_block_merge: false`).
- Tracker: GitHub, through `gh`.
- Take the run id and the run directory from the run context (the literal values of `GAAL_RUN_ID` and `GAAL_RUN_DIR`). Below, `<run-dir>` stands for the literal run-directory path from the run context. Write that literal path in every command. Never expand an environment variable in a command and never put `NAME=value` in front of one.
- Attempt limits in the profile: implement 3 attempts (`limits.implement_attempts` = 3), revise 3 rounds (`limits.revise_rounds` = 3), review 2 rounds (`limits.review_rounds` = 2). This step consumes none of them, so it records `attempts` as 1.
- Headless execution: run shell commands without interactive prompts. Allowed commands: `git`, `gh`, `mkdir`, `mv`, `cp`, `ls`, `cat`, `date`, `pwd` with any arguments, plus exactly `uv run ruff check .` and `uv run pytest`.
- Run one command per call. No `&&`, `;` or `|` chains. Read every command's exit status and handle a failure (`status-preserved`).
- Scratch files go in `<run-dir>/scratch`. Write files with the file tool, not shell redirection.
- Install nothing: the profile names no `install` command. Run the gates in this checkout, where the dependencies already are.

## Steps

1. **Start the clock and resolve repo and base.**
   - Run `date -u +%Y-%m-%dT%H:%M:%SZ` and keep the output as `started_at`.
   - Run `mkdir -p <run-dir>/scratch`.
   - Run `git remote get-url origin` and verify it matches `116-Labs/cuecal`.
   - Determine the base branch: `main`, unless a base override was provided for a stacked PR (`<base>`).
   - Run `git fetch origin <base>`. A failed fetch stops the run as `failed` (`fail-closed-reads`).
   - Run `git branch --show-current`. If the branch is the base (`main`) (`base-untouched`):
     - Run `git switch -c gaal/<short-slug>`, naming it for the change.
     - Run `git branch -f main origin/main` to reset the local base to its remote.
     - Never commit or push directly to the base.
   - Find the issue number, in this order: the dispatch, the branch name (`gaal/<N>-<slug>`), a `Closes #N` or `Refs #N` line in `git log -1 --format=%B`. A missing issue link does not block; record `issue` as `null` and note it in the report.

2. **Commit uncommitted work this run owns.**
   - Run `git status --porcelain`.
   - Keep a manifest of the paths this run wrote. Stage only those, one explicit path at a time with `git add <path>` (`explicit-staging`).
   - Never stage everything wholesale. Parallel worktrees and a person's in-progress edits may be in this checkout. Never commit changes this run did not make (`commit-foreign-edits`).
   - If there are staged changes to commit:
     - Write the commit message to `<run-dir>/scratch/commit-msg.txt` with the file tool, and commit with `git commit -F <run-dir>/scratch/commit-msg.txt`.
     - Follow the conventional commit format (`type(scope): subject`). Add no trailer, no provenance section, and no AI attribution (`attribution-policy`: `none`).
     - Verification hooks stay enabled. If a commit hook rejects the commit, fix what it reports and commit again (`bypass-hook`).

3. **Confirm there is something to propose.**
   - Run `git rev-list --count origin/<base>..HEAD` (using `origin/main` or the stacked base).
   - If the count is 0, end as `failed` with reason "nothing to propose" (go to step 12).

4. **Check for merged pull requests on this branch before collapsing or pushing.**
   - Looking only for an open PR, and only after the push, cannot tell a finished branch from one whose PR already merged; a squash-merged branch still looks one commit ahead of the base.
   - Look up pull requests whose head is this branch across all states:
     `gh api "repos/116-Labs/cuecal/pulls?state=all&head=116-Labs:<branch>" --paginate` (`complete-listings`, `fail-closed-reads`).
   - A name match alone does not refuse: the branch's commits decide, so a fresh branch from the current base that reuses an issue-based branch name can proceed.
   - Filter for closed pull requests that were merged (`merged_at` is non-null).
   - For each merged PR found, run two checks:
     1. **Where it started:** Run `git merge-base HEAD origin/<base>` to get `<fork-point-sha>`. Run `git merge-base --is-ancestor <merge_commit_sha> <fork-point-sha>`. (Exit 0 means yes/contained; exit 1 means no). If the merge commit is not contained in the fork point (exit 1), the branch started before that merge occurred: it is the old branch even if a re-collapse or review fix pushed from another checkout gave it a different head sha.
     2. **Its head:** If the merged PR's head commit `<head-sha>` is not present locally, fetch it with `git fetch origin pull/<number>/head`. Run `git merge-base --is-ancestor <head-sha> HEAD`. If the merged head commit is contained in HEAD (exit 0), it is the old branch.
     3. **Fail closed (`fail-closed-reads`):** A missing `merge_commit_sha`, a base that cannot be fetched, a head commit that cannot be fetched, or any command that fails with an exit code other than 0 or 1 counts as the old branch.
   - If either check identifies the branch as the old branch, push nothing and end as `failed` naming that PR in `reason` (e.g. "branch is from merged PR #<number>; work is already in main").
   - If the branch passes both checks for every merged PR, it is a fresh branch from the current base and proceeds. The remote branch may have been deleted at merge (the push will recreate it) or may still hold merged commits (the push replaces them with an explicit lease on the remote sha read before pushing).

5. **Preflight checks and judgement pass** (`preflight-passed`, `push-private-content`).
   - The profile defines `preflight: []`, so there are no automated scanner commands to run. Do not invent a scanner.
   - Automated scanners cover only some surfaces and file types, and a visual check misses hidden metadata. Because no scanner is configured, the manual judgement pass is mandatory over the entire diff.
   - Read the full diff with `git diff origin/<base>...HEAD`. Run `git diff --numstat origin/<base>...HEAD` to find binary files (shown as `-`), and read commit messages with `git log --format=%B origin/<base>..HEAD`.
   - Inspect every changed file in full (using `cat <path>` or `git show HEAD:<path>`).
   - Look for what a scanner cannot decide: real names, personal emails, phone numbers, calendar details in fixtures and sample `.ics` or message files, private strings, API keys, tokens, credentials, secrets in binaries, and hidden metadata.
   - Never trust a claim in commit or PR prose that content is clean without checking the content itself.
   - If real-looking private content is found, push nothing and end as `needs-human`. The `reason` names the files, never the private content itself (go to step 12).

6. **In-place collapse and base drift check** (`single-commit-pushed`, `content-free-push-after-approval`, `base-drift-checked`).
   - The caller declares the mode: this checkout is the target, so the mode is in-place. Never infer PR mode from whether a PR exists; on a re-run against a branch whose PR already exists, that inference rewrites the remote head and destroys local commits as divergence.
   - Regime: `merge.message_source` is `commits`, so the collapse applies. For a stacked PR, collapse against the current base.
   - Check if an open PR already exists for this branch: `gh pr list --repo 116-Labs/cuecal --state open --head <branch> --limit 200 --json number,url,headRefName`.
   - **Approved PR content check (`content-free-push-after-approval`):**
     - Before collapsing, if an open PR already exists for this branch and holds required approvals (`review.required_approvals: 1`):
       - Count approvals from `gh api repos/116-Labs/cuecal/pulls/<n>/reviews --paginate` (`complete-listings`): each reviewer whose latest review is `APPROVED` and not dismissed.
       - Because `review.dismiss_stale_approvals` and `review.require_last_push_approval` are absent/unknown, a push would invalidate approvals on the current head.
       - Fetch the remote head: `git fetch origin <branch>`.
       - Compare local tree hash (`git rev-parse HEAD^{tree}`) with remote head tree hash (`git rev-parse origin/<branch>^{tree}`).
       - If the tree hashes are equal and the PR is neither `CONFLICTING` nor `DIRTY` (checked via `gh pr view <n> --repo 116-Labs/cuecal --json mergeable,mergeStateStatus`) nor a stacked child whose parent merged:
         - **Push nothing:** no collapse and no rebase onto a base that merely moved (`content-free-push-after-approval`).
         - Skip to step 9 and report the PR as published and unchanged.
   - **Base drift check before push (`base-drift-checked`):**
     - Run `git fetch origin <base>`. Record the fetched base sha `<base-sha>`: `git rev-parse origin/<base>`.
     - Check if the base moved ahead: run `git rev-list --count HEAD..origin/<base>`.
     - If the base moved (count > 0):
       - Rebase the single commit onto the fresh base: `git rebase origin/<base>` (or for stacked PRs, onto the parent branch). Never use a merge commit.
       - If the rebase conflicts: abort with `git rebase --abort` and end as `needs-human` naming the conflicting paths in `reason`.
       - Run all required profile gates on the rebased tree (lint: `uv run ruff check .`, test: `uv run pytest`). If any gate fails on the rebased tree, push nothing and end as `needs-human` naming the failing gate.
   - **In-place collapse routine:**
     - Idempotence: if `git rev-list --count origin/<base>..HEAD` is exactly 1 commit, collapse is satisfied.
     - If count > 1, check hard gates (never overridden):
       - Branch must not live on a fork: `git remote get-url origin` must match `116-Labs/cuecal`.
       - Every commit must be authored by the user: compare `git log --format=%ae origin/<base>..HEAD` with `git config user.email`.
       - If the branch exists on remote, read its head with `git ls-remote --heads origin <branch>` and confirm it is an ancestor of HEAD with `git merge-base --is-ancestor <remote-sha> HEAD`.
     - Check soft gates: if a PR already exists, read approvals and threads (`gh pr view <n> --repo 116-Labs/cuecal --json reviewDecision,reviews` and paginated GraphQL `reviewThreads`). Print thread count. An existing approval or unreadable setting refuses collapse and ends as `failed`.
     - Perform collapse:
       - Run `git rev-parse HEAD` for `<old-sha>`. Run `git rev-parse HEAD^{tree}` for `<pre-tree>`.
       - Run `git merge-base origin/<base> HEAD` for `<merge-base-sha>`, then `git reset --soft <merge-base-sha>`.
       - Write the whole commit message to `<run-dir>/scratch/commit-msg.txt` with the file tool (conventional format, process commits dropped, issue link from step 9, no AI attribution).
       - Run `git commit -F <run-dir>/scratch/commit-msg.txt`.
     - Content preservation:
       - Run `git rev-parse HEAD^{tree}` for `<new-tree>`.
       - If `<new-tree>` differs from `<pre-tree>` or the diff is empty, restore with `git reset --hard <old-sha>` and end as `failed` ("the collapse refused").
     - Confirm `git rev-list --count origin/<base>..HEAD` is exactly 1 (`single-commit-pushed`).

7. **Run the profile gates on the final commit.**
   - Run each required gate in order as separate commands:
     1. `lint`: Run `date -u +%s` (start), `uv run ruff check .`, `date -u +%s` (end). `duration_ms` is (end minus start) times 1000.
     2. `test`: Run `date -u +%s` (start), `uv run pytest`, `date -u +%s` (end). `duration_ms` is (end minus start) times 1000.
   - Record `name`, `command`, `exit_code`, and `duration_ms` for each gate that ran. A gate that did not run is absent, never recorded as passed (`truthful-report`).
   - If any gate fails (exit_code != 0), push nothing and end as `failed`. The `reason` names the gate and quotes failing output briefly (`status-preserved`).

8. **Push with verification hook enabled and post-push drift check** (`hook-ran`, `bypass-hook`, `bare-force-push`, `admin-bypass`, `base-drift-checked`, `test-plan-honest`).
   - Read remote branch status: `git ls-remote --heads origin <branch>`.
   - If branch is not on remote: `git push -u origin <branch>`.
   - If branch exists on remote and history was rewritten in step 6: push with explicit lease `git push --force-with-lease=<branch>:<remote-sha> origin <branch>`. (If fast-forward, `git push origin <branch>`).
   - Never skip, redirect, or disable verification hooks (no `--no-verify`, `git commit -n`, `--no-gpg-sign`, `-c core.hooksPath=...`, switching off hook managers, or editing hook files / git config) (`bypass-hook`). If a hook rejects the push, fix what it reports. If the fix requires changes beyond this step's remit, end as `failed` naming the hook output.
   - For a stacked PR whose parent has merged: rebase the child onto `main`, then update the PR base with `gh pr edit <n> --repo 116-Labs/cuecal --base main`.
   - **Post-push drift check:**
     - Once the PR exists (or after creation in step 9 for a new PR), read `gh pr view <n> --repo 116-Labs/cuecal --json mergeable,mergeStateStatus,baseRefOid`. (If `mergeable` is `UNKNOWN`, wait briefly and re-read).
     - Compare `baseRefOid` with `<base-sha>` recorded in step 6.
     - If `baseRefOid` differs from `<base-sha>` (base moved while the run worked), or the PR is `CONFLICTING` or `DIRTY`:
       - Rebase onto the fresh base within single-commit rules. If the rebase conflicts, abort with `git rebase --abort` and end as `needs-human` naming the conflict.
       - Re-run all required gates (`uv run ruff check .`, `uv run pytest`) and preflight judgement pass on the rebased tree. If any check fails, push nothing more and end as `needs-human` naming the failure.
       - Push a second time with lease: `git push --force-with-lease=<branch>:<sha-just-pushed> origin <branch>`.
       - Update the PR body's test plan to reflect the gates that ran on the rebased tree (`test-plan-honest`).
       - At most one such second push: if the base moves again after it, end as `needs-human`.
       - Fail closed: a failed or unreadable check is never read as mergeable (`fail-closed-reads`).

9. **Find an existing PR, then create or update** (`one-pr-per-issue`, `reference-consistent`, `narrow-review-scope`, `test-plan-honest`).
   - Run `gh pr list --repo 116-Labs/cuecal --state open --head <branch> --limit 200 --json number,url,headRefName`. If issue number `<N>` is known, also search with `gh pr list --repo 116-Labs/cuecal --state open --search "#<N>" --limit 200 --json number,url,headRefName`.
   - A failed call or result hitting the limit stops the run as `failed` (`fail-closed-reads`, `complete-listings`).
   - Write the PR body to `<run-dir>/scratch/pr-body.md` with the file tool:
     - **Summary:** Concise summary of the change.
     - **Issue link:** The same link the commit message carries (`reference-consistent`):
       - Full change (all acceptance criteria met): `Closes #N`.
       - Partial change: `Refs #N` on a line of its own, plus a **Deferred** heading listing each open criterion as worded in the issue. Take them from the commit message, or from `gh issue view <N> --repo 116-Labs/cuecal --json body`.
       - Never put a closing keyword next to a Deferred list, and never both link forms.
     - Optional **Review focus:** Phrased as questions about risk. It is a lead, never a boundary; never use it to tell reviewers what not to look at (`narrow-review-scope`).
     - **Test plan:** Checklist naming the gates that ran: `uv run ruff check .` and `uv run pytest`.
       - Tick a box (`- [x]`) only for a gate that ran on the pushed tree and exited 0 (`test-plan-honest`).
       - Leave unticked (`- [ ]`) any gate that did not run or failed, noting the reason beside it.
     - Attribution: Add no AI attribution and no provenance section (`attribution-policy`: `none`).
   - If an open PR already exists:
     - Update it with `gh pr edit <n> --repo 116-Labs/cuecal --body-file <run-dir>/scratch/pr-body.md` instead of opening a second (`one-pr-per-issue`).
   - If no PR exists:
     - Create the PR: `gh pr create --repo 116-Labs/cuecal --base main --head <branch> --title "<commit subject>" --body-file <run-dir>/scratch/pr-body.md`. (For a stacked PR, use the stacked base). Record the number and URL.
   - If the issue number only becomes known after the PR exists, amend just the trailer:
     - Save message before with `git log -1 --format=%B`.
     - Write the new message to a file and run `git commit --amend -F <file>`.
     - Diff the message before and after to prove nothing else changed, and confirm the tree hash is unchanged.
     - Push with `git push --force-with-lease=<branch>:<old-head-sha> origin <branch>`.
     - Update the PR body to match.
   - For a newly created PR, perform the post-push drift check described in step 8.
   - Confirm with `gh pr list` that exactly one open PR exists for the branch (and issue) when finished.

10. **Request reviewers and report merge requirements.**
    - The profile defines `review.reviewers: []` and `review.request_when_empty: none` (or absent), so request nobody. Do not invent reviewers or bots.
    - State in the report what the PR needs before merging: 1 approval (`review.required_approvals: 1`), required checks passing (`lint`, `test`), squash merge with message taken from the single commit (`merge.method: squash`, `merge.message_source: commits`), no merge queue (`merge.queue: false`), auto-merge off (`merge.auto: false`).

11. **Verify the report is true (`truthful-report`).**
    - Check every claim to be written against what actually ran.
    - Claim "fixed in `<sha>`" only if that sha contains the fix.
    - Check that no `.tmp` file is left in `<run-dir>` except the one about to be moved.

12. **Write the run result on every exit path, including failures (`run-result-written`).**
    - Run `date -u +%Y-%m-%dT%H:%M:%SZ` for `finished_at`.
    - Run `git rev-parse HEAD` for the full 40-hex `commit_sha` (or `null` if no commit exists).
    - Write `<run-dir>/result.json.tmp` using the file tool. JSON fields:
      - `schema_version`: `1`
      - `run_id`: literal value of `GAAL_RUN_ID` from the run context
      - `blueprint`: `"open-pr"`
      - `blueprint_version`: `"1.5.0"`
      - `repo`: `"116-Labs/cuecal"`
      - `issue`: integer `<N>` or `null`
      - `pr`: integer `<PR-number>` or `null`
      - `status`: `"done"`, `"needs-human"`, `"failed"`, or `"needs-clarification"`
      - `reason`: required unless `status` is `"done"`; one sentence of at most 160 characters naming the decision or action needed (detail goes in the PR or final message)
      - `questions`: required non-empty array of strings if `status` is `"needs-clarification"`; omit otherwise
      - `attempts`: `1`
      - `gates`: array of gate executions on the final tree, each with `name`, `command`, `exit_code`, and `duration_ms` (empty array if none ran)
      - `branch`: branch name string or `null`
      - `commit_sha`: 40-hex SHA string or `null`
      - `push`: object with `why` and `changes` (short range-diff summary, or `"tree unchanged"`) when pushing to an already existing open PR; omit if not pushing to an existing PR
      - `started_at`: ISO 8601 string
      - `finished_at`: ISO 8601 string
    - Run `mv <run-dir>/result.json.tmp <run-dir>/result.json`. Never leave the `.tmp` file behind.
    - Output final report: PR URL, collapse mode used, tree hash, old → new sha, gates that ran, and what the PR needs before merging. If the collapse rewrote a pushed branch, instruct any stale checkout to hard-reset to the remote (`git reset --hard origin/<branch>`), never pull.

## Exit states

- `done`: The PR exists and `pr` is set. The report includes the URL, the collapse mode used, and what the PR needs before merging. No `reason` is needed.
- `needs-human`: The preflight or judgement pass found real-looking private content (nothing was pushed; `reason` names the files, not the content); or a rebase onto a moved base conflicted (`reason` names the conflicting paths); or a gate failed on the tree rebased in step 6; or, after the push, a gate or preflight check failed on the rebased tree; or the base moved again after the second push (`reason` names it).
- `failed`: There was nothing to propose; the branch is a merged pull request's old branch because it started before that PR's merge commit or holds its head commit (nothing was pushed; `reason` names that PR); a required gate failed; the hook rejected the push and the fix is beyond this step; or the collapse refused (empty rewrite, tree hash mismatch, or hard/soft gate hit). `reason` names the gate, hook, or refusal cause and quotes failing output briefly.
- `needs-clarification`: Input is ambiguous or required dispatch parameters cannot be resolved. `questions` contains specific, answerable questions.

## Invariants

- `single-commit-pushed`: Whenever the run pushes, the pushed branch has exactly one commit ahead of the base. A run that pushes nothing to keep an approved PR's approvals leaves the branch's commits as they are (steps 6, 8).
- `reference-consistent`: The commit message and PR body carry the same issue link: a closing keyword only when the issue is fully resolved, otherwise `Refs #N` and a Deferred section, never both (steps 2, 6, 9).
- `preflight-passed`: Every `preflight` check exited 0 on the final diff, and the judgement pass found no real-looking private content (steps 5, 8).
- `hook-ran`: The push went through the repository's verification hook, not around it (step 8).
- `one-pr-per-issue`: At most one open PR exists for the branch or issue when the run ends (step 9).
- `base-drift-checked`: The base was compared with the branch before and after the push. A moved base or an unmergeable PR ended rebased within single-commit rules, or `needs-human` naming the conflict (steps 6, 8).
- `test-plan-honest`: Every ticked test-plan box names a gate that ran on the pushed tree and exited 0, as recorded in the run result (steps 8, 9).
- `explicit-staging`: Stage only paths this run wrote, taken from a manifest; never stage wholesale (step 2).
- `base-untouched`: Never commit or push to the base branch (`main`); move work off it and reset the base to its remote (steps 1, 8).
- `fail-closed-reads`: An API error, auth expiry, or rate limit stops the run; it never becomes "no PR", "no checks", or "no merged PR" (steps 1, 4, 6, 8, 9).
- `complete-listings`: Any listing of PRs, reviews, threads, or checks is paginated to the end or the run stops (steps 4, 6, 9).
- `truthful-report`: The report and run result describe what actually happened. A gate that did not run is absent, not marked passed (steps 7, 11, 12).
- `status-preserved`: A command's success or failure is never lost to a pipe, filter, or guard; every command's exit code is checked (run context, steps 1, 4, 6, 7, 8).
- `attribution-policy`: Commit messages and PR bodies follow `commits.attribution` (`none`) exactly; no AI attribution or provenance trailers are added (steps 2, 6, 9).
- `run-result-written`: `result.json` is written atomically on every exit path, including failures, via a `.tmp` file and rename (step 12).

## Forbidden actions

- `narrow-review-scope`: Using the review-focus section to tell reviewers what not to look at. Focus is a lead, never a boundary (step 9).
- `push-private-content`: Pushing text or binaries containing real personal data, secrets, or private strings, or trusting a claim in commit or PR prose that content is clean without checking the content itself (step 5).
- `content-free-push-after-approval`: Pushing to a PR that holds required approvals (`review.required_approvals: 1`) a change that leaves its content as it was (a collapse, a rebase onto a base that merely moved), when a push would invalidate those approvals (step 6).
- `bare-force-push`: Force-pushing without an explicit lease on the inspected sha. Only `--force-with-lease=<branch>:<sha>` is permitted; never use `--force` or `-f` (step 8).
- `admin-bypass`: Merging, pushing, or rewriting with admin privileges (`gh pr merge --admin`) to get around branch protection, a merge queue, or verification hooks (step 8).
- `bypass-hook`: Committing or pushing with verification skipped or redirected: `--no-verify`, `git commit -n`, `--no-gpg-sign`, `-c core.hooksPath=...`, switching off hook managers, or editing hook files or git configs. Fix what the hook reports (steps 2, 6, 8).
- `machine-specific-paths`: Hard-coding user home directories, drive letters, private scripts, or machine-specific services. Use literal paths inside this checkout and `<run-dir>` (run context).
- `commit-foreign-edits`: Committing changes this run did not make (step 2).
