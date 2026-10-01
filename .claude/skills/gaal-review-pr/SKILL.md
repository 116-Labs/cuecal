---
name: gaal-review-pr
description: Adversarially reviews an open pull request in 116-Labs/cuecal against its linked issue's acceptance criteria and the profile gates, posts exactly one review whose verdict follows from the verified findings, pushes small unambiguous fixes when allowed, and writes the run result to `$GAAL_RUN_DIR/result.json`. Use when a dispatch hands you a repo and PR number and asks for the `review-pr` step. Do not use to implement an issue, open a PR, revise a PR after review, or merge; those are other steps. If no PR can be determined, do not guess; end as `needs-clarification`.
---
<!-- gaal-stamp blueprint=review-pr@1.2.0 shared=1.3.0 profile=7d4c49f36df8465f generated=2026-10-01 content=a75ed17b12370fc7 -->

# gaal-review-pr

Review an open PR in `116-Labs/cuecal` the way a careful maintainer would. Judge it against the linked issue's acceptance criteria and the project gates, independently of how the PR describes itself. Post exactly one review whose verdict follows from the findings. Push small, unambiguous fixes directly so the author owes answers only on what genuinely needs them.

## Conventions for this run

- `<run-dir>` stands for the literal run directory path given in the run context. `<run-id>` stands for the literal run id from the run context. Write the literal values in every command. Never write `$GAAL_RUN_DIR` or `$GAAL_RUN_ID` in a command, never use `$VAR`, `$(...)` or backticks, and never put `NAME=value` before a command.
- Run one command per call. Never join commands with `&&`, `;` or `|`. A `|` inside a single-quoted `jq` filter is part of that argument and is fine.
- Write files with the file-writing tool, never through shell redirection. Scratch files live in `<run-dir>/scratch` (create it with `mkdir -p <run-dir>/scratch`). Throwaway worktrees live in `<run-dir>/worktree`. Never use `/tmp` or `mktemp`.
- Tracker: GitHub, repo `116-Labs/cuecal`. Use `gh` for all reads and writes.
- Gates (both required), run exactly as written with nothing added: `uv run ruff check .` (gate `lint`) and `uv run pytest` (gate `test`). Preflight: none. Install: the profile names no install command, so install nothing. Use the checkout's existing install, which means gates run in the checkout itself, never in a throwaway worktree (a worktree has no install).
- Commits: `commits.convention` is conventional; `commits.attribution` is `none`, so (`attribution-policy`) no AI attribution, co-author trailer or provenance line appears in any commit message, review body or comment. Branch prefix is `gaal/`. Merge method is squash with `merge.message_source: commits`, no queue, no auto-merge. Review policy: 1 required approval, open threads do not block merge, no named reviewers, start signal is a reaction.
- Limit: `review_rounds` is 2. If two or more earlier reviews on this PR carry this skill's signature (step 5), do not post a third: write the result as `needs-human` with a `reason` naming the round limit of 2.
- Mode: post (default) or preview, from the dispatch. In preview mode post nothing, push nothing and add no reaction; still do every read, pass and gate, and put the full review text in the final message.
- Time: read with `date -u +%Y-%m-%dT%H:%M:%SZ`. Record `started_at` first thing. Time each gate by running `date -u +%s` just before and just after it, as separate commands; `duration_ms` is the difference times 1000.
- Every exit path, including every failure, goes through step 17 (`run-result-written`). On any failure, stop doing work, restore the checkout (step 16) and go straight to step 17.

## Steps

1. **Start and identify.** Record `started_at`. Take `repo` and the PR number from the dispatch. If no PR number can be determined, end as `needs-clarification` with a question asking for it. Record the authenticated login with `gh api user --jq .login`. Record the checkout's starting point with `git rev-parse HEAD` and `git rev-parse --abbrev-ref HEAD`, and its dirty paths with `git status --porcelain` (those paths are never yours to stage or revert, `explicit-staging`, `commit-foreign-edits`). Never work on or push to `main` (`base-untouched`).

2. **Read PR metadata, not the description.** Run `gh pr view <N> --repo 116-Labs/cuecal --json number,state,baseRefName,headRefName,headRefOid,isCrossRepository,author,files,commits,closingIssuesReferences`. Never request the `body` field here (`description-last`, `description-sets-scope`). If `state` is not `OPEN`, end as `failed` with a reason naming this step. Any API error, auth expiry or rate limit stops the run as `failed`; it never becomes "no PR" or "no threads" (`fail-closed-reads`). Note whether the branch is a fork (`isCrossRepository`) and whether every commit was authored by the login from step 1.

3. **Find the linked issues without reading the description.** Use the issue-link rule. First take `closingIssuesReferences` (these links are closing). If it is empty, extract only issue numbers from the body with a filter that emits digits only, for example `gh pr view <N> --repo 116-Labs/cuecal --json body --jq '.body | [scan("(?im)^\\s*(?:closes|fixes|resolves|refs)\\s+#(\\d+)")]'`, then do the same over each commit message (`--json commits`). A line opening with a closing keyword counts before a `Refs #N` line; every such link counts; an issue named in the dispatch takes precedence. Record each link as closing (`Closes`/`Fixes`/`Resolves`) or plain (`Refs`). Do not read or quote description text. If no issue is linked, end as `needs-clarification` asking which issue the PR is for. Read each issue with `gh issue view <M> --repo 116-Labs/cuecal --json title,body,state,comments` and write down its acceptance criteria, worded as the issue words them; read comments that start with `**Clarification` as part of the criteria. A PR linking several issues is judged against all of them. If an issue has no checkable acceptance criteria, end as `needs-clarification` with `questions` saying what is missing.

4. **Start signal (post mode only).** Add the reaction: `gh api repos/116-Labs/cuecal/issues/<N>/reactions --raw-field content=eyes`. A failure here is noted in the report but does not stop the review.

5. **Prior reviews and threads.** List reviews with `gh api repos/116-Labs/cuecal/pulls/<N>/reviews --paginate`, and review threads by writing a GraphQL query (`reviewThreads` with `id`, `isResolved`, and each thread's first-comment `author.login`, `body`, `path`, `line`, with `pageInfo { hasNextPage endCursor }` and an `$endCursor` variable) to `<run-dir>/scratch/threads.graphql` and running `gh api graphql --paginate --field query=@<run-dir>/scratch/threads.graphql --field owner=116-Labs --field name=cuecal --field number=<N>`. Every listing is paginated to the end or the run stops (`complete-listings`). This skill's signature is the line `gaal review-pr · run <run-id>` in review bodies and the marker `<!-- gaal-review-pr -->` in inline comments. Count earlier reviews carrying the signature (round limit above), record the last one's `commit_id` as the previous reviewed head, and record the threads whose first comment carries the marker as "threads this review opened". Do not touch any other thread.

6. **Check out the head as fetched from the remote.** If `git status --porcelain` shows edits to files the PR touches, stop as `failed` (uncommitted edits of unknown origin). Run `git fetch origin pull/<N>/head`, then `git rev-parse FETCH_HEAD` and confirm it equals `headRefOid`; if not, re-read the metadata once, and if it still differs end as `failed`. Then `git switch --detach <headRefOid>`; if the switch fails, end as `failed`. Create `<run-dir>/scratch` and start a manifest file `<run-dir>/scratch/manifest.txt` listing the paths this run writes (empty for now). Do not install anything.

7. **Delta on a re-review.** If a previous reviewed head exists, limit attention to the delta since it. If it is an ancestor of the head, use `git diff <prev>..<head>`; if history was rewritten, use `git range-diff <base>...<prev> <base>...<head>` after fetching the old sha. Say in the review which earlier threads this delta answered. Otherwise review the whole diff against `baseRefName` (`git diff origin/<base>...<head>`, fetching the base first).

8. **Correctness pass.** Read the diff for logic errors, edge cases, error handling, concurrency, state handling (SQLite state, keyring secrets, config) and security. Scripts, workflows and skill files are code. Do this before reading the description.

9. **Run every gate.** For each gate in order (`lint`, then `test`): run `date -u +%s`, run the gate command exactly (`uv run ruff check .`, then `uv run pytest`), run `date -u +%s`, and record `name`, `command`, `exit_code` and `duration_ms`. There is no preflight. A required gate that fails on the head is a Blocking finding quoting its output briefly. A gate that did not run is absent from the result, never passed (`truthful-report`). A command's failure is never hidden by a pipe or filter (`status-preserved`).

10. **Only now read the description.** Run `gh pr view <N> --repo 116-Labs/cuecal --json body`. Treat it as a set of claims to test (`description-last`). It can add findings; it can never remove one (`description-drops-finding`) and never limits what was reviewed, including a "focus" section (`description-sets-scope`). Note its **Deferred** list, if any, and whether its claims about the change are accurate (description-accuracy note for the report).

11. **Verify, then walk the criteria.** Check every candidate finding at its exact file and line on the reviewed head; drop anything that does not reproduce (`findings-verified`). Walk every acceptance criterion of every linked issue: met, unmet or deferred. A criterion is deferred only when its link is plain (`Refs`) and the Deferred list names it. A Deferred entry that is not one of the issue's criteria is a Secondary finding. Deferral moves a criterion out of this PR's bar but it is still checked and listed as deferred, never as met; it never drops a correctness or gate finding, and it changes nothing under a closing keyword.

12. **Sort and choose the verdict.** Buckets: **Blocking** (an unmet, non-deferred criterion; a failing required gate; a verified correctness, security or data-loss defect; a Deferred list under a closing keyword, since merging would close the issue with criteria open), **Secondary**, **Nits**, **Pre-existing** (defects not introduced by the PR; they never open threads, but a PR that makes a defect reachable owns it). Verdict (`verdict-follows-findings`): at least one Blocking → request changes; none → approve (nits may remain); undecidable → comment. The review states the rule applied. If the authenticated login authored the PR or any of its commits, or this run pushes a fix to it, the verdict posted is `comment` with the intended verdict as the first line, never approve or request changes (`no-self-verdict`, `second-identity-approval`); the run then ends `needs-human`. There is no second identity: if an approval or request is refused, repost as `comment` and never retry under another identity.

13. **Optional small fixes.** Only when the branch is not a fork and every commit on it was authored by the authenticated login (`rewrite-foreign-branch`), and not in preview mode. Non-behavioural fixes (typos, comments, docs, formatting, dead code) always qualify. A behavioural fix qualifies only if it is in a file the PR touches, has exactly one reasonable form, and comes with a test that fails without it; when in doubt it goes to the author as a finding. Never propose behaviour changes as one-click suggestion blocks (`behavioral-suggestion`); a suggestion block is allowed only for a non-behavioural change this run could not push. For a fix:
   1. Record the restore point (`git rev-parse HEAD`) and the exact paths you change in `<run-dir>/scratch/manifest.txt`; exclude paths that were already dirty.
   2. Edit with the file tools, rerun both gates as in step 9, and if either fails revert only the manifest paths with `git checkout <restore-point> -- <path>` and drop the fix.
   3. Stage by explicit path (`git add <path>`; never `git add -A`, `git add .` or `git commit -a`, `explicit-staging`). Write a conventional message (for example `fix: ...`) to `<run-dir>/scratch/fix-msg.txt` and commit with `git commit -F <run-dir>/scratch/fix-msg.txt`. If a hook rejects the commit or push, fix what it reports; if that is beyond this run, end as `failed` naming the hook and quoting its output briefly (`bypass-hook`).
   4. Before pushing, run `git fetch origin <headRefName>` and `git merge-base --is-ancestor <remote-head> HEAD`. If the remote head moved and is not an ancestor, abandon the auto-fix entirely and revert only the manifest paths; any push would drop the author's commits.
   5. Fast-forward push: `git push origin HEAD:refs/heads/<headRefName>`. No force.
   6. A fixed item goes in the "Fixed in" list and never also as an inline finding (`fixed-not-flagged`).

14. **Collapse (PR mode, only after a fix was pushed).** Collapse only if the review pushed a fix, there are zero Blocking findings, `merge.message_source` is `commits`, and the branch is not a fork and has no commit authored by someone else (hard gates, never overridden); otherwise skip and say why. If the branch is already one commit ahead of the merge base, nothing to do. Soft gates: an existing approval would be dismissed (an unreadable setting counts as yes) and unresolved threads exist; print the thread count and say in the report that the review overrode them. Collapse before anchors are computed and before the review is posted (`collapse-before-approve`). Procedure, in a throwaway worktree, never the checkout:
   1. Read the remote head with `git ls-remote origin refs/heads/<headRefName>` and confirm it equals the pushed sha.
   2. `git worktree add --detach <run-dir>/worktree <pushed-sha>`, then `cd <run-dir>/worktree`.
   3. Note the tree hash with `git rev-parse HEAD^{tree}`, then `git reset --soft <merge-base>` and write the whole-change conventional message (process commits dropped, no attribution) to `<run-dir>/scratch/collapse-msg.txt`; commit with `git commit -F <run-dir>/scratch/collapse-msg.txt`. If the rewrite nets to an empty change, restore and stop. If the new tree hash differs from the noted one, abort before pushing.
   4. Push with an explicit lease: `git push --force-with-lease=<headRefName>:<pushed-sha> origin HEAD:refs/heads/<headRefName>`. On failure, restore the previous HEAD. Never use an interactive rebase.
   5. On every exit path, `git worktree remove --force <run-dir>/worktree`.
   6. Record mode (PR mode), regime, commit count before and after, gates that fired, tree hash, old → new sha, and say that any stale checkout must be hard-reset to the remote, never pulled.
   After a collapse, "Fixed in `<sha>`" names the new sha, and only if that sha contains the fix (`truthful-report`).

15. **Compute anchors, then post one review (post mode).** Anchors come from the right-hand side of the post-push patch hunks: run `gh pr diff <N> --repo 116-Labs/cuecal --patch` after any push or collapse, never before (`collapse-before-approve`). After one anchoring failure, re-fetch and re-anchor once, then fall back to a body-only review. Open inline threads for Blocking and Secondary findings on a first review; on a re-review only Blocking findings open new threads, otherwise the loop never converges. Nits and Pre-existing go in the body only. Every inline comment carries `<!-- gaal-review-pr -->`. Write the review body with the file tool to `<run-dir>/scratch/review.md`, in this order: the verdict as the first line; the rule applied; findings by bucket; acceptance-criteria results per issue (met, unmet, deferred, with deferred ones listed as deferred, not met); the "Fixed in `<sha>`" list (omit if nothing was pushed); the description-accuracy note; the reviewed head sha (the `headRefOid` from step 2) and the signature line `gaal review-pr · run <run-id>` (`signed-review`). Post once: with inline comments, write the JSON payload (`commit_id` = the current remote head, `event`, `body`, `comments` with `path`, `line`, `side: RIGHT`) to `<run-dir>/scratch/review.json` and run `gh api repos/116-Labs/cuecal/pulls/<N>/reviews --method POST --input <run-dir>/scratch/review.json`; body-only, run `gh pr review <N> --repo 116-Labs/cuecal --comment --body-file <run-dir>/scratch/review.md` (or `--approve` / `--request-changes` when the verdict allows). Event values: `APPROVE`, `REQUEST_CHANGES`, `COMMENT`. If posting fails, retry once as a body-only review; if that fails too, end as `failed` naming this step. Never post a second review. Then, for threads this review opened in an earlier round and that the delta verifiably answered at the current head, reply and resolve with GraphQL mutations written to files in `<run-dir>/scratch` (`addPullRequestReviewThreadReply`, then `resolveReviewThread`, passing the thread id with `--field id=<id>`). Resolve only those, each after a reply (`resolve-own-threads-only`); never resolve a thread to clear the merge path (`resolve-to-unblock`), and never resolve other people's threads. In preview mode, skip every write in this step and print the review instead.

16. **Restore the checkout.** Remove any leftover worktree (`git worktree remove --force <run-dir>/worktree`). Return to the starting point from step 1 with `git switch <branch>`, or `git switch --detach <sha>` if the checkout was detached. Do not modify hook configuration at any point.

17. **Write the run result (every exit path).** Take the finish time with `date -u +%Y-%m-%dT%H:%M:%SZ`. With the file tool write `<run-dir>/result.json.tmp`, then `mv <run-dir>/result.json.tmp <run-dir>/result.json`; never leave the `.tmp` file behind. Content, valid against the run-result schema:
   - `schema_version`: 1; `run_id`: the literal run id; `blueprint`: `review-pr`; `blueprint_version`: `1.2.0`; `repo`: `116-Labs/cuecal`.
   - `issue`: the first linked issue number, or null; `pr`: the PR number, or null if none was determined.
   - `status`: one of the exit states below; `attempts`: 1.
   - `reason`: required unless `done`; one sentence of at most 160 characters naming the decision or action needed (detail belongs in the review and final message).
   - `questions`: required and non-empty for `needs-clarification`.
   - `gates`: every gate run that actually happened, each with `name`, `command`, `exit_code`, `duration_ms`; an empty array if none ran.
   - `branch`: the PR head branch, or null; `commit_sha`: the 40-character sha of the fix or collapsed head this run pushed, else null.
   - `review`: `verdict` (`approve`, `request-changes` or `comment` as posted), `blocking` (count) and `non_blocking` (Secondary plus Nits); required when `done`, and included whenever a review was posted.
   - `started_at` and `finished_at`: ISO 8601 UTC timestamps.
   Then give a final message with: the verdict, bucket counts, acceptance-criteria results, the description-accuracy note, the thread ledger (which threads were opened, replied to, resolved or left), and the push or collapse outcome with old → new sha (or "none").

## Exit states

- `done`: The review is posted (in preview mode, composed and printed) and nothing needs a person beyond normal merge. `review` carries the verdict and counts.
- `needs-human`: Threads are left for the author (expected whenever Blocking > 0), or the verdict was downgraded to `comment` because the authenticated identity wrote or pushed the change, or the round limit of 2 was reached. `reason` summarizes.
- `needs-clarification`: No PR could be determined, the PR links no issue by the issue-link rule, or a linked issue has no checkable acceptance criteria. `questions` say what is missing.
- `failed`: The PR is not open, an API read or write failed in a way that cannot be trusted (`fail-closed-reads`), the checkout could not be switched, a hook rejected a commit or push this run could not fix, or posting failed even after falling back to a body-only review. `reason` names the step.

## Invariants

- `description-last`: The PR description is read only after the correctness pass, the gates and the acceptance-criteria work have produced findings (steps 2, 3, 8–10).
- `verdict-follows-findings`: Request changes if there is at least one Blocking finding, approve if none, comment when undecidable; the review states the rule applied.
- `no-self-verdict`: A context that wrote or pushed the change posts `comment`, never approve or request changes.
- `findings-verified`: Every posted finding was reproduced at its line against the reviewed head.
- `signed-review`: The review body names the reviewed head sha and carries the signature line.
- `fixed-not-flagged`: A fix pushed by the review appears in the "Fixed in" list and never also as an inline finding.
- `resolve-own-threads-only`: Only threads opened by this review are resolved, each after a reply.
- `collapse-before-approve`: Any collapse happens before anchors are computed and before the review is posted.
- `explicit-staging`: Stage only paths this run wrote, taken from the manifest; never stage everything wholesale; a person's in-progress edits may be in the checkout.
- `base-untouched`: Never commit or push to `main`.
- `fail-closed-reads`: Errors, auth expiry and rate limits stop the run; they never become "no PR", "no threads" or "no checks".
- `complete-listings`: Every listing of threads, reviews, comments or checks is paginated to the end or the run stops.
- `truthful-report`: The report and result describe what actually happened; a gate that did not run is absent; "Fixed in `<sha>`" appears only when that sha contains the fix.
- `status-preserved`: A command's success or failure is never lost to a pipe, filter or guard.
- `attribution-policy`: Commit messages and review text follow `commits.attribution: none` exactly; nothing is added or dropped on the agent's own initiative.
- `run-result-written`: `result.json` is written atomically on every exit path (step 17).

## Forbidden actions

- `description-sets-scope`: Letting the description or its focus section limit what is reviewed.
- `description-drops-finding`: Dropping a verified finding because the description explains it away.
- `second-identity-approval`: Approving through another identity, or retrying a refused approval under a different one.
- `rewrite-foreign-branch`: Pushing to or rewriting a fork's branch or commits authored by someone else.
- `resolve-to-unblock`: Resolving threads to clear the merge path.
- `behavioral-suggestion`: Proposing behaviour changes as one-click suggestion blocks; they go to the author as findings.
- `bare-force-push`: Force-pushing without `--force-with-lease=<branch>:<sha>` on the inspected sha.
- `admin-bypass`: Merging, pushing or rewriting with admin privileges to get around protection or a hook; this skill never merges.
- `bypass-hook`: Skipping or redirecting verification (`--no-verify`, `git commit -n`, `--no-gpg-sign`, any change to where git looks for hooks, switching a hook manager off) or retrying a rejected commit or push through another route.
- `machine-specific-paths`: Hard-coding a person's home directory, private scripts or services.
- `commit-foreign-edits`: Committing changes this run did not make.
