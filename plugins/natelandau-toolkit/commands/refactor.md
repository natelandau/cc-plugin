---
name: refactor
description: Review existing code in any language for behavior-preserving refactor opportunities with a multi-agent deep review by default (or a fast inline pass with --quick), refute inapplicable findings, and optionally apply the safe ones with --fix. Targets a function, class, file, folder, module, package, or the whole project.
argument-hint: "[--quick] [--fix] [<target>]"
---

# /refactor: behavior-preserving refactor

Restructure code to improve readability, maintainability, and design without
changing external behavior. This is a disciplined review-and-apply process, not
freeform editing. It complements `/code-review`, which hunts bugs in a diff.
This command reviews existing code for refactor quality.

## Scope and promise

- Behavior is always preserved. Every change applied with `--fix` must produce
  identical outputs and side effects. A fix that changes behavior is reported,
  never applied.
- Security is out of scope. Use a dedicated security review.
- Bugs, behavior-changing optimizations, and language pitfalls (Python mutable
  default arguments, JS `==` coercion, Go nil-map writes) are reported as
  out-of-scope notes that point at `/code-review`. They are never auto-fixed.
- The golden rules of refactoring hold: behavior preserved, small steps, one
  concern at a time, tests as the baseline.

## Arguments

Parse `$ARGUMENTS` into three values:

- QUICK: `true` if the token `--quick` appears anywhere, otherwise `false`.
  `false` (the default) runs the full multi-agent deep review. `true` runs a
  fast inline pass with no subagents.
- FIX: `true` if the token `--fix` appears anywhere, otherwise `false`.
- TARGET: everything left after removing `--quick` and `--fix`. It can name a
  function, class, file, folder, module, or package, or be empty. If empty,
  default to the current working directory (the whole project).

Echo the parsed mode (`quick` or `deep`), FIX, and TARGET back to the user in
one line before you proceed.

## Phase 1: Scope

1. Resolve TARGET into concrete files or regions:
   - A path (file or folder): that path.
   - A dotted module or package (`pkg.sub`): its files on disk.
   - A bare symbol (a function or class name): grep for its definition. If it
     resolves to more than one definition, list them and ask which one.
   - Empty: the whole project under the current working directory.

   If the resolved set is empty, stop and report "nothing to review".

2. Identify the target languages and load the standards a refactor must
   honor. Read each that exists:
   - `~/.claude/CLAUDE.md` (user global)
   - the repo-root `CLAUDE.md` and any `CLAUDE.md` in an ancestor directory of
     a target file
   - any language standards or style rules that apply to the target's file
     types, plus any project rules

3. Record the test BASELINE. If FIX is true, get a `GREEN` or `RED` baseline
   from the project's gates. In deep mode, dispatch the `test-runner` subagent
   (it ships with this plugin, discovers the project's own tooling, and returns
   the verdict plus any failures). In quick mode, run the gates inline. If FIX
   is false, run nothing. Only note whether a test suite exists, because Phase
   6 will not run.

4. Build the SCOPE BLOCK that goes to every finder: the resolved file list, a
   one-paragraph summary of what the code does, the loaded conventions, and
   the verbatim TARGET instructions. Focus or skip instructions in TARGET
   override an angle's default breadth.

## Phase 2: Find

In quick mode, dispatch no subagents. Skip the rest of Phase 2 and all of
Phase 3, and go to the "Quick path" below.

In deep mode, select the finder angles by TARGET and dispatch each in parallel
as the `review-finder` subagent (it ships with this plugin and is read-only).
Give each one the SCOPE BLOCK, its single angle prompt, and the candidate
schema. It returns candidate findings in that schema.

Angle selection: dispatch idioms, simplification, reuse, conventions,
docs-and-comments, efficiency, pitfalls, and altitude. Add structure only when
TARGET is a directory. Up to 8 candidates per angle. After the first pass, run
one gap-sweep finder (Phase 4).

Candidate schema, per finding:

- `file` (string), `line` (number), `summary` (one line)
- `rationale`: why it improves the code
- `proposed_change`: the concrete simpler or clearer form
- `kind`: `mechanical` (a local, behavior-neutral edit) or `structural`
  (extract, move, split, or generalize)
- `angle`: the angle id that produced it

A finder passes every candidate with a real rationale through, including
half-believed ones. The verifier judges them next. An angle that finds nothing
returns an empty list.

### Angle prompts

Every angle applies to the target file's language. For a mixed-language
target, judge each file by its own language's idioms, standards, and pitfalls.

**idioms**: Review the code for adherence to the target language's idioms,
typing, naming, and style per the loaded standards, and for behavior-preserving
modernizations. Examples: Python `os.path` to `pathlib`, `%` or `.format` to
f-strings, `List` or `Optional` to `list` or `| None`. JS `var` to `const` or
`let`, callbacks to async/await. Apply the equivalent for the file's language.
Surface only changes that preserve behavior. Mark all `mechanical`.

**simplification**: Flag unnecessary complexity: redundant or derivable state,
copy-paste with slight variation, deep nesting that an early return or guard
clause can flatten, and dead code (unreachable branches, unused locals or
imports). Name the simpler form that does the same job. Dead-code removal and
flattening are `mechanical`. Consolidating duplicated logic is `structural`.

**reuse**: Flag code that re-implements something the project already
provides. Grep the shared and utility modules and the files adjacent to the
target, and name the existing helper to call instead. Mark `structural`.

**structure** (directory targets only): Recommend file and directory
organization improvements: modules that do too many things, code in the wrong
module, and circular-import-prone layouts. Mark `structural`.

**efficiency**: Flag wasted work: redundant computation or repeated I/O,
independent operations run sequentially, and blocking work on a hot path. Also
flag long-lived objects built from closures that keep an entire scope alive.
Prefer a class that copies only the fields it needs. Name the cheaper
alternative.
For each, state whether the fix preserves behavior (hoisting an invariant,
de-duplicating I/O, memoizing a pure call, copying fields) or changes it
(parallelization, laziness that shifts side effects, caching a mutable value).
Behavior-preserving ones are `mechanical` or `structural`. Flag
behavior-changing ones so Phase 3 routes them to report-only.

**altitude**: Check that code is implemented at the right depth rather than as
a fragile workaround. Special cases layered on shared infrastructure signal
that the code is not deep enough. Prefer generalizing the underlying mechanism
over adding special cases. Mark `structural`.

**conventions**: Find the CLAUDE.md, rules, and standards that govern the
target and flag clear violations. Quote the exact rule and the exact line that
breaks it. No style preferences and no "spirit of the doc" inferences. Name the
source path so the report can cite it. Mark each finding `mechanical` (a
naming, formatting, or docstring rule) or `structural` (a rule that requires
reorganizing code). If nothing applies, return nothing.

**docs-and-comments**: Rewrite API docs in the language's documentation
convention (Python docstrings, JSDoc, godoc, rustdoc) and the project's
required format, explaining why a developer uses the unit. Rewrite inline
comments to explain why, not what. Flag and remove comments that restate the
code. Mark `mechanical`.

**pitfalls** (report-only): Flag the classic bug-class traps of the target
language. Examples: Python mutable default arguments and late-binding
closures, JS falsy-zero and `==` coercion, Go nil-map writes and
range-variable capture, SQL injection, float equality. These are bug fixes, not refactors, so they are
reported and never applied. Leave `kind` unset. Phases 3 and 4 route every
pitfalls finding to REPORT_ONLY by angle.

## Phase 3: Verify and refute

In deep mode, dispatch one `review-verifier` subagent (read-only) per
candidate. Quick mode skips this phase. Give it the SCOPE BLOCK and the
candidate, and ask it to also judge behavior preservation. It returns one
verdict (`KEEP`, `PLAUSIBLE`, or `REFUTED`) plus "behavior-preserving?
yes/no": whether applying the change keeps outputs and side effects identical.

Drop REFUTED candidates, and record them briefly for the report.

Routing, the cardinal rule: the behavior-preserving judgment decides, not the
angle.

- behavior-preserving and KEEP or PLAUSIBLE: apply-eligible
- behavior-changing, or any `pitfalls` finding: report-only

## Phase 4: Synthesize

1. Gap sweep (deep mode): dispatch one fresh `review-finder` that sees the
   surviving candidates and hunts only for opportunities not already found.
   Examples: moved code that lost clarity, second-tier duplication, asymmetric
   setup and teardown. Verify any new candidates through Phase 3.
2. Merge candidates that describe the same root cause. Keep the one with the
   clearest rationale.
3. Partition the survivors into three lists:
   - `APPLY_MECHANICAL`: behavior-preserving, `kind: mechanical`
   - `APPLY_STRUCTURAL`: behavior-preserving, `kind: structural`
   - `REPORT_ONLY`: behavior-changing, including all pitfalls
4. Rank each list most-impactful first. Cap the combined total at 12 in deep
   mode (5 in quick mode). If the cap forces a cut, drop the least impactful.
   Never drop a REPORT_ONLY safety note silently. Note the count if trimmed.

## Phase 5: Report

Always print these sections. This is the full output when `--fix` is absent.

1. Apply-eligible findings: `APPLY_MECHANICAL` then `APPLY_STRUCTURAL`, each
   as `path/to/file:LINE - summary`, followed by the rationale, the proposed
   change, and one confidence label from the `review-verifier` mapping
   (Confirmed or Worth considering). Never print the raw verdict tokens.
2. Out of scope (report-only): each `REPORT_ONLY` finding with its summary and
   the note "behavior-changing; consider `/code-review`."
3. Refuted: each REFUTED entry on one line, so the user sees what was
   considered and dropped.

If FIX is false, stop here. If FIX is true, continue to Phase 6.

## Phase 6: Apply (--fix)

Never touch `REPORT_ONLY` findings.

Precondition: the BASELINE must be green. If it is red, or absent where the
project clearly expects tests, refuse to apply and explain why. A red suite is
not a trustworthy regression detector. Report the findings and stop.

Apply `APPLY_MECHANICAL` only. Group the fixes into coherent batches: all
dead-code removals together, all docstring rewrites together, all idiom
modernizations together. A batch boundary must be a state where the code is
internally consistent, never a half-finished restructure.

Per-batch gate:

1. Apply the batch.
2. Re-run the gates. In deep mode, dispatch the `test-runner` subagent again.
   In quick mode, run the suite (and pre-commit if configured) inline.
3. `GREEN`: commit with a conventional-commit message that names the technique
   (`refactor: remove dead code in <area>`). `RED`: revert the batch, stop, and
   report the failure.

Protected branches: on `main` or `master`, apply and verify but do not commit.
The branch-protection hook blocks it. Tell the user to create a feature branch,
and leave the changes staged.

`APPLY_STRUCTURAL` is never auto-applied. Emit it as a proposed, ordered
refactor plan for the user's sign-off.

### Characterization-test scaffolding (deep mode)

Before you propose a structural change to untested code, scaffold a safety net
so the refactor can be verified. Quick mode skips this.

- Test at the stable seam, one level above the largest thing the refactor
  moves, so the tests survive the restructuring:
  - function internals with the signature kept: a unit test on that function
  - class methods: the class's public methods
  - module or package: the module's public API
  - whole project: end-to-end or smoke tests on the CLI or HTTP entry points
- Pin current behavior, including bugs. These tests detect change, not
  correctness. If one reveals a bug, that is a separate fix in a separate
  commit.
- Surface the generated tests for review, then commit them on their own before
  any refactor commit. For complex output, prefer a golden-master snapshot:
  capture output, refactor, diff.

## Quick path

When `--quick` is set, dispatch no subagents and scaffold no tests. Read the
target code once and surface at most 5 behavior-preserving findings across
simplification, reuse, dead code, and docstrings or comments. There is no
verifier pass. Judge the findings yourself. Partition them into the same
`APPLY_MECHANICAL`, `APPLY_STRUCTURAL`, and `REPORT_ONLY` lists. `REFUTED` is
empty. Then go to Phase 5, and to Phase 6 if `--fix` is set, applying only
mechanical findings under the same green precondition and per-batch gate.
