# BMAD Method - Claude Code Instructions

## Activating Agents

BMAD agents are installed as slash commands in `.claude/commands/bmad/`.

### How to Use

1. **Type Slash Command**: Start with `/` to see available commands
2. **Select Agent**: Type `/bmad-{agent-name}` (e.g., `/bmad-dev`)
3. **Execute**: Press Enter to activate that agent persona

### Examples

```
/bmad:bmm:agents:dev - Activate development agent
/bmad:bmm:agents:architect - Activate architect agent
/bmad:bmm:workflows:dev-story - Execute dev-story workflow
```

### Notes

- Commands are autocompleted when you type `/`
- Agent remains active for the conversation
- Start a new conversation to switch agents

## 🔗 Linear Integration with linctl

For Linear project management, use the `linctl` CLI tool which provides comprehensive Linear API access:

### Essential linctl Commands for Projects

```bash
# Project Management
linctl project list --include-completed    # List all projects
linctl project get PROJECT-UUID           # Get project details
linctl project create --name "Project" --team TEAM
linctl project update PROJECT-UUID --state started

# Project Updates (NEW)
linctl project update-post create PROJECT-UUID --body "Progress update..." --health "onTrack"
linctl project update-post list PROJECT-UUID

# Milestone Management (NEW)
linctl milestone create PROJECT-UUID --name "Milestone" --target-date "2025-12-31"
linctl milestone list PROJECT-UUID

# Issue Management with Project Assignment
linctl issue create --title "Feature" --team TEAM --project PROJECT-UUID
linctl issue update LIN-123 --project PROJECT-UUID

# Sub-Issues (Parent Linking) (NEW)
linctl issue create --title "Implement worker" --team ENG --parent RAE-123
linctl issue update LIN-123 --parent RAE-123        # set parent
linctl issue update LIN-123 --parent unassigned     # remove parent

# Label Management (NEW)
linctl issue update LIN-123 --label "bug,urgent"
linctl issue update LIN-123 --add-label "backend"

# Enhanced Search (NEW)
linctl issue search "authentication" --team ENG --project PROJECT-UUID

# Advanced Filters (NEW)
linctl issue list --label-any "bug,backend"         # OR semantics
linctl issue list --label-not "wontfix,duplicate"   # Exclude
linctl issue list --unlabeled                        # No labels
linctl issue list --parent RAE-123                   # Under specific parent
linctl issue list --has-parent                       # Only sub-issues
linctl issue list --no-parent                        # Only top-level issues
```

### Project Update Workflow

When working on Linear projects, create regular update posts:

```bash
# Daily/weekly progress updates
linctl project update-post create PROJECT-UUID \
  --body "Completed API integration, starting frontend development" \
  --health "onTrack"

# Risk reporting  
linctl project update-post create PROJECT-UUID \
  --body "Blocked by external dependency, team investigating alternatives" \
  --health "atRisk"
```

All linctl commands support `--json` output for automation and scripting.
