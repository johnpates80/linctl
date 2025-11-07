# Epic 3: Parent Issue Linking

**Slug:** parent-linking
**Date:** 2025-11-07

### Goal
Enable creating and managing sub-issues entirely from the CLI: set a parent on creation, update an existing issue to become a sub-issue, and remove a parent to de-nest. Provide basic filters to work with parent/child relationships.

### Scope
**In Scope:**
- Set parent when creating issues (flag)
- Set/remove parent for existing issues (update flags)
- List/search filters for parent relationships
- Minimal output enhancement to improve visibility

**Out of Scope:**
- Deep tree operations (multi-level bulk restructure)
- Drag-and-drop reordering or interactive TUI

### Success Criteria
1. Users can set a parent during `issue create`.
2. Users can set/remove a parent during `issue update`.
3. Users can filter lists by `--parent` and `--has-parent`.
4. List/plaintext output shows parent identifier when present.

### Story Map
```
Epic: Parent Issue Linking
├── Story 3.1: Parent Flags on Create/Update (2 pts)
├── Story 3.2: Parent Filters for List/Search (2 pts)
└── Story 3.3: Parent Info in Outputs (1 pt)
```

