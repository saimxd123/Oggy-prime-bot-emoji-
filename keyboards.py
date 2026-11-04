"""
keyboards.py — inline keyboards + raw Bot API helpers.
"""
import asyncio
import requests

from config import BOT_TOKEN, OWNER_ID


# ══════════════════════════════════════════════════════════
# Shared HTTP session
# ══════════════════════════════════════════════════════════
_http_session = requests.Session()


# ══════════════════════════════════════════════════════════
# Raw Bot API — sync core  ← bot.py imports this
# ══════════════════════════════════════════════════════════
def _raw_post(method, payload, timeout=15):
    """Synchronous POST to Telegram Bot API. Returns parsed JSON."""
    url = f"https://api.telegram.org/bot{BOT_TOKEN}/{method}"
    try:
        r = _http_session.post(url, json=payload, timeout=timeout)
        return r.json()
    except Exception:
        return {"ok": False}


# ══════════════════════════════════════════════════════════
# Async wrappers
# ══════════════════════════════════════════════════════════
async def raw_send(chat_id, text, buttons=None, reply_to=None):
    payload = {
        "chat_id": chat_id,
        "text": text,
        "parse_mode": "HTML",
        "disable_web_page_preview": True,
    }
    if reply_to is not None:
        payload["reply_to_message_id"] = reply_to
    if buttons:
        payload["reply_markup"] = {"inline_keyboard": buttons}
    data = await asyncio.to_thread(_raw_post, "sendMessage", payload)
    return data["result"]["message_id"] if data.get("ok") else None


async def raw_edit(chat_id, message_id, text, buttons=None):
    payload = {
        "chat_id": chat_id,
        "message_id": message_id,
        "text": text,
        "parse_mode": "HTML",
        "disable_web_page_preview": True,
    }
    if buttons is not None:
        payload["reply_markup"] = {"inline_keyboard": buttons}
    data = await asyncio.to_thread(_raw_post, "editMessageText", payload)
    if data.get("ok"):
        return True
    if "message is not modified" in (data.get("description") or "").lower():
        return True
    return False


async def nav_edit(chat_id, message_id, text, buttons=None):
    return await raw_edit(chat_id, message_id, text, buttons or [])


# ══════════════════════════════════════════════════════════
# Sync helpers (call via asyncio.to_thread)
# ══════════════════════════════════════════════════════════
def _send_notification(chat_id, text):
    data = _raw_post("sendMessage", {
        "chat_id": chat_id, "text": text,
        "parse_mode": "HTML", "disable_web_page_preview": True,
    })
    return data["result"]["message_id"] if data.get("ok") else None


def _pin_message_botapi(chat_id, message_id):
    return _raw_post("pinChatMessage", {
        "chat_id": chat_id, "message_id": message_id,
        "disable_notification": True,
    })


def _to_chat_id(ref):
    if isinstance(ref, int):
        return ref
    if isinstance(ref, str) and ref.lstrip('-').isdigit():
        return int(ref)
    return ref


def _get_chat_member(chat, uid):
    data = _raw_post("getChatMember", {
        "chat_id": _to_chat_id(chat), "user_id": int(uid),
    })
    if not data.get("ok"):
        return False
    return data["result"].get("status") in ("creator", "administrator", "member")


def _get_chat_info(chat):
    data = _raw_post("getChat", {"chat_id": _to_chat_id(chat)})
    if not data.get("ok"):
        return None
    r = data["result"]
    return {"id": r.get("id"), "username": r.get("username"), "title": r.get("title")}


def _get_join_link(chat):
    info = _get_chat_info(chat)
    if not info:
        return None
    if info.get("username"):
        return f"https://t.me/{info['username']}"
    data = _raw_post("exportChatInviteLink", {"chat_id": _to_chat_id(chat)})
    return data.get("result") if data.get("ok") else None


# ══════════════════════════════════════════════════════════
# Menus
# ══════════════════════════════════════════════════════════
def rows_main():
    return [
        [{"text": "🔥  Gates",  "callback_data": "gates"}],
        [{"text": "🔑  Redeem", "callback_data": "redeem_info"},
         {"text": "🔌  Proxy",  "callback_data": "manage_proxy"}],
        [{"text": "👑  Admin Panel", "callback_data": "admin_panel"}],
        [{"text": "❌  Close",  "callback_data": "close"}],
    ]


def rows_gates():
    return [
        [{"text": "💳  Shopify",         "callback_data": "gate_shopify"}],
        [{"text": "🔥  Stripe 1$",       "callback_data": "gate_st1"},
         {"text": "💎  Stripe 5$",       "callback_data": "gate_st5"}],
        [{"text": "✅  Stripe Auth2 $0", "callback_data": "gate_auth"}],
        [{"text": "⚡  Stripe Auth2 v2",  "callback_data": "gate_auth1"}],
        [{"text": "🅱️  Braintree",       "callback_data": "gate_btauth"}],
        [{"text": "🔑  Manage Proxy",    "callback_data": "manage_proxy"}],
        [{"text": "↪️  Back",            "callback_data": "back_start"}],
    ]


def rows_proxy(uid):
    return [
        [{"text": "🧪  Test Proxy", "callback_data": "test_proxy_btn"},
         {"text": "🗑️  Remove",     "callback_data": "remove_proxy_btn"}],
        [{"text": "↪️  Back",       "callback_data": "back_start"}],
    ]


def rows_stop():
    return [[{"text": "⛔  Stop Check", "callback_data": "stop_mass"}]]


def rows_admin(uid):
    is_owner = (uid == OWNER_ID)
    rows = [
        [{"text": "👤  Users", "callback_data": "admin_users"},
         {"text": "🌐  Sites", "callback_data": "admin_sites"}],
        [{"text": "📡  Proxy Pool", "callback_data": "admin_proxy_pool"}],
        [{"text": "📢  Broadcast",  "callback_data": "admin_broadcast_info"}],
        [{"text": "📦  Backup",     "callback_data": "admin_backup"},
         {"text": "♻️  Restore",    "callback_data": "admin_restore_info"}],
    ]
    if is_owner:
        rows.append([{"text": "🔌  API Endpoints", "callback_data": "owner_api_eps"}])
        rows.append([{"text": "🔑  Keys",          "callback_data": "owner_keys"},
                     {"text": "🛡  GC/Channels",   "callback_data": "owner_gc"}])
    rows.append([{"text": "↪️  Back", "callback_data": "back_start"}])
    return rows


def rows_admin_users():
    return [
        [{"text": "📋  List Users", "callback_data": "admin_list_users"}],
        [{"text": "✅  Add User",   "callback_data": "admin_add_user_info"},
         {"text": "❌  Remove",     "callback_data": "admin_rm_user_info"}],
        [{"text": "↪️  Back",       "callback_data": "admin_panel"}],
    ]


def rows_admin_sites():
    return [
        [{"text": "📋  List Sites", "callback_data": "admin_list_sites_cb"}],
        [{"text": "✅  Add Site",   "callback_data": "admin_add_site_info"},
         {"text": "❌  Remove",     "callback_data": "admin_rm_site_info"}],
        [{"text": "↪️  Back",       "callback_data": "admin_panel"}],
    ]


def rows_admin_proxy_pool():
    return [
        [{"text": "📋  List Pool", "callback_data": "admin_list_proxy_cb"}],
        [{"text": "✅  Add",       "callback_data": "admin_add_proxy_info"},
         {"text": "🗑️  Clear",     "callback_data": "admin_clear_proxy_cb"}],
        [{"text": "↪️  Back",      "callback_data": "admin_panel"}],
    ]


def rows_owner_api_eps():
    return [
        [{"text": "📋  List", "callback_data": "owner_api_list"}],
        [{"text": "✅  Add",  "callback_data": "owner_api_add_info"},
         {"text": "❌  Remove", "callback_data": "owner_api_rm_info"}],
        [{"text": "↪️  Back", "callback_data": "admin_panel"}],
    ]


def rows_owner_keys():
    return [
        [{"text": "📋  List Keys",     "callback_data": "owner_key_list"}],
        [{"text": "✅  Generate Keys", "callback_data": "owner_key_gen_info"}],
        [{"text": "↪️  Back",          "callback_data": "admin_panel"}],
    ]


def rows_owner_gc():
    return [
        [{"text": "🔒  Private GC",     "callback_data": "owner_gc_private"}],
        [{"text": "🌐  Public GC",      "callback_data": "owner_gc_public"}],
        [{"text": "📝  Log GC",         "callback_data": "owner_gc_log"}],
        [{"text": "📢  Public Channel", "callback_data": "owner_gc_channel"}],
        [{"text": "🔗  Required Chans", "callback_data": "owner_gc_req"}],
        [{"text": "↪️  Back",           "callback_data": "admin_panel"}],
    ]
