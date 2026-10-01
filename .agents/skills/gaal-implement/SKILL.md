---
name: gaal-implement
description: Implements one qualified GitHub issue in 116-Labs/cuecal as a verified change on its own `gaal/` branch holding exactly one commit, then writes the run result to `$GAAL_RUN_DIR/result.json`. Use when a dispatch hands you a repo and issue number that already passed qualification and asks for the `implement` step, before any PR exists. Do not use to open a PR, revise a PR after review, review a PR, or merge; those are other steps. Do not use for issues that have not been qualified.
---
<!-- gaal-stamp blueprint=implement@1.4.0 shared=1.3.0 profile=7d4c49f36df8465f generated=2026-10-01 content=cb32a06cc7698dda -->

# gaal-implement

Take one qualified issue of `116-Labs/cuecal` and produce a branch off `main` holding exactly one commit. The commit satisfies the issue's acceptance criteria and passes every profile gate. `open-pr` takes it from there. This run never pushes, never opens a PR and never merges.

## Run context

- The dispatch gives the issue number. The repo is `116-Labs/cuecal`, the base is `main`, and the tracker is GitHub.
- `<run-dir>` below stands for the literal run directory path from the run context (the value of `GAAL_RUN_DIR`). The run id is the value of `GAAL_RUN_ID`. Write both out literally in every command and file. Never expand an environment variable in a command, never put `NAME=value` before a command, and never use `$(...)` or backticks.
- The run is headless. It cannot ask anyone anything (`ask-mid-run`). Anything you would ask becomes `needs-clarification` with questions.
- Allowed shell commands: `git`, `gh`, `mkdir`, `mv`, `cp`, `ls`, `cat`, `date`, `pwd` with any arguments, plus exactly `uv run ruff check .` and `uv run pytest`. Run one command per call, with no `&&`, `;` or `|` chains. Write files with the file-editing tool, never with shell redirection.
- The profile names no `install` command and no `preflight` command. Install nothing. Work and run the gates in this checkout, where the dependencies are already installed. A throwaway worktree would have no install, so do not use one for gates.
- Scratch files go under `<run-dir>/scratch` (create it with `mkdir -p <run-dir>/scratch` if needed), never in `/tmp`.

## Steps

1. **Start the clock and the result record.** Run `date -u +%Y-%m-%dT%H:%M:%SZ` and keep the value as `started_at`. Note the run id and the issue number. Keep a running list of the gates you run (name, command, exit code, duration) and an attempt counter at 0. From here on, every exit path ends at step 14.

2. **Resolve the repo and the issue.** Run `git remote get-url origin` and confirm it is `116-Labs/cuecal`. Run `gh issue view <N> --repo 116-Labs/cuecal --json number,title,body,state,labels`. If the repo or the issue cannot be resolved, or a call fails (auth, rate limit, network), end as `failed` with enough in `reason` to retry. Never guess, and never turn a failed call into "no comments" (`fail-closed-reads`).

3. **Read the issue and every comment.** Fetch comments to the end: `gh api repos/116-Labs/cuecal/issues/<N>/comments --paginate` (`complete-listings`). Comments that clarify or narrow scope are part of the spec; prefer comments starting with `**Clarification**`, `**Clarification (rewrite)**` or `**Clarification (scope narrow)**`. When a comment says the body was rewritten, the current body wins. List the acceptance criteria explicitly, numbered.

4. **Check the state of the checkout.** Run `git status --porcelain` and `git branch --show-current`. Ignore untracked files under `<run-dir>`. Any other pre-existing edit is someone else's work (`absorb-stray-edits`, `commit-foreign-edits`): record the dirty paths, never commit, revert or reformat them. Handle them in step 6. Also run `git fetch origin main`. If the fetch fails, end as `failed`.

5. **Check references and look for reuse.** Check every file, symbol and line the issue references against the current code, and record any drift. Search the code for an existing module that already owns the capability the issue adds, and extend it rather than building a parallel one. If building new is justified, record why in the plan. If the issue is ambiguous, or the code has drifted beyond what a plan can safely assume, end as `needs-clarification` with specific, answerable questions that each name the file or criterion concerned (`ask-mid-run`).

6. **Resolve resumable work and a resume marker.**
   - Run `git branch --list 'gaal/*'` and look for an existing branch for this issue (name starts with `gaal/<N>-`). Resume it if its state is sound (its commits are on top of current `main`, tree clean). Otherwise start fresh.
   - If the prompt handed over a resume marker, adopt it only when all three hold: its branch is checked out, its base matches the base you are using (`main`), and the dirty paths are exactly the marker's `paths`. Those edits are this issue's work, not stray edits. Take the marker's `plan` as the starting plan, put its `paths` into this run's manifest, reset the attempt counter to 0, and go straight to step 10 (gates). Keep `plan-before-code` satisfied by reading the marker's saved plan and copying it to `<run-dir>/plan.md`.
   - A marker that does not match is ignored. If the checkout then has dirty paths that are not the run's own, end as `needs-human`. `reason` lists the dirty paths and, when a marker was handed over, which condition failed: the marker's branch is not checked out, the base differs, or the dirty paths differ from the marker's `paths`.
   - If the checkout is on `main` with commits ahead of `origin/main`, do not commit there (`base-untouched`). Move any such work off the base only if it is clearly yours; otherwise end as `needs-human`.

7. **Write the plan before any source edit (`plan-before-code`).** List the files to change, the tests to add, and, for every numbered acceptance criterion, how it will be shown to hold. Add the drift and reuse notes from step 5. Save it with the file tool as `<run-dir>/plan.md`. Do not edit any source file before this file exists. Check the plan against these guards; if it needs one of them, end as `needs-human` naming the guard and what a person should do:
   - A breaking change to a public contract, CLI surface, config format, keyring secret layout or the SQLite state schema or any persisted format, when the issue does not explicitly ask for it (`unapproved-breaking-change`).
   - Anything that deploys, publishes, or runs against a shared environment (`deploy`). Return the commands for a human instead of running them.

8. **Create the branch off the base.** Unless you resumed a branch in step 6, run `git switch -c gaal/<N>-<slug> origin/main`, where `<slug>` is a short lowercase kebab-case summary of the issue title. The branch prefix is `gaal/`. Never commit on `main`.

9. **Implement the plan.** Read each file before changing it. Keep edits minimal and in scope. Do not fix pre-existing debt outside the change (`unrelated-refactor`); note it for the final report. Add the tests the plan calls for. Keep a manifest of every path you write or create, one per line, as `<run-dir>/manifest.txt` (write it with the file tool, and update it whenever a path is added). A path missing from the manifest is damage: it ends up in a later commit or is lost. Never include files you did not write.

10. **Run every gate on the current tree, in order, as separate commands.** Increment the attempt counter before each full pass.
    1. `date -u +%s`, then `uv run ruff check .`, then `date -u +%s`. Record the `lint` gate: command `uv run ruff check .`, exit code, and `duration_ms` as the difference of the two times times 1000.
    2. `date -u +%s`, then `uv run pytest`, then `date -u +%s`. Record the `test` gate the same way with command `uv run pytest`.
    - Both gates are required (`gates-green`). Run them exactly as written, with nothing added. Do not claim a gate passed that did not run; a gate that did not run is absent from the result (`truthful-report`). Never lose an exit code to a pipe or filter (`status-preserved`).
    - If a gate fails, read its output, fix the cause (never skip, weaken or delete the check), update the manifest, and run both gates again on the new tree. Gate-fix cycles stop at 3 attempts (`bounded-attempts`).
    - When the third attempt still fails, end as `needs-human` with the failing gate's output summarized in `reason` (one sentence, at most 160 characters; put detail in the final message). If the work is uncommitted, first write the resume marker (step 11).
    - A pass counts only when both gates exit 0 on the final tree, with no edits made after them.

11. **Resume marker (only on the attempt-limit exit with uncommitted work).** With the file tool, write `<run-dir>/resume.json` containing: `schema_version` 1, `run_id`, `issue`, `branch`, `base` (`main`), `paths` (the manifest, which must be exactly the dirty tree you leave behind; remove any path from the tree or the manifest until they agree) and `plan` (the path of the saved plan, `<run-dir>/plan.md`, or null). Then skip to step 14 with status `needs-human`. Do not commit or revert the work; Gaal hands the marker to the next implement run of this issue.

12. **Stage the manifest and create one commit with the hooks enabled.**
    - Stage by explicit path: `git add -- <path> <path> ...`, listing every manifest path (`explicit-staging`). Never stage everything wholesale and never use the commit-all shortcut.
    - Run `git diff --cached --name-only` and compare with the manifest. The staged set must equal the manifest exactly (`manifest-matches-staged`). Run `git status --porcelain`: no other change this run is responsible for may remain, and pre-existing foreign edits must still be untouched and unstaged. If the sets differ, fix the manifest or the staging; never commit paths this run did not write.
    - Write the message with the file tool to `<run-dir>/commit-msg.txt`. It follows the conventional-commit convention (`type(scope): subject`, subject in the imperative, no trailing period), describes the change as a whole rather than the process, and carries no AI attribution and no `Co-Authored-By` trailer: the profile's attribution policy is `none` (`attribution-policy`).
    - Link the issue by the issue-link rule (`issue-trailer`). If every acceptance criterion is met, end the message with a line `Closes #N`. Otherwise end with `Refs #N` on a line of its own, never a closing keyword, and add a **Deferred** heading listing each criterion left open, worded as the issue words it. Never put `Closes` next to a Deferred list.
    - Commit with `git commit -F <run-dir>/commit-msg.txt`. Hooks stay enabled. If a hook rejects the commit, treat it as a failing gate: read its output, fix what it reports, restage the manifest and commit again, counting it against the 3 attempts. Never skip, bypass or redirect hooks, never change where git looks for hooks, never edit hook files or git config (`bypass-hook`). If the hook's complaint is beyond this run's remit, end as `failed` naming the hook and quoting its output briefly. If a fix changes the tree, re-run both gates (step 10) before committing again.

13. **Collapse to one commit, in place.** Run `git rev-list --count origin/main..HEAD`. The profile's merge regime takes the squash message from the commits (`message_source: commits`), so the branch must hold one commit (`single-commit`). If the count is 1, nothing to do. If it is more than 1, apply the in-place collapse:
    - Record the tree hash: `git rev-parse 'HEAD^{tree}'`, and the old sha: `git rev-parse HEAD`.
    - Confirm every commit on the branch is yours (`git log --format=%an origin/main..HEAD`); if any commit was authored by someone else, stop and end as `needs-human`.
    - Run `git reset --soft origin/main`. Write one message for the whole change (same rules as step 12) and run `git commit -F <run-dir>/commit-msg.txt`.
    - Check that `git rev-parse 'HEAD^{tree}'` equals the recorded tree hash. If not, restore with `git reset --hard <old-sha>` (the old sha you recorded) and end as `failed`. If the soft reset nets to an empty change, restore the same way and stop.
    - Never use an interactive rebase. Finally confirm `git rev-list --count origin/main..HEAD` prints 1, and `git status --porcelain` shows no leftover change from this run. Record the commit sha with `git rev-parse HEAD` as `commit_sha` (40 hex characters).
    - The branch is not pushed. Do not push anything in this step. Never commit or push to `main` (`base-untouched`).

14. **Write the run result on every exit path.** Run `date -u +%Y-%m-%dT%H:%M:%SZ` for `finished_at`. With the file tool write `<run-dir>/result.json.tmp`, then run `mv <run-dir>/result.json.tmp <run-dir>/result.json`. Never leave the `.tmp` file behind (`run-result-written`). The JSON object has exactly these keys:
    - `schema_version`: 1
    - `run_id`: the run id from the run context
    - `blueprint`: `"implement"`
    - `blueprint_version`: `"1.4.0"`
    - `repo`: `"116-Labs/cuecal"`
    - `issue`: the issue number (integer), or null if it could not be resolved
    - `pr`: null
    - `status`: one of `done`, `needs-human`, `needs-clarification`, `failed`
    - `reason`: required unless `done`; one sentence of at most 160 characters naming the decision or action needed
    - `questions`: required and non-empty for `needs-clarification`, each specific and naming the file or criterion; omit otherwise
    - `attempts`: integer of at least 1; the number of gate-fix passes consumed (use 1 when the run stopped before any gate ran)
    - `gates`: the gates that actually ran on the final tree, each `{name, command, exit_code, duration_ms}`; an empty list when none ran
    - `branch`: the branch name, or null when none was created
    - `commit_sha`: the 40-hex sha of the single commit, or null when there is no commit
    - `started_at`, `finished_at`: timestamps from `date`, never estimated
    - Do not add other keys. The result and the final message describe only what actually happened (`truthful-report`).
    - In the final message (not in `reason`), list each acceptance criterion as met or not met, name the gates that ran and any that did not and why, and record pre-existing debt noticed but left alone.

## Exit states

- `done`: The single commit exists, all required gates exit 0 on the final tree, `branch`, `commit_sha` and `gates` are set. The final message lists each acceptance criterion as met or not met. A partial result uses `Refs #N` and a Deferred list, never a closing keyword.
- `needs-clarification`: The spec is ambiguous or the code has drifted from what the issue describes. `questions` are specific and answerable, each naming the file or criterion it concerns. No source edit has been made.
- `needs-human`: The attempt limit (3) was reached, leaving a resume marker when the work is uncommitted. Or a risky-surface guard fired (breaking change to a public contract or persisted format, deploy, shared-environment action). Or the checkout had edits of unclear ownership (edits matching a handed-over resume marker are not). `reason` says which and what a person should do; for the ownership refusal it lists the dirty paths and, when a marker was handed over, which adoption condition failed.
- `failed`: Environment or tooling problems (repo unreachable, an API call failing, a hook rejection beyond this run's remit, a collapse that failed content preservation, disk). `reason` includes enough to retry.

## Invariants

- `plan-before-code`: `<run-dir>/plan.md` exists before the first source edit, and every acceptance criterion maps to part of it.
- `single-commit`: At hand-off the branch has exactly one commit ahead of `main` (`git rev-list --count origin/main..HEAD` prints 1).
- `manifest-matches-staged`: The files in the commit are exactly the manifest of paths this run wrote.
- `gates-green`: `uv run ruff check .` and `uv run pytest` both ran on the final tree and exited 0, and the result lists each one.
- `issue-trailer`: The commit message links the issue: `Closes #N` only when every acceptance criterion is met, otherwise `Refs #N` and a Deferred list naming each open criterion.
- `bounded-attempts`: Gate-fix cycles stop at 3 attempts; the run then ends as `needs-human`, never as an endless loop.
- `explicit-staging`: Stage only paths this run wrote, by explicit path, from the manifest.
- `base-untouched`: Never commit or push to `main`.
- `fail-closed-reads`: A failed API call stops the run; it never becomes "no comments" or "no issue".
- `complete-listings`: Comment listings are paginated to the end or the run stops.
- `truthful-report`: The result and final message describe what happened; a gate that did not run is absent, not passed.
- `status-preserved`: A command's failure is never lost to a pipe, filter or guard.
- `attribution-policy`: Attribution is `none`: no AI attribution, no trailers added on your own initiative.
- `run-result-written`: `result.json` is written atomically on every exit path, including failures.

## Forbidden actions

- `absorb-stray-edits`: Committing, reverting or reformatting changes that were in the checkout before the run.
- `deploy`: Running deploys, migrations against shared environments or publishes. Return the commands for a human instead.
- `unapproved-breaking-change`: Breaking a public contract, schema or persisted format without the issue explicitly asking for it.
- `unrelated-refactor`: Fixing pre-existing debt outside the change's scope. Record it in the report instead.
- `ask-mid-run`: Waiting on interactive input. End as `needs-clarification` with questions instead.
- `bare-force-push`: Force-pushing without an explicit lease on the inspected sha. This run does not push at all; if a push ever becomes necessary elsewhere, it must use an explicit `--force-with-lease=<branch>:<sha>`.
- `admin-bypass`: Merging, pushing or rewriting with admin privileges to get around branch protection or a verification hook.
- `bypass-hook`: Committing or pushing with verification skipped or redirected, changing where git looks for hooks, switching a hook manager off, or retrying a rejected commit through another route. Fix what the hook reports.
- `machine-specific-paths`: Hard-coding a person's home directory, private scripts or services.
- `commit-foreign-edits`: Committing changes this run did not make.

## Lessons applied

- A path missing from the manifest does real damage; check `git diff --cached --name-only` against `<run-dir>/manifest.txt` before committing.
- Review the work before anything leaves the machine; this run does not push, so fix everything now rather than after submission.
- Report validation exactly: which gates ran, which did not, and why.
- Stopping at the attempt limit with an untested fix leaves a tree a re-run would refuse as unclear ownership; the resume marker (step 11) prevents that.
