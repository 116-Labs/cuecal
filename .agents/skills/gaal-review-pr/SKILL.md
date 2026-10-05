---
name: gaal-review-pr
description: Adversarially reviews an open pull request in 116-Labs/cuecal against its linked issue's acceptance criteria and the profile gates (`uv run ruff check .`, `uv run pytest`), posts exactly one review whose verdict follows from the verified findings, pushes small unambiguous fixes when allowed, and writes the run result to `$GAAL_RUN_DIR/result.json`. Use when a dispatch hands you a repo and PR number and asks for the `review-pr` step. Do not use to implement an issue, open a PR, revise a PR after review, or merge; those are other steps. If no PR can be determined, do not guess; end as `needs-clarification`.
---
<!-- gaal-stamp blueprint=review-pr@1.7.0 shared=1.4.0 profile=833de6ae33df6d68 generated=2026-10-04 core=1324aca6e6892990 forbidden=c5860b98ae1dfd7d content=a12ae57f8706b82f -->

# gaal-review-pr

Review an open pull request in `116-Labs/cuecal` the way a careful maintainer would. Judge it against the linked issue's acceptance criteria and the project's gates independently of how the PR describes itself. Post exactly one review with a verdict that strictly follows from verified findings. When allowed, push small, unambiguous fixes directly so the author owes answers only on what genuinely requires their attention.

## Run context

- Dispatch inputs: repository `116-Labs/cuecal`, PR number `<pr>`, mode: **post** (default) or **preview** (posts and pushes nothing; writes the review text to `<run-dir>/scratch/review.md`), `GAAL_RUN_ID`, `GAAL_RUN_DIR`, and `GAAL_LOGIN` (the account login the run acts as). If no PR can be determined, end as `needs-clarification` without guessing.
- Profile configuration for `116-Labs/cuecal`:
  - Default branch: `main`. Tracker: GitHub via `gh`. Branch prefix: `gaal/`.
  - Profile gates: `lint` (`uv run ruff check .`, required) and `test` (`uv run pytest`, required).
  - Preflight checks: none (`preflight: []`). Advisory checks: none.
  - Install commands: none (`install` names no commands). Install nothing; use the checkout's existing environment and run all gates directly in the checkout (`machine-specific-paths`). (A throwaway worktree has no install, so gates must run in the checkout itself).
  - Commit convention: conventional commits (`type(scope): subject`). Attribution policy (`commits.attribution`): `none`. Do not add AI attribution, model signatures, or `Co-Authored-By` lines (`attribution-policy`).
  - Merge regime: squash merge, no merge queue (`merge.queue: false`), `message_source: commits`, auto-merge disabled (`merge.auto: false`).
  - Review policy: `review.required_approvals: 1`, open threads do not block merge (`review.threads_block_merge: false`), `review.reviewers: []`, start signal: reaction `eyes` (`review.start_signal: reaction`), sign-off line not configured.
  - Reviewer identity: `review.identity: { reviewer: separate, login: 116-labs-gaal-review[bot] }`. Push identity: `identities.push: [116-labs-gaal-push[bot]]`. With `review.identity.reviewer: separate`, push nothing; all fixes go to the author as findings. An agent never approves its own change (`no-self-verdict`). Only the separate review identity approves; otherwise post `comment` (`identity-withholds`).
  - Attempt limits: review rounds limit is 2 (`limits.review_rounds: 2`). Profile also records implement attempts 3 (`limits.implement_attempts: 3`) and revise rounds 3 (`limits.revise_rounds: 3`).
  - Communications: GitHub comments enabled (`comms.github_comments: true`), maintainer channels empty.
- Headless execution rules:
  - Allowed commands: `git`, `gh`, `mkdir`, `mv`, `cp`, `ls`, `cat`, `date`, `pwd` with any arguments, plus exactly `uv run ruff check .` and `uv run pytest`.
  - Run one command per call. Never chain commands with `&&`, `;`, or `|`.
  - Never use shell variables (`$VAR`, `${VAR}`, `$(...)`, backticks) or `NAME=value` prefixes. In commands, `<run-dir>` stands for the literal path from `GAAL_RUN_DIR`, and `<run-id>` stands for the literal value of `GAAL_RUN_ID` from the run context. Write literal paths without machine-specific prefixes (`machine-specific-paths`).
  - Write files using file tools, never shell redirection. Scratch files and throwaway worktrees live in `<run-dir>/scratch` and `<run-dir>/worktree`, never `/tmp` or via `mktemp`. Pass file paths to tools (`git commit -F <file>`, `--body-file <file>`, `-F body=@<file>`, `--input <file>`).
  - Read timestamps with `date -u +%Y-%m-%dT%H:%M:%SZ`. Time gates by running `date -u +%s` immediately before and after the gate command; duration in milliseconds is `(end - start) * 1000`.
  - Check every command's exit code; never mask errors behind pipes or guards (`status-preserved`).
  - Atomic result writing: write `<run-dir>/result.json.tmp` then rename via `mv <run-dir>/result.json.tmp <run-dir>/result.json` (`run-result-written`).

## Steps

### 1. Read PR metadata (except description) and initialize run
- Read start timestamp with `date -u +%Y-%m-%dT%H:%M:%SZ` and record as `started_at`.
- Create scratch space: `mkdir -p <run-dir>/scratch`.
- Maintain a manifest of all file paths written or modified by this run at `<run-dir>/manifest.txt`. Stage only paths from this manifest (`explicit-staging`).
- Check status: `git status --porcelain`. If foreign uncommitted changes exist, do not touch them; end as `needs-human` with reason "Checkout is dirty; clean it and re-run" (`commit-foreign-edits`).
- If no PR number is provided in the dispatch and none can be determined, do not guess; end as `needs-clarification` with questions asking for the PR number.
- Read PR metadata **without reading the description body text into context** (`description-last`, `description-sets-scope`):
  `gh pr view <pr> --repo 116-Labs/cuecal --json number,state,baseRefName,headRefName,headRefOid,isCrossRepository,author,files,commits,closingIssuesReferences`
- If the API call fails (auth expiry, rate limit, network error), stop and end as `failed` naming this step (`fail-closed-reads`, `status-preserved`). Never interpret an API failure as "no PR".
- Check PR state: If `state` is not `OPEN` (e.g. `CLOSED` or `MERGED`), end as `failed` with reason "PR is not open".
- Target isolation: Changes must land only on the PR head branch. Never commit or push to `main` (`base-untouched`).
- Record `<branch>` (`headRefName`), `<head-sha>` (`headRefOid`), `isCrossRepository`, and author login.
- Do not read or evaluate the PR description text yet (`description-last`, `description-sets-scope`). Order is the defense: a description read first becomes the map, and the author's blind spots become the reviewer's.
- Note: Every exit path from here onward writes `$GAAL_RUN_DIR/result.json` atomically in step 17 (`run-result-written`).

### 2. Extract linked issues and acceptance criteria
- Apply the issue-link rule without bringing PR description prose into context (`description-last`). Extract only issue numbers by running jq over the body:
  `gh pr view <pr> --repo 116-Labs/cuecal --json body --jq '[.body | scan("(?im)^[ \\t]*(close|closes|closed|fix|fixes|fixed|resolve|resolves|resolved|refs)[ \\t]*:?[ \\t]*#([0-9]+)")]'`
  (Keep both flags: `i` for case insensitivity, `m` for multiline so `^` matches the start of every line, not only the first).
- For commit messages (after step 4's fetch): extract issue references from `git log --format=%B origin/main..<head-sha>`, matching closing and plain keywords.
- Classify each linked issue as closing (`close`, `closes`, `closed`, `fix`, `fixes`, `fixed`, `resolve`, `resolves`, `resolved`) or plain (`refs`).
- An issue explicitly specified in the dispatch takes precedence over extracted links.
- If the PR links no issue, or if a linked issue has no checkable acceptance criteria, end as `needs-clarification` with `questions` detailing what is missing.
- Read each linked issue fresh as it stands at review time (body and comments; comments that clarify or narrow scope form part of the specification):
  `gh issue view <issue> --repo 116-Labs/cuecal --json body,comments`
- The issue can change under the PR: a maintainer may add or clarify a criterion by editing the issue while the PR is open. A review that graded a remembered copy would evaluate obsolete scope.
- Account for plan drift vs spec: Only text between `<!-- gaal:plan-drift -->` and `<!-- /gaal:plan-drift -->` (and comments carrying the opening marker) represents the implementer's drift account (a claim to test, not part of the spec). Everything else in the issue body, including maintainer edits and comments added after a drift section, is the author's spec.
- Write down all acceptance criteria. If multiple issues are linked, grade against all of them.

### 3. Check review rounds and post start signal
- List all existing reviews on the PR, paginated to the end (`complete-listings`, `fail-closed-reads`):
  `gh api repos/116-Labs/cuecal/pulls/<pr>/reviews --paginate`
- Count prior reviews whose body carries the signature line `gaal review-pr · run ` (step 15) (`signed-review`). Never match by author login: GitHub spells an App login three ways (`<slug>[bot]`, `<slug>`, `app/<slug>`), while `GAAL_LOGIN` is only the first.
- Check attempt limit: `limits.review_rounds: 2`. If 2 prior signed reviews exist, do not review again; end as `needs-human` with reason "Review round limit of 2 reached".
- If 1 signed review exists, this is a re-review (round 2; delta rules apply). If 0 exist, this is round 1.
- In post mode, post the "review started" signal per `review.start_signal: reaction` (reaction `eyes`):
  `gh api -X POST repos/116-Labs/cuecal/issues/<pr>/reactions -f content=eyes`
  (Skip this in preview mode).

### 4. Fetch PR head and set up environment
- Fetch the PR head and `main` from remote:
  `git fetch origin pull/<pr>/head`
  `git fetch origin main`
- Verify fetched HEAD: Run `git rev-parse FETCH_HEAD` and confirm it matches `<head-sha>`. If the remote head moved, re-read PR metadata from step 1 once.
- Check out the head detached:
  `git checkout --detach <head-sha>`
- Dependency installation: The profile specifies `install: []` (no install commands). Install nothing; use the checkout's existing environment and run all gates directly in the checkout (`machine-specific-paths`). (Throwaway worktrees lack installed dependencies, so gates must run in the checkout itself).

### 5. Focus delta on re-review
- On a re-review (round 2):
  - Identify `<last-reviewed-head-sha>` from the `Reviewed head: <sha>` line of the newest signed review (`signed-review`).
  - Limit attention to the delta since that review:
    `git diff <last-reviewed-head-sha> <head-sha>`
    or when history was rewritten:
    `git range-diff <last-base>..<last-reviewed-head-sha> origin/main..<head-sha>`
  - Identify which earlier review threads were answered by this delta.
  - On a re-review, only Blocking findings and contradictions open new inline threads (`rereview-converges`). Other Secondary findings and nits stay in the review body.

### 6. Run correctness pass over code, scripts, workflows, and skills
- Inspect the diff against base: `git diff origin/main...<head-sha>` and touched files.
- Evaluate correctness: logic, edge cases, error handling, concurrency, and security.
- Treat scripts, CI workflows (`.github/workflows/`), and skill files (`.agents/skills/`) as code.
- Execute the script and workflow checklist:
  - Nonexistent or invalid flags.
  - Word-splitting and quoting issues.
  - Documented but unimplemented options or flags.
  - Shell injection vulnerabilities through untrusted inputs.
  - Non-idempotent re-runs.
  - Swallowed errors or missing error exits.
  - Unverified success inside loops.
- Record candidate findings with exact file paths and line numbers.

### 7. Run profile gates and record timing
- The profile specifies `preflight: []` and no advisory checks. Required gates: `lint` and `test`.
- Run each gate in order on the checkout tree as separate commands, timing each with `date -u +%s`:
  - Gate `lint`:
    `date -u +%s` (start)
    `uv run ruff check .`
    `date -u +%s` (end) -> calculate `duration_ms` = (end - start) * 1000
  - Gate `test`:
    `date -u +%s` (start)
    `uv run pytest`
    `date -u +%s` (end) -> calculate `duration_ms` = (end - start) * 1000
- Record each gate's `name`, exact `command`, `exit_code`, and `duration_ms` (`status-preserved`). Only record gates that actually ran (`truthful-report`).
- A non-zero exit code of a required gate is a candidate Blocking finding.

### 8. Check test coverage for behavioural changes
- For each behavioural change in the diff, name the test covering it (`tests-named`):
  - A new or changed test that fails without the change, or an existing test that already exercises it.
  - A change is tested only when a test fails without it; a test that passes on `main` proves nothing about the change, and a test the gates never ran proves nothing about the head.
- A behavioural change with no covering test is a finding:
  - **Blocking** if the linked issue's criteria ask for tests.
  - **Secondary** otherwise.
- For each new or changed test, record whether it ran in the profile gates of step 7.

### 9. Read PR description as claims to test
- **Only now** read the PR description (`description-last`):
  `gh pr view <pr> --repo 116-Labs/cuecal --json body --jq .body`
- Treat the description strictly as a set of claims to test. It can add findings; it can never remove one (`description-drops-finding`) and never limits what is reviewed (`description-sets-scope`).
- Note any **Deferred** list under `Refs #N`.
- Check description accuracy: compare summary, test counts, gate results, and ticked test-plan boxes against actual head state.

### 10. Verify candidate findings and evaluate acceptance criteria
- Verify every candidate finding at its exact line in the reviewed head; drop anything that does not reproduce (`findings-verified`).
- Walk every acceptance criterion from step 2 on the reviewed head (on a re-review, walk every criterion again, not only those touched by the delta):
  - **verified**: Met, proven by gate output, a test, or direct verification.
  - **failed**: Not met.
  - **unverified**: Could not be confirmed; state what a person must check.
  - **deferred**: The link is plain `Refs #N` and the PR's Deferred list explicitly names it.
- Note: A Deferred list entry that is not one of the issue's criteria is a Secondary finding.
- Deferral is scope, not an excuse: A plain `Refs` link with a Deferred list moves the named criteria out of this PR's bar; they are still checked and listed in the verdict. It never drops a correctness, gate or other finding, and it changes nothing under a closing keyword.

### 11. Sort findings into buckets and verify workflow/script constructs
- Sort verified findings into four buckets:
  - **Blocking**:
    - Any failed (unmet) acceptance criterion (unless validly deferred).
    - A Deferred list under a closing keyword (`Closes`, `Fixes`, `Resolves`), which would incorrectly close the issue on merge.
    - A failing required gate (`uv run ruff check .` or `uv run pytest`).
    - A ticked test-plan box for a gate or test that did not run on the head (claims evidence that does not exist).
    - An untested behavioural change when issue criteria mandate tests (`tests-named`).
    - An unverified workflow or script construct that the PR's CI could have run but did not run or failed.
  - **Secondary**:
    - Unverified acceptance criteria.
    - Untested behavioural change when issue criteria do not mandate tests.
    - Workflow or script construct that CI cannot run for this PR.
    - A Deferred list entry not present in the issue criteria.
    - Code quality, maintainability, or minor edge-case findings.
  - **Nits**: Minor style, naming, or cosmetic improvements.
  - **Pre-existing**: Defects in code this PR did not touch that reproduce on `main`. (Pre-existing defects never open threads, unless the PR makes the defect reachable).
- **Contradictions (`contradiction-fixed-or-threaded`):**
  - Any finding on lines the PR adds that contradicts other code in the PR (a hint, doc, test, error message, or default that disagrees with new behaviour).
  - Contradictions must end either fixed in step 13 or as inline threads in step 15; they are never left only in the review body.
- **Workflow / CLI / API constructs & CI checks:**
  - Check CI runs on the head: `gh run list --repo 116-Labs/cuecal --commit <head-sha>` (`complete-listings`).
  - Determine if the PR's CI could have run it: Workflow triggers on `pull_request` with `branches` and `paths` filters (and their `-ignore` forms) matching this PR's base and changed files, and the job/step `if:` conditions evaluate to true for `pull_request` events.
  - If CI could have run it and did not run or failed: **Blocking finding** (behaviour unverified; lint does not verify it).
  - Note: `pull_request_target` workflows run the base branch's copy, never the PR's, and do not verify PR changes.
  - If CI cannot run the construct (triggers only on push to main, tags, releases, schedules, or `pull_request_target`): **Secondary finding** naming what a person must check. When the description states the construct was verified by a command, record "the author states it was verified by `<command>`", and if that command is allowed by headless permissions, run it and record the result; this never drops the finding (`description-drops-finding`).

### 12. Choose verdict
- Choose the verdict strictly based on verified findings (`verdict-follows-findings`):
  - At least 1 Blocking finding -> `request-changes`.
  - 0 Blocking findings -> `approve` (nits and non-blocking findings may remain).
  - Undecidable / ambiguous requirements -> `comment`.
- The review body states the rule applied.

### 13. Optional auto-fix and single-commit collapse
- In preview mode: Skip auto-fix and collapse completely.
- Reviewer identity rule: The profile specifies `review.identity: { reviewer: separate, login: 116-labs-gaal-review[bot] }`. With `review.identity.reviewer: separate`, push nothing (`identity-withholds`): gaal refuses an approval from a review run that pushed, so every fix goes to the author as a finding.
- If a future non-separate identity configuration is used:
  - Push only when ALL conditions hold: 0 Blocking findings (`blocking: 0`), `isCrossRepository` is false, and every commit on the branch (`git log --format=%ae origin/main..<head-sha>`) is authored by the run's own account (`GAAL_LOGIN`). With `GAAL_LOGIN` empty or absent, push nothing (`rewrite-foreign-branch`, `identity-withholds`).
  - Auto-fix bound: Non-behavioural fixes always qualify. A behavioural fix qualifies only if it is in a file the PR touches, has exactly one reasonable form, and comes with a test that fails without it. When in doubt, hand it to the author. Never propose behavioural changes as one-click suggestions (`behavioral-suggestion`).
  - Execution order: Fix → commit → fast-forward push → collapse → anchors → post (`collapse-before-approve`).
  - Record restore point (`<head-sha>`). Add paths to `<run-dir>/manifest.txt`. Stage manifest paths explicitly: `git add <path1> <path2> ...` (`explicit-staging`). Never use `git add -A` or `git add .`.
  - Re-run gates: `uv run ruff check .` and `uv run pytest` (timing each as in step 7). If any gate fails, restore modified paths via `git restore <path>` and turn the fix into a finding.
  - Write conventional commit message to `<run-dir>/scratch/fix-msg.txt` with attribution `none` (`attribution-policy`): `fix(scope): address review finding`.
  - Commit: `git commit -F <run-dir>/scratch/fix-msg.txt` with verification hooks enabled (`bypass-hook`).
  - Check remote before push: `git fetch origin <branch>`. Verify `git merge-base --is-ancestor origin/<branch> HEAD`. If the remote head moved during review, abandon auto-fix and revert (`git reset --hard <head-sha>`).
  - Push fast-forward: `git push origin HEAD:<branch>`.
  - Single-commit collapse routine in PR mode (`collapse-before-approve`):
    - Regime: `merge.message_source` is `commits`, so collapse applies.
    - Idempotence: Check commit count ahead of `origin/main` (`git rev-list --count origin/main..HEAD`). If 0 or 1, succeed without rewriting.
    - Hard gates: Not a fork, foreign-authored commits absent, remote head is an ancestor. Never merge or bypass as admin (`admin-bypass`).
    - Worktree rewrite: `git worktree add --detach <run-dir>/worktree <pushed-sha>`, `cd <run-dir>/worktree`. Record pre-collapse tree hash `git rev-parse HEAD^{tree}`. Find merge base `git merge-base origin/main HEAD`. Soft reset `git reset --soft <merge-base-sha>`.
    - Write collapse message to `<run-dir>/scratch/collapse-msg.txt` (conventional format, process commits dropped, attribution `none`, settled issue links). Commit with `git commit -F <run-dir>/scratch/collapse-msg.txt` (`bypass-hook`).
    - Content preservation: verify post-collapse tree hash `git rev-parse HEAD^{tree}` equals pre-collapse tree hash and change is not empty.
    - Push collapse: `git push --force-with-lease=<branch>:<pushed-sha> origin HEAD:refs/heads/<branch>` (`bare-force-push`).
    - Tear down worktree on every exit path: `cd` back to checkout, then `git worktree remove --force <run-dir>/worktree`.
    - Reset checkout: `git fetch origin <branch>` and `git reset --hard origin/<branch>`. Never `git pull`.
  - A run that pushed a fix posts `comment` instead of `approve` (`no-self-verdict`).

### 14. Compute inline comment anchors
- Fetch post-push patch hunks:
  `gh api repos/116-Labs/cuecal/pulls/<pr>/files --paginate` (`complete-listings`)
- Compute anchors from the right-hand side of patch hunks for un-fixed findings.
- **Round 1:** Open threads for all Blocking findings, all contradictions, and Secondary findings worth a thread.
- **Round 2+ (re-review):** Open threads ONLY for Blocking findings and contradictions (`rereview-converges`). All other Secondary findings and nits stay in review body.
- Any finding fixed in step 13 gets no inline anchor (`fixed-not-flagged`).
- After one anchoring failure, re-fetch and re-anchor once; if anchoring fails again, fall back to a body-only review.

### 15. Compose and post review
- In preview mode: Write review body to `<run-dir>/scratch/review.md` and skip posting.
- In post mode: Compose review body and inline comments.
- **Review body structure (in exact order):**
  1. **Verdict line**: First line states the verdict (`APPROVE`, `REQUEST_CHANGES`, or `COMMENT`) and the rule applied (`verdict-follows-findings`).
  2. **Findings by bucket**:
     - `### Blocking`
     - `### Secondary`
     - `### Nits`
     - `### Pre-existing`
     (Each contradiction not fixed is carried as an inline thread and listed in its bucket `contradiction-fixed-or-threaded`).
  3. **Acceptance Criteria**: List every linked issue's criteria with status (`#<issue>: <text> - verified / failed / unverified / deferred`). Never show deferred criteria as met.
  4. **Tests section**: List each new or changed test and whether it ran in gates (`tests-named`); list each behavioural change with no test.
  5. **Fixed in `<sha>` section**: List fixes pushed in step 13 with their exact sha (`fixed-not-flagged`, `truthful-report`). (Omitted if no fixes pushed).
  6. **Description accuracy note**: Summary of whether the PR description matched head state.
  7. **Reviewed head**: `Reviewed head: <head-sha>` naming the reviewed head sha (`signed-review`).
  8. **Signature**: Exact signature on its own line: `gaal review-pr · run <run-id>` with literal `GAAL_RUN_ID` (`signed-review`).
- **Review event determination:**
  - The author of the change posts `COMMENT` with the verdict as the first line, never `APPROVE` or `REQUEST_CHANGES` (`no-self-verdict`).
  - A run whose account did not write the PR posts `REQUEST_CHANGES` when that is the verdict, whatever its identity.
  - Only `APPROVE` requires the separate review identity (`116-labs-gaal-review[bot]`). A run that is not the separate review identity, or whose run context names no login (`GAAL_LOGIN` empty or absent), or that pushed a fix, posts `COMMENT` when findings call for approve (`identity-withholds`, `no-self-verdict`). The review states that approval is withheld for identity/author/pushed reasons and that the PR is otherwise clean.
- Write `<run-dir>/scratch/review.json` with `commit_id`, `body`, `event`, and `comments` array.
- Post review:
  `gh api -X POST repos/116-Labs/cuecal/pulls/<pr>/reviews --input <run-dir>/scratch/review.json`
- If posting fails, retry once as a body-only review (`gh pr review <pr> --repo 116-Labs/cuecal ...`). If that fails too, end as `failed` naming this step.
- If API refuses approval, do not retry under another identity (`second-identity-approval`); downgrade to `COMMENT` once and end as `needs-human`.

### 16. List opened threads and resolve own threads
- Query threads opened by this review:
  - Take the `pull_request_review_id` of the review just posted from step 15.
  - Match threads whose first comment carries that review ID (`complete-listings`, `fail-closed-reads`).
  - **Stop if review ID is empty:** End `needs-human` with reason "Review ID is empty; cannot list opened threads" (`fail-closed-reads`). Never match by login.
- For threads opened by this review:
  - If the thread was disposed of by this run (recorded observation only, agreed trade-off, or filed follow-up issue under the follow-up bar): reply to the thread and then resolve it via GraphQL `resolveReviewThread` (`resolve-own-threads-only`).
  - Leave blockers, questions, suggestion blocks, and contradiction threads open.
  - Never resolve threads to clear the merge path (`resolve-to-unblock`). (`review.threads_block_merge: false`).
- Follow-up bar: File a follow-up issue only for a user-visible defect in code outside the diff that reproduces on `main`. Everything else is fixed, sent to the author, or recorded in the review—never filed.
- Report open threads split into suggestions and author-owed.

### 17. Write the run result
- Read finish timestamp: `date -u +%Y-%m-%dT%H:%M:%SZ` as `finished_at`.
- Construct `<run-dir>/result.json.tmp` using the file tool conforming to the JSON Schema:
  - `schema_version`: `1`
  - `run_id`: literal `GAAL_RUN_ID` string from run context
  - `blueprint`: `"review-pr"`
  - `blueprint_version`: `"1.7.0"`
  - `repo`: `"116-Labs/cuecal"`
  - `issue`: integer (first linked issue number) or `null`
  - `pr`: `<pr>` (integer) or `null`
  - `status`: `"done"`, `"needs-human"`, `"needs-clarification"`, or `"failed"`
  - `reason`: required unless `status` is `"done"`. One sentence of at most 160 characters naming the decision or action needed.
  - `questions`: required array of strings when `status` is `"needs-clarification"`.
  - `attempts`: `1` (review-pr consumes 1 attempt)
  - `gates`: array of gate objects (`name`, `command`, `exit_code`, `duration_ms`). Empty if no gates ran.
  - `branch`: `<branch>` or `null`
  - `commit_sha`: 40-hex sha of reviewed head (or post-fix head) or `null`
  - `review`: (required on `done`):
    - `verdict`: `"approve"`, `"request-changes"`, or `"comment"`
    - `blocking`: integer count of Blocking findings
    - `non_blocking`: integer count of Secondary plus Nits findings
    - `head`: `<head-sha>` (40-hex sha on `Reviewed head:` line)
    - `criteria`: array of every linked issue's criteria in order: `{"text": "#<issue>: <criterion>", "status": "verified" | "failed" | "unverified" | "deferred"}`
    - `approval_withheld`: `"author"`, `"identity"`, or `"pushed"` when findings called for approve but comment was posted (in that priority order if multiple apply)
  - `push`: (required when the run pushed to the PR):
    - `why`: string explaining why the run pushed
    - `changes`: string summarizing range-diff or `"tree unchanged"`
  - `started_at`: start timestamp
  - `finished_at`: finish timestamp
- Atomically move into place: `mv <run-dir>/result.json.tmp <run-dir>/result.json` (`run-result-written`).
- Clean up any temporary worktree and restore checkout ref (`git checkout <starting-ref>`).

## Invariants

- `description-last`: The PR description is read only after independent passes (correctness, gates, acceptance criteria) have produced findings.
- `verdict-follows-findings`: Verdict equals request changes if there is at least one Blocking finding, approve if there are none, and comment when undecidable. The review states the rule applied.
- `no-self-verdict`: A context that wrote or pushed the change posts comment, never approve or request changes. That includes a run that pushed a fix to the PR: it never approves code it pushed.
- `identity-withholds`: A run that is not the separate review identity, or whose run context names no login (`GAAL_LOGIN` empty or absent), posts comment when the findings call for approve, never approve, with `approval_withheld: author` when its account wrote the PR, else `identity`.
- `findings-verified`: Every posted finding was reproduced at its line against the reviewed head.
- `tests-named`: Every behavioural change in the diff names the test that covers it, or is a finding, Blocking when the issue's criteria ask for tests. The review's Tests section lists each new or changed test and whether it ran in the gates.
- `signed-review`: The review body names the reviewed head sha on a `Reviewed head: <sha>` line and ends with the signature `gaal review-pr · run <run-id>` on a line of its own.
- `fixed-not-flagged`: A fix pushed by the review appears in the "Fixed in" list and never also as an inline finding.
- `resolve-own-threads-only`: Only threads opened by this review (matched by review id, never by login) are resolved, each after a reply.
- `collapse-before-approve`: Any collapse happens before anchors are computed and before the review is posted.
- `contradiction-fixed-or-threaded`: A non-blocking finding on lines the PR adds that contradicts other code in the PR is fixed within the auto-fix bound or opened as an inline thread, on a first review and on a re-review. It is never left only in the review body.
- `rereview-converges`: After round 1, a new thread opens only for a Blocking finding or a contradiction. Questions go in the review body. A non-blocking finding other than a contradiction on lines an earlier round already read is fixed within the auto-fix bound or omitted.
- `explicit-staging`: Stage only paths this run wrote, taken from a manifest the run keeps. After staging, the working tree has no other changes this run is responsible for. Never stage everything wholesale.
- `base-untouched`: Never commit or push to the base branch (`main`).
- `fail-closed-reads`: Tell "the API said there is nothing" apart from "the call failed". Errors, auth expiry and rate limits stop the run. They never become "no PR", "no threads" or "no checks".
- `complete-listings`: Any listing of threads, reviews, comments or checks is either paginated to the end or the run stops. Truncated data is never trusted.
- `truthful-report`: The report and run result describe what actually happened. A gate that did not run is absent, not passed. "Fixed in `<sha>`" appears only when that sha contains the fix.
- `status-preserved`: A command's success or failure is never lost to a pipe, a filter or a guard. A failed push, gate or API write is seen and handled.
- `attribution-policy`: Commit messages and PR bodies follow `commits.attribution: none` from the profile exactly. No AI attribution, model signatures, or `Co-Authored-By` lines are added.
- `run-result-written`: When `GAAL_RUN_DIR` is set, the final step atomically writes `result.json` on every exit path including failures. `reason` is one sentence of at most 160 characters naming the decision or action needed.

## Forbidden actions

- `description-sets-scope`: Letting the description or its focus section limit what is reviewed.
- `description-drops-finding`: Dropping a verified finding because the description explains it away.
- `second-identity-approval`: Approving through another identity, or retrying a refused approval under a different one.
- `rewrite-foreign-branch`: Pushing to or rewriting a fork's branch or commits authored by someone else.
- `resolve-to-unblock`: Resolving threads to clear the merge path.
- `behavioral-suggestion`: Proposing behaviour changes as one-click suggestion blocks. Those go to the author as findings.
- `bare-force-push`: Force-pushing without an explicit lease on the sha that was inspected (`--force-with-lease=<branch>:<sha>`).
- `admin-bypass`: Merging, pushing or rewriting with admin privileges (`gh pr merge --admin` and the like) to get around branch protection, a merge queue or a verification hook.
- `bypass-hook`: Committing or pushing with the repository's verification skipped or redirected: `--no-verify` (`git commit -n` included), `--no-gpg-sign`, `-c core.hooksPath=…` or any other change to where git looks for hooks, turning a hook manager off, or retrying a rejected commit or push through another route.
- `machine-specific-paths`: Hard-coding a person's home directory, private scripts or services into the generated skill.
- `commit-foreign-edits`: Committing changes this run did not make.

## Exit states

- `done`: The review is posted (or written to `<run-dir>/scratch/review.md` in preview). `review` carries the verdict and counts. A clean review (no Blocking finding, no thread the author owes) whose approve was posted as comment for identity ends `done` with `review.approval_withheld`, so Gaal can tell it from one that leaves the author work. The final report includes acceptance-criteria results, description-accuracy note, thread ledger (open threads split into suggestions and author-owed), and push/collapse outcome with old → new sha.
- `needs-human`: Threads are left for the author (expected when Blocking > 0), whether or not identity downgraded the verdict to comment; the review round limit of 2 is reached; or the id of the review just posted was empty, so opened threads could not be listed (step 16). `reason` summarizes the decision or action needed in at most 160 characters.
- `needs-clarification`: No PR could be determined, the PR links no issue by the shared issue-link rule, or a linked issue has no checkable acceptance criteria. `questions` specify what is missing.
- `failed`: The PR is not open, an API read failed, a verification hook rejected a commit beyond this run's remit, or posting failed even after falling back to a body-only review. `reason` names the step and failure in at most 160 characters.
