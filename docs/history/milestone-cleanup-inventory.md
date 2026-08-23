# Milestone cleanup inventory

This document records the deliberate cleanup performed before public release.
It is historical evidence and is not part of the current operator surface.

## Classification rules

| Previous material | Current artifact |
|---|---|
| lasting architecture decision | ADR under `docs/adr/` |
| supported operator behavior | current operations documentation |
| capability proof | capability-oriented acceptance script or test |
| real-run proof | sanitized external-repository case study |
| planning sequence | roadmap retained under `docs/history/` |
| obsolete setup note or compatibility wrapper | deleted |

## Completed cleanup

- Removed tracked Python bytecode, cache directories, and macOS archive metadata.
- Added a root `.gitignore` for runtime state, secrets, caches, editor files,
  temporary repositories, patches, and archives.
- Replaced milestone-named Compose, validation, smoke, unit, and acceptance paths
  with capability-oriented names.
- Removed redundant validation wrappers where a current capability acceptance
  already existed.
- Moved the active planning ladder into deliberate history.
- Replaced the committed repository example with a neutral disabled profile.
- Generalized real external-repository validation and case-study generation.
- Removed target task words from prompts, fake model responses, tests, examples,
  and current documentation.
- Added a deterministic repository-hygiene check that prevents reintroduction.

## Deliberate historical exceptions

Numbered milestone language may remain only under:

```text
docs/adr/
docs/history/
```

Those files explain how the architecture evolved. Current runtime, test,
operator, configuration, prompt, and fixture surfaces must remain capability
oriented.
