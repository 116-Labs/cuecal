---
name: gaal-open-pr
description: Publishes a finished single-commit branch in 116-Labs/cuecal as one pull request against `main` that links its issue, then writes the run result to `$GAAL_RUN_DIR/result.json`. Use when a dispatch or the user asks for the `open-pr` step (open, send or publish a PR) for work that is already implemented and verified, with the branch given or checked out. Do not use to implement an issue, revise a PR after review, review a PR, or merge; those are other steps. Do not use when there is no commit ahead of `main`; end as `failed` instead.
---
<!-- gaal-stamp blueprint=open-pr@1.2.0 shared=1.3.0 profile=7d4c49f36df8465f generated=2026-10-01 content=9b5f441a9ae8f5ef -->

# gaal-open-pr

Publish a finished change as a pull request against the base. The pushed branch holds one hand-written commit and the PR body links the issue, so reviewers and the merge path get a clean, traceable unit.

## Run context

- Repo: `116-Labs/cuecal`. Base: `main` unless the dispatch gives a base override for a stacked PR.
- Branch prefix: `gaal/`. Commit convention: conventional commits. Attribution policy (`commits.attribution`): `none`.
- Merge: squash, no queue, `message_source: commits`, auto-merge off. Review: 1 required approval, no reviewers to request, threads do not block merge.
- Tracker: GitHub, through `gh`.
- Take the run id and the run directory from the run context (the values of `GAAL_RUN_ID` and `GAAL_RUN_DIR`). Below, `<run-dir>` stands for the literal run-directory path from the run context. Write that literal path in every command. Never expand an environment variable in a command and never put `NAME=value` in front of one.
- Attempt limits in the profile: implement 3 attempts, revise 3 rounds, review 2 rounds. This step consumes none of them, so it records `attempts` as 1.
- Run one command per call. No `&&`, `;` or `|` chains. Read every command's exit status and handle a failure (`status-preserved`).
- Scratch files go in `<run-dir>/scratch`. Write files with the file-editing tool, not shell redirection.
- Install nothing: the profile names no `install` command. Run the gates in this checkout, where the dependencies already are.

## Steps

1. **Start the clock and resolve repo and base.**
   - Run `date -u +%Y-%m-%dT%H:%M:%SZ` and keep the output as `started_at`.
   - Run `mkdir -p <run-dir>/scratch`.
   - Run `git fetch origin`. A failed fetch stops the run as `failed` (`fail-closed-reads`).
   - Run `git branch --show-current`. If the branch is the base (`base-untouched`):
     - Run `git switch -c gaal/<short-slug>`, naming it for the change.
     - Run `git branch -f main origin/main` to reset the local base to its remote.
     - Never commit or push to the base.
   - Find the issue number, in this order: the dispatch, the branch name, a `Closes #N` or `Refs #N` line in `git log -1 --format=%B`. A missing issue link does not block. Record `issue` as null and say so in the report.

2. **Commit work this run owns.**
   - Run `git status --porcelain`.
   - Keep a manifest of the paths this run wrote. Stage only those, one explicit path at a time with `git add <path>` (`explicit-staging`).
   - Never stage everything wholesale. Other worktrees and a person's in-progress edits may be in this checkout. Never commit changes this run did not make (`commit-foreign-edits`).
   - Write the commit message to `<run-dir>/scratch/commit-msg.txt` with the file tool, and commit with `git commit -F <run-dir>/scratch/commit-msg.txt`.
   - Follow the conventional-commit convention. Add no trailer, no provenance line and no tool credit (`attribution-policy`, `none`).
   - If a commit hook rejects the commit, fix what it reports and commit again (`bypass-hook`).

3. **Confirm there is something to propose.**
   - Run `git rev-list --count origin/main..HEAD`, using the stacked base instead of `origin/main` if one was given.
   - If the count is 0, end as `failed` with reason "nothing to propose" (go to step 11).

4. **Preflight and judgement pass** (`preflight-passed`, `push-private-content`).
   - The profile names no preflight commands, so there is nothing to run. Do not invent a scanner. The judgement pass is therefore the whole check, and it is mandatory.
   - Read the full diff with `git diff origin/main...HEAD`. Run `git diff --numstat origin/main...HEAD` to find binary files (shown as `-`), and read the commit messages with `git log --format=%B origin/main..HEAD`.
   - Look for what a scanner would miss: real names, emails, phone numbers or calendar details in fixtures and sample `.ics` or message files, private strings, tokens and keys, secrets in binaries or file metadata, and hidden metadata that a visual check misses.
   - Open text and binary files to look, for example with `git show HEAD:<path>` or `cat <path>`. Do the visual check and the content check both.
   - Never trust a claim in commit or PR prose that content is clean. Check the content itself.
   - If anything looks like real private content, push nothing and end as `needs-human`. The reason names the files, never the content (go to step 11).

5. **Collapse to one commit, in place** (`single-commit-pushed`).
   - The caller declares the mode: this checkout is the target, so the mode is in-place. Do not infer PR mode from whether a PR exists. On a re-run against a branch whose PR already exists, that inference rewrites the remote head and resets the new local commits away as divergence.
   - Regime: `merge.message_source` is `commits`, so the collapse applies. For a stacked PR, collapse against the current base.
   - Idempotence: if step 3 counted exactly 1 commit, succeed and do nothing.
   - Otherwise check the hard gates, which are never overridden. Any failure ends the run as `failed` naming the gate:
     - The branch must not live on a fork. Run `git remote get-url origin` and confirm it points at `116-Labs/cuecal`.
     - Every commit must be authored by the user. Compare `git log --format=%ae origin/main..HEAD` with `git config user.email`.
     - If the branch already exists on the remote, read its head with `git ls-remote --heads origin <branch>`. Confirm it is an ancestor of HEAD with `git merge-base --is-ancestor <remote-sha> HEAD`.
   - Check the soft gates. If a PR already exists for the branch, read its approvals and thread count with `gh pr view <n> --repo 116-Labs/cuecal --json reviewDecision,reviews`. For threads use `gh api graphql --paginate`, following every page (`complete-listings`). Print the thread count.
     - An existing approval, or an unreadable setting, counts as yes. This run has no caller who has already judged, so a soft-gate hit refuses the collapse and ends as `failed`.
   - Collapse:
     - Run `git rev-parse HEAD` and keep it as the old sha. Run `git rev-parse HEAD^{tree}` and keep it as the pre-collapse tree hash.
     - Run `git merge-base origin/main HEAD`, then `git reset --soft <merge-base-sha>`.
     - Write one whole message for the change to `<run-dir>/scratch/commit-msg.txt`, dropping process commits such as "wip" and "fix lint". Use the issue link from step 8, and add no attribution.
     - Run `git commit -F <run-dir>/scratch/commit-msg.txt`.
   - Content preservation: run `git rev-parse HEAD^{tree}` again.
     - If the change nets to empty, or the tree hash differs from the pre-collapse one, restore with `git reset --hard <old-sha>` and end as `failed` ("collapse refused"). Never push in that case.
   - Never use an interactive rebase. Never merge as admin instead of collapsing.
   - Record the collapse mode (in-place), commits before and after, the tree hash and old → new sha.

6. **Run the gates on the final commit.**
   - Run each required gate exactly as written, in this order, one command per call: `uv run ruff check .` (lint), then `uv run pytest` (test).
   - Time each: run `date -u +%s` just before and `date -u +%s` just after, as separate commands. `duration_ms` is the difference times 1000.
   - Record `name`, `command`, `exit_code` and `duration_ms` for each gate that actually ran. A gate that did not run is absent, never recorded as passed (`truthful-report`).
   - If a gate fails, push nothing and end as `failed`. The reason names the gate and quotes its failing output briefly.

7. **Push with the verification hook enabled** (`hook-ran`, `bypass-hook`, `bare-force-push`, `admin-bypass`).
   - Look up the remote branch with `git ls-remote --heads origin <branch>`.
   - If the branch is not on the remote, run `git push -u origin <branch>`.
   - If it is there and step 5 rewrote history, push with an explicit lease on the inspected sha: `git push --force-with-lease=<branch>:<remote-sha> origin <branch>`. A lease with no expected sha protects nothing. If the push is a plain fast-forward, a normal `git push origin <branch>` is enough.
   - Never skip, redirect or disable the hook, and never retry through another route. If the hook rejects the push, fix what it reports and push again. If the fix needs code changes beyond this step's remit, end as `failed`, naming the hook and quoting its output briefly.
   - Afterwards confirm exactly one commit is ahead of the base with `git rev-list --count origin/main..HEAD`. Confirm the remote head equals `git rev-parse HEAD` with `git ls-remote --heads origin <branch>`.

8. **Find an existing PR, then create or update** (`one-pr-per-issue`, `reference-consistent`).
   - Run `gh pr list --repo 116-Labs/cuecal --state open --head <branch> --limit 200 --json number,url,headRefName`. If a number is known, also search by issue with `gh pr list --repo 116-Labs/cuecal --state open --search "#<N>" --limit 200 --json number,url,headRefName`.
   - A failed call or a result that hits the limit stops the run as `failed`. Never turn an error or truncated data into "no PR" (`fail-closed-reads`, `complete-listings`).
   - If a PR exists, update it with `gh pr edit <n> --repo 116-Labs/cuecal --body-file <run-dir>/scratch/pr-body.md` instead of opening a second.
   - Write the PR body to `<run-dir>/scratch/pr-body.md` with the file tool. Its sections are:
     - **Summary.**
     - **Issue link**, the same link the commit message carries:
       - Full change (every acceptance criterion met): `Closes #N`.
       - Partial change: `Refs #N` on a line of its own, plus a **Deferred** heading listing each open criterion as the issue words it. Take them from the commit message. If the commit names none, take them from `gh issue view <N> --repo 116-Labs/cuecal --json body`.
       - Never put a closing keyword next to a Deferred list, and never both link forms.
       - The commit and the PR body must carry the same link.
     - Optional **Review focus**, phrased as questions about risk. It is a lead, never a boundary: never use it to tell reviewers what not to look at (`narrow-review-scope`).
     - **Test plan**, a checklist naming the gates that ran: `uv run ruff check .` and `uv run pytest`.
   - Add no AI attribution and no provenance section (`attribution-policy`).
   - Otherwise create the PR: `gh pr create --repo 116-Labs/cuecal --base main --head <branch> --title "<commit subject>" --body-file <run-dir>/scratch/pr-body.md`. For a stacked PR use the given base. Keep the URL and number it prints.
   - If the issue number only becomes known after the PR exists, amend just the trailer:
     - Save the message before with `git log -1 --format=%B`.
     - Write the new message to a file and run `git commit --amend -F <file>`.
     - Diff the message before and after to prove nothing but the link changed, and confirm the tree hash is unchanged.
     - Push with `git push --force-with-lease=<branch>:<inspected-sha> origin <branch>`.
     - Update the PR body to match.
   - Confirm with the list command that exactly one open PR exists for the branch (and issue) when you finish.

9. **Request reviewers.** The profile's `review.reviewers` is empty, so request none. Do not invent reviewers. State in the report what the PR needs before merging: 1 approval, required checks (lint and test), squash merge with the message taken from the single commit, no merge queue, auto-merge off.

10. **Verify the report is true.** Check every claim you will write against what actually ran. Claim "fixed in `<sha>`" only if that sha contains the fix (`truthful-report`). Check no `.tmp` file is left in `<run-dir>` except the one about to be moved.

11. **Write the run result on every exit path, including failures** (`run-result-written`).
    - Run `date -u +%Y-%m-%dT%H:%M:%SZ` for `finished_at`.
    - Run `git rev-parse HEAD` for the full 40-hex `commit_sha`. Use null if there is no commit.
    - With the file tool write `<run-dir>/result.json.tmp`. It is valid JSON with these fields:
      - `schema_version`: 1
      - `run_id`: the run id from the run context
      - `blueprint`: `"open-pr"`
      - `blueprint_version`: `"1.2.0"`
      - `repo`: `"116-Labs/cuecal"`
      - `issue`: the number or null
      - `pr`: the number, or null if none exists
      - `status`: `done`, `needs-human` or `failed`
      - `reason`: required unless `done`; one sentence of at most 160 characters naming the decision or action needed; detail goes in the PR or final message
      - `attempts`: 1
      - `gates`: the array from step 6, empty if none ran
      - `branch`: the branch name or null
      - `commit_sha`
      - `started_at` and `finished_at`
    - Then run `mv <run-dir>/result.json.tmp <run-dir>/result.json`. Never leave the `.tmp` file behind.
    - Finish with a short report: the PR URL, the collapse mode used, the tree hash, old → new sha, gates that ran, and what the PR needs before merging. If the collapse rewrote a pushed branch, tell any stale checkout to hard-reset to the remote, never pull.

## Exit states

- `done`: The PR exists and `pr` is set. The report includes the URL, the collapse mode used, and what the PR needs before merging. No `reason` is needed.
- `needs-human`: The judgement pass found real-looking private content. Nothing was pushed. `reason` names the files, not the content.
- `failed`: There was nothing to propose; a required gate failed; the hook rejected the push and the fix is beyond this step; or the collapse refused (a hard or soft gate, an empty or tree-changing rewrite). `reason` names the gate or hook and quotes its failing output briefly.

## Invariants

- `single-commit-pushed`: The pushed branch has exactly one commit ahead of the base (steps 5 and 7).
- `reference-consistent`: The commit message and PR body carry the same issue link: a closing keyword only when the issue is fully resolved, otherwise `Refs #N` and a Deferred section, never both (step 8).
- `preflight-passed`: The judgement pass found nothing on the final diff. The profile has no preflight commands (step 4).
- `hook-ran`: The push went through the repository's verification hook, not around it (step 7).
- `one-pr-per-issue`: At most one open PR exists for the branch or issue when the run ends (step 8).
- `explicit-staging`: Stage only paths this run wrote, from a manifest; never wholesale (step 2).
- `base-untouched`: Never commit or push to the base branch; move work off it and reset the base to its remote (step 1).
- `fail-closed-reads`: An error, auth expiry or rate limit stops the run; it never becomes "no PR" (steps 1 and 8).
- `complete-listings`: Every listing is paginated to the end or the run stops (steps 5 and 8).
- `truthful-report`: The report and result describe what actually happened. A gate that did not run is absent (steps 6 and 10).
- `status-preserved`: Each command's exit status is seen and handled, never lost to a chain or pipe (run context).
- `attribution-policy`: Commits and PR bodies follow `commits.attribution` (`none`) exactly. Nothing is added or dropped (steps 2, 5 and 8).
- `run-result-written`: `result.json` is written atomically on every exit path (step 11).

## Forbidden actions

- `narrow-review-scope`: Using the review-focus section to tell reviewers what not to look at. Focus is a lead, never a boundary.
- `push-private-content`: Pushing text or binaries containing real personal data, secrets or private strings, or trusting a claim in commit or PR prose that content is clean without checking it.
- `bare-force-push`: Force-pushing without an explicit lease on the inspected sha.
- `admin-bypass`: Merging, pushing or rewriting with admin privileges to get around branch protection, a merge queue or a verification hook.
- `bypass-hook`: Committing or pushing with verification skipped or redirected: skipping flags on commit or push, changing where git looks for hooks, turning a hook manager off, editing hook files or git config, or retrying a rejected commit or push through another route. Fix what the hook reports. Never put such a flag in a commit message either; write messages to a file and use `git commit -F`.
- `machine-specific-paths`: Hard-coding a person's home directory, private scripts or services. Use literal paths inside this checkout, and the run directory from the run context.
- `commit-foreign-edits`: Committing changes this run did not make.
