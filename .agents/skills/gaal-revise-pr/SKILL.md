---
name: gaal-revise-pr
description: Revises an open pull request in 116-Labs/cuecal after review. It addresses every unresolved review thread, every actionable request in a review body, and every request made on the linked issue since the PR opened with a code fix or a reasoned reply, runs the profile gates (`uv run ruff check .`, `uv run pytest`), checks for base drift, pushes once per round, optionally collapses to a single commit when all threads resolve unless approvals would be invalidated, replies to and resolves threads by rule, keeps the PR description true to the new head, and writes the run result to `$GAAL_RUN_DIR/result.json`. Use when a dispatch hands you a repo and PR number and asks for the `revise-pr` step, including imported feedback from another PR, a comment URL, or free-text notes. Do not use to open a PR, implement an issue, review a PR, or merge; those are other steps. Do not use when no PR can be determined; end as `needs-clarification` instead of guessing.
---
<!-- gaal-stamp blueprint=revise-pr@1.7.0 shared=1.4.0 profile=833de6ae33df6d68 generated=2026-10-04 core=b92499e6abdd3fda forbidden=df8e4e73381d2451 content=27b19221f323026f -->

# gaal-revise-pr

Close the review loop on an open pull request in `116-Labs/cuecal`. Every unresolved review thread, every actionable request in a review body, and every request made on the linked issue since the PR opened receives either a verified code fix or a reasoned reply. The branch is pushed at most once per round with green gates, threads are resolved strictly by rule, and the PR description is updated to remain truthful to the final head before requesting review again.

## Run context

- Dispatch inputs: repository `116-Labs/cuecal`, PR number `<pr>`, optional imported feedback (threads from another PR, a single comment URL, or free-text notes), `GAAL_RUN_ID`, `GAAL_RUN_DIR`. If no PR number can be determined from the dispatch, end as `needs-clarification` without guessing.
- Profile configuration for `116-Labs/cuecal`:
  - Default branch: `main`. Tracker: GitHub via `gh`. Branch prefix: `gaal/`.
  - Profile gates: `lint` (`uv run ruff check .`, required) and `test` (`uv run pytest`, required).
  - Preflight checks: none (`preflight: []`). Advisory checks: none.
  - Install commands: none (`install` names no commands). Install nothing; use the checkout's existing environment and run all gates directly in the checkout (`machine-specific-paths`). (A throwaway worktree has no install, so gates must run in the checkout itself).
  - Commit convention: conventional commits (`type(scope): subject`). Attribution policy (`commits.attribution`): `none`. Do not add AI attribution, model signatures, or `Co-Authored-By` lines (`attribution-policy`).
  - Merge regime: squash merge, no merge queue (`merge.queue: false`), `message_source: commits`, auto-merge disabled (`merge.auto: false`).
  - Review policy: `review.required_approvals: 1`, open threads do not block merge (`review.threads_block_merge: false`), `review.reviewers: []`, start signal: reaction `eyes` (`review.start_signal: reaction`), reviewer identity: `review.identity: { reviewer: separate, login: 116-labs-gaal-review[bot] }`. Protection facts (`review.dismiss_stale_approvals`, `review.require_last_push_approval`) are absent/unspecified in the profile.
  - Attempt limits: revise rounds limit is 3 (`limits.revise_rounds: 3`). Profile also records implement attempts 3 (`limits.implement_attempts: 3`) and review rounds 2 (`limits.review_rounds: 2`).
  - Communications: GitHub comments enabled (`comms.github_comments: true`), maintainer channels empty.
- Headless execution rules:
  - The run executes shell commands headlessly without prompts. Outside the allowlist, every command is refused.
  - Allowed commands: `git`, `gh`, `mkdir`, `mv`, `cp`, `ls`, `cat`, `date`, `pwd` with any arguments, plus exactly `uv run ruff check .` and `uv run pytest`.
  - Run one command per call. Never chain commands with `&&`, `;`, or `|`.
  - Never use shell variables (`$VAR`, `${VAR}`, `$(...)`, backticks) or `NAME=value` prefixes. In commands, `<run-dir>` stands for the literal path from `GAAL_RUN_DIR`, and `<run-id>` stands for the literal value of `GAAL_RUN_ID` from the run context. Write literal paths without machine-specific prefixes (`machine-specific-paths`).
  - Write files using file tools, never shell redirection. Scratch files and throwaway worktrees live in `<run-dir>/scratch` and `<run-dir>/worktree`, never `/tmp` or via `mktemp`. Pass file paths to tools (`git commit -F <file>`, `--body-file <file>`, `-F body=@<file>`).
  - Read timestamps with `date -u +%Y-%m-%dT%H:%M:%SZ`. Time gates by running `date -u +%s` immediately before and after the gate command; duration in milliseconds is `(end - start) * 1000`.
  - Check every command's exit code; never mask errors behind pipes or guards (`status-preserved`).
  - Atomic result writing: write `<run-dir>/result.json.tmp` then rename via `mv <run-dir>/result.json.tmp <run-dir>/result.json` (`run-result-written`).

## Steps

### 1. Initialize run, scratch directory, and verify PR is open
- Run `date -u +%Y-%m-%dT%H:%M:%SZ` and record as `started_at`.
- Run `mkdir -p <run-dir>/scratch`.
- Identify the PR number `<pr>` from the dispatch input. If no PR number is given or can be determined, do not guess; end as `needs-clarification` with questions asking for the PR number.
- Run `git remote get-url origin` and verify it matches `116-Labs/cuecal`.
- Read PR metadata via `gh`:
  `gh pr view <pr> --repo 116-Labs/cuecal --json number,state,baseRefName,headRefName,headRefOid,isCrossRepository,author`
- If the API call fails (auth expiry, rate limit, network error), stop and end as `failed` naming this step (`fail-closed-reads`, `status-preserved`).
- Confirm PR state: If `state` is not `OPEN` (e.g. `CLOSED` or `MERGED`), end as `failed` with reason "PR is not open; cannot revise".
- Target isolation: All code changes must land strictly on this PR's branch (`<branch>`, `headRefName`) (`target-branch-only`). Never commit or push to `main` (`base-untouched`).
- Note: Every exit path from here onward writes `$GAAL_RUN_DIR/result.json` atomically in step 16 (`run-result-written`).

### 2. Fetch and check out the PR head
- Fetch the PR head and base branch from remote:
  `git fetch origin pull/<pr>/head`
  `git fetch origin main`
- If either fetch fails, end as `failed` (`fail-closed-reads`).
- Check out the PR branch locally:
  `git checkout <branch>`
- Verify HEAD matches `<head-sha>` (`headRefOid`): `git rev-parse HEAD`.
- Dependency installation: The profile specifies no `install` command (`install: []`). Install nothing. Work and run all profile gates directly in this checkout where dependencies are already installed (`machine-specific-paths`). (Throwaway worktrees lack installed dependencies, so gates must run in the checkout itself).

### 3. List all unresolved review threads and capture thread IDs
- List every unresolved review thread through the GitHub GraphQL API, paginated to the end (`complete-listings`, `fail-closed-reads`):
  Query `repository(owner: "116-Labs", name: "cuecal") { pullRequest(number: <pr>) { reviewThreads(first: 100) { nodes { id isResolved isOutdated path line originalLine comments(first: 50) { nodes { id body author { login } createdAt path position } } } pageInfo { hasNextPage endCursor } } } }`.
- Filter for unresolved threads (`isResolved: false`).
- **Capture thread IDs before any history rewrite:** Rewriting history or rebasing marks threads outdated; capturing thread IDs now ensures replies can still be sent through the thread relation later.
- Record each unresolved thread: thread ID, path, line, and comments. Tag each item with source `this-pr`.
- If optional imported feedback is provided (threads from another PR, a single comment URL, or free-text notes):
  - For a comment URL, inspect its shape before extracting IDs: distinguish a pull request review comment URL (which belongs to a review thread) from an issue-level comment URL (which has no thread).
  - Tag each imported item with its import source (e.g. `import-pr-<other-pr>`, `import-comment`, `import-notes`).

### 4. Read review bodies for actionable requests
- Reviewers sometimes list actionable findings only in the review body, where no thread exists to reply in.
- List all reviews on this PR, paginated to the end:
  `gh api repos/116-Labs/cuecal/pulls/<pr>/reviews --paginate` (`complete-listings`, `fail-closed-reads`).
- Read the body of the latest review from each reviewer, plus any earlier review body whose requests were never answered (`body-requests-answered`).
- A review body has no thread, so each actionable request in one (a requested change, a bug or edge-case finding described only in the body) becomes an item tagged `review-body`.
- Skip pure verdicts (e.g. "LGTM", "Approved"), general praise, and requests that were already answered or resolved by a subsequent commit or PR comment.

### 5. Read linked issues and new issue requests fresh
- Find linked issues by applying the issue-link rule: extract issue numbers from the PR body (`gh pr view <pr> --repo 116-Labs/cuecal --json body`) and commit messages (`git log origin/main..HEAD`), or from the dispatch.
- For each linked issue `<N>`:
  - Read the issue body and all comments, paginated to the end:
    `gh issue view <N> --repo 116-Labs/cuecal --json body,comments,createdAt`
    `gh api repos/116-Labs/cuecal/issues/<N>/comments --paginate` (`complete-listings`).
  - Query the issue's body edit history via GraphQL (`userContentEdits`: `editedAt`, `editor { login }`, `diff`).
  - Determine the request baseline timestamp: the earlier of (1) when the PR was created, and (2) when Gaal's newest done implement run for the issue started (the creation timestamp of its `Gaal finished implement …: done.` comment on the issue). Requests count from the earlier of the two.
  - Maintainers and authors ask for additional scope or changes on the issue as often as on the PR. Every comment created after the baseline by the issue's author or a repository maintainer (admin), and every body edit made by one of them after the baseline, is a request (`issue-requests-answered`).
  - **Filter out non-requests:**
    - Skip comments carrying a `<!-- gaal:` marker (Gaal's own comments).
    - Skip body edits whose changes lie entirely inside a marked plan-drift section (between `<!-- gaal:plan-drift -->` and `<!-- /gaal:plan-drift -->`, inclusive). An edit with any modified line outside such a section is a request.
    - Skip bot comments and edits.
    - Skip requests that an existing PR comment already answers.
    - Skip comments that ask for nothing actionable (status updates, thank-you notes).
  - Each actionable request (a new requirement, a changed acceptance criterion, a bug report) becomes an item tagged `issue-request`.

### 6. Re-verify imported items against this branch
- For each imported item from step 3:
  - Check whether the finding reproduces on the current PR branch tree.
  - Classify as: **reproduces**, **partly applies**, or **does not apply**.
  - Never apply an imported finding that does not reproduce on this branch (`apply-unreproduced-import`). If it does not apply or only partly applies, prepare an explanation for why it was declined or adjusted.

### 7. Decide each item and manage follow-ups
- For every item across all sources (`this-pr` thread, `import`, `review-body`, `issue-request`), choose one of four decisions:
  1. **fix**: Implement the requested change in code and covering tests.
  2. **answer**: Explain why the code is correct, answer the question, or provide clarification.
  3. **defer**: Defer the work to a follow-up issue, adhering strictly to the shared follow-up bar.
     - **Follow-up bar:** File a follow-up issue *only* for a user-visible defect outside the diff (wrong output a user can see in code this PR did not touch, reproducing on `main`). Name the defect, reproduction steps, and files, and link the PR/issue.
     - If the bar is met and agreement is recorded on the thread: file the issue using `gh issue create --repo 116-Labs/cuecal --title "..." --body-file <run-dir>/scratch/issue-body.md` and record the issue number.
     - If the bar is NOT met: do NOT file a follow-up issue. The item must be fixed, answered, or pushed back. A deferral with no issue number or no agreement is a pushback.
  4. **push back**: Disagree with the request, providing clear technical justification and reasoning.
- For `review-body` and `issue-request` items: decide using the same criteria. Because there is no review thread for these items, deferrals cannot carry recorded thread agreement; name the follow-up issue or technical rationale in the PR comment reply.
- If an `issue-request` widens the issue beyond what this PR can reasonably carry, defer it rather than folding it into this PR (file a follow-up only if the follow-up bar is met; otherwise answer with the reason in the reply).
- In `116-Labs/cuecal`, `review.threads_block_merge: false`. Even though threads do not block merge in GitHub settings, `resolve-by-rule` strictly governs thread resolution: an agreed deferral resolves, whereas a pushback stays open for the reviewer.

### 8. Implement code fixes and maintain the manifest
- Read each file before modifying it. Keep edits minimal, precise, and strictly scoped to the decided fixes.
- Do not refactor unrelated code or fix pre-existing debt outside the change's scope (`commit-foreign-edits`).
- Add or update covering tests for every bug fix or behavioral modification.
- Maintain a manifest of all file paths created or modified by this run in `<run-dir>/manifest.txt` (written and updated with the file tool).
- Stage only paths recorded in the manifest (`explicit-staging`). Never touch or stage foreign pre-existing edits (`commit-foreign-edits`).

### 9. Run required profile gates and handle failures
- Run each required profile gate in order on the checkout tree as separate commands:
  1. Gate `lint`:
     `date -u +%s` (start)
     `uv run ruff check .`
     `date -u +%s` (end) -> calculate `duration_ms` = (end - start) * 1000.
  2. Gate `test`:
     `date -u +%s` (start)
     `uv run pytest`
     `date -u +%s` (end) -> calculate `duration_ms` = (end - start) * 1000.
- Record `name`, `command`, `exit_code`, and `duration_ms` for each gate (`status-preserved`). Only record gates that actually ran (`truthful-report`).
- If any gate fails (exit code != 0):
  - Examine the error output, fix the root cause in code, update `<run-dir>/manifest.txt`, and re-run all gates from the beginning.
  - Gate-fix cycles stop at 3 rounds (`limits.revise_rounds: 3`; `bounded-rounds`).
  - If round 3 finishes with failing gates, push nothing (`push-red`) and end as `needs-human` with the failing gate summarized in `reason` (one sentence, at most 160 characters).
- Both required gates (`lint`, `test`) must exit 0 before proceeding to push (`gates-green-before-push`).

### 10. Commit fixes, check base drift, and push once
- If code changes were made in step 8:
  - Stage only manifest paths: `git add -- <path1> <path2> ...` (`explicit-staging`). Never use `git add -A`, `git add .`, or `git commit -a`.
  - Write the commit message to `<run-dir>/scratch/fixup-msg.txt` with the file tool (conventional format `fix(scope): subject`, no AI attribution per `commits.attribution: none`).
  - Commit with `git commit -F <run-dir>/scratch/fixup-msg.txt`.
  - Verification hooks stay enabled (`bypass-hook`). Never use `--no-verify`, `git commit -n`, `--no-gpg-sign`, `-c core.hooksPath=...`, or edit git hook configurations. If a hook rejects the commit, fix what it reports and re-run gates.
- **Base drift check before push (`base-drift-checked`):**
  - Run `git fetch origin main` (or stacked base `<base>`). Record `<base-sha>`: `git rev-parse origin/main`.
  - Run `gh pr view <pr> --repo 116-Labs/cuecal --json mergeable,mergeStateStatus,baseRefOid`. (If `mergeable` is `UNKNOWN`, wait briefly and re-read).
  - Rebase only when:
    1. PR `mergeable` is `CONFLICTING` or `DIRTY`, OR
    2. `mergeStateStatus` is `BEHIND` (GitHub reports `BEHIND` only when base requires branches to be up to date before merging; never read branch protection directly for this), OR
    3. PR is a stacked PR whose parent has merged.
  - A base that merely moved while the PR remains `MERGEABLE` and is not `BEHIND` is NOT rebased onto (avoids unnecessary history rewrites and reviewer range-diff burden).
  - **Rebase execution:**
    - Thread IDs were already captured in step 3.
    - Record pre-rebase tree: `git rev-parse HEAD^{tree}` and pre-rebase HEAD: `git rev-parse HEAD`.
    - Rebase onto the fresh base: `git rebase origin/main` (no merge commit).
    - If the rebase conflicts: abort with `git rebase --abort`, push nothing, and end as `needs-human` naming the conflicting paths in `reason`.
    - For a stacked PR whose parent merged: rebase onto `main` and retarget the base: `gh pr edit <pr> --repo 116-Labs/cuecal --base main`.
    - Compare tree identity: record `git rev-parse HEAD^{tree}` after rebase. If tree hashes differ, check if PR changes survived cleanly: `git range-diff <old-base>..<old-head> origin/main..HEAD`. Record `tree unchanged` or the range-diff summary for result `push.changes`.
    - Re-run all required profile gates (`uv run ruff check .`, `uv run pytest`) on the rebased tree. If any gate fails on the rebased tree, push nothing (`push-red`) and end as `needs-human` naming the failing gate and `<base-sha>`.
- **Push once (`one-push-per-round`, `piecemeal-push`, `bare-force-push`):**
  - Record current HEAD sha `<inspected-sha>`: `git rev-parse HEAD`.
  - Push with an explicit lease on the inspected SHA:
    `git push --force-with-lease=<branch>:<inspected-sha> origin <branch>`
  - (The fix push must land before a collapse that reads the remote head, or the collapse ships without the fix).
- **Post-push check:**
  - Re-read `gh pr view <pr> --repo 116-Labs/cuecal --json mergeable,mergeStateStatus` (wait briefly if `UNKNOWN`).
  - If the PR is now `CONFLICTING` or `DIRTY`: do NOT push a second time (`one-push-per-round`). Skip step 11 collapse, proceed to step 12 to post replies (none claiming the PR is ready), and end as `needs-human` naming the conflict in `reason`.
  - Fail closed: unreadable check before push stops the run with nothing pushed; after push it is reported like a conflict (`fail-closed-reads`).

### 11. Single-commit collapse routine in PR mode
- **Collapse applicability check:**
  - Regime: `merge.message_source` is `commits`, so collapse is supported in `116-Labs/cuecal`.
  - Thread check: If ANY thread on this PR will remain open after replies (e.g. pushbacks or unagreed deferrals), DO NOT collapse (`collapse-with-open-threads`). Keep the fixup commit separate so the reviewer can diff just the delta.
  - **Approval preservation check (`content-free-push-after-approval`):**
    - Read reviews on this PR after step 10's push: `gh api repos/116-Labs/cuecal/pulls/<pr>/reviews --paginate` (`complete-listings`).
    - Count reviewers whose latest review approves and is not dismissed, counting on the current head.
    - In `116-Labs/cuecal`, `review.required_approvals: 1`. Protection facts (`dismiss_stale_approvals`, `require_last_push_approval`) are absent in the profile, so any push must be assumed to invalidate approvals on the current head.
    - If the current head holds required approvals (count >= 1) and this round made no code fixes in step 10 (or already has approvals on the current head that a content-free push would throw away): DO NOT collapse (`content-free-push-after-approval`). A collapse changes no content and would throw approvals away for nothing. Skip collapse, retain existing commits, and report that collapse was skipped to preserve approvals and whoever merges supplies the squash message.
    - (If step 10 pushed fixes, stale approvals were already dismissed by that push, so collapse proceeds).
- **Collapse execution in throwaway worktree (PR mode):**
  - Idempotence: Check `git rev-list --count origin/main..HEAD`. If count <= 1, collapse is already satisfied.
  - If count > 1 and all collapse conditions are met:
    - Check hard gates: verify `git remote get-url origin` is `116-Labs/cuecal` (not a fork) and all commits are authored by the repository account (`git log --format=%ae origin/main..HEAD`). Never use admin bypass (`admin-bypass`).
    - Fetch latest remote branch: `git fetch origin <branch>`. Record `<remote-head-sha>`: `git rev-parse origin/<branch>`.
    - Create a throwaway detached worktree in `<run-dir>/worktree`:
      `git worktree add --detach <run-dir>/worktree origin/<branch>`
    - Record pre-collapse tree hash: `git -C <run-dir>/worktree rev-parse HEAD^{tree}`.
    - Find merge base: `git merge-base origin/main <remote-head-sha>` -> `<merge-base-sha>`.
    - Soft reset in worktree: `git -C <run-dir>/worktree reset --soft <merge-base-sha>`.
    - Prepare the single commit message: write `<run-dir>/scratch/collapsed-msg.txt` with the file tool (conventional commit format, describe change as a whole, drop WIP/process commit messages, include issue link from step 14, `commits.attribution: none`).
    - Commit in worktree: `git -C <run-dir>/worktree commit -F <run-dir>/scratch/collapsed-msg.txt`.
    - Content preservation check: verify `git -C <run-dir>/worktree rev-parse HEAD^{tree}` matches pre-collapse tree hash. If hashes differ or tree is empty, abort collapse.
    - Overrule unresolved-threads soft gate knowingly because threads just fixed resolve in step 13.
    - Push the collapsed single commit with lease:
      `git -C <run-dir>/worktree push --force-with-lease=<branch>:<remote-head-sha> origin <branch>`
      (This is the round's closing push, `one-push-per-round`).
    - Clean up throwaway worktree: `git worktree remove --force <run-dir>/worktree`.
    - Sync local checkout: `git reset --hard origin/<branch>`. Never pull after a collapse (`pull-after-collapse`).
    - Confirm `git rev-list --count origin/main..HEAD` is 1 (`single-commit`).

### 12. Reply to all review threads, review bodies, and issue requests
- **Reply to every review thread:**
  - For each unresolved thread from step 3, send a reply through its thread reply relation (works even on outdated threads):
    `gh api graphql -f query='mutation { addPullRequestReviewThreadReply(input: { pullRequestReviewThreadId: "<thread_id>", body: "..." }) { comment { id } } }'`
    (Or write reply to `<run-dir>/scratch/reply-<id>.txt` with file tool and pass `-F body=@<run-dir>/scratch/reply-<id>.txt`).
  - Fix reply: names the commit SHA containing the fix (`reply-matches-action`).
  - Deferral reply: names the follow-up issue number filed under the follow-up bar.
  - Pushback reply: provides clear technical reasoning for disagreeing.
- **Answer review-body and issue-request items in a single PR comment (`body-requests-answered`, `issue-requests-answered`):**
  - Review bodies and issue requests have no thread relation to reply in.
  - Compile a single clear PR comment answering every `review-body` and `issue-request` item:
    - Quote or link each request (issue request by comment URL or edit timestamp; review-body request by quotation).
    - State the decision and outcome for each (SHA containing fix, follow-up issue number, or reasoning).
  - Save to `<run-dir>/scratch/pr-revision-comment.md` with the file tool.
  - Post comment: `gh pr comment <pr> --repo 116-Labs/cuecal --body-file <run-dir>/scratch/pr-revision-comment.md`.

### 13. Resolve review threads by rule
- For each review thread on this PR:
  - Resolve using GraphQL:
    `gh api graphql -f query='mutation { resolveReviewThread(input: { threadId: "<thread_id>" }) { thread { isResolved } } }'`
  - **Resolution rules (`resolve-by-rule`):**
    - **Resolve**: Threads that were fixed in code, threads marked outdated by delta, or threads deferred with recorded agreement.
    - **Keep OPEN**: Pushbacks (disagreed) and unagreed deferrals must stay OPEN for the reviewer (`resolve-pushback`, `resolve-unagreed-deferral`).
  - If resolving an imported thread on another PR fails due to repository permissions, record the outcome; the reply is what matters and permission failure is not a blocker.
  - Review-body and issue-request items have no thread to resolve.

### 14. Update PR description to match the final head
- Test counts, gate results, and behavioral claims in the PR description go stale across revise rounds; check them strictly after the last push.
- Read the existing PR description: `gh pr view <pr> --repo 116-Labs/cuecal --json body --jq .body`.
- Compare description claims against the pushed tree and round outcome:
  - Update summary and behavioral descriptions if fixes altered behavior.
  - Update test counts and test plan checklist (`- [x]` only for gates that ran and passed on the pushed tree: `uv run ruff check .`, `uv run pytest`).
  - Update issue links per the shared issue-link rule:
    - If all acceptance criteria (including previously deferred ones) are now met: turn `Refs #N` into `Closes #N` and remove the **Deferred** list.
    - If criteria remain deferred: update the **Deferred** list under `Refs #N`.
    - Never include a **Deferred** list next to `Closes #N`.
  - Edit only what is now false or missing; do not rewrite untouched prose.
  - Attribution: Add no AI attribution (`commits.attribution: none`).
- Write updated description to `<run-dir>/scratch/pr-body.md` with the file tool.
- Update PR: `gh pr edit <pr> --repo 116-Labs/cuecal --body-file <run-dir>/scratch/pr-body.md`.
- (Skip if the round made no code changes and no claim in the description became false. Editing the description pushes nothing).

### 15. Re-request review per profile policy
- Profile configuration: `review.reviewers: []`. Do not invent or request unconfigured reviewers.
- When this round's push dismissed approvals, Gaal itself re-requests exactly those reviewers, once per push, with a PR comment that quotes the run result's `push`; post no notice of your own about the dismissal.

### 16. Write the run result on every exit path, including failures
- Read finish timestamp: `date -u +%Y-%m-%dT%H:%M:%SZ` and record as `finished_at`.
- Record `commit_sha`: `git rev-parse HEAD` (or `null` if no commit exists).
- Write `<run-dir>/result.json.tmp` using the file-writing tool.
- Atomically move into place: `mv <run-dir>/result.json.tmp <run-dir>/result.json` (`run-result-written`). Never leave the `.tmp` file behind.
- JSON Schema conforming payload:
  - `schema_version`: `1`
  - `run_id`: literal value of `GAAL_RUN_ID` from the run context
  - `blueprint`: `"revise-pr"`
  - `blueprint_version`: `"1.7.0"`
  - `repo`: `"116-Labs/cuecal"`
  - `issue`: integer `<N>` or `null`
  - `pr`: integer `<pr>`
  - `status`: `"done"`, `"needs-human"`, `"needs-clarification"`, or `"failed"`
  - `reason`: required unless `status` is `"done"`; one sentence of at most 160 characters naming the decision or action needed (detail goes in PR comments and final message)
  - `questions`: required non-empty array of strings if `status` is `"needs-clarification"`; omit otherwise
  - `attempts`: positive integer (1, 2, or 3) indicating revise rounds consumed in this run
  - `gates`: array of gate executions on the final tree, each containing `name`, `command`, `exit_code`, `duration_ms` (empty array if no gates ran)
  - `branch`: branch name string (e.g. `"gaal/<N>-<slug>"`) or `null`
  - `commit_sha`: 40-hex SHA string or `null`
  - `push`: object with `why` (one sentence explaining why the push was needed) and `changes` (short range-diff summary, or `"tree unchanged"`) if this run pushed to the PR; omit if no push was made (`push-explained`)
  - `started_at`: ISO 8601 string
  - `finished_at`: ISO 8601 string
- Present the final hand-off report: list each item addressed with its source, decision, and commit SHA or issue number; summarize push and collapse status; and list open pushbacks.

## Exit states

- `done`: Every review thread, every actionable review-body request, and every issue request since the PR opened is answered; the PR description matches the head; and the branch is pushed with green gates. `commit_sha` is the PR head after the run (when nothing needed changing, it is the unchanged head, nothing is pushed, and `gates` may be empty). The report has one row per item (source, decision, SHA or issue). Open pushbacks are normal and listed. A collapse skipped to keep approvals is reported and is not an error.
- `needs-clarification`: No PR could be determined from the dispatch, or a reviewer's request is ambiguous enough that any fix would be a guess. `questions` quotes the thread or request.
- `needs-human`: The round limit of 3 was reached with failing gates (`limits.revise_rounds: 3`); a merge conflict (a rebase onto a moved base, or an unmergeable PR) or permission problem blocks the push; a gate was red on the tree rebased onto a fresh base (nothing was pushed); or after the push the PR became `CONFLICTING` or `DIRTY`. `reason` states what happened.
- `failed`: The PR is not open; the push failed; or the collapse refused (empty rewrite, tree hash mismatch, or hard gate failure). `reason` names the step and cause.

## Invariants

- `every-thread-answered`: Every unresolved thread at the start of the run has a reply at the end, including imports that did not apply (steps 3, 12).
- `one-push-per-round`: The branch is pushed at most once per round with changes, after all fixes (step 10). The one other push a round may make is the step-11 collapse, made whenever every thread on this PR will be resolved after replies and `merge.message_source` is `commits` (and skipped when step 10 ends the round on a conflict, or when the PR holds approvals the collapse would throw away): it keeps the tree unchanged and is the round's closing push (its only push when step 10 pushed nothing). There is never a second push to chase a moved base (steps 10, 11).
- `gates-green-before-push`: Every required gate (`uv run ruff check .`, `uv run pytest`) exited 0 on the tree that was pushed. A pending gate runnable on that tree must also exit 0 (step 9).
- `reply-matches-action`: Each reply describes what was done: a SHA that contains the fix, an issue number for a deferral, reasons for a pushback (steps 7, 12).
- `resolve-by-rule`: A thread is resolved only if it was fixed, is outdated, or was deferred with agreement recorded on the thread (steps 7, 13).
- `target-branch-only`: Code changes land only on this PR's branch. A fix for an imported item names where it landed in the reply (steps 1, 8).
- `bounded-rounds`: Gate-fix cycles stop at 3 rounds (`limits.revise_rounds`), ending as `needs-human` (step 9).
- `body-requests-answered`: Every actionable request found in a latest review body is either acted on or answered in a PR comment that gives the reason (steps 4, 12).
- `issue-requests-answered`: Every actionable request made on the linked issue since the PR opened, by its author or a maintainer, is acted on or answered in a PR comment with a SHA, a follow-up issue or the reason it was declined (steps 5, 12).
- `base-drift-checked`: The base and the PR's mergeability were read before and after the round's push. Before the push, a `CONFLICTING` or `DIRTY` PR, or one whose `mergeStateStatus` is `BEHIND` ended rebased onto the fresh base with the branch's commits kept as they are (no merge commit) and the gates re-run, with a stacked child retargeted once its parent merged; or it ended `needs-human`, naming the conflict or the gate red on the rebased tree. A base that only moved is not rebased onto. After the push, a `CONFLICTING` or `DIRTY` PR ends `needs-human` naming it, never a second push (step 10).
- `push-explained`: A run that pushed records in its result's `push` why the push was needed and what it changed: a range-diff summary, or `tree unchanged` when the pushed tree equals the tree before the run. A rebase compared tree identity before and after it (steps 10, 16).
- `description-matches-head`: After a round that changed behaviour, tests or gate results, the PR description states nothing the pushed head contradicts: no stale test counts, no claims about code that was replaced, no `Refs` with a **Deferred** list once every criterion is met, no **Deferred** list under `Closes`, and no issue link that differs from the head commit's (steps 11, 14).
- `explicit-staging`: Stage only paths this run wrote, taken from a manifest the run keeps. After staging, the working tree has no other changes this run is responsible for. Never stage everything wholesale (steps 8, 10).
- `base-untouched`: Never commit or push to `main` (steps 1, 10).
- `fail-closed-reads`: Tell "the API said there is nothing" apart from "the call failed". Errors, auth expiry and rate limits stop the run. They never become "no PR", "no threads" or "no checks" (steps 1, 2, 3, 4, 5, 10).
- `complete-listings`: Any listing of threads, reviews, comments or checks is either paginated to the end or the run stops. Truncated data is never trusted (steps 3, 4, 5, 11).
- `truthful-report`: The report and run result describe what actually happened. A gate that did not run is absent, not passed. "Fixed in `<sha>`" appears only when that sha contains the fix (steps 9, 16).
- `status-preserved`: A command's success or failure is never lost to a pipe, a filter or a guard. A failed push, gate or API write is seen and handled (steps 1, 9, 10).
- `attribution-policy`: Commit messages and PR bodies follow `commits.attribution: none` from the profile exactly. No AI attribution, no `Co-Authored-By` trailer, and no tool credits are added (steps 10, 11, 14).
- `run-result-written`: `result.json` is written atomically on every exit path, including failures, via a `.tmp` file and rename (steps 1, 16).
- `single-commit`: The branch is collapsed to exactly one commit ahead of `main` when all threads resolve and approvals are not invalidated, maintaining `message_source: commits` squash merge regime (step 11).

## Forbidden actions

- `push-red`: Pushing a branch with a failing required gate to clear comments (steps 9, 10).
- `piecemeal-push`: Pushing once per comment instead of once per round (steps 10, 11).
- `resolve-pushback`: Resolving a thread where the revision disagreed with the reviewer (steps 7, 13).
- `resolve-unagreed-deferral`: Resolving a deferral that only the reviser decided on. A deferral with no issue number is a pushback in disguise (steps 7, 13).
- `apply-unreproduced-import`: Applying an imported finding that does not reproduce on this branch (steps 6, 7).
- `collapse-with-open-threads`: Collapsing while any thread on this PR will remain open. The reviewer needs to diff only the delta (step 11).
- `pull-after-collapse`: Pulling into a checkout after a collapse. Hard-reset it to the remote instead (step 11).
- `content-free-push-after-approval`: Pushing a change that leaves the PR's content as it was (a collapse, or a rebase that step 10 does not require) while the PR holds the approvals `review.required_approvals` asks for (1 approval, counted as step 11 counts them) and a push would invalidate them. A rebase the PR needs (a conflict, `BEHIND`, a merged stack parent) still goes ahead (steps 10, 11).
- `bare-force-push`: Force-pushing without an explicit lease on the sha that was inspected (`--force-with-lease=<branch>:<sha>`) (steps 10, 11).
- `admin-bypass`: Merging, pushing or rewriting with admin privileges (`gh pr merge --admin` and the like) to get around branch protection, a merge queue or a verification hook (steps 10, 11).
- `bypass-hook`: Committing or pushing with the repository's verification skipped or redirected: `--no-verify` (`git commit -n` included), `--no-gpg-sign`, `-c core.hooksPath=…` or any other change to where git looks for hooks, turning a hook manager off, or retrying a rejected commit or push through another route. When a hook rejects a commit or push, fix what it reports (step 10).
- `machine-specific-paths`: Hard-coding a person's home directory, private scripts or services into the generated skill instead of reading them from the profile. Use literal paths inside this checkout and `<run-dir>` (steps 1, 2).
- `commit-foreign-edits`: Committing changes this run did not make, or editing files outside the manifest (steps 8, 10).
