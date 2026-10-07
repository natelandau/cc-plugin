# Writing commit subjects

A commit subject, or a PR title that becomes one, lands in the trunk history
and the release changelog. Write it as a summary of the work: what kind of
change this is and what it covers.

- Summarize what was done, not the results it produces. "clean up
  post-redesign performance and security" says what the work is. "harden sync
  and sign-out, and cut wasted redraws" lists effects and leaves the reader to
  guess what kind of change made them.
- Pick the type from the nature of the work, not from its best side effect. A
  cleanup that also closes a bug is still a `refactor`. Use `fix` when
  repairing a defect is the point of the change.
- When a change spans several concerns, name the kind of work and its themes.
  Do not enumerate each effect.
- Leave out which file or class changed and how it works. Those belong in the
  body or the PR's review sections.
- Write it from the diff it describes, not from earlier commit subjects.
  Commits describe steps. The subject summarizes the whole.
- Pair a verb like "improve", "update", or "enhance" with the specific thing
  that is better, or pick a stronger verb.
- Use as few words as the meaning needs. A short, plain subject beats a long,
  complete one. Cut qualifiers, and stop well before 70 characters when you
  can.
- No process or provenance references: "as discussed", "per review",
  "addresses feedback", mentions of agents, tools, conversations, or sessions,
  or a bare ticket or PR number as the payload.
- Test: would a reader scanning the log know what kind of change landed, and
  where?

| Avoid (results or mechanics)                                 | Prefer (summary of the work)                                     |
| ------------------------------------------------------------ | ---------------------------------------------------------------- |
| fix(apple): harden sync and sign-out, and cut wasted redraws | refactor(apple): clean up post-redesign performance and security |
| feat(settings): make text easier to read everywhere          | feat(settings): add an in-app text size setting                  |
| feat(s3): add HeadBucket call and optional credentials       | feat(s3): support the host's ambient credentials                 |
| fix(sync): never lose a change again                         | fix(sync): retry failed syncs with backoff                       |
| refactor: improve sync                                       | refactor(sync): split the sync engine into fetch and merge       |

The same bar holds for the body: fewer words beat more. If a sentence still
says the same thing with a clause cut, cut it.
