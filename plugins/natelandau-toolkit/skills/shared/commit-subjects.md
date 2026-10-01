# Writing commit subjects

A commit subject, or a PR title that becomes one, lands in the trunk history
and the release changelog. Write it as a changelog headline: the capability a
user gains, or the failure that stops happening.

- Name the capability and its visible effect. Leave out where it lives in the
  UI, which file or class changed, and how it works. Those belong in the body
  or the PR's review sections.
- Write it from the diff it describes, not from earlier commit subjects.
  Commits describe steps. The subject describes the outcome.
- Pair a verb like "improve", "update", or "enhance" with the specific thing
  that is better, or pick a stronger verb.
- Use as few words as the meaning needs. A short, plain subject beats a long,
  complete one. Cut qualifiers, and stop well before 70 characters when you
  can.
- When the type has no user-visible effect (`refactor`, `test`, `ci`,
  `build`), name the area and the result for a maintainer instead.
- No process or provenance references: "as discussed", "per review",
  "addresses feedback", mentions of agents, tools, conversations, or sessions,
  or a bare ticket or PR number as the payload.
- Test: would a user scanning release notes know what they get?

| Mechanical (avoid)                                    | Headline (prefer)                                   |
| ----------------------------------------------------- | --------------------------------------------------- |
| shift text size in Settings and scale spacing with it | add an in-app text size that scales the UI          |
| add HeadBucket call and optional credentials to S3    | authenticate S3 with the host's ambient credentials |
| wrap fetch in retry loop with backoff                 | retry a failed sync instead of dropping the change  |
| improve sync                                          | keep local edits when the app updates its database  |

The same bar holds for the body: fewer words beat more. If a sentence still
says the same thing with a clause cut, cut it.
