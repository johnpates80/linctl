#!/usr/bin/env python3
"""
Rollback utilities for BMAD sync system.

Restores the most recent pre-sync backup from .sync/backups.
Enhanced with comprehensive logging for Story 3.4.
"""

from __future__ import annotations

import shutil
import json
from pathlib import Path
from typing import Optional, List, Dict, Any
from datetime import datetime

from logger import get_logger


def _find_sync_root(start: Optional[Path] = None) -> Path:
    cur = start or Path.cwd()
    while cur != cur.parent:
        if (cur / '.sync').exists():
            return cur / '.sync'
        cur = cur.parent
    return Path('.sync')


def preview_rollback(sync_root: Optional[Path] = None) -> Dict[str, Any]:
    """
    Preview what would be restored in a rollback.

    Args:
        sync_root: Optional sync root directory

    Returns:
        Dictionary with rollback preview information
    """
    sync_root = sync_root or _find_sync_root()
    backups_dir = sync_root / 'backups'
    state_dir = sync_root / 'state'

    if not backups_dir.exists():
        return {
            "available": False,
            "message": "No backup directory found"
        }

    # Find latest pre-sync directory
    candidates = sorted([p for p in backups_dir.iterdir() if p.is_dir() and p.name.startswith('pre-sync-')])
    if not candidates:
        return {
            "available": False,
            "message": "No backups available"
        }

    latest = candidates[-1]

    # Extract timestamp from directory name (format: pre-sync-YYYYMMDDHHMMSS)
    timestamp_str = latest.name.replace('pre-sync-', '')
    try:
        backup_time = datetime.strptime(timestamp_str, '%Y%m%d%H%M%S')
        formatted_time = backup_time.strftime('%Y-%m-%d %H:%M:%S')
    except ValueError:
        formatted_time = timestamp_str

    # Get file information
    files_to_restore = []
    for name in ['content_index.json', 'sync_state.json', 'number_registry.json']:
        src = latest / name
        dst = state_dir / name

        if src.exists():
            # Get content preview
            current_exists = dst.exists()
            current_size = dst.stat().st_size if current_exists else 0
            backup_size = src.stat().st_size

            # For content_index, show story count difference
            if name == 'content_index.json' and current_exists:
                try:
                    with open(src, 'r') as f:
                        backup_data = json.load(f)
                    with open(dst, 'r') as f:
                        current_data = json.load(f)

                    backup_stories = len(backup_data.get('stories', {}))
                    current_stories = len(current_data.get('stories', {}))

                    files_to_restore.append({
                        "name": name,
                        "backup_size": backup_size,
                        "current_size": current_size,
                        "backup_stories": backup_stories,
                        "current_stories": current_stories,
                        "story_diff": backup_stories - current_stories
                    })
                except Exception:
                    files_to_restore.append({
                        "name": name,
                        "backup_size": backup_size,
                        "current_size": current_size
                    })
            else:
                files_to_restore.append({
                    "name": name,
                    "backup_size": backup_size,
                    "current_size": current_size
                })

    return {
        "available": True,
        "backup_path": str(latest),
        "backup_time": formatted_time,
        "files_to_restore": files_to_restore,
        "total_files": len(files_to_restore)
    }


def rollback_last(sync_root: Optional[Path] = None, log_operation: bool = True) -> Dict[str, Any]:
    """
    Restore the latest pre-sync backup set with comprehensive logging.

    Args:
        sync_root: Optional sync root directory
        log_operation: Whether to log the rollback operation

    Returns:
        Dictionary with rollback summary:
        {
            'success': bool,
            'restored_files': List[str],
            'backup_used': str,
            'timestamp': str,
            'reason': str,
            'errors': List[str]
        }
    """
    sync_root = sync_root or _find_sync_root()
    backups_dir = sync_root / 'backups'
    state_dir = sync_root / 'state'
    logger = get_logger() if log_operation else None

    result = {
        'success': False,
        'restored_files': [],
        'backup_used': None,
        'timestamp': datetime.now().isoformat(),
        'reason': 'manual_rollback',
        'errors': []
    }

    if not backups_dir.exists():
        error_msg = "No backup directory found"
        result['errors'].append(error_msg)
        if logger:
            logger.error("Rollback failed: No backup directory", context={"path": str(backups_dir)})
        return result

    # Find latest pre-sync directory
    candidates = sorted([p for p in backups_dir.iterdir() if p.is_dir() and p.name.startswith('pre-sync-')])
    if not candidates:
        error_msg = "No backup snapshots available"
        result['errors'].append(error_msg)
        if logger:
            logger.error("Rollback failed: No backups", context={"path": str(backups_dir)})
        return result

    latest = candidates[-1]
    result['backup_used'] = str(latest)

    if logger:
        logger.info(
            "Starting rollback operation",
            context={
                "backup": latest.name,
                "backup_path": str(latest),
                "files_to_restore": ['content_index.json', 'sync_state.json', 'number_registry.json']
            }
        )

    # Restore each file
    for name in ['content_index.json', 'sync_state.json', 'number_registry.json']:
        src = latest / name
        dst = state_dir / name

        if src.exists():
            try:
                # Backup current file before overwriting
                if dst.exists():
                    backup_current = dst.with_suffix(dst.suffix + '.pre-rollback')
                    shutil.copy2(dst, backup_current)

                # Restore from backup
                shutil.copy2(src, dst)
                result['restored_files'].append(str(dst))

                if logger:
                    logger.info(
                        f"Restored {name}",
                        context={
                            "source": str(src),
                            "destination": str(dst),
                            "size": src.stat().st_size
                        }
                    )
            except Exception as e:
                error_msg = f"Failed to restore {name}: {e}"
                result['errors'].append(error_msg)
                if logger:
                    logger.error(
                        f"File restoration failed: {name}",
                        context={"error": str(e), "source": str(src), "dest": str(dst)}
                    )
        else:
            if logger:
                logger.warning(
                    f"Backup file not found: {name}",
                    context={"expected_path": str(src)}
                )

    result['success'] = len(result['restored_files']) > 0 and len(result['errors']) == 0

    if logger:
        logger.info(
            "Rollback operation completed",
            context={
                "success": result['success'],
                "files_restored": len(result['restored_files']),
                "errors": len(result['errors'])
            }
        )

    # Write rollback log
    log_rollback_operation(result, sync_root)

    return result


def log_rollback_operation(result: Dict[str, Any], sync_root: Path) -> Path:
    """
    Log rollback operation to a persistent log file.

    Args:
        result: Rollback result dictionary
        sync_root: Sync root directory

    Returns:
        Path to log file
    """
    log_dir = sync_root / 'logs'
    log_dir.mkdir(parents=True, exist_ok=True)

    log_file = log_dir / 'rollback_history.json'

    # Load existing log
    history = []
    if log_file.exists():
        try:
            history = json.loads(log_file.read_text(encoding='utf-8'))
        except Exception:
            history = []

    # Append new entry
    history.append(result)

    # Keep last 100 entries
    history = history[-100:]

    # Write atomically
    temp_file = log_file.with_suffix('.tmp')
    temp_file.write_text(json.dumps(history, indent=2), encoding='utf-8')
    temp_file.replace(log_file)

    return log_file


def render_rollback_preview(preview: Dict[str, Any]) -> str:
    """
    Render rollback preview as formatted text.

    Args:
        preview: Rollback preview dictionary

    Returns:
        Formatted preview text
    """
    lines = []

    lines.append("=" * 60)
    lines.append("ROLLBACK PREVIEW")
    lines.append("=" * 60)
    lines.append("")

    if not preview.get("available"):
        lines.append(f"❌ {preview.get('message', 'No rollback available')}")
        lines.append("")
        lines.append("=" * 60)
        return "\n".join(lines)

    lines.append(f"✓ Backup Available")
    lines.append(f"  Created: {preview['backup_time']}")
    lines.append(f"  Location: {preview['backup_path']}")
    lines.append(f"  Files to restore: {preview['total_files']}")
    lines.append("")

    lines.append("FILES TO RESTORE:")
    for file_info in preview['files_to_restore']:
        lines.append(f"  • {file_info['name']}")
        lines.append(f"    Backup size: {file_info['backup_size']} bytes")
        lines.append(f"    Current size: {file_info['current_size']} bytes")

        if 'story_diff' in file_info:
            diff = file_info['story_diff']
            if diff > 0:
                lines.append(f"    Stories: {file_info['backup_stories']} (current: {file_info['current_stories']}, +{diff})")
            elif diff < 0:
                lines.append(f"    Stories: {file_info['backup_stories']} (current: {file_info['current_stories']}, {diff})")
            else:
                lines.append(f"    Stories: {file_info['backup_stories']} (no change)")
        lines.append("")

    lines.append("=" * 60)
    lines.append("⚠️  WARNING: Rollback will overwrite current state files")
    lines.append("=" * 60)

    return "\n".join(lines)


if __name__ == '__main__':
    files = rollback_last()
    for f in files:
        print(f)

