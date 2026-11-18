---
name: organize
description: Review how a project is organized (file/directory topology, naming, module boundaries, grab-bag files, scattered functions) and produce a prioritized report plus an ordered reorganization plan to make the codebase easier for developers to navigate and change. Advisory only with a multi-agent verified review; never moves files. Targets a subtree or the whole project.
disable-model-invocation: true
argument-hint: "[<target>]"
---

# /organize: project navigability review

Review how a project is organized so developers can find what they need and change it
safely: file and directory topology, naming, module boundaries. Not the inside of
functions; `/refactor` works at the line level.

## Scope and promise

- Advisory only: a report and an ordered reorganization plan. Never moves, renames,
  splits, or merges files; no commits. File moves rewrite imports project-wide, so a
  human reviews and executes them with the `safe-refactoring` discipline.
- Organization, not code quality. Line-level refactors (idioms, simplification, reuse,
  docs, efficiency) belong to `/refactor`; bugs and security to `/code-review` and a
  security review. Name any overlap and point at the right tool.
- Grounded in the stack's conventions. Justify every recommendation against the
  detected ecosystem's norms (Python src-layout, Flask blueprints, JS feature folders)
  and the loaded standards, not generic taste.

## Arguments

TARGET is all of `$ARGUMENTS`: a folder, a dotted module or package, or empty (the whole
project under the cwd). A bare file is allowed but a weak signal; prefer a directory or
the whole project, and say so when given a single file.

Echo the resolved TARGET in one line before proceeding.

## Phase 1: Map

Build the REPO MAP once; it goes to every finder.

1. Resolve TARGET to a tree: a path is that path; a dotted module or package is its
   directory or files; empty is the whole project. Empty result: stop and report
   "nothing to review".

2. Detect the stack (languages, frameworks, package layout) from manifests
   (`pyproject.toml`, `package.json`, `go.mod`, `Cargo.toml`) and directory shape. Read
   each standards source that exists and note the organizational norms to honor:
   - `~/.claude/CLAUDE.md`
   - repo-root `CLAUDE.md` and any `CLAUDE.md` in an ancestor directory of a target file
   - language or framework standards for the target's file types

3. Summarize the dependency shape: top-level modules and the edges between them, a
   coarse "what imports what" map, not a full graph. Raw material for spotting
   grab-bags, miswired layers, and code that changes together but lives apart.

4. Assemble the REPO MAP: resolved tree, stack and conventions, loaded standards,
   dependency summary, verbatim TARGET instructions. Focus or skip instructions in
   TARGET override an angle's default breadth.

## Phase 2: Find

Dispatch each angle in parallel as the read-only `review-finder` subagent (ships with
this plugin), with the REPO MAP, its single angle prompt, and the candidate schema. Up
to 8 candidates per angle.

Candidate schema:

- `area` (string): the path, directory, or cluster
- `problem` (one line): what is hard to navigate or change
- `proposed_change`: the concrete reorganization (move, split, merge, rename, introduce
  a class or module), in `safe-refactoring` vocabulary where it fits
- `navigation_cost`: the concrete friction a developer pays today, not hypothetical
- `angle`: the producing angle id

Finders pass through every candidate with a real `navigation_cost`, half-believed ones
too; the verifier judges next. Nothing found: empty list.

### Angle prompts

Judge every angle against the stack's conventions and loaded standards; in a
mixed-stack target, judge each area by its own ecosystem.

**topology**: Directory layout and grouping against the ecosystem's conventions. Flag
flat dumping grounds, inconsistent grouping (part by feature, part by type), packages
mixing unrelated concerns, and code in the wrong layer (business logic under `models/`
or `routes/`). Name the conventional layout and where the project diverges in a way that
costs navigation.

**cohesion**: Owns all splitting and merging of existing containers, in two directions.
Grab-bags and god-files (`utils`, `helpers`, `misc`, `common`, oversized
multi-responsibility files): name the internal seams and target homes.
Over-fragmentation: many tiny files or packages splitting one cohesive concept. Justify
each by the friction the current shape causes. Functions scattered across files with no
home belong to **boundaries**.

**boundaries**: Owns only the gather-the-homeless case: functions, constants, and state
for one domain or resource scattered across files with no owning module or class.
Recommend a focused module, or a service or handler class when the cluster shares state
or lifecycle. Name the scattered members and the new boundary. Not oversized or grab-bag
files that merely need splitting (**cohesion**), and no class where a plain module is the stack's
idiomatic home.

**naming**: File, directory, and module names that don't communicate their contents:
generic, misleading, or abbreviated past recognition. Also inconsistent conventions
across the tree (mixed casing or pluralization for the same kind of thing). Propose the
clearer name and cite the inconsistency.

**colocation**: Code that changes together but lives apart: a feature scattered across
distant directories, so one logical change edits many far-flung files. Use the
dependency summary and naming patterns to find clusters; name where they belong.

**wayfinding**: The newcomer's view. Unclear or missing entry points, no obvious "start
here", critical modules buried deep, missing or misleading directory-level index or
README signposting, orphaned modules nothing imports. Name the concrete fix.

## Phase 3: Verify and refute

Dispatch one read-only `review-verifier` per candidate with the REPO MAP and the
candidate. It returns `KEEP`, `PLAUSIBLE`, or `REFUTED`; no behavior-preservation
judgment. A `KEEP` must cite a navigation or maintenance cost the change removes ("a new
developer hunting for auth logic must grep four directories"; "editing billing forces
touching `utils.py`, which 30 unrelated modules import").

Drop REFUTED candidates; record them briefly for the report. A finding survives only if
it names a cost a developer pays today.

## Phase 4: Synthesize and report

1. Merge same-root-cause candidates; keep the clearest statement.
2. Rank by impact, most impactful first: navigation cost times how often the area
   changes.
3. Cap at 10, dropping the least impactful and noting the trimmed count.

Always print:

1. Today's map: one short paragraph on the current organization and top friction
   points.
2. Recommendations: ranked survivors grouped by theme, each as `area - summary`, then
   the proposed change, the cited `navigation_cost`, and one confidence label from the
   `review-verifier` mapping (Confirmed or Worth considering). Never print raw verdict
   tokens.
3. Ordered reorganization plan: safe steps respecting dependencies (create the package,
   move files, update imports, rename), each with a one-line risk note. Open with a
   reminder to establish test coverage at a stable seam before any structural move.
   Execution follows the `safe-refactoring` discipline: small steps, green tests between
   batches, behavior preserved. This command does not execute it.
4. Considered and dropped: each REFUTED candidate on one line.

Stop after the report. Never move files or commit.
