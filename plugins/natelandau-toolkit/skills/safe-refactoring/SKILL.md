---
name: safe-refactoring
description: Use when the user asks to refactor, restructure, reorganize, extract, simplify, deduplicate, or "clean up"/"make this more readable"/"break this apart" any code, in any language, even when they don't say "refactor" explicitly. Keeps refactoring behavior-preserving and disciplined rather than freeform editing.
---

# Safe Refactoring

Restructure code to improve readability, maintainability, and design **without changing
external behavior**. This is a disciplined process, not freeform editing. It applies to any
language.

## When to reach for the `/refactor` command instead

This skill is the always-on discipline for refactoring that comes up in conversation. For a
**thorough, multi-angle review-and-apply pass** (idioms, reuse, simplification, structure,
efficiency, conventions, docs, and more, each verified independently), suggest the user run
the **`/refactor`** command:

- `/refactor <target>` runs the full multi-agent deep review (default).
- `/refactor --quick <target>` runs a fast inline pass with no subagents.
- add `--fix` to apply the safe (behavior-preserving, mechanical) findings.

For **project organization** rather than line-level code (file/directory topology, naming,
module boundaries, grab-bag files, scattered functions that want a home), suggest the
**`/organize`** command instead. It is advisory: it produces a report and an ordered
reorganization plan but never moves files. Execute that plan with this skill's discipline,
small steps, green tests between batches, behavior preserved.

Use this skill's discipline for any refactor you do directly; point at `/refactor` for the
heavy line-level pass and `/organize` for a structural/navigability review.

## The golden rules

1. **Behavior is preserved.** Refactoring changes structure, never what the code does.
2. **Small steps.** Make tiny, verifiable changes; never a big-bang rewrite.
3. **Tests are the safety net.** Without tests covering the code, you are editing and hoping,
   not refactoring. Run the suite before (a green baseline) and after each step.
4. **One concern at a time.** Never mix refactoring with feature changes or bug fixes.
5. **Commit safe states.** Commit before and after each coherent, green batch.

## How to approach it

1. **Understand intent.** What pain point drives this (readability, duplication, coupling,
   testability)? What is explicitly out of scope? Ask before touching code if it is unclear.
2. **Establish a baseline.** Run the existing tests. If the target code lacks coverage, write
   characterization tests that pin current behavior first, and commit them separately.
3. **Work in small, verifiable steps**, grouped into coherent batches (all renames together,
   all extractions together). Run the tests after each batch; commit only when green.
4. **Stop if you drift.** Changing more files than planned, "fixing" tests to match new
   behavior, or adding functionality means you have left refactoring. Stop and reassess.

## What refactoring is NOT

- **Not a bug fix.** Found a bug? Note it and fix it in a separate commit.
- **Not a feature.** Adding behavior is a separate task.
- **Not an optimization** that changes behavior. Behavior-changing perf work is its own
  concern with its own verification.

If you discover any of these during a refactor, note it for the user and keep it out of the
refactoring commits.

## Common techniques (vocabulary for the plan)

| Technique | When to use |
| --- | --- |
| Extract function/method | Long function, repeated logic, unclear intent |
| Extract class/type | A unit doing too many things; a group of related functions |
| Move function/class | Code in the wrong module; circular dependencies |
| Rename | Name does not communicate intent |
| Inline | An abstraction adds complexity without value |
| Replace conditional with polymorphism | Complex type-based if/else chains |
| Introduce parameter object | Functions with many related parameters |
| Split module/file | One file with mixed responsibilities |
| Consolidate duplicates | The same logic in multiple places |
