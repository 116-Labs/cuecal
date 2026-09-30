---
name: gaal-revise-pr
description: Revises an open pull request in 116-Labs/cuecal after review. It answers every unresolved review thread with a code fix or a reasoned reply, runs the profile gates, and pushes once per round. It then replies to threads and resolves them by rule, and asks for review again. Use it when a dispatch gives you a repo and PR number and asks for the `revise-pr` step. That includes imported feedback from another PR, a single comment URL, or free-text notes. Do not use it to open a PR, implement an issue, review a PR, or merge. If no PR can be determined, end as `needs-clarification` instead of guessing.
---
<!-- gaal-stamp blueprint=revise-pr@1.2.0 shared=1.1.0 profile=0ed21dd3bece7944 generated=2026-09-30 content=8f5f308dced4910a -->

# gaal-revise-pr

Blueprint `revise-pr` v1.2.0. Repo: `116-Labs/cuecal`. Base branch: `main`. Tracker: GitHub.

Close the review loop on an open PR. Each unresolved thread gets a code change or a reasoned reply. Push the branch once per round with green gates. Each thread ends in a state that matches what was done. Then request review again.

## Project facts used by this skill

- Gates, in order (both are `pending: true`, `required: false`):
  - `lint`: `uv run ruff check .`
  - `test`: `uv run pytest`
- Preflight commands: none.
- Branch prefix: `gaal/`.
- Commit convention: conventional. Attribution policy: `none`. Commits and PR text carry no agent, model or tool attribution and no trailers.
- Merge: squash, no merge queue, message source `commits`.
- Review: 1 required approval. Open threads do not block merge (`threads_block_merge: false`). No named reviewers. The start signal is a reaction.
- Limits: `limits.revise_rounds` = 3.
- Comms: GitHub comments are allowed.

## Inputs

- `repo` and PR number, from dispatch. If no PR can be determined, end as `needs-clarification`. Never guess.
- Optional imported feedback:
  - threads from another PR
  - a single comment URL
  - free-text notes
- `GAAL_RUN_ID` and `GAAL_RUN_DIR`.

## Steps

0. **Start.** Record `started_at` (UTC, RFC 3339). Start a gate list and a manifest, which is a list of every path this run writes. Keep a round counter at 0. Every exit path below ends at step 13.

1. **Confirm the PR is open.** Read the PR state from the GitHub API. Tell "the API says closed or merged" apart from "the call failed" (`fail-closed-reads`). An error, auth expiry or rate limit stops the run as `failed` (or `needs-human` for a permission problem). It is never read as "no PR". If the PR is closed or merged, end as `failed` with a `reason`.

2. **Check out the PR head.** Fetch the PR branch from the remote and check out exactly the fetched head. Record that sha as `inspected_sha`. Never work on `main` (`base-untouched`). Never push to `main`. Reinstall dependencies with `uv sync` only if `uv.lock` differs from the last install and `pyproject.toml` exists. `preflight` is empty, so there is nothing else to run first. If the checkout has uncommitted changes you did not make, stop as `needs-human` (`commit-foreign-edits`).

3. **List every unresolved review thread.** Use the GitHub GraphQL `reviewThreads` connection on the PR. It exposes `id`, `isResolved`, `isOutdated` and the comments. Follow `pageInfo.hasNextPage` and `endCursor` until the end for the threads and for each thread's comments. If any page fails, or the listing cannot be completed, stop. Never work from truncated data (`complete-listings`, `fail-closed-reads`). Record every thread id now, before any history rewrite, because rewriting history marks threads outdated. Tag each item with its source: this PR or an import.

4. **Re-verify imported items.** For an import, check the shape first. A comment URL can point at an issue-level comment, which has no thread and no thread id. Treat it as a plain comment. Then reproduce the finding on this branch and classify it as reproduces, partly applies, or does not apply. Never apply a finding that does not reproduce here (`apply-unreproduced-import`). If a reviewer's request is so ambiguous that any fix would be a guess, collect the questions (quoting the thread) and end as `needs-clarification`.

5. **Decide each item.** Choose exactly one:
   - **fix**: change the code.
   - **answer**: a question or explanation needs no change.
   - **defer**: a follow-up issue in this repo, filed first, whose number you can name. It counts as agreed only when the reviewer has agreed on the thread. A deferral with no issue number is a pushback in disguise (`resolve-unagreed-deferral`).
   - **push back**: disagree, with reasons.

   An import that does not apply or does not reproduce is an answer that explains why. Imported items you fix still land only on this PR's branch (`target-branch-only`).

6. **Make all fixes.** Edit files for every **fix** item. Add each written path to the manifest. Do not change files unrelated to the threads. Keep domain-specific changes in line with the repo's existing code.

7. **Run every profile gate.** Increment the round counter for each full pass. A pass runs `lint` (`uv run ruff check .`) and `test` (`uv run pytest`) in that order, measuring each command's exit code and duration.
   - Both gates are pending, so skip one only while its tool or manifest does not exist yet (for example, no `pyproject.toml` or no `uv`). Say so in the report. A skipped gate is absent from the result, not passed. If a gate is runnable on this tree, it must exit 0 (`gates-green-before-push`).
   - On a failure, fix the cause, add the paths to the manifest, and run the whole pass again.
   - If a gate was already red on the base before your change, report it as pre-existing.
   - If the round counter reaches 3 (`limits.revise_rounds`) and a runnable gate is still red, do not push. End as `needs-human` (`bounded-rounds`, `push-red`).
   - If nothing needed changing (every item is an answer, pushback or non-applying import), skip steps 7 and 8. The head stays `inspected_sha`, and `gates` may be empty.

8. **Commit once and push once.**
   - Stage by explicit path from the manifest, one `git add -- <path>` per file. Never stage wholesale, and never use commit-all (`explicit-staging`). Check `git status` shows no other changes this run is responsible for.
   - Make one fixup commit with a conventional message, for example `fix: address review feedback on <topic>`. Follow `commits.attribution: none`, so add no attribution lines (`attribution-policy`).
   - Push once with a plain `git push origin HEAD:<branch>`, after all fixes and green gates (`one-push-per-round`, `piecemeal-push`). Check the push's exit status. A failed push is `failed`. A rejection from a moved remote, a conflict or a permission problem is `needs-human` (`status-preserved`). Do not skip hooks. Do not push to `main`.
   - Say in the report that this push may dismiss the existing approval.

9. **Collapse only on the final round.** The fix push must land first, because the collapse reads the remote head. Collapse when both hold:
   - every thread on this PR will be resolved after the replies, meaning there are no pushbacks and no unagreed deferrals (`collapse-with-open-threads`), and
   - `merge.message_source` is `commits` (it is).

   Otherwise keep the fixup commit separate so the reviewer can diff only the delta. Run the shared collapse routine in **PR mode**. Declare the mode explicitly. Never infer it from the existence of a PR.
   1. Idempotence: if the branch is zero or one commit ahead of the merge base, do nothing.
   2. Read the head sha from the remote. Check that it equals the sha just pushed. Rewrite in a throwaway detached worktree, never in your checkout.
   3. Soft gates: unresolved threads exist (print the count) and an existing approval would be dismissed (an unreadable setting counts as yes). Override both knowingly, because the threads just fixed resolve after the push, and say so in the report.
   4. Hard gates, never overridden: the branch lives on a fork, or any commit on it has another author, or the remote head is not an ancestor of what will be pushed. If one applies, end as `failed` with the reason (the collapse refused). Do not push a partial collapse.
   5. Divergent local checkout: back up local-only commits to a permanent `gaal/` branch ref, verify the backup, then reset. Uncommitted edits of unknown origin stop the collapse for a human.
   6. Build one commit with the same tree. The tree hash after committing must equal the pre-collapse tree hash, or abort before pushing. If the rewrite nets to empty, restore and stop. Write one conventional message for the whole change. Drop process commits (such as "wip" or "fix lint"). Follow `attribution: none`. Never use an interactive rebase.
   7. Push with `git push --force-with-lease=<branch>:<inspected-remote-sha> origin <new-sha>:<branch>`, where the sha is the remote head you inspected. On failure, restore the previous HEAD. Remove only the throwaway worktree, on every exit path.
   8. Afterwards, hard-reset the local checkout to the remote (`git fetch` then `git reset --hard origin/<branch>`). Never pull after a collapse (`pull-after-collapse`). Tell the user any other stale checkout needs the same hard reset.
   9. Report the mode, regime, commit counts before and after, gates that fired, tree hash, old and new sha, backup refs in full, and the reset each stale checkout needs.

   Set `commit_sha` to the head on the remote after this step.

10. **Reply to every thread** (`every-thread-answered`). Reply through the thread's reply relation (GraphQL `addPullRequestReviewThreadReply` with the thread id from step 3). That works on outdated threads. Each reply must say what was actually done (`reply-matches-action`):
    - **fix**: name the sha that contains the fix. Use the final head after any collapse, and check that sha really contains the change. For an imported fix, say which branch it landed on.
    - **answer**: give the explanation.
    - **defer**: name the follow-up issue number. File the issue first, unassigned to any milestone.
    - **push back**: give the reasons.
    - **import that did not apply or reproduce**: give the reason, and reply on its source thread where one exists. Free-text notes have no thread, so put them in the report.

    If a reply fails, retry it once. If it still fails, stop as `needs-human` instead of dropping it.

11. **Resolve threads by rule** (`resolve-by-rule`). Resolve a thread (GraphQL `resolveReviewThread`) only if it was fixed, is outdated, or was deferred with the reviewer's agreement recorded on the thread. Leave pushbacks open (`resolve-pushback`). Leave deferrals that only you decided open too (`resolve-unagreed-deferral`). Because `threads_block_merge` is false, an open pushback does not block merge, but it still stays open for the reviewer. Failing to resolve another PR's thread because of permissions is not a blocker. The reply is what matters. Note it in the report.

12. **Request review again.** The profile names no reviewers, and the start signal is a reaction. Post one PR comment saying which round was pushed, the head sha, and that review is requested again. Leave any reaction to the reviewer. Do not name a person the profile does not list. If the commenting call fails, note it in the report and do not treat it as blocking.

13. **Write the run result.** Do this on every exit path, including failures (`run-result-written`). Write `$GAAL_RUN_DIR/result.json` atomically: write a temp file in `$GAAL_RUN_DIR`, then `mv` it over `result.json`. Check that the write and the rename succeeded. Use only what actually happened (`truthful-report`):
    - `schema_version`: `1`
    - `run_id`: the value of `$GAAL_RUN_ID`
    - `blueprint`: `"revise-pr"`, `blueprint_version`: `"1.2.0"`
    - `repo`: `"116-Labs/cuecal"`
    - `issue`: `null` unless the dispatch gave one
    - `pr`: the PR number, or `null` if none could be determined
    - `status`: one of `done`, `needs-human`, `needs-clarification`, `failed`
    - `reason`: required unless `done`. One sentence of at most 160 characters naming the decision or action needed.
    - `questions`: required and non-empty for `needs-clarification`, quoting the thread
    - `attempts`: rounds used, at least 1
    - `gates`: one entry per gate that ran, each with `name`, `command`, `exit_code` and `duration_ms`. Gates that did not run are absent. An empty list is valid.
    - `branch`: the PR branch, or `null`
    - `commit_sha`: the 40-character PR head after the run (the unchanged head if nothing was pushed), or `null` if unknown
    - `started_at` and `finished_at`: RFC 3339 timestamps with a `Z` or offset

    Example for a successful run:

    ```json
    {
      "schema_version": 1,
      "run_id": "<value of GAAL_RUN_ID>",
      "blueprint": "revise-pr",
      "blueprint_version": "1.2.0",
      "repo": "116-Labs/cuecal",
      "issue": null,
      "pr": 42,
      "status": "done",
      "attempts": 1,
      "gates": [
        {"name": "lint", "command": "uv run ruff check .", "exit_code": 0, "duration_ms": 1200},
        {"name": "test", "command": "uv run pytest", "exit_code": 0, "duration_ms": 8400}
      ],
      "branch": "gaal/example",
      "commit_sha": "0123456789abcdef0123456789abcdef01234567",
      "started_at": "2026-01-01T00:00:00Z",
      "finished_at": "2026-01-01T00:05:00Z"
    }
    ```

    The final message repeats the report: one row per item (source, decision, sha or issue), the gates that ran or were skipped, the collapse report if any, and open pushbacks.

## Exit states

- `done`: Every thread is answered and the branch is pushed with green gates. `commit_sha` is the PR head after the run. If nothing needed changing, it is the unchanged head, nothing was pushed, and `gates` may be empty. Open pushbacks are normal and are listed.
- `needs-clarification`: No PR could be determined, or a reviewer's request is ambiguous enough that any fix would be a guess. `questions` quote the thread.
- `needs-human`: The round limit of 3 was reached with red gates, or a conflict or permission problem blocks the push. `reason` names it.
- `failed`: The PR is not open, the push failed, or the collapse refused. `reason` names the step. Gates that were already red on the base are reported as pre-existing.

## Invariants

- `every-thread-answered`: Every thread unresolved at the start has a reply at the end, including imports that did not apply.
- `one-push-per-round`: Push once per round, after all fixes.
- `gates-green-before-push`: Every runnable gate exited 0 on the pushed tree. A pending gate is skipped only while its tool or manifest does not exist, and the report says so.
- `reply-matches-action`: Each reply names a sha that contains the fix, an issue number for a deferral, or reasons for a pushback.
- `resolve-by-rule`: Resolve only fixed, outdated, or agreed-deferral threads.
- `target-branch-only`: Code changes land only on this PR's branch. An imported fix's reply says where it landed.
- `bounded-rounds`: Gate-fix cycles stop at 3 (`limits.revise_rounds`) and end as `needs-human`.
- `explicit-staging`: Stage only manifest paths by name. Never stage wholesale.
- `base-untouched`: Never commit or push to `main`.
- `fail-closed-reads`: An API error, auth expiry or rate limit stops the run. It is never read as "no PR", "no threads" or "no checks".
- `complete-listings`: Threads, comments, reviews and checks are paginated to the end or the run stops.
- `truthful-report`: The report and result describe what happened. A gate that did not run is absent. "Fixed in `<sha>`" appears only when that sha contains the fix.
- `status-preserved`: A push, gate or API write failure is never lost to a pipe, filter or guard.
- `attribution-policy`: Follow `commits.attribution: none` exactly. Add no attribution to commits or PR text, and drop none the policy requires.
- `run-result-written`: `result.json` is written atomically on every exit path.

## Forbidden actions

- `push-red`: Pushing with a failing runnable gate to clear comments.
- `piecemeal-push`: Pushing once per comment instead of once per round.
- `resolve-pushback`: Resolving a thread where the revision disagreed with the reviewer.
- `resolve-unagreed-deferral`: Resolving a deferral only you decided on. A deferral without an issue number is a pushback.
- `apply-unreproduced-import`: Applying an imported finding that does not reproduce on this branch.
- `collapse-with-open-threads`: Collapsing while any thread on this PR will stay open.
- `pull-after-collapse`: Pulling into a checkout after a collapse. Hard-reset it to the remote.
- `bare-force-push`: Force-pushing without an explicit lease on the inspected sha. Use `--force-with-lease=<branch>:<sha>` only.
- `admin-bypass`: Merging, pushing or rewriting with admin privileges, or skipping hooks, to get around branch protection or verification.
- `machine-specific-paths`: Hard-coding a person's home directory, private scripts or services. Read them from the profile.
- `commit-foreign-edits`: Committing changes this run did not make.
