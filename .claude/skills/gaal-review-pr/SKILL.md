---
name: gaal-review-pr
description: Adversarially reviews an open pull request in 116-Labs/cuecal against its linked issue's acceptance criteria and the profile gates (`uv run ruff check .`, `uv run pytest`), posts exactly one review whose verdict follows from the verified findings, pushes small unambiguous fixes when allowed, and writes the run result to `$GAAL_RUN_DIR/result.json`. Use when a dispatch hands you a repo and PR number and asks for the `review-pr` step. Do not use to implement an issue, open a PR, revise a PR after review, or merge; those are other steps. If no PR can be determined, do not guess; end as `needs-clarification`.
---
<!-- gaal-stamp blueprint=review-pr@1.7.0 shared=1.4.0 profile=7d4c49f36df8465f generated=2026-10-03 core=1324aca6e6892990 forbidden=c5860b98ae1dfd7d content=41dc874a9958eb8f -->

# review-pr (116-Labs/cuecal)

Review an open PR the way a careful maintainer would. Judge it against the linked issue's acceptance criteria and the project's profile gates, independently of how the PR describes itself. Post exactly one review with a verdict that follows directly from the verified findings. Small, unambiguous fixes may be pushed directly so the author only owes answers on what genuinely needs them.

## Run context

- Inputs from dispatch: repo `116-Labs/cuecal`, PR number `<N>`, mode: **post** (default) or **preview** (posts, reacts, pushes and resolves nothing; writes the composed review body to `<run-dir>/scratch/review.md` and records the would-be verdict in the run result).
- `<run-dir>` stands for the literal run directory path from the run context (the value of `GAAL_RUN_DIR`), and `<run-id>` for the literal run id (the value of `GAAL_RUN_ID`). Write them out literally in every command and path; never expand `$GAAL_RUN_DIR` or `$GAAL_RUN_ID` inside a command, and never put `NAME=value` in front of a command.
- Account identity: the run context provides `GAAL_LOGIN` naming the account this run acts as. Take the login from the run context, never from `gh api user` (which returns 403 for GitHub App tokens). Compare it with GitHub logins in any of their three spellings (`<slug>[bot]`, `<slug>`, `app/<slug>`). When `GAAL_LOGIN` is empty or absent, treat the author check as unknown.
- Profile: tracker GitHub; default branch `main`; branch prefix `gaal/`; commits conventional, single commit per PR, attribution `none`; merge method `squash`, queue `false`, `message_source: commits`, auto `false`; review: 1 required approval, `threads_block_merge: false`, `reviewers: []`, start signal `reaction` (`eyes`); gates: `lint` (`uv run ruff check .`) and `test` (`uv run pytest`), both required; `preflight: []`; no `advisory` checks; no `install` commands (install nothing; run gates in the existing checkout environment).
- Limits: `review_rounds` is 2.
- Headless permissions: only `git`, `gh`, `mkdir`, `mv`, `cp`, `ls`, `cat`, `date`, `pwd` with any arguments, and exactly `uv run ruff check .` and `uv run pytest` may be executed. Run one command per call; never chain with `&&`, `;` or `|`. Write files with the file-editing tool, never through shell redirection. Scratch files and throwaway worktrees live inside `<run-dir>`.

## Steps

0. **Start the clock and record starting state.**
   - Run `date -u +%Y-%m-%dT%H:%M:%SZ` and keep the timestamp as `started_at`.
   - Run `pwd` and keep the literal checkout path.
   - Run `git rev-parse --abbrev-ref HEAD` and `git rev-parse HEAD` to record the starting ref and sha.
   - Run `git status --porcelain`. If the checkout has uncommitted changes, do not touch them: end as `needs-human` (`reason`: "Checkout is dirty; clean uncommitted changes and re-run") via step 17.
   - Run `mkdir -p <run-dir>/scratch`.
   - Start an empty manifest at `<run-dir>/manifest.txt` to track any files written into the repo.
   - If no PR number was provided or it cannot be determined from the dispatch, end as `needs-clarification` with a question asking for the PR number.

1. **Read PR metadata without the description (`description-last`, `fail-closed-reads`).**
   - Run `gh pr view <N> --repo 116-Labs/cuecal --json state,baseRefName,headRefName,headRefOid,isCrossRepository,author,files,commits,closingIssuesReferences`.
   - **Do not request `body` or description text in this call** (`description-last`).
   - If the API call fails (network error, auth expiry, rate limit), end as `failed` naming this step (`fail-closed-reads`).
   - If `state` is not `OPEN`, end as `failed` (`reason`: "PR is not open").
   - Record the PR head sha as `<head-sha>`, the head branch name as `<head-branch>`, and the author login.

2. **Extract linked issues and read acceptance criteria fresh.**
   - Apply the issue-link rule without bringing description prose into context.
   - Closing references come from `closingIssuesReferences`. If empty, extract keyword and digits from the body using this exact jq filter:
     `gh pr view <N> --repo 116-Labs/cuecal --json body --jq '[.body | scan("(?im)^[ \\t]*(close|closes|closed|fix|fixes|fixed|resolve|resolves|resolved|refs)[ \\t]*:?[ \\t]*#([0-9]+)")]'`
   - After fetching in step 4, extract issue numbers from commit messages: `git log --format=%B origin/main..<head-sha>`, where a closing keyword (`Closes`, `Fixes`, `Resolves`) takes precedence over a `Refs #N` line. An issue specified in the dispatch takes precedence over PR text.
   - Note per issue whether the link is closing (`Closes`, `Fixes`, `Resolves`) or plain (`Refs`).
   - Read each issue fresh: `gh issue view <issue> --repo 116-Labs/cuecal --comments` (`fail-closed-reads`, `complete-listings`). Comments clarifying or narrowing scope are part of the spec.
   - Write down all acceptance criteria. Only text between `<!-- gaal:plan-drift -->` and `<!-- /gaal:plan-drift -->` (or comments with that marker) is the implementer's plan drift and treated as a claim to test; everything else in the issue body and comments is author/maintainer spec. A PR linking several issues is judged against all of them.
   - If no issue is linked, or the linked issue has no checkable acceptance criteria, end as `needs-clarification` with `questions` stating what is missing.

3. **Check review rounds, identity, and start signal (`complete-listings`, `identity-withholds`).**
   - List prior reviews: `gh api repos/116-Labs/cuecal/pulls/<N>/reviews --paginate` (`complete-listings`).
   - Count prior reviews whose body contains the signature line `gaal review-pr · run ` (never match reviews by reviewer login, as GitHub App logins have multiple spellings).
   - If 2 or more signed reviews already exist (`review_rounds` limit is 2), do not review again: end as `needs-human` (`reason`: "Review round limit of 2 reached").
   - If 1 signed review exists, this run is round 2 (re-review; step 5 applies).
   - In post mode, add the start signal reaction: `gh api -X POST repos/116-Labs/cuecal/issues/<N>/reactions -f content=eyes`. Skip in preview mode.

4. **Fetch remote head and check out detached.**
   - Fetch the latest refs: `git fetch origin pull/<N>/head` and `git fetch origin main`.
   - Confirm `git rev-parse FETCH_HEAD` equals `<head-sha>`. If the remote head moved, re-read metadata from step 1.
   - Check out the head detached: `git checkout --detach <head-sha>`.
   - The profile defines no `install` commands: install nothing and run the gates in the checkout's existing environment.

5. **Re-review delta on round 2 (`rereview-converges`).**
   - On a re-review (round 2), find the newest prior review carrying `gaal review-pr · run ` and extract its `Reviewed head: <last-sha>`.
   - Limit attention to what changed since `<last-sha>`: run `git diff <last-sha> <head-sha>`, or `git range-diff origin/main..<last-sha> origin/main..<head-sha>` if history was rewritten.
   - Note which earlier review threads the delta answered.
   - On a re-review, only Blocking findings and contradictions open new inline threads (`rereview-converges`); other secondary findings and nits stay in the review body to ensure the loop converges.

6. **Run correctness pass over the diff.**
   - Inspect `git diff origin/main...<head-sha>` and all touched files.
   - Evaluate logic, edge cases, error handling, concurrency, and security. Scripts, workflows, and skill files count as code.
   - Checklist for scripts and workflows: check for nonexistent flags, word-splitting/quoting bugs, documented but unimplemented flags, injection vulnerabilities, non-idempotent re-runs, swallowed errors, and unverified loop success.
   - Record candidate findings with exact file paths and line numbers.

7. **Run profile gates (`gates-green`, `truthful-report`, `status-preserved`).**
   - `preflight: []` is empty (no preflight checks). Run each required gate in order, timing each with the system clock:
     1. Run `date -u +%s`, then `uv run ruff check .`, then `date -u +%s`. Record gate `lint`: command `uv run ruff check .`, exit code, and `duration_ms` = (end - start) * 1000.
     2. Run `date -u +%s`, then `uv run pytest`, then `date -u +%s`. Record gate `test`: command `uv run pytest`, exit code, and `duration_ms` = (end - start) * 1000.
   - Both gates are required. A non-zero exit code produces a Blocking candidate finding quoting the failure output.
   - A gate that did not run must remain absent from the result, never reported as passed (`truthful-report`).

8. **Check test coverage for behavioural changes (`tests-named`).**
   - For every behavioural change in the diff, identify the test covering it: a new/changed test that fails without the change, or an existing test exercising it.
   - A behavioural change without covering tests is a finding: Blocking if the issue criteria require tests, Secondary otherwise.
   - For each new or changed test, record whether it ran and passed in step 7's test gate.

9. **Read the description only now (`description-last`, `description-sets-scope`, `description-drops-finding`).**
   - Run `gh pr view <N> --repo 116-Labs/cuecal --json body --jq .body`.
   - Read the description strictly as a set of claims to test. It can add findings; it can never remove a finding or restrict review scope.
   - Note its **Deferred** list, if any, and evaluate description accuracy.

10. **Verify candidate findings and walk acceptance criteria (`findings-verified`).**
    - Verify every candidate finding at its exact line on the reviewed head. Drop any candidate that does not reproduce.
    - Walk every acceptance criterion from step 2 one by one on the reviewed head (on re-reviews, evaluate all criteria, not only touched ones):
      - `verified`: confirmed met by a gate, test, or check run on this head.
      - `failed`: confirmed not met.
      - `unverified`: cannot be confirmed on this head; specify what a human must check.
      - `deferred`: allowed only when the PR uses a plain link (`Refs #N`) and lists the criterion under **Deferred**. A deferred entry not present in the issue criteria is a Secondary finding.

11. **Sort findings and check platform/workflow constructs (`contradiction-fixed-or-threaded`, `description-drops-finding`).**
    - Sort findings into **Blocking**, **Secondary**, **Nits**, and **Pre-existing**:
      - **Blocking**: failed criteria (unless deferred); failing required gates; a Deferred list under a closing keyword (`Closes`, `Fixes`, `Resolves`); ticked test-plan boxes for gates that did not run on the head; unverified workflow/script changes where PR CI could have run the step but did not run or failed.
      - **Secondary**: unverified criteria; workflow/script changes that PR CI cannot run (`pull_request_target`, push-to-base, release triggers); unverified claims in the description; deferred entries not in issue criteria.
      - **Nits**: minor style, documentation, or non-blocking polish.
      - **Pre-existing**: issues existing on `main` before this PR; pre-existing defects never open threads unless this PR makes them reachable.
    - **Contradictions**: any finding on lines added by this PR that contradicts other code, docs, hints, tests, or defaults in the PR. Contradictions must end either auto-fixed in step 13 or as an inline thread in step 15 (`contradiction-fixed-or-threaded`), never only in the review body.
    - **Workflow CI Verification**: inspect workflow `on:` and `if:` conditions and run `gh run list --commit <head-sha>`. If a changed workflow triggers on `pull_request` matching base and paths and CI failed or did not run, it is Blocking. If it triggers on `pull_request_target` or non-PR events, it is Secondary (unverified) naming what a human must check. An author's claim of local verification does not drop the finding (`description-drops-finding`).

12. **Choose the review verdict (`verdict-follows-findings`).**
    - If there is at least one Blocking finding → verdict is `request-changes`.
    - If there are zero Blocking findings → verdict is `approve` (nits and non-blocking secondary findings may remain).
    - If undecidable → verdict is `comment`.
    - The review body explicitly states the rule applied.

13. **Optional auto-fix, commit, push, and collapse (`collapse-before-approve`, `no-self-verdict`, `rewrite-foreign-branch`, `behavioral-suggestion`, `bare-force-push`, `bypass-hook`, `base-untouched`).**
    - In preview mode, skip auto-fix entirely.
    - Auto-fix qualifies only when all hold:
      1. Zero Blocking findings.
      2. `isCrossRepository` is false (not a fork).
      3. `GAAL_LOGIN` is present and matches the author of every commit on `origin/main..<head-sha>` (`git log --format=%an origin/main..<head-sha>`). Never rewrite someone else's branch (`rewrite-foreign-branch`).
      4. Reviewer identity is not configured as `separate`.
    - Scope bound: non-behavioural fixes always qualify. Behavioural fixes qualify only if in a touched file, with exactly one reasonable form, and accompanied by a test failing without it (`behavioral-suggestion`). Otherwise hand to the author.
    - If qualifying fixes exist:
      - Record restore point `<head-sha>`. Add every modified file path to `<run-dir>/manifest.txt`.
      - Stage only manifest paths: `git add <path>` (`explicit-staging`).
      - Re-run both gates (`uv run ruff check .`, `uv run pytest`), timing each. If either fails, revert manifest paths (`git restore <path>`) and treat as findings.
      - Write conventional commit message without attribution to `<run-dir>/fix-msg.txt` (`attribution-policy`: `none`).
      - Commit with `git commit -F <run-dir>/fix-msg.txt` (hooks stay enabled; `bypass-hook`).
      - Check remote head: `git fetch origin <head-branch>`. Confirm remote tip is an ancestor: `git merge-base --is-ancestor <remote-tip> HEAD`. If remote moved, abandon auto-fix and revert.
      - Push fix: `git push origin HEAD:<head-branch>`. Never push to `main` (`base-untouched`).
      - **Collapse routine** (`collapse-before-approve`, PR mode, `message_source: commits`):
        - If `git rev-list --count origin/main..HEAD` <= 1, collapse is not needed.
        - If > 1 commit: read remote head `<pushed-sha>`.
        - Create throwaway worktree: `git worktree add --detach <run-dir>/worktree <pushed-sha>`.
        - `cd <run-dir>/worktree`
        - Find merge base: `git merge-base origin/main HEAD`.
        - Capture tree hash: `git rev-parse HEAD^{tree}`.
        - Soft-reset: `git reset --soft <merge-base-sha>`.
        - Write single whole-change message to `<run-dir>/collapse-msg.txt` (conventional, process commits dropped, attribution `none`, issue link `Closes #N` or `Refs #N` with **Deferred** list).
        - Commit: `git commit -F <run-dir>/collapse-msg.txt`.
        - Confirm `git rev-parse HEAD^{tree}` matches pre-collapse tree hash and tree is non-empty.
        - Push with lease: `git push origin HEAD:<head-branch> --force-with-lease=<head-branch>:<pushed-sha>` (`bare-force-push`).
        - `cd` back to the checkout path and clean worktree: `git worktree remove --force <run-dir>/worktree`.
      - Update `<head-sha>` to `git rev-parse HEAD`. A run that pushed a fix posts `COMMENT` instead of `APPROVE` (`no-self-verdict`).

14. **Compute inline anchors from post-push hunks (`complete-listings`, `fixed-not-flagged`, `rereview-converges`).**
    - Fetch post-push patch hunks: `gh api repos/116-Labs/cuecal/pulls/<N>/files --paginate` (`complete-listings`).
    - Compute inline anchors from the right-hand side of patch hunks for un-fixed findings.
    - On round 1: anchor every Blocking finding, every contradiction, and noteworthy Secondary findings.
    - On round 2+ (re-review): anchor only Blocking findings and contradictions (`rereview-converges`); other findings go into the review body.
    - Findings fixed in step 13 receive no inline anchor (`fixed-not-flagged`).
    - If anchoring fails, re-fetch and retry once; if it fails again, fall back to a body-only review.

15. **Compose and post the review (`signed-review`, `no-self-verdict`, `identity-withholds`, `second-identity-approval`).**
    - Compose the review body with the file-editing tool:
      1. Verdict as the first line plus the rule applied.
      2. Findings grouped by bucket (Blocking, Secondary, Nits, Pre-existing), carrying contradictions as inline threads and listing them in their bucket.
      3. Acceptance Criteria results table/list, with each criterion marked `verified`, `failed`, `unverified`, or `deferred` (never mark deferred as met).
      4. **Tests** section: list each new/changed test and whether it ran in gates, and note behavioural changes without tests (`tests-named`).
      5. "Fixed in `<sha>`" section (if fixes were pushed; `truthful-report`).
      6. Description accuracy note.
      7. `Reviewed head: <head-sha>` naming the reviewed head sha.
      8. Exact signature line on its own line: `gaal review-pr · run <run-id>`.
    - In preview mode: write the composed review body to `<run-dir>/scratch/review.md` and proceed to step 17.
    - Determine GitHub review event:
      - If verdict is `request-changes`: post `REQUEST_CHANGES` (if author matches login, post `COMMENT` per `no-self-verdict`).
      - If verdict is `approve`:
        - If `GAAL_LOGIN` wrote the PR, or this run pushed a fix (`no-self-verdict`), or the run is not the separate review identity / login is absent (`identity-withholds`): post `COMMENT`, stating that the PR is clean and approval is withheld due to author/identity/pushed status.
        - Otherwise post `APPROVE`.
      - If verdict is `comment`: post `COMMENT`.
    - Write payload `<run-dir>/review.json` and post: `gh api -X POST repos/116-Labs/cuecal/pulls/<N>/reviews --input <run-dir>/review.json`.
    - If API refuses approval, do not retry under another identity (`second-identity-approval`): downgrade event to `COMMENT` and note approval withheld.
    - If posting fails, retry once as a body-only review; if that fails too, end as `failed`.

16. **Manage review threads (`resolve-own-threads-only`, `resolve-to-unblock`).**
    - In preview mode, skip this step.
    - Retrieve the ID of the review just posted (`pull_request_review_id` from the API response).
    - **If the review ID is empty, stop immediately**: end as `needs-human` (`reason`: "Posted review ID was empty; cannot safely identify opened threads") without modifying threads (`resolve-own-threads-only`).
    - List PR review threads (`complete-listings`). Filter for threads whose root comment belongs to the posted review ID.
    - For threads that this review resolved itself (e.g. recorded observations, agreed trade-offs):
      - Reply: `gh api -X POST repos/116-Labs/cuecal/pulls/<N>/comments/<comment-id>/replies -f body="Resolved by review run <run-id>."`.
      - Resolve: `gh api graphql -f query='mutation { resolveReviewThread(input: {threadId: "<thread-id>"}) { thread { id } } }'`.
    - Leave open all author-owed questions, blockers, suggestion blocks, and contradiction threads (`resolve-to-unblock`).
    - Report open threads categorized into suggestions and author-owed items.

17. **Restore checkout and write run result (`run-result-written`, `truthful-report`).**
    - Clean up any temporary worktree (`git worktree remove --force <run-dir>/worktree`).
    - Restore starting ref (`git checkout <starting-ref>`) unless a pushed commit is the intended branch state.
    - Run `date -u +%Y-%m-%dT%H:%M:%SZ` and keep as `finished_at`.
    - With the file tool, write `<run-dir>/result.json.tmp`, then run `mv <run-dir>/result.json.tmp <run-dir>/result.json` (`run-result-written`). Never leave `.tmp` files behind.

## Run result

The result file at `<run-dir>/result.json` must be valid against the run-result schema:
- `schema_version`: `1`
- `run_id`: literal run id from run context
- `blueprint`: `"review-pr"`
- `blueprint_version`: `"1.7.0"`
- `repo`: `"116-Labs/cuecal"`
- `issue`: first linked issue number (integer) or `null`
- `pr`: PR number (integer) or `null`
- `status`: `"done"` | `"needs-human"` | `"needs-clarification"` | `"failed"`
- `reason`: required unless `status` is `"done"`; single sentence of at most 160 characters describing the decision or action needed.
- `questions`: required non-empty array of strings when `status` is `"needs-clarification"`.
- `attempts`: `1`
- `gates`: array of gate executions actually run on the head, each with `name`, `command`, `exit_code`, `duration_ms`.
- `branch`: head branch name (string) or `null`
- `commit_sha`: 40-hex sha of pushed fix or `null`
- `review`: object present when a review was completed (required for `done`):
  - `verdict`: `"approve"` | `"request-changes"` | `"comment"`
  - `blocking`: integer count (>= 0)
  - `non_blocking`: integer count (>= 0; sum of Secondary and Nits)
  - `head`: 40-hex sha from `Reviewed head:` line
  - `criteria`: array of `{ "text": "#<issue>: <criterion>", "status": "verified" | "failed" | "unverified" | "deferred" }` covering every linked issue's criteria in order.
  - `approval_withheld`: `"author"` | `"identity"` | `"pushed"` (present when verdict called for approve but comment was posted).
- `push`: optional object `{ "why": "<string>", "changes": "<string>" }` if a fix was pushed.
- `started_at`, `finished_at`: ISO 8601 UTC timestamps from `date`.

Example `result.json`:

```json
{
  "schema_version": 1,
  "run_id": "<run-id>",
  "blueprint": "review-pr",
  "blueprint_version": "1.7.0",
  "repo": "116-Labs/cuecal",
  "issue": 12,
  "pr": 34,
  "status": "done",
  "attempts": 1,
  "gates": [
    {
      "name": "lint",
      "command": "uv run ruff check .",
      "exit_code": 0,
      "duration_ms": 1100
    },
    {
      "name": "test",
      "command": "uv run pytest",
      "exit_code": 0,
      "duration_ms": 7800
    }
  ],
  "branch": "gaal/12-add-feature",
  "commit_sha": null,
  "review": {
    "verdict": "approve",
    "blocking": 0,
    "non_blocking": 1,
    "head": "0123456789abcdef0123456789abcdef01234567",
    "criteria": [
      {
        "text": "#12: CLI emits JSON when --json is passed",
        "status": "verified"
      }
    ]
  },
  "started_at": "2026-10-02T23:00:00Z",
  "finished_at": "2026-10-02T23:04:00Z"
}
```

## Exit states

- `done`: The review is posted (or written to `<run-dir>/scratch/review.md` in preview). `review` carries verdict, finding counts, `head` sha, and full `criteria` list. The final report includes acceptance criteria status, description accuracy, thread ledger (open threads split into suggestions and author-owed), push/collapse summary with old → new sha, inline vs body-only counts, and line-anchor fallback status.
- `needs-human`: Action required from a human: open threads left for author (expected when Blocking > 0); review ID was empty after posting review; review round limit (2) was reached; or checkout was dirty at start. `reason` summarizes.
- `needs-clarification`: No PR could be determined, the PR links no issue by the issue-link rule, or a linked issue has no checkable acceptance criteria. `questions` list specific missing requirements.
- `failed`: PR is not open; API read/listing failed (`fail-closed-reads`); hook rejected a commit/push beyond this run's remit; or review posting failed after all fallbacks. `reason` names the failing step.

## Invariants

- `description-last`: The PR description is read only after independent passes (correctness, gates, acceptance criteria) have produced candidate findings.
- `verdict-follows-findings`: Verdict is `request-changes` if >= 1 Blocking finding, `approve` if 0 Blocking findings, and `comment` when undecidable. The review states the rule applied.
- `no-self-verdict`: An account that wrote or pushed the change posts `comment`, never `approve` or `request-changes`, including runs that pushed an auto-fix.
- `identity-withholds`: A run that is not the separate review identity, or whose run context lacks `GAAL_LOGIN`, posts `comment` when findings call for approve, with `approval_withheld: author` or `identity`.
- `findings-verified`: Every posted finding is reproduced at its exact line against the reviewed head.
- `tests-named`: Every behavioural change in the diff names the test covering it, or is raised as a finding. The Tests section lists all new/changed tests and whether gates ran them.
- `signed-review`: The review body names the reviewed head sha on a `Reviewed head: <sha>` line and ends with the exact signature `gaal review-pr · run <run-id>` on its own line.
- `fixed-not-flagged`: A fix pushed by this review appears in the "Fixed in" list and never as an unresolved inline finding.
- `resolve-own-threads-only`: Only threads opened by this review run (matched by review ID, never by login) and resolved by this run are resolved.
- `collapse-before-approve`: Any branch collapse happens before anchors are computed and before the review is posted.
- `contradiction-fixed-or-threaded`: A finding on lines added by the PR that contradicts other code in the PR is auto-fixed or opened as an inline thread; it is never left only in the review body.
- `rereview-converges`: On round 2+, new inline threads open only for Blocking findings and contradictions. Non-blocking findings stay in the review body.
- `explicit-staging`: Stage only paths explicitly tracked in the run's manifest; never stage wholesale.
- `base-untouched`: Never commit or push to `main`.
- `fail-closed-reads`: API errors, auth failures, and rate limits stop the run; they never become "no PR", "no threads", or "no checks".
- `complete-listings`: Paginate all listings of reviews, comments, and files to the end or stop.
- `truthful-report`: The report and run result describe only what actually occurred; unrun gates are omitted, not marked passed.
- `status-preserved`: Command exit codes are never masked or lost to pipes or filters.
- `attribution-policy`: Attribution policy is `none`; no AI attribution or extra trailers are added to commit messages or PR text.
- `run-result-written`: Write `result.json` atomically via `result.json.tmp` on every exit path, including early failures.

## Forbidden actions

- `description-sets-scope`: Letting the PR description or its focus section restrict what code or criteria are reviewed.
- `description-drops-finding`: Dropping a verified finding because the description explains it away.
- `second-identity-approval`: Approving through another identity or retrying a refused approval under a different identity.
- `rewrite-foreign-branch`: Pushing to or rewriting a fork or commits authored by someone else.
- `resolve-to-unblock`: Resolving review threads simply to clear the merge path.
- `behavioral-suggestion`: Offering behavioural changes as one-click suggestion blocks instead of reporting them as findings to the author.
- `bare-force-push`: Force-pushing without an explicit lease on the inspected sha (`--force-with-lease=<head-branch>:<sha>`).
- `admin-bypass`: Using admin privileges (`--admin`) to bypass branch protection, merge rules, or verification hooks.
- `bypass-hook`: Committing or pushing with verification skipped (`--no-verify`, `git commit -n`, `--no-gpg-sign`, `core.hooksPath`).
- `machine-specific-paths`: Hard-coding local user paths, home directories, drive letters, or private tools.
- `commit-foreign-edits`: Committing changes this run did not make.
