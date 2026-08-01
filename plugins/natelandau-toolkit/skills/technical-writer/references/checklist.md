# Verification checklist

Run this pass on every draft before you deliver it, and run it in full when the
user asks you to check text rather than write it.

The checks move from mechanical to structural. Mechanical checks are searchable
and take seconds. Structural checks need judgment, so they come last, when the
prose is already clean enough to read for shape.

## Tier 1: Mechanical checks (searchable)

Search the draft for each pattern. Every hit outside code blocks and quoted text
is a violation.

| Search for | Violation | Fix |
|---|---|---|
| `'ll`, `'re`, `'ve`, `n't`, `it's` | Contraction (Rule 4.2) | Expand it. |
| `has been`, `have been`, `had been` | Present or past perfect (Rule 3.4) | Simple past or simple present. |
| `has` or `have` plus a past participle | Present perfect (Rule 3.4) | Simple past. |
| `should`, `would`, `may`, `might`, `could` | Unapproved modal (Rule 3.2) | Use the modal ladder in SKILL.md. |
| `is being`, `are being`, `was being` | Progressive passive (Rules 3.4, 3.5) | Active voice, simple tense. |
| `, making`, `, allowing`, `, enabling`, `, ensuring` | "-ing" clause used as a verb (Rule 3.5) | New sentence with a real subject. |
| `;` | Semicolon (Rule 8.1) | Two sentences. |
| `e.g.`, `i.e.`, `etc.` | Latin abbreviation (GR-6) | "for example", "that is", or name the items. |
| An em dash | Banned punctuation | A comma, a period, or a rewrite. |
| `simply`, `easily`, `seamlessly`, `robust`, `just` | Filler that carries no fact | Delete. |
| ` if `, ` when ` mid-sentence | Trailing condition (Rule 5.4) | Move the condition to the start of the sentence and add a comma. |
| `new`, `now`, `recently`, `currently`, `previously`, `latest`, `still`, `no longer`, `used to` | The moment of writing leaking into the text | Delete it, or restate the present-tense fact. Name a version when the fact is version-bound. |
| `as requested`, `as discussed`, `you asked`, `this change`, `this PR`, `this refactor` | The document addressing the requester instead of the reader | Delete the frame and keep the fact. |
| `click here`, `read more` | Anchor text with no meaning out of context | Name the destination. |
| A smart quote or a unicode arrow | Decoration that a keyboard does not produce | Straight quotes, or plain words. |

## Tier 2: Countable checks

1. **Sentence length.** Count the words in each sentence. The procedural limit is
   20 words. The descriptive limit is 25 words. A note takes 25 words.
   Backticked commands, numbers with units, and identifiers each count as one word
   (Rule 8.6).
2. **Paragraph size.** Six sentences maximum per paragraph (Rule 6.6).
3. **Multi-word nouns.** Break any noun chain over three words with a preposition
   (Rule 2.1).
4. **Instructions per sentence.** One, unless the actions are simultaneous
   (Rule 5.2).
5. **Bold-first bullets.** Count the list items that open with a bold keyword. When
   most of a list does this, the list reads as machine-written. Rewrite the items
   as sentences.

## Tier 3: Sentence judgment

6. **Classification.** Each passage is cleanly procedural or descriptive.
   Procedures use the imperative, and descriptions never do.
7. **Voice.** For every passive sentence, confirm that the agent is truly unknown
   and the passage is descriptive. Otherwise make it active (Rule 3.6).
8. **Condition placement.** Every "if" and "when" stands before its command, with a
   comma (Rule 5.4).
9. **Synonym rotation.** One term per concept across the whole document
   (Rules 1.11, 9.4). Scan for check and verify and confirm, for config and
   settings, and for run and execute.
10. **Warnings.** Command or condition first, risk second (Rules 7.2, 7.3).
11. **Completeness.** Articles present, "that" present after "make sure", and no
    telegraph style (Rule 4.2).
12. **Untouchables intact.** Code, identifiers, quoted errors, and proper nouns are
    unchanged.

## Tier 4: Structural judgment

These checks cover what the document contains, not how its sentences read. A draft
can pass every check above and still fail the reader.

13. **Accuracy.** Every command, flag, config key, default value, and described
    behavior matches the implementation. Verify against the code, not against the
    previous version of the document.
14. **Bottom line first.** The opening states what the reader accomplishes. It does
    not warm up.
15. **Scope.** The depth matches the document type. A README stays scannable in
    under two minutes. An API reference covers every public surface.
16. **Order.** Simple before complex. Quick start before deep dive. Prerequisites
    before the steps that need them.
17. **Examples.** Every concept carries a runnable example with real names, the
    expected output, and the common error case. No "foo" and no "bar".
18. **Links.** Every internal cross-reference and external URL resolves. New pages
    appear in the sidebar, the index, or the navigation config.
19. **Repetition.** No section summarizes a section the reader just finished. No
    idea appears in three phrasings. See "Fractal Summaries" and "One-Point
    Dilution" in `tropes.md`.
20. **Necessity.** Every section earns its place by helping the reader finish the
    task. Delete background nobody needs, an option nobody uses, and an internal
    detail that changes nothing for the caller.
21. **No context leak.** Read the draft as a stranger who opens it a year from
    now, with no view of the conversation or the change that produced it. Every
    sentence still makes sense, and no sentence describes the change itself.
    History belongs in the commit message.
22. **No decay.** No wording goes stale on the next release. "The latest version",
    "the upcoming API", and "soon" each name a version or state a durable fact
    instead.
23. **Tropes.** Read the draft against `tropes.md`. Rewrite any passage that
    carries one of those patterns.
24. **Right size.** The change matches the gap between the page and its goal. A
    page that needed reordering got reordered, and a page that needed replacing
    got replaced. An edit that stopped at the comfortable size fails this check.
25. **Tooling.** Run the formatter or linter for docs, if the project has one.

## Reporting violations (check mode)

For each violation give three things: the rule number, the offending text, and a
compliant rewrite. Cite only rule numbers that appear in `ste-rules.md`. Never cite a
rule number from memory, because the numbering is unintuitive and models invent it.

Structural findings carry no rule number. Report those by checklist item number and
name, such as "Item 17: examples use placeholder names".

When the user asked about ASD-STE100 compliance, end the report with this
statement: "No
tool can guarantee ASD-STE100 compliance. Final approval rests with the writer. The
official standard is a free download at asd-ste100.org."
