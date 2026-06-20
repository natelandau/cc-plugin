---
name: organize
description: Review how a project is organized (file/directory topology, naming, module boundaries, grab-bag files, scattered functions) and produce a prioritized report plus an ordered reorganization plan to make the codebase easier for developers to navigate and change. Advisory only with a multi-agent verified review; never moves files. Targets a subtree or the whole project.
argument-hint: "[<target>]"
---

# /organize - project navigability review

Review how a project is **organized** so developers can find what they need and change it
safely. This looks at file/directory topology, naming, and module boundaries, not the
inside of individual functions. It complements `/refactor` (line-level, behavior-preserving)
the way a city planner complements a carpenter.

## Scope and promise

- **Advisory only.** This command produces a report and an ordered reorganization plan. It
  **never moves, renames, splits, or merges files itself**, and it makes no commits. File
  moves rewrite imports across the project and must be reviewed and executed by a human (with
  the `safe-refactoring` discipline).
- **Organization, not code quality.** Line-level refactors (idioms, simplification, reuse,
  docs, efficiency) belong to `/refactor`. Bugs and security belong to `/code-review` and a
  security review. If an organizational finding overlaps those, name it and point at the right
  tool rather than expanding scope here.
- **Grounded in this stack's conventions.** Every recommendation must be justified against the
  detected ecosystem's norms (e.g. Python src-layout, Flask blueprints, JS feature-folders)
  and the loaded project standards, not generic taste.

## Arguments

Parse `$ARGUMENTS` into one value:

- **TARGET** - everything in `$ARGUMENTS`. May name a folder, a dotted module/package, or be
  empty. If empty, default to the current working directory (whole project). A bare file is
  allowed but weak signal; prefer a directory or the whole project, and say so if given a
  single file.

Echo the resolved `TARGET` back to the user in one line before proceeding.

## Phase 1: Map

Build the **REPO MAP** once. It is the shared substrate that rides along to every finder
(the analog of `/refactor`'s SCOPE BLOCK).

1. **Resolve TARGET into a concrete tree.**
   - A path (folder/file) -> that path.
   - A dotted module/package -> its directory/files on disk.
   - Empty -> the whole project under the current working directory.
   Confirm the resolved set is non-empty; if empty, stop and report "nothing to review".

2. **Detect the stack and load conventions.** Identify the language(s), framework(s), and
   package layout from manifest files (e.g. `pyproject.toml`, `package.json`, `go.mod`,
   `Cargo.toml`) and directory shape. Read each standards source that exists and note the
   organizational norms a recommendation must honor:
   - `~/.claude/CLAUDE.md` (user global)
   - the repo-root `CLAUDE.md` and any `CLAUDE.md` in a directory that is an ancestor of a
     target file
   - any language/framework standards that apply to the target's file types

3. **Summarize the dependency shape.** Produce a lightweight "what imports what" summary for
   the target (top-level modules and the edges between them). This is the raw material for
   detecting grab-bags, miswired layers, and code that changes together but lives apart. Keep
   it coarse; this is a map, not a full import graph.

4. **Assemble the REPO MAP**: the resolved tree, the detected stack and its conventions, the
   loaded standards, the dependency summary, and the verbatim TARGET instructions. Honor any
   focus/skip instructions in TARGET over an angle's default breadth.

## Phase 2: Find

Select the angles below and run each as an independent subagent **in parallel** via the Task
tool. Each subagent receives the REPO MAP and its single angle prompt, and returns candidate
findings in the schema below. Up to 8 candidates per angle.

**Candidate schema** (each finding):
- `area` (string) - the path, directory, or cluster the finding is about,
- `problem` (one line) - what about the organization is hard to navigate or change,
- `proposed_change` - the concrete reorganization (move/split/merge/rename/introduce class
  or module), named in `safe-refactoring` vocabulary where it fits,
- `navigation_cost` - the concrete friction this causes a developer **today** (not a
  hypothetical),
- `angle` - the angle id that produced it.

Pass every candidate with a real `navigation_cost` through; do not silently drop half-believed
ones, an independent verifier judges them next. If an angle finds nothing, it returns an empty
list.

### Angle prompts

Judge every angle against the detected stack's conventions and the loaded standards. For a
mixed-stack target, judge each area by its own ecosystem's norms.

**topology** - Review the directory layout and grouping against this ecosystem's conventions.
Flag flat dumping grounds, inconsistent grouping (part by-feature, part by-type), packages
that mix unrelated concerns, and code placed in the wrong layer (e.g. business logic under a
`models/` or `routes/` directory). Name the conventional layout for this stack and where the
project diverges in a way that costs navigation.

**cohesion** - Owns all **splitting and merging of existing containers**. Find files and
packages whose contents don't belong together, in two directions: (1) grab-bags and
god-files - `utils`, `helpers`, `misc`, `common`, or oversized multi-responsibility files
that should split along their internal seams; name the seams and the target homes. (2)
over-fragmentation - many tiny files or packages that fragment one cohesive concept and
should merge. Justify each by the friction the current shape causes. Scope boundary: you
reshape what is already grouped in a file or package. Functions that are spread across
*several* files with no proper home belong to **boundaries**, not here; do not also flag
those.

**boundaries** - Owns only the **gather-the-homeless** case: functions, constants, and state
that operate on one domain or resource but are scattered across several files with no module
or class that owns them. Recommend consolidating them into a focused module, or a
service/handler class where the cluster shares state or lifecycle. Name the scattered members
and the new boundary that would contain them. Scope boundary: do not flag oversized or
grab-bag files that merely need splitting (that is **cohesion**), and do not recommend a class
where a plain module is the idiomatic home for this stack.

**naming** - Flag file, directory, and module names that don't communicate what they contain
(generic, misleading, or abbreviated past recognition), and naming-convention inconsistency
across the tree (mixed casing or pluralization schemes for the same kind of thing). Propose
the clearer name and cite the inconsistency.

**colocation** - Find code that changes together but lives apart: a feature whose pieces are
scattered across distant directories so that one logical change means editing many far-flung
files (shotgun surgery). Use the dependency summary and naming patterns to identify the
clusters, and name where they should be colocated.

**wayfinding** - Take the newcomer's view. Flag what makes the project hard to enter: unclear
or missing entry points, no obvious "start here", critical modules buried deep in the tree,
missing or misleading index/README signposting at directory level, and orphaned or dead
modules (nothing imports them) that clutter navigation. Name the concrete wayfinding fix.

## Phase 3: Verify & refute

Run one independent verifier subagent per candidate. Give the verifier the REPO MAP and the
candidate. It returns exactly one verdict:

- **KEEP** - a real improvement to navigability or maintainability. The verifier **must cite a
  concrete navigation or maintenance cost** the change removes (e.g. "a new dev hunting for
  auth logic must grep four directories"; "editing the billing feature forces touching
  `utils.py`, which 30 unrelated modules import"). No concrete cost -> not a KEEP.
- **PLAUSIBLE** - the improvement is real but context-dependent; state what would confirm it
  (e.g. team ownership, churn data, a convention the repo hasn't declared).
- **REFUTED** - subjective restyling ("I'd arrange it differently"), factually wrong, would
  break the stack's conventions, or net-negative for navigation. Quote what proves it.

Drop REFUTED candidates (record them briefly for the report). This is the defense against
organizational bikeshedding: a finding survives only if it names a cost a developer pays today.

## Phase 4: Synthesize & report

1. **Merge** candidates that describe the same root cause, keeping the clearest statement.
2. **Rank** survivors by impact, approximated as navigation cost times how often the area
   changes (churn). Most-impactful first.
3. **Cap** the recommendation list at <=10. If the cap forces a cut, drop the least impactful
   and note the trimmed count.

Then always print these sections:

1. **Today's map** - one short paragraph: how the project is organized now and the top
   friction points, so the reader has the lay of the land before the recommendations.
2. **Recommendations** - the ranked survivors, grouped by theme, each as
   `area - summary` followed by the proposed change, the cited `navigation_cost`, and the
   verdict (KEEP/PLAUSIBLE).
3. **Ordered reorganization plan** - the recommendations sequenced into safe steps that
   respect dependencies (e.g. create the package, then move files into it, then update
   imports, then rename). Each step carries a one-line risk note. Open the plan with a
   reminder to establish test coverage at a stable seam before executing structural moves, and
   note that execution should follow the `safe-refactoring` discipline (small steps, green
   tests between batches, behavior preserved). This command does not execute the plan.
4. **Considered & dropped** - each REFUTED candidate, one line each, so the reader sees what
   was weighed and set aside.

Stop after the report. This command is advisory; it never moves files and never commits.
