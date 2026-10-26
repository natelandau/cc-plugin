---
name: gha
description: Analyze GitHub Actions failures and identify root causes. Use when asked to investigate a CI/CD GitHub Actions failure and recommend a fix.
argument-hint: <url>
disable-model-invocation: true
---

Investigate this GitHub Actions URL: $ARGUMENTS

Use the `gh` CLI to analyze the workflow run.

1. Identify the actual failure. Find which workflow and job failed, when, and
   on which commit. Read the full logs to find what caused the non-zero exit.
   Separate warnings and non-fatal errors from the real failure. Look for
   markers such as "failing:" and "fatal:", and for the script logic that
   decides when to exit 1. When the logs show both non-fatal and fatal errors,
   focus on the one that caused the exit.

2. Check flakiness. Review the past 10 to 20 runs of the exact job that
   failed, not the workflow as a whole. Use
   `gh run list --workflow=<workflow-name>` to get the run ids, then
   `gh run view <run-id> --json jobs` to read that job's status in each run.
   Answer three questions: is this a one-time failure or a recurring pattern
   for this job, what is its recent success rate, and when did it last pass?

3. Identify the breaking commit, if the job fails in a pattern. Find the first
   run where the job failed and the last run where it passed, and identify the
   commit between them. Confirm it: the job fails in every run after that
   commit and passes in every run before it. Report the commit only when
   confirmed.

4. Find the root cause. Combine the logs, the history, and any breaking commit
   into the likely cause. Focus on what caused the failure, not on every error
   in the logs. Confirm your hypothesis against the logs and the failure
   logic.

5. Check for an existing fix. Search open PRs with
   `gh pr list --state open --search "<keywords>"`, using the error messages
   or file names. Check whether any open PR modifies the failing file or
   workflow. If a fix PR exists, include it in the report and skip the
   recommendation.

Write a final report with:

- the failure summary: what triggered the non-zero exit;
- the flakiness assessment: one-time or recurring, with the success rate;
- the breaking commit, if identified and confirmed;
- the root cause;
- the existing fix PR, if found, with its number and link;
- a recommendation, unless a fix PR exists.
