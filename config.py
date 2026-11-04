"""
config.py — central configuration.
All values come from env vars (Render / .env) with sensible fallbacks.
Mutable ADMIN_IDS set is persisted to admin.json so /setadmin survives restarts.
"""
import os
import json


# ══════════════════════════════════════════════════════════
# Telegram API credentials
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
PREMIUM_FILE     = 'premium.txt'          # premium users (one id per line)
SITES_FILE       = 'sites.txt'            # shopify sites (one url per line)
PROXY_FILE       = 'proxy.txt'            # legacy proxy pool
USER_PROXY_FILE  = 'user_proxies.json'    # per-user proxies
USER_POOL_FILE   = 'user_pool.json'       # per-user pool toggle
GC_CONFIG_FILE   = 'gc_config.json'       # gc/channel links
KEYS_FILE        = 'keys.json'            # redeemable keys
FEEDBACK_FILE    = 'feedback.json'        # pending feedback

KEY_PREFIX = os.getenv('KEY_PREFIX', 'OGGY')


# ══════════════════════════════════════════════════════════
# Admins — mutable set, persisted to admin.json
# ══════════════════════════════════════════════════════════
_DEFAULT_ADMINS = {OWNER_ID}
_ADMIN_FILE     = 'admin.json'


def _load_admin_ids() -> set:
    """Load admin set from disk; owner is always guaranteed present."""
    try:
        with open(_ADMIN_FILE, 'r') as f:
            data = json.load(f)
        ids = {int(x) for x in data.get('admins', [])}
        ids.add(OWNER_ID)
        return ids
    except Exception:
        return set(_DEFAULT_ADMINS)


def _save_admin_ids(ids: set):
    """Persist admin set to disk (used by /setadmin)."""
    try:
        with open(_ADMIN_FILE, 'w') as f:
            json.dump({'admins': sorted(int(x) for x in ids)}, f, indent=2)
    except Exception:
        pass


ADMIN_IDS: set = _load_admin_ids()
ADMIN_ID       = OWNER_ID       # alias for legacy code


# ══════════════════════════════════════════════════════════
# Limits & concurrency
# ══════════════════════════════════════════════════════════
LIMITS = {
    'admin':   5000,   # max cards per mass check
    'premium': 1000,
    'user':       0,   # no access
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
