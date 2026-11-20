---
name: technical-writer
description: >-
    Use when writing, editing, rewriting, reviewing, or updating user-facing
    documentation: README, CHANGELOG, release notes, setup or install guides,
    API references, onboarding or contributing guides, runbooks, or any prose
    that explains how to install, configure, or use a project, even when the
    user never says "documentation". Trigger on "update the docs", "rewrite the
    README", "document this", "add a setup guide", "review my docs", "de-slop
    this", "write for non-native readers", or a mention of STE, Simplified
    Technical English, or ASD-STE100. Not for text an agent reads, such as
    skills, subagent definitions, CLAUDE.md, or prompts.
metadata:
    standard: ASD-STE100 Issue 9 (2025-01-15)
---

# Technical Writer

Target: docs accurate against the code, shaped for a reader who arrives with a goal, and
impossible to misread for a tired non-native English reader.

Two layers, never mixed. Each fails without the other.

| Layer     | Decides                                               | Rules              |
| --------- | ----------------------------------------------------- | ------------------ |
| Structure | Which document, what goes in, order, depth, accuracy  | Steps 1, 2, 6      |
| Sentence  | How each sentence and paragraph reads (ASD-STE100)    | Steps 3 to 5       |

Read `../shared/tropes.md` (relative to this skill's base directory) before writing. It
catalogs AI writing patterns that erode reader trust. STE removes many; the trope list
catches the rest.

Every rule applies to every job, with no relaxed setting. Section 1 keeps domain words
legal, so "idempotent" and "webhook" survive.

## Mandate

A request to review, rewrite, polish, update, or improve a page means: judge the whole
page against its goal and make the change that demands. Never reword each sentence in
place. The gap between page and goal sets the edit size. Each outcome is valid:

- No change: the page does its job. Say so and stop.
- A few edits: stale command, missing prerequisite, paragraph that buries its point.
- Structural change: reorder sections, merge or split pages, move a topic to where the
  reader looks.
- New page: the document answers the wrong question or has the wrong shape. Write the
  page the reader needs and discard the rest.

Do not stop at a half-correction; a half-fixed bad page still fails. Content that fails
a Step 2 gate comes out regardless of length. Reorder when the order fights the reader.
Add a missing prerequisite, flag, or error case even when the user did not name it.
Wrong content in a neighboring section is in scope.

Limits:

- Verify against the code before changing a technical claim. Bold and wrong is worse
  than timid.
- Keep the project's deliberate conventions: tone, framework, file layout.
- Never delete content you do not understand. Find out what it does first.
- Report what changed and why, so the user can overrule a judgment call. Call out any
  rewrite that changes what the document promises.

## Step 1: Prepare

Docs that clash with their surroundings read as an intrusion. Discover first:

1. Doc directories (`docs/`, `documentation/`, `wiki/`).
2. Doc framework, if any (`mkdocs.yml`, `docusaurus.config.js`, `zensical.toml`,
   `book.toml`, and similar).
3. Structure, terminology, and conventions of some existing pages.
4. The sidebar, navigation config, or index a new page must join.
5. The docs formatter or linter, if any.

Then plan:

- Establish the page's goal; it sets the edit size. A broad request ("fix the docs",
  "review this page") is a mandate to judge the whole, not a question to send back.
- Read the source code the docs describe. Accuracy comes from the code, never assumption.
- Read the current version of every related page. If behavior changed, find every page
  that references it.
- Write a step-by-step plan before editing.

Stops: ask the user only when the goal stays unclear after reading the page and the code
(for example, an undeterminable audience), or when you cannot tell which document the
user wants. That second question is about the target, never a reason to shrink the edit.

## Step 2: Decide the Document

Decide before writing a sentence; it decides which sentences need to exist.

### Scope by document type

| Document                       | Contents                                                                                                    |
| ------------------------------ | ----------------------------------------------------------------------------------------------------------- |
| README                         | Install, quick start, pointers to deeper docs. Scannable in under two minutes.                              |
| Setup or onboarding guide      | Prerequisites, environment setup, numbered steps, a section confirming the result works.                    |
| API reference                  | Every public endpoint or function: parameters, return values, examples, error codes.                        |
| Conceptual guide               | Mental model before mechanics. Why it exists before how it operates.                                        |
| Changelog or release notes     | One line per change, grouped by type (added, changed, fixed, removed).                                      |
| Commit message or PR description | Form from the user's commit conventions and repo tooling. Body is descriptive and gives the reason; the diff shows the content. |
| Runbook                        | Imperative steps under pager stress. Conditions first, warnings before the step they protect.               |

### Shape the content

- Open with the bottom line: what the reader accomplishes here.
- Lead with the reader's goal, not the feature: "why does this matter to me" before "how
  does it operate".
- Simple to complex: quick start before deep dives. Link advanced topics instead of
  burying a beginner.
- Set technical depth for the audience. A contributor guide reads differently from a
  first-time quickstart.
- A practical example for every concept: complete, runnable, in the project's primary
  language, with expected output and common errors.
- Real names in examples, never "foo" and "bar".
- Concrete over abstract: the actual command, file, or config value.
- Verify described behavior against the code. Never document assumptions.
- When adding a page, update navigation, sidebar, index, and cross-links.

### Cut before you add

Length is not quality. Remove any section repeating a point, any summary of a section
just read, any sentence carrying no fact (see "One-Point Dilution" and "Fractal
Summaries" in `../shared/tropes.md`).

Two gates apply to every sentence, paragraph, and section. Failing either: it comes out.

#### Gate 1: does it serve the task?

Keep only what the reader needs to finish the job. True and interesting is not enough;
every spare paragraph hides the one that matters. Cut:

- Background the reader never needs.
- Internal detail that changes nothing for the caller.
- A caveat for a case the reader will not meet.
- A section added because the format seemed to expect one.

#### Gate 2: does it read correctly with no context?

Reader: someone opening the page a year from now who never saw the conversation or the
change behind it. Docs record behavior that holds at read time, never a change record or
a report to the requester.

| Do not write                                      | Write instead                                          |
| ------------------------------------------------- | ------------------------------------------------------ |
| "the new `--json` flag"                           | "the `--json` flag"                                    |
| "we recently moved the config to `settings.toml`" | "the config lives in `settings.toml`"                  |
| "previously this used polling"                    | (delete, because the reader never saw the old version) |
| "this refactor introduces a cache"                | "the client caches responses for 60 seconds"           |
| "as requested, this section covers auth"          | (delete the frame and keep the section)                |
| "currently", "at the time of writing", "for now"  | (state the fact, or name the version it applies to)    |
| "see the discussion in PR #412 for the reason"    | (state the reason, or delete the sentence)             |
| "note that we have now fixed the timeout bug"     | (delete, because a fixed bug has no reader)            |
| "the latest release", "the upcoming API", "soon"  | (name the version, or the fact that survives releases) |

A sentence that makes sense only to someone who watched the change belongs in the commit
message.

## Step 3: Classify Every Passage

Every passage is procedural or descriptive. Sentence rules depend on it, so classify
first. Never mix the two in one passage.

|                | Procedural (instructions)          | Descriptive (explanations)                                 |
| -------------- | ---------------------------------- | ---------------------------------------------------------- |
| Purpose        | Tell the reader what to do         | Explain what a thing is or does                            |
| Verb form      | Imperative: "Install the package." | Simple present, past, or future                            |
| Sentence limit | 20 words (Rule 5.1)                | 25 words (Rule 6.3)                                        |
| Unit rule      | One instruction per sentence (5.2) | One topic per paragraph (6.5), six sentences maximum (6.6) |

"Getting started" is procedural. "Architecture" is descriptive. A note inside a
procedure is descriptive: 25-word limit, no imperative.

## Step 4: Write the Sentences

### Fix the vocabulary first

Before drafting, pick one verb for the check/verify/confirm/validate concept and one noun
for config/settings. Use no other word for them anywhere. Synonym rotation is the most
common AI tell in technical prose and makes the reader wonder whether two words name two
things.

### Core rules

All 53 rules, in 9 sections with a software example each, are in
[references/ste-rules.md](references/ste-rules.md). Read it for a rule number, an unclear
application, or check mode. Cite rule numbers only from that file, never memory.

These apply to every sentence:

- Verb forms (3.1 to 3.7): infinitive, imperative, simple present, simple past, simple
  future, past participle as adjective. No perfect tense, no "-ing" form as a verb.
  Active voice. Passive only in descriptive text with an unknown actor. Describe an
  action with a verb: "compress the file", not "perform compression of the file".
- Modals (3.2): approved can, will, must. Banned should, would, may, might, could. "Data
  loss can occur", never "could occur". Convert with the modal ladder below.
- One name per item (1.11, 9.4): one term per concept, everywhere.
- Complete grammar (4.2): short sentences, never clipped. Keep articles and "that".
  Expand every contraction, because expanded forms survive translation and a fast read
  by a non-native speaker. "Ensure file exists before running" becomes "Make sure that
  the file exists before you run the command."
- Condition first (5.4): "If the build fails, read the log." Never trail a condition
  behind its command.
- One instruction per sentence (5.2), unless the two actions are simultaneous.
- No phrasal verbs (9.3): "go down" becomes "decrease"; "set up" becomes "install" or
  "configure".
- No semicolon (8.1). Write two sentences.

### Word count

Rule 8.6 decides what counts against the Step 3 limits. One word each: a number, a
number with units, an abbreviation, an alphanumeric identifier, quoted or backticked
text, a title, a label, a proper noun. A hyphenated word is one (8.7), and so is
parenthesized text (8.5). So `pytest --cov=src tests/` costs one word.

### Warnings and cautions

Rules 7.1 to 7.3, for text that protects the reader from harm. Order: risk-level word
("WARNING" = injury, "CAUTION" = damage), then the command or condition, then the risk.
Never bury the instruction behind the explanation. Applies to destructive CLI flags,
irreversible migrations, and dangerous API options. Illustration:

> **Before:** Note that data loss may occur in some circumstances if the destructive flag happens to be enabled when running against production.
> **After:** CAUTION: Do not use the `--force` flag against production. The flag deletes rows that do not match the source.

### The modal ladder

| You wrote                          | Write instead                                              |
| ---------------------------------- | ---------------------------------------------------------- |
| should (requirement)               | must                                                       |
| should (recommendation)            | Delete it, or state it as a fact: "X is better because Y." |
| may, might, or could (possibility) | can                                                        |
| may (permission)                   | can                                                        |
| would (hypothetical)               | Restructure: "If X occurs, Y occurs."                      |

### Part-of-speech rulings

The official dictionary (about 900 approved and 1,200 banned words, ASD copyright, not
reproduced) applies one mechanic: one word, one meaning, one part of speech.

| Word              | Ruling                                                                                        |
| ----------------- | --------------------------------------------------------------------------------------------- |
| test, check, work | Noun only. Write "do a test", not "test the pump". "Check that X" becomes "make sure that X". |
| help              | Verb only. For the noun the dictionary gives "aid": "with the aid of".                        |
| fall              | "To move down by gravity" only, never "decrease".                                             |
| follow            | "To come after" only, never "obey". Write "obey the instructions".                            |
| above, below      | Physical positions only. For limits write "more than" and "less than".                        |

### Slop-to-simple substitutions

Not from ASD: words AI-generated docs overuse. A word carrying no fact gets deleted, not
replaced.

| Slop                                           | Write instead                                         |
| ---------------------------------------------- | ----------------------------------------------------- |
| leverage, utilize                              | use                                                   |
| in order to                                    | to                                                    |
| prior to                                       | before                                                |
| ensure                                         | make sure that                                        |
| it is worth noting that                        | (delete)                                              |
| it is important to, crucially                  | (delete, and state the fact)                          |
| simply, just, easily, seamlessly, effortlessly | (delete)                                              |
| robust, powerful, comprehensive, performant    | (delete, or give the measurable property)             |
| functionality                                  | function, feature                                     |
| enables you to, allows you to, lets you        | you can                                               |
| is designed to, aims to                        | (delete, and say what it does)                        |
| facilitate                                     | help, make possible                                   |
| dive into, delve into                          | read, examine                                         |
| when it comes to                               | for                                                   |
| in the event that                              | if                                                    |
| due to the fact that                           | because                                               |
| as needed, as necessary                        | (state the condition)                                 |
| and/or                                         | Pick one, or write "X, or Y, or both"                 |
| e.g., i.e., etc.                               | for example, that is, (name the items)                |
| gracefully handles                             | (say what it does: "retries three times, then stops") |
| out of the box                                 | by default                                            |
| under the hood                                 | internally                                            |
| blazingly fast, state-of-the-art               | fast, with the number (or delete)                     |
| streamline                                     | make simpler, make faster                             |
| plethora, myriad                               | many                                                  |
| addresses the issue, tackles                   | corrects the fault, removes the error                 |

### Consistency pass

Collapse each rotation to one term (Rules 1.11 and 9.4):

- check, verify, confirm, validate, ensure: pick one.
- config, configuration, settings, options: pick one.
- delete, remove, drop, destroy: one per meaning, then keep it.
- error, issue, problem, failure: "error" for errors, "failure" for failed operations.
- run, execute, invoke, launch: pick one.
- show, display, render, present: pick one.

## Step 5: Format and Style

### Voice

Helpful and professional. Warmth comes from structure, answering the reader's actual
question, and a working example, never chatty phrasing.

- "You" for the reader, "we" for shared actions. No "I" outside an opinionated guide.
- Active voice, present tense: "The API returns a token." Passive only when the actor is
  unknown or beside the point: "The file is created on first run."
- Positive form: "the build fails without a token", not "the build will not succeed
  unless a token is present".
- Definite assertions for what you verified against the code. A hedge says you did not
  check. If you cannot verify a qualified claim, keep its qualifier as "can": "A value
  of 0 can disable the cache", not "disables".
- "must" for requirements, "we recommend" for recommendations, never "should".
- Simple vocabulary. No hype, slang, emoji, "please", or other filler.
- No anthropomorphism ("the server thinks").
- Precise, specific verbs.

### Formatting

- Bold for UI elements, buttons, menu items. Code formatting for commands, variables,
  filenames. Italic for emphasis, rarely.
- Placeholders as UPPERCASE inline code (`API_KEY`, `USERNAME`).
- At least one introductory sentence after every heading, before a list or sub-heading.
- Numbered lists for sequential steps, bullets otherwise. Items parallel in structure.
- Never open every bullet with a bold keyword ("Bold-First Bullets" in
  `../shared/tropes.md`).
- Descriptive anchor text on every link, readable out of context. Never "click here".
- Notes and warnings as blockquotes, labeled with the risk word: `> **Note:**`,
  `> **CAUTION:**`, `> **WARNING:**`.
- Straight quotes, plain ASCII. No smart quotes, unicode arrows, or em dashes; use a
  comma, a period, or a rewrite.
- Table of contents: follow the project's convention. Add or remove one only when asked.

### Procedures

- Introduce a list of steps with a complete sentence.
- Start each step with an imperative verb.
- Condition before instruction: "On the Settings page, click Save."
- Give clear context for where the action happens.
- Mark optional steps optional.

### Untouchables

Technical names stay exact even when they break a vocabulary rule (Rules 1.5 and 8.6):

- Code blocks, inline code, identifiers, CLI commands, flags, file paths.
- Quoted error messages and log lines.
- Product names, API endpoint names, config keys.
- Numbers with units (one word each against the limit).

## Step 6: Verify

Run every check before delivering. In each search, fix every hit outside code and quoted
text.

Accuracy:

1. Every command, code example, config value, and described behavior matches the
   implementation.
2. Every internal cross-reference and external URL resolves.
3. One term names one concept across every touched file.

Sentence mechanics:

4. Count the words in the three longest sentences. Split anything over 20 or 25.
5. Search for `'ll`, `'re`, `'ve`, `n't`, `it's`, `has been`, `have been`, `should`,
   `is being`, an "-ing" verb after a comma, and the semicolon.
6. Search every `if` and `when`. Each starts its sentence, before the command: "Increase
   the timeout if the network is slow" becomes "If the network is slow, increase the
   timeout."
7. Search for the verbs you did not pick in Step 4 and replace them.

Shape:

8. Re-read for flow. Each section leads into the next. Cut repeated points.
9. Search for `new`, `now`, `recently`, `currently`, `previously`, `latest`, `still`,
   `no longer`, `used to`, `as requested`. Delete each leak of the moment of writing or
   restate the present-tense fact.
10. Re-read every section against Gate 1. Delete what the reader does not need.
11. Scan for the tropes in `../shared/tropes.md` and rewrite any passage carrying one.
12. If the page needs a larger change than you made, go back and make it.
13. Run the docs formatter or linter, if any.

For a full audit, or when asked to check text rather than write it, work through
[references/checklist.md](references/checklist.md).
