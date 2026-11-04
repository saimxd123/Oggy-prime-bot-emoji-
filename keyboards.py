"""
keyboards.py — inline keyboards wired to your emojis.py.

Uses the two helpers exported by emojis.py:
    _btn_icon_id(text)   → returns Telegram custom-emoji ID for the first
                          emoji in the text, or None
    _clean_btn_text(text) → strips the leading emoji from the label

Buttons set `icon_custom_emoji_id` so Telegram renders the premium
colored icon, while text stays clean.
"""
import asyncio
import requests

from config import BOT_TOKEN, OWNER_ID
from emojis import SEP, _btn_icon_id, _clean_btn_text


_http_session = requests.Session()


# ══════════════════════════════════════════════════════════
# Raw Bot API
# ══════════════════════════════════════════════════════════
def _raw_post(method, payload, timeout=15):
    url = f"https://api.telegram.org/bot{BOT_TOKEN}/{method}"
    try:
        r = _http_session.post(url, json=payload, timeout=timeout)
        return r.json()
    except Exception:
        return {"ok": False}


async def raw_send(chat_id, text, buttons=None, reply_to=None):
    payload = {
        "chat_id": chat_id, "text": text,
        "parse_mode": "HTML", "disable_web_page_preview": True,
    }
    if reply_to is not None:
        payload["reply_to_message_id"] = reply_to
    if buttons:
        payload["reply_markup"] = {"inline_keyboard": buttons}
    data = await asyncio.to_thread(_raw_post, "sendMessage", payload)
    return data["result"]["message_id"] if data.get("ok") else None


async def raw_edit(chat_id, message_id, text, buttons=None):
    payload = {
        "chat_id": chat_id, "message_id": message_id,
        "text": text, "parse_mode": "HTML",
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
# Sync helpers
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
# Button builder — auto-extracts icon from leading emoji
# ══════════════════════════════════════════════════════════
def _b(text, cb_data):
    """
    Build a callback button.
    Text must START with an emoji that exists in BUTTON_CUSTOM_EMOJIS.
    Emoji is stripped from visible label and attached as icon.
    """
    icon_id = _btn_icon_id(text)
    clean = _clean_btn_text(text)
    btn = {"text": clean, "callback_data": cb_data}
    if icon_id:
        btn["icon_custom_emoji_id"] = icon_id
    return btn


def _bu(text, url):
    """URL button variant."""
    icon_id = _btn_icon_id(text)
    clean = _clean_btn_text(text)
    btn = {"text": clean, "url": url}
    if icon_id:
        btn["icon_custom_emoji_id"] = icon_id
    return btn


# ══════════════════════════════════════════════════════════
# Menus — every label starts with an emoji from BUTTON_CUSTOM_EMOJIS
# ══════════════════════════════════════════════════════════
def rows_main():
    return [
        [_b("🔥  Gates",       "gates")],
        [_b("🔑  Redeem",      "redeem_info"),
         _b("⚙️  Proxy",       "manage_proxy")],
        [_b("👑  Admin Panel", "admin_panel")],
        [_b("❌  Close",       "close")],
    ]


def rows_gates():
    return [
        [_b("💳  Shopify",         "gate_shopify")],
        [_b("🔥  Stripe 1$",       "gate_st1"),
         _b("💎  Stripe 5$",       "gate_st5")],
        [_b("✅  Stripe Auth2 $0", "gate_auth")],
        [_b("⚡  Stripe Auth2 v2",  "gate_auth1")],
        [_b("🤖  Braintree",       "gate_btauth")],
        [_b("🌐  Manage Proxy",    "manage_proxy")],
        [_b("↪️  Back",            "back_start")],
    ]


def rows_proxy(uid):
    return [
        [_b("🛡  Test Proxy", "test_proxy_btn"),
         _b("❌  Remove",     "remove_proxy_btn")],
        [_b("↪️  Back",       "back_start")],
    ]


def rows_stop():
    return [[_b("⚠️  Stop Check", "stop_mass")]]


def rows_admin(uid):
    is_owner = (uid == OWNER_ID)
    rows = [
        [_b("📋  Users", "admin_users"),
         _b("🌐  Sites", "admin_sites")],
        [_b("📡  Proxy Pool", "admin_proxy_pool")],
        [_b("💫  Broadcast",  "admin_broadcast_info")],
        [_b("💻  Backup",     "admin_backup"),
         _b("⭐  Restore",    "admin_restore_info")],
    ]
    if is_owner:
        rows.append([_b("⚙️  API Endpoints", "owner_api_eps")])
        rows.append([_b("🔑  Keys",          "owner_keys"),
                     _b("🛡  GC/Channels",   "owner_gc")])
    rows.append([_b("↪️  Back", "back_start")])
    return rows


def rows_admin_users():
    return [
        [_b("📋  List Users", "admin_list_users")],
        [_b("✅  Add User",   "admin_add_user_info"),
         _b("❌  Remove",     "admin_rm_user_info")],
        [_b("↪️  Back",       "admin_panel")],
    ]


def rows_admin_sites():
    return [
        [_b("📋  List Sites", "admin_list_sites_cb")],
        [_b("✅  Add Site",   "admin_add_site_info"),
         _b("❌  Remove",     "admin_rm_site_info")],
        [_b("↪️  Back",       "admin_panel")],
    ]


def rows_admin_proxy_pool():
    return [
        [_b("📋  List Pool", "admin_list_proxy_cb")],
        [_b("✅  Add",       "admin_add_proxy_info"),
         _b("❌  Clear",     "admin_clear_proxy_cb")],
        [_b("↪️  Back",      "admin_panel")],
    ]


def rows_owner_api_eps():
    return [
        [_b("📋  List",     "owner_api_list")],
        [_b("✅  Add",      "owner_api_add_info"),
         _b("❌  Remove",   "owner_api_rm_info")],
        [_b("↪️  Back",     "admin_panel")],
    ]


def rows_owner_keys():
    return [
        [_b("📋  List Keys",     "owner_key_list")],
        [_b("✅  Generate Keys", "owner_key_gen_info")],
        [_b("↪️  Back",          "admin_panel")],
    ]


def rows_owner_gc():
    return [
        [_b("🛡  Private GC",     "owner_gc_private")],
        [_b("🌐  Public GC",      "owner_gc_public")],
        [_b("📋  Log GC",         "owner_gc_log")],
        [_b("📡  Public Channel", "owner_gc_channel")],
        [_b("🔑  Required Chans", "owner_gc_req")],
        [_b("↪️  Back",           "admin_panel")],
    ]
