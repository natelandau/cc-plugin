---
name: safe-refactoring
description: Use when the user asks to refactor, restructure, reorganize, extract, simplify, deduplicate, or "clean up"/"make this more readable"/"break this apart" any code, in any language, even when they don't say "refactor" explicitly. Keeps refactoring behavior-preserving and disciplined rather than freeform editing.
---

# Safe Refactoring

Restructure code to improve readability, maintainability, and design without
changing external behavior. This is a disciplined process, not freeform
editing. It applies to any language.

## When to point at a command instead

This skill is the discipline for any refactor you do directly. Two commands
cover the heavier passes. Suggest them when they fit:

- `/refactor <target>` runs a multi-angle review-and-apply pass (idioms,
  reuse, simplification, structure, efficiency, conventions, docs), with each
  finding verified independently. `--quick` runs a fast inline pass with no
  subagents. `--fix` applies the safe, mechanical findings.
- `/organize <target>` reviews project organization: file and directory
  topology, naming, module boundaries, grab-bag files, and scattered
  functions. It produces a report and an ordered plan but never moves files.
  Execute that plan with this skill's discipline.

## The golden rules

1. Behavior is preserved. Refactoring changes structure, never what the code
   does.
2. Small steps. Make tiny, verifiable changes, never a big-bang rewrite.
3. Tests are the safety net. Without tests that cover the code, you are
   editing and hoping. Run the suite before (a green baseline) and after each
   step.
4. One concern at a time. Never mix refactoring with feature changes or bug
   fixes.
5. Commit safe states. Commit before and after each coherent, green batch.

## How to approach it

1. Understand the intent. Which pain point drives this: readability,
   duplication, coupling, or testability? What is out of scope? If unclear,
   ask before you touch code.
2. Establish a baseline. Run the existing tests. If the target code lacks
   coverage, write characterization tests that pin current behavior, and
   commit them separately.
3. Work in small, verifiable steps, grouped into coherent batches (all renames
   together, all extractions together). Run the tests after each batch, and
   commit only when green.
4. Stop if you drift. Changing more files than planned, "fixing" tests to
   match new behavior, or adding functionality means you have left
   refactoring. Stop and reassess.

## What refactoring is not

- Not a bug fix. If you find a bug, note it and fix it in a separate commit.
- Not a feature. Adding behavior is a separate task.
- Not an optimization that changes behavior. Behavior-changing performance
  work needs its own verification.

If you discover any of these during a refactor, tell the user and keep it out
of the refactoring commits.

## Common techniques

| Technique                             | When to use                                                 |
| ------------------------------------- | ----------------------------------------------------------- |
| Extract function or method            | Long function, repeated logic, unclear intent               |
| Extract class or type                 | A unit that does too many things, or related functions      |
| Move function or class                | Code in the wrong module, or circular dependencies          |
| Rename                                | The name does not communicate intent                        |
| Inline                                | An abstraction adds complexity without value                |
| Replace conditional with polymorphism | Complex type-based if/else chains                           |
| Introduce parameter object            | A function with many related parameters                     |
| Split module or file                  | One file with mixed responsibilities                        |
| Consolidate duplicates                | The same logic in several places                            |
