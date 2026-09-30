---
name: gaal-open-pr
description: Publishes a finished single-commit branch in 116-Labs/cuecal as one pull request against `main` that links its issue, then writes the run result to `$GAAL_RUN_DIR/result.json`. Use when a dispatch or the user asks for the `open-pr` step (open, send or publish a PR) for work that is already implemented and verified, with the branch given or checked out. Do not use to implement an issue, revise a PR after review, review a PR, or merge; those are other steps. Do not use when there is no commit ahead of `main`; end as `failed` instead.
---
<!-- gaal-stamp blueprint=open-pr@1.0.0 shared=1.1.0 profile=0ed21dd3bece7944 generated=2026-09-30 content=a3e4682b7a867974 -->

# gaal-open-pr

Publish a finished change as a pull request against the base. The pushed branch holds one hand-written commit and the PR body links the issue, so reviewers and the merge path get a clean, traceable unit.

## Project facts (from the profile)

- Repo `116-Labs/cuecal`, tracker GitHub, base `main`, visibility private.
- Branch prefix `gaal/`. Commits are conventional. `commits.attribution` is `none`: no trailers, no provenance section, no AI attribution in commits or PR bodies.
- Merge: squash, no merge queue, message taken from the commits (`merge.message_source: commits`), so the single-commit collapse applies.
- Review: 1 approval required, `threads_block_merge: false`, `reviewers: []` (nobody to request).
- Gates, both `required: false` and `pending: true`:
  - `lint`: `uv run ruff check .`
  - `test`: `uv run pytest`
- `preflight` is empty: no scanner commands are configured. Do not invent any.
- Limits: `implement_attempts` 3, `revise_rounds` 3, `review_rounds` 2. This step consumes none of them and never loops on them. Record `attempts` as `1` (this run).

## Inputs

- The repo, and the branch to publish (from dispatch, else the current checkout).
- Issue number, from dispatch, else the branch name, else the commit trailer. A missing issue link does not block; the report says it is missing and `issue` is `null`.
- Optional base override for stacked PRs.
- `GAAL_RUN_ID` and `GAAL_RUN_DIR`. Note the start time (UTC, ISO 8601) for `started_at`.

Keep a manifest of every path this run writes or stages (`explicit-staging`).

## Steps

1. **Resolve repo and base.** Run `git fetch origin`, then confirm the remote points at `116-Labs/cuecal`. Base is `main` unless a base override was given. If the work sits on `main` (`base-untouched`):
   1. Create a `gaal/<short-slug>` branch at the current HEAD and switch to it.
   2. Confirm the new branch holds the commits.
   3. Move the local `main` ref back to `origin/main` with `git update-ref refs/heads/main origin/main`.

   Never commit or push to `main`. If the branch name lacks the `gaal/` prefix and this run created it, use the prefix.

2. **Commit work this run owns.** If the manifest has uncommitted paths, stage each by explicit path (`git add -- <path> <path>`) and commit with a conventional message. Then check `git status`. Changes outside the manifest belong to someone else: leave them unstaged and uncommitted (`commit-foreign-edits`). Do not stage wholesale and do not commit with an auto-stage flag.

3. **Confirm there is something to propose.** Count commits with `git rev-list --count origin/main..HEAD` (use the override base if given). If zero, end as `failed` with reason "nothing to propose".

4. **Content safety (`preflight-passed`, `push-private-content`).**
   1. Run every `preflight` command from the profile on the final diff. The list is empty here, so no scanner runs. Record no preflight entries; an absent check is never reported as passed (`truthful-report`).
   2. Do the judgement pass on the actual diff and on every added or changed file, including binaries, images and file metadata. Look for real personal names, emails, phone numbers, private strings, credentials, tokens, and hidden metadata such as EXIF, document properties and embedded paths. Automated scanners cover only some surfaces and a visual check misses hidden metadata, so use tooling plus a visual check where both apply.
   3. Never accept a claim in a commit message or PR prose that content is clean. Check the content itself.
   4. If anything looks real, private or secret, stop before any push. End as `needs-human`; `reason` names the files, never the content.

5. **Run gates.** Run `uv run ruff check .` (`lint`) and `uv run pytest` (`test`) and record the exact command, exit code and duration in ms. Both are advisory in the profile (`required: false`, `pending: true`), so a failure does not by itself stop the run. Report it as-is in the PR test plan and the final message, never as a pass. If a gate cannot start (for example `uv` is missing), leave it out of `gates` and say so; do not record it as passed or invent an exit code. Never run `git push` first to "see what the hook says".

6. **Collapse in place (`single-commit-pushed`).** Run the shared collapse routine with **mode declared in-place**, targeting this checkout. Never infer the mode from whether a PR exists. On a re-run against a branch whose PR already exists, inferring PR mode would rewrite the remote head, skip the new local commits and reset them away as divergence. Collapsing before the first push is almost free: no approval to dismiss, no threads to strand. Apply the safety gates in order:
   1. **Regime.** `merge.message_source` is `commits`, so collapse. For stacked PRs, collapse against the current base.
   2. **Idempotence.** Zero or one commit ahead of the merge base: succeed without changes.
   3. **Target.** In-place. Record the pre-collapse `HEAD` sha and tree hash (`git rev-parse HEAD^{tree}`).
   4. **Soft gates**, only relevant if a PR or approvals already exist: an existing approval would be dismissed (an unreadable setting counts as yes); unresolved threads exist (always print the count). Proceed past them only when this run has already judged the collapse right, and say so in the report.
   5. **Hard gates**, never overridden: the branch lives on a fork, or any commit on it was authored by someone else; the remote head (if the branch is already pushed) is not an ancestor of the pre-collapse local tip. On a hard gate, end as `failed` naming it.
   6. **Rewrite.** Use `git reset --soft "$(git merge-base origin/main HEAD)"` and one new commit. Never use an interactive rebase.
   7. **Content preservation.** If the change nets to empty, restore the recorded HEAD and stop as `failed`. After committing, the new tree hash must equal the recorded one; otherwise restore the recorded HEAD and stop as `failed` before pushing.
   8. **Message.** Write it as a whole for the change: conventional subject (`type(scope): summary`), a short body only where the why is not obvious, drop process commits ("wip", "fix lint"), and add no attribution (`attribution-policy`). Put the issue reference in the footer (step 7).
   9. Note the collapse mode (`in-place`), regime, commit count before and after, gates that fired, tree hash, old and new sha, and any backup ref for the report.

   After this step exactly one commit is ahead of the base.

7. **Issue reference (`reference-consistent`).** Use `Closes #<N>` only if the change fully resolves the issue; otherwise `Refs #<N>`. The commit footer and the PR body carry the same keyword and number. If the issue number is unknown, omit the reference and note that in the report. If it becomes known only after the PR exists, amend just the footer, diff the commit message before and after to prove nothing else changed, then push with an explicit lease as in step 8.

8. **Push through the hook (`hook-ran`, `bypass-hook`, `bare-force-push`).**
   1. Fetch the remote branch state first. Then push with the verification hook enabled: `git push --set-upstream origin <branch>`.
   2. If the branch already exists on the remote with different history (the re-run or amended case), inspect its sha and push only with an explicit lease on it: `git push --force-with-lease=<branch>:<inspected-sha> origin <branch>`. Never force-push without the expected sha.
   3. If the hook rejects the push, read its output and fix the cause, then push again through the same route. Never skip the hook and never retry through another route. If the fix needs code changes beyond this step's remit, end as `failed`; `reason` names the hook and briefly quotes its failing output.
   4. Check the push's exit status directly (`status-preserved`); never let a pipe or filter hide a failure. If the push fails, restore the previous HEAD if the collapse moved it.

9. **One PR per issue (`one-pr-per-issue`).** Before creating anything, list open PRs for this repo with `gh`, paginated to the end (`complete-listings`), for the same head branch and for any PR whose body references the issue. Treat an API error, auth expiry or rate limit as a stop, not as "no PR" (`fail-closed-reads`). If one exists, update it (edit its body; the branch push already updated its head) and use its number. Otherwise create it. At the end, at most one open PR exists for the branch or issue.

10. **Create the PR.** Use `gh pr create` against the base with the title from the commit subject and a structured body from a file (`--body-file`):
    - `## Summary`: what changed and why, in a few lines.
    - The same `Closes #<N>` or `Refs #<N>` line as the commit.
    - `## Review focus` (optional): questions about risk, such as "does X hold when Y?". This is a lead, never a boundary (`narrow-review-scope`). Never tell reviewers what not to look at.
    - `## Test plan`: a checklist of the gate commands actually run with their real outcomes, plus any manual checks.
    - No provenance section and no AI attribution, per `commits.attribution: none`.

11. **Reviewers.** `review.reviewers` is empty, so request none. State in the report that the PR needs 1 approval, that no merge queue exists, that the merge is a squash whose message comes from the single commit, that unresolved threads do not block merge, and that `lint` and `test` are not required checks.

12. **Write the run result (last step, every exit path).** Write `$GAAL_RUN_DIR/result.json`, atomically (write a temp file in the same directory, then rename it), on success and on every failure or stop (`run-result-written`). Fields:
    - `schema_version`: `1`; `run_id`: the value of `$GAAL_RUN_ID`; `blueprint`: `open-pr`; `blueprint_version`: `1.0.0`; `repo`: `116-Labs/cuecal`.
    - `issue`: the issue number, or `null`. `pr`: the PR number, or `null` if none exists.
    - `status`: `done`, `needs-human` or `failed`. (`needs-clarification` is not an exit state of this step, and `questions` is not used.)
    - `reason`: required unless `done`; one sentence, at most 160 characters, naming the decision or action needed. Detail goes in the final message.
    - `attempts`: `1`.
    - `gates`: one object `{name, command, exit_code, duration_ms}` for each gate that actually ran (`truthful-report`); `[]` if none ran. Add no preflight entries, since none are configured.
    - `branch`: the branch name, or `null`. `commit_sha`: the full 40-character lowercase sha of the pushed commit, or `null` if nothing was pushed.
    - `started_at` and `finished_at`: UTC ISO 8601 timestamps, for example `2026-09-29T12:00:00Z`.

    Include no other properties. Then print the final message: PR URL, collapse mode and details from step 6, gate outcomes, merge requirements from step 11, and any missing issue link. "Fixed in `<sha>`" appears only when that sha contains the fix.

## Exit states

- `done`: the PR exists and `pr` is set. The report includes the URL, the collapse mode used (in-place, or no-op if already one commit) and what the PR needs before merging.
- `needs-human`: the preflight or judgement pass found real-looking private content. Nothing was pushed. `reason` names the files, not the content.
- `failed`: nothing to propose; the hook rejected the push; the collapse refused (hard gate, empty net change, or tree-hash mismatch); or an API read or write failed. `reason` names the gate or hook and briefly quotes its failing output.

## Invariants

- `single-commit-pushed`: the pushed branch has exactly one commit ahead of the base (step 6).
- `reference-consistent`: the commit and the PR body carry the same issue reference, with a closing keyword only when the issue is fully resolved (steps 7 and 10).
- `preflight-passed`: every configured `preflight` command exited 0 on the final diff (none are configured) and the judgement pass found nothing (step 4).
- `hook-ran`: the push went through the repository's verification hook, not skipped (step 8).
- `one-pr-per-issue`: at most one open PR exists for the branch or issue when the run ends (step 9).
- `explicit-staging`: stage only manifest paths, by explicit path (step 2).
- `base-untouched`: never commit or push to `main` (step 1).
- `fail-closed-reads`: a failed call is never treated as "no PR" or "no threads" (steps 9 and 6).
- `complete-listings`: listings are paginated to the end or the run stops (step 9).
- `truthful-report`: the report and result describe what happened; a gate that did not run is absent, not passed (steps 5 and 12).
- `status-preserved`: a command's success or failure is never lost to a pipe, filter or guard (step 8).
- `attribution-policy`: commits and PR bodies follow `commits.attribution: none` exactly (steps 6 and 10).
- `run-result-written`: `result.json` is written atomically on every exit path (step 12).

## Forbidden actions

- `bypass-hook`: pushing with verification disabled, or retrying a rejected push through another route.
- `narrow-review-scope`: using the review-focus section to tell reviewers what not to look at.
- `push-private-content`: pushing text or binaries containing real personal data, secrets or private strings, including trusting a claim in commit or PR prose that content is clean without checking the content.
- `bare-force-push`: force-pushing without an explicit lease on the inspected sha (`--force-with-lease=<branch>:<sha>`).
- `admin-bypass`: merging, pushing or rewriting with admin privileges to get around branch protection, a merge queue or a verification hook.
- `machine-specific-paths`: hard-coding a person's home directory, private scripts or services into commands, the PR, or the result.
- `commit-foreign-edits`: committing changes this run did not make.
