# Story 3.1: Parent Flags on Create/Update

**Epic:** Epic 3 - Parent Issue Linking
**Priority:** P2
**Status:** drafted
**Estimated Hours:** 2
**Dependencies:** None

## User Story
As a linctl user, I want to set or remove a parent issue on creation and update so I can manage sub-issue hierarchies from the CLI.

## Acceptance Criteria
- [ ] AC-1: `linctl issue create --title "..." --team ENG --parent PARENT-ID` creates a sub-issue under the specified parent (by issue ID, e.g., `RAE-123`).
- [ ] AC-2: `linctl issue update ISS-123 --parent PARENT-ID` sets the issue's parent.
- [ ] AC-3: `linctl issue update ISS-123 --parent unassigned` removes the parent (issue becomes a top-level issue).
- [ ] AC-4: Invalid parent (not found) returns a clear error: `Parent issue 'X' not found`.

## Technical Notes
- On create/update, resolve `PARENT-ID` (identifier like `RAE-123`) to the underlying GraphQL node ID via `GetIssue` call.
- Add optional `parentId` to mutations: create/update should accept `parentId: String` (null for removal).
- Validate that parent belongs to the same team/project constraints as required by Linear (if any).

## Implementation Checklist
- [ ] Add `--parent` to `issue create` and `issue update`.
- [ ] Implement identifier → node ID resolution (reuse existing `GetIssue`).
- [ ] Update mutation inputs to set/remove `parentId`.
- [ ] Standardize not-found error messaging.
- [ ] README: document flags and examples.

## Definition of Done
- [ ] All ACs pass with manual tests.
- [ ] Build/tests pass; docs updated.

