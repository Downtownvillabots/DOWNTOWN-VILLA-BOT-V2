# ═══════════════════════════════════════════════════════════
# BROADCAST SETUP (per-admin toggles before send)
# ═══════════════════════════════════════════════════════════

_SETUPS: Dict[int, Dict[str, Any]] = {}
SETUP_TTL = 1800


def setup_new(uid: int, tmdb_id: int, channel_id: int) -> None:
    _SETUPS[int(uid)] = {
        "tmdb_id": int(tmdb_id),
        "channel_id": int(channel_id),
        "notify": True,
        "auto_delete_hours": 24,
        "created": time.time(),
    }


def setup_get(uid: int) -> Optional[Dict[str, Any]]:
    return _SETUPS.get(int(uid))


def setup_drop(uid: int) -> None:
    _SETUPS.pop(int(uid), None)


def setup_cleanup() -> None:
    now = time.time()
    for uid in list(_SETUPS.keys()):
        if now - _SETUPS[uid]["created"] > SETUP_TTL:
            _SETUPS.pop(uid, None)
