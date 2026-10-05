---
name: gaal-review-pr
description: Adversarially reviews an open pull request in 116-Labs/cuecal against its linked issue's acceptance criteria and the profile gates (`uv run ruff check .`, `uv run pytest`), posts exactly one review whose verdict follows from the verified findings, pushes small unambiguous fixes when allowed, and writes the run result to `$GAAL_RUN_DIR/result.json`. Use when a dispatch hands you a repo and PR number and asks for the `review-pr` step. Do not use to implement an issue, open a PR, revise a PR after review, or merge; those are other steps. If no PR can be determined, do not guess; end as `needs-clarification`.
---
<!-- gaal-stamp blueprint=review-pr@1.7.0 shared=1.4.0 profile=833de6ae33df6d68 generated=2026-10-04 core=1324aca6e6892990 forbidden=c5860b98ae1dfd7d content=21157c36dc39f942 -->

# gaal-review-pr

Review an open pull request in `116-Labs/cuecal` the way a careful maintainer would. Judge it against the linked issue's acceptance criteria and the project's profile gates independently of how the PR describes itself. Post exactly one review with a verdict that follows strictly from verified findings. When allowed, push small, unambiguous fixes directly so the author only owes answers on what genuinely requires their attention.

## Run context

- Dispatch inputs: repository `116-Labs/cuecal`, PR number `<pr>`, mode: **post** (default) or **preview** (posts and pushes nothing; writes the composed review body to `<run-dir>/scratch/review.md`), `GAAL_RUN_ID`, `GAAL_RUN_DIR`, and `GAAL_LOGIN` (the account login the run acts as). If no PR can be determined, do not guess; end as `needs-clarification`.
- Project profile configuration for `116-Labs/cuecal`:
  - Default branch: `main`. Tracker: GitHub via `gh`. Branch prefix: `gaal/`.
  - Profile gates: `lint` (`uv run ruff check .`, required) and `test` (`uv run pytest`, required).
  - Preflight checks: none (`preflight: []`). Advisory checks: none.
  - Install commands: none (`install` names no commands). Install nothing; use the checkout's existing environment and run all gates directly in the checkout. (A throwaway worktree has no install, so never run gates in a worktree).
  - Commit convention: conventional commits (`type(scope): subject`). Attribution policy (`commits.attribution`): `none`. Do not add AI attribution, model signatures, or `Co-Authored-By` lines (`attribution-policy`).
  - Merge regime: squash merge, no merge queue (`merge.queue: false`), `message_source: commits`, auto-merge disabled (`merge.auto: false`).
  - Review policy: `review.required_approvals: 1`, open threads do not block merge (`review.threads_block_merge: false`), `review.reviewers: []`, start signal: reaction `eyes` (`review.start_signal: reaction`), sign-off line not configured.
  - Reviewer identity: separate reviewer identity configured (`review.identity.reviewer: separate`, `review.identity.login: 116-labs-gaal-review[bot]`). Push identity: `116-labs-gaal-push[bot]`.
  - Attempt limits: review rounds limit is 2 (`limits.review_rounds: 2`). Profile also notes implement attempts 3 (`limits.implement_attempts: 3`) and revise rounds 3 (`limits.revise_rounds: 3`).
  - Communications: GitHub comments enabled (`comms.github_comments: true`), maintainer channels empty.
- Headless execution rules:
  - The run executes shell commands headlessly without asking anyone. Outside the allowlist, every command is refused.
  - Allowed commands: `git`, `gh`, `mkdir`, `mv`, `cp`, `ls`, `cat`, `date`, `pwd` with any arguments, plus exactly `uv run ruff check .` and `uv run pytest`.
  - Run one command per call. Never chain commands with `&&`, `;`, or `|`.
  - Never use shell variables (`$VAR`, `${VAR}`, `$(...)`, backticks) or `NAME=value` prefixes. In commands, `<run-dir>` stands for the literal path from `GAAL_RUN_DIR`, and `<run-id>` stands for the literal value of `GAAL_RUN_ID` from the run context. Write literal paths inside this checkout without machine-specific prefixes (`machine-specific-paths`).
  - Write files using file tools, never shell redirection. Scratch files and throwaway worktrees live in `<run-dir>/scratch` and `<run-dir>/worktree`, never `/tmp` or through `mktemp`. Pass file paths to tools (`git commit -F <file>`, `--body-file <file>`, `-F body=@<file>`, `--input <file>`).
  - Read timestamps with `date -u +%Y-%m-%dT%H:%M:%SZ`. Time gates by running `date -u +%s` immediately before and after the gate command; duration in milliseconds is `(end - start) * 1000`.
  - Check every command's exit code; never mask errors behind pipes or guards (`status-preserved`).
  - Verification hooks stay enabled (`bypass-hook`, `admin-bypass`): never use `--no-verify`, `git commit -n`, `--no-gpg-sign`, `-c core.hooksPath=...`, switch off hook managers, or use `gh pr merge --admin`. To find the hooks directory, run `git rev-parse --git-path hooks`.
  - Atomic result writing: write `<run-dir>/result.json.tmp` then rename via `mv <run-dir>/result.json.tmp <run-dir>/result.json` (`run-result-written`).

## Steps

### 1. Initialize run, scratch space, and manifest

1. Read the start timestamp: `date -u +%Y-%m-%dT%H:%M:%SZ` and record it as `started_at`.
2. Check working directory and branch state: run `pwd`, `git rev-parse --abbrev-ref HEAD`, and `git rev-parse HEAD`.
3. Check checkout state: run `git status --porcelain`. Ignore untracked files located under `<run-dir>`. Any other pre-existing dirty path is unowned work (`commit-foreign-edits`). If dirty paths exist, do not touch or reformat them; end as `needs-human` with reason "Checkout contains uncommitted changes; clean working tree before running review-pr".
4. Create scratch space: run `mkdir -p <run-dir>/scratch`.
5. Maintain a manifest of all file paths written or modified by this run at `<run-dir>/manifest.txt`. Stage only paths from this manifest (`explicit-staging`).
6. Note: Every exit path from here on writes `$GAAL_RUN_DIR/result.json` atomically in step 17 (`run-result-written`).

### 2. Read PR metadata (except description)

1. If no PR number is provided in the dispatch and none can be determined, do not guess; end as `needs-clarification` with `questions` asking for the PR number.
2. Read PR metadata **without reading the description body text into context** (`description-last`, `description-sets-scope`):
   run `gh pr view <pr> --repo 116-Labs/cuecal --json number,state,baseRefName,headRefName,headRefOid,isCrossRepository,author,files,commits,closingIssuesReferences`
3. Handle API errors: If the call fails due to auth expiry, rate limit, or network error, stop and end as `failed` naming this step (`fail-closed-reads`, `status-preserved`). Never interpret an API failure as "no PR".
4. Check PR state: If `state` is not `OPEN` (e.g. `CLOSED` or `MERGED`), end as `failed` with reason "PR is not open".
5. Record `<branch>` (`headRefName`), `<head-sha>` (`headRefOid`), `isCrossRepository`, and `author.login`.
6. Target isolation: Never commit or push to `main` (`base-untouched`).
7. Do not read or evaluate the PR description text yet (`description-last`, `description-sets-scope`).

### 3. Extract linked issues and acceptance criteria

1. Apply the issue-link rule without bringing PR description prose into context. Extract only issue numbers by running jq over the body:
   run `gh pr view <pr> --repo 116-Labs/cuecal --json body --jq '[.body | scan("(?im)^[ \\t]*(close|closes|closed|fix|fixes|fixed|resolve|resolves|resolved|refs)[ \\t]*:?[ \\t]*#([0-9]+)")]'`
   (Keep both flags: `i` for case insensitivity, `m` for multiline matching so `^` matches at the start of every line).
2. For commit messages (after step 5's fetch): extract issue references from `git log --format=%B origin/main..<head-sha>`, matching closing and plain keywords.
3. Classify each linked issue as closing (`close`, `closes`, `closed`, `fix`, `fixes`, `fixed`, `resolve`, `resolves`, `resolved`) or plain (`refs`).
4. An issue explicitly given in the dispatch takes precedence over extracted links.
5. If the PR links no issue by the issue-link rule, or if a linked issue has no checkable acceptance criteria, end as `needs-clarification` with `questions` detailing what is missing.
6. Read each linked issue fresh as it stands at review time, including its body and all comments paginated to the end (`complete-listings`, `fail-closed-reads`):
   run `gh issue view <issue> --repo 116-Labs/cuecal --json body,comments`
   run `gh api repos/116-Labs/cuecal/issues/<issue>/comments --paginate`
7. The issue can change under the PR: maintainers may add or clarify criteria via comments or edits while the PR is open. Comments that clarify or narrow scope form part of the specification (especially those beginning `**Clarification**`, `**Clarification (rewrite)**`, or `**Clarification (scope narrow)**`).
8. Plan drift vs spec: Only text between an opening `<!-- gaal:plan-drift -->` line and its closing `<!-- /gaal:plan-drift -->` line (and a comment carrying the opening marker) is the implementer's account of how its plan changed; this is a claim to check like the description, never the spec. Everything else in the issue body, including maintainer edits and comments added after a drift section, is the author's spec.
9. Write down all acceptance criteria across all linked issues. A PR that links several issues is judged against all of them.

### 4. Check review rounds and post start signal

1. List all existing reviews on the PR, paginated to the end (`complete-listings`, `fail-closed-reads`):
   run `gh api repos/116-Labs/cuecal/pulls/<pr>/reviews --paginate`
2. Count prior reviews carrying the exact signature `gaal review-pr · run ` (step 15). Never match by author login: GitHub spells an App login three ways (`<slug>[bot]`, `<slug>`, `app/<slug>`), while `GAAL_LOGIN` is only the first.
3. Enforce attempt limit: `limits.review_rounds: 2`. If 2 prior signed reviews exist, do not review again; end as `needs-human` with reason "Review round limit of 2 reached".
4. If 1 signed review exists, this is a re-review (round 2; delta rules apply). If 0 exist, this is round 1.
5. In post mode, post the "review started" signal per `review.start_signal: reaction` (reaction `eyes`):
   run `gh api -X POST repos/116-Labs/cuecal/issues/<pr>/reactions -f content=eyes`
   (Skip this in preview mode).

### 5. Fetch PR head and set up environment

1. Fetch the PR head and `main` from remote:
   run `git fetch origin pull/<pr>/head`
   run `git fetch origin main`
2. Verify fetched HEAD: run `git rev-parse FETCH_HEAD` and confirm it matches `<head-sha>`. If the remote head moved, re-read PR metadata from step 2 once.
3. Check out the head detached:
   run `git checkout --detach <head-sha>`
4. Environment installation: The profile specifies `install: []` (no install commands). Install nothing; use the checkout's existing environment and run all gates directly in the checkout.

### 6. Focus delta on re-review

1. On a re-review (round 2):
   - Identify `<last-reviewed-head-sha>` from the `Reviewed head: <sha>` line of the newest signed review.
   - Limit attention to the delta since that review:
     run `git diff <last-reviewed-head-sha> <head-sha>`
     or when history was rewritten:
     run `git range-diff <last-base>..<last-reviewed-head-sha> origin/main..<head-sha>`
   - Identify which earlier review threads were answered by this delta.
   - Re-review convergence (`rereview-converges`): After round 1, a new inline thread opens only for a Blocking finding or a contradiction. Other Secondary findings and nits stay in the review body. A non-blocking finding other than a contradiction on lines an earlier round already read is fixed within the auto-fix bound or omitted.

### 7. Run correctness pass over code, scripts, workflows, and skills

1. Inspect the diff against base: run `git diff origin/main...<head-sha>` and inspect all touched files.
2. Evaluate correctness: logic, edge cases, error handling, concurrency, and security.
3. Treat scripts, CI workflows (`.github/workflows/`), and skill files (`.agents/skills/`) as code.
4. Execute the script and workflow checklist:
   - Nonexistent or invalid flags.
   - Word-splitting and quoting issues.
   - Documented but unimplemented options or flags.
   - Shell injection vulnerabilities through untrusted inputs.
   - Non-idempotent re-runs.
   - Swallowed errors or missing error exits.
   - Unverified success inside loops.
5. Record candidate findings with exact file paths and line numbers.

### 8. Run profile gates and record timing

1. The profile specifies `preflight: []` and no advisory checks. Required gates: `lint` and `test`.
2. Run each gate in order on the checkout tree as separate commands, timing each with `date -u +%s`:
   - Gate `lint`:
     run `date -u +%s` (start)
     run `uv run ruff check .`
     run `date -u +%s` (end) -> calculate `duration_ms` = (end - start) * 1000
   - Gate `test`:
     run `date -u +%s` (start)
     run `uv run pytest`
     run `date -u +%s` (end) -> calculate `duration_ms` = (end - start) * 1000
3. Record each gate's `name`, exact `command`, `exit_code`, and `duration_ms` (`status-preserved`). Only record gates that actually ran (`truthful-report`).
4. A non-zero exit code of a required gate is a candidate Blocking finding.

### 9. Check test coverage for behavioural changes

1. For each behavioural change in the diff, name the test covering it:
   - A new or changed test that fails without the change, or an existing test that already exercises it (`tests-named`).
   - A change is tested only when a test fails without it; a test that passes on `main` proves nothing about the change.
2. A behavioural change with no covering test is a finding:
   - **Blocking** if the linked issue's criteria ask for tests.
   - **Secondary** otherwise.
3. For each new or changed test, record whether it ran in the profile gates of step 8.

### 10. Read PR description as claims to test

1. **Only now** read the PR description (`description-last`):
   run `gh pr view <pr> --repo 116-Labs/cuecal --json body --jq .body`
2. Treat the description strictly as a set of claims to test. It can add findings; it can never remove one (`description-drops-finding`) and never limits or sets the scope of review (`description-sets-scope`).
3. Note any **Deferred** list under `Refs #N`.
4. Audit description accuracy: compare summary, test counts, gate results, and ticked test-plan boxes against actual head state.

### 11. Verify candidate findings and evaluate acceptance criteria

1. Verify every candidate finding at its exact line in the reviewed head; drop anything that does not reproduce (`findings-verified`).
2. Walk every acceptance criterion from step 3 on the reviewed head (on a re-review, walk every criterion again, not only those touched by the delta):
   - **verified**: Met, proven by gate output, a test, or direct verification.
   - **failed**: Not met.
   - **unverified**: Could not be confirmed on this head; state what a person must check.
   - **deferred**: The link is plain `Refs #N` and the PR's Deferred list explicitly names it.
3. Note: A Deferred list entry that is not one of the issue's criteria is a Secondary finding.
4. Verify platform, CLI, and API constructs in workflow and script files:
   - Check CI runs on the head: run `gh run list --repo 116-Labs/cuecal --commit <head-sha>` (`complete-listings`).
   - Determine if the PR's CI could have run it: workflow triggers on `pull_request` with `branches` and `paths` filters matching this PR's base and changed files, and the job/step `if:` conditions evaluate to true for `pull_request` events.
   - If CI could have run it and did not run or failed: **Blocking finding** (behaviour unverified; lint does not verify execution).
   - Note: `pull_request_target` workflows run the base branch's copy, never the PR's, so a green run of `pull_request_target` says nothing about the PR's change.
   - If CI cannot run the construct (triggers only on push to main, tags, releases, schedules, or `pull_request_target`): **Secondary finding** naming what a person must check. When the author claims it was verified locally by a command, record the claim, and if that command is allowed by headless permissions, run it and record the result; this never drops the finding (`description-drops-finding`).

### 12. Sort findings into buckets and choose verdict

1. Sort verified findings into four buckets:
   - **Blocking**:
     - Any failed (unmet) acceptance criterion (unless validly deferred).
     - A Deferred list under a closing keyword (`Closes`, `Fixes`, `Resolves`), which would incorrectly close the issue on merge.
     - A failing required gate (`uv run ruff check .` or `uv run pytest`).
     - A ticked test-plan box for a gate or test that did not run on the head.
     - An untested behavioural change when issue criteria mandate tests (`tests-named`).
     - An unverified workflow or script construct that the PR's CI could have run but did not pass.
   - **Secondary**:
     - Unverified acceptance criteria.
     - Untested behavioural change when issue criteria do not mandate tests.
     - Workflow or script construct that CI cannot run for this PR.
     - A Deferred list entry not present in the issue criteria.
     - Code quality, maintainability, or minor edge-case findings.
   - **Nits**: Minor style, naming, or cosmetic improvements.
   - **Pre-existing**: Defects in code this PR did not touch that reproduce on `main`. (Pre-existing defects never open threads, unless the PR makes the defect newly reachable).
2. **Contradictions (`contradiction-fixed-or-threaded`):**
   - Any finding on lines the PR adds that contradicts other code in the PR (a hint, doc, test, error message, or default that disagrees with new behaviour).
   - Contradictions must end either fixed in step 13 or as inline threads in step 15; they are never left only in the review body.
3. **Choose verdict (`verdict-follows-findings`):**
   - ≥ 1 Blocking finding -> `request-changes`.
   - 0 Blocking findings -> `approve` (nits and non-blocking findings may remain).
   - Undecidable / ambiguous requirements -> `comment`.

### 13. Optional auto-fix and single-commit collapse

1. In preview mode: Skip auto-fix and collapse completely.
2. In post mode:
   - With `review.identity.reviewer: separate` configured: push nothing. A token review identity can push and an App's run token cannot, but either way gaal refuses an approval from a review run that pushed, so every fix goes to the author as a finding.
   - In configurations where pushing is permitted (when `review.identity.reviewer` is not separate, `GAAL_LOGIN` is present and matches the PR author's account, `isCrossRepository` is false, and there are zero Blocking findings):
     - Auto-fix bound: Non-behavioural fixes always qualify. A behavioural fix qualifies only if it is in a file the PR touches, has exactly one reasonable form, and comes with a test that fails without it. When in doubt, hand it to the author. Never propose behavioural changes as one-click suggestions (`behavioral-suggestion`).
     - Auto-fix order: Fix -> commit -> fast-forward push -> collapse -> anchors -> post (`collapse-before-approve`, `fixed-not-flagged`).
     - If the remote head moved during review (not an ancestor of local HEAD), abandon auto-fix entirely (`git reset --hard <head-sha>`).
     - Apply single-commit collapse: rewrite in a throwaway worktree `<run-dir>/worktree`, verify tree hash matches pre-collapse tree hash, push with `--force-with-lease=<branch>:<pushed-sha>`, tear down worktree, and update checkout with `git fetch origin <branch>` and `git reset --hard origin/<branch>`. Never `git pull`.
     - A run that pushed a fix posts `comment` instead of `approve` (`no-self-verdict`).

### 14. Compute inline comment anchors

1. Fetch post-push patch hunks:
   run `gh api repos/116-Labs/cuecal/pulls/<pr>/files --paginate` (`complete-listings`)
2. Compute anchors from the right-hand side of patch hunks for un-fixed findings.
3. **Round 1:** Open threads for all Blocking findings, all contradictions, and Secondary findings worth a thread.
4. **Round 2+ (re-review):** Open threads ONLY for Blocking findings and contradictions (`rereview-converges`). All other Secondary findings and nits stay in the review body.
5. Any finding fixed in step 13 gets no inline anchor (`fixed-not-flagged`).
6. After one anchoring failure, re-fetch and re-anchor once; if anchoring fails again, fall back to a body-only review.

### 15. Compose and post review

1. In preview mode: Write the composed review body to `<run-dir>/scratch/review.md` and skip posting.
2. In post mode: Compose the review body and inline comments.
3. **Review body structure (in exact order):**
   - **Verdict line**: First line states the verdict (`APPROVE`, `REQUEST_CHANGES`, or `COMMENT`) and the rule applied (`verdict-follows-findings`).
   - **Findings by bucket**: `### Blocking`, `### Secondary`, `### Nits`, `### Pre-existing`. Each contradiction that was not fixed is carried as an inline thread and listed in its bucket.
   - **Acceptance Criteria**: List every linked issue's criteria with status (`#<issue>: <text> - verified / failed / unverified / deferred`). Never show deferred criteria as met.
   - **Tests section**: List each new or changed test and whether it ran in the profile gates; list each behavioural change with no test (`tests-named`).
   - **Fixed in `<sha>` section**: List fixes pushed in step 13 with their exact sha (`truthful-report`). (Omit or leave empty if no fixes were pushed).
   - **Description accuracy note**: Summary of whether the PR description matched head state.
   - **Reviewed head**: `Reviewed head: <head-sha>` naming the reviewed head sha.
   - **Signature**: Exact signature on its own line: `gaal review-pr · run <run-id>` (`signed-review`).
4. **Review event determination:**
   - A run whose account wrote the PR (`GAAL_LOGIN` equals PR author in any spelling: `<slug>[bot]`, `<slug>`, `app/<slug>`) or pushed a fix posts `COMMENT` with the verdict as the first line, never `APPROVE` or `REQUEST_CHANGES` (`no-self-verdict`).
   - A run that is not the separate review identity, or whose run context names no login (`GAAL_LOGIN` empty or absent), posts `COMMENT` when findings call for approve (`identity-withholds`).
   - The separate review identity (`116-labs-gaal-review[bot]`) posts `APPROVE` when clean and not author.
   - For `request-changes`, any reviewing account that did not write the PR posts `REQUEST_CHANGES`.
   - When the verdict is approve but comment is posted (due to author or identity or pushed fix), the review body says so and notes that the PR is otherwise clean.
5. Write `<run-dir>/scratch/review.json` using the file tool with `commit_id`, `body`, `event`, and `comments` array.
6. Post review:
   run `gh api -X POST repos/116-Labs/cuecal/pulls/<pr>/reviews --input <run-dir>/scratch/review.json`
7. If posting fails, retry once as a body-only review (`gh pr review <pr> --repo 116-Labs/cuecal ...`). If that fails too, end as `failed` naming this step.
8. If the API refuses an approval, do not retry under a different identity (`second-identity-approval`); downgrade to `COMMENT` once and end as `needs-human`.

### 16. List opened threads and resolve own threads

1. Query threads opened by this review:
   - Take the `pull_request_review_id` of the review just posted in step 15.
   - Match threads whose first comment carries that review ID (`complete-listings`).
   - **Stop if review ID is empty:** End `needs-human` with reason "Review ID is empty, cannot list opened threads" (`fail-closed-reads`). Never match by login.
2. For threads opened by this review:
   - If the thread was resolved by this run (recorded only, an agreed trade-off, or filed as a follow-up issue under the follow-up bar): reply to the thread and then resolve it via GraphQL `resolveReviewThread` (`resolve-own-threads-only`).
   - Leave blockers, questions, suggestion blocks, and contradictions open.
   - Follow-up bar: File a follow-up issue ONLY for a user-visible defect outside the diff reproducing on `main`. Everything else is never filed.
   - Never resolve threads to clear the merge path (`resolve-to-unblock`). `threads_block_merge: false`.
3. Report open threads split into suggestions and author-owed.

### 17. Write the run result on every exit path (`run-result-written`)

1. Read finish timestamp: `date -u +%Y-%m-%dT%H:%M:%SZ` as `finished_at`.
2. Construct `<run-dir>/result.json.tmp` using the file tool conforming to the JSON Schema:
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
   - `attempts`: `1`
   - `gates`: array of gate objects (`name`, `command`, `exit_code`, `duration_ms`). Empty array if no gates ran.
   - `branch`: `<branch>` or `null`
   - `commit_sha`: 40-hex sha of reviewed head (or post-fix head) or `null`
   - `review`: (required on `done`):
     - `verdict`: `"approve"`, `"request-changes"`, or `"comment"`
     - `blocking`: integer count of Blocking findings
     - `non_blocking`: integer count of Secondary plus Nits findings
     - `head`: `<head-sha>` (40-hex sha on `Reviewed head:` line)
     - `criteria`: array of every linked issue's criteria in order: `{"text": "#<issue>: <criterion>", "status": "verified" | "failed" | "unverified" | "deferred"}`
     - `approval_withheld`: `"author"`, `"identity"`, or `"pushed"` when findings called for approve but comment was posted
   - `push`: (required when the run pushed to the PR):
     - `why`: string explaining why the run pushed
     - `changes`: string summarizing range-diff or `"tree unchanged"`
   - `started_at`: start timestamp
   - `finished_at`: finish timestamp
3. Atomically move into place: run `mv <run-dir>/result.json.tmp <run-dir>/result.json` (`run-result-written`).
4. Clean up any temporary worktree and restore checkout ref if needed.

## Exit states

- `done`: The review is posted (or written to scratch in preview). `review` carries the verdict and counts. A clean review (no Blocking finding, no thread the author owes) whose approve was posted as comment for identity ends `done` with `review.approval_withheld`, so Gaal can tell it from one that leaves the author work. The final report includes acceptance-criteria results, a description-accuracy note, the thread ledger (open threads split into suggestions and author-owed), and the push or collapse outcome with old → new sha. It also states the inline and body-only finding counts with the reason for any body-only one, a line-anchor fallback if one happened, whose push moved the diff (this review's or the author's), and a branch that is still more than one commit after the collapse (which is an invariant violation).
- `needs-human`: Threads are left for the author (expected when Blocking > 0), whether or not identity downgraded the verdict to comment; the review round limit of 2 is reached (`limits.review_rounds: 2`); or the id of the review just posted was empty, so the threads it opened could not be listed (step 16). `reason` summarizes.
- `needs-clarification`: No PR could be determined, the PR links no issue by the shared issue-link rule, or a linked issue has no checkable acceptance criteria. `questions` say what is missing.
- `failed`: The PR is not open, an API read failed, a verification hook rejected a commit beyond this run's remit, or posting failed even after falling back to a body-only review. `reason` names the step.

## Invariants

- `description-last`: The PR description is read only after the independent passes (correctness, gates, acceptance criteria) have produced findings (steps 2, 10).
- `verdict-follows-findings`: Verdict equals request changes if there is at least one Blocking finding, approve if there are none, and comment when undecidable. The review states the rule applied (steps 12, 15).
- `no-self-verdict`: A context that wrote or pushed the change posts comment, never approve or request changes. That includes a run that pushed a fix to the PR: it never approves code it pushed (steps 13, 15).
- `identity-withholds`: A run that is not the separate review identity, or whose run context names no login (`GAAL_LOGIN` empty or absent), posts comment when the findings call for approve, never approve, with `approval_withheld: author` when its account wrote the PR, else `identity` (steps 13, 15, 17).
- `findings-verified`: Every posted finding was reproduced at its line against the reviewed head (step 11).
- `tests-named`: Every behavioural change in the diff names the test that covers it, or is a finding, Blocking when the issue's criteria ask for tests. The review's Tests section lists each new or changed test and whether it ran in the gates (steps 9, 15).
- `signed-review`: The review body names the reviewed head sha on a `Reviewed head: <sha>` line and ends with the signature `gaal review-pr · run <run-id>` on a line of its own (steps 4, 6, 15).
- `fixed-not-flagged`: A fix pushed by the review appears in the "Fixed in" list and never also as an inline finding (steps 13, 14, 15).
- `resolve-own-threads-only`: Only threads opened by this review (matched by review id, never by login) are resolved, each after a reply (step 16).
- `collapse-before-approve`: Any collapse happens before anchors are computed and before the review is posted (step 13).
- `contradiction-fixed-or-threaded`: A non-blocking finding on lines the PR adds that contradicts other code in the PR is fixed within the auto-fix bound or opened as an inline thread, on a first review and on a re-review. It is never left only in the review body (steps 12, 14, 15).
- `rereview-converges`: After round 1, a new thread opens only for a Blocking finding or a contradiction. Questions go in the review body. A view on another reviewer's open thread goes in the body, never in a second thread. A non-blocking finding other than a contradiction on lines an earlier round already read is fixed within the auto-fix bound or omitted. The review names which of its own earlier threads the delta answered (steps 6, 14).
- `explicit-staging`: Stage only paths this run wrote, taken from a manifest the run keeps. After staging, the working tree has no other changes this run is responsible for. Never stage everything wholesale (steps 1, 13).
- `base-untouched`: Never commit or push to the base branch (`main`) (steps 2, 13).
- `fail-closed-reads`: Tell "the API said there is nothing" apart from "the call failed". Errors, auth expiry and rate limits stop the run. They never become "no PR", "no threads" or "no checks" (steps 2, 3, 4, 16).
- `complete-listings`: Any listing of threads, reviews, comments or checks is either paginated to the end or the run stops. Truncated data is never trusted (steps 3, 4, 11, 14, 16).
- `truthful-report`: The report and run result describe what actually happened. A gate that did not run is absent, not passed. "Fixed in `<sha>`" appears only when that sha contains the fix (steps 8, 15, 17).
- `status-preserved`: A command's success or failure is never lost to a pipe, a filter or a guard. A failed push, gate or API write is seen and handled (steps 2, 8, 17).
- `attribution-policy`: Commit messages and PR bodies follow `commits.attribution: none` from the profile exactly. Nothing is added or dropped on the agent's own initiative (steps 13, 15).
- `run-result-written`: When `GAAL_RUN_DIR` is set, the final step atomically writes `result.json` on every exit path including failures: write `result.json.tmp` in the run directory, then rename it over `result.json`, and never leave the temporary file behind. `reason` is one sentence of at most 160 characters naming the decision or action needed (steps 1, 17).

## Forbidden actions

- `description-sets-scope`: Letting the description or its focus section limit what is reviewed (steps 2, 10).
- `description-drops-finding`: Dropping a verified finding because the description explains it away (steps 10, 11).
- `second-identity-approval`: Approving through another identity, or retrying a refused approval under a different one (step 15).
- `rewrite-foreign-branch`: Pushing to or rewriting a fork's branch or commits authored by someone else (step 13).
- `resolve-to-unblock`: Resolving threads to clear the merge path (step 16).
- `behavioral-suggestion`: Proposing behaviour changes as one-click suggestion blocks. Those go to the author as findings (steps 13, 16).
- `bare-force-push`: Force-pushing without an explicit lease on the sha that was inspected (`--force-with-lease=<branch>:<sha>`) (step 13).
- `admin-bypass`: Merging, pushing or rewriting with admin privileges (`gh pr merge --admin` and the like) to get around branch protection, a merge queue or a verification hook.
- `bypass-hook`: Committing or pushing with the repository's verification skipped or redirected: `--no-verify` (`git commit -n` included), `--no-gpg-sign`, `-c core.hooksPath=…` or any other change to where git looks for hooks, turning a hook manager off, or retrying a rejected commit or push through another route.
- `machine-specific-paths`: Hard-coding a person's home directory, private scripts or services into the generated skill instead of reading them from the profile.
- `commit-foreign-edits`: Committing changes this run did not make (steps 1, 13).
