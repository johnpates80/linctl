    # Story 2.1: Issue List Filters by Project and Labels

**Epic:** Epic 2 - Issue Filtering & Search Enhancements
**Priority:** P2
**Status:** done
**Estimated Hours:** 4
**Dependencies:** None

## User Story

As a linctl user working in large projects,
I want to filter issues by project and labels from the CLI,
So that I can quickly narrow results without switching to the web UI.

## Acceptance Criteria

- [x] AC-1: `linctl issue list --team ENG --project PROJECT-UUID` returns only issues assigned to the specified project.
- [x] AC-2: `linctl issue list --team ENG --label "bug,backend"` returns only issues that include BOTH labels (AND semantics).
- [x] AC-3: Invalid project ID or unknown label name returns a clear error with suggestions for the closest label names.
- [x] AC-4: Filters work in combination with existing flags (`--assignee`, `--state`, `--priority`, `--include-completed`, `--newer-than`).
- [x] AC-5: JSON and plaintext outputs remain consistent; filtered results only.

## Technical Notes

- Extend `issue list` to accept `--project` and `--label` filters.
- Map label names to IDs via `GetIssueLabels` (issue labels) for filter construction.
- Resolve project by ID; do not fetch by name to avoid ambiguity.
- Build GraphQL `IssueFilter` accordingly (projectId, labels).
- Preserve paging, sorting, and existing output formatting.

## Implementation Checklist

- [x] Add flags to `issueListCmd`: `--project`, `--label`.
- [x] Validate and normalize flags; map labels → IDs.
- [x] Extend filter map for `GetIssues` (projectId, labelIds).
- [x] Keep AND semantics for multiple labels.
- [x] Update errors to include suggestions for label typos.
- [x] Ensure JSON/plaintext outputs unaffected except for filtering.
- [x] Update README usage examples for new filters.
- [x] Manual validation for combinations with `--assignee`, `--state`, `--priority`.

## Definition of Done

- [x] All acceptance criteria met
- [x] Flags documented in README
- [x] Errors include helpful suggestions for unknown labels
- [x] No regressions in `issue list` baseline behavior
- [x] Local tests pass, including manual validation steps
