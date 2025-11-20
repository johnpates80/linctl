# Story 3.2: Parent Filters for Issue List/Search

**Epic:** Epic 3 - Parent Issue Linking
**Priority:** P2
**Status:** done
**Estimated Hours:** 2
**Dependencies:** 3-1 (parent flags)

## User Story
As a linctl user, I want to filter issues by parent relationships, so I can focus on sub-issues under a specific parent or find top-level issues.

## Acceptance Criteria
- [ ] AC-1: `linctl issue list --parent RAE-123` shows only issues whose parent is `RAE-123`.
- [ ] AC-2: `linctl issue list --has-parent` shows only issues that are sub-issues (any parent).
- [ ] AC-3: `linctl issue list --no-parent` shows only issues without a parent.
- [ ] AC-4: Works with other filters and search.

## Technical Notes
- Add `--parent` (identifier), `--has-parent` (bool), `--no-parent` (bool; mutually exclusive).
- For `--parent`, resolve identifier to node ID.
- Server filter example: `parent { id: { eq: <nodeID> } }` if supported; fallback to client-side filtering.

## Implementation Checklist
- [ ] Add flags (list/search) and validate conflicts.
- [ ] Resolve identifier; build server filters; add client post-filter as fallback.
- [ ] README updates with examples.

## Definition of Done
- [ ] All ACs pass; build/tests pass.
