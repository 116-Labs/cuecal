---
name: gaal-review-pr
description: Adversarially reviews one open pull request in 116-Labs/cuecal against the acceptance criteria of its linked GitHub issues, read fresh at review time, and against the profile gates (`uv run ruff check .` and `uv run pytest`). It reads the PR description last and treats it as a set of claims to test. It posts exactly one signed review whose verdict follows from the verified findings, and it leaves open only the threads the author owes. It writes the run result to `result.json` in the run directory. Use it when a dispatch hands over a repo and a PR number, in post or preview mode, and asks for the review-pr step. In this repository the review runs as the separate review identity (`116-labs-gaal-review[bot]`), so it never commits or pushes, and every fix goes to the author as a finding. Do not use it to implement an issue (gaal-implement), open a PR (gaal-open-pr), revise a PR after review (gaal-revise-pr), merge or deploy. When no PR can be determined, do not guess. End as `needs-clarification` instead.
---
<!-- gaal-stamp blueprint=review-pr@1.9.0 shared=1.5.0 profile=833de6ae33df6d68 generated=2026-10-08 core=b8870cb250ef9e03 forbidden=54c30c1c66633c73 content=8cc122680fb4d8e8 -->

# gaal-review-pr

Review an open PR in `116-Labs/cuecal` the way a careful maintainer would. Judge it against the linked issues' acceptance criteria and the project's gates, without relying on how the PR describes itself. Post exactly one review whose verdict follows from the findings. This repository reviews through a separate identity, so this run never pushes a fix. Every fix it would make goes to the author as a finding.

This file implements blueprint `review-pr` version `1.9.0` together with the shared rules.

## Project facts this skill relies on

- **Repo:** `116-Labs/cuecal` (private). Default branch `main`. Tracker: GitHub issues in the same repo.
- **Gates** (both required, run exactly as written, with nothing added):
  - `lint`: `uv run ruff check .`
  - `test`: `uv run pytest`
- **Preflight:** none. **Advisory:** none. **Install:** none. Install nothing. The gates run in this checkout itself, where the dependencies already exist. A throwaway worktree has no environment, so gates never run in one.
- **Commits:** one commit per PR (`single_commit: true`), Conventional Commits, attribution `none`. This run makes no commits. Any text it writes (review bodies, follow-up issues) carries no AI attribution.
- **Branches:** gaal branches use the prefix `gaal/`. A PR's base is `main`, or the open parent branch of a stacked PR. The profile names no stacking tool.
- **Merge:** method `squash`, `message_source: commits`, no merge queue, `merge.auto: false`. A person merges, so whatever a review leaves only in its body can merge unseen.
- **Review policy:** `required_approvals: 1`. `threads_block_merge: false`: branch protection does not block a merge on open threads, so a thread is how a finding reaches the author and revise-pr. `reviewers: []`. Start signal: `reaction`. Identity: `reviewer: separate`, login `116-labs-gaal-review[bot]`. The push identity is `116-labs-gaal-push[bot]`. No `sign_off` line is set.
- **Limits:** `implement_attempts: 3`, `revise_rounds: 3`, `review_rounds: 2`. Gaal enforces the round limits. This run reviews whichever round it is given and records `attempts: 1`. Because Gaal stops on a head that a review covers, every round reports every criterion with `head`, including re-reviews.

## Run context and command rules

- `<run-dir>` in any command stands for the literal path of the run directory from the run context (the value of `GAAL_RUN_DIR`). `<run-id>` is the literal value of `GAAL_RUN_ID`. Never write either variable name inside a command.
- `GAAL_LOGIN` is the account this run acts as. Take it from the run context and never from GitHub: `gh api user` answers 403 to an App token. Compare logins in all three spellings: `<slug>[bot]`, `<slug>` and `app/<slug>`.
- Run one command per call. Never use `$VAR`, `$(…)`, backticks, `NAME=value` prefixes, pipes, `&&` or `;`. Write paths literally. Quote every glob.
- Allowed commands are `git`, `gh`, `mkdir`, `mv`, `cp`, `ls`, `cat`, `date` and `pwd` with any arguments, plus exactly `uv run ruff check .` and `uv run pytest`. Nothing else is allowed. Filter output with `gh`'s own `--jq`, never with a separate `jq`.
- Write every file with the file-writing tool, never through shell redirection. That covers review bodies, GraphQL request files, follow-up issue bodies and the result. Pass each file by path: `--body-file <file>` for `gh`, `--input <file>` for `gh api`.
- GraphQL calls go through a JSON request file, so no `$` ever appears on a command line. Write `<run-dir>/scratch/<name>.json` as `{"query": "...", "variables": {...}}`, then run `gh api graphql --input <run-dir>/scratch/<name>.json`. To paginate, rewrite the file's `after` variable with the last `endCursor` and run the call again until `hasNextPage` is false.
- Never touch hook configuration, `.git/config` or hook files. Never use a flag that skips or redirects verification. If you ever need the hooks directory, run `git rev-parse --git-path hooks`.
- Read the time with `date -u +%Y-%m-%dT%H:%M:%SZ`. Time each gate by running `date -u +%s` just before and just after it, as separate commands. The gate's `duration_ms` is the difference × 1000.

## Steps

The steps refer to each other by name: the *metadata step*, *link step*, *start-signal step*, *checkout step*, *re-review step*, *correctness pass*, *gate step*, *tests step*, *description step*, *criteria walk*, *sort step*, *verdict step*, *auto-fix step*, *filing step*, *anchor step*, *posting step*, *thread listing* and *result step*. Every exit path, from any step, goes to the result step.

### 1. Setup

1. Run `date -u +%Y-%m-%dT%H:%M:%SZ` and keep the output as `started_at`.
2. Run `mkdir -p <run-dir>/scratch`.
3. Get the PR number and the mode from the dispatch. The mode is post (the default) or preview. If no PR number can be determined, end `needs-clarification` with a question asking which PR to review.
4. Record the checkout's starting point so you can restore it at the end:
   - `git rev-parse --abbrev-ref HEAD`
   - `git rev-parse HEAD`
   - `git status --porcelain=v1 --untracked-files=all`

   If the status lists any entry, the gates cannot run on the PR head in this checkout. Since the profile names no install, there is nowhere else to run them. End `failed` with the reason "checkout not clean; cannot run gates on the PR head". Post nothing.

### 2. Metadata step: read the PR, except its description

Do not read the PR body here (`description-last`).

1. Check that the PR exists by HTTP status, never by the wording of an error message:
   - `gh api --include repos/116-Labs/cuecal/pulls/<n> --jq '{state, base: .base.ref, head: .head.ref, head_sha: .head.sha, author: .user.login, fork: .head.repo.fork, cross: (.head.repo.full_name != .base.repo.full_name)}'`
   - A `404` status ends `failed` with a reason naming PR `<n>`.
   - Any other failure, such as expired auth or a rate limit, ends `failed` naming the read (`fail-closed-reads`).
   - A PR whose `state` is not `open` ends `failed`.
2. List the files and commits, paginated to the end (`complete-listings`):
   - `gh api repos/116-Labs/cuecal/pulls/<n>/files --paginate --jq '.[] | {filename, status, additions, deletions}'`
   - `gh api repos/116-Labs/cuecal/pulls/<n>/commits --paginate --jq '.[] | {sha, author: .author.login, email: .commit.author.email}'`
3. Note `<base>`, the head branch name (used for `branch` in the result), the PR author, and whether the PR comes from a fork.
4. Determine the identity:
   - The run **is the separate review identity** when `GAAL_LOGIN` equals `116-labs-gaal-review[bot]` in any of its spellings.
   - The run **wrote the PR** when `GAAL_LOGIN` equals the PR author in any spelling.
   - When `GAAL_LOGIN` is empty or absent, the author check is unknown (`identity-withholds`).

### 3. Link step: find the linked issues (shared issue-link rule)

The PR's issues are the union of three sources. Read all three every time. Never read the body or commits only when GitHub reports no closing issues.

1. Issues GitHub reports the PR closes: `gh pr view <n> --repo 116-Labs/cuecal --json closingIssuesReferences --jq '[.closingIssuesReferences[].number]'`
2. Links in the body. Extract only each link's keyword and digits, so the description text never enters context:
   `gh pr view <n> --repo 116-Labs/cuecal --json body --jq '[(.body // "") | scan("(?im)^[ \\t]*(close|closes|closed|fix|fixes|fixed|resolve|resolves|resolved|refs)[ \\t]*:?[ \\t]*#([0-9]+)")]'`
3. Links in every commit message:
   `gh api repos/116-Labs/cuecal/pulls/<n>/commits --paginate --jq '.[] | [(.commit.message // "") | scan("(?im)^[ \\t]*(close|closes|closed|fix|fixes|fixed|resolve|resolves|resolved|refs)[ \\t]*:?[ \\t]*#([0-9]+)")]'`

Keep both regex flags: `i` for any case, and `m` so that a `Refs #N` below the summary line is still found. Note whether each link is closing or plain (`refs`).

Check each number, judging by HTTP status: `gh api --include repos/116-Labs/cuecal/issues/<i> --jq .pull_request`.

- A `404`, or a non-empty `pull_request` value, means the number is no issue link. (For a real issue the field is null and the output is an empty line.)
- Any other failure ends `failed` (`fail-closed-reads`).
- If no issue link remains, end `needs-clarification`. Put each number that named no issue in `questions`.

Read each linked issue fresh, as it stands now:

- `gh api repos/116-Labs/cuecal/issues/<i> --jq '{number, title, state, body}'`
- `gh api repos/116-Labs/cuecal/issues/<i>/comments --paginate --jq '.[] | {user: .user.login, created_at, body}'`

Comments that clarify or narrow the scope are part of the spec. Write down each acceptance criterion, including any that an edit of the body added or changed since the PR opened. Grade every linked issue.

Some text is not spec. That is the text between a `<!-- gaal:plan-drift -->` line and its closing `<!-- /gaal:plan-drift -->` line, and any comment that carries the opening marker. That text is the implementer's account of how the plan changed. Treat it as a claim to test, like the description. Everything else in the body is the author's spec, including text a maintainer added after a plan-drift section.

If a linked issue has no checkable acceptance criteria, end `needs-clarification` with questions saying what is missing.

Pick the result's `issue` this way:
1. An issue the dispatch names.
2. Otherwise, the first closing issue GitHub reports.
3. Otherwise, the first closing-keyword line in the body, then in each commit message.
4. Otherwise, the first `Refs` line.

### 4. Start-signal step

The profile's start signal is a reaction. Skip this step in preview.

`gh api repos/116-Labs/cuecal/issues/<n>/reactions --method POST -f content=eyes`

If the call fails, note it in the report and carry on. The exception is expired auth or a rate limit, which end `failed` (`fail-closed-reads`).

### 5. Checkout step

1. Fetch in this exact order:
   1. `git fetch origin <base>`
   2. `git fetch origin pull/<n>/head`
   3. `git rev-parse FETCH_HEAD`

   Run the `rev-parse` immediately after the head fetch and before any other fetch. `FETCH_HEAD` holds only the most recent fetch. The sha it prints is `<head>`, the head this review checks out and reviews.
2. Run `git checkout --detach <head>`.
3. Run `git merge-base <head> origin/<base>` and keep the result as `<merge-base>`.
4. Install nothing. The profile names no `install` command (`install-before-gates`), so the gates run on the checkout's existing environment.

### 6. Re-review step: limit attention to the delta

1. Find the earlier reviews by their signature, never by login:
   `gh api repos/116-Labs/cuecal/pulls/<n>/reviews --paginate --jq '.[] | select((.body // "") | contains("gaal review-pr · run ")) | {id, head: ((.body | capture("Reviewed head: (?<sha>[0-9a-f]{40})").sha) // "none")}'`

   The reviews come oldest first.
   - **No match:** this is round 1. Review the whole diff.
   - **Otherwise:** the last match is the last review, and its `head` is `<old-head>`. The round number is the number of matches + 1.
2. If `<old-head>` is `none`, review the whole diff.
3. If `git cat-file -e <old-head>` fails, run `git fetch origin <old-head>`. If it still cannot be fetched, review the whole diff and say so in the review.
4. When history was rewritten, get the old merge base with `git merge-base <old-head> origin/<base>` and compare with:
   `git range-diff <old-merge-base>..<old-head> <merge-base>..<head>`

   Use the merge base of the old head, never the current head's.
5. Re-check resolved threads.
   1. List all threads the way the anchor step does.
   2. Read each earlier review's body with `gh api repos/116-Labs/cuecal/pulls/<n>/reviews/<id> --jq .body` to collect the thread links its Dispositions list names.
   3. Keep each thread that meets all three conditions:
      - `isResolved` is true.
      - Its first comment's `pullRequestReview.databaseId` is one of the listed review ids, or a Dispositions list links it as a finding's thread. That includes a thread a person or another bot opened.
      - Its `resolvedBy.login` is the PR author or `GAAL_LOGIN`, in any spelling.
   4. A thread any other account resolved is a person's decision. Do not re-check it.
   5. When a kept thread's finding still reproduces on `<head>`, it becomes a candidate finding of this review, whatever the delta. It takes a disposition again. A rebase can mark a thread outdated and leave it resolved unfixed, so resolved does not mean fixed.

   When gaal pushes as a person's own login, the PR author is that person. Their resolution is then re-checked too, and such a PR is merged by hand.

### 7. Correctness pass

Review the diff (`git diff <merge-base> <head>`), or the delta on a re-review, for:

- logic
- edge cases
- error handling
- concurrency
- security

Scripts, workflows and skill files count as code. In those files, check for:

- nonexistent flags
- word-splitting and quoting bugs
- documented but unimplemented flags
- injection through untrusted input
- re-runs that are not idempotent
- swallowed errors
- unverified success inside loops

A pre-existing defect that this PR makes reachable belongs to the PR. It is a Blocking or Secondary finding, even though the code it sits in is untouched.

### 8. Gate step

Run each gate in this checkout, at `<head>`:

1. `date -u +%s`
2. `uv run ruff check .`
3. `date -u +%s`
4. `date -u +%s`
5. `uv run pytest`
6. `date -u +%s`

Record `name`, `command`, `exit_code` and `duration_ms` for each gate. A gate that exits non-zero is a Blocking finding naming the gate, so a review that ran it never ends `done` (`gates-final-tree`). The profile has no preflight and no advisory checks, so there are no Secondary or Pre-existing advisory findings.

### 9. Tests step

For each behavioural change in the diff, name the test that covers it (`tests-named`). That is either a new or changed test that fails without the change, or an existing test that already exercises it. A test that also passes on the base proves nothing about the change.

A behavioural change with no covering test is a finding:
- **Blocking** when the linked issue's criteria ask for tests.
- **Secondary** otherwise.

For each new or changed test, note whether `uv run pytest` ran it in the gate step. A test the gates never ran proves nothing about the head.

This run cannot run a test on the merge base. A throwaway worktree has no environment, the profile names no install, and `uv run pytest` takes no path argument. So the Tests section must say that "fails without the change" was reasoned from the code, not run on the base.

### 10. Description step

Only now read the description:

`gh pr view <n> --repo 116-Labs/cuecal --json body --jq .body`

Treat it as a set of claims to test. It can add findings. It can never remove a finding (`description-drops-finding`) or limit what is reviewed (`description-sets-scope`). Note its Deferred list, if any, and whether each statement about the change is accurate. The report includes this description-accuracy note.

### 11. Criteria walk: verify findings and walk the criteria

1. Verify every candidate finding at its exact line on `<head>`. Drop any that does not reproduce (`findings-verified`).
2. Walk every acceptance criterion of every linked issue on `<head>`. On a re-review, walk every criterion again, not only the ones the delta touches. Give each a status:
   - **verified:** met, and shown by a gate, a test or a check you ran.
   - **failed:** not met.
   - **unverified:** you could not confirm it on this head. Say what a person must check.
   - **deferred:** only when the link is plain (`Refs`) and the Deferred list names the criterion. A deferral is scope, not an excuse. Under a closing keyword it changes nothing, and it never drops a correctness or gate finding.
3. A Deferred entry that is not one of the issue's criteria is a Secondary finding.

### 12. Sort step

Sort the findings into **Blocking**, **Secondary**, **Nits** and **Pre-existing** using these rules:

- **Criteria:**
  - A failed criterion is Blocking unless it is deferred.
  - An unverified criterion is Secondary.
- **Description claims:**
  - A Deferred list under a closing keyword is Blocking, because merging would close the issue with criteria still open.
  - A test-plan box ticked for a gate that did not run on the head is Blocking. Compare each ticked box with the gates this run ran and with CI on `<head>`.
- **Contradictions:** a finding on lines the PR adds that contradicts other code in the PR is a contradiction. Examples are a hint, message, doc, test or default that disagrees with the new behaviour. Whatever its bucket, a contradiction must end fixed or as a thread, never only as text in the body (`contradiction-fixed-or-threaded`).
- **Workflow, CLI or API constructs** that the PR's workflow or script files add or change:
  1. Look for live evidence first. Run `gh run list --repo 116-Labs/cuecal --commit <head> --json databaseId,workflowName,event,status,conclusion --limit 100`. A listing that returns a full 100 is truncated, so end `failed` (`complete-listings`).
  2. Read the workflow's `on:` and `if:` conditions with the file-reading tool. The PR's CI **could have run** a construct when a `pull_request` run on this head would reach the step holding the PR's version of it. That means the `branches`/`paths` filters and their `-ignore` forms match this PR, and the job's and step's `if:` are true for a `pull_request` event. A `pull_request_target` trigger does not count, because it runs the base branch's copy.
  3. If CI ran the construct and it passed, there is no finding.
  4. If CI could have run it but did not, or it failed, the finding is Blocking. Lint never verifies it.
  5. If the PR's CI cannot run it (`pull_request_target` only, a push to the base, a tag, a release, a schedule, or filtered out for this PR), the finding is Secondary and names what a person must check. Its thread waits for a person to resolve it.
  6. When the description says the construct was verified by a command, write "the author states it was verified by `<command>`" in the finding. If that command is one this run may execute, run it and record the result. The claim never drops the finding.
- **Secondary versus Pre-existing:** a Secondary finding is the PR's own (it does not reproduce on the base). A defect that reproduces on the base, in code the PR did not touch, is Pre-existing. A nit that is not safe to merge is Secondary.

Every finding then gets a disposition (`finding-disposed`):

| Finding | Disposition |
|---|---|
| Blocking | Always **thread** |
| Secondary | **fixed** or **thread**, never filed |
| Contradiction | **fixed** or **thread**, never filed |
| Pre-existing that meets the shared follow-up bar | **filed** |
| Pre-existing below the bar | Recorded in the review body |
| Nit that is not a contradiction | No disposition |

In this repository the auto-fix step pushes nothing, so every Blocking finding, Secondary finding and contradiction ends as **thread**.

A Pre-existing finding meets the follow-up bar only when it is a user-visible defect outside the diff: wrong output a user can see, in code this PR did not touch, that reproduces on the base. Anything else is recorded, not filed.

### 13. Verdict step

Apply this rule and state it in the review (`verdict-follows-findings`):

- At least one Blocking finding → **request changes**.
- No Blocking finding → **approve**. Nits may remain.
- The findings cannot decide the verdict → **comment**.

Then decide which event to post:

- If `GAAL_LOGIN` is empty or absent, post **comment** whatever the verdict, and put the verdict on the first line (`identity-withholds`).
- If the run wrote the PR, post **comment** with the verdict on the first line (`no-self-verdict`). If the verdict was approve, `approval_withheld` is `author`.
- If the verdict is approve and the run is not the separate review identity, post **comment** (`identity-withholds`). `approval_withheld` is `identity`.
- If the verdict is request changes and `GAAL_LOGIN` is set and did not write the PR, post request changes, whatever the identity.
- Never approve through another identity. Never retry a refused approval under a different one (`second-identity-approval`).
- When the verdict was approve but this run posts comment, say so in the review and say that the PR is otherwise clean.

### 14. Auto-fix step

With `review.identity.reviewer: separate`, this run pushes nothing. That holds even when there are zero Blocking findings and every commit is the run's own. Gaal refuses an approval from a review run that pushed.

So in this repository:
- Never commit and never push.
- Never rewrite a fork's branch or commits authored by someone else (`rewrite-foreign-branch`).
- Send every fix you would have made to the author as a finding. A fix that is a Blocking finding, Secondary finding or contradiction has the disposition **thread**.

Never propose a behaviour change as a one-click suggestion block (`behavioral-suggestion`). A suggestion block is only for a non-behavioural edit with exactly one reasonable form.

Because nothing is pushed:
- The "Fixed in" list is empty.
- `commit_sha` is null.
- `approval_withheld: pushed` never applies.
- No collapse runs. `collapse-before-approve` holds trivially, and the merge's `squash` message comes from the branch's commits as they are.

The shared rules `explicit-staging`, `base-untouched` and `commit-foreign-edits` hold because nothing is staged or committed. `bare-force-push` and `push-failure-states` hold because nothing is pushed. `admin-bypass` holds because nothing is merged.

### 15. Filing step: file follow-ups before posting

Only a Pre-existing finding that meets the follow-up bar is filed. A Blocking finding, Secondary finding or contradiction is never filed. In preview, file nothing and mark each such finding `would file` in the body.

For each finding to file:

1. Look for an issue already filed for it:
   `gh issue list --repo 116-Labs/cuecal --state all --search "\"gaal:follow-up pr=<n>\" in:body" --json number,title,body --limit 100`

   - A listing that returns a full 100 is truncated: end `failed` (`complete-listings`).
   - A search that fails ends `failed` (`fail-closed-reads`).
   - If a listed issue carries the same finding, its number is the disposition.
2. Otherwise, write the issue body to `<run-dir>/scratch/follow-up-<k>.md` with the file tool. The body must:
   - name the defect, how to reproduce it and the files involved,
   - link this PR,
   - carry the marker line `<!-- gaal:follow-up pr=<n> -->`.
3. File it with `gh issue create --repo 116-Labs/cuecal --title "<title>" --body-file <run-dir>/scratch/follow-up-<k>.md`. Assign no milestone and add no labels, because the profile names none.
4. If the filing errors, do not retry it. Run the same search once more:
   - If it now lists an issue for the finding, that issue is the disposition.
   - Otherwise, record the finding in the review body and name the failed filing in the report.

### 16. Anchor step: list threads and compute inline anchors

1. Write `<run-dir>/scratch/threads-q.json` with this content (rewrite `after` for each page):

   ```json
   {"query": "query($owner: String!, $name: String!, $number: Int!, $after: String) { repository(owner: $owner, name: $name) { pullRequest(number: $number) { reviewThreads(first: 100, after: $after) { pageInfo { hasNextPage endCursor } nodes { id isResolved isOutdated path line resolvedBy { login } comments(first: 1) { nodes { body url pullRequestReview { databaseId } } } } } } } }", "variables": {"owner": "116-Labs", "name": "cuecal", "number": <n>, "after": null}}
   ```
2. Run `gh api graphql --input <run-dir>/scratch/threads-q.json` and page to the end (`complete-listings`). A failed read ends `failed` (`fail-closed-reads`).
3. If an earlier review's unresolved thread already carries a finding, that thread is the finding's disposition. Open no second thread for it, and record the `url` of its first comment.
4. Every other finding whose disposition is **thread** takes a new thread:
   - **Round 1:** every Blocking finding, contradiction and Secondary finding. A nit may also open a thread, and it carries no disposition.
   - **Round 2 and later:** the same Blocking findings, Secondary findings and contradictions, and never a nit that is not a contradiction (`rereview-converges`). Questions, and your view on another reviewer's open thread, go in the body. A nit on lines an earlier round already read is omitted. Name which of this review's own earlier threads the delta answered.
5. Take anchor lines from the right-hand side of the patch hunks of `<head>`. Read them with `gh api repos/116-Labs/cuecal/pulls/<n>/files --paginate --jq '.[] | {filename, patch}'` or `git diff <merge-base> <head>`.
6. A finding with no changed line of its own is anchored on the changed line closest to what it concerns, or else on the PR's first changed line. Examples are an unverified criterion, a CI-unrunnable construct, or a finding about the description.

### 17. Posting step: post one review

**Compose the body** in `<run-dir>/scratch/review.md` with the file tool, in this order:

1. The verdict as the first line, with the rule applied. When identity downgraded an approve, add the note required by the verdict step.
2. Findings by bucket. Each finding with a new thread is also posted inline on its anchor. A finding an earlier unresolved thread carries is listed with that thread's url and is never threaded again.
3. Acceptance-criteria results. Each criterion is verified, failed, unverified or deferred, prefixed `#<issue>:`. Never show a deferred criterion as met.
4. A **Tests** section: each new or changed test and whether it ran in the gates, each behavioural change with no test, and the note that "fails without the change" was reasoned, not run on the base.
5. A **Fixed in** list. It reads "none: this run pushes nothing (separate review identity)". A fix never appears both as fixed and as a finding (`fixed-not-flagged`).
6. A **Dispositions** list. Name each Blocking finding, Secondary finding and contradiction with `thread` (and the thread url when an earlier thread carries it). Name each filed Pre-existing finding as `filed #<n>`, or `would file` in preview. Record Pre-existing findings below the bar, and any failed filings.
7. The description-accuracy note and, on a re-review, the earlier threads the delta answered.
8. `Reviewed head: <head>` (the full 40-character sha).
9. Last, on a line of its own, exactly `gaal review-pr · run <run-id>`. Never reword it (`signed-review`). No `sign_off` line is configured.

**In preview:** post nothing, and carry the would-be verdict into the result. Skip the thread listing.

**In post mode,** follow these sub-steps in order.

1. **Clear out leftover pending reviews.**
   1. Run `gh api repos/116-Labs/cuecal/pulls/<n>/reviews --paginate --jq '.[] | select(.state == "PENDING") | {node_id, body: (.body // "")}'`.
   2. A pending review whose body carries `<!-- gaal:review-pr pending -->` was left by a run that stopped mid-post. Delete it with a `deletePullRequestReview` mutation file (`{"query": "mutation($id: ID!) { deletePullRequestReview(input: {pullRequestReviewId: $id}) { clientMutationId } }", "variables": {"id": "<node_id>"}}`) and `gh api graphql --input <run-dir>/scratch/delete-pending.json`.
   3. A pending review without that line is a person's draft. Never delete it. Post nothing and end `failed`, naming it.
2. **Create the review pending.**
   1. Write `<run-dir>/scratch/review-create.json` as `{"commit_id": "<head>", "body": "<!-- gaal:review-pr pending -->", "comments": [{"path": "<path>", "line": <line>, "side": "RIGHT", "body": "<finding>"}]}`. Give it no `event`. Never put the review body, the `Reviewed head` line or the signature in a pending review.
   2. Run `gh api repos/116-Labs/cuecal/pulls/<n>/reviews --method POST --input <run-dir>/scratch/review-create.json --jq '{id, node_id}'`.
   3. If GitHub refuses an inline anchor, nothing was created. Fetch the patch again, re-anchor once, and retry.
   4. If GitHub refuses again, move each refused finding to a file-level thread. If GitHub does not say which anchor it refused, move every finding with a new thread. A file-level thread goes on the file the finding concerns, or else on the PR's first changed file. Create the pending review with the remaining line comments only.
3. **Add each file-level thread.** For each one, write a mutation file and run it:
   - `{"query": "mutation($rid: ID!, $path: String!, $body: String!) { addPullRequestReviewThread(input: {pullRequestReviewId: $rid, path: $path, body: $body, subjectType: FILE}) { thread { id } } }", "variables": {"rid": "<node_id>", "path": "<path>", "body": "<finding>"}}`
   - `gh api graphql --input <run-dir>/scratch/file-thread-<k>.json`

   Use the review's `node_id`, never its numeric `id`. Never use the single-comment endpoint `pulls/<n>/comments`.
4. **Submit.** Write `<run-dir>/scratch/review-submit.json` and run it with `gh api graphql --input <run-dir>/scratch/review-submit.json`:
   - `{"query": "mutation($rid: ID!, $event: PullRequestReviewEvent!, $body: String!) { submitPullRequestReview(input: {pullRequestReviewId: $rid, event: $event, body: $body}) { pullRequestReview { databaseId url } } }", "variables": {"rid": "<node_id>", "event": "<APPROVE|REQUEST_CHANGES|COMMENT>", "body": "<full review body>"}}`
5. **On failure, post nothing.** If a file-level thread is refused or the submit fails, delete the pending review with the same `node_id`, so nothing is posted. Then end `failed`, naming the refused anchor or the failed submit. A review body alone would let the PR merge past the finding.
6. **Check whether the head moved.** Run `gh api repos/116-Labs/cuecal/pulls/<n> --jq .head.sha`. If it differs from `<head>`, the review stays pinned to `<head>`. Report that the author's push moved the diff.

### 18. Thread listing: list and settle this review's own threads

Skip this step in preview.

1. Take the posted review's `databaseId`. **If it is empty, stop.** End `needs-human` with a reason. Never fall back to matching by login.
2. List the threads as in the anchor step. Keep only those whose first comment's `pullRequestReview.databaseId` equals that id (`resolve-own-threads-only`).
3. Never resolve a thread that carries a Blocking finding, Secondary finding or contradiction. It stays open for the author and revise-pr (`finding-disposed`). Never resolve threads to clear the merge path (`resolve-to-unblock`).
4. Settle only the threads this review opened for a nit and disposed of itself (recorded only, or an agreed trade-off). Reply first, then resolve:
   - Reply with `addPullRequestReviewThreadReply` (`{"query": "mutation($tid: ID!, $body: String!) { addPullRequestReviewThreadReply(input: {pullRequestReviewThreadId: $tid, body: $body}) { comment { id } } }", ...}`).
   - Resolve with `resolveReviewThread` (`{"query": "mutation($tid: ID!) { resolveReviewThread(input: {threadId: $tid}) { thread { isResolved } } }", ...}`).
   - Run each through `gh api graphql --input <file>`.
5. If a reply or resolve fails, report it and end `needs-human`. Never retry.
6. Leave questions, blockers, suggestion blocks and contradiction threads open. Report the open threads split into suggestions and author-owed.

### 19. Restore the checkout

Return the checkout to where it started. Use `git checkout <original-branch>`, or `git checkout --detach <original-sha>` if it started detached. Do this on every exit path after the checkout step. Leave no `.tmp` file behind.

### 20. Result step: write the run result

Write the result on every exit path, failures included (`run-result-written`).

1. Run `date -u +%Y-%m-%dT%H:%M:%SZ` for `finished_at`.
2. Write `<run-dir>/result.json.tmp` with the file tool.
3. Run `mv <run-dir>/result.json.tmp <run-dir>/result.json`.

```json
{
  "schema_version": 1,
  "run_id": "<run-id>",
  "blueprint": "review-pr",
  "blueprint_version": "1.9.0",
  "repo": "116-Labs/cuecal",
  "issue": <issue number or null>,
  "pr": <n or null>,
  "status": "<done|needs-human|needs-clarification|failed>",
  "reason": "<one sentence, at most 160 characters; omit only when done>",
  "questions": ["<only for needs-clarification; non-empty>"],
  "attempts": 1,
  "gates": [
    {"name": "lint", "command": "uv run ruff check .", "exit_code": <code>, "duration_ms": <ms>},
    {"name": "test", "command": "uv run pytest", "exit_code": <code>, "duration_ms": <ms>}
  ],
  "branch": "<PR head branch or null>",
  "commit_sha": null,
  "review": {
    "verdict": "<approve|request-changes|comment>",
    "blocking": <count>,
    "non_blocking": <count>,
    "head": "<head>",
    "criteria": [{"text": "#<issue>: <criterion as the issue states it>", "status": "<verified|failed|unverified|deferred>"}],
    "approval_withheld": "<author|identity; only when approve was posted as comment>"
  },
  "started_at": "<started_at>",
  "finished_at": "<finished_at>"
}
```

Field rules:

- **`reason`:** omit it only when `status` is `done`.
- **`questions`:** include it only for `needs-clarification`, and never leave it empty then.
- **`gates`** (`gates-final-tree`, `truthful-report`):
  - List only the gate runs on `<head>`, in the order they ran.
  - A gate that did not run is absent.
  - A `done` result never lists a non-zero `exit_code`.
- **`review.verdict`:**
  - It is the event actually posted. In preview it is the would-be event.
  - With `GAAL_LOGIN` empty or absent it is `comment`, and `blocking` still counts what was found.
  - When approve was posted as comment, set `approval_withheld`: `author` before `identity`.
- **`review`:** required on `done`. Include it whenever a verdict was reached.
- **`review.head` and `review.criteria`:**
  - `head` is the sha on the `Reviewed head` line.
  - `criteria` lists every linked issue's criteria, in order.
- **`commit_sha`:** always null, because this run never pushes. Omit `push`.

## Exit states

- `done`: No Blocking finding stands, no thread is left that the author owes, and the review is posted (or composed, in preview). A clean review whose approve was posted as comment because of identity also ends `done`, with `review.approval_withheld`. The report includes:
  - the criteria results,
  - the description-accuracy note,
  - the thread ledger,
  - inline versus body-only finding counts, with the reason for each body-only one (only a nit, a recorded Pre-existing finding, or a filed finding with its link),
  - the follow-up issues filed,
  - any line-anchor fallback,
  - whose push moved the diff,
  - the push outcome: none, separate identity.
- `needs-human`: Any of these:
  - a Blocking finding stands;
  - threads are left for the author (every finding whose disposition is thread is one), whether or not identity downgraded the verdict;
  - the posted review's id was empty;
  - a thread reply or resolve failed after posting.

  `reason` summarizes.
- `needs-clarification`: Any of these:
  - no PR could be determined;
  - the PR links no issue by the issue-link rule (`questions` name any number that named no issue);
  - a linked issue has no checkable acceptance criteria.
- `failed`: Any of these, with `reason` naming the step:
  - the PR is not open, or its number is a 404;
  - the checkout was not clean, so the head could not be verified (nothing posted);
  - a read failed or a listing was truncated (`fail-closed-reads`, `complete-listings`);
  - a person's pending draft review blocks posting;
  - posting failed even after the file-level fallback, including a refused file-level thread (nothing posted).

## Invariants

Blueprint invariants:

- `description-last`: Read the PR description only after the correctness pass, the gates and the tests pass have produced findings.
- `verdict-follows-findings`: The verdict is request changes with at least one Blocking finding, approve with none, and comment when undecidable. The review states the rule it applied.
- `no-self-verdict`: A context that wrote or pushed the change posts comment, never approve or request changes.
- `identity-withholds`: A run that is not the separate review identity posts comment when the findings call for approve (`approval_withheld`: `author` when its account wrote the PR, else `identity`). With `GAAL_LOGIN` empty or absent, the run posts comment whatever the verdict, with the verdict on the first line.
- `findings-verified`: Every posted finding was reproduced at its line on the reviewed head.
- `tests-named`: Every behavioural change names its covering test or is a finding. The Tests section lists each new or changed test and whether the gates ran it.
- `signed-review`: The body names `Reviewed head: <sha>` and ends with `gaal review-pr · run <run-id>` on its own line.
- `fixed-not-flagged`: A pushed fix appears in "Fixed in" and never also as an inline finding. This run pushes none.
- `resolve-own-threads-only`: Resolve only threads this review opened, matched by review id and never by login, and each only after a reply.
- `collapse-before-approve`: Any collapse precedes anchors and posting. This run never collapses.
- `contradiction-fixed-or-threaded`: A contradiction on lines the PR adds is fixed or carried by a thread, never left only in the body and never filed.
- `rereview-converges`: After round 1, open new threads only for Blocking findings, Secondary findings and contradictions that no earlier unresolved thread carries. Name the earlier threads the delta answered.
- `finding-disposed`: Every Blocking finding, Secondary finding and contradiction ends with exactly one disposition (fixed or thread) before posting. A Pre-existing finding that meets the bar is filed. A review that cannot open a finding's thread is not posted.

Shared invariants:

- `explicit-staging`: Stage only paths this run wrote. This run stages nothing.
- `base-untouched`: Never commit or push to `main` or to any base.
- `fail-closed-reads`: A failed read stops the run. It never becomes "nothing".
- `complete-listings`: Paginate every listing to the end. A full `--limit 100` page is truncated and stops the run.
- `truthful-report`: The report and result describe only what happened.
- `status-preserved`: Never lose a command's exit status to a pipe or a filter.
- `attribution-policy`: Attribution is `none`. Add no AI attribution anywhere.
- `run-result-written`: Write `result.json` atomically on every exit path.
- `gates-final-tree`: `gates` lists only the runs on the final tree.
- `install-before-gates`: The profile names no install, so install nothing and run the gates in this checkout.
- `push-failure-states`: Not exercised, because this run never pushes.
- `collapse-remote-contained`: Not exercised, because this run never collapses.
- `collapse-content-preserved`: Not exercised, because this run never collapses.
- `collapse-keeps-link`: Not exercised, because this run never collapses.

## Forbidden actions

- `description-sets-scope`: Letting the description or its focus section limit what is reviewed.
- `description-drops-finding`: Dropping a verified finding because the description explains it away.
- `second-identity-approval`: Approving through another identity, or retrying a refused approval under a different one.
- `rewrite-foreign-branch`: Pushing to or rewriting a fork's branch or another author's commits.
- `resolve-to-unblock`: Resolving threads to clear the merge path.
- `behavioral-suggestion`: Proposing behaviour changes as one-click suggestion blocks.
- `bare-force-push`: Force-pushing without an explicit lease on the inspected sha. This run never pushes.
- `admin-bypass`: Merging, pushing or rewriting with admin privileges.
- `bypass-hook`: Skipping or redirecting the repository's verification hooks, or editing hook configuration.
- `machine-specific-paths`: Hard-coding personal directories, scripts or services.
- `commit-foreign-edits`: Committing changes this run did not make.
