---
name: gha
description: Analyze GitHub Actions failures and identify root causes. Use when asked to investigate a CI/CD GitHub Actions failure and recommend a fix.
argument-hint: <url>
disable-model-invocation: true
---

Investigate this GitHub Actions URL with the `gh` CLI: $ARGUMENTS

1. **Actual failure.** Which workflow and job failed, when, on which commit. Read the
   full logs for what caused the non-zero exit. Separate warnings and non-fatal errors
   from the real failure: look for markers such as "failing:" and "fatal:" and the
   script logic that decides when to exit 1. With both, focus on the one that caused
   the exit.

2. **Flakiness.** Review the past 10 to 20 runs of the exact failed job, not the whole
   workflow: `gh run list --workflow=<workflow-name>` for run ids, then
   `gh run view <run-id> --json jobs` for that job's status. One-time or recurring?
   Recent success rate? Last pass?

3. **Breaking commit**, if the job fails in a pattern. Find the first failing and last
   passing run and the commit between. Report it only when confirmed: the job fails in
   every run after it and passes in every run before.

4. **Root cause.** Combine logs, history, and any breaking commit. Focus on what caused
   the failure, not every logged error. Confirm the hypothesis against the logs and the
   failure logic.

5. **Existing fix.** `gh pr list --state open --search "<keywords>"` with error messages
   or file names; check whether an open PR modifies the failing file or workflow.

Report: failure summary (what triggered the exit); flakiness (one-time or recurring,
success rate); confirmed breaking commit, if any; root cause; existing fix PR with
number and link, if found; a recommendation, unless a fix PR exists.
