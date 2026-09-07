---
name: organize
description: Review how a project is organized (file/directory topology, naming, module boundaries, grab-bag files, scattered functions) and produce a prioritized report plus an ordered reorganization plan to make the codebase easier for developers to navigate and change. Advisory only with a multi-agent verified review; never moves files. Targets a subtree or the whole project.
argument-hint: "[<target>]"
---

# /organize: project navigability review

Review how a project is organized so developers can find what they need and
change it safely. This looks at file and directory topology, naming, and module
boundaries, not the inside of individual functions. It complements `/refactor`,
which works at the line level.

## Scope and promise

- Advisory only. This command produces a report and an ordered reorganization
  plan. It never moves, renames, splits, or merges files, and it makes no
  commits. File moves rewrite imports across the project, so a human reviews
  and executes them with the `safe-refactoring` discipline.
- Organization, not code quality. Line-level refactors (idioms,
  simplification, reuse, docs, efficiency) belong to `/refactor`. Bugs and
  security belong to `/code-review` and a security review. If an
  organizational finding overlaps those, name it and point at the right tool.
- Grounded in the stack's conventions. Justify every recommendation against
  the detected ecosystem's norms (Python src-layout, Flask blueprints, JS
  feature folders) and the loaded project standards, not generic taste.

## Arguments

Parse `$ARGUMENTS` into one value:

- TARGET: everything in `$ARGUMENTS`. It can name a folder or a dotted module
  or package, or be empty. If empty, default to the current working directory
  (the whole project). A bare file is allowed but a weak signal. Prefer a
  directory or the whole project, and say so when given a single file.

Echo the resolved TARGET back to the user in one line before you proceed.

## Phase 1: Map

Build the REPO MAP once. It goes to every finder.

1. Resolve TARGET into a concrete tree:
   - A path (folder or file): that path.
   - A dotted module or package: its directory or files on disk.
   - Empty: the whole project under the current working directory.

   If the resolved set is empty, stop and report "nothing to review".

2. Detect the stack and load conventions. Identify the languages, frameworks,
   and package layout from the manifest files (`pyproject.toml`,
   `package.json`, `go.mod`, `Cargo.toml`) and the directory shape. Read each
   standards source that exists and note the organizational norms a
   recommendation must honor:
   - `~/.claude/CLAUDE.md` (user global)
   - the repo-root `CLAUDE.md` and any `CLAUDE.md` in an ancestor directory of
     a target file
   - any language or framework standards that apply to the target's file types

3. Summarize the dependency shape. Produce a coarse "what imports what"
   summary for the target: the top-level modules and the edges between them.
   This is the raw material for detecting grab-bags, miswired layers, and code
   that changes together but lives apart. Keep it a map, not a full import
   graph.

4. Assemble the REPO MAP: the resolved tree, the detected stack and its
   conventions, the loaded standards, the dependency summary, and the verbatim
   TARGET instructions. Focus or skip instructions in TARGET override an
   angle's default breadth.

## Phase 2: Find

Dispatch each angle below in parallel as the `review-finder` subagent (it
ships with this plugin and is read-only). Give each one the REPO MAP, its
single angle prompt, and the candidate schema. It returns up to 8 candidate
findings in that schema.

Candidate schema, per finding:

- `area` (string): the path, directory, or cluster the finding is about
- `problem` (one line): what about the organization is hard to navigate or
  change
- `proposed_change`: the concrete reorganization (move, split, merge, rename,
  or introduce a class or module), named in `safe-refactoring` vocabulary
  where it fits
- `navigation_cost`: the concrete friction a developer pays today, not a
  hypothetical
- `angle`: the angle id that produced it

A finder passes every candidate with a real `navigation_cost` through,
including half-believed ones. The verifier judges them next. An angle that
finds nothing returns an empty list.

### Angle prompts

Judge every angle against the detected stack's conventions and the loaded
standards. For a mixed-stack target, judge each area by its own ecosystem's
norms.

**topology**: Review the directory layout and grouping against this
ecosystem's conventions. Flag flat dumping grounds, inconsistent grouping (part
by feature, part by type), and packages that mix unrelated concerns. Flag code
in the wrong layer, such as business logic under a `models/` or `routes/`
directory. Name the conventional layout for this stack and where the project diverges in
a way that costs navigation.

**cohesion**: Owns all splitting and merging of existing containers. Find
files and packages whose contents do not belong together, in two directions.
First, grab-bags and god-files: `utils`, `helpers`, `misc`, `common`, or
oversized multi-responsibility files that split along their internal seams.
Name the seams and the target homes. Second, over-fragmentation: many tiny
files or packages that fragment one cohesive concept and belong together.
Justify each by the friction the current shape causes. Functions spread across
several files with no proper home belong to **boundaries**, not here.

**boundaries**: Owns only the gather-the-homeless case. Functions, constants,
and state operate on one domain or resource, but they are scattered across
several files with no module or class that owns them. Recommend consolidating
them into a focused module, or into a service or handler class when the
cluster shares state or lifecycle. Name the scattered members and the new
boundary. Do not flag oversized or grab-bag files that merely need splitting
(that is **cohesion**), and do not recommend a class where a plain module is
the idiomatic home for this stack.

**naming**: Flag file, directory, and module names that do not communicate
what they contain: generic, misleading, or abbreviated past recognition. Flag
naming-convention inconsistency across the tree, such as mixed casing or
pluralization for the same kind of thing. Propose the clearer name and cite
the inconsistency.

**colocation**: Find code that changes together but lives apart: a feature
whose pieces are scattered across distant directories, so one logical change
means editing many far-flung files. Use the dependency summary and naming
patterns to identify the clusters, and name where they belong together.

**wayfinding**: Take the newcomer's view. Flag what makes the project hard to
enter: unclear or missing entry points, no obvious "start here", and critical
modules buried deep in the tree. Also flag missing or misleading index or
README signposting at directory level, and orphaned modules that nothing
imports. Name the concrete wayfinding fix.

## Phase 3: Verify and refute

Dispatch one `review-verifier` subagent (read-only) per candidate. Give it the
REPO MAP and the candidate. It returns one verdict (`KEEP`, `PLAUSIBLE`, or
`REFUTED`). No behavior-preservation judgment is needed here. For a `KEEP`, it
must cite a navigation or maintenance cost the change removes. Examples: "a
new developer hunting for auth logic must grep four directories", or "editing
the billing feature forces touching `utils.py`, which 30 unrelated modules
import".

Drop REFUTED candidates, and record them briefly for the report. A finding
survives only if it names a cost a developer pays today.

## Phase 4: Synthesize and report

1. Merge candidates that describe the same root cause. Keep the clearest
   statement.
2. Rank the survivors by impact: navigation cost times how often the area
   changes. Most impactful first.
3. Cap the list at 10. If the cap forces a cut, drop the least impactful and
   note the trimmed count.

Then always print these sections:

1. Today's map: one short paragraph on how the project is organized now and
   the top friction points.
2. Recommendations: the ranked survivors, grouped by theme, each as
   `area - summary`, followed by the proposed change, the cited
   `navigation_cost`, and one confidence label from the `review-verifier`
   mapping (Confirmed or Worth considering). Never print the raw verdict
   tokens.
3. Ordered reorganization plan: the recommendations sequenced into safe steps
   that respect dependencies (create the package, move files into it, update
   imports, rename). Each step carries a one-line risk note. Open the plan
   with a reminder to establish test coverage at a stable seam before any
   structural move. Note that execution follows the `safe-refactoring`
   discipline: small steps, green tests between batches, behavior preserved.
   This command does not execute the plan.
4. Considered and dropped: each REFUTED candidate on one line.

Stop after the report. This command never moves files and never commits.
