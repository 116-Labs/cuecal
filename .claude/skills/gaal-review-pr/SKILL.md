---
name: gaal-review-pr
description: >-
  Adversarially reviews one open pull request in 116-Labs/cuecal against the acceptance criteria of its linked GitHub issues, read fresh at review time, and against the profile gates (uv run ruff check . and uv run pytest). It reads the PR description last and treats it as a set of claims to test. It posts exactly one signed review whose verdict follows from the verified findings. It leaves open only the threads the author owes, and it writes the run result to result.json in the run directory. Use it when a dispatch hands over a repo and a PR number, in post or preview mode, and asks for the review-pr step. In this repository the review runs as the separate review identity, so it never commits or pushes, and every fix goes to the author as a finding. Do not use it to implement an issue (gaal-implement), open a PR (gaal-open-pr), revise a PR after review (gaal-revise-pr), merge or deploy. When no PR can be determined, do not guess. End as needs-clarification instead.
---
<!-- gaal-stamp blueprint=review-pr@1.9.0 shared=1.5.0 profile=833de6ae33df6d68 generated=2026-10-08 core=b8870cb250ef9e03 forbidden=54c30c1c66633c73 content=b45ece58e44b8cfb -->

# gaal-review-pr (blueprint review-pr 1.9.0)

Review an open PR the way a careful maintainer would. Judge it against the linked issues' acceptance criteria and the project's gates, without relying on how the PR describes itself. Post exactly one review, with a verdict that follows from the findings. Leave open only the threads the author genuinely owes.

## Project facts (from `.gaal/project.yml`)

- Repo: `116-Labs/cuecal`. Default branch: `main`. Visibility: private. Tracker: GitHub issues in the same repo.
- Gates are both required. Run them exactly as written, with nothing added:
  - `lint`: `uv run ruff check .`
  - `test`: `uv run pytest`
- `preflight`: none. `advisory`: none. `install`: none.
  - Nothing is ever installed.
  - A throwaway worktree would have no environment, so the gates run in this checkout itself, on the PR head checked out detached.
- Commits:
  - One commit per PR (`single_commit: true`), in Conventional Commits form.
  - Attribution is `none`: no AI attribution in any commit, PR body, issue body or review (`attribution-policy`).
  - This skill commits nothing.
- Branch prefix: `gaal/`. Quote every glob, for example `git branch --list 'gaal/*'`.
- Merge:
  - Method `squash`, with `message_source: commits`.
  - No merge queue (`queue: false`), and `auto: false`, so a person merges.
  - Branch protection requires 1 approval (`required_approvals: 1`).
  - Open threads do not block merge (`threads_block_merge: false`), and a review body blocks nothing. So everything the author owes must be a thread or a changes-requested verdict, never body text alone.
- Review:
  - Start signal: a `reaction`.
  - No extra `reviewers`.
  - `review.sign_off` is not set.
  - Identity is `reviewer: separate`, with review login `116-labs-gaal-review[bot]`. GitHub spells it three ways:
    - `116-labs-gaal-review[bot]` in REST
    - `116-labs-gaal-review` in GraphQL
    - `app/116-labs-gaal-review` in `gh --json`
  - The push identity is `116-labs-gaal-push[bot]`.
- Because `review.identity.reviewer` is `separate`, this skill **pushes nothing**:
  - The auto-fix step never commits or pushes, and the collapse never runs.
  - `commit_sha` is always `null`, and `approval_withheld: pushed` never applies.
- Limits: `review_rounds: 2`, `revise_rounds: 3`, `implement_attempts: 3`. Gaal enforces them across runs. This run is one review round and records `attempts: 1`.
- Stacking: the profile names no stacking tool. The base is whatever the PR targets: `main`, or a parent PR's branch for a stacked PR. Always read it from the PR metadata.

## Run context and command rules

- `GAAL_RUN_ID`, `GAAL_RUN_DIR` and `GAAL_LOGIN` come from the run context.
  - In every command below, `<run-dir>` stands for the literal run-directory path from the run context, and `<run-id>` stands for the literal run id.
  - Never write an environment variable, a `$`-expansion, a command substitution or backticks inside a command.
  - Never put `NAME=value` in front of a command.
- Allowed commands:
  - `git`, `gh`, `mkdir`, `mv`, `cp`, `ls`, `cat`, `date` and `pwd`, with any arguments.
  - `cd` to a literal path.
  - Exactly `uv run ruff check .` and exactly `uv run pytest`.
- Run one command per call. Never chain commands with `&&`, `;` or a pipe. There is no standalone `jq`: filter with `gh … --jq`.
- Write every file with the file-writing tool, never through shell redirection. That covers:
  - review bodies and thread bodies
  - GraphQL query files and JSON inputs
  - issue bodies
  - the result
- Pass bodies by path: `--body-file <file>`, `--raw-field body=@<file>` / `-F body=@<file>`, or `--input <file>`.
- GraphQL documents go in files under `<run-dir>/scratch/` and are passed as `-F query=@<file>`. Their variables are passed as fields, so the command line never carries a GraphQL variable sigil.
- Scratch space lives in `<run-dir>/scratch`. Never use `/tmp` or `mktemp`.
- Placeholders:
  - `<n>` is the PR number.
  - `<head>` is the fetched head sha.
  - `<base>` is the PR's base branch.
  - `<node-id>` is a GraphQL node id.
  - `<event>` is one of the three review events, `APPROVE`, `REQUEST_CHANGES` or `COMMENT`, written as one literal word.
  - Every other `<placeholder>` is a literal value you fill in.
- Never touch the hook setup (`bypass-hook`):
  - Never use `--no-verify`, `git commit -n`, `--no-gpg-sign`, a `-c` override of the hooks path, `--admin` (`admin-bypass`), `--force` on a push (`bare-force-push`), `git add -A`, `git add .` or `git commit -a`.
  - Never edit `.git/config` or a hook file.
  - This skill neither commits nor pushes, so none of these is ever needed. If you need the hooks directory, run `git rev-parse --git-path hooks`.
- A read that fails is never "nothing" (`fail-closed-reads`). An error, an auth expiry or a rate limit stops the run as `failed`, naming the read, unless a step names another outcome.
- Every listing is paginated to the end, or the run stops `failed` naming it (`complete-listings`).
- Judge each command by its own exit code. Never let a filter hide a failure (`status-preserved`).
- The skill holds no machine-specific path, private script or private service (`machine-specific-paths`). Everything comes from the profile and the run context.

**On every exit path, including failures, go to the cleanup step and then to the final step, Write the run result.**

## Steps

### Setup

1. Read the start time with `date -u +%Y-%m-%dT%H:%M:%SZ` and keep it as `started_at`.
2. Run `mkdir -p <run-dir>/scratch`.
3. Determine the PR number and the mode from the dispatch. The mode is post by default, or preview.
   - If no PR number can be determined, do not guess. End `needs-clarification` with a question asking which PR to review.
4. Record the checkout's starting point so you can restore it later:
   - `git rev-parse --abbrev-ref HEAD`
   - `git rev-parse HEAD`

### Read PR metadata (never the description)

5. Read the PR metadata, **without the description** (`description-last`, `description-sets-scope`):
   `gh pr view <n> --repo 116-Labs/cuecal --json number,state,baseRefName,headRefName,headRefOid,author,isCrossRepository,headRepositoryOwner,commits`
   Never request `body` here.
   - If GitHub cannot find the PR (HTTP 404), end `failed` naming the number.
   - If `state` is not `OPEN`, end `failed` because the PR is not open.
   - Keep `author.login` (in `gh --json` an App appears as `app/<slug>`). Keep `baseRefName` as `<base>`, and `headRefName` as the result's `branch`.
6. List the changed files completely with `gh api repos/116-Labs/cuecal/pulls/<n>/files --paginate`. Keep each file's `filename`, `status` and `patch`. A failed read ends `failed`.

### Linked issues (issue-link rule)

7. The linked issues are the union of three sources. Read all three every time, never the text sources only when GitHub reports none.
   - **Closing references GitHub reports:**
     `gh pr view <n> --repo 116-Labs/cuecal --json closingIssuesReferences --jq '.closingIssuesReferences[].number'`
   - **Body links.** This extracts only keywords and digits, so the description text never enters context:
     `gh pr view <n> --repo 116-Labs/cuecal --json body --jq '[(.body // "") | scan("(?im)^[ \\t]*(close|closes|closed|fix|fixes|fixed|resolve|resolves|resolved|refs)[ \\t]*:?[ \\t]*#([0-9]+)")]'`
   - **Commit-message links:**
     `gh api repos/116-Labs/cuecal/pulls/<n>/commits --paginate --jq '.[] | [(.commit.message // "") | scan("(?im)^[ \\t]*(close|closes|closed|fix|fixes|fixed|resolve|resolves|resolved|refs)[ \\t]*:?[ \\t]*#([0-9]+)")]'`

   Keep both regex flags:
   - `i` matches any case.
   - `m` makes `^` match at the start of every line. Without it, a `Refs #N` below the summary is never found.

   For each link, note whether it is **closing** (a close, fix or resolve form, or reported by GitHub) or **plain** (`refs`).
8. Check every number with `gh api --include repos/116-Labs/cuecal/issues/<number> --jq .pull_request`. Judge it by the HTTP status line, never by the wording of an error message.
   - `404`: nothing by that number, so it is no link.
   - `200` with a non-empty `pull_request`: the number is a pull request, so it is no link. `gh issue view` succeeds on a pull request, so it cannot tell the two apart.
   - `200` with an empty line: it is an issue.
   - Any other failure ends `failed` naming the read (`fail-closed-reads`).
9. If no issue remains, end `needs-clarification`. Its `questions` name every number that turned out to be no issue, or say that the PR links none.
10. Read each issue **fresh, as it stands now**, never as a copy from when the PR opened. A maintainer may have added a criterion while the PR was open, and a review graded against a remembered copy would approve the old scope.
    - Body: `gh issue view <number> --repo 116-Labs/cuecal --json number,title,body`
    - Comments: `gh api repos/116-Labs/cuecal/issues/<number>/comments --paginate`

    What counts as spec:
    - Comments that clarify or narrow scope are part of the spec.
    - Text between an opening `<!-- gaal:plan-drift -->` line and its closing `<!-- /gaal:plan-drift -->` line is the implementer's account of how the plan changed. So is any comment that carries the opening marker. Treat it as a claim to check, never as spec.
    - Everything else is the author's spec, including maintainer text added after a plan-drift section. Grade against the issue as its author and maintainers wrote it.

    Write down each issue's acceptance criteria in order, as `#<issue>: <criterion>`. A criterion added by an edit since the PR opened is graded like the others. A PR that links several issues is judged against all of them.

    If a linked issue has no checkable acceptance criteria, end `needs-clarification`, with `questions` saying what is missing.
11. Pick the result's `issue`, in this order of precedence:
    1. An issue named in the dispatch.
    2. A closing issue GitHub reports.
    3. In the body and then in each commit message, a closing-keyword link before a `Refs` link.

### Start signal

12. In post mode, react to the PR with:
    `gh api -X POST repos/116-Labs/cuecal/issues/<n>/reactions --raw-field content=eyes`
    Skip this in preview.
    - If the reaction fails for auth expiry or a rate limit, end `failed` naming the call (`fail-closed-reads`).
    - Any other failure is noted in the report, and the run carries on.

### Check out the head

13. Fetch in this order:
    1. `git fetch origin <base>`
    2. `git fetch origin pull/<n>/head`
    3. `git rev-parse FETCH_HEAD`, immediately after the head fetch and before any other fetch. That full sha is `<head>`, the head this review checks out and reviews.

    `FETCH_HEAD` holds only the last fetch. Read after the base fetch, it would name the base tip.
14. Run `git status --porcelain=v1 --untracked-files=all`.
    - If the checkout has changes this run did not make, leave them alone (`commit-foreign-edits`). End `failed` with a reason saying the checkout is dirty, so the head cannot be verified.
    - Otherwise run `git checkout --detach <head>`.
15. Install nothing. The profile names no `install` (`install-before-gates`), so the gates use the checkout's existing environment.

    If a gate cannot start because the environment does not resolve (a `uv` resolution or sync error, not a lint or test failure), decide which side caused it:
    - **The PR changes `pyproject.toml` or `uv.lock`:** the PR broke it. Record a Blocking finding naming the command. The review says that what the gates would have shown is unverified.
    - **Otherwise:** the head cannot be verified, for reasons outside the PR. End `failed` naming the command, and post no review.
16. Compute `<merge-base>` with `git merge-base <head> origin/<base>`, then read the diff with `git diff <merge-base> <head>`.

### Re-review step

17. Find the last review this skill posted. Find it by its signature, never by login: an App's login has three spellings, and `GAAL_LOGIN` is only one of them.
    `gh api repos/116-Labs/cuecal/pulls/<n>/reviews --paginate --jq '.[] | select((.body // "") | contains("gaal review-pr · run ")) | {id, head: ((.body | capture("Reviewed head: (?<sha>[0-9a-f]{40})").sha) // "none")}'`

    Reviews come oldest first, so the last match is the last review. Its `head` is `<old-head>`.
    - No match: this is round 1.
    - `head` is `none`: review the whole diff.
18. On a re-review, focus fresh attention on the delta since `<old-head>`. The criteria walk still covers every criterion again.
    1. If `<old-head>` is not local, fetch it with `git fetch origin <old-head>`. If it cannot be fetched, review the whole diff and say so in the review.
    2. Compute `<old-merge-base>` with `git merge-base <old-head> origin/<base>`. It is where the old head left the base it was reviewed against. Never use the current head's merge base here.
    3. If history was rewritten, run `git range-diff <old-merge-base>..<old-head> <merge-base>..<head>`. Otherwise run `git diff <old-head> <head>`.
    4. Note which of this skill's earlier threads the delta answered. The review names them (`rereview-converges`).
19. Re-check resolved threads. A resolved thread is not a fixed finding: a rebase can mark a thread outdated, and revise-pr may then resolve it unfixed.
    1. List the threads the way the anchor step does.
    2. For each `id` that the filter in step 17 listed, read that review's body with `gh api repos/116-Labs/cuecal/pulls/<n>/reviews/<id> --jq .body`. Take the thread links its Dispositions list names.
    3. Keep each thread that meets all three conditions:
       - `isResolved` is true.
       - An earlier review-pr review opened it, or a Dispositions list links it as a finding's `thread`. "Opened it" means its first comment's `pullRequestReview.databaseId` is one of those ids; never match it by login. A linked thread counts even when a person or another bot opened it.
       - Its `resolvedBy.login` is the PR's author or `GAAL_LOGIN`, compared in any of the three spellings.

       A thread that anyone else resolved is a person's decision. It stands and is not re-checked.

       Where gaal pushes as a person's own login (no push App), that person is the PR's author, so their resolution is re-checked too. Such a PR is merged by hand.
    4. Each kept thread whose finding still reproduces on `<head>` becomes a candidate finding of this review, whatever the delta. It takes a disposition again.

### Correctness pass

20. Review the diff for logic, edge cases, error handling, concurrency and security. Scripts, workflows and skill files count as code, and get this checklist:
    - nonexistent flags
    - word-splitting and quoting
    - documented but unimplemented flags
    - injection through untrusted input
    - non-idempotent re-runs
    - swallowed errors
    - unverified success inside loops

    A PR that makes a pre-existing defect reachable owns that defect. It is a Blocking or Secondary finding of this PR, even though the code it sits in is untouched, and it is never filed.

### Gates

21. Run each gate on `<head>` in this checkout. Time each one with separate commands:
    1. `date -u +%s`
    2. `uv run ruff check .`
    3. `date -u +%s`
    4. `date -u +%s`
    5. `uv run pytest`
    6. `date -u +%s`

    For each gate, record `name`, `command`, `exit_code` and `duration_ms` (the difference times 1000).

    A required gate that exits non-zero is a Blocking finding naming the gate, so this review cannot end `done` (`gates-final-tree`). There are no `preflight` or `advisory` checks to run.

### Tests

22. For each behavioural change, name the test that covers it (`tests-named`). That is either a new or changed test that fails without the change, or an existing test that already exercises the change.
    - A behavioural change with no covering test is a finding. It is Blocking when the linked issue's criteria ask for tests, Secondary otherwise.
    - For each new or changed test, note whether it ran in the gates this run ran.

    A test that also passes on the base proves nothing about the change, and a test the gates never ran proves nothing about the head.

    No allowed command can run the test suite on the base: only `uv run pytest` is allowed, exactly as written, and a throwaway worktree has no environment. So the Tests section says that "fails without the change" was reasoned from the code, not run on the base.

### Read the description, last

23. **Only now** read the description (`description-last`):
    `gh pr view <n> --repo 116-Labs/cuecal --json body --jq .body`

    Order is the defense: a description read first becomes the map, and the author's blind spots become the reviewer's.
    - Treat it as a set of claims to test. It can add findings. It can never remove or narrow one (`description-drops-finding`, `description-sets-scope`).
    - Note its **Deferred** list and its ticked test-plan boxes, if it has any.
    - Write a description-accuracy note for the report.

### Criteria walk

24. Verify every candidate finding at its exact line on `<head>`. Drop anything that does not reproduce (`findings-verified`).
25. Walk every acceptance criterion of every linked issue on `<head>`, on a re-review too. Give each one a status:
    - `verified`: met, and shown by a gate, a test or a check you ran.
    - `failed`: not met.
    - `unverified`: you could not confirm it on this head. Say what a person must check.
    - `deferred`: only when the link is plain (`Refs`) and the Deferred list names the criterion.

    Deferral is scope, not an excuse. It moves the named criteria out of this PR's bar, but they are still checked and listed. It never drops a correctness, gate or other finding, and it changes nothing under a closing keyword.

    A Deferred entry that is not one of the issue's criteria is a Secondary finding.

### Sort step

26. Sort the findings into **Blocking**, **Secondary**, **Nits** and **Pre-existing**.

    **Criteria and claims**
    - A `failed` criterion is Blocking unless it is deferred. An `unverified` criterion is Secondary.
    - A Deferred list under a closing keyword is Blocking, because merging would close the issue with criteria still open.
    - A ticked test-plan box for a gate that did not run on `<head>` is Blocking: the description claims evidence that does not exist. Compare each ticked box against the gates this run ran, and against the CI runs:
      `gh run list --repo 116-Labs/cuecal --commit <head> --json databaseId,workflowName,event,status,conclusion --limit 100`
      A listing that returns a full 100 is truncated, so end `failed` naming it (`complete-listings`).

    **Contradictions**
    - A contradiction is a finding on lines the PR adds that contradicts other code in the PR: a hint, message, doc, test or default that disagrees with the new behaviour.
    - Whatever its bucket, it ends as a thread here, because this repo's review never auto-fixes (`contradiction-fixed-or-threaded`). It is never left as body text only, and never filed.

    **Workflow and platform constructs: use live evidence first**
    - Before raising a finding about what a platform, CLI or API accepts, check whether the PR's own CI already exercised that construct, and read that run. A construct CI ran and passed is not a finding.
    - For a construct this PR's workflow or script files add or change, read the workflow's `on:` and `if:` conditions with `cat .github/workflows/<file>`, then read the runs on `<head>`.
    - CI **could have run** the construct when a `pull_request` run on this head would reach the step that holds the PR's version of it. That requires three things:
      - The `branches` and `paths` filters, and their `-ignore` forms, match this PR's base and changed files.
      - The job's `if:` is true for a `pull_request` event.
      - The step's `if:` is true for a `pull_request` event.
    - A `pull_request_target` trigger does not count. It runs the base branch's copy of the workflow, never the PR's.
    - If CI could have run the construct, and no run on `<head>` ran it and passed, it is **Blocking**. Its behaviour is unverified, and lint does not verify it.
    - If the PR's CI cannot run the construct, it is **Secondary**, and the finding names what a person must check. This covers:
      - workflows that trigger only on `pull_request_target`
      - push-to-base, tag, release or schedule triggers
      - steps whose filters or `if:` skip them for this PR

      Its thread keeps the PR from merging automatically until a person resolves it.
    - If the description says the construct was verified by a command, the finding says "the author states it was verified by `<command>`". When that command is one this run may execute, run it and record its result. The claim never drops the finding.

    **Pre-existing findings and nits**
    - A Pre-existing finding reproduces on the base, in code the PR did not touch. It never opens a thread.
    - A nit is safe to merge by definition. A nit that is not safe to merge is Secondary.
27. Give each finding exactly one disposition before posting (`finding-disposed`). This run pushes nothing, so nothing is **fixed**.
    - Every Blocking finding, Secondary finding and contradiction is a **thread**. That is either a new inline or file-level thread that the posting step opens, or an earlier review's unresolved thread that already carries the finding. A Blocking finding is always a thread.
    - A Secondary finding belongs to this PR (it does not reproduce on the base), so it never meets the follow-up bar and is never filed. That includes a defect in untouched code that this PR makes reachable. Filing it would let the PR merge with it.
    - A Pre-existing finding that meets the shared follow-up bar is **filed**. That bar is a user-visible defect outside the diff: wrong output a user can see, in code this PR did not touch, that reproduces on the base. A Pre-existing finding below the bar is recorded in the review body.
    - A nit that is not a contradiction takes no disposition.

### Verdict

28. Choose the verdict by the rule `verdict-follows-findings`:
    - At least one Blocking finding: **request changes**.
    - No Blocking finding: **approve**. Nits may remain.
    - Undecidable: **comment**.

    The review states the rule it applied.
29. Decide which event to post. Compare `GAAL_LOGIN` with the PR author, and with the review identity, in all three spellings each.
    - **`GAAL_LOGIN` empty or absent.** The author check is unknown, so post `COMMENT` whatever the verdict, with the verdict as the first line (`identity-withholds`). `review.verdict` is then `comment`, and `review.blocking` still counts what was found.
    - **`GAAL_LOGIN` is the PR author.** Post `COMMENT`, with the verdict as the first line (`no-self-verdict`). When the verdict is approve, `approval_withheld` is `author`.
    - **`GAAL_LOGIN` set and not the author.**
      - A request-changes verdict posts `REQUEST_CHANGES`, whatever the identity.
      - An approve verdict posts `APPROVE` only when `GAAL_LOGIN` is the separate review identity, `116-labs-gaal-review[bot]` in any spelling. Otherwise post `COMMENT`, with `approval_withheld: identity` (`identity-withholds`).
    - When more than one reason applies, use the first in this order: `author`, `identity`, `pushed`.
    - When approve is downgraded to comment, the review says so, and says that the PR is otherwise clean.
    - Never approve through another identity, and never retry a refused approval under a different identity (`second-identity-approval`).

### Auto-fix step

30. Skip this step. The profile sets `review.identity.reviewer: separate`, so this run commits nothing and pushes nothing.
    - Every fix goes to the author as a finding, and its disposition is **thread**.
    - The "Fixed in" list is empty (`fixed-not-flagged`).
    - No collapse runs, so `collapse-before-approve`, `collapse-remote-contained`, `collapse-content-preserved` and `collapse-keeps-link` hold trivially.
    - Nothing is staged (`explicit-staging`), nothing touches the base branch (`base-untouched`), and `push-failure-states` never arises.
    - Never push to, or rewrite, a fork's branch or commits that someone else authored (`rewrite-foreign-branch`).
    - Never propose a behaviour change as a one-click suggestion block (`behavioral-suggestion`). Behaviour changes go to the author as findings. A suggestion block may carry only a non-behavioural nit or a non-behavioural fix.

### Filing step

31. File the follow-ups before posting, so the review body can link each one by its number. Only a Pre-existing finding that meets the follow-up bar is filed. A Blocking finding, Secondary finding or contradiction never is.
    - **In preview,** file nothing. The review body marks each such finding as `would file`.
    - **Otherwise,** first look for an issue already filed for the finding:
      `gh issue list --repo 116-Labs/cuecal --state all --search "\"gaal:follow-up pr=<n>\" in:body" --json number,title,body --limit 100`
      - A listing that returns a full 100 is truncated: end `failed` (`complete-listings`).
      - A search that fails ends `failed` (`fail-closed-reads`).
      - When a listed issue carries the same finding, its number is the disposition. File nothing new.
    - **When no issue carries it,** write the body with the file tool to `<run-dir>/scratch/follow-up-<k>.md`. The body:
      - names the defect, the reproduction and the files
      - links this PR
      - carries the marker line `<!-- gaal:follow-up pr=<n> -->`
      - carries no attribution

      Then create the issue:
      `gh issue create --repo 116-Labs/cuecal --title "<title>" --body-file <run-dir>/scratch/follow-up-<k>.md`
    - **When the create errors,** do not retry it, since a retry could file the issue twice. Run the same search once more:
      - If it now lists an issue for the finding, that issue was filed anyway and is the disposition.
      - Otherwise the filing failed. Record the finding in the review body, and name the failed filing in the report.

### Anchor step

32. List this PR's review threads with GraphQL. Write `<run-dir>/scratch/threads.graphql` with the file tool. It is a query that:
    - takes the variables `owner`, `name`, `number` and `endCursor`
    - reads `repository.pullRequest.reviewThreads(first: 100, after: endCursor)`, with `pageInfo { hasNextPage endCursor }`
    - reads, for each thread: `id`, `isResolved`, `isOutdated`, `path`, `resolvedBy { login }`, and `comments(first: 1) { nodes { body url pullRequestReview { databaseId } } }`

    Then run:
    `gh api graphql --paginate -F query=@<run-dir>/scratch/threads.graphql --raw-field owner=116-Labs --raw-field name=cuecal -F number=<n>`

    Paginate to the end (`complete-listings`). A failed read ends `failed` (`fail-closed-reads`).
33. Match findings to existing threads. When an earlier review's thread is still unresolved (`isResolved` false) and carries the same finding, that thread is the finding's disposition. Open no second thread, and do not post your view as a reply on it: a view on another reviewer's open thread goes in the review body.
34. Every other finding whose disposition is **thread** takes a **new** thread. Compute its anchor from the right-hand side of the patch hunks of `<head>`; that is the post-push patch, since nothing was pushed. The anchor is a `path`, a `line` and `side: RIGHT`.
    - **Round 1** opens new threads for every Blocking finding, Secondary finding and contradiction that no earlier unresolved thread carries. A nit may also open a thread on round 1, and it carries no disposition.
    - **From round 2 on,** threads open only for Blocking findings, Secondary findings and contradictions, never for a nit that is not a contradiction (`rereview-converges`). Such a nit stays in the body, or is omitted when it sits on lines an earlier round already read. A Secondary finding is never omitted, even one first seen on lines an earlier round read.
    - When a finding has no changed line of its own, anchor it on the changed line closest to what it concerns, or else on the first changed line of the PR. Examples are an unverified criterion, a workflow construct the PR's CI could not run, and a finding about the description.
    - Questions go in the review body.

### Posting step

35. Re-read the remote head with:
    `gh pr view <n> --repo 116-Labs/cuecal --json headRefOid --jq .headRefOid`

    If it differs from `<head>`, the author pushed during the review. Still review `<head>`, and say in the report that the author's push moved the diff.
36. Compose the review body with the file tool at `<run-dir>/scratch/review.md`, in this order:
    1. **The verdict first,** with the rule applied. When the event is downgraded to comment, say why, and that the PR is otherwise clean if it is.
    2. **Findings by bucket:** Blocking, Secondary, Nits, Pre-existing.
       - Each finding with a new thread is listed in its bucket and also carried as an inline or file-level thread.
       - A finding that an earlier unresolved thread carries is listed in its bucket, never threaded again.
    3. **Acceptance criteria:** each one `verified`, `failed`, `unverified` or `deferred`. Never show a deferred criterion as met.
    4. **Tests:** each new or changed test, and whether it ran in the gates. Each behavioural change that has no test. A statement that "fails without the change" was reasoned from the code, not run on the base.
    5. **Fixed in:** none, because this run pushes nothing.
    6. **Dispositions:** each entry has exactly one disposition.
       - Each Blocking finding, Secondary finding and contradiction is `thread`. For one carried by an earlier thread, give the `url` of that thread's first comment.
       - Each filed Pre-existing finding is `filed #<number>`, or `would file` in preview.
       - Each Pre-existing finding below the bar, or whose filing failed, is `recorded`.
    7. **On a re-review:** the earlier threads the delta answered, and any whole-diff fallback.
    8. **The head line:** `Reviewed head: <head>`, with the full sha. `review.sign_off` is not set, so no sign-off line comes before it.
    9. **Last, on a line of its own:** exactly `gaal review-pr · run <run-id>`, with this run's id (`signed-review`). Never reword it: a signature reworded from run to run hid verdicts from a reader that matched one form.
37. **In preview,** post nothing. Keep `<run-dir>/scratch/review.md`, carry the would-be verdict into the run result, and skip to the cleanup step.
38. Before any posting call, look for a pending review that this account already has on the PR. GitHub allows one pending review per account per PR.
    `gh api repos/116-Labs/cuecal/pulls/<n>/reviews --paginate --jq '.[] | select(.state == "PENDING") | {node_id, body: (.body // "")}'`
    - **Its body carries `<!-- gaal:review-pr pending -->`:** a run that stopped mid-post left it. Delete it by writing `<run-dir>/scratch/delete.graphql` (a `deletePullRequestReview` mutation taking `pullRequestReviewId`) and running:
      `gh api graphql -F query=@<run-dir>/scratch/delete.graphql --raw-field id=<node-id>`
    - **Any other pending review** is a person's draft. Post nothing, never delete it, and end `failed` naming it.
39. Create the review as pending.
    1. Write `<run-dir>/scratch/pending.json` with the file tool. It holds:
       - `commit_id`: `<head>`
       - `body`: only the line `<!-- gaal:review-pr pending -->`. Never put the review body, the `Reviewed head` line or the signature here: nothing may read a pending review as a posted verdict.
       - `comments`: one per new inline thread, each with `path`, `line`, `side` `RIGHT` and `body`
       - no `event`
    2. Run:
       `gh api -X POST repos/116-Labs/cuecal/pulls/<n>/reviews --input <run-dir>/scratch/pending.json`
       Keep the answer's `id` as `<review-id>` and its `node_id` as `<node-id>`.
    3. If GitHub refuses an inline anchor, nothing was created. Re-fetch the patch with `gh api repos/116-Labs/cuecal/pulls/<n>/files --paginate`, re-anchor, and try once more.
    4. If GitHub refuses again, each finding whose anchor it refused becomes a file-level thread. When GitHub does not say which anchor it refused, every finding with a new thread does. The file-level thread goes on the file the finding concerns, or else on the PR's first changed file. Create the pending review with the remaining line comments only, and record the line-anchor fallback for the report.
40. Add each file-level thread to the pending review. The review endpoint takes no file-level comment.
    1. Write `<run-dir>/scratch/add-thread.graphql`: an `addPullRequestReviewThread` mutation taking `pullRequestReviewId`, `path` and `body`, with `subjectType: FILE` and no line.
    2. Write each thread's body to `<run-dir>/scratch/thread-<k>.md`.
    3. Run:
       `gh api graphql -F query=@<run-dir>/scratch/add-thread.graphql --raw-field reviewId=<node-id> --raw-field path=<path> --raw-field body=@<run-dir>/scratch/thread-<k>.md`
       Use the pending review's `node_id`, never its numeric `id`.

    Never use the single-comment endpoint (`pulls/<n>/comments`): it posts each comment as a separate review.
41. Submit the review. Write `<run-dir>/scratch/submit.graphql`: a `submitPullRequestReview` mutation taking `pullRequestReviewId`, `event` and `body`, and returning `pullRequestReview { databaseId }`. Then run:
    `gh api graphql -F query=@<run-dir>/scratch/submit.graphql --raw-field id=<node-id> --raw-field event=<event> --raw-field body=@<run-dir>/scratch/review.md`

    The full review body replaces the pending line.
42. If GitHub refuses a file-level thread, or the submit fails:
    1. Delete the pending review with the delete command in step 38, using the same `node_id`, so nothing is posted.
    2. End `failed`, naming the refused anchor or the failed submit.

    A review that cannot open a finding's thread is never posted (`finding-disposed`), since a review body alone would let the PR merge past the finding.

### Thread listing

43. Skip this step in preview. Otherwise:
    1. Take the posted review's id: `<review-id>`, or the `databaseId` the submit returned.
    2. **If that id is empty,** stop. End `needs-human` with a `reason`. Never fall back to matching by login: that would take in threads that another run, or the same account, opened.
    3. List the threads again with the anchor step's command. Keep only the threads whose first comment's `pullRequestReview.databaseId` equals that id (`resolve-own-threads-only`).
44. Never resolve a thread that carries a finding's **thread** disposition: a Blocking finding, a Secondary finding or a contradiction. It stays open for the author and revise-pr (`finding-disposed`).
    - Never resolve a thread to clear the merge path (`resolve-to-unblock`).
    - Leave open questions, blockers, suggestion blocks and contradiction threads.
    - Some threads wait for a person: an unverified criterion, or a construct the PR's CI cannot run. No review resolves them.
45. Reply to, then resolve, only a thread this review opened for a nit and disposed of itself: a nit recorded only, or an agreed trade-off.
    1. Write `<run-dir>/scratch/reply.graphql` (an `addPullRequestReviewThreadReply` mutation taking `pullRequestReviewThreadId` and `body`) and `<run-dir>/scratch/resolve.graphql` (a `resolveReviewThread` mutation taking `threadId`).
    2. Reply:
       `gh api graphql -F query=@<run-dir>/scratch/reply.graphql --raw-field thread=<node-id> --raw-field body=@<run-dir>/scratch/reply-<k>.md`
    3. Resolve:
       `gh api graphql -F query=@<run-dir>/scratch/resolve.graphql --raw-field thread=<node-id>`

    Nothing is filed here: the filing step already filed every follow-up.

    A reply or resolve that fails after the review is posted is reported, and the run ends `needs-human`. Never retry it, since a retry could post a second review.
46. Report the open threads, split into two groups: suggestions, and threads the author owes.

### Cleanup

47. Restore the checkout's starting point:
    - If it was on a branch: `git checkout <original-branch>`.
    - Otherwise: `git checkout --detach <original-sha>`.

    Leave the scratch files in `<run-dir>/scratch`.

### Write the run result (always last, on every exit path)

48. Read `finished_at` with `date -u +%Y-%m-%dT%H:%M:%SZ`.
49. Pick the exit state:
    - **`done`:** no Blocking finding stands, the review was posted (or composed, in preview), and no finding has a **thread** disposition the author owes. A clean review whose approve was posted as comment for identity still ends `done`, with `review.approval_withheld` set.
    - **`needs-human`:** any of these holds:
      - a Blocking finding stands
      - a finding with a **thread** disposition is left for the author, whether or not identity downgraded the verdict to comment
      - the posted review's id was empty
      - a thread reply or resolve failed after posting
    - **`needs-clarification`:** any of these holds, and `questions` say what is missing:
      - no PR could be determined
      - the PR links no issue (a number that names no issue counts as none, and `questions` name it)
      - a linked issue has no checkable acceptance criteria
    - **`failed`:** any of these holds:
      - the PR is not open, or GitHub cannot find it (404)
      - the head could not be verified for reasons outside the PR
      - the checkout was dirty
      - a read failed or a listing was truncated
      - a person's pending review stands
      - posting failed even after the file-level fallback (nothing was posted)
50. Write `<run-dir>/result.json.tmp` with the file tool, then run `mv <run-dir>/result.json.tmp <run-dir>/result.json`. Never leave the `.tmp` file behind (`run-result-written`). The JSON holds:
    - `schema_version`: `1`
    - `run_id`: the run id from the run context
    - `blueprint`: `"review-pr"`
    - `blueprint_version`: `"1.9.0"`
    - `repo`: `"116-Labs/cuecal"`
    - `issue`: the issue picked in step 11, or `null`
    - `pr`: `<n>`, or `null` when none was determined
    - `status`: the exit state
    - `reason`: required unless the status is `done`. One sentence of at most 160 characters, naming the step, decision or action needed.
    - `questions`: a non-empty list when the status is `needs-clarification`
    - `attempts`: `1`
    - `gates`: the gate runs on `<head>` in the order they ran, each with `name`, `command`, `exit_code` and `duration_ms` (`gates-final-tree`). A gate that did not run is absent (`truthful-report`). A `done` result never lists a non-zero exit.
    - `branch`: the PR's `headRefName`, or `null`
    - `commit_sha`: `null`, because nothing was pushed. Omit `push`.
    - `review`: required for `done`, and included whenever a verdict was reached. It holds:
      - `verdict`: `approve`, `request-changes` or `comment`, as actually posted (or as would be posted, in preview)
      - `blocking`: the number of Blocking findings
      - `non_blocking`: every other finding
      - `head`: `<head>`, the full sha on the `Reviewed head` line
      - `criteria`: every linked issue's criteria in order, each `{"text": "#<issue>: <criterion>", "status": "<status>"}`. Report every criterion, with `head`, on every round, a re-review included: Gaal posts these criteria when the rounds run out.
      - `approval_withheld`: `author` or `identity`, when approve was posted as comment
    - `started_at` and `finished_at`

    Fields outside the schema are not allowed.
51. Final report. It covers:
    - the acceptance-criteria results and the description-accuracy note
    - the thread ledger: open threads split into suggestions and author-owed
    - the inline and body-only finding counts, with the reason for each body-only one. Only a nit, a recorded Pre-existing finding, or a filed finding listed with its link may be body-only.
    - the follow-up issues filed, and any failed filing
    - any line-anchor fallback
    - whose push moved the diff
    - any start-signal failure
    - the push and collapse outcome: none, the branch is unchanged at `<head>`

    The report describes only what actually happened (`truthful-report`).

## Invariants

- `description-last`: The description is read only after the correctness pass, the gates and the tests check have produced findings.
- `verdict-follows-findings`: Request changes if there is at least one Blocking finding. Approve if there are none. Comment when undecidable. The review states the rule it applied.
- `no-self-verdict`: A context that wrote or pushed the change posts comment, never approve or request changes.
- `identity-withholds`: A run that is not the separate review identity posts comment where approve is called for. A run without `GAAL_LOGIN` always posts comment, with the verdict as the first line.
- `findings-verified`: Every posted finding was reproduced at its line on the reviewed head.
- `tests-named`: Every behavioural change names its covering test, or is a finding. The Tests section lists each new or changed test and whether it ran.
- `signed-review`: The body carries `Reviewed head: <sha>` and ends with `gaal review-pr · run <run-id>` on its own line.
- `fixed-not-flagged`: A pushed fix appears only in "Fixed in". This run pushes none.
- `resolve-own-threads-only`: Only threads this review opened, matched by review id and never by login, are resolved, each after a reply.
- `collapse-before-approve`: Any collapse happens before anchors and posting. No collapse runs here.
- `contradiction-fixed-or-threaded`: A contradiction is fixed or carried by a thread, never body-only and never filed.
- `rereview-converges`: After round 1, new threads open only for Blocking findings, Secondary findings and contradictions, never for one an earlier unresolved thread carries. The review names the earlier threads the delta answered.
- `finding-disposed`: Every Blocking finding, Secondary finding and contradiction ends with exactly one disposition before posting. A qualifying Pre-existing finding is filed. A review that cannot open a finding's thread is not posted.
- `explicit-staging`: Stage only manifest paths this run wrote. This run stages nothing.
- `base-untouched`: Never commit or push to the base.
- `fail-closed-reads`: A failed read stops the run. It is never treated as "nothing".
- `complete-listings`: Every listing is paginated to the end, or the run ends `failed`.
- `truthful-report`: The report and result state only what happened.
- `status-preserved`: No failure is lost to a filter or a guard.
- `attribution-policy`: Attribution is `none`. Nothing is added to any body.
- `run-result-written`: `result.json` is written atomically on every exit path.
- `gates-final-tree`: `gates` lists only the runs on the final reviewed tree.
- `install-before-gates`: The profile names no install, so nothing is installed and the gates run in the checkout.
- `push-failure-states`: Not triggered, since nothing is pushed. A failed push would abandon the fix and the review would go on.
- `collapse-remote-contained`, `collapse-content-preserved`, `collapse-keeps-link`: These hold trivially, because no collapse runs.

## Forbidden actions

- `description-sets-scope`: Letting the description limit what is reviewed.
- `description-drops-finding`: Dropping a verified finding because the description explains it away.
- `second-identity-approval`: Approving through another identity, or retrying a refused approval under one.
- `rewrite-foreign-branch`: Pushing to, or rewriting, a fork's branch or another author's commits.
- `resolve-to-unblock`: Resolving threads to clear the merge path.
- `behavioral-suggestion`: Proposing a behaviour change as a one-click suggestion block.
- `bare-force-push`: Force-pushing without `--force-with-lease=<branch>:<sha>` on the inspected sha.
- `admin-bypass`: Using `--admin` or any admin route around protection.
- `bypass-hook`: Skipping or redirecting verification, or editing hooks or `.git/config`.
- `machine-specific-paths`: Hard-coding personal paths, scripts or services.
- `commit-foreign-edits`: Committing changes this run did not make.

## Exit states

- `done`: No Blocking finding stands, and the review was posted with no author-owed thread. When approve was posted as comment, `review.approval_withheld` is set.
- `needs-human`: A Blocking finding stands, or threads are left for the author. It also applies when the posted review's id was empty, or when a reply or resolve failed after posting.
- `needs-clarification`: No PR could be determined, or no issue is linked, or a linked issue has no checkable criteria. `questions` say what is missing.
- `failed`: Any of these, with `reason` naming the step:
  - the PR is not open, or returns a 404
  - the head was unverifiable for reasons outside the PR
  - the checkout was dirty
  - a read failed or a listing was truncated
  - a person's pending review exists
  - posting failed after the fallbacks (nothing was posted)
