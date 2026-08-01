# The ASD-STE100 rule catalog

53 rules in 9 sections, paraphrased from ASD-STE100 Issue 9 with software
examples. The official wording is in the free standard at asd-ste100.org.

Read this file when you need a rule number, when you are unsure how a rule
applies, or whenever the user asks you to CHECK text rather than write it. The
operational core of these rules already sits in SKILL.md, so routine writing
needs no trip here.

When you report a violation, give three things: the rule number, the offending
text, and a compliant rewrite. Cite only rule numbers that appear in this file.
Never cite a rule number from memory. The numbering is unintuitive and models
invent it. An agent without this file cited "Rule 3.1: short sentences", but the
real Rule 3.1 covers verb forms.

## Contents

| Section | Covers | Rules |
|---|---|---|
| [1](#section-1-words) | Words and one-name-per-item | 1.1 to 1.14 |
| [2](#section-2-multi-word-nouns) | Multi-word noun chains | 2.1 to 2.2 |
| [3](#section-3-verbs) | Verb forms, tense, voice, modals | 3.1 to 3.7 |
| [4](#section-4-sentences) | Sentence construction and completeness | 4.1 to 4.5 |
| [5](#section-5-procedural-writing) | Instructions, the 20-word limit, conditions | 5.1 to 5.5 |
| [6](#section-6-descriptive-writing) | Explanations, the 25-word limit, paragraphs | 6.1 to 6.6 |
| [7](#section-7-safety-instructions) | Warnings and cautions | 7.1 to 7.3 |
| [8](#section-8-punctuation-and-word-count) | Punctuation and how to count words | 8.1 to 8.7 |
| [9](#section-9-writing-practices) | Style, consistency, general recommendations | 9.1 to 9.4, GR-1 to GR-8 |

## Section 1: Words

| Rule | Instruction                                                                               |
| ---- | ----------------------------------------------------------------------------------------- |
| 1.1  | Use only approved words, technical nouns, or technical verbs.                             |
| 1.2  | Use an approved word only as its listed part of speech.                                   |
| 1.3  | Use an approved word only with its approved meaning.                                      |
| 1.4  | Use only the approved forms of verbs and adjectives.                                      |
| 1.5  | You can use domain words as technical nouns, such as "webhook", "commit", and "endpoint". |
| 1.6  | Use an unapproved word only when it is a technical noun or part of one.                   |
| 1.7  | Do not use technical nouns as verbs.                                                      |
| 1.8  | Use the technical nouns of the project or the industry.                                   |
| 1.9  | When you pick a technical noun, pick a short and clear one.                               |
| 1.10 | No regional, slang, or jargon words as technical nouns.                                   |
| 1.11 | One item, one name. Do not call it "config" here and "settings" there.                    |
| 1.12 | You can use domain verbs as technical verbs, such as "deploy", "compile", and "merge".    |
| 1.13 | Do not use technical verbs as nouns.                                                      |
| 1.14 | Use American English spelling.                                                            |

Rules 1.5, 1.8, and 1.12 make your domain vocabulary legal, so jargon that names a
real thing survives. The rules that agents break are 1.7, 1.11, and 1.13.

> **Before:** You can webhook the event, then do a deploy.
> **After:** Send the event to the webhook. Then deploy the service.

## Section 2: Multi-word nouns

| Rule | Instruction                                                                                                              |
| ---- | ------------------------------------------------------------------------------------------------------------------------ |
| 2.1  | Write multi-word nouns of three words or fewer.                                                                          |
| 2.2  | When a technical noun needs more than three words, write it in full once, then give a short form or hyphenate the units. |

Break a long noun chain with a preposition, such as of, on, in, or for.

> **Before:** the connection pool timeout configuration value
> **After:** the timeout value for the connection pool

## Section 3: Verbs

| Rule | Instruction                                                                                                                               |
| ---- | ----------------------------------------------------------------------------------------------------------------------------------------- |
| 3.1  | Use only the verb forms that the dictionary gives.                                                                                        |
| 3.2  | Use only the infinitive, the imperative, the simple present, the simple past, the simple future, and the past participle as an adjective. |
| 3.3  | Use the past participle only as an adjective, such as "the cached response".                                                              |
| 3.4  | No auxiliary verbs for complex constructions. No present perfect. No "is to be installed".                                                |
| 3.5  | Use an "-ing" form only as a technical noun or inside one, such as "logging" or "the mounting bracket". Never use it as a verb.           |
| 3.6  | Use the active voice. In descriptive text, the passive is legal only when the agent is unknown.                                           |
| 3.7  | Describe an action with a verb, not a noun. Write "compress the file", not "perform compression of the file".                             |

The approved modals are can, will, and must. The banned modals are should, would,
may, might, and could. The standard rejects "could" even for possibility, so write
"data loss can occur", never "could occur". This matters twice over for
documentation that an agent reads, because a model treats "should" as optional.

> **Before:** The migration has completed and the table is being rebuilt.
> **After:** The migration is complete. The database rebuilds the table.

> **Before:** The temperature must be adjusted.
> **After:** Adjust the temperature.

## Section 4: Sentences

| Rule | Instruction                                                                                           |
| ---- | ----------------------------------------------------------------------------------------------------- |
| 4.1  | Write short and clear sentences.                                                                      |
| 4.2  | Do not omit words or use contractions to shorten sentences. Keep the articles and keep "that".        |
| 4.3  | Use a vertical list for complex text.                                                                 |
| 4.4  | Use connecting words between sentences on related topics, such as "Then" or "As a result".            |
| 4.5  | Put an article (the, a, an) or a demonstrative adjective (this, these) before nouns where applicable. |

Rule 4.2 is the anti-terseness rule. STE is short sentences with complete grammar,
not telegraph style.

> **Wrong shortening:** Ensure file exists before running.
> **Correct:** Make sure that the file exists before you run the command.

## Section 5: Procedural writing

| Rule | Instruction                                                                                          |
| ---- | ---------------------------------------------------------------------------------------------------- |
| 5.1  | Maximum 20 words per sentence, warnings and cautions included.                                       |
| 5.2  | One instruction per sentence, unless two actions happen at the same time.                            |
| 5.3  | Write instructions in the imperative: "Run the migration."                                           |
| 5.4  | Put a required condition before the command, divided by a comma: "If the build fails, read the log." |
| 5.5  | Notes give information, never instructions. Notes take the 25-word limit.                            |

> **Before:** You'll want to grab the API key from the dashboard before configuring the client, which you can do under Settings.
> **After:** Get the API key from the dashboard, under Settings. Then configure the client with this key.

## Section 6: Descriptive writing

| Rule | Instruction                                                     |
| ---- | --------------------------------------------------------------- |
| 6.1  | Give information gradually. One new fact per sentence.          |
| 6.2  | Use key words and phrases to give the text a logical structure. |
| 6.3  | Maximum 25 words per sentence.                                  |
| 6.4  | Group related information in paragraphs.                        |
| 6.5  | One topic per paragraph.                                        |
| 6.6  | Maximum six sentences per paragraph.                            |

No imperative in descriptive text. Descriptions explain, and procedures instruct.

## Section 7: Safety instructions

| Rule | Instruction                                                                              |
| ---- | ---------------------------------------------------------------------------------------- |
| 7.1  | Use a word that shows the level of risk. "WARNING" means injury. "CAUTION" means damage. |
| 7.2  | Start with a clear command or condition.                                                 |
| 7.3  | Then give the risk or the possible result.                                               |

Never bury the instruction after the explanation. This pattern applies directly to
destructive CLI flags, irreversible migrations, and dangerous API options.

> **Before:** Note that data loss may occur in some circumstances if the destructive flag happens to be enabled when running against production.
> **After:** CAUTION: Do not use the `--force` flag against production. The flag deletes rows that do not match the source.

## Section 8: Punctuation and word count

| Rule | Instruction                                                                                                                                  |
| ---- | -------------------------------------------------------------------------------------------------------------------------------------------- |
| 8.1  | All standard punctuation is legal except the semicolon. Write two sentences instead.                                                         |
| 8.2  | Use hyphens to connect words that act as one unit.                                                                                           |
| 8.3  | Parentheses are legal for references, item numbers, abbreviations, plural forms, explanations, and alternatives.                             |
| 8.4  | In a vertical list, the lead-in colon ends a sentence for the word count.                                                                    |
| 8.5  | Text inside parentheses counts as one word.                                                                                                  |
| 8.6  | Count as one word each: numbers, numbers with units, abbreviations, alphanumeric identifiers, quoted text, titles, labels, and proper nouns. |
| 8.7  | A hyphenated word counts as one word.                                                                                                        |

Rule 8.6 matters for software text. A backticked command such as
`pytest --cov=src tests/` is quoted text and counts as one word, so long
identifiers never exhaust your sentence budget.

## Section 9: Writing practices

| Rule | Instruction                                                                                          |
| ---- | ---------------------------------------------------------------------------------------------------- |
| 9.1  | When a word-for-word replacement does not work, restructure the sentence.                            |
| 9.2  | Use each approved word correctly, with its approved meaning and part of speech.                      |
| 9.3  | Do not build phrasal verbs. "Go down" becomes "decrease". "Set up" becomes "install" or "configure". |
| 9.4  | Keep one consistent style and terminology through the whole document.                                |

General recommendations GR-1 to GR-8: keep the conjunction "that", take care with
"with", give every pronoun a clear referent, prefer "this" plus a noun over a bare
"this", avoid false friends, avoid Latin abbreviations, use inclusive language, and
use the possessive apostrophe only when you are certain it is correct. GR-8 is
explicit: when you are unsure, do not use it, because non-native readers find it
hard.

GR-6 in software docs: "e.g." becomes "for example", "i.e." becomes "that is", and
"etc." disappears. Name the items or write "and more".

