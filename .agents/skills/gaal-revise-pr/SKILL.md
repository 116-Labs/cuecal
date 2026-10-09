---
name: gaal-revise-pr
description: >-
  Revises an open pull request in 116-Labs/cuecal after review. It answers every unresolved review thread, every actionable request in a review body and every request made on the linked GitHub issue since the PR opened. Each one gets a verified code change or a reasoned reply. It installs with `uv sync --locked`, runs the profile gates (`uv run ruff check .` and `uv run pytest`), checks base drift and pushes at most once per round with an explicit lease. When every thread will resolve, it collapses the branch to one Conventional Commits commit with no attribution, unless that would throw away approvals. It replies to threads, resolves them by rule, keeps the PR description true to the pushed head, requests review again and writes the run result to result.json in the run directory. Use it when a dispatch or the user names a repo and a PR number and asks for the revise-pr step ("revise the PR", "address the review comments", "fix the review feedback"). That includes imported feedback such as threads from another PR, a single comment URL or free-text notes. Do not use it to implement an issue (gaal-implement), open a PR (gaal-open-pr), review a PR (gaal-review-pr), merge, publish or deploy. When no PR can be determined, do not guess. End as needs-clarification instead.
---
<!-- gaal-stamp blueprint=revise-pr@1.8.0 shared=1.5.0 profile=6f85855df888e336 generated=2026-10-09 core=aee666ea0d453d32 forbidden=605730d3fee67b49 content=12a80ac1d0b7fb1d -->

# gaal-revise-pr

This skill closes the review loop on one open pull request in `116-Labs/cuecal` (blueprint `revise-pr`, version `1.8.0`). Every unresolved thread, every actionable request in a review body, and every request made on the linked issue since the PR opened gets either a code change or a reasoned reply. The branch is pushed at most once per round, and only with green gates. Threads end in a state that matches what was actually done. The PR description describes the head that was pushed, and then review is requested again.

## Project facts (from `.gaal/project.yml`)

| Field | Value |
|---|---|
| Repository | `116-Labs/cuecal` (public). Tracker: GitHub issues |
| Default branch | `main` |
| Branch prefix | `gaal/` (branches this skill meets usually start with it; this skill creates no branch) |
| Install | `uv sync --locked` |
| Gates (both required) | `lint`: `uv run ruff check .`; `test`: `uv run pytest` |
| Preflight / advisory | none / none |
| Commits | `single_commit: true`, Conventional Commits, attribution `none`. No `Co-Authored-By`, no "Generated with" line and no AI attribution anywhere in commits, PR bodies or comments |
| Merge | method `squash`, `message_source: commits`, no merge queue (`queue: false`), `auto: true`. This skill never merges |
| Review | `required_approvals: 1`, `threads_block_merge: true`, `dismiss_stale_approvals: true`, `require_last_push_approval: false`, `code_owner_reviews: true`, required checks `test` and `zizmor`, fixed reviewers: none, review identity `116-labs-gaal-review[bot]` (separate), start signal `reaction` |
| Push identity | `116-labs-gaal-push[bot]` |
| Stacking | The profile names no stacking tool. A PR is *stacked* when its base is a branch other than `main` |
| Limits | `revise_rounds: 3` (the limit this skill uses). The other limits, `implement_attempts: 3` and `review_rounds: 2`, belong to other steps |

What the protection facts mean here:
- `dismiss_stale_approvals: true` means **every push to the PR dismisses its approvals**, including a push that changes no content.
- `threads_block_merge: true` means an open thread blocks the merge. An agreed deferral is therefore resolved, and a pushback stays open and blocks.

## Conventions for every command

- **Run one command per call.** Never chain with `&&`, `;` or `|`. Never put `NAME=value` in front of a command. Never use shell variables, `$(…)` or backticks in a command.
- **`<run-dir>`** stands for the literal path of the run directory, taken from the run context (the value of GAAL_RUN_DIR). **`<run-id>`** stands for the literal run id from the run context (the value of GAAL_RUN_ID). **`<checkout>`** stands for the literal path that `pwd` prints at the start. Write these values out literally in every command and file path.
- Other placeholders: `<n>` is the PR number, `<branch>` the PR head branch, `<base>` the PR base branch, `<sha>` a commit id, `<N>` an issue number, `<login>` a GitHub login.
- The only commands allowed besides `git`, `gh`, `mkdir`, `mv`, `cp`, `ls`, `cat`, `date`, `pwd` and `cd` are these three, exactly as written: `uv sync --locked`, `uv run ruff check .`, `uv run pytest`. Add nothing to them. To run one in another directory, `cd` into that directory first.
- Scratch files and the throwaway worktree live inside `<run-dir>`. Never use `/tmp` or `mktemp`.
- Write every commit message, PR body, comment body, reply body and GraphQL query to a file with the file-writing tool, then pass the file by path: `git commit -F <file>`, `gh pr edit --body-file <file>`, `gh pr comment --body-file <file>`, `gh issue create --body-file <file>`, `-F body=@<file>` and `-F query=@<file>` for `gh api`. Never write a body inline. A message that quotes a refused flag is refused too.
- Quote every glob, and every argument that zsh could expand (`'HEAD^{tree}'`, `git branch --list '<branch>'`).
- List uncommitted paths only with `git status --porcelain=v1 --untracked-files=all`.
- Read the time with `date -u +%Y-%m-%dT%H:%M:%SZ`. To time a gate, run `date -u +%s` just before it and again just after it, as separate commands. Its `duration_ms` is the difference times 1000.
- **Reads fail closed** (`fail-closed-reads`). A `gh` or `git` read that errors, hits auth expiry or hits a rate limit ends the run `failed`, naming the read. It never becomes "no PR", "no threads" or "no reviews". The one exception is the mergeability check, which ends `needs-human`.
- **Listings are complete** (`complete-listings`). Every listing is paginated to the end, or the run ends `failed` naming the listing.
- **Exit statuses are kept** (`status-preserved`). Check each command's exit status yourself, and never lose it to a filter.
- `<run-dir>` is set for every Gaal run, so the run result is always written (`run-result-written`).
- **Verification is never skipped or redirected** (`bypass-hook`):
  - Do not use `--no-verify`, `git commit -n`, `--no-gpg-sign`, `-c core.hooksPath=…`, or anything else that changes where git looks for hooks.
  - Do not switch off a hook manager. Do not edit, move or restore a hook file or `.git/config`.
  - Never run a command that names `core.hooksPath`, even one that only reads it. To find the hooks directory, run `git rev-parse --git-path hooks`.
  - When a hook rejects a commit or push, fix what it reports and try again. When the fix is beyond this run's remit, end `failed` naming the hook and quoting its output briefly.
- **Stage explicitly** (`explicit-staging`). Never use `git add -A`, `git add .` or `git commit -a`.
- **Force-push only with a lease** (`bare-force-push`): `git push --force-with-lease=<branch>:<sha> origin HEAD:refs/heads/<branch>`, where `<sha>` is the remote head you inspected.
- **No admin route** (`admin-bypass`). Never merge, never use `gh pr merge --admin`, and never take any admin route around protection.
- **No machine-specific paths** (`machine-specific-paths`). Use only paths inside the checkout or the run directory, and only the tools the profile names.

## Steps

The steps refer to each other by name:
- the **push step** commits the fixes, checks base drift and pushes;
- the **collapse step** applies the collapse routine;
- the **reply step** replies to every thread and posts the one PR comment;
- the **description step** brings the PR description up to date;
- the **run result** is the last step.

### 0. Start the run

1. Run `date -u +%Y-%m-%dT%H:%M:%SZ` and keep the output as `started_at`.
2. Run `pwd` and keep the output as `<checkout>`.
3. Run `mkdir -p <run-dir>/scratch`.
4. Keep these in memory for the run result: `attempts` (starts at 1), the list of gate runs, the item table, and every decision taken.

### 1. Determine the PR and confirm it is open

1. Take the PR number from the dispatch. If the dispatch names only a branch, run `gh pr list --repo 116-Labs/cuecal --head <branch> --state open --json number`, and use the result only when it holds exactly one PR. If no PR can be determined, never guess. End `needs-clarification` with a question asking which PR to revise, and go to the run result.
2. Read the PR:
   `gh pr view <n> --repo 116-Labs/cuecal --json number,state,url,createdAt,author,baseRefName,headRefName,headRefOid,isCrossRepository,body,commits,closingIssuesReferences,mergeable,mergeStateStatus,baseRefOid`
3. If `state` is not `OPEN` (the PR is closed or merged), end `failed` with a reason such as "PR #<n> is not open", and go to the run result.
4. Keep `<branch>` = `headRefName`, `<base>` = `baseRefName` and `<start-sha>` = `headRefOid` (the inspected sha).
   - If `<branch>` is `main`, end `failed`: this skill never commits or pushes to the base (`base-untouched`).
   - If `isCrossRepository` is true, the head lives on a fork. Handle the items as usual. Nothing can be pushed from `origin`, so the push step ends the round `needs-human` (a permission refusal) and reports the fixes as prepared.

### 2. Check out the PR head and install

1. Run `git fetch origin <branch>`.
2. Run `git rev-parse origin/<branch>`. The output must equal `<start-sha>`. If it differs, the head moved while it was being read: end `failed` naming the read.
3. Run `git worktree add --detach <run-dir>/worktree <start-sha>`.
4. Run `cd <run-dir>/worktree`. Every later git and gate command runs here unless a step says otherwise.
5. Run `git rev-parse 'HEAD^{tree}'` and keep the output as `<start-tree>`.
6. Run `uv sync --locked`. Run it every time, because dependencies that look present may be stale (`install-before-gates`). If it fails, end `failed` naming `uv sync --locked`.

### 3. List every unresolved review thread

1. Write `<run-dir>/scratch/threads-1.graphql` with the file tool. Use literal values only, with no GraphQL variables:
   ```
   query {
     repository(owner: "116-Labs", name: "cuecal") {
       pullRequest(number: <n>) {
         reviewThreads(first: 100) {
           pageInfo { hasNextPage endCursor }
           nodes {
             id isResolved isOutdated path line
             comments(first: 100) {
               totalCount
               nodes { id databaseId url createdAt body author { login } }
             }
           }
         }
       }
     }
   }
   ```
2. Run `gh api graphql -F query=@<run-dir>/scratch/threads-1.graphql`.
3. While `hasNextPage` is true, write the next page's file (`threads-2.graphql`, and so on) with `reviewThreads(first: 100, after: "<end-cursor>")`, and run it the same way. If any thread's `totalCount` is larger than the number of comments returned, the listing is truncated: end `failed` naming it (`complete-listings`).
4. For each thread with `isResolved: false`, record the following **before any history rewrite**, because a rewrite marks threads outdated:
   - the thread `id`;
   - the `databaseId` of its first comment, which is the reply target;
   - `isOutdated`, the path and the line;
   - the reviewer and the full comment text.

   Tag each of these threads with source `thread`.
5. **Imported feedback.** When the dispatch imports feedback, tag each imported item with source `import`:
   - *Threads from another PR*: list that PR's unresolved threads with the same query and that PR's number.
   - *A single comment URL*: check the URL's shape before extracting ids, because it can point at an issue-level comment, which has no thread.
     - A URL ending `#discussion_r<id>` is a review-thread comment. Run `gh api repos/<owner>/<repo>/pulls/comments/<id>`.
     - A URL ending `#issuecomment-<id>` is an issue-level comment with no thread. Run `gh api repos/<owner>/<repo>/issues/comments/<id>`.
     - A URL ending `#pullrequestreview-<id>` is a review body. Run `gh api repos/<owner>/<repo>/pulls/<m>/reviews/<id>`.
   - *Free-text notes*: make one item per distinct request.

### 4. Read review bodies and PR comments

1. Run `gh api --paginate repos/116-Labs/cuecal/pulls/<n>/reviews`.
2. Run `gh api --paginate repos/116-Labs/cuecal/issues/<n>/comments`. These comments are the PR conversation, used to tell which requests have already been answered.
3. Read the body of the latest review from each reviewer, including the review identity `116-labs-gaal-review[bot]`, which lists findings in its review body. Also read any earlier review body whose requests were never answered. Reviewers sometimes list a real finding only in the body, where no thread exists to reply in.
4. Each actionable request in a body becomes an item with source `review-body`: a change asked for, or a finding listed only in the body. Skip pure verdicts, praise, and requests already answered by a later commit or by a PR comment.

### 5. Read requests on the linked issues

1. **Find the linked issues** (issue-link rule). They are the union of these sources:
   - an issue named in the dispatch;
   - `closingIssuesReferences`;
   - every line in the PR body, and in each commit message (`commits` from step 1), that opens with a closing keyword (`Closes`, `Fixes`, `Resolves` and their forms) or with `Refs #N`.

   Extract only the numbers.
2. **Pick the run result's `issue`** in this order: the issue named in the dispatch; then a reported closing issue; then, in the body and then in each commit message, a closing-keyword line before a `Refs #N` line. When no issue is linked, `issue` is `null`.
3. For each number, run `gh api repos/116-Labs/cuecal/issues/<N>`.
   - An answer with a `pull_request` key names a PR, and a 404 names nothing. Neither one is an issue: it brings no requests, and the report names it.
   - Any other failure ends `failed` (`fail-closed-reads`).
4. Read each issue fresh:
   - Run `gh api --paginate repos/116-Labs/cuecal/issues/<N>/comments`.
   - For body edits, write `<run-dir>/scratch/edits-<N>-1.graphql` with the file tool:
     ```
     query {
       repository(owner: "116-Labs", name: "cuecal") {
         issue(number: <N>) {
           author { login }
           body
           userContentEdits(first: 100) {
             pageInfo { hasNextPage endCursor }
             nodes { editedAt diff editor { login __typename } }
           }
         }
       }
     }
     ```
     Run `gh api graphql -F query=@<run-dir>/scratch/edits-<N>-1.graphql`. While `hasNextPage` is true, page with `after: "<end-cursor>"` in new files.
5. **Cutoff.** Take two times and use the **earlier** of them:
   - the PR's `createdAt`;
   - the creation time of the newest issue comment that reads `Gaal finished implement …: done.`, which marks when Gaal's newest done implement run for this issue started.

   Open-pr only published that work and read nothing new.
6. **Who counts.** A request comes from the issue's author or from a maintainer. A maintainer is a login for which `gh api repos/116-Labs/cuecal/collaborators/<login>/permission --jq .permission` prints `admin`. Look each login up once. A 404 there means the login is not a collaborator; any other error ends `failed`. A bot never counts: one with a `__typename` or user `type` of `Bot`, or a login ending in `[bot]`.
7. **What is a request:**
   - Every comment created after the cutoff by someone who counts, unless it carries a `<!-- gaal:` marker. A marked comment is Gaal's own.
   - Every body edit after the cutoff by someone who counts. Compare each edit's `diff` with the version before it.
     - Skip an edit only when every added or removed line falls inside a marked plan-drift section. A section runs from an opening `<!-- gaal:plan-drift -->` line to the next closing `<!-- /gaal:plan-drift -->` line, with both marker lines included. Implement wrote that section, perhaps under the maintainer's own login.
     - An edit with any changed line outside such a section is a request. That includes a maintainer's text appended after a section.
     - A body that merely contains a marked section is still read.
   - Skip requests that a PR comment already answers.
8. Each actionable request becomes an item with source `issue-request`: a change asked for in a comment, or a criterion or requirement that an edit added or changed. A comment that asks for nothing (a status note, thanks) is no item.

Maintainers ask for more on the issue as often as they do on the PR. If you skip this step, the PR converges on the old scope. Gaal does not ask again about a request once a revise-pr run that saw it has finished, so every request must be answered (`issue-requests-answered`).

### 6. Re-verify imported items

Re-check each `import` item against this branch's code in the worktree, and classify it as *reproduces*, *partly applies* or *does not apply*.
- An item that does not reproduce is never applied (`apply-unreproduced-import`).
- It is still answered, with the reason (`every-thread-answered`).

### 7. Decide each item

Give every item exactly one decision:

- **fix**: a code change on this PR's branch only (`target-branch-only`). For an imported item, the reply names where the fix landed. A fix that needs a new or changed dependency cannot be made here: `uv.lock` cannot be regenerated with the allowed commands, and `uv sync --locked` refuses a mismatched lock. Answer that item instead, with this reason.
- **answer**: answer a question or give an explanation.
- **defer**: only under the follow-up bar. A follow-up issue is filed only for a *user-visible defect outside the diff*: wrong output a user can see, in code this PR did not touch, that reproduces on the base.
  - File the issue before replying: `gh issue create --repo 116-Labs/cuecal --title "<title>" --body-file <run-dir>/scratch/followup-<k>.md`. The body names the defect, the reproduction and the files, and links where the defect was found. Add no milestone.
  - Anything else is never filed: a finding inside the diff, a style point, a refactor, a hardening idea, a pre-existing defect nobody can see, or a request that widens the issue. Fix it, answer it or push back on it.
  - A deferral with no issue and no agreed owner is a pushback in disguise, and is answered as one.
- **push back**: disagree, with reasons.

Rules for the other sources and for ambiguous requests:
- A `review-body` or `issue-request` item is decided the same way. A deferral there has no thread to carry agreement, so it is not resolved, and the PR comment names its follow-up issue.
- An `issue-request` that widens the issue beyond what this PR can reasonably carry is deferred, not folded in. It becomes a follow-up issue only when the follow-up bar is met. Otherwise it is answered with the reason.
- A request ambiguous enough that any fix would be a guess does not stop the round.
  - Answer it by asking its question: on its thread, or in the PR comment for a `review-body` or `issue-request` item.
  - Decide and handle every other item as usual: fixes pushed, replies sent, the PR comment posted.
  - The run then ends `needs-clarification`, with `questions` quoting the request. The thread stays open.

**From here on, every exit goes through the reply step** (see "Exit paths").

### 8. Make the fixes

1. Edit files in `<run-dir>/worktree` with the file tools.
2. Keep a manifest of every repository path you write.
3. Make all the fixes before any push. Pushing once per comment is forbidden (`piecemeal-push`).

### 9. Run the gates (when the round has fixes)

1. If a fix changed `pyproject.toml` or `uv.lock`, run `uv sync --locked` again first (`install-before-gates`). If it fails, end `failed` naming it.
2. Run each gate in order, timing each one. Run these as separate commands:
   1. `date -u +%s`
   2. `uv run ruff check .`
   3. `date -u +%s`
   4. `date -u +%s`
   5. `uv run pytest`
   6. `date -u +%s`
3. If a gate is red, fix what it reports, add the paths to the manifest, and re-run every gate. Each gate-fix cycle is one round, and `attempts` counts the rounds used.
4. When `revise_rounds` (**3**) rounds have been used without both gates green, stop and end `needs-human`, naming the red gate (`bounded-rounds`). Nothing is pushed: a red push is forbidden (`push-red`). If the failure is in code this PR did not touch and the round's fixes did not cause it, report it as pre-existing.
5. Record only the runs on the tree that is finally pushed, in the order they ran, each with `name`, `command`, `exit_code` and `duration_ms`. A gate that went red, was fixed and was run again appears once, with its green run (`gates-final-tree`).

### 10. Push step: commit, check base drift, push once

This step runs every round, with or without fixes.

**Commit (only when there are fixes).**

1. For each path in the manifest, run `git add -- <path>`.
2. Run `git status --porcelain=v1 --untracked-files=all`. Nothing that this run is responsible for may be left unstaged, and nothing outside the manifest may be staged (`explicit-staging`, `commit-foreign-edits`). The untracked `.venv` from the install is not this run's change, and is never staged.
3. Write `<run-dir>/scratch/fixup-msg.txt` with the file tool. It holds one Conventional Commits fixup commit, such as `fix: address review feedback on #<n>`, with a body that lists the fixes. Add no attribution trailer (`attribution-policy`, attribution `none`).
4. Run `git commit -F <run-dir>/scratch/fixup-msg.txt` with the hooks enabled. If a hook rejects the commit, fix what it reports, stage the fixed paths explicitly and commit again (`bypass-hook`). If the fix is beyond this run's remit, end `failed` naming the hook.
5. Run `git rev-parse HEAD` and keep the output as `<fix-sha>`.

**Check base drift (`base-drift-checked`), also in a round with no fix.**

6. Run `git rev-parse HEAD` and keep the output as `<old-head>`. Run `git rev-parse 'HEAD^{tree}'` and keep the output as `<old-tree>`.
7. **When `<base>` is not `main` (a stacked PR)**, look up the parent PR, which is the pull request whose head branch is `<base>`:
   `gh pr list --repo 116-Labs/cuecal --head <base> --state all --json number,state,headRefOid,mergedAt`

   Take the most recent PR. Keep its `headRefOid` as `<old-parent-tip>` and its number as `<p>`.
   - If the parent has **merged**, fetch only `main`: run `git fetch origin main`. Never fetch `origin <base>`, because the parent branch may have been deleted at merge.
   - Otherwise, run `git fetch origin <base>` and `git fetch origin main`.
8. **When `<base>` is `main`**, run `git fetch origin main`.
9. Read mergeability: `gh pr view <n> --repo 116-Labs/cuecal --json mergeable,mergeStateStatus,baseRefOid`.
   - While `mergeable` is `UNKNOWN`, read it again, up to five reads in all. No `sleep` is allowed, so the time between calls is the wait.
   - A value still `UNKNOWN` after the fifth read is unreadable, and so is a failed call. Never read either as mergeable. End `needs-human` naming the check, with nothing pushed.
10. **Decide whether to rebase.** Rebase only in these cases:
    - the PR is `CONFLICTING` or `DIRTY`;
    - `mergeStateStatus` is `BEHIND`. GitHub reports `BEHIND` only when the base requires branches to be up to date before merging. Never read branch protection for this;
    - the PR is stacked and its parent has merged.

    A base that merely moved while the PR stays `MERGEABLE` and is not `BEHIND` is not rebased onto. A rebase rewrites history that the reviewer then has to range-diff, and while the PR holds approvals it would be a content-free push (`content-free-push-after-approval`). Thread ids are already recorded (step 3), so a rebase can go ahead.
11. **Normal rebase** (the base is `main`, or the parent has not merged):
    1. Run `git merge-base <old-head> origin/<base>` and keep the output as `<old-merge-base>`. A base that only moved forward leaves that merge base where the branch left it.
    2. Run `git rebase origin/<base>`. This keeps the branch's commits as they are, with no merge commit.
12. **Merged-parent rebase** (stacked, and the parent has merged):
    1. If `<old-parent-tip>` is not local, run `git fetch origin pull/<p>/head`.
    2. Run `git merge-base --is-ancestor <old-parent-tip> HEAD`. If it does not exit 0, the parent was rewritten after this branch left it (for example, collapsed). Do not rebase. End `needs-human` naming the parent PR, with nothing pushed.
    3. Keep `<old-merge-base>` = `<old-parent-tip>`.
    4. Run `git rebase --onto origin/main <old-parent-tip>`. This rebases only the child's own commits.
    5. After the push below succeeds, run `gh pr edit <n> --repo 116-Labs/cuecal --base main` to retarget the PR. From then on, `<base>` is `main` for every later step: the post-push check, the collapse's merge base, and its author check.
13. **If a rebase conflicts**, run `git diff --name-only --diff-filter=U` and keep the conflicting paths. Then run `git rebase --abort`, and end `needs-human` naming those paths, with nothing pushed.
14. **After any rebase:**
    1. Run `git rev-parse 'HEAD^{tree}'`.
    2. If the tree equals `<old-tree>`, record `tree unchanged`.
    3. Otherwise, run `git merge-base HEAD origin/<new-base>` and keep the output as `<new-merge-base>`. Then run `git range-diff <old-merge-base>..<old-head> <new-merge-base>..HEAD`. Every commit should pair with `=`. Record the short summary.
    4. Both results go into the run result's `push` (`push-explained`).
    5. Run `uv sync --locked` again (on failure, end `failed`), and re-run both gates with timing, as in step 9. Replace the recorded gate runs with these runs.
    6. A gate that is red on the rebased tree ends `needs-human`, naming the gate and the base sha, with nothing pushed. The branch and the new base disagree, which is a person's call, not a review fix.
15. **Nothing to push.** With no fix and no required rebase, the push step pushes nothing. Continue to the collapse step.
16. **Fork head.** If `isCrossRepository` is true, do not push. Run `git reset --hard <old-head>` to restore the HEAD from before any rebase, then end `needs-human` (a permission refusal), with the fixes reported as prepared.

**Push once (`one-push-per-round`, `gates-green-before-push`).**

17. Run `git ls-remote origin refs/heads/<branch>`. The output must equal `<start-sha>`. If it does not, the push would fail its lease: restore the HEAD with `git reset --hard <old-head>`, push nothing, and end `failed` naming the lease mismatch.
18. Run `git push --force-with-lease=<branch>:<start-sha> origin HEAD:refs/heads/<branch>` with the hooks enabled.
    - **A local hook rejects the push.** Fix what it reports, commit the fix explicitly (with the gates re-run), and push again with the same lease (`bypass-hook`).
    - **Any other failure is never retried** (`push-failure-states`). Run `git reset --hard <old-head>` to restore the HEAD from before any rebase, and push nothing more.
      - A permission refusal ends `needs-human` naming it. That covers no write access, a protected branch, HTTP 403, or a server-side hook such as a pre-receive hook declining the push (GH006, GH013).
      - Anything else ends `failed` naming it: a lease mismatch, a network error, or another error.
19. Run `git rev-parse HEAD` and keep the output as `<pushed-sha>`. Record `push.why` in one sentence: the fixes the push carried, or what required the rebase.
20. **After the push**, read mergeability again with the same command and the same `UNKNOWN` re-read rule.
    - If the PR is now `CONFLICTING` or `DIRTY`, do not push again (`one-push-per-round`). Skip the collapse step, send the replies (none of them claims the PR is ready), and end `needs-human` naming the conflict.
    - An unreadable or failed check here is reported the same way as a conflict.
    - A base that moved again while the PR stays mergeable ends nothing. The next round or the merge path takes it, and there is never a second push to chase a moved base.

### 11. Settle the issue link

Settle the link now, because the collapse step must write into the commit message the same link that the body will carry (open-pr's `reference-consistent`).
- The issue-link rule applies: a full change carries `Closes #N`; a partial change carries `Refs #N` on a line of its own, followed by a **Deferred** list that words each open criterion as the issue words it.
- A closing keyword never appears next to a **Deferred** list.
- A round that completes some deferred criteria removes them from the **Deferred** list.
- A round that completes the last of them turns `Refs #N` into `Closes #N` and drops the list.

### 12. Collapse step

Collapse only when **all** of these hold:
- every thread on this PR will be resolved after replies: no pushback, unagreed deferral or open question remains. Otherwise collapsing is forbidden (`collapse-with-open-threads`), because the reviewer needs to diff only the delta;
- `merge.message_source` is `commits` (it is, in this repository);
- the push step did not end the round on a conflict.

When these do not hold, keep the fixup commit separate and skip to the reply step.

**Approval check (`content-free-push-after-approval`).** Read it just before the collapse, after the push step's push:
1. Run `gh api --paginate repos/116-Labs/cuecal/pulls/<n>/reviews`.
2. For each reviewer, take their latest review whose state is `APPROVED` or `CHANGES_REQUESTED`. Count the reviewer when that review is `APPROVED` and not `DISMISSED`.

   In this profile both protection facts are set and `require_last_push_approval` is false, so an approval of an earlier commit still counts until GitHub dismisses it.
3. When the count reaches `required_approvals` (**1**), do not collapse. Here `dismiss_stale_approvals: true` means the collapse would throw those approvals away for nothing, because it changes no content.
   - Keep the commits as they are.
   - Say in the report that the collapse was skipped to keep the approvals, and that whoever merges supplies the message.
4. A round whose push carried fixes has usually lost its approvals already, through GitHub's dismissal. The collapse then goes ahead.

**Gates for a collapse-only round.** When the push step pushed nothing, the collapse is the round's only push. First install and run every gate on the head, as in step 9 (`gates-green-before-push`). A red gate ends `needs-human` naming it, with nothing pushed.

**The routine, in PR mode, in the throwaway worktree `<run-dir>/worktree`:**

1. **Regime.** `merge.message_source` is `commits`, so the routine runs.
2. **Idempotence.**
   1. Run `git merge-base HEAD origin/<base>` and keep the output as `<merge-base>`. Use the current base, which is `main` after a retarget.
   2. Run `git rev-list --count <merge-base>..HEAD`.
   3. If the count is 0 or 1, the collapse succeeds without doing anything.
3. **Target.** The mode is PR mode, declared by this skill. Run `git ls-remote origin refs/heads/<branch>` and keep the output as `<remote-head>`. Note that `<remote-head>` is `<pushed-sha>` if the push step pushed, and `<start-sha>` otherwise.
4. **Soft gates.** This skill knowingly overrides the unresolved-threads gate, because the threads just fixed resolve after the push. Print the count of unresolved threads, and name the override in the report. The approval check above decides the other soft gate.
5. **Hard gates (never overridden).** If one fires, the collapse is refused: send the replies (none of them claims a collapse) and end `failed` naming the gate.
   - **Fork.** `isCrossRepository` is true.
   - **Foreign author.** Run `git var GIT_AUTHOR_IDENT` and `git log --format=%ae <merge-base>..HEAD`. The gate fires if any author email differs from the email in `GIT_AUTHOR_IDENT`. Never compare with `git config user.email`.
   - **Remote not contained** (`collapse-remote-contained`). The gate fires if `<remote-head>` differs from the sha this run inspected or pushed, or if `git merge-base --is-ancestor <remote-head> HEAD` does not exit 0.
6. **Divergent local checkouts.** In `<checkout>`, run `git branch --list '<branch>'`.
   1. If a local branch `<branch>` exists, run `git rev-list origin/<branch>..<branch>`. When that lists local-only commits:
      1. Back them up with `git branch gaal-backup/<branch>-<run-id> <branch>`.
      2. Verify the backup with `git rev-parse gaal-backup/<branch>-<run-id>`.
   2. Run `git worktree list` to see whether `<branch>` is checked out anywhere. If it is, run `git status --porcelain=v1 --untracked-files=all` there. Uncommitted edits of unknown origin stop the collapse for a human: end `needs-human`, with nothing pushed.
   3. Return to the worktree with `cd <run-dir>/worktree`.
7. **Rewrite.**
   1. Run `git rev-parse HEAD` and keep the output as `<pre-collapse-head>`.
   2. Run `git rev-parse 'HEAD^{tree}'` and keep the output as `<pre-collapse-tree>`.
   3. Run `git reset --soft <merge-base>`. Never reset to the base's tip: on a base that moved on, the new commit would revert the base's newer changes while the tree hash still matched.
8. **Content preservation** (`collapse-content-preserved`).
   1. Run `git diff --cached --quiet`. Exit 0 means the change nets to nothing. Abort: run `git reset --hard <pre-collapse-head>`, push nothing, send the replies (none of them claims a collapse) and end `failed` naming the content gate.
   2. Write `<run-dir>/scratch/collapse-msg.txt` as one Conventional Commits message for the whole change (`collapse-keeps-link`).
      - Drop process messages such as "wip" or "fix lint".
      - Carry the issue link settled in step 11, with its **Deferred** list when the link is `Refs`.
      - Add no attribution.
   3. Run `git commit -F <run-dir>/scratch/collapse-msg.txt` with the hooks enabled (`bypass-hook`).
   4. Run `git rev-parse 'HEAD^{tree}'`. If the tree differs from `<pre-collapse-tree>`, abort exactly as in step 8.1. The commit is never retried.
9. **Push.** Run `git push --force-with-lease=<branch>:<remote-head> origin HEAD:refs/heads/<branch>`.
   - This is the round's closing push (`one-push-per-round`). It rewrites the pushed commits into one without changing the tree. When the push step pushed nothing, it is the round's only push.
   - The fix push has already landed, so the collapse reads a remote head that contains the fix.
   - On a hook rejection, fix what it reports and push again.
   - On any other failure, run `git reset --hard <pre-collapse-head>`, and end as `push-failure-states` says: `needs-human` for a permission refusal, `failed` for anything else.
10. **Bring the stale checkout up to date.** If a local `<branch>` exists in `<checkout>`, run `cd <checkout>`, then bring the branch up to the remote. Never pull, because a pull merges the old history back in (`pull-after-collapse`).
    - If the branch is checked out in `<checkout>` and clean, run `git reset --hard <collapsed-sha>`.
    - If the branch is not checked out, run `git update-ref refs/heads/<branch> <collapsed-sha> <old-local-sha>`.
    - For any other worktree that has the branch checked out, report the hard reset it needs.

    Then run `cd <run-dir>/worktree`.
11. **Report**:
    - the mode (PR) and the regime (`commits`);
    - the commit count before and after;
    - the gates that fired or were overridden;
    - the tree hash;
    - the old and new sha;
    - the backup refs in full;
    - the reset that each stale checkout needs.
12. Record `push.changes` as `tree unchanged` when the final tree equals `<start-tree>`. Otherwise record a short range-diff summary from `git range-diff <start-merge-base>..<start-sha> <final-merge-base>..HEAD`.

### 13. Reply step

The reply step runs on **every** exit after items were decided, not only on `done`. That includes a round that stops before or at its push: the round limit, a rebase conflict, a gate red on the rebased tree, an unreadable mergeability check, a refused or failed push, a hook fix beyond this run's remit, a fork head, or a refused or aborted collapse.

- **Thread replies** (`every-thread-answered`, `reply-matches-action`). For each recorded thread, write `<run-dir>/scratch/reply-<k>.md`, then run:
  `gh api repos/116-Labs/cuecal/pulls/<n>/comments/<first-comment-database-id>/replies -F body=@<run-dir>/scratch/reply-<k>.md`

  This reply relation works on outdated threads too, which is why the ids were recorded before any rewrite. Each reply says what was done:
  - **fix**: "Fixed in `<sha>`", where `<sha>` is the final remote head that contains the fix (the collapsed sha after a collapse, otherwise `<pushed-sha>`). For an import, say where the fix landed.
  - **defer**: the follow-up issue number.
  - **push back**: the reasons.
  - **answer**: the answer.
  - **question**: the question, quoted.
  - **import that does not apply**: the reason.
- **Imported threads on another PR** get their reply on their own thread. The fix sha names this PR.
- **One PR comment** (`body-requests-answered`, `issue-requests-answered`). When there are `review-body` or `issue-request` items, write `<run-dir>/scratch/pr-comment.md` and run `gh pr comment <n> --repo 116-Labs/cuecal --body-file <run-dir>/scratch/pr-comment.md`. The comment quotes or links each request (an issue request by its comment link, or by the edit's time) and gives its decision: a sha, an issue number or the reasons.
- **When no collapse runs**, a changed issue link cannot reach the commit message. This happens when a thread stays open, when the push step skipped the collapse, when the approvals kept it from running, or when the routine refused or aborted. Say in the reply or the PR comment that the link and the **Deferred** list stay as the branch's commit carries them.
- **On a stopped round**, report a fix that was not pushed as *prepared, not pushed*, with the reason, and leave its thread open. No reply names a sha the remote does not have, and no reply claims the PR is ready or collapsed.
- Do not mention approval dismissal here. Gaal handles it (step 16).

### 14. Resolve threads by rule (`resolve-by-rule`)

1. Resolve a thread only when one of these holds:
   - it was fixed and the fix is on the remote;
   - it is outdated, and its decision is not a pushback, a question or an unagreed deferral;
   - it was deferred with agreement already recorded on the thread.

   This repository's open threads block merge, so an agreed deferral is resolved and a pushback stays open and blocks.
2. For each thread to resolve, write `<run-dir>/scratch/resolve-<k>.graphql` with the file tool:
   ```
   mutation { resolveReviewThread(input: { threadId: "<thread-id>" }) { thread { isResolved } } }
   ```
   Then run `gh api graphql -F query=@<run-dir>/scratch/resolve-<k>.graphql`.
3. Leave these open for the reviewer: pushbacks (`resolve-pushback`), unagreed deferrals (`resolve-unagreed-deferral`), questions, and fixes that were not pushed.
4. `review-body` and `issue-request` items have nothing to resolve.
5. Resolving another PR's thread may fail on permissions. The reply is what matters, so report that failure without treating it as a blocker.

### 15. Description step (`description-matches-head`)

1. Skip this step when the round changed no code and no claim in the description became false. Editing the description pushes nothing.
2. Run `gh pr view <n> --repo 116-Labs/cuecal --json body`, and re-read the body against the pushed tree and the round's outcome. Do this after the last push, because test counts and behaviour claims go stale across rounds. Check:
   - the summary;
   - the test plan;
   - every test count, gate result and behavioural claim that the round changed.
3. Edit only what is now false or missing. Keep the issue reference and any attribution section, and do not rewrite untouched prose.
4. **The issue link.**
   - **When a collapse ran**, write the link settled in step 11. A **Deferred** list appears only under `Refs`, never under `Closes`.
   - **When no collapse ran**, leave the link and the **Deferred** list as the branch's commit carries them, so that the body and the head commit agree.
5. Write the new body to `<run-dir>/scratch/pr-body.md` and run `gh pr edit <n> --repo 116-Labs/cuecal --body-file <run-dir>/scratch/pr-body.md`.

### 16. Request review again

1. Re-request review from each human reviewer who left a thread or a review body that this round answered: `gh api -X POST repos/116-Labs/cuecal/pulls/<n>/requested_reviewers -F 'reviewers[]=<login>'`.
2. Bots, including `116-labs-gaal-review[bot]`, cannot be requested this way. Gaal starts its own review run.
3. When this round's push dismissed approvals, Gaal itself re-requests exactly those reviewers, once per push, with a PR comment that quotes the run result's `push`. Do not re-request them yourself, and post no notice of your own about the dismissal.

### 17. Clean up and write the run result

1. Run `cd <checkout>`.
2. Run `git worktree remove --force <run-dir>/worktree`. Do this on every exit path where the worktree exists.
3. Run `date -u +%Y-%m-%dT%H:%M:%SZ` and keep the output as `finished_at`.
4. Run `gh pr view <n> --repo 116-Labs/cuecal --json headRefOid` for `commit_sha`, when a PR is known. On `done`, this is the PR head after the run. When nothing needed changing, it is the unchanged head.
5. Write `<run-dir>/result.json.tmp` with the file tool, then run `mv <run-dir>/result.json.tmp <run-dir>/result.json`. Never leave the `.tmp` file behind. The fields:

```json
{
  "schema_version": 1,
  "run_id": "<run-id>",
  "blueprint": "revise-pr",
  "blueprint_version": "1.8.0",
  "repo": "116-Labs/cuecal",
  "issue": 123,
  "pr": 45,
  "status": "done",
  "attempts": 1,
  "gates": [
    { "name": "lint", "command": "uv run ruff check .", "exit_code": 0, "duration_ms": 2000 },
    { "name": "test", "command": "uv run pytest", "exit_code": 0, "duration_ms": 14000 }
  ],
  "branch": "gaal/123-example",
  "commit_sha": "<40-hex sha>",
  "push": { "why": "Carried the fixes for two review threads.", "changes": "1 commit changed: tests for empty input added" },
  "started_at": "2026-01-01T00:00:00Z",
  "finished_at": "2026-01-01T00:05:00Z"
}
```

Rules for the run result:
- `issue` is an integer or `null`. `pr` is an integer, or `null` when no PR was determined. `branch` is `<branch>`, or `null` when no PR was determined. `commit_sha` is a 40-hex sha, or `null` when none is known.
- `reason` is required unless `status` is `done`. It is one sentence of at most 160 characters naming the decision or action needed. Detail belongs in the PR comment and the final message.
- `questions` is required and non-empty when `status` is `needs-clarification`. Each entry quotes the request or names the missing PR.
- `attempts` is the number of rounds used, at least 1.
- `gates` follows `gates-final-tree`:
  - It lists only the runs on the final tree, in the order they ran.
  - A `done` result never lists a non-zero `exit_code`.
  - A result that is not `done` lists the runs on the tree it stopped on, and may include the red run that stopped it.
  - A gate that did not run is absent (`truthful-report`).
  - `gates` may be empty when nothing was pushed and no gate ran.
- `push` is present only when the run pushed. `why` gives the fixes it carried or what required the rebase. `changes` gives a short range-diff summary of the head before the run against the head after it, or `tree unchanged`.
- Add no other fields. `tier`, `model` and `tier_signals` are recorded by Gaal.

**Final message.** End with a report that has one row per item (source, decision, sha or issue). It lists:
- open pushbacks;
- the collapse report, or the reason the collapse was skipped;
- the soft gates that were overridden;
- gates that were already red on the base, as pre-existing;
- linked numbers that named no issue.

## Exit paths

Every exit writes the run result. Every exit after items were decided (step 7) first runs the reply step, and the resolve step where it applies, before the run result.

- `done`: Every thread, every actionable review-body request and every issue request since the PR opened is answered. The description matches the head, and the branch is pushed with green gates. When nothing needed changing (no fix, no required rebase, no collapse), nothing is pushed, `commit_sha` is the unchanged head, and `gates` may be empty. Open pushbacks are normal and are listed. A collapse skipped to keep the PR's approvals is reported, not treated as an error.
- `needs-clarification`: No PR could be determined (step 1). Or a reviewer's request is ambiguous enough that any fix would be a guess: it was asked on its thread or in the PR comment, after every other item was handled as usual. `questions` quote it.
- `needs-human`: any of these, with `reason` naming it:
  - the round limit of 3 was reached with red gates;
  - a gate was red on the head before a collapse that was the round's only push (nothing was pushed);
  - a merged stack parent's last head is not an ancestor of the branch (nothing was pushed);
  - a rebase conflict, or an unmergeable PR, blocks the push;
  - the push was refused for permission, or the head lives on a fork;
  - a mergeability check was unreadable;
  - a gate was red on the tree rebased onto a fresh base (nothing was pushed);
  - the PR became `CONFLICTING` or `DIRTY` after the push;
  - uncommitted edits of unknown origin blocked a collapse.
- `failed`: any of these, with `reason` naming the step:
  - the PR is not open;
  - the install failed;
  - the push failed for another reason, such as a lease mismatch or a network error (the HEAD was restored);
  - the collapse routine refused, or its content gate aborted (the pre-collapse HEAD was restored);
  - a hook fix was beyond this run's remit;
  - a read failed, or a listing was truncated.

## Invariants

- `every-thread-answered`: Every unresolved thread at the start of the run has a reply at the end, including imports that did not apply.
- `one-push-per-round`: The push step pushes at most once per round, after all fixes. The only other push a round may make is the collapse step's closing push, which leaves the tree unchanged. There is never a second push to chase a moved base.
- `gates-green-before-push`: Every required gate (`lint`, `test`) exited 0 on the tree that was pushed.
- `reply-matches-action`: Each reply describes what was done: a sha that contains the fix, an issue number for a deferral, or reasons for a pushback.
- `resolve-by-rule`: A thread is resolved only if it was fixed, is outdated, or was deferred with agreement recorded on the thread.
- `target-branch-only`: Code changes land only on this PR's branch. A fix for an imported item names where it landed.
- `bounded-rounds`: Gate-fix cycles stop at `revise_rounds` (3), ending `needs-human`.
- `body-requests-answered`: Every actionable request in a latest review body is acted on, or answered in the PR comment with the reason.
- `issue-requests-answered`: Every actionable request made on the linked issue since the cutoff, by its author or a maintainer, is acted on, or answered in the PR comment with a sha, a follow-up issue or the reason it was declined.
- `description-matches-head`: After the round, the PR description states nothing that the pushed head contradicts. It never has a **Deferred** list under `Closes`, and its issue link never differs from the head commit's. It is edited before review is re-requested.
- `base-drift-checked`: The base and the PR's mergeability are read before and after the round's push. Only a `CONFLICTING`, `DIRTY` or `BEHIND` PR, or a stacked child whose parent merged, is rebased, with the commits kept and the gates re-run. A conflict after the push ends `needs-human`.
- `push-explained`: A run that pushed records `push.why` and `push.changes`. A rebase compared tree identity before and after it.
- `explicit-staging`: Stage only manifest paths, one by one.
- `base-untouched`: Never commit or push to `main` or to the PR's base.
- `fail-closed-reads`: A failed read stops the run `failed`. The mergeability check is the exception, and ends `needs-human`.
- `complete-listings`: Every listing is paginated to the end, or the run ends `failed`.
- `truthful-report`: The report and the run result describe only what happened.
- `status-preserved`: No command's failure is lost.
- `attribution-policy`: Attribution is `none`. Commits, PR bodies and comments carry no attribution, and nothing claims that a person reviewed or approved the change.
- `run-result-written`: `result.json` is written atomically on every exit path.
- `gates-final-tree`: `gates` lists only the runs on the final tree.
- `install-before-gates`: `uv sync --locked` runs before every gate run, again after a rebase, and again after a dependency change.
- `push-failure-states`: A hook rejection is fixed and pushed again. Any other failed push restores the HEAD and ends `needs-human` for a permission refusal, or `failed` for anything else.
- `collapse-remote-contained`: The remote head equals the inspected sha, and is an ancestor of the pre-collapse head, before the collapse rewrites anything.
- `collapse-content-preserved`: An empty net change, or a tree mismatch, aborts the collapse and restores the pre-collapse HEAD.
- `collapse-keeps-link`: The collapsed message carries the link settled in step 11, with its **Deferred** list.

## Forbidden actions

- `push-red`: pushing with a failing required gate to clear comments.
- `piecemeal-push`: pushing once per comment instead of once per round.
- `resolve-pushback`: resolving a thread where the revision disagreed with the reviewer.
- `resolve-unagreed-deferral`: resolving a deferral that only the reviser decided on.
- `apply-unreproduced-import`: applying an imported finding that does not reproduce on this branch.
- `collapse-with-open-threads`: collapsing while any thread on this PR will remain open.
- `pull-after-collapse`: pulling into a checkout after a collapse. Hard-reset it to the remote instead.
- `content-free-push-after-approval`: pushing a collapse, or a rebase that is not required, while the PR holds 1 approval that the push would dismiss. A required rebase still goes ahead.
- `bare-force-push`: force-pushing without `--force-with-lease=<branch>:<sha>`.
- `admin-bypass`: merging, pushing or rewriting with admin privileges (`gh pr merge --admin` and the like).
- `bypass-hook`: skipping or redirecting the repository's verification in any form, or retrying a rejected commit or push through another route.
- `machine-specific-paths`: hard-coding home directories, private scripts or services.
- `commit-foreign-edits`: committing changes this run did not make.
