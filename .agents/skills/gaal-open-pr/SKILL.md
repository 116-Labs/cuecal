---
name: gaal-open-pr
description: Opens a pull request in 116-Labs/cuecal for a finished branch that holds one hand-written conventional commit, linked to its issue, then writes the run result to `$GAAL_RUN_DIR/result.json`. Use when a dispatch hands you a repo and a branch (or the current checkout) and asks for the `open-pr` step. It checks for private content, collapses the branch to a single commit, pushes through the repository's verification hook, and creates or updates exactly one PR against `main`. Do not use to implement an issue, revise a PR after review, review a PR, or merge; those are other steps.
---
<!-- gaal-stamp blueprint=open-pr@1.0.0 shared=1.1.0 profile=0ed21dd3bece7944 generated=2026-09-30 content=126eed2efc17da65 -->

# gaal-open-pr

Publish a finished change as a pull request against the base. The pushed branch holds one commit and the PR body links the issue, so reviewers and the merge path get a clean, traceable unit.

## Project facts

- Repository: `116-Labs/cuecal` (private). Tracker: GitHub.
- Base branch: `main`. New branches use the prefix `gaal/`.
- Commits: conventional style, one commit per PR. Attribution policy is `none`: no trailers, no provenance section, no mention of an AI agent in commits or the PR body.
- Merge: squash, no merge queue, message taken from the commits (`merge.message_source: commits`). So the single commit is the message that lands on `main`.
- Review: 1 approval required, no default reviewers listed, unresolved threads do not block merge.
- Gates: `lint` (`uv run ruff check .`) and `test` (`uv run pytest`). Both are marked `required: false` and `pending: true`. This step does not require them.
- Preflight commands: none are configured. The judgement pass in step 5 is still mandatory.
- Limits: `implement_attempts` 3, `revise_rounds` 3, `review_rounds` 2. This step consumes none of them. Do not retry a failed push or hook in a loop. Record `attempts` as 1 for this run.

## Inputs

- `repo` and the branch to publish, from dispatch or the current checkout.
- Issue number, from dispatch, the branch name, or the commit trailer. A missing issue link does not block the run. Say so in the final report.
- Optional base override for a stacked PR. Default is `main`.
- Environment: `GAAL_RUN_ID`, `GAAL_RUN_DIR`.

Record the start time (UTC, RFC 3339) now. You need it for `started_at`.

## Steps

1. **Resolve repo and base.**
   - Fetch the remote. Determine the branch to publish.
   - If the work sits on `main`, create `gaal/<short-slug>` at the current HEAD, switch to it, and move local `main` back to the remote tip with `git branch -f main origin/main`. This enforces `base-untouched`. Never commit or push to `main`.
   - Keep a manifest of the paths this run wrote.

2. **Commit work this run owns.**
   - If uncommitted changes exist, stage only the paths in your manifest, by explicit path (`explicit-staging`). Never stage everything wholesale.
   - If uncommitted changes exist that are not in your manifest, leave them alone. They belong to someone else (`commit-foreign-edits`).
   - Commit with a conventional-style message (`type(scope): summary`) and no attribution lines (`attribution-policy`).
   - Put the issue reference in the commit footer: `Closes #N` only if the issue is fully resolved by this change, otherwise `Refs #N` (`reference-consistent`).

3. **Confirm there is something to propose.**
   - Count the commits ahead of the base.
   - If there are none, end as `failed` with reason "nothing to propose". Go to step 10.

4. **Do not trust prose.**
   - Read the actual diff and file contents, not the commit or PR text. A claim that content is clean is not evidence (`push-private-content`).

5. **Preflight and judgement pass.**
   - The profile lists no preflight commands, so there is nothing to run. Do not invent any.
   - Read the whole diff yourself for what automation would miss: real personal names, emails, phone numbers, private strings, credentials or tokens, and hidden content in binaries, images and file metadata. Check both text and binary files, because a visual look misses metadata.
   - If anything looks like real private content, stop before any push (`preflight-passed`, `push-private-content`). End as `needs-human`. `reason` names the files, never the content. Nothing is pushed. Go to step 10.

6. **Collapse to one commit, in place** (`single-commit-pushed`).
   - Declare the mode explicitly as **in-place** on this checkout. Never infer it from whether a PR exists. On a re-run where a PR already exists, inferring PR mode would rewrite the remote head, skip the new local commits and reset them away as divergence.
   - Follow these gates in order:
     1. Regime: `merge.message_source` is `commits`, so the collapse applies.
     2. Idempotence: if zero or one commit is ahead of the merge base, do nothing and continue.
     3. Soft gates: if a PR already exists, count its approvals and unresolved threads. Print the thread count. Note any override in the report.
     4. Hard gates, never overridden: if the branch lives on a fork, or any commit on it was authored by someone else, refuse. If the remote head is not an ancestor of what you will push, refuse. A refusal ends the run as `failed`, naming the gate.
     5. Content preservation: record the tree hash first. Write one commit for the whole change, dropping process commits like "wip" or "fix lint". Its tree hash must equal the recorded hash. If it nets to an empty change or the hashes differ, restore the previous HEAD and end as `failed`.
   - Collapsing before the first push is nearly free: there is no approval to dismiss and no thread to strand.
   - Use non-interactive commands only. Never use an interactive rebase.
   - The message is written as a whole for the change, conventional style, with the same issue reference as step 2, and no attribution.
   - Record commits before and after, old and new sha, and the tree hash for the report.

7. **Push through the verification hook** (`hook-ran`, `bypass-hook`, `status-preserved`).
   - New branch: `git push --set-upstream origin <branch>`.
   - Existing remote branch whose head you inspected as `<sha>`: `git push --force-with-lease=<branch>:<sha> origin <branch>`. The lease must name the inspected sha. A lease without one is not acceptable (`bare-force-push`).
   - Check the exit status of the push directly. Do not pipe it through a filter that hides failures (`status-preserved`).
   - If the hook rejects the push, fix what it reports and push again through the same route. Never disable verification or try another route (`bypass-hook`, `admin-bypass`). If the fix needs code changes beyond this step's remit, end as `failed` and quote the hook output briefly in `reason`. Go to step 10.
   - The base branch must never be pushed.

8. **Ensure one PR per issue** (`one-pr-per-issue`, `fail-closed-reads`, `complete-listings`).
   - List open PRs for this branch and, if the issue is known, PRs that reference it. Paginate to the end.
   - If an API call fails, or auth or rate limits stop you, stop the run as `failed`. Never treat an error as "no PR exists".
   - If a PR already exists, update its body and keep it. Do not open a second.
   - Otherwise create it against the base (or the stacked-PR override) using the GitHub tooling available in the environment.
   - Title: the commit subject. Body sections:
     - **Summary**: what changed and why.
     - **Issue**: the same `Closes #N` or `Refs #N` as the commit (`reference-consistent`). If no issue is known, say so plainly.
     - **Review focus** (optional): questions about where the risk is. It is a lead, never a boundary. Do not tell reviewers what not to look at (`narrow-review-scope`).
     - **Test plan**: a checklist of what was actually run or should be checked. List a gate only if it actually ran (`truthful-report`).
   - Add no attribution or provenance section (`attribution-policy`).
   - If the issue number only becomes known after the PR exists, amend only the trailer. Diff the message before and after to prove nothing else changed, update the PR body to match, and push with `--force-with-lease=<branch>:<sha>` on the inspected sha.

9. **Request reviewers.**
   - `review.reviewers` is empty, so request none. State in the report that 1 approval is required before merge, that the merge method is squash with no queue, and that the message comes from the single commit.

10. **Write the run result** (`run-result-written`). Do this on every exit path, including `failed` and `needs-human`.
    - If `GAAL_RUN_DIR` is set, write `$GAAL_RUN_DIR/result.json` atomically: write to a temporary file in the same directory, then rename it into place.
    - Required fields:
      - `schema_version`: `1`
      - `run_id`: the value of `$GAAL_RUN_ID`
      - `blueprint`: `"open-pr"`
      - `blueprint_version`: `"1.0.0"`
      - `repo`: `"116-Labs/cuecal"`
      - `issue`: integer, or `null` if unknown
      - `pr`: integer if a PR exists, otherwise `null`
      - `status`: `done`, `needs-human` or `failed`
      - `attempts`: `1`
      - `gates`: array with one object per gate that actually ran (`name`, `command`, `exit_code`, `duration_ms`). Use `[]` if none ran. A gate that did not run is absent, not passed (`truthful-report`).
      - `branch`: the branch name, or `null`
      - `commit_sha`: the 40-character sha of the single pushed commit, or `null` if nothing was pushed
      - `started_at`, `finished_at`: RFC 3339 UTC timestamps
    - Add `reason` for every status except `done`: one sentence, at most 160 characters, naming the decision or action needed. Put detail in the PR or the final message.
    - Do not add fields beyond the schema. `questions` is only for `needs-clarification`, which this step does not use.
    - Then print the final report. For `done`, include the PR URL, the collapse mode used (in-place), commit count before and after, tree hash, old and new sha, and what the PR still needs before merging: 1 approval, and the commit as the squash message. If the issue link was missing, say so. If a collapse rewrote history, tell anyone with a stale checkout to hard-reset to the remote and never pull.

## Exit states

- `done`: the PR exists and `pr` is set. The report includes the URL, the collapse mode, and what the PR needs before merging.
- `needs-human`: the judgement pass found real-looking private content. Nothing was pushed. `reason` names the files, not the content.
- `failed`: there was nothing to propose, the verification hook rejected the push, the collapse refused, or a read or write to the remote failed. `reason` names the gate or hook and quotes its failing output briefly.

## Invariants

- `single-commit-pushed`: the pushed branch has exactly one commit ahead of the base.
- `reference-consistent`: the commit message and PR body carry the same issue reference. A closing keyword is used only when the issue is fully resolved.
- `preflight-passed`: every configured preflight check exited 0 on the final diff (none are configured), and the judgement pass found nothing.
- `hook-ran`: the push went through the repository's verification hook and it was not skipped.
- `one-pr-per-issue`: at most one open PR exists for the branch or issue when the run ends.
- `explicit-staging`: stage only paths this run wrote, from a manifest.
- `base-untouched`: never commit or push to `main`.
- `fail-closed-reads`: errors, auth expiry and rate limits stop the run and are never read as "nothing found".
- `complete-listings`: any listing is paginated to the end or the run stops.
- `truthful-report`: the report and result describe what actually happened. A gate that did not run is absent.
- `status-preserved`: a command's success or failure is never lost to a pipe, filter or guard.
- `attribution-policy`: commits and PR bodies follow `commits.attribution: none` exactly. Nothing is added or dropped on your own initiative.
- `run-result-written`: `result.json` is written atomically on every exit path.

## Forbidden actions

- `bypass-hook`: pushing with verification disabled, or retrying a rejected push through another route.
- `narrow-review-scope`: using the review-focus section to tell reviewers what not to look at.
- `push-private-content`: pushing text or binaries with real personal data, secrets or private strings, or trusting a prose claim that content is clean without checking it.
- `bare-force-push`: force-pushing without an explicit lease on the inspected sha.
- `admin-bypass`: merging, pushing or rewriting with admin privileges to get around branch protection or a verification hook.
- `machine-specific-paths`: hard-coding a person's home directory, private scripts or services. Read values from the profile and environment.
- `commit-foreign-edits`: committing changes this run did not make.
