# Story 2.2: Show Labels in Issue List Output

**Epic:** Epic 2 - Issue Filtering & Search Enhancements
**Priority:** P2
**Status:** review
**Estimated Hours:** 3
**Dependencies:** 2-1 (filters implemented)

## User Story

As a linctl user reviewing issue lists,
I want to see labels directly in the list output,
So that I can quickly understand categorization without opening each issue.

## Acceptance Criteria

- [x] AC-1: Table output includes a new "Labels" column showing up to 3 labels (comma-separated), truncated gracefully.
- [x] AC-2: Plaintext output shows a "- Labels:" line listing all labels for each issue, or "None" when absent.
- [x] AC-3: JSON output includes a `labels` array with `{ id, name }` for each issue node.
- [x] AC-4: When an issue has no labels, table shows "-" in the Labels column; plaintext shows "None"; JSON shows `labels: []`.
- [x] AC-5: Performance remains acceptable (no extra GraphQL requests beyond current list/search queries).

## Technical Notes

- Reuse labels already returned by existing queries in `pkg/api/queries.go` (`issues{ nodes{ labels{ nodes{ id name }}}}` already present).
- Table view: add a "Labels" column; render up to 3 names (e.g., `bug, backend, urgent`). Truncate cell to fit width constraints.
- Plaintext: add "- Labels:" with full list (no hard cap); if none, print "None".
- JSON: ensure `labels` array is serialized (already included when using `output.JSON(issues.Nodes)`).
- Keep current column widths reasonable; avoid wrapping excessively.

## Implementation Checklist

- [x] Update `renderIssueCollection` to compute a label string for each row.
- [x] Insert a "Labels" column into headers and rows.
- [x] Add plaintext rendering of labels with fallback to "None".
- [x] Validate JSON output includes labels (no code change expected).
- [x] Verify behavior for issues with 0, 1, and many labels.
- [x] Keep table width readable; truncate label list string if too long.
- [x] Update README example table to include Labels column snippet.

## Definition of Done

- [ ] All acceptance criteria pass with manual validation.
- [ ] README updated with an example including labels.
- [ ] No regressions in issue list/search; existing smoke tests pass.
- [ ] Works with other filters (assignee/state/team/priority/newer-than/project/label).
