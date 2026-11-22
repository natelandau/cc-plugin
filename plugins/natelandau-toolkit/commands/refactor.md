---
name: refactor
description: Review existing code in any language for behavior-preserving refactor opportunities with a multi-agent deep review by default (or a fast inline pass with --quick), refute inapplicable findings, and optionally apply the safe ones with --fix. Targets a function, class, file, folder, module, package, or the whole project.
disable-model-invocation: true
argument-hint: "[--quick] [--fix] [<target>]"
---

# /refactor: behavior-preserving refactor

Review existing code for refactor quality (readability, maintainability, design) and
optionally apply the safe findings. External behavior never changes.

## Scope

- Every applied change yields identical outputs and side effects. A behavior-changing
  finding is reported, never applied.
- Security is out of scope; point at a dedicated security review.
- Bugs, behavior-changing optimizations, and language pitfalls (Python mutable default
  arguments, JS `==` coercion, Go nil-map writes): report as out-of-scope notes pointing
  at `/code-review`. Never fix them.
- Small steps, one concern at a time, tests as the baseline.

## Arguments

Parse `$ARGUMENTS`:

- QUICK: `true` if `--quick` appears anywhere. `false` (default): full multi-agent deep
  review. `true`: fast inline pass, no subagents.
- FIX: `true` if `--fix` appears anywhere.
- TARGET: the rest. A function, class, file, folder, module, or package. Empty: the
  whole project under the cwd.

Echo mode (`quick` or `deep`), FIX, and TARGET in one line before proceeding.

## Phase 1: Scope

1. Resolve TARGET to files or regions:
   - Path: that path.
   - Dotted module or package (`pkg.sub`): its files on disk.
   - Bare symbol: grep for its definition. Several matches: list them and ask which.
   - Empty: the whole project.

   Nothing resolves: stop and report "nothing to review".

2. Identify the target languages. Read every standard that exists:
   - `~/.claude/CLAUDE.md`
   - repo-root `CLAUDE.md` and any `CLAUDE.md` in an ancestor directory of a target file
   - language standards or style rules for the target's file types, plus project rules

3. Record the test BASELINE.
   - FIX true: get `GREEN` or `RED` from the project's gates. Deep mode: dispatch the
     `natelandau-toolkit:test-runner` subagent, which discovers the tooling and returns
     the verdict plus failures. Quick mode: run the gates inline.
   - FIX false: run nothing. Note only whether a test suite exists.

4. Build the SCOPE BLOCK for every finder: resolved file list, one-paragraph summary of
   what the code does, loaded conventions, verbatim TARGET instructions. Focus or skip
   instructions in TARGET override an angle's default breadth.

## Phase 2: Find

Quick mode: skip Phases 2-4; go to "Quick path".

Deep mode: dispatch each angle in parallel as the read-only
`natelandau-toolkit:review-finder` subagent, with the SCOPE BLOCK, its single angle
prompt, and the candidate schema. Angles: idioms, simplification, reuse, conventions,
docs-and-comments, efficiency, pitfalls, altitude, plus structure when TARGET is a
directory. At most 8 candidates per angle.

Candidate schema:

- `file` (string), `line` (number), `summary` (one line)
- `rationale`: why it improves the code
- `proposed_change`: the concrete simpler or clearer form
- `kind`: `mechanical` (local, behavior-neutral edit) or `structural` (extract, move,
  split, generalize)
- `angle`: the producing angle id

Finders return every candidate with a real rationale, half-believed ones too; the
verifier judges next. Nothing found: empty list.

### Angle prompts

Judge each file by its own language's idioms, standards, and pitfalls.

**idioms**: Adherence to the language's idioms, typing, naming, and style per the
loaded standards, and behavior-preserving modernizations. Examples: Python `os.path` to
`pathlib`, `%` or `.format` to f-strings, `List`/`Optional` to `list`/`| None`; JS `var`
to `const`/`let`, callbacks to async/await; equivalents in other languages. All
`mechanical`.

**simplification**: Unnecessary complexity: redundant or derivable state, copy-paste
with slight variation, deep nesting an early return or guard clause can flatten, dead
code (unreachable branches, unused locals or imports). Name the simpler form. Dead-code
removal and flattening: `mechanical`. Consolidating duplicated logic: `structural`.

**reuse**: Code re-implementing something the project already provides. Grep shared and
utility modules and files adjacent to the target; name the helper to call. `structural`.

**structure** (directory targets only): File and directory organization: modules doing
too much, code in the wrong module, circular-import-prone layouts. `structural`.

**efficiency**: Wasted work: redundant computation or repeated I/O, independent
operations run sequentially, blocking work on a hot path, long-lived objects built from
closures that keep a whole scope alive (prefer a class copying only the fields it
needs). Name the cheaper alternative and state whether the fix preserves behavior
(hoisting an invariant, de-duplicating I/O, memoizing a pure call, copying fields) or
changes it (parallelization, laziness that shifts side effects, caching a mutable
value). Preserving: `mechanical` or `structural`. Changing: flag it so Phase 3 routes
it to report-only.

**altitude**: Code at the right depth, not a fragile workaround. Special cases layered
on shared infrastructure mean the code is not deep enough; prefer generalizing the
underlying mechanism. `structural`.

**conventions**: Find the CLAUDE.md, rules, and standards governing the target and flag
clear violations. Quote the exact rule, the exact breaking line, and the source path.
No style preferences, no "spirit of the doc" inferences. `mechanical` (naming,
formatting, docstring rule) or `structural` (a rule requiring reorganization). Nothing
applies: return nothing.

**docs-and-comments**: Rewrite API docs in the language's convention (Python
docstrings, JSDoc, godoc, rustdoc) and the project's required format, explaining why a
developer uses the unit. Rewrite inline comments to explain why, not what. Flag and
remove comments that restate the code. `mechanical`.

**pitfalls** (report-only): The language's classic bug-class traps: Python mutable
default arguments and late-binding closures, JS falsy-zero and `==` coercion, Go
nil-map writes and range-variable capture, SQL injection, float equality. Leave `kind`
unset; every pitfalls finding routes to REPORT_ONLY by angle.

## Phase 3: Verify and refute

Deep mode only. Dispatch one read-only `natelandau-toolkit:review-verifier` per
candidate with the SCOPE BLOCK and the candidate, and ask it to judge behavior
preservation too. It returns `KEEP`, `PLAUSIBLE`, or `REFUTED` plus "behavior-preserving?
yes/no".

Drop REFUTED candidates; record each in one line for the report.

Route by the behavior-preserving judgment, not the angle:

- Behavior-preserving and KEEP or PLAUSIBLE: apply-eligible.
- Behavior-changing, or any `pitfalls` finding: report-only.

## Phase 4: Synthesize

1. Gap sweep (deep mode): dispatch one fresh `natelandau-toolkit:review-finder` with the
   survivors. It hunts only for missed opportunities (moved code that lost clarity,
   second-tier duplication, asymmetric setup and teardown). Verify new candidates
   through Phase 3.
2. Merge candidates with the same root cause; keep the clearest rationale.
3. Partition:
   - `APPLY_MECHANICAL`: behavior-preserving, `kind: mechanical`
   - `APPLY_STRUCTURAL`: behavior-preserving, `kind: structural`
   - `REPORT_ONLY`: behavior-changing, including all pitfalls
4. Rank each list most-impactful first. Cap the combined total at 12 (deep) or 5
   (quick); drop the least impactful and note the trimmed count. Never drop a
   REPORT_ONLY safety note silently.

## Phase 5: Report

Always print these sections. Without `--fix`, this is the full output.

1. Apply-eligible: `APPLY_MECHANICAL` then `APPLY_STRUCTURAL`, each as
   `path/to/file:LINE - summary`, then rationale, proposed change, and one confidence
   label: Confirmed (any merged verdict is KEEP) or Worth considering (all PLAUSIBLE).
   Never print raw verdict tokens.
2. Out of scope (report-only): each `REPORT_ONLY` finding with its summary and
   "behavior-changing; consider `/code-review`."
3. Refuted: one line each.

FIX false: stop. FIX true: Phase 6.

## Phase 6: Apply (--fix)

Never touch `REPORT_ONLY`.

Precondition: BASELINE green. If red, or absent where the project clearly expects tests,
refuse to apply, explain that a red suite cannot detect regressions, report the
findings, and stop.

Apply `APPLY_MECHANICAL` only, in coherent batches (all dead-code removals, all
docstring rewrites, all idiom modernizations). Every batch boundary leaves the code
internally consistent.

Per batch:

1. Apply it.
2. Re-run the gates. Deep: dispatch `natelandau-toolkit:test-runner` again. Quick: run
   the suite, and pre-commit if configured, inline.
3. `GREEN`: commit with a message naming the technique ("remove dead code in <area>").
   `RED`: revert the batch, stop, and report the failure.

On `main` or `master`: apply and verify but do not commit (the branch-protection hook
blocks it). Leave the changes staged and tell the user to create a feature branch.

Never auto-apply `APPLY_STRUCTURAL`. Emit it as an ordered refactor plan for the user's
sign-off.

### Characterization-test scaffolding (deep mode)

Before proposing a structural change to untested code, scaffold a safety net:

- Test at the stable seam, one level above the largest thing the refactor moves, so the
  tests survive it:
  - function internals, signature kept: a unit test on the function
  - class methods: the class's public methods
  - module or package: its public API
  - whole project: end-to-end or smoke tests on the CLI or HTTP entry points
- Pin current behavior, bugs included. A revealed bug is a separate fix in a separate
  commit.
- Surface the tests for review, then commit them on their own before any refactor
  commit. Complex output: golden-master snapshot (capture, refactor, diff).

## Quick path

No subagents, no test scaffolding, no verifier. Read the target once and surface at most
5 behavior-preserving findings across simplification, reuse, dead code, and docstrings
or comments, judging them yourself. Partition into the same three lists (no refuted
list). Go to Phase 5, then Phase 6 if `--fix`: apply only mechanical findings under the
same green precondition and per-batch gate.
