# Domain Docs

This is a single-context repository. Engineering skills should consume its domain documentation using these rules.

## Before Exploring

- Read `CONTEXT.md` at the repository root when it exists.
- Read relevant architectural decisions under `docs/adr/` when that directory exists.
- If either is absent, proceed silently. Producer skills create these files lazily when terminology or a durable architectural decision is resolved.

## Layout

```text
/
|-- CONTEXT.md
|-- docs/
|   `-- adr/
`-- src/
```

## Vocabulary

Use canonical terms from `CONTEXT.md` in issue titles, plans, tests, and implementation. If a required concept is missing, reconsider whether new language is necessary or note the gap for a domain-modeling session.

## Architectural Decisions

Surface conflicts with existing ADRs explicitly rather than silently overriding them. Create an ADR only for a hard-to-reverse, surprising decision made through a genuine trade-off.
