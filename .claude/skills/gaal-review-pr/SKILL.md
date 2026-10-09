---
name: gaal-review-pr
description: >-
  Adversarially reviews one open pull request in 116-Labs/cuecal. It judges the PR against the acceptance criteria of its linked GitHub issues, read fresh at review time, and against the profile gates (`uv run ruff check .` and `uv run pytest`, run after `uv sync --locked`). It reads the PR description last and treats it as a set of claims to test. It posts exactly one signed review whose verdict follows from the verified findings, leaves open only the threads the author owes, and writes the run result to `result.json` in the run directory. Use it when a dispatch hands over a repo and a PR number, in post or preview mode, and asks for the review-pr step. In this repository the review runs as the separate review identity, so it never commits or pushes, and every fix goes to the author as a finding. Do not use it to implement an issue (gaal-implement), open a PR (gaal-open-pr), revise a PR after review (gaal-revise-pr), merge, publish or deploy. When no PR can be determined, do not guess: end as `needs-clarification`.
---
<!-- gaal-stamp blueprint=review-pr@1.9.0 shared=1.5.0 profile=6f85855df888e336 generated=2026-10-09 core=b8870cb250ef9e03 forbidden=54c30c1c66633c73 content=25a0503ea398d772 -->

# gaal-review-pr

Review an open PR the way a careful maintainer would. Judge it against the linked issues' acceptance criteria and the project's gates, without relying on how the PR describes itself. Post exactly one review whose verdict follows from the findings, and leave open only the threads the author really owes.

Blueprint: `review-pr` version `1.9.0` (shared rules `1.5.0`).

## Project facts (from `.gaal/project.yml`)

- **Repo:** `116-Labs/cuecal`. Default branch `main`. Visibility public. Tracker: GitHub issues in the same repo.
- **Install:** `uv sync --locked` (name `uv`). Run it before the gates every time (`install-before-gates`).
- **Gates (both required):**
  - `lint` = `uv run ruff check .`
  - `test` = `uv run pytest`
- **Preflight:** none. **Advisory:** none. No advisory step runs, and no finding comes from an advisory check.
- **Commits:** one commit per PR, Conventional Commits, attribution `none`. This skill never commits. Any text it writes that could land in a commit or PR body carries no AI attribution (`attribution-policy`).
- **Branches:** gaal branches use the prefix `gaal/`. The PR's base is `main` or an open stacked parent branch. The profile names no stacking tool, so read the base from the PR itself and never assume `main`.
- **Merge:** method `squash`, `message_source: commits`, no merge queue, `auto: true`. A converged PR merges automatically. A review body blocks nothing. Only an unresolved thread, changes requested or a missing approval holds a PR back.
- **Review policy and branch protection:**
  - `required_approvals: 1`
  - `threads_block_merge: true`
  - `dismiss_stale_approvals: true`
  - `require_last_push_approval: false`
  - `code_owner_reviews: true`
  - required checks: `test` and `zizmor`
  - start signal: `reaction`
  - no `sign_off` is set, so the review body carries no sign-off line
- **Review identity:** `review.identity.reviewer: separate`, login `116-labs-gaal-review[bot]`.
  - Its three spellings are `116-labs-gaal-review[bot]` (REST), `116-labs-gaal-review` (GraphQL) and `app/116-labs-gaal-review` (`gh --json`).
  - The push identity is `116-labs-gaal-push[bot]`.
  - Because the reviewer is separate, **this skill never commits or pushes**. The auto-fix step sends every fix to the author as a finding, `commit_sha` is always `null`, and no collapse ever runs.
- **Attempt limits:** `implement_attempts: 3`, `revise_rounds: 3`, `review_rounds: 2`. Gaal enforces them across runs. Gaal starts revise-pr only while a review round (at most 2) is left for the push it will make. Once the rounds are spent, it stops on a head that a review covers and posts the `criteria` that review reported. So every round, re-reviews included, reports every criterion together with `head`.

## Inputs

- PR number and repo, from the dispatch. Mode is `post` (default) or `preview`. Preview posts, pushes and files nothing.
- Run context:
  - `GAAL_RUN_ID`: the run id.
  - `GAAL_RUN_DIR`: the run directory.
  - `GAAL_LOGIN`: the account this run acts as. It may be empty or absent. Never ask GitHub for it: `gh api user` answers 403 to an App token.

## Command rules (headless)

The run refuses every command outside its allowlist. Apart from the file tools, it allows `git`, `gh`, `mkdir`, `mv`, `cp`, `ls`, `cat`, `date` and `pwd` with any arguments. It allows exactly three other commands, each exactly as written: `uv run ruff check .`, `uv run pytest` and `uv sync --locked`.

**Placeholders**

- In every command below, `<run-dir>` stands for the literal run-directory path from the run context (the value of `GAAL_RUN_DIR`), and `<run-id>` for the literal run id (the value of `GAAL_RUN_ID`). Never write the variable names inside a command.
- `<checkout>` is the literal path of this repository checkout.
- Fill in every other `<placeholder>` (`<n>`, `<head>`, `<base>`, `<sha>`, `<path>`, `<node_id>`, `<event>`) literally.
- Never use `$VAR`, `${VAR}`, `$(…)`, backticks or a `NAME=value` prefix.

**One command per call**

- Never chain commands with `&&`, `;` or `|`.
- To run a command somewhere else, `cd` to the literal path first.

**Scratch space and files**

- Scratch files go in `<run-dir>/scratch` (`mkdir -p <run-dir>/scratch`). Throwaway worktrees go under `<run-dir>`, never in `/tmp` and never through `mktemp`.
- Write every file with the file-writing tool, never with shell redirection. That covers review bodies, thread bodies, comment bodies, issue bodies, GraphQL query files and JSON payloads.
- Pass each file by its path: `--body-file <file>`, `--input <file>`, or `--field body=@<file>` / `--field query=@<file>`.
- Quote every glob. List uncommitted paths with `git status --porcelain=v1 --untracked-files=all`.

**Time**

- Read the time with `date -u +%Y-%m-%dT%H:%M:%SZ`.
- Time a gate with `date -u +%s` just before it and just after it, as separate commands. `duration_ms` is the difference times 1000.

**Hooks**

- Never touch the hook configuration. That means no `--no-verify`, no `git commit -n`, no `--no-gpg-sign` and no `core.hooksPath`, not even to read it. Never edit, move or restore hook files or `.git/config`, and never run `gh pr merge --admin` (`bypass-hook`, `admin-bypass`).
- This skill commits and pushes nothing.

**Reads and listings**

- Every read fails closed (`fail-closed-reads`). An error, auth expiry or rate limit stops the run with `failed` naming the read. It never becomes "nothing found".
- A command's failure is never lost to a filter or a guard (`status-preserved`).
- Paginate every listing to the end with `--paginate`, or for GraphQL with a `pageInfo { hasNextPage endCursor }` query run through `gh api graphql --paginate`.
- A listing that stops at its cap is truncated, for example a `--limit 100` that returns exactly 100 items. End `failed` naming it (`complete-listings`).

**GraphQL files**

- Write each GraphQL document to a file in `<run-dir>/scratch` with the file tool.
- A paginated query declares a String variable named `endCursor`, passes it as `after:` and selects `pageInfo { hasNextPage endCursor }`, as `gh api graphql --paginate` requires.
- Mutations take their ids and values as GraphQL variables, passed with `--raw-field` (strings) or `--field <name>=@<file>` (file contents).

## Steps

Before step 1, record `started_at` with `date -u +%Y-%m-%dT%H:%M:%SZ`, then run `mkdir -p <run-dir>/scratch`. On any exit, go to step 18 (the result step) once any cleanup the step names is done.

### 1. Metadata step: read the PR, but not its description

If the dispatch names no PR and none can be determined, end `needs-clarification`, with a question asking which PR to review.

Read the PR:

`gh api --include repos/116-Labs/cuecal/pulls/<n> --jq '{state, merged, draft, base: .base.ref, head: .head.ref, head_sha: .head.sha, head_repo: .head.repo.full_name, author: .user.login}'`

Judge the result by its HTTP status line:

- **404:** end `failed` naming PR `<n>`.
- **Any other error:** end `failed` naming the read.
- **`state` is not `open`:** end `failed` with "PR is not open".

Record `<base>`, the head branch (it becomes the result's `branch`) and the PR author.

List the changed files:

`gh api repos/116-Labs/cuecal/pulls/<n>/files --paginate --jq '.[] | {filename, status}'`

That endpoint stops at 3000 files, so exactly 3000 means truncated.

List the commits:

`gh api repos/116-Labs/cuecal/pulls/<n>/commits --paginate --jq '.[] | {sha, author: .author.login, email: .commit.author.email}'`

That endpoint stops at 250 commits, so exactly 250 means truncated (`complete-listings`).

Do **not** read the title or body here (`description-last`).

### 2. Link step: find the linked issues (shared issue-link rule)

Read all three sources every time:

1. Closing references reported by GitHub. GitHub fills this field only for PRs based on the default branch.
   `gh pr view <n> --repo 116-Labs/cuecal --json closingIssuesReferences --jq '.closingIssuesReferences[].number'`
2. Links in the body, extracted without reading the body text into context:
   `gh api repos/116-Labs/cuecal/pulls/<n> --jq '[(.body // "") | scan("(?im)^[ \\t]*(close|closes|closed|fix|fixes|fixed|resolve|resolves|resolved|refs)[ \\t]*:?[ \\t]*#([0-9]+)")]'`
3. Links in each commit message, with the same filter:
   `gh api repos/116-Labs/cuecal/pulls/<n>/commits --paginate --jq '.[] | [(.commit.message // "") | scan("(?im)^[ \\t]*(close|closes|closed|fix|fixes|fixed|resolve|resolves|resolved|refs)[ \\t]*:?[ \\t]*#([0-9]+)")]'`

Keep both regex flags: `i` for case, and `m` so that a `Refs #N` below the summary line is found. Take the union of all three sources. Record each link as **closing** (a close, fix or resolve form, or a reported closing reference) or **plain** (`refs`).

Check each number `<k>`, judged by the HTTP status and never by the wording of an error message:

`gh api --include repos/116-Labs/cuecal/issues/<k> --jq .pull_request`

- **404:** not a link.
- **Output that is not empty:** the number is a pull request, so it is not a link. `gh issue view` cannot tell the two apart, because it succeeds on a PR.
- **Empty line:** a real issue.
- **Any other failure:** end `failed` naming the read.

If no real issue remains, end `needs-clarification`. Its `questions` name each linked number that was not an issue, or say that the PR links none.

For the result's `issue`, pick one issue. An issue named in the dispatch wins. Otherwise take the first match in this order:

1. a reported closing issue
2. a closing-keyword line in the body
3. a closing-keyword line in the commits
4. a `Refs` line in the body, then in the commits

Read each issue fresh, as it stands now, never from a copy taken when the PR opened:

- its body: `gh api repos/116-Labs/cuecal/issues/<k> --jq .body`
- every comment: `gh api repos/116-Labs/cuecal/issues/<k>/comments --paginate --jq '.[] | {user: .user.login, body}'`

Comments that clarify or narrow scope are part of the spec. A maintainer may add a criterion by editing the issue while the PR is open. A review that graded a remembered copy would approve the old scope, so grade criteria added by an edit like the rest.

The text between an opening `<!-- gaal:plan-drift -->` line and its closing `<!-- /gaal:plan-drift -->` line, and any comment carrying the opening marker, is the implementer's account of how its plan changed. Treat it as a claim to check, never as spec. Everything else in the body is the author's spec, including text a maintainer added after a plan-drift section.

Write down every linked issue's acceptance criteria in order. A PR that links several issues is judged against all of them. If a linked issue has no checkable acceptance criteria, end `needs-clarification`, with `questions` saying what is missing.

### 3. Signal step: post the start signal

Skip this step in preview. The profile's start signal is a reaction:

`gh api repos/116-Labs/cuecal/issues/<n>/reactions --method POST --raw-field content=eyes`

If it fails because of auth expiry or a rate limit, end `failed` (`fail-closed-reads`). Any other failure is noted for the report, and the run carries on.

### 4. Checkout step: fetch, check out and install the head

From `<checkout>`, fetch in this order:

1. `git fetch origin <base>`
2. `git fetch origin pull/<n>/head`
3. `git rev-parse FETCH_HEAD`

Run the third command right after the head fetch, before any other fetch: `FETCH_HEAD` holds only the last fetch. That sha is `<head>`, the head this review checks out and judges.

Then:

1. Compute `<merge-base>` with `git merge-base <head> origin/<base>`.
2. Create the review worktree with `git worktree add --detach <run-dir>/worktree <head>`, then `cd <run-dir>/worktree`.
3. Run `uv sync --locked`. Run it every time, even when a `.venv` seems present, since it may be stale (`install-before-gates`).

If the install fails:

- **The PR changes a dependency manifest or lockfile (`pyproject.toml`, `uv.lock`):** the PR broke the install. Record a **Blocking** finding naming `uv sync --locked`. Skip the gates in the gate step. The review says that what the gates would have shown is unverified.
- **Otherwise:** the head cannot be verified for reasons outside the PR. Post no review, remove the worktree, and end `failed` naming `uv sync --locked`.

From here on, remove the worktree on every exit path before the result step: `cd <checkout>`, then `git worktree remove --force <run-dir>/worktree`.

### 5. Re-review step: limit attention to the delta

Find earlier review-pr reviews by their signature line, never by login. GitHub spells an App's login three ways, and `GAAL_LOGIN` is only one of them.

`gh api repos/116-Labs/cuecal/pulls/<n>/reviews --paginate --jq '.[] | select((.body // "") | contains("gaal review-pr · run ")) | {id, head: ((.body | capture("Reviewed head: (?<sha>[0-9a-f]{40})").sha) // "none")}'`

**No match:** this is round 1. Review the whole diff, `git diff <merge-base> <head>`.

**One or more matches:** reviews come oldest first, so the last match is the last review. Its `head` is `<old-head>`.

- If `<old-head>` is `none`, review the whole diff.
- Otherwise, make sure `<old-head>` is local, running `git fetch origin <old-head>` when it is not.
- Compute `<old-merge-base>` with `git merge-base <old-head> origin/<base>`. That is the base the old head was reviewed against, never the current head's merge base.
- Review the delta with `git range-diff <old-merge-base>..<old-head> <merge-base>..<head>`. This works even when history was rewritten.
- If `<old-head>` cannot be fetched, review the whole diff and say so in the review.

On a re-review, also re-check resolved threads. A resolved thread is not a fixed finding: a rebase can mark a thread outdated, and revise-pr then resolves it unfixed.

1. List this PR's review threads as the anchor step does.
2. Read each earlier review-pr review's body with `gh api repos/116-Labs/cuecal/pulls/<n>/reviews/<id> --jq .body`, for each `id` listed above. Take the thread links its Dispositions list names.
3. Keep each thread that meets all three conditions:
   - `isResolved` is true.
   - An earlier review-pr review opened it (its first comment's `pullRequestReview { databaseId }` is one of the listed `id`s), or such a review's Dispositions list links it as a finding's `thread`. The second case includes a thread a person or another bot opened.
   - `resolvedBy { login }` is the PR's author or `GAAL_LOGIN`, compared in any of their spellings.

A thread any other account resolved is a person's decision and is not re-checked: that person accepted the finding.

Where gaal pushes as a person's own login (no push App), the PR's author is that person, so their resolution counts as gaal's and is re-checked. A finding that still reproduces opens a thread again, and such a PR is merged by hand.

When a kept thread's finding still reproduces on `<head>`, it is a candidate finding of this review whatever the delta. The criteria walk verifies it, and it takes a disposition again.

Note for the report whose push moved the diff since the last review. This skill never pushes, so it is the author's push or revise-pr's.

### 6. Correctness step: review the code

Review the diff, or the delta plus the re-checked threads, for logic, edge cases, error handling, concurrency and security. Scripts, workflows and skill files count as code. In each of them, look for:

- nonexistent flags
- word-splitting and quoting
- documented but unimplemented flags
- injection through untrusted input
- non-idempotent re-runs
- swallowed errors
- unverified success inside loops

A PR that makes a pre-existing defect reachable owns it. That defect is a Blocking or Secondary finding of this PR, never Pre-existing, even though the code it sits in is untouched.

### 7. Gate step: run the gates

Skip this step when the checkout step recorded a Blocking install finding.

In `<run-dir>/worktree`, run each gate in profile order, timed:

1. `date -u +%s`, then `uv run ruff check .`, then `date -u +%s`. Record `{name: "lint", command: "uv run ruff check .", exit_code, duration_ms}`.
2. `date -u +%s`, then `uv run pytest`, then `date -u +%s`. Record `{name: "test", command: "uv run pytest", exit_code, duration_ms}`.

A gate that exits non-zero on the head is a **Blocking** finding naming the gate. A review that ran a failing gate never ends `done` (`gates-final-tree`).

The profile has no preflight or advisory checks, so nothing else runs here.

### 8. Tests step: name the covering tests

For each behavioural change in the diff, name the test that covers it (`tests-named`). That is either a new or changed test that fails without the change, or an existing test that already exercises it.

A behavioural change with no covering test is a finding:

- **Blocking** when a linked issue's criteria ask for tests.
- **Secondary** otherwise.

For each new or changed test, note whether it ran in the gates this run ran. A test the gates never ran proves nothing about the head.

A change is tested only when a test fails without it. A test that also passes on the base proves nothing. To show a failure without the change, run the test on the merge base:

1. `git worktree add --detach <run-dir>/base-worktree <merge-base>`
2. `cd <run-dir>/base-worktree`
3. `git checkout <head> -- <test-path>`, once for each new or changed test file.
4. `uv sync --locked`
5. `uv run pytest`. It runs the whole suite, so read the named tests' results from its output.
6. `cd <checkout>`
7. `git worktree remove --force <run-dir>/base-worktree`. The copied tests leave this worktree modified, so the forced remove is needed.

If that cannot be done, the Tests section says that "fails without the change" was reasoned from the code, not run on the base.

### 9. Description step: read the description only now

`gh pr view <n> --repo 116-Labs/cuecal --json title,body`

Read the description only after the independent passes have produced findings (`description-last`). A description read first becomes the map, and the author's blind spots become the reviewer's.

Treat it as a set of claims to test:

- It can add findings.
- It never removes a verified finding (`description-drops-finding`).
- It never limits what is reviewed, its focus section included (`description-sets-scope`).

Note its **Deferred** list, if any, and its test-plan boxes. Write a description-accuracy note for the report.

### 10. Criteria walk: verify findings and walk the criteria

Verify every candidate finding at its exact line on `<head>`, and drop anything that does not reproduce (`findings-verified`).

Then walk every acceptance criterion of every linked issue on `<head>`. On a re-review, walk all of them again, not only the ones the delta touches. Give each criterion one status:

- **verified:** met, and shown by a gate, a test or a check you ran.
- **failed:** not met.
- **unverified:** you could not confirm it on this head. Say what a person must check.
- **deferred:** only when the link is plain (`Refs`) and the Deferred list names the criterion.

Deferral is scope, not an excuse:

- A deferred criterion is still checked and listed.
- Deferral never drops a correctness, gate or other finding.
- Deferral changes nothing under a closing keyword.
- A Deferred entry that is not one of the issue's criteria is a Secondary finding.

### 11. Sort step: sort findings and give each a disposition

Sort every finding into **Blocking**, **Secondary**, **Nits** or **Pre-existing**, using these rules:

- A **failed** criterion is Blocking unless it is deferred.
- An **unverified** criterion is a Secondary finding.
- A **Deferred list under a closing keyword** is Blocking, because merging would close the issue with criteria still open.
- A **ticked test-plan box for a gate that did not run on the head** is Blocking. Compare each ticked box with the gates this run ran and the CI result. The description then claims evidence that does not exist.
- A **contradiction** is a finding on lines the PR adds that disagrees with other code in the PR: a hint, message, doc, test or default that disagrees with the new behaviour. Whatever its bucket, it ends as a thread, never only as body text (`contradiction-fixed-or-threaded`). In this repository it is never fixed by the review, because the review pushes nothing. An earlier review listed one only in its body (a retry hint that disagreed with the new handoff), and it was lost at merge.

**Workflow, CLI and API constructs.** This applies to every platform, CLI or API construct that the PR's workflow or script files add or change. Before raising a finding about what the construct accepts, check whether the PR's own CI already exercised it, and read that run.

1. Read the workflow's `on:` triggers in `<run-dir>/worktree/.github/workflows/`, including their `branches` and `paths` filters and the `-ignore` forms. Read the job's and step's `if:` conditions.
2. List the CI runs on the head:
   `gh run list --repo 116-Labs/cuecal --commit <head> --json databaseId,workflowName,event,status,conclusion --limit 100`
   Exactly 100 results means truncated.
3. Read a run's jobs with `gh run view <ci-run-id> --repo 116-Labs/cuecal --json jobs`.

CI **could have run** a construct when a `pull_request` run on this head would execute the step that holds the PR's version of it. That means the trigger's filters match this PR's base and changed files, and the job's and step's `if:` conditions are true for a `pull_request` event. A `pull_request_target` trigger does not count: it runs the base branch's copy of the workflow.

- **CI ran the construct on `<head>` and passed:** not a finding.
- **CI could have run it but did not, or the run failed:** Blocking. Its behaviour is unverified, and lint does not verify it.
- **CI cannot run it** (it triggers only on `pull_request_target`, on a push to the base, a tag, a release or a schedule, or filters or `if:` skip it for this PR): a Secondary finding naming what a person must check. Its thread keeps the PR from merging automatically until a person resolves it, and that is intended.

The required `zizmor` check is read from CI like this, never run locally.

The description never removes a construct finding. If the author states the construct was verified by a command, the finding says "the author states it was verified by `<command>`". If that command is one this run may execute, run it and record the result in the finding.

**Dispositions.** Every Blocking finding, Secondary finding and contradiction ends with exactly one disposition (`finding-disposed`):

- **fixed:** the auto-fix step pushed its fix. This never happens in this repository.
- **thread:** an inline or file-level thread that the posting step opens, or an earlier review's still-unresolved thread that already carries the finding.

Apply the dispositions by bucket:

- **Blocking:** always a thread.
- **Contradiction:** a thread.
- **Secondary:** a thread. A Secondary finding is this PR's own: it does not reproduce on the base. So it never meets the follow-up bar and is never filed. That includes a defect in untouched code that this PR makes reachable.
- **Pre-existing:** filed when it meets the shared follow-up bar, that is, a user-visible defect outside the diff that reproduces on the base: wrong output a user can see. Otherwise it is recorded in the review body. Pre-existing defects never open threads.
- **Nit that is not a contradiction:** no disposition, because it is safe to merge by definition. A nit that is not safe to merge is Secondary.

### 12. Verdict step: choose the verdict

Apply this rule (`verdict-follows-findings`), and state it in the review:

- at least one Blocking finding → **request changes**
- no Blocking finding → **approve** (nits may remain)
- undecidable → **comment**

Then decide what is posted:

1. **`GAAL_LOGIN` is empty or absent:** post **comment** whatever the verdict, with the verdict as the first line (`identity-withholds`). Set `approval_withheld: identity` when the verdict is approve.
2. **`GAAL_LOGIN` equals the PR author in any spelling** (`<slug>[bot]`, `<slug>` or `app/<slug>`): post **comment** with the verdict as the first line (`no-self-verdict`). Set `approval_withheld: author` when the verdict is approve.
3. **`GAAL_LOGIN` is set, did not write the PR, and is not the review identity** (no spelling of `116-labs-gaal-review[bot]`): post request changes when that is the verdict. When the verdict is approve, post **comment** with `approval_withheld: identity` (`identity-withholds`).
4. **Otherwise:** post the verdict as it is.

Whenever approve is posted as comment, the review says so, and says that the PR is otherwise clean. Never approve through another identity, and never retry a refused approval under a different one (`second-identity-approval`).

### 13. Auto-fix step: send every fix to the author

`review.identity.reviewer` is `separate`, so this run pushes nothing. A GitHub App's run token cannot push, and gaal refuses an approval from a review run that pushed. So:

- Every small fix the review would have made becomes a finding sent to the author. For a Blocking finding, a Secondary finding or a contradiction, its disposition is **thread** (`finding-disposed`).
- A small fix with exactly one reasonable form that is **not behavioural** (a typo, a wording fix, a doc line) may carry a one-click suggestion block in its thread.
- A behavioural change is never offered as a suggestion block. It goes to the author as a finding in prose (`behavioral-suggestion`).
- Nothing is staged, committed, collapsed or pushed. That keeps these rules trivially:
  - `explicit-staging`, `commit-foreign-edits`
  - `base-untouched`
  - `rewrite-foreign-branch`, `bare-force-push`, `push-failure-states`
  - `collapse-remote-contained`, `collapse-content-preserved`, `collapse-keeps-link`, `collapse-before-approve`
- The "Fixed in" list is empty and says "none". No finding appears in it and also inline (`fixed-not-flagged`).
- If the remote head moved during the review (`git fetch origin pull/<n>/head` gives a sha other than `<head>`), note it in the report. The review still names `<head>`, the head it judged.

### 14. Filing step: file follow-ups before posting

File follow-ups only for Pre-existing findings that meet the shared follow-up bar. Never file a Blocking finding, a Secondary finding or a contradiction.

**In preview,** file nothing. The review body marks each such finding as `would file`.

**Otherwise,** look first for an issue already filed for the finding:

`gh issue list --repo 116-Labs/cuecal --state all --search "\"gaal:follow-up pr=<n>\" in:body" --json number,title,body --limit 100`

- A search that returns a full 100 is truncated (`complete-listings`). End `failed`.
- A search that fails stops the run (`fail-closed-reads`).
- When a listed issue carries the same finding, its number is the disposition. File nothing new.

Otherwise, write the issue body with the file tool to `<run-dir>/scratch/follow-up-<k>.md`. The body names:

- the defect
- its reproduction on the base
- the files involved
- a link to this PR

It also carries the marker line `<!-- gaal:follow-up pr=<n> -->`. Then create the issue:

`gh issue create --repo 116-Labs/cuecal --title "<title>" --body-file <run-dir>/scratch/follow-up-<k>.md`

If the create errors, never retry it, because a retry could file the issue twice. Run the same search once more:

- If it now lists an issue for the finding, that issue was filed anyway and is the disposition (`filed #<n>`).
- Otherwise the filing failed. Record the finding in the review body and name the failed filing in the report.

### 15. Anchor step: list threads and compute anchors

**List this PR's review threads.** Write `<run-dir>/scratch/threads.graphql` with the file tool. It is a paginated query on `repository(owner, name) { pullRequest(number) { reviewThreads(first: 100, after: endCursor) { … } } }`. For each node it selects:

- `id`, `isResolved`, `path`
- `resolvedBy { login }`
- `comments(first: 1) { nodes { body url pullRequestReview { databaseId } } }`

Run it:

`gh api graphql --paginate --field query=@<run-dir>/scratch/threads.graphql --raw-field owner=116-Labs --raw-field name=cuecal --field number=<n>`

The listing is paginated to the end (`complete-listings`), and a failed read stops the run (`fail-closed-reads`).

**Reuse unresolved threads.** When an earlier review's thread is still unresolved (`isResolved` false) and carries the same finding, that thread is the finding's disposition. Record its first comment's `url`, and open no second thread.

**Decide which findings get a new thread.**

- **Round 1:** every Blocking finding, contradiction and Secondary finding not carried by an earlier unresolved thread. A nit may also open a thread on round 1, and it carries no disposition.
- **Round 2 and later:** the same Blocking findings, Secondary findings and contradictions, never a nit that is not a contradiction (`rereview-converges`). Nits stay in the body. A nit on lines an earlier round already read is omitted. Questions, and any view on another reviewer's open thread, go in the review body, never in a new thread.

**Compute anchors from the patch.** Read the patch hunks:

`gh api repos/116-Labs/cuecal/pulls/<n>/files --paginate --jq '.[] | {filename, patch}'`

Nothing was pushed, so this is the reviewed head's patch.

- Anchor lines come from the right-hand side (`RIGHT`) of the hunks.
- When a finding has no changed line of its own (an unverified criterion, a workflow construct the PR's CI could not run, a finding about the description), anchor it on the changed line closest to what it concerns. Failing that, anchor it on the PR's first changed line.

### 16. Posting step: post one review

**Compose the review body** with the file tool at `<run-dir>/scratch/review.md`, in this order:

1. The verdict on the first line, and the rule applied (`verdict-follows-findings`). Add the approve-posted-as-comment note when it applies.
2. Findings by bucket: Blocking, Secondary, Nits, Pre-existing. Every finding with a new thread is listed in its bucket and also carried as an inline (or file-level) thread. Every finding an earlier unresolved thread carries is listed in its bucket, never threaded again.
3. Acceptance-criteria results: each criterion of each issue as verified, failed, unverified or deferred. A deferred criterion is never shown as met.
4. **Tests:** each new or changed test and whether it ran in the gates, each behavioural change with no test, and whether "fails without the change" was run on the base or reasoned from the code.
5. **Fixed in:** "none". This run pushes nothing.
6. **Dispositions:** each Blocking finding, Secondary finding and contradiction with exactly one of `fixed in <sha>` or `thread`. A reused thread gives its first comment's `url`. Each filed Pre-existing finding is listed as `filed #<n>` (`would file` in preview), so every follow-up issue is linked from the body (`finding-disposed`).
7. On a re-review: which of this review's own earlier threads the delta answered (`rereview-converges`).
8. No sign-off line, because `review.sign_off` is not set.
9. The line `Reviewed head: <head>` (`signed-review`).
10. Last, on a line of its own, exactly `gaal review-pr · run <run-id>`. Never reword it. A signature reworded from run to run hid verdicts from readers that matched one form.

**In preview,** post nothing. Leave the body in `<run-dir>/scratch/review.md`, carry the would-be verdict into the run result, and skip step 17.

**Clear a stale pending review.** Before any call that posts, look for a pending review this account already has. GitHub allows one per account per PR.

`gh api repos/116-Labs/cuecal/pulls/<n>/reviews --paginate --jq '.[] | select(.state == "PENDING") | {node_id, body: (.body // "")}'`

- **One whose body carries `<!-- gaal:review-pr pending -->`:** a run that stopped mid-post left it. Delete it. Write `<run-dir>/scratch/delete.graphql` with the file tool: a `deletePullRequestReview(input: {pullRequestReviewId: rid})` mutation with a String variable `rid`. Then run:
  `gh api graphql --field query=@<run-dir>/scratch/delete.graphql --raw-field rid=<node_id>`
- **One without that line:** it is a person's draft and is never deleted. Post nothing, and end `failed` naming it.

**Post the review in three calls.** The review endpoint takes no file-level comment. Never use the single-comment endpoint (`pulls/<n>/comments`): it posts each comment as a separate review.

**Call 1: create the review pending.** Write `<run-dir>/scratch/pending.json` with the file tool, with these fields:

- `commit_id`: `<head>`
- `body`: only the line `<!-- gaal:review-pr pending -->`. Never put the review body here: a pending review must not carry the `Reviewed head` line or the signature.
- no `event`
- `comments`: each inline thread as `{path, line, side: "RIGHT", body}`

Then run:

`gh api repos/116-Labs/cuecal/pulls/<n>/reviews --method POST --input <run-dir>/scratch/pending.json`

Record the answer's `node_id`.

If GitHub refuses an inline anchor (a 422; nothing is created):

1. Re-read the patch hunks, re-anchor, and create the pending review again, once.
2. If GitHub refuses again, move each finding whose anchor it refused to a file-level thread. When GitHub does not say which anchor it refused, move every finding with a new thread. A file-level thread sits on the file the finding concerns, or failing that on the PR's first changed file.
3. Create the pending review with the remaining line comments.
4. Note the line-anchor fallback for the report.

**Call 2: add each file-level thread.** Write `<run-dir>/scratch/add-thread.graphql`: an `addPullRequestReviewThread` mutation with input `{pullRequestReviewId: rid, path: path, body: body, subjectType: FILE}` and no line. Write each thread's body to `<run-dir>/scratch/thread-<k>.md`. Then run:

`gh api graphql --field query=@<run-dir>/scratch/add-thread.graphql --raw-field rid=<node_id> --raw-field path=<path> --field body=@<run-dir>/scratch/thread-<k>.md`

`rid` is the pending review's `node_id`, never its numeric `id`.

**Call 3: submit the review.** Write `<run-dir>/scratch/submit.graphql`: a `submitPullRequestReview(input: {pullRequestReviewId: rid, event: event, body: body})` mutation, declaring `event` as `PullRequestReviewEvent!`. It selects `pullRequestReview { databaseId }`. Then run:

`gh api graphql --field query=@<run-dir>/scratch/submit.graphql --raw-field rid=<node_id> --raw-field event=<event> --field body=@<run-dir>/scratch/review.md`

`<event>` is one literal word chosen in the verdict step: `APPROVE`, `REQUEST_CHANGES` or `COMMENT`. The full body replaces the pending line. Record the returned `databaseId` as `<review-id>`.

**If a file-level thread is refused, or the submit fails:** delete the pending review with the delete mutation above, so nothing is posted. End `failed`, naming the refused anchor or the failed submit. A review that cannot open a finding's thread is never posted (`finding-disposed`), because a review body alone would let `merge.auto` merge the PR past the finding.

### 17. Thread listing: handle the threads this review opened

Skip this step in preview.

**Stop if `<review-id>` is empty.** End `needs-human` with a `reason`. Never fall back to matching by reviewer login: that would take in threads another run or the same account opened.

Re-run the threads query from the anchor step, and keep only the threads whose first comment's `pullRequestReview { databaseId }` equals `<review-id>` (`resolve-own-threads-only`).

- **Threads that carry a finding's thread disposition** (Blocking, Secondary, contradiction): never resolve them. They stay open for the author and revise-pr, and keep the PR unconverged (`finding-disposed`). Never resolve a thread to clear the merge path (`resolve-to-unblock`).
- **Threads that stay open anyway:** questions, blockers, suggestion blocks and contradiction threads.
- **Nit threads with no suggestion block** that this review disposed of itself (recorded only, or an agreed trade-off): first reply, then resolve.
  - Reply: write `<run-dir>/scratch/reply.graphql` (an `addPullRequestReviewThreadReply` mutation with input `{pullRequestReviewThreadId: tid, body: body}`) and the reply body file `<run-dir>/scratch/reply-<k>.md`. Then run:
    `gh api graphql --field query=@<run-dir>/scratch/reply.graphql --raw-field tid=<thread_id> --field body=@<run-dir>/scratch/reply-<k>.md`
  - Resolve: write `<run-dir>/scratch/resolve.graphql` (a `resolveReviewThread` mutation with input `{threadId: tid}`). Then run:
    `gh api graphql --field query=@<run-dir>/scratch/resolve.graphql --raw-field tid=<thread_id>`

Nothing is filed here: the filing step already filed every follow-up issue.

A reply or resolve that fails after the review is posted is reported, and the run ends `needs-human`. Never retry it: a retry could post a second review.

Report the open threads split into **suggestions** and **author-owed**.

### 18. Result step: write the run result

Run this step on every exit path, failures included (`run-result-written`).

1. Remove any worktree under `<run-dir>` that still exists: `cd <checkout>`, then `git worktree remove --force <run-dir>/worktree`.
2. Record `finished_at` with `date -u +%Y-%m-%dT%H:%M:%SZ`.
3. Write `<run-dir>/result.json.tmp` with the file tool.
4. Run `mv <run-dir>/result.json.tmp <run-dir>/result.json`. Never leave the `.tmp` file behind.

The result has these fields:

- `schema_version`: `1`
- `run_id`: the value of `GAAL_RUN_ID`
- `blueprint`: `"review-pr"`
- `blueprint_version`: `"1.9.0"`
- `repo`: `"116-Labs/cuecal"`
- `issue`: the issue picked in the link step, or `null`
- `pr`: `<n>`, or `null` when no PR was determined
- `status`: one of the exit states below
- `reason`: required unless `status` is `done`. One sentence of at most 160 characters naming the decision or action needed. Detail goes in the review and the final report.
- `questions`: required and non-empty for `needs-clarification`
- `attempts`: `1`
- `gates`: the gate runs on the reviewed head, in the order they ran, each with `name`, `command`, `exit_code` and `duration_ms` (`gates-final-tree`). A gate that did not run is absent, not passed (`truthful-report`). The list is `[]` when no gate ran. A `done` result never lists a non-zero `exit_code`.
- `branch`: the PR's head branch name, or `null`
- `commit_sha`: `null`, because this run pushes nothing
- `review` (required when `done`; include it whenever a verdict was reached, preview included):
  - `verdict`: `approve`, `request-changes` or `comment`, as actually posted (or would be posted, in preview)
  - `blocking`: the count of Blocking findings, counted even when identity downgraded the verdict to comment
  - `non_blocking`: the count of Secondary findings, Nits and Pre-existing findings
  - `head`: the full 40-character `<head>` from the `Reviewed head` line
  - `criteria`: every linked issue's criteria in order, each `{text: "#<issue>: <criterion as the issue states it>", status}`, with `status` one of `verified`, `failed`, `unverified` or `deferred`
  - `approval_withheld`: set only when the verdict was approve but comment was posted. It is `author`, else `identity`, else `pushed` (never `pushed` here).
- `started_at`, `finished_at`

No `push` object, since nothing was pushed. No other fields.

Then give the final report:

- the acceptance-criteria results
- the description-accuracy note
- the thread ledger: open threads split into suggestions and author-owed
- the push and collapse outcome: "none — separate review identity; old → new sha unchanged"
- inline versus body-only finding counts, with the reason for each body-only finding (a nit, a recorded Pre-existing finding, or a filed finding listed with its link)
- the follow-up issues filed, and any failed filing
- any line-anchor fallback
- whose push moved the diff
- any failed start signal

## Exit states

- `done`: no Blocking finding stands, the review is posted (in preview, composed), and no thread is left that the author owes. A clean review whose approve was posted as comment ends `done` with `review.approval_withheld`, so Gaal can tell it apart from a review that leaves the author work.
- `needs-human`: any of these:
  - a Blocking finding stands
  - threads are left for the author: every finding whose disposition is a thread, whether or not identity downgraded the verdict to comment
  - the id of the review just posted was empty, so the threads it opened could not be listed
  - a thread reply or resolve failed after the review was posted

  `reason` summarizes which.
- `needs-clarification`: any of these:
  - no PR could be determined
  - the PR links no issue by the shared issue-link rule; a link to a number that names no issue counts as none, and `questions` name the number
  - a linked issue has no checkable acceptance criteria

  `questions` say what is missing.
- `failed`: `reason` names the step. Any of these:
  - the PR is not open
  - GitHub cannot find the PR number (404)
  - the install failed on a PR that changes no dependency manifest or lockfile, so nothing was posted
  - a read failed or a listing was truncated (`fail-closed-reads`, `complete-listings`)
  - a person's pending draft review stands
  - posting failed even after falling back to file-level threads, including a refused file-level thread or a failed submit; nothing was posted

## Invariants

- `description-last`: The PR description is read only after the independent passes (correctness, gates, acceptance criteria) have produced findings.
- `verdict-follows-findings`: The verdict is request changes when there is at least one Blocking finding, approve when there are none, and comment when undecidable. The review states the rule applied.
- `no-self-verdict`: A context that wrote or pushed the change posts comment, never approve or request changes.
- `identity-withholds`: A run that is not the separate review identity posts comment when the findings call for approve, with `approval_withheld` set to `author` or `identity`. With `GAAL_LOGIN` empty or absent, the run posts comment whatever the verdict, with the verdict as the first line, and `review.blocking` still counts what it found.
- `findings-verified`: Every posted finding was reproduced at its line on the reviewed head.
- `tests-named`: Every behavioural change names its covering test, or is a finding: Blocking when the issue's criteria ask for tests. The Tests section lists each new or changed test and whether it ran in the gates.
- `signed-review`: The body ends with a `Reviewed head: <sha>` line and then `gaal review-pr · run <run-id>` on a line of its own. A `sign_off` line would come before them; none is set here.
- `fixed-not-flagged`: A fix pushed by the review appears in "Fixed in" and never also as an inline finding. This review pushes none.
- `resolve-own-threads-only`: Only threads this review opened are resolved, matched by review id, never by login, and each only after a reply.
- `collapse-before-approve`: Any collapse happens before anchors are computed and before the review is posted. No collapse runs here.
- `contradiction-fixed-or-threaded`: A contradiction is fixed or carried by a thread, on every round. It is never left only in the body and never filed.
- `rereview-converges`: After round 1, a new thread opens only for a Blocking finding, a Secondary finding or a contradiction, and never for one an earlier unresolved thread carries. The review names which earlier threads the delta answered.
- `finding-disposed`: Every Blocking finding, Secondary finding and contradiction ends fixed or thread before the review is posted. A Pre-existing finding that meets the follow-up bar ends filed, or is recorded when filing failed. A review that cannot open a finding's thread is not posted.
- `explicit-staging`: Stage only paths this run wrote. This run stages nothing.
- `base-untouched`: Never commit or push to the base branch.
- `fail-closed-reads`: Errors, auth expiry and rate limits stop the run with `failed`. They never become "nothing".
- `complete-listings`: Every listing is paginated to the end, or the run ends `failed` naming it.
- `truthful-report`: The report and result describe what actually happened. A gate that did not run is absent.
- `status-preserved`: No command's failure is lost to a pipe, a filter or a guard.
- `attribution-policy`: Attribution is `none`. Nothing is added or dropped on the agent's own initiative.
- `run-result-written`: `result.json` is written atomically on every exit path.
- `gates-final-tree`: `gates` lists only the runs on the reviewed head, in order. A failing required gate is a Blocking finding.
- `install-before-gates`: `uv sync --locked` runs before the gates every time, in every worktree.
- `push-failure-states`: A failed push is handled per the shared rule. This run pushes nothing.
- `collapse-remote-contained`, `collapse-content-preserved`, `collapse-keeps-link`: These collapse safety rules apply to any collapse. This run never collapses.

## Forbidden actions

- `description-sets-scope`: letting the description or its focus section limit what is reviewed.
- `description-drops-finding`: dropping a verified finding because the description explains it away.
- `second-identity-approval`: approving through another identity, or retrying a refused approval under a different one.
- `rewrite-foreign-branch`: pushing to or rewriting a fork's branch or commits authored by someone else.
- `resolve-to-unblock`: resolving threads to clear the merge path.
- `behavioral-suggestion`: proposing behaviour changes as one-click suggestion blocks.
- `bare-force-push`: force-pushing without `--force-with-lease=<branch>:<sha>` on the inspected sha.
- `admin-bypass`: merging, pushing or rewriting with admin privileges, such as `gh pr merge --admin`.
- `bypass-hook`: skipping or redirecting the repository's verification (`--no-verify`, `git commit -n`, `--no-gpg-sign`, `core.hooksPath`, switching a hook manager off), or retrying a rejected commit or push through another route.
- `machine-specific-paths`: hard-coding a person's home directory, private scripts or services.
- `commit-foreign-edits`: committing changes this run did not make.
