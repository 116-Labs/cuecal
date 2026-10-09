---
name: gaal-review-pr
description: >-
  Adversarially reviews one open pull request in 116-Labs/cuecal against the
  acceptance criteria of its linked GitHub issues, read fresh at review time,
  and against the profile gates (uv run ruff check . and uv run pytest, run
  after uv sync --locked). It reads the PR description last, as a set of
  claims to test, posts exactly one signed review whose verdict follows from
  the verified findings, leaves open only the threads the author owes, and
  writes the run result to result.json in the run directory. Use it when a
  dispatch hands over a repo and a PR number, in post or preview mode, and
  asks for the review-pr step. In this repository the review runs as the
  separate review identity, so it never commits or pushes, and every fix goes
  to the author as a finding. Do not use it to implement an issue
  (gaal-implement), open a PR (gaal-open-pr), revise a PR after review
  (gaal-revise-pr), merge, publish or deploy. When no PR can be determined, do
  not guess, and end as needs-clarification.
---
<!-- gaal-stamp blueprint=review-pr@1.9.0 shared=1.5.0 profile=6f85855df888e336 generated=2026-10-09 core=b8870cb250ef9e03 forbidden=54c30c1c66633c73 content=ce07dfa26a4cd9d8 -->

# gaal-review-pr

Review an open PR in `116-Labs/cuecal` the way a careful maintainer would. Judge it against the linked issues' acceptance criteria and the project's gates, independently of how the PR describes itself. Post exactly one review with a verdict that follows from the findings, and leave open only the threads the author genuinely owes.

Blueprint: `review-pr` version `1.9.0`, with the shared rules version `1.5.0`.

## Project facts this skill relies on

- **Repository:** `116-Labs/cuecal`, public, default branch `main`. Tracker: GitHub issues in the same repository.
- **Install:** `uv sync --locked`. It is the only install command. Run it before the gates every time.
- **Gates (both required):** `lint` is `uv run ruff check .` and `test` is `uv run pytest`.
- **Preflight:** none. **Advisory checks:** none.
- **Commits:** one commit per PR (`single_commit: true`), Conventional Commits, attribution `none`. Nothing this run writes (review bodies, replies, follow-up issue bodies) carries AI attribution (`attribution-policy`).
- **Branches:** gaal branches use the prefix `gaal/`. No stacking tool is named. A PR's base is whatever GitHub reports (`main`, or a parent branch for a stacked PR). Always use the PR's actual base.
- **Merge:** squash, message taken from the commits (`message_source: commits`), no merge queue, `merge.auto: true`. Gaal merges a converged PR automatically. A review body blocks nothing. Only an open thread, changes requested or a missing approval blocks a merge.
- **Review policy and branch protection:** 1 required approval. Open threads block merge (`threads_block_merge: true`). Stale approvals are dismissed on push. Approval of the last push is not required. Code-owner reviews are required. Required checks are `test` and `zizmor`. `zizmor` runs only in CI, and this run never runs it locally. The start signal is a reaction. No `sign_off` line is configured.
- **Review identity:** `review.identity.reviewer` is `separate`, with login `116-labs-gaal-review[bot]`. GitHub spells it `116-labs-gaal-review[bot]` in REST, `116-labs-gaal-review` in GraphQL and `app/116-labs-gaal-review` in `gh --json`. The push identity is `116-labs-gaal-push[bot]`. Because the reviewer is separate, **this skill never commits and never pushes**.
- **Limits:** `review_rounds: 2`, `revise_rounds: 3`, `implement_attempts: 3`. Gaal enforces them across runs. This run consumes one attempt (`attempts: 1` in the result) and reports its round number in the final message: 1 when no earlier signed review exists, otherwise the count of earlier signed reviews plus 1.

## Run context and command rules

- `<run-dir>` in every command stands for the literal path of `GAAL_RUN_DIR` from the run context. `<run-id>` stands for the literal value of `GAAL_RUN_ID`. Never write either variable name in a command. Write the literal values.
- `GAAL_LOGIN` from the run context is the account this run acts as. Never ask GitHub for it (`gh api user` answers 403 to an App token). Compare it with any login GitHub shows in all three spellings (`<slug>[bot]`, `<slug>`, `app/<slug>`). The run **is the separate review identity** only when `GAAL_LOGIN` is `116-labs-gaal-review[bot]` in one of its spellings.
- Allowed commands: `git`, `gh`, `mkdir`, `mv`, `cp`, `ls`, `cat`, `date`, `pwd`, `cd` with a literal path, and exactly `uv sync --locked`, `uv run ruff check .` and `uv run pytest`, with nothing added. Run one command per call. Do not chain with `&&`, `;` or `|`. Never use shell variables, command substitution, backticks or `NAME=value` prefixes. Placeholders below are written `<like-this>`; replace each with a literal value.
- Scratch files and throwaway worktrees live under `<run-dir>`, never in `/tmp` or through `mktemp`. Write every file (review body, issue bodies, GraphQL query files, JSON payloads, the result) with the file-writing tool, never through shell redirection. Pass each by its path (`--body-file <file>`, `-F body=@<file>`, `-F query=@<file>`, `--input <file>`).
- There is no `jq` binary. Filter with `gh … --jq`.
- Quote every glob passed to a command.
- List uncommitted paths file by file with `git status --porcelain=v1 --untracked-files=all`.
- Never touch hook configuration (`bypass-hook`): no `--no-verify`, no `git commit -n`, no `--no-gpg-sign`, nothing that names where git looks for hooks. Never edit, move or restore `.git/config` or a hook file. This skill makes no commits, so it never needs any of these. If it needs the hooks directory, it runs `git rev-parse --git-path hooks`.
- Never use `gh pr merge`, and never use `--admin` (`admin-bypass`).

## Steps

### 1. Start

1. Run `date -u +%Y-%m-%dT%H:%M:%SZ` and keep the output as `started_at`.
2. Run `pwd` and keep the output as `<checkout>`, the literal checkout path.
3. Run `mkdir -p <run-dir>/scratch`.
4. Take the PR number `<n>` and the mode from the dispatch. The mode is post by default, or preview. If no PR number can be determined, go to the result step and end `needs-clarification` with a question asking which PR to review.

From here on, every exit path goes through **cleanup** and then the result step. This includes failures. Cleanup means:

- run `cd <checkout>`;
- remove each worktree this run added (`git worktree remove --force <run-dir>/worktree`, and the same for `<run-dir>/base-worktree`);
- delete any pending review this run created and did not submit (see the posting step).

### 2. Read PR metadata, but not the description (`description-last`)

Read only the metadata. Never read the `body` here:

```
gh api --include repos/116-Labs/cuecal/pulls/<n> --jq '{number, state, merged, draft, base: .base.ref, head: .head.ref, head_sha: .head.sha, head_repo: .head.repo.full_name, author: .user.login}'
```

- If the HTTP status line is `404`, end `failed` and name PR `<n>` as not found.
- Any other failed read, auth expiry or rate limit ends `failed` naming the read. Never treat a failure as "no PR" (`fail-closed-reads`).
- If `state` is not `open`, end `failed` because the PR is not open.
- Keep `<base>`, `<branch>` (the head ref), the PR author's login, and whether `head_repo` differs from `116-Labs/cuecal` (a fork).

List files and commits to the end (`complete-listings`). A failed listing ends `failed`.

```
gh api repos/116-Labs/cuecal/pulls/<n>/files --paginate --jq '.[] | {filename, status, additions, deletions}'
```

```
gh api repos/116-Labs/cuecal/pulls/<n>/commits --paginate --jq '.[] | {sha, author: .author.login, email: .commit.author.email}'
```

Note two things:

- whether the PR changes a dependency manifest or lockfile (`pyproject.toml`, `uv.lock`);
- whether it changes workflows (`.github/workflows/`), scripts or skill files.

### 3. Find the linked issues (shared issue-link rule)

Read all three sources every time. Never read the body links only when GitHub reports no closing issue.

1. Closing references GitHub reports. GitHub fills these only for a PR based on `main`.

   ```
   gh pr view <n> --repo 116-Labs/cuecal --json closingIssuesReferences --jq '.closingIssuesReferences[].number'
   ```

2. Links in the PR body. Extract only each link's keyword and digits, with exactly this filter, so the description text never enters context. jq reads the pattern as a string literal, so `\\t` reaches the regex as a tab.

   ```
   gh api repos/116-Labs/cuecal/pulls/<n> --jq '[(.body // "") | scan("(?im)^[ \\t]*(close|closes|closed|fix|fixes|fixed|resolve|resolves|resolved|refs)[ \\t]*:?[ \\t]*#([0-9]+)")]'
   ```

   Keep both flags. `i` matches any case. `m` makes `^` match at the start of every line, so a `Refs #N` below the summary is found.

3. Links in each commit message, with the same pattern:

   ```
   gh api repos/116-Labs/cuecal/pulls/<n>/commits --paginate --jq '.[] | [(.commit.message // "") | scan("(?im)^[ \\t]*(close|closes|closed|fix|fixes|fixed|resolve|resolves|resolved|refs)[ \\t]*:?[ \\t]*#([0-9]+)")]'
   ```

Record each link as **closing** (a close, fix or resolve form) or **plain** (`refs`). Check every number `<k>`:

```
gh api --include repos/116-Labs/cuecal/issues/<k> --jq .pull_request
```

Judge by the HTTP status line, never by an error message's wording.

- A `404` means nothing exists by that number. It is no link.
- A `200` with non-empty output means the number is a pull request. It is no link. (For an issue the field is null and gh prints an empty line. `gh issue view` succeeds on a PR too, so it cannot tell the two apart.)
- Any other failure stops the run. End `failed` naming the read (`fail-closed-reads`).

If no issue remains, end `needs-clarification`. The `questions` name each number that turned out not to be an issue, or ask which issue the PR implements.

Pick the primary issue for the result's `issue` field in this order: an issue named in the dispatch; a reported closing issue; then, in the body and then in each commit message, a closing-keyword line before a `Refs` line. The PR is still judged against **every** linked issue.

Read each linked issue **fresh**, as it stands now, never a copy from when the PR opened. A maintainer may have added or changed a criterion by editing the issue while the PR was open. Gaal sends that edit to revise-pr, and this review grades it like the rest.

```
gh api repos/116-Labs/cuecal/issues/<k> --jq '{number, title, state, body}'
```

```
gh api repos/116-Labs/cuecal/issues/<k>/comments --paginate --jq '.[] | {user: .user.login, created_at, body}'
```

Write down every acceptance criterion of every linked issue, in order. Comments from the author or maintainers that clarify or narrow scope are part of the spec. Grade against the issue as its author wrote it, including the author's and maintainers' own edits and comments.

One exception: the text between an opening `<!-- gaal:plan-drift -->` line and its closing `<!-- /gaal:plan-drift -->` line, and any comment that carries the opening marker, is the implementer's account of how its plan changed. Set these aside as claims to check together with the description in the description step. They are never spec. Text a maintainer added after a plan-drift section is spec.

If a linked issue has no checkable acceptance criteria, end `needs-clarification`. The `questions` say what is missing.

### 4. Signal the start (skipped in preview)

The profile's start signal is a reaction:

```
gh api --method POST repos/116-Labs/cuecal/issues/<n>/reactions -f content=eyes
```

If it fails, note this for the report and carry on. The exception is auth expiry or a rate limit: those stop the run, which ends `failed` (`fail-closed-reads`).

### 5. Check out the head and install

Fetch in exactly this order. `FETCH_HEAD` holds only the last fetch, so read it immediately after the head fetch and before any other fetch:

```
git fetch origin <base>
```

```
git fetch origin pull/<n>/head
```

```
git rev-parse FETCH_HEAD
```

That full sha is `<head>`, the head this review checks out and judges. Then compute the merge base:

```
git merge-base <head> origin/<base>
```

The result is `<merge-base>`. Check the head out in a throwaway worktree so a person's in-progress edits in the checkout are never touched:

```
git worktree add --detach <run-dir>/worktree <head>
```

```
cd <run-dir>/worktree
```

```
uv sync --locked
```

Install every time, even when the dependencies look present, because they may be stale (`install-before-gates`). If `uv sync --locked` fails:

- **The PR changes `pyproject.toml` or `uv.lock`:** the PR broke the install. Record a Blocking finding that names `uv sync --locked`. Skip the gates. The review says that what the gates would have shown is unverified. Carry on with the remaining passes.
- **Otherwise:** the head cannot be verified for reasons outside the PR. Post nothing, and end `failed` naming `uv sync --locked`.

### 6. Re-review step: limit attention to the delta

Find earlier reviews by their signature line, never by login. GitHub spells an App's login three ways, and `GAAL_LOGIN` is only one of them. This filter skips a review with no body instead of failing on it:

```
gh api repos/116-Labs/cuecal/pulls/<n>/reviews --paginate --jq '.[] | select((.body // "") | contains("gaal review-pr · run ")) | {id, head: ((.body | capture("Reviewed head: (?<sha>[0-9a-f]{40})").sha) // "none")}'
```

Keep every listed `id` as an **earlier review-pr review**. Reviews come oldest first, so the last match is the last review.

**No match:** this is round 1. Review the whole diff:

```
git diff <merge-base> <head>
```

**A match:** this is a re-review, and the last match's `head` is `<old-head>`.

- If `<old-head>` is `none`, review the whole diff.
- Otherwise, if `<old-head>` is not local, fetch it with `git fetch origin <old-head>`. If it still cannot be fetched, review the whole diff and say so in the review.
- When it is available, compute where `<old-head>` left the base it was reviewed against. Never use the current head's merge base for this.

  ```
  git merge-base <old-head> origin/<base>
  ```

  The result is `<old-merge-base>`. When history was rewritten, use a range diff:

  ```
  git range-diff <old-merge-base>..<old-head> <merge-base>..<head>
  ```

  When it was not rewritten, use `git diff <old-head> <head>`.
- Also check whether the author's push moved the diff since the last review. Report that later.

**On a re-review, also re-check resolved threads.** A resolved thread is not a fixed finding. A rebase can mark a thread outdated, revise-pr then resolves it unfixed, and a delta-only re-review would never look at it again.

1. List all this PR's review threads with the query in the anchor step.
2. Read each earlier review-pr review's body to take the thread links its Dispositions list names:

   ```
   gh api repos/116-Labs/cuecal/pulls/<n>/reviews/<id> --jq .body
   ```

3. Keep each thread that meets all three conditions:
   - `isResolved` is true;
   - an earlier review-pr review opened it (its first comment's `pullRequestReview.databaseId` is one of the listed `id`s, never matched by login), or such a review's Dispositions list links it as a finding's `thread`. A thread a person or another bot opened counts in that second case;
   - `resolvedBy.login` is the PR's author or `GAAL_LOGIN`, each compared in any of its spellings.

A thread any other account resolved is a person's decision. That person accepted the finding, and it is not re-checked.

Where gaal pushes as a person's own login (the token fallback, with no push App), the PR's author is that person, so their resolution counts as gaal's and is re-checked. A finding that still reproduces then opens a thread again on the next re-review, and such a PR is merged by hand.

Each kept thread whose finding still reproduces on `<head>` becomes a candidate finding of this review, whatever the delta. The criteria walk verifies it, and it takes a disposition again.

### 7. Correctness pass

Read the diff (on a re-review, the delta, plus the re-checked threads) for logic, edge cases, error handling, concurrency and security. Scripts, workflows and skill files count as code. In them, check for:

- nonexistent flags;
- word-splitting and quoting;
- flags that are documented but not implemented;
- injection through untrusted input;
- re-runs that are not idempotent;
- swallowed errors;
- success inside loops that is never verified.

A PR that makes a pre-existing defect reachable owns it. That defect is a Blocking or Secondary finding of this PR, never Pre-existing and never filed, even though the code it sits in is untouched.

### 8. Gates

Skip the gates if the install step recorded a PR-caused install failure. Otherwise, in `<run-dir>/worktree`, run each gate exactly as the profile writes it, timing it with separate calls just before and just after:

```
date -u +%s
```

```
uv run ruff check .
```

```
date -u +%s
```

```
date -u +%s
```

```
uv run pytest
```

```
date -u +%s
```

For each gate, record `name`, `command`, `exit_code` and `duration_ms`. `duration_ms` is the difference between the two readings times 1000. Read every exit status directly, never through a filter or pipe that could hide it (`status-preserved`).

- A required gate that exits non-zero on `<head>` is a Blocking finding naming the gate. A review that ran one never ends `done` (`gates-final-tree`).
- There is no preflight and no advisory check to run.
- A gate that did not run is never reported as passed (`truthful-report`).

### 9. Tests check (`tests-named`)

For each behavioural change in the diff, name the test that covers it. That is either a new or changed test that fails without the change, or an existing test that already exercises it. A change is tested only when a test fails without it. A test that also passes on the base proves nothing about the change. A test the gates never ran proves nothing about the head.

A behavioural change with no covering test is a finding. It is Blocking when the linked issue's criteria ask for tests, and Secondary otherwise. For each new or changed test, note whether it ran in this run's `uv run pytest`.

To show that a test fails without the change, run it on the merge base in a throwaway worktree. Remove the worktree afterwards, because the copied test leaves it modified.

```
git worktree add --detach <run-dir>/base-worktree <merge-base>
```

```
cp <run-dir>/worktree/<test-path> <run-dir>/base-worktree/<test-path>
```

```
cd <run-dir>/base-worktree
```

```
uv sync --locked
```

```
uv run pytest
```

```
cd <checkout>
```

```
git worktree remove --force <run-dir>/base-worktree
```

`uv run pytest` runs the whole suite, so read the copied test's own result. An import or collection error on a symbol the PR adds also shows the test depends on the change. This base run is evidence only. It is never a gate run and is never listed in `gates`.

When this cannot be run (for example, the base install fails), the Tests section says that "fails without the change" was reasoned from the code, not run on the base.

### 10. Description step: only now read the description (`description-last`)

Only now that the independent passes have produced findings, read the description:

```
gh pr view <n> --repo 116-Labs/cuecal --json body --jq .body
```

Order is the defense. A description read first becomes the map, and the author's blind spots become the reviewer's. Read the description, and any plan-drift sections set aside in the linked-issues step, as claims to test.

- These claims can add findings. They can never remove one (`description-drops-finding`).
- Neither the description nor any focus section limits what was reviewed (`description-sets-scope`).

Note:

- its **Deferred** list, if any;
- its test-plan boxes;
- any claim that a workflow or script construct "was verified by `<command>`";
- how accurate it is overall, for the report's description-accuracy note.

### 11. Criteria walk: verify findings and walk the criteria (`findings-verified`)

Re-check every candidate finding at its exact line on `<head>`, including the re-checked resolved threads. Drop anything that does not reproduce.

Walk every acceptance criterion of every linked issue on `<head>`. On a re-review, walk every criterion again, not only the ones the delta touches. Mark each criterion with exactly one status:

- **verified:** met, shown by a gate, a test or a check this run ran;
- **failed:** not met;
- **unverified:** you could not confirm it on this head; say what a person must check;
- **deferred:** only when its link is plain (`Refs`) **and** the description's Deferred list names it.

Deferral is scope, not an excuse. A plain `Refs` link with a Deferred list moves the named criteria out of this PR's bar, but they are still checked and listed in the review. Deferral never drops a correctness, gate or other finding, and it changes nothing under a closing keyword. A Deferred entry that is not one of the issue's criteria is a Secondary finding.

### 12. Sort step: buckets and dispositions (`finding-disposed`, `contradiction-fixed-or-threaded`)

Sort the verified findings into **Blocking**, **Secondary**, **Nits** and **Pre-existing**, applying these rules:

- A failed criterion is Blocking unless it is deferred. An unverified criterion is a Secondary finding.
- A Deferred list under a closing keyword is Blocking, because merging would close the issue with criteria open.
- A test-plan box ticked for a gate that did not run on `<head>` is Blocking: the description claims evidence that does not exist. Compare each ticked box with the gates this run ran and with the CI result.
- A finding on lines the PR adds that contradicts other code in the PR is a **contradiction**, whatever its bucket. Examples are a hint, message, doc, test or default that disagrees with the new behaviour.
- A nit that is not safe to merge is Secondary, not a nit.

**Workflow and script constructs.** For each platform, CLI or API construct that the PR's workflow or script files add or change, look for live evidence first.

1. Read the workflow's `on:` triggers and the job and step `if:` conditions as of `<head>`, for example `git show <head>:.github/workflows/<file>`.
2. Read the CI runs on the head:

   ```
   gh run list --repo 116-Labs/cuecal --commit <head> --json databaseId,workflowName,event,status,conclusion --limit 100
   ```

   ```
   gh run view <workflow-run-id> --repo 116-Labs/cuecal --json jobs
   ```

   A listing that returns a full 100 is truncated. End `failed` naming it (`complete-listings`).

The PR's CI **could have run** the construct when a `pull_request` run on this head would execute the step holding the PR's version of it. That means:

- the workflow triggers on `pull_request`;
- its `branches` and `paths` filters, and their `-ignore` forms, match this PR's base and changed files;
- the job's `if:` and the step's `if:` are true for a `pull_request` event.

A `pull_request_target` trigger does not count. It runs the base branch's copy of the workflow, so a green run of it says nothing about the PR's change.

Classify each construct:

- **Ran and passed:** CI ran it on `<head>` and it passed. This is not a finding.
- **Could have run but did not, or failed:** this is **Blocking**. Its behaviour is unverified, and lint does not verify it. A workflow change the PR's CI can run is never approved on lint alone.
- **Cannot run on this PR:** examples are a `pull_request_target`-only workflow, a trigger only on a push to the base, a tag, a release or a schedule, or filters or an `if:` that skip it for this PR. This is a **Secondary** finding that names what a person must check, the same way an unverified criterion does. Its thread keeps the PR from merging automatically until a person resolves it, and that is intended: nothing a review or revise-pr pushes can verify it.

When the description states the construct was verified by a command, the finding says "the author states it was verified by `<command>`". If that command is one this run may execute (one of the three `uv` commands), run it and record its result in the finding. The description never drops the finding (`description-drops-finding`).

**Dispositions.** Give each finding exactly one disposition before the review is posted:

- **Blocking finding:** always **thread**.
- **Secondary finding or contradiction:** **fixed** or **thread**. This repository's reviewer is the separate identity and pushes nothing (see the auto-fix step), so here it is always **thread**. That means a new inline or file-level thread, or an earlier review's still-unresolved thread that already carries the finding. A contradiction is never left only in the review body: revise-pr acts on threads, so a contradiction listed only in a body is lost at merge.
- **Secondary findings are never filed.** A Secondary finding is this PR's own and does not reproduce on the base. That includes a defect in untouched code that this PR makes reachable. An issue filed against it would let the PR merge with it.
- **Pre-existing finding:** if it meets the shared follow-up bar (a user-visible defect outside the diff, in code this PR did not touch, that reproduces on the base), it is **filed**. Otherwise it is recorded in the review body. Pre-existing defects never open threads.
- **Nit that is not a contradiction:** takes no disposition. It is safe to merge by definition.

A finding that appears only in the summary merges unseen. `merge.auto` merges a converged PR, and a review body blocks nothing. In one cuecal review (PR #63), a real defect was flagged only as a Secondary finding in the body, and only a person reading it caught the defect. So no review leaves a Blocking finding, Secondary finding or contradiction only in its summary text.

### 13. Verdict (`verdict-follows-findings`)

Choose the verdict from the findings:

- **request changes** when at least one Blocking finding stands;
- **approve** when none stands (nits may remain);
- **comment** when the verdict is undecidable.

The review states which rule it applied.

Then decide which event this run may post (`identity-withholds`, `no-self-verdict`, `second-identity-approval`):

1. **`GAAL_LOGIN` is empty or absent:** the author check is unknown. Post **comment** whatever the verdict, with the verdict as the first line. Never approve or request changes.
2. **`GAAL_LOGIN` equals the PR author** in any of its spellings (`<slug>[bot]`, `<slug>`, `app/<slug>`): this context wrote the change. Post **comment** with the verdict as the first line.
3. **Request changes** from an account that did not write the PR: post **request changes**, whatever the identity.
4. **Approve** from an account that did not write the PR: post **approve** only when this run is the separate review identity (`116-labs-gaal-review[bot]`). Otherwise post **comment**.

Never approve through another identity, and never retry a refused approval under a different one (`second-identity-approval`). When the verdict is approve but this run posts comment, the review says so and says that the PR is otherwise clean.

### 14. Auto-fix step: no fixes are pushed here

The profile sets `review.identity.reviewer: separate`. A review run that pushed could never approve, and gaal refuses an approval from a review run that pushed. So this run **commits nothing and pushes nothing**, whatever the bucket.

- Every small fix this run could have made goes to the author as a finding. A Secondary finding or contradiction takes the **thread** disposition.
- Never propose a behaviour change as a one-click suggestion block (`behavioral-suggestion`). Behaviour changes go to the author as findings. A suggestion block is only for a non-behavioural edit with exactly one reasonable form.
- Because nothing is pushed, none of the following applies, and the report says so:
  - the collapse routine never runs (`collapse-before-approve` holds trivially; `collapse-remote-contained`, `collapse-content-preserved` and `collapse-keeps-link` are never exercised);
  - the push-failure handling never runs (`push-failure-states`);
  - the "Fixed in" list is empty (`fixed-not-flagged`);
  - `commit_sha` is null;
  - `approval_withheld` is never `pushed`.
- Never push to or rewrite any branch, a fork's or someone else's above all (`rewrite-foreign-branch`). Never commit or push to the base (`base-untouched`). Never stage anything (`explicit-staging`), and never commit changes this run did not make (`commit-foreign-edits`). Never force-push. Any lease-based push would need `--force-with-lease=<branch>:<sha>` (`bare-force-push`), but this skill never pushes at all.
- Scratch files live under `<run-dir>`. Leave the checkout's working tree exactly as it was.

### 15. Filing step: file follow-ups before posting

Only a Pre-existing finding that meets the shared follow-up bar is filed. A Blocking finding, Secondary finding or contradiction never is.

In preview, file nothing. The review body marks each such finding `would file`.

Otherwise, for each such finding, first look for an issue already filed for it. Every follow-up body carries the marker line `<!-- gaal:follow-up pr=<n> -->`, so list them with exactly:

```
gh issue list --repo 116-Labs/cuecal --state all --search "\"gaal:follow-up pr=<n>\" in:body" --json number,title,body --limit 100
```

- A listing that returns a full 100 is truncated: end `failed` (`complete-listings`). A search that fails stops the run: end `failed` (`fail-closed-reads`).
- If a listed issue carries the same finding, its number is the disposition, and nothing new is filed.
- Otherwise, write the body to `<run-dir>/scratch/follow-up-<k>.md` with the file tool. The body names the defect, the reproduction and the files, links this PR, carries the marker line and carries no AI attribution (`attribution-policy`). No labels are added, because the profile names none. Then create the issue:

  ```
  gh issue create --repo 116-Labs/cuecal --title "<title>" --body-file <run-dir>/scratch/follow-up-<k>.md
  ```

A filing that errors is never retried, because a retry could file the issue twice. Run the same search once more. If it lists an issue for the finding, that issue was filed anyway and is the disposition. Otherwise the filing failed: the finding is recorded in the review body, and the report names the failed filing.

### 16. Anchor step: list threads and compute inline anchors

List all of this PR's review threads, paginated to the end (`complete-listings`). Write the query to `<run-dir>/scratch/threads-1.graphql` with the file tool. For the first page, leave out `after`:

```
query {
  repository(owner: "116-Labs", name: "cuecal") {
    pullRequest(number: <n>) {
      reviewThreads(first: 100, after: "<end-cursor>") {
        pageInfo { hasNextPage endCursor }
        nodes {
          id
          isResolved
          isOutdated
          path
          resolvedBy { login }
          comments(first: 1) { nodes { databaseId body url pullRequestReview { databaseId } } }
        }
      }
    }
  }
}
```

```
gh api graphql -F query=@<run-dir>/scratch/threads-1.graphql
```

While `hasNextPage` is true, write the next page's file with `after: "<end-cursor>"` set to the returned `endCursor`, and run it the same way. A failed read stops the run: end `failed` naming it (`fail-closed-reads`).

When an earlier review's thread on this PR is still unresolved (`isResolved` false) and carries the same finding, that thread is the finding's disposition. Open no second thread, and record that thread's first-comment `url`.

Every other finding whose disposition is **thread** takes a **new** thread:

- **Round 1:** every Blocking finding, contradiction and Secondary finding that no earlier unresolved thread carries. A nit may also open a thread on round 1, and it carries no disposition.
- **Re-review (`rereview-converges`):** only Blocking findings, Secondary findings and contradictions, never a nit that is not a contradiction. Nits stay in the body, or are omitted on lines an earlier round already read. A view on another reviewer's open thread goes in the body, never in a second thread. Questions go in the body.

Compute each anchor from the right-hand side of the patch hunks of `<head>` (there is no post-push patch, because nothing is pushed):

```
gh api repos/116-Labs/cuecal/pulls/<n>/files --paginate --jq '.[] | {filename, patch}'
```

When a finding has no changed line of its own, anchor it on the changed line closest to what it concerns, otherwise on the first changed line of the PR. Examples are an unverified criterion, a workflow construct the PR's CI could not run, and a finding about the description.

### 17. Posting step: post one review

**Compose the body.** Write the review body to `<run-dir>/scratch/review.md` with the file tool, in this order:

1. The verdict, as the first line. When the posted event differs from the verdict, say why: the reviewing account wrote the PR, the run is not the separate review identity, or no login is known. If the verdict is approve, also say that the PR is otherwise clean.
2. The rule applied (`verdict-follows-findings`).
3. Findings by bucket (Blocking, Secondary, Nits, Pre-existing). Each finding with a new thread is listed in its bucket and also carried as an inline (or file-level) thread. A finding that an earlier unresolved thread carries is listed in its bucket and not threaded again.
4. Acceptance-criteria results: each criterion of each linked issue marked verified, failed, unverified or deferred. A deferred criterion is never shown as met.
5. A short **Tests** section: each new or changed test and whether it ran in the gates, each behavioural change with no test, and whether "fails without the change" was run on the base or reasoned from the code.
6. A "Fixed in" list. Here it is empty, because this run pushes nothing.
7. A **Dispositions** list naming each Blocking finding, Secondary finding and contradiction with exactly one of:
   - `thread` plus the `url` of its first comment, for an earlier unresolved thread;
   - `thread`, for a thread this review opens;
   - `fixed in <sha>` (never here).

   It also names each Pre-existing finding the filing step filed or found as `filed #<number>` (`would file` in preview), so every follow-up issue is linked from the body. A failed filing is recorded instead.
8. On a re-review, which of this reviewer's earlier threads the delta answered. The body never resolves a thread on that account.
9. No sign-off line, because `review.sign_off` is not set.
10. The line `Reviewed head: <head>`, with the full 40-character sha of the head the review leaves. Here that is the fetched `<head>`, because nothing was pushed.
11. Last, on a line of its own, the signature exactly `gaal review-pr · run <run-id>`, with the literal run id (`signed-review`). Never reword it. A signature that varied from run to run once hid verdicts from a reader that matched only one form.

Carry no AI attribution in the body (`attribution-policy`).

**In preview**, post nothing. Leave the body at `<run-dir>/scratch/review.md`, carry the would-be verdict into the run result and skip the thread listing.

**In post mode**, follow these steps in order.

1. **Check for a pending review.** GitHub allows one pending review per account per PR and refuses to create another, and it shows a pending review only to its author:

   ```
   gh api repos/116-Labs/cuecal/pulls/<n>/reviews --paginate --jq '.[] | select(.state == "PENDING") | {node_id, body: (.body // "")}'
   ```

   - If its body carries the line `<!-- gaal:review-pr pending -->`, a run that stopped mid-post left it. Delete it:

     ```
     gh api graphql -f query='mutation { deletePullRequestReview(input: {pullRequestReviewId: "<node-id>"}) { pullRequestReview { id } } }'
     ```

   - If a pending review without that line stands, it is a person's draft and is never deleted. Post nothing and end `failed` naming it.

2. **Create the review pending.** Write `<run-dir>/scratch/pending.json` with the file tool. It holds `commit_id` (`<head>`), a `body` that is only the line `<!-- gaal:review-pr pending -->`, and `comments`, each `{path, line, side: "RIGHT", body}` for an inline thread. Leave out `event`. A pending review must never carry the `Reviewed head` line or the signature, since nothing may read it as a posted verdict.

   ```
   gh api --method POST repos/116-Labs/cuecal/pulls/<n>/reviews --input <run-dir>/scratch/pending.json
   ```

   Keep the answer's `node_id` and `id`. Never use the single-comment endpoint (`pulls/<n>/comments`), because it posts each comment as a separate review.

   If GitHub refuses an inline anchor, the review is not created. Re-fetch the patch, re-anchor once and try again. If GitHub refuses again, give each finding whose anchor it refused a file-level thread instead. When GitHub does not say which anchor it refused, do this for every finding with a new thread. The file-level thread goes on the file the finding concerns, otherwise on the PR's first changed file. Create the pending review with the remaining line comments, and record the line-anchor fallback for the report.

3. **Add each file-level thread** to the pending review. Write `<run-dir>/scratch/file-thread-<k>.graphql` with the file tool. Use the pending review's `node_id`, never its numeric `id`. Write the body as a GraphQL block string, escaping any `"""` in it as `\"""`.

   ```
   mutation {
     addPullRequestReviewThread(input: {pullRequestReviewId: "<node-id>", path: "<path>", subjectType: FILE, body: """<finding text>"""}) {
       thread { id }
     }
   }
   ```

   ```
   gh api graphql -F query=@<run-dir>/scratch/file-thread-<k>.graphql
   ```

4. **Submit** with the event and the full body from `review.md`, which replaces the pending line. Write `<run-dir>/scratch/submit.graphql` with the file tool. `<event>` is `APPROVE`, `REQUEST_CHANGES` or `COMMENT`.

   ```
   mutation {
     submitPullRequestReview(input: {pullRequestReviewId: "<node-id>", event: <event>, body: """<full review body>"""}) {
       pullRequestReview { databaseId state }
     }
   }
   ```

   ```
   gh api graphql -F query=@<run-dir>/scratch/submit.graphql
   ```

If GitHub also refuses a file-level thread, or the submit fails, delete the pending review with the `deletePullRequestReview` call above (the same `node_id`) so that nothing is posted. Then end `failed`, naming the refused anchor or the failed submit. A review that cannot open a finding's thread is never posted, because a review body alone would let the PR merge past the finding (`finding-disposed`).

### 18. Thread listing: list and settle the threads this review opened (skipped in preview)

Take the id of the review just posted: `pullRequestReview.databaseId` from the submit answer, or the `id` the create call returned.

**Stop if that review id is empty.** End `needs-human` with a `reason`. Never fall back to matching by reviewer login, because that would take in threads that another run or the same account opened (`resolve-own-threads-only`).

List the threads again with the anchor step's query, and keep only those whose first comment's `pullRequestReview.databaseId` equals that id.

- Never resolve a thread that carries a finding's **thread** disposition (a Blocking finding, Secondary finding or contradiction). It stays open for the author and revise-pr, and it keeps the PR unconverged (`finding-disposed`).
- Leave questions, blockers, suggestion blocks and contradiction threads open.
- Never resolve any thread to clear the merge path (`resolve-to-unblock`).
- A Secondary thread the author pushed back on, or one only a person can check (an unverified criterion, a construct the PR's CI cannot run), waits for a person. No review resolves it.

Reply to and then resolve only a thread this review opened for a nit and disposed of itself (recorded only, or an agreed trade-off). Reply first:

```
gh api --method POST repos/116-Labs/cuecal/pulls/<n>/comments/<first-comment-database-id>/replies -F body=@<run-dir>/scratch/reply-<k>.md
```

Then resolve:

```
gh api graphql -f query='mutation { resolveReviewThread(input: {threadId: "<thread-id>"}) { thread { isResolved } } }'
```

Nothing is filed here. The filing step already filed every follow-up issue.

A reply or resolve that fails after the review is posted is reported and ends `needs-human`. Never retry it, because a retry could post a second review.

Report the open threads, split into suggestions and author-owed.

### 19. Result step: write the run result (`run-result-written`)

Do this on every exit path, including failures, after cleanup.

1. Run `date -u +%Y-%m-%dT%H:%M:%SZ` for `finished_at`.
2. Write `<run-dir>/result.json.tmp` with the file tool:

   ```json
   {
     "schema_version": 1,
     "run_id": "<run-id>",
     "blueprint": "review-pr",
     "blueprint_version": "1.9.0",
     "repo": "116-Labs/cuecal",
     "issue": 0,
     "pr": 0,
     "status": "done",
     "reason": "<one sentence, at most 160 characters>",
     "questions": ["<question>"],
     "attempts": 1,
     "gates": [
       {"name": "lint", "command": "uv run ruff check .", "exit_code": 0, "duration_ms": 0},
       {"name": "test", "command": "uv run pytest", "exit_code": 0, "duration_ms": 0}
     ],
     "branch": "<branch>",
     "commit_sha": null,
     "review": {
       "verdict": "approve",
       "blocking": 0,
       "non_blocking": 0,
       "head": "<head>",
       "criteria": [{"text": "#<issue>: <criterion as the issue states it>", "status": "verified"}],
       "approval_withheld": "identity"
     },
     "started_at": "<started_at>",
     "finished_at": "<finished_at>"
   }
   ```

   Fill it in by these rules:

   - `issue` is the primary linked issue number, or `null` when none was found. `pr` is `<n>`, or `null` when no PR was determined. `branch` is the PR's head ref, or `null`.
   - `reason` is required unless `status` is `done`. Leave it out for `done`. It is one sentence of at most 160 characters naming the decision or action needed. Detail belongs in the review and the final message.
   - `questions` is included, non-empty, only for `needs-clarification`.
   - `gates` lists only the gate runs on `<head>`, in the order they ran (`gates-final-tree`). Never list the base-worktree run. Use `[]` when no gate ran. A gate that did not run is absent (`truthful-report`). A `done` result never lists a gate with a non-zero `exit_code`.
   - `commit_sha` is always `null`, because this run never pushes. Leave out `push`.
   - Include `review` once the verdict is known. It is required for `done`.
     - `verdict` is the event actually posted (in preview, the would-be event).
     - `blocking` is the count of Blocking findings. `non_blocking` is the count of Secondary, Nit and Pre-existing findings.
     - `head` is the full sha on the `Reviewed head` line.
     - `criteria` lists every linked issue's criteria in order, on every round including re-reviews, because Gaal posts these after the last round.
   - When the verdict was approve but comment was posted, set `review.verdict` to `comment` and `approval_withheld` to the first that applies: `author` (`GAAL_LOGIN` is the PR author in any spelling), then `identity` (not the separate review identity, or no login known). Leave `approval_withheld` out otherwise.
   - With no login known, `review.verdict` is `comment` and `review.blocking` still counts what was found.

3. Rename it into place, and never leave the `.tmp` file behind:

   ```
   mv <run-dir>/result.json.tmp <run-dir>/result.json
   ```

## Exit states

- `done`: no Blocking finding stands, the review is posted, and no finding's thread is left for the author. `review` carries the verdict and counts. A clean review whose approve was posted as comment for identity or authorship ends `done` with `review.approval_withheld`, so Gaal can tell it apart from one that leaves the author work. In preview, use the status the posted review would have had.

  The final message includes:
  - the acceptance-criteria results and a description-accuracy note;
  - the thread ledger, with open threads split into suggestions and author-owed;
  - the push and collapse outcome: none, nothing pushed, and the head unchanged at `<head>`;
  - the inline and body-only finding counts, with the reason for each body-only one (only a nit, a recorded Pre-existing finding, or a filed finding listed with its link may be body-only);
  - the follow-up issues filed or found;
  - any line-anchor fallback;
  - whose push moved the diff since the last review (the author's, since this run pushes nothing);
  - a failed start signal or failed filing, if one happened;
  - the round number.
- `needs-human`: applies in three cases. First, a Blocking finding stands, or threads are left for the author; every finding whose disposition is thread is one. This holds whether or not identity or authorship downgraded the event to comment. Second, the id of the review just posted was empty, so the threads it opened could not be listed. Third, a thread reply or resolve failed after the review was posted. `reason` summarizes.
- `needs-clarification`: applies in three cases: no PR could be determined; the PR links no issue by the issue-link rule (a link to a number that names no issue counts as none, and `questions` name that number); or a linked issue has no checkable acceptance criteria. `questions` say what is missing.
- `failed`: applies in four cases. First, the PR is not open, or GitHub cannot find the PR number (404). Second, `uv sync --locked` failed on a PR that changes neither `pyproject.toml` nor `uv.lock`, and nothing was posted. Third, a read failed or a listing was truncated (`fail-closed-reads`, `complete-listings`). Fourth, posting failed even after falling back to file-level threads, a refused file-level thread or failed submit included, or a person's pending draft blocked posting; nothing was posted. `reason` names the step.

## Invariants

Blueprint invariants:

- `description-last`: the PR description is read only after the independent passes (correctness, gates, acceptance criteria) have produced findings. See the metadata step and the description step.
- `verdict-follows-findings`: the verdict is request changes with at least one Blocking finding, approve with none, and comment when undecidable. The review states the rule applied.
- `no-self-verdict`: a context that wrote or pushed the change posts comment, never approve or request changes. This run never pushes. When `GAAL_LOGIN` is the PR author, it posts comment.
- `identity-withholds`: a run that is not the separate review identity (`116-labs-gaal-review[bot]`) posts comment when the findings call for approve, with `approval_withheld` set to `author` or `identity`. With `GAAL_LOGIN` empty or absent, the run posts comment whatever the verdict, with the verdict first.
- `findings-verified`: every posted finding was reproduced at its line on the reviewed head.
- `tests-named`: every behavioural change names its covering test or is a finding, which is Blocking when the criteria ask for tests. The Tests section lists each new or changed test and whether it ran in the gates.
- `signed-review`: the body carries `Reviewed head: <sha>` and ends with `gaal review-pr · run <run-id>` on its own line.
- `fixed-not-flagged`: a fix the review pushed appears in "Fixed in" and never also as an inline finding. Here nothing is pushed, so the list is empty.
- `resolve-own-threads-only`: only threads this review opened are resolved, each after a reply. They are matched by review id, never by login.
- `collapse-before-approve`: any collapse happens before anchors and posting. Here no collapse ever runs.
- `contradiction-fixed-or-threaded`: a contradiction is fixed or carried by a thread, never left only in the body and never filed.
- `rereview-converges`: after round 1, new threads open only for Blocking findings, Secondary findings and contradictions that no earlier unresolved thread carries. The review names which earlier threads the delta answered.
- `finding-disposed`: every Blocking finding, Secondary finding and contradiction ends with exactly one disposition before posting. A qualifying Pre-existing finding is filed, or recorded if its filing failed. A review that cannot open a finding's thread is never posted.

Shared invariants:

- `explicit-staging`: this run stages nothing. It writes only scratch files under `<run-dir>`.
- `base-untouched`: this run never commits or pushes to the base.
- `fail-closed-reads`: a failed read, auth expiry or rate limit ends `failed`, never "nothing found". The start signal is the only exception, and only for errors other than auth expiry or a rate limit.
- `complete-listings`: listings are paginated to the end. A truncated listing ends `failed`.
- `truthful-report`: the report and result say only what happened. A gate that did not run is absent.
- `status-preserved`: no command's status is hidden by a pipe, filter or guard.
- `attribution-policy`: attribution is `none`, so nothing this run writes carries AI attribution.
- `run-result-written`: `result.json` is written atomically on every exit path.
- `gates-final-tree`: `gates` lists only the gate runs on `<head>`. A failed required gate is Blocking.
- `install-before-gates`: `uv sync --locked` runs before the gates every time.
- `push-failure-states`: this run never pushes, so this never applies.
- `collapse-remote-contained`: never exercised, because there is no collapse.
- `collapse-content-preserved`: never exercised, because there is no collapse.
- `collapse-keeps-link`: never exercised, because there is no collapse.

## Forbidden actions

- `description-sets-scope`: letting the description or its focus section limit what is reviewed.
- `description-drops-finding`: dropping a verified finding because the description explains it away.
- `second-identity-approval`: approving through another identity, or retrying a refused approval under a different one.
- `rewrite-foreign-branch`: pushing to or rewriting a fork's branch, or commits authored by someone else. This run pushes nothing.
- `resolve-to-unblock`: resolving threads to clear the merge path.
- `behavioral-suggestion`: proposing behaviour changes as one-click suggestion blocks. Those go to the author as findings.
- `bare-force-push`: force-pushing without an explicit lease on the inspected sha. This run never pushes. Any push would need `--force-with-lease=<branch>:<sha>`, never `--force` or `-f`.
- `admin-bypass`: merging, pushing or rewriting with admin privileges, such as `gh pr merge --admin`.
- `bypass-hook`: skipping or redirecting verification (`--no-verify`, `git commit -n`, `--no-gpg-sign`, changing where git looks for hooks, switching off a hook manager, editing hook files or `.git/config`), or retrying through another route.
- `machine-specific-paths`: hard-coding a home directory, private script or service. Every path here is `<run-dir>`, `<checkout>` or a path inside the repository.
- `commit-foreign-edits`: committing changes this run did not make. This run commits nothing.
