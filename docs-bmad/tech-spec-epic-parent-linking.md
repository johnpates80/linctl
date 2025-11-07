# Tech Spec: Epic 3 - Parent Issue Linking

## Overview
Add parent-child issue linking to linctl so users can:
- Create sub-issues with `--parent <identifier>`
- Update an existing issue's parent (`--parent <identifier>` or `--parent unassigned`)
- Filter by parent relationships (future Story 3.2)
- Display parent info in list/get (future Story 3.3)

## GraphQL
- IssueCreateInput supports `parentId`
- IssueUpdateInput supports `parentId` (null removes)
- Query fields already include `parent { id identifier title }`

## CLI Changes
- issue create: add `--parent` flag, resolve identifier → node ID, set `parentId`
- issue update: add `--parent` flag, accept `unassigned` to clear parent
- README updated with examples

## Risks
- Identifier resolution depends on Linear API accepting `issue(id: "RAE-123")`; current code uses this for `issue get` successfully.
- Parent validation errors normalized to `Parent issue '<value>' not found` for consistency

