# Story 3.3: Parent Info in List/Get Outputs

**Epic:** Epic 3 - Parent Issue Linking
**Priority:** P3
**Status:** done
**Estimated Hours:** 1
**Dependencies:** 3-1 (parent flags)

## User Story
As a linctl user scanning issue lists, I want to see the parent issue identifier so I can understand hierarchy at a glance.

## Acceptance Criteria
- [ ] AC-1: Table output adds a `Parent` column (identifier), truncated if needed.
- [ ] AC-2: Plaintext output shows `- Parent: <identifier>` when present.
- [ ] AC-3: JSON output includes `parent { id, identifier, title }` if available.

## Technical Notes
- Ensure queries fetch parent identifier in list/get.
- Keep column optional if future `--columns` supports it; default include OK.

## Implementation Checklist
- [ ] Extend queries to include parent identifier in list.
- [ ] Render Parent column/line; ensure no regressions.
- [ ] README examples.

## Definition of Done
- [ ] All ACs pass; build/tests pass; docs updated.
