---
name: prompt-writer
description: >-
  Use when writing, revising, or reviewing text an agent reads instead of a
  person: a skill (SKILL.md and its references), slash command, subagent
  definition, CLAUDE.md or rules file, subagent or workflow prompt, or a hook
  message fed back to the model. Trigger on "write a skill", "add an agent",
  "tighten this prompt", "update CLAUDE.md", "make this skill shorter". Not for
  READMEs, docs sites, commit messages, or PR descriptions, which people read.
---

# Prompt Writer

Reader: an agent. Reads literally, has no memory of the conversation that produced the
text, pays for every token on every turn the text stays loaded. Goal: least text that
produces the right behavior.

## Mandate

- Judge the whole text against the behavior it must produce. Rewrite, reorder, merge,
  or cut as that demands. "No change needed" is a valid result.
- Verify every command, path, flag, tool name, and frontmatter field against the code
  or current platform docs before writing it.
- Report what changed and why. Call out any change to the behavior the text asks for.
- If two rules conflict, report the conflict and ask which wins. Never resolve it by
  allowing both.

## 1. Prepare

- Read the code, tools, and files the text names. If sibling components exist, read
  two and keep their frontmatter, layout, naming, and description format.
- State the target behavior in one line: what the agent does, when, and what it returns.
- Place the text by its load cost:

| Component                        | Loaded                              | Put here                                                                   |
| -------------------------------- | ----------------------------------- | -------------------------------------------------------------------------- |
| Skill or command description     | Every session, listing              | Trigger conditions only                                                    |
| SKILL.md body                    | On invoke, stays for the session    | Workflow and rules, most important first (compaction keeps only the start) |
| `references/` files              | When the body says to read one      | Catalogs, long examples, check-mode detail                                 |
| Subagent description             | Every session of the dispatcher     | One line naming who dispatches it                                          |
| Subagent body or dispatch prompt | Whole run; the agent's only context | Goal, known facts, scope, return shape                                     |
| CLAUDE.md or rules file          | Every turn                          | Only what holds for all work in that scope                                 |
| Hook block message               | Once, at the blocked call           | What was blocked, what to do instead                                       |

## 2. Decide the content

Keep a line only when deleting it changes what the agent does. Cut:

- Defaults the model already follows: read before editing, write clean code, be careful.
- "Think carefully", "think step by step", "take a deep breath". The model sets its own
  reasoning depth.
- Persona and preamble: "You are an expert...", "This skill helps you...".
- Motivation written for a human reviewer, history of the text, restated rules,
  summaries of the section above.
- A rule a hook already enforces. Keep at most one line so the agent does not waste a
  blocked attempt.

No-context gate: the text reads correctly for an agent in an unrelated project a year
from now. Cut "new", "now", "currently", "previously", incident and ticket references,
and pointers to sibling components the reader may not have.

Reasons: add a short "why" clause only when the rule needs judgment at its edges. The
reason lets the agent handle cases the rule does not name. A mechanical rule gets no
reason.

A rule that must hold every time belongs in a hook, not prose.

## 3. Phrase each instruction

- **Say what to do.** Pair every ban with its replacement: "Run `uv run duty test`,
  not bare `pytest`." A bare ban is allowed only as a concrete list of named patterns
  ("no cream backgrounds, pill buttons, numbered section labels"), never a vague one
  ("avoid generic design").
- **Modals.** `must` = required. `can` = allowed. Replace the rest:

| Wrote                         | Write                                            |
| ----------------------------- | ------------------------------------------------ |
| should, need to (requirement) | Imperative, or `must`                            |
| should, consider (suggestion) | `Optional:` prefix, or state default + exception |
| may, might, could, try to     | `can`, or the condition that decides it          |
| as needed, if appropriate     | The actual condition                             |

- **Condition first.** "If the build fails, read the log." Scope words ("only when",
  "unless", "at most", "every") stay explicit. They carry the meaning.
- **Constraints as hard limits.** Numbers, paths, tool names, counts: "at most 3
  findings", "edit only files under `src/`", "no push".
- **Stops.** Default is to continue. List the stops: "Stop and ask only when X or Y."
  Destructive or outward-facing actions are always a listed stop.
- **No emphasis.** No caps, IMPORTANT, CRITICAL, or bold for urgency. Emphasis makes the
  model over-apply a rule.
- **One term per concept.** Pick one verb for check/verify/validate and one noun for
  config/settings. Use only those.
- **Standing instructions.** The body loads once and stays. Write rules that hold for
  the whole run: "Run the tests after every edit", not "Run the tests."

## 4. Compress

Fragments are the default. Keep the verb, object, condition, qualifier, number, and
name. Drop articles, the subject "you", copulas, "that", filler, and hedges.

| Full sentence                                                                   | Fragment                                          |
| ------------------------------------------------------------------------------- | ------------------------------------------------- |
| You should make sure that you read the existing tests before you add a new one. | Read existing tests before adding one.            |
| It is important to note that the config file is located in the home directory.  | Config: `~/.config/app/config.toml`.              |
| If you are not sure which branch is the default, you can check with git.        | Default branch unknown: `git remote show origin`. |

Pick the format by the content's shape:

- One rule: bullet.
- Sequence: numbered steps.
- Mapping (if X then Y, bad to good): table.
- Exact output: template in a code block.
- Example: only when the pattern resists a rule. One, minimal, labeled as an
  illustration so the agent does not copy it verbatim.
- Headings: short labels, no intro sentence.
- XML tags: only to fence pasted input or data inside a prompt.

Never compress: code, commands, paths, identifiers, quoted error text, output templates.
Skip private abbreviations and shorthand the model does not know. They cost more tokens
than the words and add ambiguity. ASCII only: `->`, straight quotes, no em dashes.

## 5. Finish line

Optional: when the task has a clear end, close with a `Done when:` block of conditions
the agent can check itself. Reference and style skills with no end moment skip it.

- Return shape for anything that reports to a caller: fields, order, length cap.
- Long runs: keep a checklist in a file, tick items off. A file survives compaction.
- Fan-out: the dispatcher checks each subagent's evidence before accepting it.

## 6. Descriptions

- Default start: "Use when ...".
- Triggers only: the situations and the phrases users say. Key use case first. No
  summary of the method; the body carries it.
- Hard cap 1,536 characters. Aim for under 500.
- Run-on-request components: `disable-model-invocation: true`, which drops the
  description from every session.
- Placeholders as `[arg]`, not `<arg>`.

## 7. Review mode

When asked to review agent-facing text, report each finding as: line, problem, rewrite.
Group by section of this skill. Apply the fixes only when asked.

## 8. Verify

1. Read the text as the target agent with nothing else loaded. Every instruction is
   actionable, and every term is defined or standard.
2. Search, as whole words, for `should`, `may`, `might`, `could`, `try to`,
   `consider`, `please`, `IMPORTANT`, `CRITICAL`, `think`, `You are`, `currently`,
   `now`, `new`, `previously`. Fix each hit outside code and quoted text.
3. Scan against the `## Word Choice` and `## Composition` sections of
   `../shared/tropes.md` (relative to this skill's base directory). Read only those
   sections.
4. For a revision, report size before and after: `wc -c` on each file.
5. Run the project's lint and tests if the text lives in a repo with them.

Done when every step passes and the change summary is delivered.
