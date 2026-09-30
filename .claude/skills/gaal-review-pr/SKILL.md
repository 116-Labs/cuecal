---
name: gaal-review-pr
description: Adversarially reviews an open pull request in 116-Labs/cuecal against its linked issue's acceptance criteria and the profile gates, posts exactly one review whose verdict follows from the verified findings, pushes small unambiguous fixes when allowed, and writes the run result to `$GAAL_RUN_DIR/result.json`. Use when a dispatch hands you a repo and PR number and asks for the `review-pr` step. Do not use to implement an issue, open a PR, revise a PR after review, or merge; those are other steps. If no PR can be determined, do not guess; end as `needs-clarification`.
---
<!-- gaal-stamp blueprint=review-pr@1.0.0 shared=1.1.0 profile=0ed21dd3bece7944 generated=2026-09-30 content=d889ad21509d4fbc -->

# gaal-review-pr

Review an open PR in `116-Labs/cuecal` like a careful maintainer. Judge it against the linked issue's acceptance criteria and the profile gates, independently of how the PR describes itself. Post exactly one review. Leave open only the threads the author owes.

## Inputs

- Repo `116-Labs/cuecal` and a PR number from dispatch. If no PR can be determined, go to step 16 with `needs-clarification`.
- Mode: post (default) or preview. In preview, post nothing and push nothing (skip steps 3, 12 push and collapse, 14, 15).
- Environment: `GAAL_RUN_ID`, `GAAL_RUN_DIR`.
- Profile values used here:
  - Gates: `lint` (`uv run ruff check .`) and `test` (`uv run pytest`). Both are `required: false` and `pending: true`. Run them anyway and report their real results.
  - Preflight: none (empty list).
  - Commits: conventional convention, single commit per PR, attribution `none`.
  - Merge: squash, no queue, `message_source: commits`.
  - Review: one required approval, open threads do not block merge, start signal is a reaction.
  - Tracker: GitHub.
  - Limit: `review_rounds` is 2. If this PR already has 2 reviews from earlier rounds of this automation, do not start a third round. Post nothing new, and end as `needs-human` with the reason naming the round limit.

## Steps

1. **Read PR metadata except the description.** Run `gh pr view <PR> --repo 116-Labs/cuecal --json state,baseRefName,headRefName,headRefOid,headRepository,isCrossRepository,author,files,commits,closingIssuesReferences`. Never request the `body` field. Record the head sha as the reviewed sha. If the call fails (error, auth expiry, rate limit), stop and go to step 16 with `failed` (`fail-closed-reads`). If the state is not open, go to step 16 with `failed`.
2. **Find linked issues without reading the description** (`description-last`). Take issue numbers only from `closingIssuesReferences` (digits only). Read each issue and its comments with `gh issue view`. Write down each acceptance criterion as a checkable statement. If no linked issue has checkable acceptance criteria, go to step 16 with `needs-clarification` and list what is missing in `questions`.
3. **Post the start signal** (post mode only): add a reaction to the PR, for example `gh api -X POST repos/116-Labs/cuecal/issues/<PR>/reactions -f content=eyes`. Check the exit status (`status-preserved`).
4. **Check out the head as fetched from the remote.** Run `git fetch origin pull/<PR>/head` and check out the fetched sha detached, or in a throwaway worktree. Confirm it equals the reviewed sha. Never commit or push to `main` (`base-untouched`). Install dependencies with `uv sync`. Record whether the working tree was already dirty before you touched it, and which paths (`explicit-staging`).
5. **Re-review delta.** If this automation already reviewed this PR, limit attention to the delta since the last review. Use `git range-diff` when history was rewritten. Note which earlier threads the delta answers.
6. **Correctness pass** over the diff: logic, edge cases, error handling, concurrency, security. Scripts, workflows and skill files count as code. Note candidate findings with file and line. Do not open the description yet.
7. **Run every gate** from the profile: `uv run ruff check .` (`lint`) and `uv run pytest` (`test`). No preflight commands exist. Record each command, exit code and duration. Never lose an exit code to a pipe or filter (`status-preserved`). A gate that did not run is absent from the report, never passed (`truthful-report`).
8. **Only now read the description** (`description-last`), as a set of claims to test. Fetch it with `gh pr view <PR> --repo 116-Labs/cuecal --json body`. It can add findings. It can never remove one (`description-drops-finding`) and it never limits what you review (`description-sets-scope`). Note any inaccuracy for the description-accuracy note.
9. **Verify every candidate finding** at its exact line against the reviewed head (`findings-verified`). Drop anything that does not reproduce. Walk the acceptance criteria one by one and mark each met or unmet. A failing gate counts as a finding only if it reproduces and the PR caused it.
10. **Sort findings** into Blocking, Secondary, Nits and Pre-existing. An unmet acceptance criterion under a closing keyword is Blocking. A gate failure caused by the PR is Blocking. Pre-existing defects never open threads, but a PR that makes a defect reachable owns it. On a re-review, only Blocking findings open new threads.
11. **Choose the verdict** (`verdict-follows-findings`): at least one Blocking finding → request changes. None → approve (nits may remain). Undecidable → comment. If you wrote or pushed the change in this context, or the reviewing identity is the PR author, post comment with the verdict as the first line, never approve or request changes (`no-self-verdict`). This downgrade ends the run as `needs-human`. State the rule applied in the review body.
12. **Optionally fix small items** (post mode only). Bound:
    - Non-behavioural fixes always qualify.
    - A behavioural fix qualifies only if it is in a file the PR touches, has exactly one reasonable form, and comes with a test that fails without it. When in doubt, send it to the author as a finding (`behavioral-suggestion`).
    - Never push to a fork's branch or to commits authored by someone else (`rewrite-foreign-branch`). If `isCrossRepository` is true or any commit is by another author, do no fixing.
    - Before pushing, fetch the remote head again. If it is not an ancestor of the local HEAD, the head moved: abandon auto-fix entirely and push nothing.
    - Keep a manifest of paths you wrote. Record a restore point. Revert only what this review wrote, and exclude paths that were already dirty.
    - Order: fix → commit → fast-forward push → collapse → anchors → post. Stage by explicit path from the manifest (`explicit-staging`), for example `git add <path>`, then `git commit` with a conventional message and no attribution lines (`attribution-policy`, attribution `none`). Never commit changes this run did not make (`commit-foreign-edits`). Push with `git push origin HEAD:<headRefName>` as a fast-forward and check the exit status. A fixed item must not also be posted as an inline finding (`fixed-not-flagged`).
    - **Collapse** (`collapse-before-approve`) only if the review pushed a fix, there are zero Blocking findings, and the branch is not a fork or someone else's. The regime is `merge.message_source: commits`, so the collapse applies. Run it in PR mode: read the head sha from the remote, confirm it matches what you fetched, and rewrite in a throwaway detached worktree. Zero or one commit ahead of the merge base is a no-op. Hard gates, never overridden: fork branch, any commit authored by someone else, remote head not an ancestor of what you push. Soft gates: an existing approval would be dismissed, or unresolved threads exist. Print the thread count and say so if you override. Uncommitted edits of unknown origin stop the collapse. After committing, the tree hash must equal the pre-collapse tree hash, or abort before pushing. If the rewrite nets to an empty change, restore and stop. Push with `git push --force-with-lease=<headRefName>:<inspected-sha> origin <new-sha>:<headRefName>`. On failure, restore the previous HEAD. Write the message as a whole for the change in conventional form and drop process commits. Never use an interactive rebase. Tear down only the throwaway worktree. Report mode, regime, commit counts before and after, tree hash, old → new sha, backup refs, and the hard reset each stale checkout needs (never a pull).
    - Because the collapse is done before approving, an approval is never dismissed (`collapse-before-approve`).
13. **Compute inline anchors** from the right-hand side of the **post-push** patch hunks, after any collapse (`collapse-before-approve`). After one anchoring failure, re-fetch and re-anchor once, then fall back to a body-only review. Page every listing of threads, reviews, comments or checks to the end, or stop (`complete-listings`).
14. **Post one review** (post mode only) with `gh api` or `gh pr review`, using a body file. Contents, in order:
    - First line: the verdict and the rule applied.
    - Findings by bucket: Blocking, Secondary, Nits, Pre-existing.
    - Acceptance-criteria results, one line each.
    - A description-accuracy note.
    - A "Fixed in `<sha>`" list, only if that sha contains the fix (`truthful-report`, `fixed-not-flagged`).
    - The reviewed head sha and a signature line (`signed-review`).
    - Suggestion blocks are for non-behavioural edits only. Behaviour changes go to the author as findings (`behavioral-suggestion`).
    - Approve only through the identity running this skill. If approval is refused, downgrade to comment and end as `needs-human`. Never retry under another identity (`second-identity-approval`). If posting fails even as a body-only review, go to step 16 with `failed` naming the step.
15. **Threads.** Reply to and resolve only threads this review opened and then disposed of itself, each after a reply (`resolve-own-threads-only`). Leave the author's threads and other reviewers' threads alone. Never resolve threads to clear the merge path (`resolve-to-unblock`). Threads left open do not block merge here (`threads_block_merge: false`), but still say which are owed. Write a thread ledger for the report.
16. **Write the run result.** On every exit path, including failures and preview, write `$GAAL_RUN_DIR/result.json` atomically (write a temp file in the same directory, then rename) (`run-result-written`). Fields:
    - `schema_version`: 1. `run_id` from `$GAAL_RUN_ID`. `blueprint`: `review-pr`. `blueprint_version`: `1.0.0`. `repo`: `116-Labs/cuecal`.
    - `issue`: the first linked issue number, or null. `pr`: the PR number, or null if none was determined.
    - `status`: one exit state below. `attempts`: 1. `branch`: the head branch or null. `commit_sha`: the full 40-hex sha of a pushed fix or collapse, else null.
    - `gates`: an entry per gate that ran, with `name`, exact `command`, `exit_code`, `duration_ms`. Absent if it did not run.
    - `review`: `verdict` (`approve`, `request-changes` or `comment`), `blocking`, `non_blocking`. Required when `status` is `done`.
    - `reason`: required unless `done`. One sentence, at most 160 characters, naming the decision or action needed.
    - `questions`: required and non-empty for `needs-clarification`.
    - `started_at` and `finished_at`: RFC 3339 timestamps with a `Z` or offset.
    - Omit fields the schema does not list. Do not add extras.

## Exit states

- `done`: The review is posted. `review` carries the verdict and counts. The final report includes acceptance-criteria results, the description-accuracy note, the thread ledger, and the push or collapse outcome with old → new sha.
- `needs-human`: Threads are left for the author (expected when Blocking > 0), the verdict was downgraded to comment because of identity or a refused approval, or the `review_rounds` limit of 2 was reached. `reason` summarizes.
- `needs-clarification`: No PR could be determined, or the linked issue has no checkable acceptance criteria. `questions` say what is missing.
- `failed`: The PR is not open, a read failed and stopped the run, or posting failed even after falling back to a body-only review. `reason` names the step.

## Invariants

- `description-last`: Read the description only after the correctness pass, gates and acceptance criteria have produced findings.
- `verdict-follows-findings`: Request changes if at least one Blocking finding, approve if none, comment when undecidable. The review states the rule applied.
- `no-self-verdict`: A context that wrote or pushed the change posts comment, never approve or request changes.
- `findings-verified`: Every posted finding was reproduced at its line against the reviewed head.
- `signed-review`: The review body names the reviewed head sha and carries a signature.
- `fixed-not-flagged`: A fix pushed by the review is in the "Fixed in" list and never also an inline finding.
- `resolve-own-threads-only`: Resolve only threads this review opened, each after a reply.
- `collapse-before-approve`: Any collapse happens before anchors are computed and before the review is posted.
- `explicit-staging`: Stage only paths this run wrote, from a manifest.
- `base-untouched`: Never commit or push to `main`.
- `fail-closed-reads`: An API error, auth expiry or rate limit stops the run. It never becomes "no PR", "no threads" or "no checks".
- `complete-listings`: Paginate every listing to the end or stop.
- `truthful-report`: The report and result describe what happened. A gate that did not run is absent, not passed.
- `status-preserved`: Never lose a command's exit status to a pipe, filter or guard.
- `attribution-policy`: Commits and PR text follow `commits.attribution: none`. Add no attribution lines.
- `run-result-written`: Write `result.json` on every exit path.

## Forbidden actions

- `description-sets-scope`: Letting the description or its focus section limit what is reviewed.
- `description-drops-finding`: Dropping a verified finding because the description explains it away.
- `second-identity-approval`: Approving through another identity, or retrying a refused approval under a different one.
- `rewrite-foreign-branch`: Pushing to or rewriting a fork's branch or commits authored by someone else.
- `resolve-to-unblock`: Resolving threads to clear the merge path.
- `behavioral-suggestion`: Proposing behaviour changes as one-click suggestion blocks.
- `bare-force-push`: Force-pushing without an explicit lease on the inspected sha. Use only `--force-with-lease=<branch>:<sha>`.
- `admin-bypass`: Merging, pushing or rewriting with admin privileges to get around branch protection or a verification hook.
- `machine-specific-paths`: Hard-coding a person's home directory, private scripts or services.
- `commit-foreign-edits`: Committing changes this run did not make.

Also never use `--no-verify`, `git add -A`, `git add .`, `git commit -a`, an interactive rebase, or a merge as admin.
