# .sync Directory Structure

This directory contains all state, configuration, and temporary files for the BMAD ↔ Linear synchronization system.

## Directory Purpose

### `config/`
**Purpose:** Configuration files for sync operations
**Tracked:** YES (committed to git)
**Contents:**
- `sync_config.yaml` - Main configuration file with BMAD ↔ Linear settings
- `state_mapping.yaml` - BMAD status to Linear state mappings

### `state/`
**Purpose:** Local state tracking and sync metadata
**Tracked:** NO (git ignored)
**Contents:**
- `content_index.json` - Content hashes and metadata
- `sync_state.json` - Last sync timestamps and operations
- `number_registry.json` - RAE-XXX issue number assignments

**Permissions:** Restricted (700) - contains sync session data

### `logs/`
**Purpose:** Sync operation logs
**Tracked:** NO (git ignored)
**Contents:**
- `sync.log` - Main log file (rotated daily or by size)
- Rotation: Last 30 days kept automatically

### `cache/`
**Purpose:** Temporary cache data during sync operations
**Tracked:** NO (git ignored)
**Contents:** Temporary files created during sync, cleaned up automatically

### `backups/`
**Purpose:** State file backups before operations
**Tracked:** NO (git ignored)
**Contents:** Timestamped copies of state files before each sync

## Security Notes

- Never commit API keys or tokens (use environment variables)
- `state/` directory has restricted permissions (700)
- Logs are sanitized to remove sensitive tokens
- API keys read from `LINEAR_API_KEY` environment variable or `~/.linctl-auth.json`

## Maintenance

- Logs rotate automatically (daily or when > 10MB)
- Old backups cleaned up after 30 days
- Cache cleared after successful sync operations
