---
name: safe-refactoring
description: Use when the user asks to refactor, restructure, reorganize, extract, simplify, deduplicate, or "clean up"/"make this more readable"/"break this apart" any code, in any language, even when they don't say "refactor" explicitly.
---

# Safe Refactoring

Restructure code for readability, maintainability, and design without changing external
behavior. Any language.

## Rules

1. Preserve behavior. Change structure, never what the code does.
2. Small, verifiable steps; never a big-bang rewrite.
3. Tests are the safety net. Run the suite before (green baseline) and after each batch.
4. One concern at a time. Never mix refactoring with feature changes or bug fixes.
5. Commit before and after each coherent, green batch.

## Process

1. Pin the intent: which pain point (readability, duplication, coupling, testability)
   and what is out of scope. Unclear: ask before touching code.
2. Establish a baseline: run the existing tests. Target code lacks coverage: write
   characterization tests that pin current behavior and commit them separately.
3. Work in batches of one kind (all renames, all extractions). Run the tests after each
   batch; commit only when green.
4. Stop and reassess on drift: changing more files than planned, editing tests to match
   new behavior, or adding functionality.

## Out of scope

Bug fixes, features, and behavior-changing optimizations. Found one mid-refactor: tell
the user and keep it out of the refactoring commits (a bug fix goes in its own commit).

## Heavier passes

Suggest when they fit:

- `/refactor [target]`: multi-angle review with independent verification. `--quick`:
  fast inline pass. `--fix`: applies the safe, mechanical findings.
- `/organize [target]`: reviews file and directory topology, naming, and module
  boundaries; produces a report and ordered plan, never moves files. Execute its plan
  with these rules.

## Techniques

| Technique                             | When                                                 |
| ------------------------------------- | ---------------------------------------------------- |
| Extract function or method            | Long function, repeated logic, unclear intent        |
| Extract class or type                 | A unit doing too many things, or related functions   |
| Move function or class                | Code in the wrong module, or circular dependencies   |
| Rename                                | The name does not communicate intent                 |
| Inline                                | An abstraction adds complexity without value         |
| Replace conditional with polymorphism | Complex type-based if/else chains                    |
| Introduce parameter object            | A function with many related parameters              |
| Split module or file                  | One file with mixed responsibilities                 |
| Consolidate duplicates                | The same logic in several places                     |
