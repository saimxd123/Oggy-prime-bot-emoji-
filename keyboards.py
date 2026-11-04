"""
keywords.py — centralised keyword classification for check results.

Import from anywhere:
    from keywords import (
        is_3ds, is_insufficient, is_proxy_error, is_declined,
        is_approved, is_charged, is_cvv_mismatch, is_avs_mismatch,
        classify,
    )

classify(msg) returns one of:
    'charged' | 'approved' | '3ds' | 'insufficient' | 'cvv' |
    'avs' | 'declined' | 'proxy_error' | 'error' | 'unknown'
"""
from __future__ import annotations


THREEDS_KEYWORDS = (
    '3d secure', '3dsecure', '3ds',
    'authentication required', 'authentication_required',
    'otp required', 'otp_required',
    'requires_action', 'redirect_to_url',
    'sca required', 'challenge_required',
)

INSUFFICIENT_KEYWORDS = (
    'insufficient_funds', 'insufficient funds', 'insufficient',
    'not_enough_funds', 'not enough funds', 'balance_too_low',
)

CVV_KEYWORDS = (
    'incorrect_cvc', 'incorrect cvc',
    'invalid_cvc', 'invalid cvc',
    'security code is incorrect',
    'cvc_check_failed',
    'cvv mismatch', 'cvv_mismatch', 'cvc mismatch',
)

AVS_KEYWORDS = (
    'avs mismatch', 'avs_mismatch',
    'incorrect_zip', 'incorrect zip',
    'address mismatch', 'address_mismatch',
    'postal_code_failed', 'zip_failed',
)

PROXY_ERROR_KEYWORDS = (
    'clienthttpproxyerror', 'proxyerror',
    'proxy error', 'proxy_error',
    'proxy timeout', 'proxy_timeout',
    'proxy fail', 'proxy_fail',
    'connectionpool', 'httpsconnectionpool', 'httpconnectionpool',
    'net:', 'network error', 'network_error',
    'connection refused', 'connection reset', 'connection aborted',
    'timed out', 'timeout',
)

CHARGED_KEYWORDS = (
    'charged', 'payment successful', 'payment_successful',
    'thank you for your donation', 'donation successful',
    'successfully charged',
)

APPROVED_KEYWORDS = (
    'approved',
    'payment method added', 'payment_method_added',
    'setup_intent succeeded', 'setup_intent_succeeded',
    '"success":true', '"status":"succeeded"',
)

DECLINED_KEYWORDS = (
    'declined', 'card_declined', 'generic_decline',
    'do_not_honor', 'do not honor',
    'fraudulent', 'lost_card', 'stolen_card',
    'pickup_card', 'restricted_card',
    'expired_card', 'expired',
    'transaction_not_allowed',
    'card number is incorrect', 'your card could not be',
)


def _match(msg: str, keywords: tuple) -> bool:
    if not msg:
        return False
    m = msg.lower()
    return any(k in m for k in keywords)


def is_3ds(msg: str) -> bool:          return _match(msg, THREEDS_KEYWORDS)
def is_insufficient(msg: str) -> bool: return _match(msg, INSUFFICIENT_KEYWORDS)
def is_proxy_error(msg: str) -> bool:  return _match(msg, PROXY_ERROR_KEYWORDS)
def is_cvv_mismatch(msg: str) -> bool: return _match(msg, CVV_KEYWORDS)
def is_avs_mismatch(msg: str) -> bool: return _match(msg, AVS_KEYWORDS)
def is_charged(msg: str) -> bool:      return _match(msg, CHARGED_KEYWORDS)
def is_approved(msg: str) -> bool:     return _match(msg, APPROVED_KEYWORDS)
def is_declined(msg: str) -> bool:     return _match(msg, DECLINED_KEYWORDS)


def is_error(msg: str) -> bool:
    if not msg:
        return False
    m = msg.lower()
    return (
        m.startswith('error')
        or 'exception' in m
        or 'tokenize:' in m
        or 'charge:' in m
        or 'confirm:' in m
        or 'pm:' in m
        or 'reg:' in m
    )


def classify(msg: str) -> str:
    """
    Return one of:
        'charged' | 'approved' | '3ds' | 'insufficient' |
        'cvv' | 'avs' | 'declined' | 'proxy_error' | 'error' | 'unknown'
    Most specific wins.
    """
    if not msg:
        return 'unknown'
    if is_proxy_error(msg):  return 'proxy_error'
    if is_charged(msg):      return 'charged'
    if is_3ds(msg):          return '3ds'
    if is_cvv_mismatch(msg): return 'cvv'
    if is_avs_mismatch(msg): return 'avs'
    if is_insufficient(msg): return 'insufficient'
    if is_approved(msg):     return 'approved'
    if is_declined(msg):     return 'declined'
    if is_error(msg):        return 'error'
    return 'unknown'


if __name__ == '__main__':
    tests = {
        'INSUFFICIENT_FUNDS':          'insufficient',
        'incorrect_cvc':               'cvv',
        'requires_action':             '3ds',
        'payment method added':        'approved',
        'card_declined':               'declined',
        'ClientHttpProxyError':        'proxy_error',
        'Thank you for your donation': 'charged',
        'ZIP mismatch':                'avs',
        'unknown garbage':             'unknown',
    }
    for inp, exp in tests.items():
        got = classify(inp)
        print(f"{'✅' if got == exp else '❌'}  {inp!r:40} → {got}  (expected {exp})")
