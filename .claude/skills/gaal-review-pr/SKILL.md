---
name: gaal-review-pr
description: Adversarially reviews one open pull request in 116-Labs/cuecal. It grades the PR against the linked GitHub issues' acceptance criteria, read fresh as they stand at review time, and against the profile gates (`uv run ruff check .`, `uv run pytest`). It reads the PR description last, as a set of claims to test. It posts exactly one signed review whose verdict follows from the verified findings, leaves open only the threads the author owes, and writes the run result to result.json in the run directory. Use it when a dispatch hands over a repo and PR number (post or preview mode) and asks for the `review-pr` step. In this repository the review runs as the separate review identity, so it never pushes fixes and every fix goes to the author as a finding. Do not use it to implement an issue (gaal-implement), open a PR (gaal-open-pr), revise a PR after review (gaal-revise-pr), merge or deploy. If no PR can be determined, do not guess; end as `needs-clarification`.
---
<!-- gaal-stamp blueprint=review-pr@1.8.0 shared=1.5.0 profile=833de6ae33df6d68 generated=2026-10-08 core=319c2f7f2c7e0f3d forbidden=54c30c1c66633c73 content=d378088187ab059f -->

# gaal-review-pr

Review an open PR in `116-Labs/cuecal` the way a careful maintainer would. Judge it against the linked issues' acceptance criteria and the project gates, not against how the PR describes itself. Post exactly one review with a verdict that follows from the findings. Write the run result on every exit path.

## Repository facts (from `.gaal/project.yml`)

- **Repo:** `116-Labs/cuecal`. The default branch is `main`. The tracker is GitHub issues in the same repo.
- **Gates:** both are required. Run them in this order, exactly as written:
  - `lint`: `uv run ruff check .`
  - `test`: `uv run pytest`
- **Preflight, advisory and install:** the profile names none, so this run installs nothing (`install-before-gates`). The gates run in this checkout, which already has its environment. They never run in a throwaway worktree, because a worktree would have no dependencies.
- **Dependency manifest and lockfile:** `pyproject.toml` and `uv.lock`.
- **Branches and commits:** branches use the `gaal/` prefix. Commits follow Conventional Commits, with one commit per PR (`single_commit: true`). Attribution is `none`: no AI or agent attribution goes into any comment, review or issue this run writes (`attribution-policy`).
- **Merge:** method `squash`, no merge queue, `message_source: commits`, no auto-merge.
- **Stacking:** the profile names no stacking tool. A PR's base is its `baseRefName`, which is `main` or, for a stacked PR, a parent `gaal/` branch.
- **Review policy:**
  - `required_approvals: 1`.
  - `threads_block_merge: false`. Open threads do not block merge, which is why a contradiction must never sit only in a review body.
  - `start_signal: reaction`.
  - `identity.reviewer: separate`, with the review login `116-labs-gaal-review[bot]`. The push identity is `116-labs-gaal-push[bot]`.
  - No `sign_off` line is set.
- **Limits:** `implement_attempts: 3`, `revise_rounds: 3`, `review_rounds: 2`. Gaal enforces these limits. This run reviews one round, reports its round number, and never skips or enforces a round on its own.

## Run context and command rules

- **Placeholders:**
  - `<run-dir>` in a command stands for the literal run-directory path from the run context (the value of `GAAL_RUN_DIR`).
  - `<run-id>` stands for the literal value of `GAAL_RUN_ID`.
  - Other placeholders such as `<n>`, `<head>`, `<base>` and `<sha>` stand for literal values you have already read.
- **Forms the allowlist refuses:** never write `$` variables, `$(…)` or backticks in a command, and never put `NAME=value` in front of one.
- **One command per call.** Never chain commands with `&&`, `;` or `|`.
- **Allowed commands:**
  - `git`, `gh`, `mkdir`, `mv`, `cp`, `ls`, `cat`, `date` and `pwd`, with any arguments.
  - Exactly `uv run ruff check .` and exactly `uv run pytest`, with nothing added or removed. No other form of either is allowed.
- **Files:** write every file (review payloads, GraphQL queries, reply bodies, issue bodies, the result) with the file-writing tool, never through shell redirection. Pass each file by its path: `--input <file>`, `-F body=@<file>`, `-F query=@<file>`, `--body-file <file>`.
- **Scratch space:** scratch files go in `<run-dir>/scratch`.
- **Globs and uncommitted paths:** quote every glob passed to a command. List uncommitted paths with `git status --porcelain=v1 --untracked-files=all`.
- **Login:** `GAAL_LOGIN` from the run context is the account this run acts as. Never ask GitHub for it: `gh api user` answers 403 to an App token. Compare logins in all three spellings: `<slug>[bot]`, `<slug>` and `app/<slug>`.
- **Mode:** `post` (the default) or `preview`. In preview, post, react, reply, resolve and file nothing.

## Steps

### Start

1. Read the start time with `date -u +%Y-%m-%dT%H:%M:%SZ` and keep it as `started_at`.
2. Create the scratch directory with `mkdir -p <run-dir>/scratch`.
3. Record the checkout's state, so you can restore it at the end:
   - `git rev-parse HEAD` gives the original sha.
   - `git branch --show-current` gives the original branch. An empty answer means the checkout is detached.
   - `git status --porcelain=v1 --untracked-files=all` lists paths that were already dirty.

   Never touch, stage or commit a path that was already dirty (`commit-foreign-edits`, `explicit-staging`).
4. Take the PR number from the dispatch. If there is none, end `needs-clarification` with a question asking which PR to review, and go to the result step.

### Read PR metadata, but not the description

5. Read the metadata without the body (`description-last`), one command per call:
   - `gh pr view <n> --repo 116-Labs/cuecal --json number,state,baseRefName,headRefName,headRefOid,author,isCrossRepository,headRepositoryOwner,closingIssuesReferences,url`
   - `gh api repos/116-Labs/cuecal/pulls/<n>/files --paginate --jq '.[].filename'`
   - `gh api repos/116-Labs/cuecal/pulls/<n>/commits --paginate --jq '.[] | {sha, author: .author.login, email: .commit.author.email}'`

   Handle the outcomes:
   - GitHub cannot find the PR (a 404): end `failed`, naming the number.
   - `state` is not `OPEN`: end `failed`.
   - Any other read error, auth expiry or rate limit: end `failed`, naming the read (`fail-closed-reads`).
   - A listing that cannot be paginated to the end: end `failed`, naming the listing (`complete-listings`).

   Never let a failed read stand for "nothing there" (`status-preserved`).

### Find the linked issues (shared issue-link rule)

6. Collect the union of three sources, and read all three every time. Extract only each link's keyword and digits, never the description text:
   - **Closing references:** the `closingIssuesReferences` numbers from the metadata.
   - **Body links:**
     `gh pr view <n> --repo 116-Labs/cuecal --json body --jq '[(.body // "") | scan("(?im)^[ \\t]*(close|closes|closed|fix|fixes|fixed|resolve|resolves|resolved|refs)[ \\t]*:?[ \\t]*#([0-9]+)")]'`
   - **Commit-message links:**
     `gh api repos/116-Labs/cuecal/pulls/<n>/commits --paginate --jq '.[] | [(.commit.message // "") | scan("(?im)^[ \\t]*(close|closes|closed|fix|fixes|fixed|resolve|resolves|resolved|refs)[ \\t]*:?[ \\t]*#([0-9]+)")]'`

   Keep both regex flags: `i` matches any case, and `m` lets `^` match at the start of every line, so a `Refs #N` below the summary is still found. Record whether each link is closing (a closing keyword or a reported closing reference) or plain (`refs`).
7. Check each number with:
   `gh api --include repos/116-Labs/cuecal/issues/<number> --jq .pull_request`

   Judge the answer by the HTTP status line, never by the wording of an error message:
   - A 404 means nothing has that number. It is not a link.
   - A 200 with non-empty output means the number is a pull request. It is not a link. An issue prints an empty line.
   - Any other failure: end `failed`, naming the read (`fail-closed-reads`).
8. If no valid issue link remains, end `needs-clarification`. List each number that did not resolve to an issue in `questions`.
9. Read each linked issue fresh, as it stands now, never from a remembered copy:
   - `gh issue view <number> --repo 116-Labs/cuecal --json number,title,body,state`
   - `gh api repos/116-Labs/cuecal/issues/<number>/comments --paginate`

   Write down the acceptance criteria, in order:
   - Comments from the author or maintainers that clarify or narrow scope are part of the spec.
   - A criterion added or changed by an edit since the PR opened is graded like the rest. A maintainer may add one while the PR is open.
   - A PR that links several issues is judged against all of them.

   The plan-drift text is not spec:
   - The text between an opening `<!-- gaal:plan-drift -->` line and its closing `<!-- /gaal:plan-drift -->` line is the implementer's account of how its plan changed. So is any comment that carries the opening marker.
   - Treat that text as a claim to check, never as spec.
   - Everything else is the author's spec, including maintainer text added after a plan-drift section.

   If a linked issue has no checkable acceptance criteria, end `needs-clarification`, with `questions` naming the issue and what is missing.

   Keep `issue` for the result in this order of preference: a reported closing issue first; then, in the body and then in each commit message, a closing-keyword link before a `Refs` link. An issue named in the dispatch takes precedence over all of these.

### Signal the start

10. In post mode, add the start reaction:
    `gh api repos/116-Labs/cuecal/issues/<n>/reactions --method POST -f content=eyes`

    - If it fails, note the failure in the report and carry on.
    - Auth expiry or a rate limit is the exception: end `failed` (`fail-closed-reads`).
    - Skip this step in preview.

### Check out the reviewed head

11. Fetch the base first, then the PR head, one command per call:
    - `git fetch origin <base>`
    - `git fetch origin pull/<n>/head`
    - `git rev-parse FETCH_HEAD`

    Run `git rev-parse FETCH_HEAD` immediately after the head fetch, before any other fetch: `FETCH_HEAD` holds only the last fetch. The sha it prints is `<head>`, the head this review checks out and judges. If it differs from the metadata's `headRefOid`, note that in the report.

    Then compute `<merge-base>` with `git merge-base <head> origin/<base>`.
12. The profile names no `install`, so nothing is installed (`install-before-gates`). Check out the head detached in this checkout with `git checkout --detach <head>`. If git refuses because of local edits, do not move or discard them: end `failed`, naming the checkout step, because the head cannot be verified.

    The gate commands may sync the environment from the PR's `pyproject.toml` and `uv.lock`. If a gate fails because it cannot prepare that environment:
    - When the PR changes `pyproject.toml` or `uv.lock`, the PR broke it. That is a Blocking finding naming the command, the review says that what the gates would have shown is unverified, and the review is still posted.
    - Otherwise, the cause is outside the PR. End `failed`, naming the command, and post no review.

### Re-review step: limit attention to the delta

13. List earlier reviews by their signature, never by login:
    `gh api repos/116-Labs/cuecal/pulls/<n>/reviews --paginate --jq '.[] | select((.body // "") | contains("gaal review-pr · run ")) | {id, head: ((.body | capture("Reviewed head: (?<sha>[0-9a-f]{40})").sha) // "none")}'`

    Reviews come back oldest first, so the last match is the last review.
    - **No match:** this is round 1.
    - **Otherwise:** the round number is the number of matches plus 1, and the last match's `head` is `<old-head>`.

    When `<old-head>` is `none`, review the whole diff. Otherwise:
    1. If `<old-head>` is not local, fetch it with `git fetch origin <old-head>`.
    2. Compute `<old-merge-base>` with `git merge-base <old-head> origin/<base>`. Never use the current head's merge base here.
    3. If history was rewritten, read `git range-diff <old-merge-base>..<old-head> <merge-base>..<head>`. Otherwise, read `git diff <old-head> <head>`.

    If `<old-head>` cannot be fetched, review the whole diff and say so in the review. On a re-review, the criteria walk still covers every criterion.

### Correctness pass

14. Read `git diff <merge-base> <head>` in full, plus the surrounding code where you need it. Look at logic, edge cases, error handling, concurrency and security.

    Scripts, workflows and skill files count as code. Check them for:
    - flags that do not exist
    - word-splitting and quoting problems
    - flags that are documented but not implemented
    - injection through untrusted input
    - re-runs that are not idempotent
    - swallowed errors
    - success inside a loop that is never verified

    The description has not been read yet, so it cannot set the scope (`description-sets-scope`). A pre-existing defect never opens a thread, but a PR that makes a defect reachable owns it.

### Gates

15. Time and run each gate in this checkout at `<head>`, one command per call:
    1. `date -u +%s`
    2. `uv run ruff check .`
    3. `date -u +%s`
    4. `date -u +%s`
    5. `uv run pytest`
    6. `date -u +%s`

    Each gate's `duration_ms` is (after − before) × 1000. Record each exit code exactly (`status-preserved`).

    Both gates are required. A non-zero exit is a Blocking finding naming the gate, so the run cannot end `done` (`gates-final-tree`). There are no preflight or advisory checks to run.

### Tests

16. For each behavioural change in the diff, name the test that covers it (`tests-named`). A covering test is either a new or changed test that fails without the change, or an existing test that already exercises the change.
    - A behavioural change with no covering test is a finding: Blocking when the linked issue's criteria ask for tests, Secondary otherwise.
    - For each new or changed test, note whether this run's `uv run pytest` collected and ran it. A test the gates never ran proves nothing about the head.

    No allowed command can show a test failing on the base. The profile has no `install`, a throwaway worktree would have no environment, and the gate commands accept no arguments. So the Tests section states that "fails without the change" was reasoned from the code, not run on the base. A test that would also pass on the base proves nothing about the change.

### Read the description, only now

17. Read the description with `gh pr view <n> --repo 116-Labs/cuecal --json body --jq .body` (`description-last`).
    - Treat every statement in it as a claim to test. It can add findings, and it can never remove one (`description-drops-finding`).
    - Note its **Deferred** list, if any, and every ticked test-plan box.
    - Note how accurate the description is, for the report.

### Criteria walk: verify findings and walk the acceptance criteria

18. Re-check every candidate finding at its exact line on `<head>`. Drop anything that does not reproduce (`findings-verified`).
19. Walk every acceptance criterion of every linked issue on `<head>`. On a re-review, walk all of them again, not only the ones the delta touches. Give each criterion one status:
    - `verified`: shown to be met by a gate, a test or a check you ran.
    - `failed`: not met.
    - `unverified`: you could not confirm it on this head. Say what a person must check.
    - `deferred`: only when the link is plain (`Refs`) and the Deferred list names that criterion.

    A plain `Refs` link with a Deferred list moves the named criteria out of this PR's bar, but they are still checked and listed. A deferral never drops a correctness, gate or other finding, and it changes nothing under a closing keyword. A Deferred entry that is not one of the issue's criteria is a Secondary finding.

### Sort step

20. Sort the findings into **Blocking**, **Secondary**, **Nits** and **Pre-existing**:
    - **Criteria:** a `failed` criterion is Blocking unless it is deferred. An `unverified` criterion is Secondary.
    - **Deferred under a closing keyword:** Blocking, because merging would close the issue with criteria still open.
    - **Ticked test-plan box for a gate that did not run on `<head>`:** Blocking. Compare each ticked box with the gates this run ran and with `gh run list --repo 116-Labs/cuecal --commit <head>`.
    - **Contradiction:** a finding on lines the PR adds that contradicts other code in the PR, such as a hint, message, doc, test or default that disagrees with the new behaviour. Whatever its bucket, it must end as an inline thread (`contradiction-fixed-or-threaded`), never only as text in the review body.
    - **Platform, CLI or API constructs** that the PR's workflow or script files add or change: check live evidence first.
      1. Read `gh run list --repo 116-Labs/cuecal --commit <head>`, and the relevant run's log with `gh run view <ci-run-id> --repo 116-Labs/cuecal --log`.
      2. Decide whether the PR's CI could have run the construct. It could when all of these hold:
         - The workflow triggers on `pull_request`.
         - Its `branches` and `paths` filters (and their `-ignore` forms) match this PR's base and changed files.
         - The job's and the step's `if:` are true for a `pull_request` event.

         A `pull_request_target` trigger does not count, because it runs the base branch's copy of the workflow.
      3. Bucket it:
         - CI ran it and it passed: not a finding.
         - CI could have run it but did not, or it failed: Blocking. Lint never verifies a construct.
         - CI cannot run it this way: Secondary, naming what a person must check. This covers a workflow that triggers only on `pull_request_target`, a push to the base, a tag, a release or a schedule, and one whose filters or `if:` skip it for this PR.
      4. If the description says the construct was verified by a command, the finding says "the author states it was verified by `<command>`". If that command is exactly `uv run ruff check .` or `uv run pytest`, run it and record its result in the finding. The claim never removes the finding (`description-drops-finding`).

### Verdict

21. Apply `verdict-follows-findings`:
    - One or more Blocking findings: request changes.
    - No Blocking finding: approve. Nits may remain.
    - Undecidable: comment.

    The review states the rule it applied.

### Auto-fix step (disabled in this repository)

22. The profile sets `review.identity.reviewer: separate`, so this run commits nothing and pushes nothing. Gaal refuses an approval from a review run that pushed, so every fix, however small, goes to the author as a finding.

    What follows from that:
    - The "Fixed in" list is empty, so `fixed-not-flagged` holds.
    - `commit_sha` is null, there is no `push` object, and `approval_withheld: pushed` never applies.
    - No collapse happens, so `collapse-before-approve`, `collapse-remote-contained`, `collapse-content-preserved` and `collapse-keeps-link` cannot be violated.
    - No push happens, so `push-failure-states`, `bare-force-push`, `bypass-hook` and `admin-bypass` cannot arise.
    - Nothing is committed to the base (`base-untouched`), to a fork, or on top of someone else's commits (`rewrite-foreign-branch`).

    A non-behavioural fix with exactly one reasonable form, such as a typo or wording fix, may go to the author as a one-click suggestion block on its inline thread. Never put a behavioural change in a suggestion block (`behavioral-suggestion`); describe it as a finding instead.

### Anchors

23. Choose which findings become inline threads:
    - **Round 1:** every Blocking finding, every contradiction, and the Secondary findings that are worth a thread.
    - **Round 2 and later:** only Blocking findings and contradictions (`rereview-converges`).
      - Questions, nits and other Secondary findings stay in the body.
      - Omit a non-blocking finding that is not a contradiction and sits on lines an earlier round already read.
      - Your view on another reviewer's open thread goes in the body, never in a second thread.
      - Name which of this run's earlier threads (from earlier signed reviews) the delta answered.

    Pre-existing findings never open threads. Compute each anchor's `line` from the right-hand side of the patch hunks of `git diff <merge-base> <head>`, with `side: RIGHT`.
24. Check whether the remote head moved during the review with `gh pr view <n> --repo 116-Labs/cuecal --json headRefOid`. If it moved, keep reviewing `<head>`; the anchors are tied to it by `commit_id`. Report that the author's push moved the diff.

### Posting step

25. Choose the event (`no-self-verdict`, `identity-withholds`, `second-identity-approval`). Take the first rule that applies:
    1. `GAAL_LOGIN` is empty or absent: post `COMMENT` whatever the verdict, with the verdict as the first line. `review.verdict` is `comment`, and `review.blocking` still counts what was found. When the verdict is approve, set `approval_withheld: identity`.
    2. `GAAL_LOGIN` matches the PR author in any spelling: post `COMMENT`, with the verdict as the first line. When the verdict is approve, set `approval_withheld: author`.
    3. The verdict is request changes: post `REQUEST_CHANGES`.
    4. The verdict is approve and `GAAL_LOGIN` is the review identity (`116-labs-gaal-review[bot]`, `116-labs-gaal-review` or `app/116-labs-gaal-review`): post `APPROVE`.
    5. The verdict is approve and `GAAL_LOGIN` is some other account: post `COMMENT`, with `approval_withheld: identity`.
    6. The verdict is undecidable: post `COMMENT`.

    When approve was posted as comment, the review says so and says that the PR is otherwise clean. Never retry a refused approval, and never approve through another identity (`second-identity-approval`).
26. Compose the review body in `<run-dir>/scratch/review-body.md` with the file tool, in this order:
    1. The verdict, and the rule it followed.
    2. The findings by bucket (Blocking, Secondary, Nits, Pre-existing). Every unfixed contradiction is listed in its bucket and is also an inline thread.
    3. The acceptance-criteria results: each criterion, prefixed `#<issue>:`, marked verified, failed, unverified or deferred. Never show a deferred criterion as met.
    4. A short **Tests** section: each new or changed test and whether it ran in the gates, each behavioural change that has no test, and the note that "fails without the change" was reasoned from the code.
    5. On a re-review, which earlier threads the delta answered.
    6. The line `Reviewed head: <head>`, with the full 40-character sha.
    7. Last, on a line of its own, exactly `gaal review-pr · run <run-id>`, with this run's `GAAL_RUN_ID`. Never reword it (`signed-review`).
27. In preview mode, post nothing. The composed body stays at `<run-dir>/scratch/review.md` (copy it there with `cp <run-dir>/scratch/review-body.md <run-dir>/scratch/review.md`), and the would-be verdict goes into the run result. Skip to the cleanup step.
28. In post mode:
    1. Write `<run-dir>/scratch/review.json` with the file tool. It holds `commit_id` (`<head>`), `body` (the text of the review body), `event`, and `comments`, an array of `{path, line, side: "RIGHT", body}`.
    2. Post it with `gh api repos/116-Labs/cuecal/pulls/<n>/reviews --method POST --input <run-dir>/scratch/review.json`, and keep the returned `id` as `<review-id>`.
    3. If GitHub rejects an anchor, re-fetch (`git fetch origin pull/<n>/head`, then `git rev-parse FETCH_HEAD`), re-anchor once, and post again.
    4. If that also fails, fall back to a body-only review: the same payload with an empty `comments` array, and every would-be thread moved into the body.
    5. If the body-only post also fails, end `failed`, naming the posting step.

    The report states the inline and body-only finding counts, the reason for each body-only finding, and any line-anchor fallback.

### Thread listing

29. List the threads this review opened, by review id, never by login (`resolve-own-threads-only`).
    1. **If `<review-id>` is empty, stop.** End `needs-human` with a `reason`.
    2. Otherwise, write `<run-dir>/scratch/threads.graphql` with the file tool. The query takes `$owner`, `$name`, `$number` and `$endCursor`, and selects `repository.pullRequest.reviewThreads(first: 100, after: $endCursor)`. For each thread it selects `id` and `isResolved`, the thread's first comment (`comments(first: 1)`) with its `databaseId` and `pullRequestReview { databaseId }`, and `pageInfo { hasNextPage endCursor }`.
    3. Run `gh api graphql --paginate -F query=@<run-dir>/scratch/threads.graphql -F owner=116-Labs -F name=cuecal -F number=<n>`. A read error or truncated listing ends `failed`, naming the listing (`complete-listings`).
    4. Keep only the threads whose first comment's `pullRequestReview.databaseId` equals `<review-id>`.
30. Of those threads, reply to and then resolve only the ones this review disposed of itself: a point recorded only, an agreed trade-off, or one filed as a follow-up issue.
    - **Follow-up issues:** file one only for a user-visible defect outside the diff that reproduces on the base. Name the defect, the reproduction and the files, and link the PR.
      1. Write the issue body with the file tool.
      2. Run `gh issue create --repo 116-Labs/cuecal --title <title> --body-file <run-dir>/scratch/followup-<k>.md`.
      3. Do this before replying to the thread, and name the new issue's number in the reply.

      Never file anything else; record it in the report instead.
    - **Reply:** write the body with the file tool, then run `gh api repos/116-Labs/cuecal/pulls/<n>/comments/<comment-id>/replies --method POST -F body=@<run-dir>/scratch/reply-<k>.md`.
    - **Resolve:** write `<run-dir>/scratch/resolve.graphql` containing a `resolveReviewThread(input: {threadId: $threadId})` mutation, then run `gh api graphql -F query=@<run-dir>/scratch/resolve.graphql -F threadId=<thread-id>`.
    - **Failure:** a reply or resolve that fails after the review is posted ends `needs-human` and is reported. Never retry it, because a retry would post a second review.

    Leave questions, blockers, suggestion blocks and contradiction threads open. Never resolve a thread to clear the merge path (`resolve-to-unblock`). Report the open threads, split into suggestions and author-owed.

### Cleanup

31. Restore the checkout to where it started:
    - If you recorded an original branch, run `git checkout <original-branch>`.
    - Otherwise, run `git checkout --detach <original-sha>`.

    Confirm with `git status --porcelain=v1 --untracked-files=all` that the only uncommitted paths are the ones that were dirty at the start. Never edit, move or restore hook files or `.git/config`.

### Result step (every exit path)

32. Read `finished_at` with `date -u +%Y-%m-%dT%H:%M:%SZ`.
33. Write `<run-dir>/result.json.tmp` with the file tool (`run-result-written`, `truthful-report`). It has these fields:
    - `schema_version`: `1`.
    - `run_id`: the literal `GAAL_RUN_ID`.
    - `blueprint`: `"review-pr"`.
    - `blueprint_version`: `"1.8.0"`.
    - `repo`: `"116-Labs/cuecal"`.
    - `issue`: the linked issue picked in the issue-link step, or `null`.
    - `pr`: the PR number, or `null` when none was determined.
    - `status`: `done`, `needs-human`, `needs-clarification` or `failed`.
    - `reason`: one sentence of at most 160 characters naming the decision or action needed. Required unless `status` is `done`.
    - `questions`: a non-empty array, only for `needs-clarification`.
    - `attempts`: `1`.
    - `gates`: by `gates-final-tree`. List this run's gate runs on `<head>` in the order they ran, each as `{name, command, exit_code, duration_ms}`, with `command` exactly `uv run ruff check .` or `uv run pytest`. A gate that did not run is absent. A `done` result never lists a non-zero `exit_code`; a red required gate makes the run `needs-human` anyway.
    - `branch`: the PR's `headRefName`, or `null`.
    - `commit_sha`: `null`. This run never pushes.
    - `review`: required whenever a review was posted, or composed in preview. It holds:
      - `verdict`: `approve`, `request-changes` or `comment`, as posted, or as it would be posted in preview.
      - `blocking` and `non_blocking`: the finding counts.
      - `head`: `<head>`, the full sha on the `Reviewed head` line.
      - `criteria`: every linked issue's criteria in order, each `{text: "#<issue>: <criterion as the issue states it>", status}`. Include them on every round.
      - `approval_withheld`: when it applies, `author`, then `identity`, then `pushed`, taking the first in that order.
    - `started_at` and `finished_at`.

    Include no other keys.
34. Run `mv <run-dir>/result.json.tmp <run-dir>/result.json`. Never leave the `.tmp` file behind.

## Exit states

- `done`: No Blocking finding stands, no thread is left that the author owes, and the review is posted (or, in preview, composed).
  - A clean review whose approve was posted as comment for identity reasons still ends `done`, with `review.approval_withheld` set.
  - The report includes:
    - the acceptance-criteria results
    - a note on the description's accuracy
    - the thread ledger (open threads split into suggestions and author-owed)
    - the push outcome (none) and the collapse outcome (none)
    - the inline and body-only finding counts, with the reason for each body-only finding
    - any line-anchor fallback
    - whose push moved the diff, if the head moved
- `needs-human`: Any of these:
  - A Blocking finding stands, or threads are left for the author. This applies even when identity downgraded the verdict to comment.
  - The id of the review just posted was empty, so the threads it opened could not be listed.
  - A thread reply or resolve failed after the review was posted.

  `reason` summarizes which.
- `needs-clarification`: Any of these:
  - No PR could be determined.
  - The PR links no issue by the issue-link rule. A link to a number that names no issue counts as no link, and `questions` name the number.
  - A linked issue has no checkable acceptance criteria.

  `questions` say what is missing.
- `failed`: Any of these, with `reason` naming the step:
  - The PR is not open, or GitHub cannot find its number (404).
  - The environment could not be prepared on a PR that changes neither `pyproject.toml` nor `uv.lock`, or the head could not be checked out. Nothing is posted.
  - A read failed or a listing was truncated (`fail-closed-reads`, `complete-listings`).
  - Posting failed even after the body-only fallback.

## Invariants

- `description-last`: Read the description only after the correctness, gate, test and criteria passes (the metadata step and the read-the-description step).
- `verdict-follows-findings`: The verdict follows from the findings, and the review states the rule (the verdict step).
- `no-self-verdict`: A context that wrote or pushed the change posts comment. This run pushes nothing, and an author match posts comment (the posting step).
- `identity-withholds`: A run that is not the review identity, or that has no `GAAL_LOGIN`, posts comment, with `approval_withheld` set (the posting step).
- `findings-verified`: Every posted finding is reproduced at its line on `<head>` (the criteria walk).
- `tests-named`: Every behavioural change names its test or is a finding, and the review has a Tests section (the tests step and the posting step).
- `signed-review`: The review body ends with the `Reviewed head: <sha>` line and then the exact signature line (the posting step).
- `fixed-not-flagged`: Nothing is fixed, so no finding is both fixed and flagged (the auto-fix step).
- `resolve-own-threads-only`: Only threads whose first comment carries this review's id are resolved, each after a reply (the thread listing).
- `collapse-before-approve`: No collapse happens in this repository's review runs (the auto-fix step).
- `contradiction-fixed-or-threaded`: Every contradiction becomes an inline thread (the sort step, the anchors step and the posting step).
- `rereview-converges`: From round 2 on, only Blocking findings and contradictions open threads (the anchors step).
- `explicit-staging`: Nothing is staged. Already-dirty paths are never touched (the start step).
- `base-untouched`: Nothing is committed or pushed to the base (the auto-fix step).
- `fail-closed-reads`: A failed read ends `failed`, never "nothing there".
- `complete-listings`: Every listing is paginated to the end, or the run ends `failed`.
- `truthful-report`: The report and result describe only what happened.
- `status-preserved`: Every exit code and API failure is seen and handled.
- `attribution-policy`: `attribution: none`. Nothing this run writes carries AI attribution.
- `run-result-written`: `result.json` is written atomically on every exit path (the result step).
- `gates-final-tree`: `gates` lists only the runs on `<head>`.
- `install-before-gates`: The profile names no install, so nothing is installed and the gates run in this checkout.
- `push-failure-states`: Cannot arise, because nothing is pushed.
- `collapse-remote-contained`: Cannot arise, because nothing is collapsed.
- `collapse-content-preserved`: Cannot arise, because nothing is collapsed.
- `collapse-keeps-link`: Cannot arise, because nothing is collapsed.

## Forbidden actions

- `description-sets-scope`: Letting the description limit what is reviewed.
- `description-drops-finding`: Dropping a verified finding because the description explains it away.
- `second-identity-approval`: Approving through another identity, or retrying a refused approval under one.
- `rewrite-foreign-branch`: Pushing to, or rewriting, a fork's branch or someone else's commits.
- `resolve-to-unblock`: Resolving threads to clear the merge path.
- `behavioral-suggestion`: Putting a behaviour change in a one-click suggestion block.
- `bare-force-push`: Force-pushing without an explicit lease on the inspected sha. This run never pushes at all.
- `admin-bypass`: Merging or pushing with admin privileges.
- `bypass-hook`: Skipping or redirecting the repository's verification, or editing hook configuration.
- `machine-specific-paths`: Hard-coding a person's home directory, private scripts or private services.
- `commit-foreign-edits`: Committing changes this run did not make.
