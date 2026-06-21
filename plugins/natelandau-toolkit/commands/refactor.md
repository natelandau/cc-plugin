---
name: refactor
description: Review existing code in any language for behavior-preserving refactor opportunities with a multi-agent deep review by default (or a fast inline pass with --quick), refute inapplicable findings, and optionally apply the safe ones with --fix. Targets a function, class, file, folder, module, package, or the whole project.
argument-hint: "[--quick] [--fix] [<target>]"
---

# /refactor - behavior-preserving refactor

Carefully restructure code to improve readability, maintainability, and design
**without changing external behavior**. This is a disciplined review-and-apply process, not
freeform editing. It complements `/code-review` (which hunts bugs in a diff); this command
reviews existing code for refactor quality.

## Scope and promise

- **Behavior is always preserved.** Every change applied with `--fix` must produce identical
  outputs and side effects. If a fix would change behavior, it is reported, never applied.
- **Security is out of scope** - not reviewed here. Use a dedicated security review.
- **Bugs, behavior-changing optimizations, and language pitfalls** (e.g. Python mutable
  default args, JS `==` coercion, Go nil-map writes) are *reported* as out-of-scope notes
  pointing at `/code-review`, never auto-fixed.
- Follows the golden rules of disciplined refactoring: behavior preserved, small steps,
  one concern at a time, tests as the baseline.

## Arguments

Parse `$ARGUMENTS` into three values:

- **QUICK** - `true` if the token `--quick` appears anywhere; otherwise `false`. This selects
  the mode: `false` (default) runs the full multi-agent deep review; `true` runs a fast inline
  pass with no subagents.
- **FIX** - `true` if the token `--fix` appears anywhere; otherwise `false`.
- **TARGET** - everything left after removing `--quick` and `--fix`. May name a function,
  class, file, folder, module/package, or be empty. If empty, default to the current
  working directory (whole project).

Echo the parsed mode (`quick` or `deep`), `FIX`, and `TARGET` back to the user in one line
before proceeding.

## Phase 1: Scope

1. **Resolve TARGET into concrete files/regions.**
   - A path (file/folder) -> that path.
   - A dotted module/package (e.g. `pkg.sub`) -> its file(s) on disk.
   - A bare symbol (function/class name) -> grep for its definition; if it resolves to more
     than one definition, list them and ask which one.
   - Empty -> the whole project under the current working directory.
   Confirm the resolved set is non-empty; if empty, stop and report "nothing to review".

2. **Identify the target language(s) and load applicable standards** (read each that exists,
   note the rules a refactor must honor):
   - `~/.claude/CLAUDE.md` (user global)
   - the repo-root `CLAUDE.md` and any `CLAUDE.md` in a directory that is an ancestor of a
     target file
   - any language standards/style rules that apply to the target's file types (these auto-load
     by path glob, e.g. `python-standards.md` for `.py`), plus any project rules

3. **Record the test BASELINE** (needed for `--fix`): if FIX is true, get a `GREEN`/`RED`
   baseline by running the project's gates — in **deep** mode dispatch the `test-runner`
   subagent (ships with this plugin; it discovers the project's own test command and
   pre-commit config and returns just the verdict plus any failures, keeping the output out
   of this conversation), and in **quick** mode (no subagents) run the gates inline. Record
   the verdict. If FIX is false, run nothing — only note whether a test suite exists at all
   (a glance at the repo's config), since Phase 6 won't execute.

4. **Build the SCOPE BLOCK** that rides along to every finder: the resolved file list, a
   one-paragraph summary of what the code does, the loaded conventions, and the verbatim
   TARGET instructions. Honor any focus/skip instructions in TARGET over an angle's default
   breadth.

## Phase 2: Find

In **quick** mode, do NOT dispatch subagents: skip the rest of Phase 2 and all of Phase 3,
and go to the "Quick path" below.

In **deep** mode (the default), select finder angles by TARGET and dispatch each **in
parallel** as the `review-finder` subagent (ships with this plugin; read-only). Give each one
the SCOPE BLOCK, its single angle prompt (below), and the candidate schema (below); it returns
candidate findings in that schema.

**Angle selection (deep mode):** dispatch idioms, simplification, reuse, conventions,
docs-&-comments, efficiency, pitfalls, and altitude. Add `structure` only if TARGET is a
directory (folder/module/package/project). Up to 8 candidates per angle. After the first
pass, run one gap-sweep finder (see Phase 4).

**Candidate schema** (each finding):
- `file` (string), `line` (number), `summary` (one line),
- `rationale` (why it improves the code),
- `proposed_change` (the concrete simpler/clearer form),
- `kind` - `mechanical` (local, behavior-neutral edit) or `structural` (extract/move/split/generalize),
- `angle` - the angle id that produced it.

Pass every candidate with a real rationale through; do not silently drop half-believed ones,
an independent verifier judges them next. If an angle finds nothing, it returns an empty list.

### Angle prompts

Every angle applies to the **target file's language**. For a mixed-language target, judge
each file by its own language's idioms, standards, and footguns.

**idioms** - Review the code for adherence to the target language's idioms, typing, naming,
and style (per the loaded standards), and for behavior-preserving modernizations. Examples:
Python `os.path` -> `pathlib`, `%`/`.format` -> f-strings, `List`/`Optional` -> `list`/`| None`;
JS `var` -> `const`/`let`, callbacks -> async/await; apply the equivalent for whatever language
the file is in. Only surface changes that preserve behavior. Mark all `mechanical`.

**simplification** - Flag unnecessary complexity the code carries: redundant or derivable
state, copy-paste with slight variation, deep nesting that an early return or guard clause
would flatten, and dead code (unreachable branches, unused locals/imports). Name the simpler
form that does the same job. Dead-code/import removal and flattening are `mechanical`;
consolidating duplicated logic is `structural`.

**reuse** - Flag code that re-implements something the project already provides. Grep the
shared/utility modules and files adjacent to the target and name the existing helper to call
instead. Mark `structural`.

**structure** - (directory targets only) Recommend file/directory organization improvements:
modules doing too many things, code in the wrong module, circular-import-prone layouts. Mark
`structural`.

**efficiency** - Flag wasted work: redundant computation or repeated I/O, independent
operations run sequentially, blocking work on a hot path, and long-lived objects built from
closures/captured environments that keep an entire scope alive (prefer a class that copies
only the fields it needs). Name the cheaper alternative. For each, state whether the fix
preserves behavior (hoisting an invariant, de-duping I/O, memoizing a pure call, copying
fields) or would change it (parallelization, laziness that shifts side effects, caching a
mutable value). Behavior-preserving ones are `mechanical` or `structural`; behavior-changing
ones must be flagged so Phase 3 routes them to report-only.

**altitude** - Check that code is implemented at the right depth, not as a
fragile bandaid. Special cases layered on shared infrastructure signal the code isn't deep
enough; prefer generalizing the underlying mechanism over adding special cases. Mark
`structural`.

**conventions** - Find the CLAUDE.md / rules / standards that govern the target and flag
clear violations. Quote the exact rule and the exact line that breaks it; no style
preferences, no "spirit of the doc" inferences. Name the source path so the report can cite
it. Mark each finding `mechanical` (a naming, formatting, or docstring rule) or `structural` (a rule that requires reorganizing code), matching the size of the change the rule demands. If nothing applies, return nothing.

**docs-&-comments** - Rewrite API docs in the language's documentation convention (Python
docstrings, JSDoc, godoc, rustdoc) and the project's required format, explaining *why* a
developer would use the unit (per the loaded standards); rewrite inline comments to explain
*why* not *what*; flag and remove comments that merely restate the code. Mark `mechanical`.

**pitfalls** - (report-only) Flag the classic bug-class footguns of the target language
(e.g. Python mutable default args / late-binding closures, JS falsy-zero / `==` coercion,
Go nil-map writes / range-var capture, SQL injection, float equality). These are bug fixes,
not refactors, so they are always reported, never applied: leave `kind` unset; Phase 3 and
Phase 4 route every pitfalls finding to REPORT_ONLY by angle.

## Phase 3: Verify & refute

In deep mode, dispatch one `review-verifier` subagent per candidate (quick mode skips Phase 3
entirely; read-only). Give it the SCOPE BLOCK and the candidate, and ask it to **also judge
behavior preservation**. It returns exactly one verdict (`KEEP`, `PLAUSIBLE`, or `REFUTED`, per
its rubric) plus a **behavior-preserving? yes/no** — whether applying the change keeps external
behavior (outputs + side effects) identical.

Drop REFUTED candidates (record them briefly for the report). This is the "refute what's not
applicable" step.

**Routing (the cardinal rule):** the behavior-preserving judgment, not the angle, decides:
- behavior-preserving + (KEEP or PLAUSIBLE) -> apply-eligible
- behavior-changing (or any `pitfalls` finding) -> report-only

## Phase 4: Synthesize

1. **Gap sweep (deep mode):** dispatch one fresh `review-finder` that sees the surviving
   candidates and hunts ONLY for refactor opportunities not already found (moved code that
   dropped clarity, second-tier duplication, asymmetric setup/teardown). Verify any new
   candidates through Phase 3.
2. **Merge** candidates that describe the same root cause, keeping the one with the clearest
   rationale.
3. **Partition** survivors into three lists:
   - `APPLY_MECHANICAL` - behavior-preserving, `kind: mechanical`
   - `APPLY_STRUCTURAL` - behavior-preserving, `kind: structural`
   - `REPORT_ONLY` - behavior-changing (efficiency-that-changes-behavior, all pitfalls)
4. **Rank** within each list most-impactful first, and **cap** the combined total at <=12 in
   deep mode (quick mode caps at <=5, see the Quick path). If the cap forces a cut, drop the
   least impactful; never drop a REPORT_ONLY safety note silently (note the count if trimmed).

## Phase 5: Report

Always print these sections (this is the full output when `--fix` is absent):

1. **Apply-eligible findings** - `APPLY_MECHANICAL` then `APPLY_STRUCTURAL`, each as
   `path/to/file:LINE - summary` followed by the rationale and the proposed change, and a
   confidence label rendered per `review-verifier`'s canonical verdict→label mapping
   (**Confirmed** / **Worth considering**). Collapse each finding to one label; never print the
   raw verifier verdict tokens.
2. **Out of scope (report-only)** - each `REPORT_ONLY` finding with its summary and a note:
   "behavior-changing; consider `/code-review`."
3. **Refuted** - each entry from `REFUTED`, one line each, so the user sees what was
   considered and dropped.

If `FIX` is false, stop here. If `FIX` is true, continue to Phase 6.

## Phase 6: Apply (--fix)

Reached only when `FIX` is true. Never touch `REPORT_ONLY` findings.

**Precondition:** the test suite must be green (from `BASELINE`). If it is red, or absent
where the project clearly expects tests, refuse to apply and explain why - a red suite is not
a trustworthy regression detector. Report the findings and stop.

**Apply `APPLY_MECHANICAL` only.** Group fixes into coherent safe-state batches (all
dead-code removals together, all docstring rewrites together, all idiom modernizations
together). A batch boundary must be a state where the code is internally consistent - never a
half-finished restructure.

**Per-batch gate:**
1. Apply the batch.
2. Re-check the gates: in **deep** mode re-dispatch the `test-runner` subagent and read its
   verdict; in **quick** mode run the suite (and pre-commit if configured) inline.
3. `GREEN` -> commit with a conventional-commit message naming the technique
   (`refactor: remove dead code in <area>`). `RED` -> revert the batch, stop, and report the
   failure.

**Protected branches:** if on `main` or `master`, apply and verify but DO NOT commit (the
branch-protection hook would block it anyway). Tell the user to create a feature branch, then
leave the changes staged.

**`APPLY_STRUCTURAL` is never auto-applied.** Emit it as a proposed, ordered refactor plan
for the user's sign-off.

### Characterization-test scaffolding (deep mode)

Before proposing a structural change to **untested** code, scaffold a safety net so the
refactor can be verified, not hoped at. Quick mode skips this.

- **Test at the stable seam** - one level above the largest thing the refactor moves, so the
  tests survive the restructuring:
  - function internals (signature kept) -> a unit test on that function
  - class methods -> the class's public methods
  - module/package -> the module's public API (integration)
  - whole project -> end-to-end/smoke on CLI / HTTP entry points
- **Pin current behavior, including bugs** - these tests detect *change*, not correctness. If
  one reveals a bug, that is a separate fix in a separate commit.
- **Human review + separate commit** - surface generated tests for a quick review, then commit
  them on their own before any refactor commit. For complex output, prefer a golden-master
  snapshot (capture output, refactor, diff).

## Quick path

When `--quick` is set: do NOT dispatch subagents and do NOT scaffold tests. The main agent
reads the target code once and surfaces at most 5 behavior-preserving findings across
simplification, reuse, dead code, and docstrings/comments. No verifier pass (the main agent
judges directly). Partition your findings into the same `APPLY_MECHANICAL` / `APPLY_STRUCTURAL` / `REPORT_ONLY` lists that Phases 5 and 6 expect; `REFUTED` is empty in quick mode because there is no verifier. Then go to Phase 5 (Report), and Phase 6 (Apply) if `--fix` is set, applying
only mechanical findings under the same suite-green precondition and per-batch gate.
