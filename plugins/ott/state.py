# ═══════════════════════════════════════════════════════════
# SETTINGS EDIT SESSIONS (caption / button text input)
# ═══════════════════════════════════════════════════════════

_SET_EDIT_SESSIONS: Dict[int, Dict[str, Any]] = {}
_SET_TTL = 600


def new_set_session(uid: int, kind: str, **data) -> None:
    _SET_EDIT_SESSIONS[int(uid)] = {
        "kind": kind,
        "data": data,
        "expires": time.time() + _SET_TTL,
    }


def get_set_session(uid: int) -> Optional[Dict[str, Any]]:
    s = _SET_EDIT_SESSIONS.get(int(uid))
    if not s:
        return None
    if time.time() > s["expires"]:
        _SET_EDIT_SESSIONS.pop(int(uid), None)
        return None
    return s


def clear_set_session(uid: int) -> None:
    _SET_EDIT_SESSIONS.pop(int(uid), None)


def cleanup_set_sessions() -> None:
    now = time.time()
    for uid in list(_SET_EDIT_SESSIONS.keys()):
        if _SET_EDIT_SESSIONS[uid]["expires"] < now:
            _SET_EDIT_SESSIONS.pop(uid, None)
