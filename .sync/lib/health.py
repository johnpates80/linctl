#!/usr/bin/env python3
"""
Health check utilities for BMAD sync system.

Computes a simple health score and status with diagnostics.
"""

from __future__ import annotations

import json
from pathlib import Path
import os
import stat
from typing import Dict, Any

from validator import validate_all
from linctl_wrapper import get_wrapper, LinctlError


def compute_health() -> Dict[str, Any]:
    """Compute overall health based on validations and environment checks."""
    diagnostics: Dict[str, Any] = {}
    score = 100

    # 1) Structural validations
    vrep = validate_all()
    diagnostics['validation'] = vrep
    if not vrep.get('ok', False):
        score -= 20

    # 2) State files readable
    state_ok = True
    state_dir = Path('.sync/state')
    for fname in ['content_index.json', 'sync_state.json', 'number_registry.json']:
        f = state_dir / fname
        try:
            if f.exists():
                json.loads(f.read_text(encoding='utf-8'))
            else:
                state_ok = False
        except Exception:
            state_ok = False
    diagnostics['state_files_ok'] = state_ok
    if not state_ok:
        score -= 15

    # 2b) State directory permissions (owner-only recommended)
    perms_ok = False
    try:
        st = os.stat(state_dir)
        mode = stat.S_IMODE(st.st_mode)
        # Require no group/other permissions
        perms_ok = (mode & 0o077) == 0
        diagnostics['state_dir_mode'] = oct(mode)
    except Exception:
        diagnostics['state_dir_mode'] = None
        perms_ok = False
    diagnostics['state_permissions_ok'] = perms_ok
    if not perms_ok:
        score -= 5

    # 3) linctl availability/auth (best-effort)
    linctl = {'installed': False, 'authenticated': False}
    try:
        wrapper = get_wrapper()
        _ = wrapper.check_installation()
        linctl['installed'] = True
        try:
            _ = wrapper.validate_auth()
            linctl['authenticated'] = True
        except LinctlError:
            pass
    except LinctlError:
        pass
    diagnostics['linctl'] = linctl
    if not linctl['installed']:
        score -= 10
    elif not linctl['authenticated']:
        score -= 5

    # Bound score
    score = max(0, min(100, score))
    status = 'OK' if score >= 80 else 'DEGRADED' if score >= 60 else 'POOR'

    return {'status': status, 'score': score, 'diagnostics': diagnostics}


if __name__ == '__main__':
    print(json.dumps(compute_health(), indent=2))
