---
name: gaal-revise-pr
description: Revises an open pull request in 116-Labs/cuecal after review. It addresses every unresolved review thread, every actionable request in a review body, and every request made on the linked issue since the PR opened with a verified code change or a reasoned reply, runs the profile gates (`uv run ruff check .`, `uv run pytest`), checks for base drift, pushes once per round, optionally collapses to a single commit when all threads resolve unless approvals would be invalidated, replies to and resolves threads by rule, keeps the PR description true to the new head, and writes the run result to `<run-dir>/result.json`. Use when a dispatch hands you a repo and PR number and asks for the `revise-pr` step, including imported feedback from another PR, a comment URL, or free-text notes. Do not use to open a PR, implement an issue, review a PR, or merge; those are other steps. Do not use when no PR can be determined; end as `needs-clarification` instead of guessing.
---
<!-- gaal-stamp blueprint=revise-pr@1.7.0 shared=1.4.0 profile=833de6ae33df6d68 generated=2026-10-04 core=b92499e6abdd3fda forbidden=df8e4e73381d2451 content=00da13c8e83f0dcc -->

# gaal-revise-pr

Close the review loop on an open pull request in `116-Labs/cuecal`. Every unresolved review thread, every actionable request in a review body, and every request made on the linked issue since the PR opened gets either a verified code change or a reasoned reply. The branch is pushed once per round with green profile gates (`uv run ruff check .` and `uv run pytest`), base drift is checked and handled before pushing, threads end in a state that matches what was actually done, the PR description accurately reflects the pushed head, and review is re-requested.

## Run context

- Dispatch inputs: repository `116-Labs/cuecal`, PR number `<pr>`, and optional imported feedback (threads from another PR, a comment URL, or free-text notes). If no PR can be determined, end as `needs-clarification` without guessing.
- Profile configuration for `116-Labs/cuecal`:
  - Default branch: `main`. Tracker: GitHub via `gh`. Branch prefix: `gaal/`.
  - Profile gates: `lint` (`uv run ruff check .`, required) and `test` (`uv run pytest`, required).
  - Preflight checks: none (`preflight: []`).
  - Install commands: none (`install` names no commands). Install nothing; use the checkout's existing install and run all gates directly in the checkout. A throwaway worktree has no install, so never run gates in a worktree.
  - Commit convention: conventional commits (`type(scope): subject`). Attribution policy (`commits.attribution`): `none`. Do not add AI attribution, model provenance, or `Co-Authored-By` lines (`attribution-policy`).
  - Merge regime: squash merge, no merge queue (`merge.queue: false`), `message_source: commits`, auto-merge disabled (`merge.auto: false`).
  - Review policy: `review.required_approvals: 1`, open threads do not block merge (`review.threads_block_merge: false`), `review.reviewers: []`. Branch protection facts `dismiss_stale_approvals` and `require_last_push_approval` are absent (treated as unknown/true: only approvals on the current head count, and a push invalidates them).
  - Stacking: default base is `main`. For stacked PRs whose parent has merged, rebase the child onto `main` and retarget with `gh pr edit <pr> --repo 116-Labs/cuecal --base main`.
  - Attempt limits: revise rounds limit is 3 (`limits.revise_rounds: 3`; `bounded-rounds`). Profile also defines implement attempts 3 (`limits.implement_attempts: 3`) and review rounds 2 (`limits.review_rounds: 2`).
  - Communications: GitHub comments enabled (`comms.github_comments: true`), maintainer channels empty.
- Headless execution rules:
  - The run executes shell commands headlessly with no interactive prompts. Commands outside the allowlist are refused. Allowed commands: `git`, `gh`, `mkdir`, `mv`, `cp`, `ls`, `cat`, `date`, `pwd` with any arguments, plus exactly `uv run ruff check .` and `uv run pytest`.
  - Run one command per call. Never chain commands with `&&`, `;`, or `|`.
  - Never use shell variables (`$VAR`, `${VAR}`, `$(...)`, backticks) or `NAME=value` prefixes. In commands, `<run-dir>` stands for the literal path from `GAAL_RUN_DIR`, and `<run-id>` stands for the literal value of `GAAL_RUN_ID` from the run context. Write literal paths without machine-specific prefixes (`machine-specific-paths`).
  - Write files with file tools, never shell redirection. Scratch files and throwaway worktrees live in `<run-dir>/scratch` and `<run-dir>/worktree`, never `/tmp`. Pass file paths to tools (`git commit -F <file>`, `--body-file <file>`, `-F body=@<file>`).
  - Read timestamps with `date -u +%Y-%m-%dT%H:%M:%SZ`. Time gates by running `date -u +%s` immediately before and after the gate command; duration in milliseconds is `(end - start) * 1000`.
  - Verify every command's exit code; never hide failure under pipes or guards (`status-preserved`).
  - Atomic result writing: write `<run-dir>/result.json.tmp` then rename via `mv <run-dir>/result.json.tmp <run-dir>/result.json` (`run-result-written`).

## Steps

### 1. Start the clock, create scratch directory, and initialize records

1. Run a shell command to read the start timestamp: `date -u +%Y-%m-%dT%H:%M:%SZ`. Record it as `started_at`.
2. Run a shell command to create the scratch directory: `mkdir -p <run-dir>/scratch`.
3. Initialize the round attempt counter at 0 and an empty list for gate execution records.
4. Keep a manifest of all file paths written or modified by this run. Stage only paths from the manifest (`explicit-staging`). Never stage foreign or pre-existing modifications wholesale (`commit-foreign-edits`).
5. Note: Every exit path from here onward writes `<run-dir>/result.json` atomically in step 16 (`run-result-written`).

### 2. Identify and confirm the PR

1. If no PR number is provided in the dispatch and none can be determined from context, do not guess. End as `needs-clarification` with questions asking for the PR number.
2. Run a shell command to read PR metadata: `gh pr view <pr> --repo 116-Labs/cuecal --json number,state,body,headRefName,headRefOid,baseRefName,isCrossRepository,commits,closingIssuesReferences,createdAt`.
3. Handle API failures: If the call fails (auth error, rate limit, network failure), stop and end as `failed` naming this step (`fail-closed-reads`, `status-preserved`). Never interpret an API failure as "no PR" or "no comments".
4. Check PR state: If `state` is not `OPEN` (e.g. `CLOSED` or `MERGED`), end as `failed` with reason "PR is not open".
5. Check repository ownership: If `isCrossRepository` is true, the branch lives on a fork and cannot be pushed to. End as `needs-human` with reason "PR branch lives on a fork".
6. Target branch isolation: Code changes land only on this PR's branch (`target-branch-only`). Never commit or push to `main` (`base-untouched`). If `headRefName` is `main`, end as `failed`.
7. Record `<branch>` (`headRefName`), `<head-sha>` (`headRefOid`), `<pr-created-at>` (`createdAt`), and the base branch (default `main`).
8. Identify linked issues: Check `closingIssuesReferences`. If empty, apply the shared issue-link rule reading order: check the PR body, then each commit message (`git log --format=%B` after fetching). A line with a closing keyword (`Closes`, `Fixes`, `Resolves`) takes precedence over a `Refs #N` line. An issue named in the dispatch takes precedence. Extract only issue numbers; do not bring the entire issue text into context unnecessarily. If no issue is linked, record `issue` as `null`.

### 3. Check out the PR head

1. Run a shell command to check working directory status: `git status --porcelain`. If foreign uncommitted changes exist that this run did not make, leave them untouched (`commit-foreign-edits`). If they prevent checkout or are of unknown origin, end as `needs-human`.
2. Run shell commands to fetch and switch to the branch:
   - `git fetch origin <branch>`
   - `git checkout <branch>`
3. If the local branch has unpushed commits ahead of `origin/<branch>`, back them up to a branch ref (`git branch backup/<branch>-<timestamp>`) and verify the ref before resetting. Then run `git reset --hard origin/<branch>`. If local uncommitted edits of unknown origin exist, stop and end as `needs-human`.
4. Confirm local HEAD matches remote: Run `git rev-parse HEAD` and verify it equals `<head-sha>`. If it does not, re-read the PR; the remote head moved.
5. Dependency installation: The profile specifies no `install` commands. Install nothing; use the checkout's existing environment.

### 4. List every unresolved review thread

1. Query all review threads via GraphQL to expose resolution state and thread IDs. Write queries with literal values (no `$` variables) and paginate to the end (`complete-listings`, `fail-closed-reads`):
   - First page:
     `gh api graphql --raw-field query='query { repository(owner: "116-Labs", name: "cuecal") { pullRequest(number: <pr>) { reviewThreads(first: 100) { pageInfo { hasNextPage endCursor } nodes { id isResolved isOutdated path line comments(first: 50) { nodes { databaseId author { login } body url } } } } } } }'`
   - While `hasNextPage` is true, repeat with `reviewThreads(first: 100, after: "<endCursor>")`.
2. Filter for unresolved threads (`isResolved: false`).
3. Record each unresolved thread's `id`, path, line, and the `databaseId` of its first comment now, before any history rewrite (rewriting history marks threads outdated; capturing thread IDs first allows replying and resolving through thread relations).
4. If any thread contains more than 50 comments, paginate its comments to ensure no truncated data is trusted (`complete-listings`).
5. Tag each item with source `this-pr`.

### 5. List reviews and collect actionable review-body requests

1. Run a shell command to list all reviews on the PR: `gh api repos/116-Labs/cuecal/pulls/<pr>/reviews --paginate` (`complete-listings`).
2. Read the body of the latest review from each reviewer, plus any earlier review body whose requests were never answered.
3. Review bodies do not have a thread ID. Extract each actionable request (a change asked for, or a finding listed only in the review body) as an item tagged `review-body`. Skip pure verdicts, praise, and requests already answered by a later commit or comment. Reviewers sometimes list real findings only in review bodies; these must be answered in a PR comment.
4. Run a shell command to list existing PR issue-level comments to verify which requests were already answered: `gh api repos/116-Labs/cuecal/issues/<pr>/comments --paginate`.

### 6. Read linked issue requests since the PR opened

Maintainers often ask for scope adjustments or additional criteria on the issue itself ("also handle X" or updated issue bodies). Read both to prevent converging on an outdated scope.

1. For each linked issue identified in step 2:
   - Read the issue body and comments: `gh issue view <issue> --repo 116-Labs/cuecal --json body,createdAt,comments` and `gh api repos/116-Labs/cuecal/issues/<issue>/comments --paginate` (`complete-listings`).
   - Read body edits via GraphQL:
     `gh api graphql --raw-field query='query { repository(owner: "116-Labs", name: "cuecal") { issue(number: <issue>) { userContentEdits(first: 50) { nodes { editedAt editor { login } diff } } } } }'`
   - Determine the request cutoff time: Note `<pr-created-at>` and check for Gaal's newest completed implement run comment on the issue (`Gaal finished implement …: done.`). Requests count from the earlier of `<pr-created-at>` and that comment's creation time.
   - Collect requests: Every comment created after the cutoff by the issue's author or a maintainer (repository admin), and every body edit since the cutoff by either of them.
   - Filter out non-requests:
     - Skip comments carrying a `<!-- gaal:` marker.
     - Skip body edits where every added or removed line falls strictly between `<!-- gaal:plan-drift -->` and `<!-- /gaal:plan-drift -->` marker lines (implement's internal plan record). If an edit modifies any line outside that section (e.g. maintainer text added after it), it is a valid request.
     - Skip bot comments and bot edits.
     - Skip comments that ask for nothing (status updates, greetings).
     - Skip requests that an existing PR comment already answered.
   - Each remaining actionable request (a requested change or a modified/added criterion) becomes an item tagged `issue-request` (`issue-requests-answered`).

### 7. Process and re-verify imported feedback

1. Supported import forms:
   - **Another PR's threads:** Read using GraphQL as in step 4 with that PR's number. Tag items as `import`.
   - **A comment URL:** Check its shape before extracting IDs. A `#discussion_r<id>` URL is a review comment with a thread. A `#issuecomment-<id>` URL is an issue-level comment without a thread; treat it as a `review-body`-style item answered in a PR comment.
   - **Free-text notes:** Each distinct request becomes an item tagged `import`.
2. **Re-verify each imported item against this branch:**
   - Inspect the code and verify with existing gates. Classify each as *reproduces*, *partly applies*, or *does not apply*.
   - Never apply an imported finding that does not reproduce on this branch (`apply-unreproduced-import`). Answer non-reproducing items with the reason instead.

### 8. Decide each item

For every item (`this-pr` thread, `review-body`, `issue-request`, `import`), choose one decision:
- **fix**: Make a code or documentation change on this branch.
- **answer**: The item is a question or requires technical clarification.
- **defer**: Under the shared follow-up bar, file a follow-up issue first only for a user-visible defect outside the diff that reproduces on `main`: run a shell command `gh issue create --repo 116-Labs/cuecal --title <title> --body-file <run-dir>/scratch/<file>.md` (filed unassigned and without milestone so it lands in backlog). Then request agreement on the thread. A deferral without a filed issue or agreement is a pushback in disguise (`resolve-unagreed-deferral`). Note that when open threads block merge, an agreed deferral resolves while a pushback blocks.
- **push back**: Disagree with technical rationale. Pushbacks remain open for the reviewer (`resolve-pushback`).
- Clarification check: If any request is so ambiguous that any fix would be a guess, stop and end as `needs-clarification` with specific `questions` quoting the thread.
- Note for `review-body` and `issue-request`: These items have no thread to record agreement, so deferrals are not marked resolved and their replies name the follow-up issue. An `issue-request` that widens scope beyond what this PR can reasonably carry should be deferred under the follow-up bar or answered with reasons.

### 9. Make all fixes

1. Edit files using the file tool. Keep changes minimal and focused on addressing the decided items.
2. Add every modified or created path to the manifest.
3. For imported items, fixes land only on this PR's branch (`target-branch-only`); the reply will name where it landed.
4. Complete all fixes for the round before running gates or committing.

### 10. Run profile gates and handle failures

1. Run each profile gate in order on the checkout tree as separate shell commands:
   - Gate `lint`:
     - Run `date -u +%s` (start)
     - Run `uv run ruff check .`
     - Run `date -u +%s` (end) -> calculate `duration_ms` = (end - start) * 1000
   - Gate `test`:
     - Run `date -u +%s` (start)
     - Run `uv run pytest`
     - Run `date -u +%s` (end) -> calculate `duration_ms` = (end - start) * 1000
2. Record gate `name`, exact `command`, `exit_code`, and `duration_ms`. Only record gates that actually ran (`truthful-report`, `status-preserved`).
3. If any required gate fails:
   - Fix the root cause in code using the file tool, update the manifest, and re-run all gates from the beginning.
   - Increment the attempt counter. Each full pass of both gates after fixes is one round.
   - When the round limit of 3 (`limits.revise_rounds: 3`) is reached with red gates, stop without pushing and end as `needs-human` (`bounded-rounds`). If a gate failure traces to code this PR did not touch, note it as pre-existing.
   - Never push a branch with failing required gates (`push-red`, `gates-green-before-push`).

### 11. Commit fixes, check base drift, and push once

The fix push must land before a collapse that reads the remote head, or the collapse ships without the fix.

1. If no code changes were made in this round:
   - Skip creating a fixup commit and skip pushing. `commit_sha` remains the unchanged head sha. Proceed to step 12.
2. If code changes were made:
   - Stage manifest paths explicitly: `git add <path1> <path2> ...` (`explicit-staging`). Never use `git add -A`, `git add .`, or `git commit -a`.
   - Run `git status --porcelain` to confirm no unintended changes are staged.
   - Write commit message to `<run-dir>/scratch/commit-msg.txt` with the file tool using conventional format: `fix(scope): address review feedback`. Attribution policy is `none` (`attribution-policy`): add no AI attribution or co-author lines.
   - Run shell command to commit: `git commit -F <run-dir>/scratch/commit-msg.txt`. Hooks must remain enabled. If a hook rejects the commit, fix what it reports and commit again; never use `--no-verify`, `git commit -n`, `--no-gpg-sign`, or change hook configurations (`bypass-hook`). If the hook failure is beyond this run, end as `failed`.
   - Record the fix commit sha: `git rev-parse HEAD`.
3. **Check base drift before pushing (`base-drift-checked`):**
   - Run `git fetch origin main` (or the base branch `<base>`).
   - Run `gh pr view <pr> --repo 116-Labs/cuecal --json mergeable,mergeStateStatus,baseRefOid`. (If `mergeable` is `UNKNOWN`, wait briefly and re-query).
   - Determine if rebase is required:
     - Rebase only if the PR is `CONFLICTING` or `DIRTY`, or `mergeStateStatus` is `BEHIND` (GitHub reports this when the base requires branches to be up to date before merging; never read branch protection for this), or if this is a stacked PR whose parent has merged.
     - Do NOT rebase if the base merely moved while the PR remains `MERGEABLE` and not `BEHIND`: rebasing rewrites history that reviewers must range-diff.
   - If rebase is required:
     - Ensure thread IDs were captured (step 4).
     - Record tree hash before rebase: `git rev-parse HEAD^{tree}`.
     - For a stacked PR whose parent merged: retarget base to `main` via `gh pr edit <pr> --repo 116-Labs/cuecal --base main` and rebase onto `origin/main`.
     - Otherwise, rebase onto `origin/main` (e.g. `git rebase origin/main`), keeping commits as they are (no merge commits).
     - If rebase conflicts occur: abort rebase with `git rebase --abort` and end as `needs-human` naming the conflicting paths.
     - Compare tree identity after rebase: record `git rev-parse HEAD^{tree}`. If tree hashes differ, run `git range-diff <old-base>..<old-head> origin/main..HEAD` to check that the PR's own changes survived (commits paired `=`). Record `tree unchanged` if trees match, or the range-diff summary if they differ (for the `push` field in result.json; `push-explained`).
     - Re-run all profile gates (`uv run ruff check .` and `uv run pytest`) on the rebased tree. If any gate fails on the rebased tree, end as `needs-human` naming the gate and base sha, with nothing pushed (base disagreement is a human call).
4. **Push once per round (`one-push-per-round`, `piecemeal-push`):**
   - Push with explicit lease on inspected sha: `git push origin HEAD:<branch> --force-with-lease=<branch>:<inspected-sha>` (or `git push origin <branch>` if fast-forward; never bare force-push: `bare-force-push`).
   - Check PR mergeability after push: Run `gh pr view <pr> --repo 116-Labs/cuecal --json mergeable,mergeStateStatus` (wait briefly if `UNKNOWN`).
   - If PR is now `CONFLICTING` or `DIRTY`, do not push again (`one-push-per-round`): skip step 12 collapse, proceed to send replies (none claiming the PR is ready), and end as `needs-human` naming the conflict.

### 12. Decide on single-commit collapse and execute if safe

`commits.single_commit` is true and `merge.message_source` is `commits`. Collapse only on the final round, in PR mode, adhering to all safety gates in order.

1. **Approval check before collapse (`content-free-push-after-approval`):**
   - Check existing reviews after step 11's push: `gh api repos/116-Labs/cuecal/pulls/<pr>/reviews --paginate`.
   - Count valid approvals: Count reviewers whose latest review is `APPROVED` (not dismissed) that still counts on the current head.
   - Because `review.dismiss_stale_approvals` and `review.require_last_push_approval` are absent in the profile, whether the repository dismisses stale approvals is unknown (counts as true / dismissing approvals on push).
   - If the PR already meets `review.required_approvals` (1 approval) and a push would invalidate them, do NOT collapse: a collapse changes no content and would throw approvals away for nothing (`content-free-push-after-approval`). Keep commits separate, report that collapse was skipped to preserve approvals, and let whoever merges supply the squash message.
   - If the round's step 11 push already carried code fixes, approvals were already dismissed, so collapse can proceed.
2. **Collapse conditions:**
   - Proceed with collapse only if all threads on this PR will be resolved after replies (step 14). If any thread will stay open (pushback or unagreed deferral), do NOT collapse (`collapse-with-open-threads`): keep the fixup commit separate so the reviewer can diff the delta.
3. **Safety gates and execution (PR mode):**
   - **Idempotence:** Run `git fetch origin` and `git rev-list --count origin/main..origin/<branch>`. If 0 or 1 commit ahead, nothing to collapse.
   - **Target check:** PR mode. Verify remote head with `git ls-remote origin refs/heads/<branch>` equals the sha pushed in step 11.
   - **Soft gates:** Unresolved threads exist now because threads resolve after the push; knowingly override and report.
   - **Hard gates:** Confirm not a fork and all commits authored by the PR author or this run: `git log --format=%an%x09%H origin/main..origin/<branch>`. Confirm remote head is an ancestor of what will be pushed (`git merge-base --is-ancestor`). Never bypass as admin (`admin-bypass`).
   - **Rewrite in throwaway worktree:**
     - Run `git worktree add --detach <run-dir>/worktree <remote-head-sha>`
     - Run `cd <run-dir>/worktree`
     - Record pre-collapse tree hash: `git rev-parse HEAD^{tree}`.
     - Find merge base: `git merge-base origin/main <remote-head-sha>`.
     - Reset soft: `git reset --soft <merge-base-sha>`.
     - Settle issue link (step 13): `Closes #N` for full change; `Refs #N` on its own line with **Deferred** list for partial change.
     - Write collapse commit message to `<run-dir>/scratch/collapse-msg.txt` with the file tool: conventional format, process commits dropped, attribution `none`, settled issue link.
     - Commit: `git commit -F <run-dir>/scratch/collapse-msg.txt` with hooks enabled (`bypass-hook`).
   - **Content preservation:** Post-collapse tree hash (`git rev-parse HEAD^{tree}`) must exactly equal pre-collapse tree hash, and change must not be empty. If hashes differ, abort before pushing.
   - **Push collapse:** `git push --force-with-lease=<branch>:<remote-head-sha> origin HEAD:refs/heads/<branch>`. On failure, restore HEAD and end as `failed`.
   - Tear down worktree on every exit path: `cd` back to checkout, then `git worktree remove --force <run-dir>/worktree`.
   - **Update stale checkout (`pull-after-collapse`):** In checkout, run `git fetch origin` and `git reset --hard origin/<branch>`. Never `git pull`. Backup local-only commits first if present.
   - Record final head: `git rev-parse HEAD` as `commit_sha`.

### 13. Settle issue link and update PR description

1. **Settle issue link under shared issue-link rule:**
   - If all acceptance criteria are met: use `Closes #N` (drop any **Deferred** list).
   - If some criteria remain deferred: use `Refs #N` on its own line followed by a **Deferred** heading listing open criteria.
   - Never place a closing keyword next to a Deferred list.
   - Settle before step 12 collapse so the commit message and PR description match.
2. **Update PR description to match the head (`description-matches-head`):**
   - Skip if the round changed no code and no claim became false.
   - Read current description: `gh pr view <pr> --repo 116-Labs/cuecal --json body`.
   - Re-read against the pushed tree after the last push: update summary, test plans, test counts, gate results, or behavioral claims (test counts and claims go stale across rounds; check after last push).
   - Update only what is false or missing; preserve untouched prose and issue reference structure. Attribution policy is `none` (no AI attribution section).
   - Write body to `<run-dir>/scratch/pr-body.md` using the file tool and update PR: `gh pr edit <pr> --repo 116-Labs/cuecal --body-file <run-dir>/scratch/pr-body.md`. Editing the description pushes nothing.

### 14. Reply to every item and resolve threads by rule

Write every reply body to `<run-dir>/scratch/<name>.md` with the file tool.

1. **Reply to review threads (`every-thread-answered`, `reply-matches-action`):**
   - Reply to each thread through its comment reply relation using the first comment's `databaseId` (recorded in step 4; works even on outdated threads):
     `gh api repos/116-Labs/cuecal/pulls/<pr>/comments/<comment-id>/replies --field body=@<run-dir>/scratch/<name>.md`
   - Content of replies:
     - **Fix:** Name the exact sha containing the fix (the final head/collapsed sha). State "Fixed in `<sha>`" only when that sha contains the fix (`truthful-report`).
     - **Deferral:** Name the filed follow-up issue number.
     - **Pushback:** Provide clear technical rationale.
     - **Import:** If it did not apply, explain why. If fixed, name where it landed (`target-branch-only`).
2. **Reply to `review-body` and `issue-request` items (`body-requests-answered`, `issue-requests-answered`):**
   - Consolidate answers for all `review-body` and `issue-request` items into a single PR comment:
     `gh pr comment <pr> --repo 116-Labs/cuecal --body-file <run-dir>/scratch/body-and-issue-answers.md`
   - Quote or link each request (for issue requests, link the issue comment or note the edit timestamp) and state the decision (fix sha, follow-up issue number, or reasons).
3. **Resolve threads by rule (`resolve-by-rule`):**
   - Resolve threads that were fixed, are outdated, or were deferred with recorded agreement on the thread:
     `gh api graphql --raw-field query='mutation { resolveReviewThread(input: {threadId: "<thread-id>"}) { thread { isResolved } } }'`
   - Leave pushbacks open (`resolve-pushback`).
   - Leave unagreed deferrals open (`resolve-unagreed-deferral`).
   - `review-body` and `issue-request` items have no threads and are not resolved.
   - If resolving an imported thread on another PR fails due to lack of permissions, do not block; the reply is what matters.

### 15. Re-request review

1. `review.reviewers` is `[]`, so re-request review from each login that submitted a review on this PR (from step 5):
   `gh pr edit <pr> --repo 116-Labs/cuecal --add-reviewer <login>`
2. If no prior reviewers exist or the re-request call fails, post a brief PR comment stating the revision is pushed and ready for review.
3. When this round's push dismissed approvals, Gaal itself re-requests those reviewers with a PR comment quoting the run result's `push`; do not post a separate notice about dismissal.

### 16. Write the run result

Write `result.json` on every exit path, including failures and early exits (`run-result-written`).

1. Run a shell command to read finish timestamp: `date -u +%Y-%m-%dT%H:%M:%SZ`. Record it as `finished_at`.
2. Construct `<run-dir>/result.json.tmp` using the file tool conforming to the JSON Schema:
   - `schema_version`: `1`
   - `run_id`: literal `GAAL_RUN_ID` string from run context
   - `blueprint`: `"revise-pr"`
   - `blueprint_version`: `"1.7.0"`
   - `repo`: `"116-Labs/cuecal"`
   - `issue`: linked issue number (integer) or `null`
   - `pr`: PR number (integer) or `null` (when none determined)
   - `status`: `"done"`, `"needs-human"`, `"needs-clarification"`, or `"failed"`
   - `reason`: required unless `status` is `"done"`. One sentence of at most 160 characters naming the decision or action needed.
   - `questions`: required array of strings when `status` is `"needs-clarification"`.
   - `attempts`: positive integer (gate-fix rounds consumed by this run, 1 to 3)
   - `gates`: array of gate objects (`name`, `command`, `exit_code`, `duration_ms`). Empty if nothing changed or ran.
   - `branch`: PR branch name string or `null`
   - `commit_sha`: 40-hex sha of final PR head (or unchanged head if nothing pushed) or `null`
   - `push`: (required when the run pushed to the open PR; `push-explained`): object with:
     - `why`: one sentence explaining why the run pushed (fixes carried or rebase reason)
     - `changes`: short range-diff summary (e.g. from `git range-diff`) or `"tree unchanged"`
   - `started_at`: start timestamp
   - `finished_at`: finish timestamp
3. Atomically move into place: `mv <run-dir>/result.json.tmp <run-dir>/result.json`. Never leave `.tmp` behind.
4. Final message: Present a summary table with one row per item (source, decision, sha or issue), open pushbacks listed, and collapse/approval details.

## Invariants

- `every-thread-answered`: Every unresolved thread at the start of the run has a reply at the end, including imports that did not apply. The reviewer is owed the reason.
- `one-push-per-round`: The branch is pushed at most once per round with changes, after all fixes (step 11). The one other push a round may make is the step-12 collapse, made whenever every thread on this PR will be resolved after replies and `merge.message_source` is `commits` (and skipped when step 11 ends the round on a conflict, or when the PR holds approvals the collapse would throw away): it keeps the tree unchanged and is the round's closing push (its only push when step 11 pushed nothing). There is never a second push to chase a moved base.
- `gates-green-before-push`: Every required gate (`lint`: `uv run ruff check .`, `test`: `uv run pytest`) exited 0 on the tree that was pushed.
- `reply-matches-action`: Each reply describes what was done: a sha that contains the fix, an issue number for a deferral, reasons for a pushback.
- `resolve-by-rule`: A thread is resolved only if it was fixed, is outdated, or was deferred with agreement recorded on the thread.
- `target-branch-only`: Code changes land only on this PR's branch. A fix for an imported item names where it landed in the reply.
- `bounded-rounds`: Gate-fix cycles stop at `limits.revise_rounds` (3), ending as `needs-human`.
- `body-requests-answered`: Every actionable request found in a latest review body is either acted on or answered in a PR comment that gives the reason. A request in a body is owed the same reply as one in a thread.
- `issue-requests-answered`: Every actionable request made on the linked issue since the PR opened, by its author or a maintainer, is acted on or answered in a PR comment with a sha, a follow-up issue or the reason it was declined. Gaal does not ask again about a request this run saw, so one left unanswered is lost.
- `base-drift-checked`: The base and the PR's mergeability were read before and after the round's push. Before the push, a `CONFLICTING` or `DIRTY` PR, or one whose `mergeStateStatus` is `BEHIND`, ended rebased onto the fresh base with the branch's commits kept as they are (no merge commit) and the gates re-run, with a stacked child retargeted once its parent merged; or it ended `needs-human`, naming the conflict or the gate red on the rebased tree. A base that only moved is not rebased onto. After the push, a `CONFLICTING` or `DIRTY` PR ends `needs-human` naming it, never a second push.
- `push-explained`: A run that pushed records in its result's `push` why the push was needed and what it changed: a range-diff summary, or `tree unchanged` when the pushed tree equals the tree before the run. A rebase compared tree identity before and after it.
- `description-matches-head`: After a round that changed behaviour, tests or gate results, the PR description states nothing the pushed head contradicts: no stale test counts, no claims about code that was replaced, no `Refs` with a **Deferred** list once every criterion is met (that is `Closes`, unless no collapse could carry it into the commit message and the reply says so), no **Deferred** list under `Closes`, and no issue link that differs from the head commit's. It is edited before review is re-requested.
- `explicit-staging`: Stage only paths this run wrote, taken from a manifest the run keeps. After staging, the working tree has no other changes this run is responsible for. Never stage everything wholesale.
- `base-untouched`: Never commit or push to the base branch (`main`).
- `fail-closed-reads`: Tell "the API said there is nothing" apart from "the call failed". Errors, auth expiry and rate limits stop the run. They never become "no PR", "no threads" or "no checks".
- `complete-listings`: Any listing of threads, reviews, comments or checks is either paginated to the end or the run stops. Truncated data is never trusted.
- `truthful-report`: The report and run result describe what actually happened. A gate that did not run is absent, not passed. "Fixed in `<sha>`" appears only when that sha contains the fix.
- `status-preserved`: A command's success or failure is never lost to a pipe, a filter or a guard. A failed push, gate or API write is seen and handled.
- `attribution-policy`: Commit messages and PR bodies follow `commits.attribution` (`none`) from the profile exactly. No AI attribution, model signatures, or `Co-Authored-By` lines are added.
- `run-result-written`: When `GAAL_RUN_DIR` is set, the final step atomically writes `result.json` on every exit path including failures. `reason` is one sentence of at most 160 characters naming the decision or action needed.

## Forbidden actions

- `push-red`: Pushing a branch with a failing required gate to clear comments.
- `piecemeal-push`: Pushing once per comment instead of once per round.
- `resolve-pushback`: Resolving a thread where the revision disagreed with the reviewer.
- `resolve-unagreed-deferral`: Resolving a deferral that only the reviser decided on. A deferral with no issue number is a pushback in disguise.
- `apply-unreproduced-import`: Applying an imported finding that does not reproduce on this branch.
- `collapse-with-open-threads`: Collapsing while any thread on this PR will remain open. The reviewer needs to diff only the delta.
- `pull-after-collapse`: Pulling into a checkout after a collapse. Hard-reset it to the remote instead.
- `content-free-push-after-approval`: Pushing a change that leaves the PR's content as it was (a collapse, or a rebase that step 11 does not require) while the PR holds the approvals `review.required_approvals` asks for (1 approval) and a push would invalidate them (`review.dismiss_stale_approvals` or `review.require_last_push_approval` true, or either absent/unknown).
- `bare-force-push`: Force-pushing without an explicit lease on the sha that was inspected. Only `--force-with-lease=<branch>:<sha>` is permitted.
- `admin-bypass`: Merging, pushing or rewriting with admin privileges (`gh pr merge --admin` and the like) to get around branch protection, a merge queue or a verification hook.
- `bypass-hook`: Committing or pushing with the repository's verification skipped or redirected: `--no-verify` (`git commit -n` included), `--no-gpg-sign`, `-c core.hooksPath=…` or any other change to where git looks for hooks, turning a hook manager off, or retrying a rejected commit or push through another route.
- `machine-specific-paths`: Hard-coding a person's home directory, private scripts or services into the generated skill.
- `commit-foreign-edits`: Committing changes this run did not make.

## Exit states

- `done`: Every thread, every actionable review-body request and every issue request since the PR opened is answered, the description matches the head, and the branch is pushed with green gates. `commit_sha` is the PR head after the run; when nothing needed changing, it is the unchanged head, nothing is pushed, and `gates` may be empty. The report has one row per item (source, decision, sha or issue). Open pushbacks are normal and listed. A collapse skipped to keep the PR's approvals is reported, not an error.
- `needs-clarification`: No PR could be determined, or a reviewer's request is ambiguous enough that any fix would be a guess. `questions` quote the thread.
- `needs-human`: The round limit of 3 was reached with red gates; a conflict (a rebase onto a moved base, or an unmergeable PR), fork, or permission problem blocks the push; a gate was red on the tree rebased onto a fresh base (nothing was pushed); or after the push the PR became `CONFLICTING` or `DIRTY`. `reason` names it.
- `failed`: The PR is not open; an API read failed; a verification hook rejected a commit beyond this run's remit; the push failed; or the collapse refused. `reason` names the step. Gates that were already red on the base are reported as pre-existing.
