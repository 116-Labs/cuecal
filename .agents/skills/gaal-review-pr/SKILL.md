---
name: gaal-review-pr
description: >-
  Adversarially reviews one open pull request in 116-Labs/cuecal. It grades the PR against the
  acceptance criteria of its linked GitHub issues, read fresh at review time, and against the
  profile gates (uv run ruff check . and uv run pytest), reading the PR description last as a set
  of claims to test. It posts exactly one signed review whose verdict follows from the verified
  findings, leaves open only the threads the author owes, and writes the run result to
  result.json in the run directory. Use it when a dispatch hands over a repo and PR number (post
  or preview mode) and asks for the review-pr step. In this repository the review runs as the
  separate review identity, so it never pushes fixes and every fix goes to the author as a
  finding. Do not use it to implement an issue (gaal-implement), open a PR (gaal-open-pr), revise
  a PR after review (gaal-revise-pr), merge or deploy. When no PR can be determined, do not guess
  and end as needs-clarification.
---
<!-- gaal-stamp blueprint=review-pr@1.8.0 shared=1.5.0 profile=833de6ae33df6d68 generated=2026-10-08 core=319c2f7f2c7e0f3d forbidden=54c30c1c66633c73 content=5b53a311953de9bc -->

# gaal-review-pr

Review an open PR in `116-Labs/cuecal` the way a careful maintainer would. Judge it against the linked issues' acceptance criteria and the project's gates, independently of how the PR describes itself. Post exactly one review, with a verdict that follows from the findings. This skill implements blueprint `review-pr` version `1.8.0`.

Steps refer to each other by name: the *re-review step* (step 5), the *criteria walk* (step 10), the *sort step* (step 11), the *auto-fix step* (step 13), the *posting step* (step 15), the *thread listing* (step 16) and the *result step* (step 17).

## Project facts this skill relies on

- **Repository:** `116-Labs/cuecal`, private, default branch `main`. The tracker is GitHub issues in this repository.
- **Gates.** Both are required. Run them exactly as written:
  - `lint`: `uv run ruff check .`
  - `test`: `uv run pytest`
- **Preflight:** none. **Advisory checks:** none. **Install commands:** none.
  - Nothing is installed (`install-before-gates`). The gates run in this checkout, which already has its environment.
  - A throwaway worktree has no environment, so this skill never runs a gate in one.
- **Commits:** one commit per PR (`single_commit: true`), Conventional Commits, attribution `none`.
  - This skill makes no commits.
  - Review bodies, replies and follow-up issues carry no AI attribution. The required `Reviewed head:` and signature lines are not attribution.
- **Branches:** gaal branches use the prefix `gaal/`. The prefix never decides who owns a branch.
- **Merge:** method `squash`, `message_source: commits`, no merge queue (`queue: false`), no auto-merge. This skill never merges.
- **Stacking:** the profile names no stacking tool. The base is the PR's own base branch: `main`, or an open parent branch.
- **Review policy and branch protection:**
  - `required_approvals: 1`.
  - `threads_block_merge: false`. Open threads do not block merge, so a thread is never resolved to clear the merge path (`resolve-to-unblock`).
  - No extra required reviewers.
  - The start signal is a reaction.
  - No `sign_off` line is set.
  - Identity is `reviewer: separate`, with login `116-labs-gaal-review[bot]`. The push identity is `116-labs-gaal-push[bot]`.
- **Limits:**
  - `implement_attempts: 3`
  - `revise_rounds: 3`
  - `review_rounds: 2`

  Gaal enforces these limits between runs. This skill counts its own round (earlier signed reviews + 1) for the re-review rules and the report.
  - Gaal starts revise-pr only while a review round is left for the push revise-pr will make.
  - Once the rounds are spent, Gaal stops on a head that a review covers and posts the `criteria` that review reported.
  - So every round, a re-review included, reports every criterion together with `head`.

## Run context and command rules

- **Placeholders:**
  - `<run-dir>` in every command stands for the literal path of the run directory, taken from the run context (`GAAL_RUN_DIR`).
  - `<run-id>` is the literal value of `GAAL_RUN_ID`.
  - Never write either variable name inside a command.
  - Other placeholders (`<n>`, `<head>`, `<base>`, `<sha>`) are replaced by literal values.
- **The run's login.** `GAAL_LOGIN` comes from the run context and names the account this run acts as.
  - Never read it from GitHub: `gh api user` answers 403 to an App token.
  - GitHub spells an App login three ways: `<slug>[bot]` (REST), `<slug>` (GraphQL) and `app/<slug>` (`gh --json`). Compare logins in all three spellings.
  - The run **is the separate review identity** when `GAAL_LOGIN` matches `116-labs-gaal-review[bot]` in any of those spellings.
- **Command form:**
  - Run one command per call. Never chain commands with `&&`, `;` or `|`. A `|` inside a quoted jq filter is part of the filter, not a chain.
  - Never use `$VAR`, `${VAR}`, `$(…)`, backticks or a `NAME=value` prefix.
  - Paths are literal and lie inside this checkout or `<run-dir>`.
  - Quote every glob.
- **Files:** write every review body, review payload, reply, issue body and GraphQL query with the file-writing tool under `<run-dir>/scratch/`. Pass each one by path: `--body-file <file>`, `-F body=@<file>`, `-F query=@<file>` or `--input <file>`. Never use shell redirection.
- **Time:** read it with `date -u +%Y-%m-%dT%H:%M:%SZ`. Time each gate with `date -u +%s` just before and just after it, as separate commands. `duration_ms` is the difference times 1000.
- **Listings** (`complete-listings`): every listing of reviews, comments, threads, commits, files or CI runs is paginated to the end. A listing that cannot be read completely ends `failed`, naming the listing.
- **Failed reads** (`fail-closed-reads`): a failed read is a failure, never "nothing there". An error, auth expiry or rate limit ends `failed`, naming the read, unless a step names another outcome.
- **Exit statuses** (`status-preserved`): a command's exit status is never hidden by a filter or a guard. Every failed gate, read or write is seen and handled.
- **Verification** (`bypass-hook`, `admin-bypass`): verification is never skipped or redirected.
  - Never use `--no-verify`, `git commit -n`, `--no-gpg-sign`, a hooks-path override or `gh pr merge --admin`.
  - Never edit, move or restore hook files or `.git/config`.
  - If the hooks directory is needed, find it with `git rev-parse --git-path hooks`.

## Steps

### 0. Start

1. Run `date -u +%Y-%m-%dT%H:%M:%SZ` and keep the output as `started_at`.
2. Run `mkdir -p <run-dir>/scratch`.
3. Decide the mode from the dispatch: **post** (the default) or **preview**. Preview posts nothing, reacts to nothing, pushes nothing and resolves nothing.
4. Take the PR number `<n>` from the dispatch. If no PR can be determined, do not guess: go to the result step with `needs-clarification` and a question asking which PR to review.

From here on, every exit goes through the result step. Once the checkout has been switched, every exit also goes through the restore in step 4.

### 1. Read PR metadata, but not the description (`description-last`)

1. Run:

   ```
   gh pr view <n> --repo 116-Labs/cuecal --json number,state,baseRefName,headRefName,headRefOid,author,isCrossRepository,headRepositoryOwner,changedFiles,closingIssuesReferences
   ```

   Never request `body` here.
   - If GitHub cannot find the PR (a 404, or "Could not resolve to a PullRequest"), end `failed`, naming the PR number.
   - Any other failure ends `failed`, naming this read.
   - A `state` other than `OPEN` ends `failed` with the reason "PR is not open".
2. Record:
   - `<base>`;
   - the head branch (the result's `branch`);
   - the PR author;
   - whether the PR is cross-repository.
3. List the files:

   ```
   gh api repos/116-Labs/cuecal/pulls/<n>/files --paginate --jq '.[].filename'
   ```

   The count must equal `changedFiles`. If it does not, end `failed` (`complete-listings`).
4. List the commits:

   ```
   gh api repos/116-Labs/cuecal/pulls/<n>/commits --paginate --jq '.[] | {sha, author: .author.login, email: .commit.author.email}'
   ```

### 2. Collect the linked issues and their acceptance criteria

Apply the shared issue-link rule. A PR's issues are the union of three sources, all read every time:

- every number GitHub reports in `closingIssuesReferences`;
- every link in the body;
- every link in each commit message.

Never read the body's links only when GitHub reports none.

1. Extract the body's links without reading its text into context, using exactly this filter:

   ```
   gh api repos/116-Labs/cuecal/pulls/<n> --jq '[(.body // "") | scan("(?im)^[ \\t]*(close|closes|closed|fix|fixes|fixed|resolve|resolves|resolved|refs)[ \\t]*:?[ \\t]*#([0-9]+)")]'
   ```

2. Extract the links from every commit message the same way:

   ```
   gh api repos/116-Labs/cuecal/pulls/<n>/commits --paginate --jq '.[] | [(.commit.message // "") | scan("(?im)^[ \\t]*(close|closes|closed|fix|fixes|fixed|resolve|resolves|resolved|refs)[ \\t]*:?[ \\t]*#([0-9]+)")]'
   ```

   Keep both regex flags. `i` matches any case. `m` makes `^` match at the start of every line, so a `Refs #N` below the summary is found.
3. Note whether each link is **closing** or **plain**. It is closing when GitHub reports it or a closing keyword introduces it. It is plain when it is a `refs` line.
4. Check each number by its HTTP status, never by the wording of an error:

   ```
   gh api repos/116-Labs/cuecal/issues/<number> --include --jq .pull_request
   ```

   - **404:** the number names nothing. It is no link.
   - **200 with non-empty output:** the number is a pull request. It is no link. An issue prints an empty line, because its `pull_request` field is null.
   - **Any other failure:** end `failed`, naming the read (`fail-closed-reads`).
5. If no real issue link remains, end `needs-clarification`. Its `questions` name every number that turned out not to be an issue, and ask which issue the PR implements.
6. Pick one issue for the result's `issue` field. An issue named in the dispatch wins. Otherwise, take the first of:
   1. a closing issue GitHub reports;
   2. a closing-keyword line in the body, then one in a commit message;
   3. a `Refs` line in the body, then one in a commit message.
7. Read each linked issue fresh, as it stands now, never from a copy made when the PR opened. A maintainer may have added a criterion by editing the issue while the PR was open.
   - `gh issue view <number> --repo 116-Labs/cuecal --json number,title,body,state`
   - `gh api repos/116-Labs/cuecal/issues/<number>/comments --paginate`
8. Write down every acceptance criterion of every linked issue, in order. A PR that links several issues is judged against all of them.
   - Grade against the issue as its author wrote it, with the author's and maintainers' own edits and comments. Comments that clarify or narrow scope are part of the spec.
   - A criterion added or changed by an edit since the PR opened is graded like the rest.
   - Text between a `<!-- gaal:plan-drift -->` line and its `<!-- /gaal:plan-drift -->` line, and any comment carrying the opening marker, is the implementer's account of how its plan changed. Treat it as a claim to check, never as spec.
   - Everything else in the body is the author's spec, including maintainer text added after a plan-drift section.
9. If a linked issue has no checkable acceptance criteria, end `needs-clarification`, with `questions` saying what is missing.

### 3. Post the start signal (post mode only)

1. React with eyes:

   ```
   gh api repos/116-Labs/cuecal/issues/<n>/reactions --method POST -f content=eyes
   ```

2. If the reaction fails, note it in the report and carry on. The exceptions are auth expiry and a rate limit: they end `failed` (`fail-closed-reads`).

### 4. Check out the head as fetched from the remote

1. Fetch in this order:
   1. `git fetch origin <base>`
   2. `git fetch origin pull/<n>/head`
   3. Immediately after the head fetch, before any other fetch, run `git rev-parse FETCH_HEAD`.

   That full sha is `<head>`. `FETCH_HEAD` holds only the last fetch, so a read made after the base fetch would name the base tip instead.
2. Run `git status --porcelain=v1 --untracked-files=all`. If it lists any path, the gates cannot run on a clean `<head>`, and nobody's edits are discarded. End `failed` with the reason "checkout has uncommitted changes; cannot verify the head".
3. Record where to come back to:
   - `git rev-parse --abbrev-ref HEAD` gives `<orig-branch>`.
   - `git rev-parse HEAD` gives `<orig-sha>`.
4. Run `git checkout --detach <head>`.
5. Run `git merge-base <head> origin/<base>` to get `<merge-base>`.
6. On every exit path from here on, come back before writing the result:
   - `git checkout <orig-branch>`, or
   - `git checkout --detach <orig-sha>` when `<orig-branch>` was `HEAD`.
7. No install runs, because the profile names no `install` commands (`install-before-gates`). If a gate in step 7 fails because uv cannot prepare the environment, decide whose fault it is:
   - **The PR changes `pyproject.toml` or `uv.lock`:** the PR broke the environment. That is a Blocking finding naming the gate, and the review says that whatever the gates would have shown is unverified.
   - **Otherwise:** the reviewer cannot verify the head for reasons outside the PR. End `failed`, naming the gate command, and post no review.

### 5. Re-review: limit attention to the delta (re-review step)

1. Find this skill's earlier reviews by their signature line, never by the author's login:

   ```
   gh api repos/116-Labs/cuecal/pulls/<n>/reviews --paginate --jq '.[] | select((.body // "") | contains("gaal review-pr · run ")) | {id, head: ((.body | capture("Reviewed head: (?<sha>[0-9a-f]{40})").sha) // "none")}'
   ```

   The output is oldest first.
2. No match means round 1. Otherwise:
   - the round is the number of matches + 1;
   - the last match is the last review, and its `head` is `<old-head>`;
   - keep every matched review id, so step 16 can find that review's threads.
3. If `<old-head>` is `none`, review the whole diff.
4. Otherwise:
   1. Fetch `<old-head>` if it is not local: `git fetch origin <old-head>`.
   2. Run `git merge-base <old-head> origin/<base>` to get `<old-merge-base>`. That is where `<old-head>` left its base. It is never the current head's merge base.
   3. Check whether history was rewritten: `git merge-base --is-ancestor <old-head> <head>`.
      - If it exits non-zero, history was rewritten. Run:

        ```
        git range-diff <old-merge-base>..<old-head> <merge-base>..<head>
        ```

      - If it exits zero, run `git diff <old-head> <head>`.
5. If `<old-head>` cannot be fetched, review the whole diff, and say so in the review.
6. The correctness pass may focus on the delta. The criteria walk still covers every criterion.

### 6. Correctness pass

1. Read `git diff <merge-base> <head>` and each changed file (`cat <path>`). Look for:
   - logic errors;
   - edge cases;
   - error handling;
   - concurrency;
   - security.
2. Scripts, workflows and skill files count as code. Check them for:
   - flags that do not exist;
   - word-splitting and quoting;
   - flags that are documented but not implemented;
   - injection through untrusted input;
   - re-runs that are not idempotent;
   - swallowed errors;
   - success inside loops that is never verified.
3. Pre-existing defects never open threads. A PR that makes a defect reachable owns that defect.

### 7. Run the gates on `<head>` (`gates-final-tree`)

1. Run the `lint` gate in this checkout, at `<head>`, as three separate commands:
   1. `date -u +%s`
   2. `uv run ruff check .`
   3. `date -u +%s`
2. Run the `test` gate the same way:
   1. `date -u +%s`
   2. `uv run pytest`
   3. `date -u +%s`
3. Record each run's `name`, `command`, `exit_code` and `duration_ms`.
4. Both gates are required. A gate that exits non-zero on the head is a Blocking finding naming the gate, so the review cannot end `done`.
5. There are no preflight or advisory checks to run.

### 8. Check the tests (`tests-named`)

1. For each behavioural change in the diff, name the test that covers it:
   - a new or changed test that fails without the change, or
   - an existing test that already exercises it.
2. A behavioural change with no covering test is a finding. It is Blocking when the linked issue's criteria ask for tests, and Secondary otherwise.
3. For each new or changed test, note whether it ran in this run's `uv run pytest`, judged from that run's output.
4. Do not try to show on the base that a test fails without the change. A throwaway worktree has no environment and the profile names no install, so no allowed command can run it there. The Tests section says that "fails without the change" was reasoned from the code, not run on the base.
5. A test that would also pass on the base proves nothing about the change. A test the gates never ran proves nothing about the head.

### 9. Only now, read the description (`description-last`)

The order is the defense: a description read first becomes the map, and the author's blind spots become the reviewer's.

1. Read the description:

   ```
   gh pr view <n> --repo 116-Labs/cuecal --json body --jq .body
   ```

2. Treat it as a set of claims to test.
   - It can add findings. It never removes a verified one (`description-drops-finding`).
   - It never limits what is reviewed (`description-sets-scope`). That includes any focus section.
3. Note its **Deferred** list, if any, and every ticked test-plan box.
4. Write a short description-accuracy note for the report.

### 10. Verify findings and walk the criteria (criteria walk, `findings-verified`)

1. Re-check every candidate finding at its exact file and line on `<head>`. Drop anything that does not reproduce.
2. Walk every acceptance criterion of every linked issue, one by one, on `<head>`. On a re-review, walk every criterion again, not only the ones the delta touches. Give each criterion one status:
   - **`verified`**: met, and shown by a gate, a test or a check this run ran;
   - **`failed`**: not met;
   - **`unverified`**: could not be confirmed on this head. Say what a person must check.
   - **`deferred`**: only when the link is plain (`Refs`) and the Deferred list names this criterion.
3. A Deferred entry that is not one of the issue's criteria is a Secondary finding.
4. Deferral moves the named criteria out of this PR's bar, but they are still checked and listed. It never drops a correctness, gate or other finding, and it changes nothing under a closing keyword.

### 11. Sort findings (sort step)

1. Sort each finding into **Blocking**, **Secondary**, **Nits** or **Pre-existing**:
   - A failed criterion is Blocking, unless it is deferred.
   - An unverified criterion is a Secondary finding.
   - A Deferred list under a closing keyword is Blocking, because merging would close the issue with criteria still open.
   - A ticked test-plan box for a gate that did not run on the head is Blocking. Compare each ticked box with this run's gates and with the CI result. Such a box claims evidence that does not exist.
2. Mark every **contradiction**: a finding on lines the PR adds that contradicts other code in the PR, such as a hint, message, doc, test or default that disagrees with the new behaviour.
   - Whatever its bucket, a contradiction ends as an inline thread, on round 1 and on a re-review alike. It is never left only as text in the review body (`contradiction-fixed-or-threaded`). revise-pr acts on threads, so a contradiction listed only in a body is lost at merge.
   - This review fixes nothing, so every contradiction becomes a thread.
3. Check live evidence first. Do this for each platform, CLI or API construct that the PR's workflow or script files add or change:
   1. Read the workflow with `cat .github/workflows/<file>`, including its `on:` block and every job and step `if:`.
   2. List the CI runs on the head:

      ```
      gh api repos/116-Labs/cuecal/actions/runs --method GET -f head_sha=<head> -f per_page=100 --paginate --jq '.workflow_runs[] | {id, name, path, event, status, conclusion}'
      ```

   3. Decide whether CI **could have run** the construct. It could when a `pull_request` run on this head would reach the step that holds the PR's version of it. That means:
      - the trigger's `branches` and `paths` filters (and their `-ignore` forms) match this PR's base and changed files; and
      - the job's and the step's `if:` are true for a `pull_request` event.

      A `pull_request_target` trigger never counts, because it runs the base branch's copy of the workflow.
   4. Classify the construct:
      - **CI ran it and the run passed:** not a finding.
      - **CI could have run it but did not, or the run failed:** Blocking. Its behaviour is unverified, and lint does not verify it.
      - **CI cannot run it** (it triggers only on `pull_request_target`, on a push to the base, a tag, a release or a schedule, or filters or `if:` skip it for this PR): Secondary, naming what a person must check.
   5. When the description says the construct was verified by a command, the finding says "the author states it was verified by `<command>`". If that command is `uv run ruff check .` or `uv run pytest`, cite this run's result for it. That statement never drops the finding.

### 12. Choose the verdict (`verdict-follows-findings`)

1. Choose the verdict from the findings:
   - At least one Blocking finding: **request changes**.
   - No Blocking finding: **approve**. Nits may remain.
   - Undecidable: **comment**.

   The review states the rule it applied.
2. Decide what will actually be posted. Apply the first case that matches:
   1. **`GAAL_LOGIN` is empty or absent.** The author check is unknown. Post **comment** whatever the verdict, with the verdict as its first line, never approve or request changes (`identity-withholds`). If the verdict was approve, set `approval_withheld: identity`.
   2. **`GAAL_LOGIN` equals the PR author** in any of its three spellings. Post **comment** with the verdict as its first line (`no-self-verdict`). If the verdict was approve, set `approval_withheld: author`.
   3. **Otherwise.** Request changes is posted as request changes. Approve is posted as approve only when this run is the separate review identity (`116-labs-gaal-review[bot]`). If it is not, post comment and set `approval_withheld: identity` (`identity-withholds`).
3. When approval is withheld, the review says why, and says the PR is otherwise clean.

### 13. Auto-fix: none in this repository (auto-fix step)

`review.identity.reviewer` is `separate`, so this run pushes nothing and commits nothing. A token review identity could push, but gaal refuses an approval from a review run that pushed. So in this repository:

- Every fix, however small, goes to the author as a finding.
- A small non-behavioural fix may be offered as a one-click suggestion block in its thread.
- A behavioural change is never a suggestion block. It is a finding (`behavioral-suggestion`).
- These all hold trivially, because nothing is pushed: `explicit-staging`, `commit-foreign-edits`, `base-untouched`, `rewrite-foreign-branch`, `bare-force-push`, `push-failure-states`, `collapse-before-approve` and the collapse invariants (`collapse-remote-contained`, `collapse-content-preserved`, `collapse-keeps-link`).
- The "Fixed in" list is empty (`fixed-not-flagged`).
- `commit_sha` is `null`.
- The report states "no push: separate review identity".

The collapse routine never runs. The squash merge (`message_source: commits`) takes its message from the author's commits as they stand.

### 14. Compute inline anchors

1. Take anchor lines from the right-hand side (`RIGHT`) of the patch hunks of `<head>`. Use the `patch` field from:

   ```
   gh api repos/116-Labs/cuecal/pulls/<n>/files --paginate
   ```

   No push happens, so `<head>` is the post-push head.
2. Decide which findings get threads:
   - **Round 1:** every Blocking finding, every contradiction, and the Secondary findings worth a thread.
   - **Round 2 and later** (`rereview-converges`): only Blocking findings and contradictions. Every other Secondary finding and nit stays in the review body.
3. Never open a thread for:
   - a question (it goes in the body);
   - a view on another reviewer's open thread (it goes in the body, never in a second thread);
   - a Pre-existing finding.

### 15. Post one review (posting step)

1. Re-read the remote head with `gh pr view <n> --repo 116-Labs/cuecal --json headRefOid`. If it differs from `<head>`, the author's push moved the diff during the review.
   - Still post the review against `<head>`.
   - Say in the review and the report that a newer head exists and was not reviewed.
2. Compose the body, in this order:
   1. The verdict, as the first line.
   2. The rule applied.
   3. The findings by bucket (Blocking, Secondary, Nits, Pre-existing). Each contradiction is listed in its bucket and also carried as an inline thread.
   4. The acceptance-criteria results, one line per criterion: verified, failed, unverified or deferred. A deferred criterion is never shown as met.
   5. A short **Tests** section listing:
      - each new or changed test, and whether it ran in the gates;
      - each behavioural change with no test;
      - that "fails without the change" was reasoned from the code.
   6. `Fixed in: none`, because this review pushes no fixes.
   7. On a re-review, which of this skill's own earlier threads the delta answered.
   8. When approval is withheld, the reason, and that the PR is otherwise clean.
   9. The line `Reviewed head: <head>` with the full 40-character sha. No `review.sign_off` line comes before it in this repository.
   10. Last, on a line of its own, exactly `gaal review-pr · run <run-id>` (`signed-review`). Never reword this signature. Variants once hid verdicts from a reader that matched one form.
3. **Preview mode.** Write the body with the file-writing tool to `<run-dir>/scratch/review.md`. Post nothing, carry the would-be posted verdict into the run result, and skip to the result step.
4. **Post mode.** Write `<run-dir>/scratch/review.json` with the file-writing tool. It holds:
   - `commit_id`: `<head>`;
   - `event`: `APPROVE`, `REQUEST_CHANGES` or `COMMENT`, per step 12;
   - `body`: the composed body;
   - `comments`: one entry per thread, each `{path, line, side: "RIGHT", body}`.

   Then post:

   ```
   gh api repos/116-Labs/cuecal/pulls/<n>/reviews --method POST --input <run-dir>/scratch/review.json --jq .id
   ```

   The output is `<review-id>`.
5. **An anchor is rejected** (HTTP 422 naming a line or position):
   1. Re-fetch the files listing, re-anchor, and post once more.
   2. If that also fails, move every inline finding into the body, with the reason, and post a body-only review.
   3. Report the fallback.
6. **Before posting again after any other failure**, list the reviews as in step 5 and look for the signature with this run's `<run-id>`. If one is there, it was posted: never post a second review.
7. **Posting still fails** after the body-only fallback: end `failed`, naming the posting step.
8. **An approval is refused:** never retry it under another identity (`second-identity-approval`). Post the same review as comment, with `approval_withheld: identity`.

### 16. List and dispose of this review's own threads (thread listing, `resolve-own-threads-only`)

1. If `<review-id>` is empty, stop. End `needs-human` with a reason. Never fall back to matching threads by reviewer login, because that would take in threads another run or the same account opened.
2. Write `<run-dir>/scratch/threads.graphql` with the file-writing tool:

   ```
   query($owner: String!, $name: String!, $number: Int!, $endCursor: String) {
     repository(owner: $owner, name: $name) {
       pullRequest(number: $number) {
         reviewThreads(first: 100, after: $endCursor) {
           pageInfo { hasNextPage endCursor }
           nodes {
             id isResolved path line
             comments(first: 1) { nodes { databaseId pullRequestReview { databaseId } } }
           }
         }
       }
     }
   }
   ```

3. Run:

   ```
   gh api graphql --paginate -F query=@<run-dir>/scratch/threads.graphql -f owner=116-Labs -f name=cuecal -F number=<n>
   ```

   Keep only the threads whose first comment's `pullRequestReview.databaseId` equals `<review-id>`. The same listing, filtered by the earlier review ids from step 5, gives the earlier threads the review named as answered.
4. Of this review's threads, reply to and then resolve only the ones this review disposed of itself:
   - recorded only;
   - an agreed trade-off;
   - filed as an issue under the follow-up bar.

   Leave these open: questions, blockers, suggestion blocks and contradiction threads. Never resolve a thread to clear the merge path (`resolve-to-unblock`).
5. **Follow-up bar.** File an issue only for a user-visible defect outside the diff: wrong output a user can see, in code this PR did not touch, that reproduces on the base. Everything else is recorded in the report or the reply, never filed.
   - Write the issue body with the defect, its reproduction, the files involved and a link to this PR.
   - File it before replying:

     ```
     gh issue create --repo 116-Labs/cuecal --title "<title>" --body-file <run-dir>/scratch/followup-<k>.md
     ```

   - Name the new issue's number in the reply.
6. To reply, write the text to `<run-dir>/scratch/reply-<k>.md` and run:

   ```
   gh api repos/116-Labs/cuecal/pulls/<n>/comments/<comment-id>/replies --method POST -F body=@<run-dir>/scratch/reply-<k>.md
   ```

7. To resolve, write `<run-dir>/scratch/resolve.graphql` containing `mutation($id: ID!) { resolveReviewThread(input: {threadId: $id}) { thread { isResolved } } }` and run:

   ```
   gh api graphql -F query=@<run-dir>/scratch/resolve.graphql -f id=<thread-id>
   ```

8. If a reply or resolve fails after the review was posted, report it and end `needs-human`. Never retry: a retry risks a second review.
9. Report the open threads split into **suggestions** and **author-owed**.

### 17. Write the run result (result step, `run-result-written`)

Run this step on every exit path, failures included, after restoring the checkout (step 4).

1. Run `date -u +%Y-%m-%dT%H:%M:%SZ` and keep the output as `finished_at`.
2. Write `<run-dir>/result.json.tmp` with the file-writing tool. It holds these fields, and no others:
   - `schema_version`: `1`
   - `run_id`: `<run-id>`
   - `blueprint`: `"review-pr"`
   - `blueprint_version`: `"1.8.0"`
   - `repo`: `"116-Labs/cuecal"`
   - `issue`: the issue picked in step 2, or `null`
   - `pr`: `<n>`, or `null`
   - `status`: `done`, `needs-human`, `needs-clarification` or `failed`
   - `reason`: required unless `done`. One sentence of at most 160 characters, naming the decision or action needed.
   - `questions`: a non-empty array, only for `needs-clarification`.
   - `attempts`: `1`
   - `gates`: the `lint` and `test` runs on `<head>`, in the order they ran, each `{name, command, exit_code, duration_ms}`.
     - Include a gate only if it ran (`truthful-report`).
     - Use `[]` when none ran.
     - A `done` result never lists a non-zero `exit_code`.
   - `branch`: the PR's head branch, or `null`
   - `commit_sha`: `null`, because this skill never pushes
   - `review`: required when `done`, and included whenever a review was composed. It holds:
     - `verdict`: `approve`, `request-changes` or `comment`, as posted (or as it would be posted, in preview);
     - `blocking`: the number of Blocking findings, still counted when the verdict was downgraded to comment;
     - `non_blocking`: Secondary plus Nits;
     - `head`: `<head>`, the sha on the `Reviewed head:` line;
     - `criteria`: every linked issue's criteria, in order, each `{text: "#<issue>: <criterion as the issue states it>", status}`;
     - `approval_withheld`: only when the verdict was approve but comment was posted. Use `author`, then `identity`, then `pushed`, taking the first that applies.
   - `started_at` and `finished_at`.
3. Run:

   ```
   mv <run-dir>/result.json.tmp <run-dir>/result.json
   ```

   Never leave the `.tmp` file behind.
4. Give the final report:
   - the acceptance-criteria results;
   - the description-accuracy note;
   - the thread ledger (open threads, split into suggestions and author-owed);
   - the push or collapse outcome ("no push: separate review identity");
   - the inline and body-only finding counts, with the reason for each body-only one;
   - any line-anchor fallback;
   - whose push moved the diff, if any;
   - any start-signal failure.

## Exit states

- **`done`**: no Blocking finding stands, and the review is posted (or composed, in preview). `review` carries the verdict and counts. A clean review whose approve was posted as comment for identity also ends `done`, with `review.approval_withheld`.
- **`needs-human`**: applies when any of these hold:
  - a Blocking finding stands;
  - threads are left for the author, expected whenever Blocking is above 0, even when identity downgraded the verdict to comment;
  - the id of the review just posted was empty;
  - a thread reply or resolve failed after the review was posted.

  `reason` summarizes which.
- **`needs-clarification`**: applies when any of these hold:
  - no PR could be determined;
  - the PR links no issue (a number that names no issue counts as none, and `questions` name the number);
  - a linked issue has no checkable acceptance criteria.

  `questions` say what is missing.
- **`failed`**: applies when any of these hold:
  - the PR is not open, or GitHub cannot find it (404);
  - the environment could not be prepared on a PR that changes no dependency manifest or lockfile (nothing posted);
  - the checkout had uncommitted changes;
  - a read failed or a listing was truncated;
  - posting failed even after the body-only fallback.

  `reason` names the step.

## Invariants

Blueprint invariants:

- `description-last`: the description is read only after the correctness pass, the gates and the test check (step 9).
- `verdict-follows-findings`: request changes with at least one Blocking finding, approve with none, comment when undecidable. The review states the rule (step 12).
- `no-self-verdict`: a context that wrote or pushed the change posts comment. This run never pushes (steps 12 and 13).
- `identity-withholds`: a run that is not the separate review identity posts comment instead of approve. With `GAAL_LOGIN` empty or absent, it posts comment whatever the verdict, with the verdict first, and `blocking` is still counted (step 12).
- `findings-verified`: every posted finding was reproduced at its line on `<head>` (step 10).
- `tests-named`: every behavioural change names its test or is a finding, and the review has a Tests section (steps 8 and 15).
- `signed-review`: the body carries `Reviewed head: <sha>` and ends with `gaal review-pr · run <run-id>` (step 15).
- `fixed-not-flagged`: a pushed fix appears only in "Fixed in". Nothing is pushed here (step 13).
- `resolve-own-threads-only`: only threads matched to this review's id are resolved, each after a reply (step 16).
- `collapse-before-approve`: any collapse precedes anchors and posting. No collapse happens here (step 13).
- `contradiction-fixed-or-threaded`: every contradiction becomes an inline thread (steps 11 and 14).
- `rereview-converges`: after round 1, new threads open only for Blocking findings and contradictions, and the review names the earlier threads the delta answered (steps 14 and 15).

Shared invariants:

- `explicit-staging`: nothing is staged here (step 13).
- `base-untouched`: nothing is committed or pushed here (step 13).
- `fail-closed-reads`: failed reads end the run `failed` (command rules).
- `complete-listings`: listings are paginated to the end (command rules).
- `truthful-report`: the report and result say only what happened (step 17).
- `status-preserved`: no exit status is hidden (command rules).
- `attribution-policy`: attribution is `none`, so nothing is added (project facts).
- `run-result-written`: the result is written atomically on every exit path (step 17).
- `gates-final-tree`: `gates` lists only the runs on `<head>` (steps 7 and 17).
- `install-before-gates`: no install is named, so the gates run in the checkout (step 4).
- `push-failure-states`: no push is made (step 13).
- `collapse-remote-contained`, `collapse-content-preserved` and `collapse-keeps-link`: no collapse runs (step 13).

## Forbidden actions

Blueprint:

- `description-sets-scope`: letting the description or its focus section limit what is reviewed.
- `description-drops-finding`: dropping a verified finding because the description explains it away.
- `second-identity-approval`: approving through another identity, or retrying a refused approval under one.
- `rewrite-foreign-branch`: pushing to or rewriting a fork's branch, or commits someone else authored.
- `resolve-to-unblock`: resolving threads to clear the merge path.
- `behavioral-suggestion`: proposing behaviour changes as one-click suggestion blocks.

Shared:

- `bare-force-push`: force-pushing without `--force-with-lease=<branch>:<sha>`. This skill never pushes.
- `admin-bypass`: using `gh pr merge --admin` or any other admin route around protection.
- `bypass-hook`: using `--no-verify`, `git commit -n`, `--no-gpg-sign`, any hooks-path change, or editing hooks or `.git/config`.
- `machine-specific-paths`: hard-coding a person's home directory, private scripts or services.
- `commit-foreign-edits`: committing changes this run did not make.
