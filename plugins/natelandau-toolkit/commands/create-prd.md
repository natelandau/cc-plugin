---
name: create-prd
description: Generate a comprehensive Product Requirements Document (PRD) from conversation context
argument-hint: output_file
---

# Create PRD

Generate a Product Requirements Document (PRD) from the requirements discussed
in the current conversation. Write it to `$ARGUMENTS` (default: `PRD.md`).

## Instructions

1. Extract the requirements. Review the whole conversation. Identify explicit
   requirements and implicit needs, technical constraints and preferences, and
   the user's goals and success criteria.
2. If critical information is missing, ask clarifying questions before you
   generate the document.
3. Organize the requirements into the sections below. Fill gaps with
   reasonable assumptions and mark each one. Keep the sections consistent with
   each other.
4. Write the PRD. Use markdown headings, lists, tables, code blocks, and
   checkboxes. Mark in-scope items with a checkmark and out-of-scope items
   with an X. Prefer concrete examples over abstract descriptions. Add code
   snippets to technical sections where they help. Use one term per concept
   throughout.
5. Adapt the depth of each section to the available detail. For a technical
   product, emphasize architecture and the technology stack. For a user-facing
   product, emphasize user stories and experience.

## PRD structure

Include every required section. Sections marked "if applicable" can be
omitted.

1. Executive Summary: a two-to-three paragraph product overview, the core
   value proposition, and the MVP goal statement.
2. Mission: the mission statement and three to five core principles.
3. Target Users: primary personas, their technical comfort level, and their
   key needs and pain points.
4. MVP Scope: in-scope and out-of-scope items as checkboxes, grouped by
   category (Core Functionality, Technical, Integration, Deployment).
5. User Stories: five to eight stories in the form "As a [user], I want to
   [action], so that [benefit]", each with a concrete example. Add technical
   user stories where relevant.
6. Core Architecture and Patterns: the high-level approach, the directory
   structure if applicable, and the key design patterns.
7. Tools or Features: detailed feature specifications. For an agent, the tool
   designs with purpose, operations, and key features. For an app, the core
   feature breakdown.
8. Technology Stack: backend and frontend technologies with versions,
   dependencies, optional dependencies, and third-party integrations.
9. Security and Configuration: authentication and authorization, configuration
   management (environment variables, settings), the security scope, and
   deployment considerations.
10. API Specification (if applicable): endpoints, request and response
    formats, authentication requirements, and example payloads.
11. Success Criteria: the MVP success definition, functional requirements as
    checkboxes, quality indicators, and user experience goals.
12. Implementation Phases: three to four phases, each with a goal,
    deliverables as checkboxes, validation criteria, and a realistic
    timeline.
13. Future Considerations: post-MVP enhancements, integration opportunities,
    and advanced features.
14. Risks and Mitigations: three to five key risks, each with a specific
    mitigation.
15. Appendix (if applicable): related documents, key dependencies with links,
    and the repository structure.

## Quality checks

Before you write the file, confirm that:

- every required section is present;
- every user story states a clear benefit;
- the MVP scope is realistic and well defined;
- the technology choices are justified;
- the implementation phases are actionable;
- the success criteria are measurable.

## After writing

1. Confirm the file path.
2. Summarize the PRD contents briefly.
3. List the assumptions you made because information was missing.
4. Suggest next steps, such as review, refinement, or planning.
