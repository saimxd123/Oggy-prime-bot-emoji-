"""
config.py — central configuration.
Values come from env vars (Render / .env) with sensible fallbacks.
"""
import os
import json


# ══════════════════════════════════════════════════════════
# Telegram API credentials (required)
# ══════════════════════════════════════════════════════════
API_ID    = int(os.getenv('API_ID', '0'))
API_HASH  = os.getenv('API_HASH', '')
BOT_TOKEN = os.getenv('BOT_TOKEN', '')


# ══════════════════════════════════════════════════════════
# Branding
# ══════════════════════════════════════════════════════════
BOT_BRAND      = os.getenv('BOT_BRAND',      'OGGY PRIME')
BOT_USERNAME   = os.getenv('BOT_USERNAME',   'OGGYsPRIME_BOT')
OWNER_NAME     = os.getenv('OWNER_NAME',     '𝑶𝑮𝑮𝒀 𝑷𝑹𝑶𝑶')
OWNER_USERNAME = os.getenv('OWNER_USERNAME', 'OggyProo')
OWNER_ID       = int(os.getenv('OWNER_ID',   '8919487892'))

DEV_LINE = (
    f'💻 <b>Dev</b>  »  '
    f'<a href="https://t.me/{OWNER_USERNAME}">{OWNER_NAME}</a>'
)


# ══════════════════════════════════════════════════════════
# File paths
# ══════════════════════════════════════════════════════════
PREMIUM_FILE    = 'premium.txt'
SITES_FILE      = 'sites.txt'
PROXY_FILE      = 'proxy.txt'
USER_PROXY_FILE = 'user_proxies.json'
USER_POOL_FILE  = 'user_pool.json'
GC_CONFIG_FILE  = 'gc_config.json'
KEYS_FILE       = 'keys.json'
FEEDBACK_FILE   = 'feedback.json'

# ── check_engine.py needs these three ──
API_ENDPOINTS_FILE   = 'api_endpoints.json'
DEFAULT_API_ENDPOINTS = [
    # Fill in your checker API(s) here, e.g.:
    # 'https://api.your-checker.com/shopify/check',
    # Or leave empty and add them at runtime with /addapi in Telegram.
]

KEY_PREFIX = os.getenv('KEY_PREFIX', 'OGGY')


# ══════════════════════════════════════════════════════════
# Admins — mutable set, persisted to admin.json
# ══════════════════════════════════════════════════════════
_DEFAULT_ADMINS = {OWNER_ID}
_ADMIN_FILE     = 'admin.json'


def _load_admin_ids() -> set:
    try:
        with open(_ADMIN_FILE, 'r') as f:
            data = json.load(f)
        ids = {int(x) for x in data.get('admins', [])}
        ids.add(OWNER_ID)
        return ids
    except Exception:
        return set(_DEFAULT_ADMINS)


def _save_admin_ids(ids: set):
    try:
        with open(_ADMIN_FILE, 'w') as f:
            json.dump({'admins': sorted(int(x) for x in ids)}, f, indent=2)
    except Exception:
        pass


ADMIN_IDS: set = _load_admin_ids()
ADMIN_ID       = OWNER_ID


# ══════════════════════════════════════════════════════════
# Limits & concurrency
# ══════════════════════════════════════════════════════════
LIMITS = {
    'admin':   5000,
    'premium': 1000,
    'user':       0,
}

MASS_WORKERS = int(os.getenv('MASS_WORKERS', '30'))


# ══════════════════════════════════════════════════════════
# Startup validation
# ══════════════════════════════════════════════════════════
if not API_ID or not API_HASH or not BOT_TOKEN:
    raise SystemExit(
        "❌ Missing required env vars:\n"
        "   API_ID, API_HASH, BOT_TOKEN\n"
        "   Set them on Render → Environment (or in .env)."
    )
