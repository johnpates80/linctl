# Story 2.3: Advanced Label Operators for Issue List/Search

**Epic:** Epic 2 - Issue Filtering & Search Enhancements
**Priority:** P2
**Status:** review
**Estimated Hours:** 3
**Dependencies:** 2-1 (filters), 2-2 (labels in outputs)

## User Story

As a linctl power user,
I want flexible label operators (OR, NOT, unlabeled),
So that I can express precise queries directly from the CLI.

## Acceptance Criteria

- [x] AC-1: `--label-any "a,b"` returns issues that have ANY of the given labels (OR semantics).
- [x] AC-2: `--label-not "x,y"` excludes issues that have ANY of the given labels.
- [x] AC-3: `--unlabeled` returns only issues with no labels; cannot be combined with other label filters.
- [x] AC-4: `--label` (AND) takes precedence when combined with other label flags; others are ignored with a warning.
- [x] AC-5: Works with both `issue list` and `issue search`, and composes with existing filters.

## Technical Notes

- `--label`: Resolve names → IDs; server filter `labels.some.id.in` + client-side AND enforcement.
- `--label-any`: Resolve names → IDs; server filter `labels.some.id.in` (OR semantics handled server-side).
- `--label-not`: Resolve names → IDs; server filter `labels.none.id.in`.
- `--unlabeled`: Client-side post-filter only (keep issues where labels is empty).
- Precedence: `--label` > (`--label-any`, `--label-not`, `--unlabeled`).

## Implementation Checklist

- [x] Add flags to both list/search: `--label-any`, `--label-not`, `--unlabeled`.
- [x] Extend filter builder to construct server filters and collect client post-filters.
- [x] Add advanced post-filter for AND/OR/NOT/unlabeled.
- [x] Warnings for conflicting flags when not using `--json`.
- [x] README updated with examples and flag descriptions.

## Definition of Done

- [x] All ACs satisfied and smoke verified on live project where feasible.
- [x] No regressions; build passes.
- [x] Documentation updated.

