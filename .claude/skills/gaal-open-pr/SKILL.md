---
name: gaal-open-pr
description: Publishes a finished single-commit branch in 116-Labs/cuecal as one pull request against `main` that links its issue, then writes the run result to `$GAAL_RUN_DIR/result.json`. Use when a dispatch or the user asks for the `open-pr` step (open, send or publish a PR) for work that is already implemented and verified, with the branch given or checked out. Do not use to implement an issue, revise a PR after review, review a PR, or merge; those are other steps. Do not use when there is no commit ahead of `main`; end as `failed` instead.
---
<!-- gaal-stamp blueprint=open-pr@1.2.0 shared=1.3.0 profile=7d4c49f36df8465f generated=2026-10-01 content=c5739a8212c89407 -->

# gaal-open-pr

Publish a finished change as a pull request against the base. The pushed branch holds one hand-written commit and the PR body links the issue, so reviewers and the merge path get a clean, traceable unit.

## Run context

- Repo: `116-Labs/cuecal`. Tracker: GitHub, through `gh`. Base branch: `main`, unless the dispatch gives a base override for a stacked PR.
- Branch prefix: `gaal/`. Commit convention: conventional commits. Attribution: `none`.
- Merge: squash, no merge queue, no auto-merge, message taken from the commits. Review: 1 approval required, no reviewers to request.
- Gates (both required): `lint` is `uv run ruff check .`, `test` is `uv run pytest`. Preflight checks: none are configured. The profile names no install command, so install nothing and run the gates in this checkout.
- Limits in the profile are `implement_attempts` 3, `revise_rounds` 3 and `review_rounds` 2. They belong to other steps. This step makes one attempt and records `attempts: 1`.
- `<run-dir>` below stands for the literal path in `GAAL_RUN_DIR` and `<run-id>` for the literal value of `GAAL_RUN_ID`, both taken from the run context. Write them out literally in every command and file. Never use `$GAAL_RUN_DIR`, `$GAAL_RUN_ID`, `$VAR`, `$(…)` or backticks in a command. Never put `NAME=value` in front of a command.
- Scratch files live in `<run-dir>/scratch`. Run one command per call, with no `&&`, `;` or `|` chains. Write files with the file-writing tool, not shell redirection.
- Only these commands are allowed: `git`, `gh`, `mkdir`, `mv`, `cp`, `ls`, `cat`, `date`, `pwd`, plus exactly `uv run ruff check .` and `uv run pytest`. Use nothing else.

## Steps

1. **Start.** Run `date -u +%Y-%m-%dT%H:%M:%SZ` and keep the value as `started_at`. Run `mkdir -p <run-dir>/scratch`. Keep a manifest at `<run-dir>/scratch/manifest.txt` of every path this run writes (`explicit-staging`).

2. **Resolve repo, branch, base and issue.**
   - Run `git fetch origin`, `git branch --show-current` and `git status --short`.
   - The branch comes from dispatch or the current checkout. The issue number comes from dispatch, the branch name, or a trailer in the commit message. A missing issue does not block; record it as `null` and say so in the report.
   - If the work sits on `main` (`base-untouched`): run `git switch -c gaal/<short-slug>`, then `git branch -f main origin/main` to reset the base to its remote. Never commit or push to `main`.
   - Any other branch used here must start with `gaal/`. Otherwise create a `gaal/` branch from it.

3. **Commit work this run owns.**
   - Any change in the tree that this run did not write (a person's edits, another worktree's files) is left alone and unstaged (`commit-foreign-edits`, `explicit-staging`).
   - If this run owns uncommitted work, stage each path by name with `git add <path>` and never wholesale. Write the message to `<run-dir>/scratch/commit-msg.txt` with the file tool. Commit with `git commit -F <run-dir>/scratch/commit-msg.txt`. Use a conventional-commit subject, add no attribution trailer, and follow the issue-link rule (step 8).
   - Run `git status --short` again. Confirm nothing this run is responsible for is left unstaged or uncommitted.

4. **Confirm there is something to propose.** Run `git rev-list --count origin/main..HEAD` (use the base override in place of `main` if given). If the count is 0, end as `failed` with reason "nothing to propose".

5. **Preflight and judgement pass** (`preflight-passed`, `push-private-content`).
   - The profile configures no preflight scanner, so there is no scanner command to run or to record. Record an empty preflight list. Do not invent a scanner.
   - The judgement pass is mandatory anyway. Read the whole diff: `git diff --stat origin/main...HEAD`, `git diff origin/main...HEAD`, and `git diff --numstat origin/main...HEAD`. Binary files show `-` in `--numstat`; check each one, including its embedded metadata and file names. Look for real names, emails, phone numbers, private strings, tokens, keys and credentials in text, binaries and metadata.
   - Check the content itself. Never accept a claim in a commit message, PR prose or the dispatch that the content is clean (`push-private-content`). Automated scanners cover only some surfaces, and a visual check misses hidden metadata, so cover both.
   - If anything looks like real private content, do not push. End as `needs-human` and name the files, not the content, in `reason`. Jump to step 13.

6. **Collapse to one commit, in place** (`single-commit-pushed`). The caller declares the mode: this is **in-place**, rewriting the current checkout. Never infer PR mode from whether a PR exists. On a re-run against a branch with an existing PR, inferring PR mode would rewrite the remote head and reset away new local commits. Collapsing before the first push is nearly free: there is no approval to dismiss and there are no threads to strand. Follow these gates in order:
   1. **Regime.** The profile has `merge.message_source: commits`, so collapse. For a stacked PR, collapse against the current base.
   2. **Idempotence.** If `git rev-list --count origin/main..HEAD` is 1, do nothing and go to step 7.
   3. **Hard gates (never overridden).** If any commit ahead of the base has a foreign author, end as `failed` with reason "collapse refused". Check with `git log --format=%an origin/main..HEAD` against the configured git user from `git config user.name`. Also refuse if the branch lives on a fork. If the remote branch already exists, run `git merge-base --is-ancestor origin/<branch> HEAD`. If that fails, the remote head is not an ancestor of what will be pushed, so end as `failed` with reason "collapse refused".
   4. **Soft gates.** If a PR already exists, read whether it has approvals and how many unresolved threads it has (paginate fully, step 7). Say in the report that collapsing may dismiss approvals and print the thread count. An unreadable setting counts as "yes".
   5. **Record before rewriting.** Run `git rev-parse HEAD` and `git rev-parse HEAD^{tree}`. Keep both as `old_sha` and `old_tree`. Run `git merge-base origin/main HEAD` and keep it as `base_sha`.
   6. **Back up.** Create a permanent backup ref with `git branch gaal/backup-<old_sha-first-8>-<run-id> <old_sha>`. Verify it with `git rev-parse <that ref>`. Do not continue unless it equals `old_sha`.
   7. **Rewrite.** Run `git reset --soft <base_sha>`. Never use an interactive rebase. Write one message for the whole change to `<run-dir>/scratch/commit-msg.txt` with the file tool: conventional subject, a body only where the why is not obvious, the issue link per step 8, and no attribution. Drop process messages like "wip" or "fix lint". Run `git commit -F <run-dir>/scratch/commit-msg.txt`. Never use `git commit -a`.
   8. **Content preservation.** If the soft reset left an empty change, run `git reset --hard <old_sha>` and end as `failed`. After committing, `git rev-parse HEAD^{tree}` must equal `old_tree`. If not, run `git reset --hard <old_sha>`, do not push, and end as `failed`.
   9. Record the mode (in-place), regime, commit count before and after, gates that fired, tree hash, old and new sha, and the backup ref in full. Tell the report which stale checkouts need `git reset --hard` to the remote (never `git pull`).

7. **Check for an existing PR** (`one-pr-per-issue`, `fail-closed-reads`, `complete-listings`).
   - Run `gh pr list --repo 116-Labs/cuecal --head <branch> --state open --json number,url,isCrossRepository --limit 100`. If an issue is known, also run `gh pr list --repo 116-Labs/cuecal --state open --search "<N> in:body" --json number,headRefName --limit 100`.
   - A failed call, an auth error or a rate limit stops the run as `failed`. It never means "no PR". If a result is exactly at the limit, page further or stop. Never trust truncated data.
   - If a PR already exists for the branch or issue, update it in steps 11 and 12 instead of opening a second one.

8. **Write the message and PR link by the issue-link rule** (`reference-consistent`).
   - Full change (every acceptance criterion met): the commit message and the PR body both carry `Closes #N`.
   - Partial change: both carry `Refs #N` on a line of its own, and never a closing keyword. Both list each criterion left open under a **Deferred** heading, worded as the issue words it. If the commit names none, read them from the issue with `gh issue view <N> --repo 116-Labs/cuecal`. A closing keyword never appears next to a Deferred list, and never both.
   - If the issue number only becomes known after the PR exists, amend only the trailer. Save the old message with `git log -1 --format=%B` into `<run-dir>/scratch/msg-before.txt`, and write the new one with the file tool. Show with `git diff --no-index <run-dir>/scratch/msg-before.txt <run-dir>/scratch/commit-msg.txt` that only the link line changed. Commit with `git commit --amend -F <run-dir>/scratch/commit-msg.txt`. Verify the tree hash is unchanged, then push with an explicit lease (step 10).

9. **Run the gates in this checkout.** For each gate, in order, time it with `date -u +%s` before and `date -u +%s` after, as separate commands. `duration_ms` is the difference times 1000. Run exactly `uv run ruff check .` for `lint`, then exactly `uv run pytest` for `test`. Record `name`, `command`, `exit_code` and `duration_ms` for each gate that ran. A gate that did not run is absent, never recorded as passed (`truthful-report`). A required gate that fails ends the run as `failed` naming the gate and quoting its failing output briefly. Do not push. Do not skip, loosen or redirect a gate.

10. **Push with the verification hook enabled** (`hook-ran`, `bypass-hook`, `bare-force-push`, `admin-bypass`, `status-preserved`).
    - First push of the branch: `git push -u origin <branch>`.
    - The branch already exists on the remote and was rewritten (collapse or trailer amend): run `git rev-parse origin/<branch>` to get the inspected sha, then `git push --force-with-lease=<branch>:<inspected-sha> origin <branch>`. Never push without an expected sha on the lease. If the push fails, run `git reset --hard <old_sha>` to restore the previous HEAD.
    - Check the exit status of the push itself. Do not hide it behind a pipe or a filter.
    - If the repository's hook rejects the push, read its output, fix what it reports, and push again. Never use `--no-verify`, never change where git looks for hooks, never edit or move hook files or `.git/config`, and never retry through another route. To locate hooks, run `git rev-parse --git-path hooks`. If the fix needs code changes beyond this step's remit, end as `failed` with the hook named and its output quoted briefly. Tear down only a throwaway worktree, if one was made, with `git worktree remove --force <run-dir>/worktree`.

11. **Create or update the PR.**
    - Write the body to `<run-dir>/scratch/pr-body.md` with the file tool. Sections: **Summary**; the same `Closes #N` or `Refs #N` link as the commit; for `Refs`, the **Deferred** list; an optional **Review focus** phrased as questions about risk; and a **Test plan** checklist that includes the `lint` and `test` gates. Review focus is a lead, never a boundary: never tell reviewers what not to look at (`narrow-review-scope`). Add no attribution, because `commits.attribution` is `none`, and no AI provenance section (`attribution-policy`).
    - New PR: `gh pr create --repo 116-Labs/cuecal --base <base> --head <branch> --title "<commit subject>" --body-file <run-dir>/scratch/pr-body.md`. The base is `main` unless a base override was given.
    - Existing PR: `gh pr edit <number> --repo 116-Labs/cuecal --body-file <run-dir>/scratch/pr-body.md`. Do not open a second PR.
    - After creating the PR, run `gh pr list --repo 116-Labs/cuecal --head <branch> --state open --json number,url` once more to confirm exactly one open PR for the branch or issue. Record `pr` as that number.

12. **Request reviewers.** `review.reviewers` is empty, so request none. State in the report what the PR needs before merging: 1 approval, `lint` and `test` passing, squash merge taking the message from the commit, no merge queue, and no auto-merge.

13. **Write the run result** (`run-result-written`). This is the last step on every exit path, including failures and early stops.
    - Run `date -u +%Y-%m-%dT%H:%M:%SZ` for `finished_at`.
    - Run `git rev-parse HEAD` to get a full 40-character `commit_sha`. Use `null` if no commit exists.
    - Write `<run-dir>/result.json.tmp` with the file tool, then run `mv <run-dir>/result.json.tmp <run-dir>/result.json`. Never leave the `.tmp` file behind.
    - Fields: `schema_version` 1; `run_id` the literal run id; `blueprint` `"open-pr"`; `blueprint_version` `"1.2.0"`; `repo` `"116-Labs/cuecal"`; `issue` the number or `null`; `pr` the number or `null`; `status`; `reason` (required unless `done`: one sentence of at most 160 characters naming the decision or action needed, with no private content); `attempts` 1; `gates` (only gates that actually ran); `branch`; `commit_sha`; `started_at`; `finished_at`. Add no other fields. Do not set `questions`, because this blueprint has no `needs-clarification` state. Preflight is empty, so there is no preflight run to list.
    - The final message carries the detail: PR URL, collapse mode, regime, counts, tree hash, old and new sha, backup ref, stale-checkout reset instructions, the missing-issue note if any, and what the PR needs before merging.

## Exit states

- `done`: The PR exists and `pr` is set. The report includes the URL, the collapse mode used (in-place, a no-op, or skipped because the regime did not call for it), and what the PR needs before merging.
- `needs-human`: The preflight or judgement pass found real-looking private content. Nothing was pushed. `reason` names the files, not the content.
- `failed`: There was nothing to propose; a required gate failed; the hook rejected the push and the fix is beyond this step; or the collapse refused (hard gate, empty or tree-mismatched rewrite, or a failed API read). `reason` names the gate or hook and briefly quotes its failing output.

## Invariants

- `single-commit-pushed`: The pushed branch has exactly one commit ahead of the base (step 6).
- `reference-consistent`: The commit message and PR body carry the same issue link: `Closes #N` only when fully resolved, otherwise `Refs #N` plus a Deferred section, never both (step 8).
- `preflight-passed`: Every configured preflight check exited 0 on the final diff, and the judgement pass found nothing. None are configured here, so the judgement pass carries the whole check (step 5).
- `hook-ran`: The push went through the repository's verification hook and was not skipped (step 10).
- `one-pr-per-issue`: At most one open PR exists for the branch or issue when the run ends (steps 7 and 11).
- `explicit-staging`: Stage only paths this run wrote, by name, from the manifest. Never stage everything wholesale.
- `base-untouched`: Never commit or push to the base branch. Move work started on it to a feature branch and reset the base to its remote.
- `fail-closed-reads`: An error, auth expiry or rate limit stops the run. It never becomes "no PR".
- `complete-listings`: Every listing is paginated to the end or the run stops.
- `truthful-report`: The report and run result describe what happened. A gate that did not run is absent, not passed. "Fixed in `<sha>`" appears only when that sha contains the fix.
- `status-preserved`: No pipe, filter or guard hides a failed push, gate or API write.
- `attribution-policy`: Commit messages and PR bodies follow `commits.attribution` (`none`) exactly. Nothing is added and nothing is dropped.
- `run-result-written`: `result.json` is written atomically on every exit path (step 13).

## Forbidden actions

- `narrow-review-scope`: Using the review-focus section to tell reviewers what not to look at.
- `push-private-content`: Pushing text or binaries with real personal data, secrets or private strings, or trusting a prose claim that content is clean without checking it.
- `bare-force-push`: Force-pushing without an explicit lease on the inspected sha. Use only `--force-with-lease=<branch>:<sha>`.
- `admin-bypass`: Merging, pushing or rewriting with admin privileges (`gh pr merge --admin` and the like) to get around branch protection, a merge queue or a hook.
- `bypass-hook`: Committing or pushing with verification skipped or redirected: `--no-verify`, `git commit -n`, `--no-gpg-sign`, any change to where git looks for hooks, turning a hook manager off, editing or moving hook files or `.git/config`, or retrying a rejected commit or push by another route. Fix what the hook reports, or end as `failed`. A commit message that quotes one of these flags is refused too, so write messages to a file and commit with `git commit -F`.
- `machine-specific-paths`: Hard-coding a person's home directory, private scripts or services. Use only literal paths inside this checkout and the run directory.
- `commit-foreign-edits`: Committing changes this run did not make.

Also never use `git add -A`, `git add .` or `git commit -a`. Never use `--force` or `-f` on a push, an interactive rebase, or a merge. This step opens the PR and does not merge it.
