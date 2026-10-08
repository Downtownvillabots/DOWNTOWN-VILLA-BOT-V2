# ═══════════════════════════════════════════════════════════
# OTT CHANNEL BROADCAST SETUP
# ═══════════════════════════════════════════════════════════

def ott_channel_kb(tmdb_id: int, notify: bool = True) -> InlineKeyboardMarkup:
    """Buttons that appear on the channel post itself."""
    rows: List[List[InlineKeyboardButton]] = []
    if notify:
        rows.append([InlineKeyboardButton(
            f"🔔 {sc('Get Notified')}",
            callback_data=f"ott:sub:{tmdb_id}")])
        rows.append([InlineKeyboardButton(
            f"🎁 {sc('Add to watchlist')}",
            callback_data=f"ott:wl_add:{tmdb_id}")])
    rows.append([InlineKeyboardButton(
        f"📤 {sc('Share')}",
        callback_data=f"ott:share:{tmdb_id}")])
    return InlineKeyboardMarkup(rows)


def kb_bc_setup(tmdb_id: int, channel: int, notify: bool,
                 hours: int) -> InlineKeyboardMarkup:
    notify_lbl = "🟢 on" if notify else "🔴 off"
    timer_lbl = ("♾️ never" if hours <= 0 else f"⏱️ {hours}h")
    return InlineKeyboardMarkup([
        [InlineKeyboardButton(
            f"🔔 Notify button · {notify_lbl}",
            callback_data="ott:bcsetup_tog_notify")],
        [InlineKeyboardButton(
            f"🗑️ Auto-delete · {timer_lbl}",
            callback_data="ott:bcsetup_timer")],
        [InlineKeyboardButton(
            f"🚀 {sc('SEND TO CHANNEL NOW')}",
            callback_data="ott:bcsetup_send")],
        [InlineKeyboardButton(
            f"⬅️ Back", callback_data=f"ott:bc_mv:{tmdb_id}"),
         InlineKeyboardButton(
            f"❌ Close", callback_data="ott:close")],
    ])


def kb_bcsetup_timer(tmdb_id: int, current: int) -> InlineKeyboardMarkup:
    from plugins.ott.config import BC_DELETE_HOURS
    rows: List[List[InlineKeyboardButton]] = []
    row: List[InlineKeyboardButton] = []
    for h in BC_DELETE_HOURS:
        label = "♾️ never" if h == 0 else f"{h}h"
        mark = "✅ " if h == current else ""
        row.append(InlineKeyboardButton(
            f"{mark}{label}",
            callback_data=f"ott:bcsetup_timer_do:{h}"))
        if len(row) == 3:
            rows.append(row); row = []
    if row:
        rows.append(row)
    rows.append([InlineKeyboardButton(
        "⬅️ Back", callback_data=f"ott:bcsetup:{tmdb_id}")])
    return InlineKeyboardMarkup(rows)
