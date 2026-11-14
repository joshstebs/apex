"""Focused P0 #1/#2 reliability regressions (offline, deterministic Redis mock)."""
import os, json, urllib.parse

os.environ['VERCEL'] = '1'
os.environ['APEX_ADMIN_TOKEN'] = 'test-only-secret'
# Reserve must be valid for tests that exercise admission paths.
os.environ['APEX_MAX_CALL_RESERVE_USD'] = '3.00'

from fastapi.testclient import TestClient
from app import app, db, settings, telephony, voice_engine

settings.UPSTASH_REDIS_REST_URL = 'https://mock.invalid'
settings.UPSTASH_REDIS_REST_TOKEN = 'test-only'
settings.SIGNALWIRE_SIGNING_KEY = 'test-signature-key'
settings.ENFORCE_WEBHOOK_SIGNATURE = True
settings.RECEPTIONIST_ENABLED = True
settings.ELEVENLABS_API_KEY = 'test-only'
settings.HUGGINGFACE_API_KEY = 'test-only'
settings.PUBLIC_URL = 'https://example.vercel.app'
settings.REQUIRE_MATCHING_INBOUND_NUMBER = True
settings.SIGNALWIRE_PHONE_NUMBER = '+12267732234'

redis = {}
eval_log = []

def cmd(c):
    op = c[0].upper()
    if op == 'GET':
        return redis.get(c[1])
    if op == 'SET':
        if 'NX' in c and c[1] in redis:
            return None
        redis[c[1]] = c[2]
        return 'OK'
    if op == 'DEL':
        return 1 if redis.pop(c[1], None) is not None else 0
    if op == 'EVAL':
        script = c[1]
        eval_log.append(script[:60])
        # Admission: lock + spend + marker + durable accounting + durable state
        if 'local lock = redis.call' in script and 'KEYS[5]' in script:
            lock, spend, marker, acct, state = c[3:8]
            call, lock_ttl, marker_ttl, reserve, budget, acct_json, acct_ttl = c[8:]
            if redis.get(lock) == call:
                if acct in redis or marker in redis:
                    return 2
                return 3
            if lock in redis:
                return 0
            raw_state = redis.get(state)
            if raw_state:
                try:
                    decoded = json.loads(raw_state)
                except Exception:
                    decoded = None
                if isinstance(decoded, dict) and isinstance(decoded.get('call'), dict):
                    if decoded['call'].get('status') == 'in-progress':
                        acct_raw = redis.get(acct)
                        if acct_raw is not None:
                            try:
                                acct_obj = json.loads(acct_raw)
                            except Exception:
                                return 5
                            if not isinstance(acct_obj, dict) or acct_obj.get('reconciled') is True:
                                return 5
                            redis[lock] = call
                            redis[marker] = acct_raw
                            return 4
                        state_acct = decoded.get('accounting')
                        if isinstance(state_acct, dict) and state_acct.get('reconciled') is not True:
                            state_json = json.dumps(state_acct)
                            chosen = state_json
                            if acct not in redis:
                                redis[acct] = state_json
                            else:
                                chosen = redis[acct]
                                try:
                                    racing = json.loads(chosen)
                                except Exception:
                                    return 5
                                if not isinstance(racing, dict) or racing.get('reconciled') is True:
                                    return 5
                            redis[lock] = call
                            redis[marker] = chosen
                            return 4
                        return 5
                    return 5
            if acct in redis:
                return 5
            if float(redis.get(spend, 0)) + float(reserve) > float(budget):
                return 0
            redis[lock] = call
            redis[spend] = str(float(redis.get(spend, 0)) + float(reserve))
            redis[acct] = acct_json
            redis[marker] = acct_json
            return 1
        # Atomic state update
        if "local raw = redis.call('GET', KEYS[1])" in script:
            key, _, updates, transcript, _, _ = c[3:]
            if key not in redis:
                return 0
            state = json.loads(redis[key])
            state['call'].update(json.loads(updates))
            if transcript:
                state['transcripts'].append(json.loads(transcript))
            redis[key] = json.dumps(state)
            return 1
        # Idempotent release / budget reconciliation (durable accounting is authoritative)
        if "local raw = redis.call('GET', KEYS[3])" in script:
            lock, spend, acct, marker = c[3:7]
            call, delta, now, acct_ttl = c[7:]
            raw = redis.get(acct)
            if not raw:
                return 0
            try:
                accounting = json.loads(raw)
            except Exception:
                return 3
            if accounting.get('reconciled') is True:
                return 2
            if redis.get(lock) == call:
                redis.pop(lock, None)
            redis[spend] = str(float(redis.get(spend, 0)) + float(delta))
            accounting['reconciled'] = True
            accounting['reconciled_at'] = now
            redis[acct] = json.dumps(accounting)
            redis.pop(marker, None)
            return 1
        raise AssertionError('Unmocked EVAL: ' + script[:120])
    raise AssertionError('Unmocked Redis operation ' + str(c))

db._upstash_cmd = cmd

# Avoid paid synthesis side effects in focused tests.
voice_engine.elevenlabs_key = ''
client = TestClient(app)


def reset_state():
    redis.clear()
    eval_log.clear()


def signed_voice_post(params, url='https://example.vercel.app/webhooks/signalwire/voice'):
    # Preserve explicit blank fields in the signed body.
    body = urllib.parse.urlencode(params, doseq=True)
    sig = telephony.compute_signalwire_laml_signature(settings.SIGNALWIRE_SIGNING_KEY, url, params)
    headers = {
        'X-Forwarded-Proto': 'https',
        'X-Forwarded-Host': 'example.vercel.app',
        'X-SignalWire-Signature': sig,
        'Content-Type': 'application/x-www-form-urlencoded',
    }
    return client.post('/webhooks/signalwire/voice', content=body, headers=headers)


# 1) Blank SpeechResult/Digits signature handling (voice webhook path)
reset_state()
params_blank = {
    'CallSid': 'CA_blank_sig',
    'From': '+15195550000',
    'To': '+12267732234',
    'SpeechResult': '',
    'Digits': '',
}
r = signed_voice_post(params_blank)
assert r.status_code == 200, r.text
assert '<Gather' in r.text, r.text
assert redis.get('apex:active_call_lock') == 'CA_blank_sig', redis

# Verify verification accepts a body with explicit blank fields included in signature.
url = 'https://example.vercel.app/webhooks/signalwire/voice'
body = urllib.parse.urlencode(params_blank, doseq=True)
parsed = {k: v[0] for k, v in urllib.parse.parse_qs(body).items()}  # drops blanks, mimics route parse
sig = telephony.compute_signalwire_laml_signature(settings.SIGNALWIRE_SIGNING_KEY, url, params_blank)
assert telephony.verify_signalwire_webhook(url, parsed, body, {'X-SignalWire-Signature': sig}), 'blank fields must verify from raw body'
print('PASS: blank SpeechResult/Digits signature handling')


# 2) Same-CallSid retry after durable state exists: no duplicate greeting/reservation
reset_state()
base = {'CallSid': 'CA_retry_1', 'From': '+15195550000', 'To': '+12267732234'}
r1 = signed_voice_post(base)
r2 = signed_voice_post(base)
assert r1.status_code == 200 and r2.status_code == 200
assert '<Gather' in r1.text and '<Gather' in r2.text
state = json.loads(redis.get('apex:call:CA_retry_1') or 'null')
assert state is not None, 'durable state missing'
transcripts = state.get('transcripts', [])
assistant_greetings = [t for t in transcripts if t.get('speaker') == 'assistant']
assert len(assistant_greetings) == 1, transcripts
assert float(redis.get('apex:spend:{}'.format(__import__('datetime').datetime.utcnow().strftime('%Y-%m')), 0)) == 3.0, redis
marker = json.loads(redis.get('apex:reserve:CA_retry_1')); assert marker.get('month') and float(marker.get('reserve',0)) > 0
print('PASS: same-CallSid retry reuses state without duplicate greeting/reservation')


# 3) Same-CallSid retry during lock-before-state race (lock held, state missing)
reset_state()
call_id = 'CA_race_1'
month_key = __import__('datetime').datetime.utcnow().strftime('%Y-%m')
redis['apex:active_call_lock'] = call_id
redis[f'apex:spend:{month_key}'] = '3.0'
redis[f'apex:acct:{call_id}'] = json.dumps({'call_id': call_id, 'month': month_key, 'reserve': 3.0, 'reconciled': False})
redis[f'apex:reserve:{call_id}'] = json.dumps({'call_id': call_id, 'month': month_key, 'reserve': 3.0, 'reconciled': False})
# state intentionally absent
r = signed_voice_post({'CallSid': call_id, 'From': '+15195550000', 'To': '+12267732234'})
assert r.status_code == 200 and '<Gather' in r.text, r.text
state = json.loads(redis.get(f'apex:call:{call_id}') or 'null')
assert state is not None and state.get('call', {}).get('id') == call_id, state
assert float(redis.get(f'apex:spend:{month_key}', 0)) == 3.0, 'reservation must not double-charge on recovery'
marker=json.loads(redis.get(f'apex:reserve:{call_id}')); assert marker.get('month')==month_key and float(marker.get('reserve',0))==3.0, marker
assert json.loads(redis.get(f'apex:acct:{call_id}')).get('reconciled') is False
print('PASS: lock-before-state race recovered without double reservation')


# 4) Same-CallSid retry where lock+state exist but reservation marker missing (expired marker)
reset_state()
call_id = 'CA_marker_expired'
month_key = __import__('datetime').datetime.utcnow().strftime('%Y-%m')
redis['apex:active_call_lock'] = call_id
redis[f'apex:spend:{month_key}'] = '3.0'
redis[f'apex:call:{call_id}'] = json.dumps({
    'call': {'id': call_id, 'assistant_id': 'tpl_hm_receptionist', 'status': 'in-progress',
             'started_at': __import__('datetime').datetime.utcnow().isoformat()},
    'transcripts': [{'speaker': 'assistant', 'message': 'hi', 'latency_ms': 1}],
    'accounting': {'call_id': call_id, 'month': month_key, 'reserve': 3.0, 'reconciled': False},
})
# marker and durable accounting intentionally absent (expired)
r = signed_voice_post({'CallSid': call_id, 'From': '+15195550000', 'To': '+12267732234'})
assert r.status_code == 200 and '<Gather' in r.text, r.text
state = json.loads(redis[f'apex:call:{call_id}'])
assert len(state['transcripts']) == 1, state['transcripts']
assert float(redis.get(f'apex:spend:{month_key}', 0)) == 3.0, 'must not re-reserve when lock/state exist'
marker=json.loads(redis.get(f'apex:reserve:{call_id}')); assert marker.get('month')==month_key and float(marker.get('reserve',0))==3.0, marker
print('PASS: expired reservation marker re-armed without duplicate reservation/transcript')


# 5) Different CallSid rejected while active-call lock is held
reset_state()
r1 = signed_voice_post({'CallSid': 'CA_active', 'From': '+15195550000', 'To': '+12267732234'})
assert '<Gather' in r1.text
r2 = signed_voice_post({'CallSid': 'CA_other', 'From': '+15195550001', 'To': '+12267732234'})
assert r2.status_code == 200
assert '<Hangup' in r2.text and '<Gather' not in r2.text, r2.text
assert redis.get('apex:active_call_lock') == 'CA_active'
assert 'apex:call:CA_other' not in redis
assert 'apex:reserve:CA_other' not in redis
print('PASS: competing CallSid rejected without stealing lock or creating state')


# 6) Accurate, idempotent budget release during duplicate/delayed callbacks
reset_state()
month_key = __import__('datetime').datetime.utcnow().strftime('%Y-%m')
call_id = 'CA_release'
redis['apex:active_call_lock'] = call_id
redis[f'apex:spend:{month_key}'] = '3.0'
redis[f'apex:acct:{call_id}'] = json.dumps({'call_id': call_id, 'month': month_key, 'reserve': 3.0, 'reconciled': False})
ok, err, outcome = db.release_call_slot(call_id, cost_delta=1.2)
assert (ok, err, outcome) == (True, None, 'released'), (ok, err, outcome)
assert abs(float(redis[f'apex:spend:{month_key}']) - 1.2) < 1e-9, redis[f'apex:spend:{month_key}']
assert redis.get('apex:active_call_lock') is None
assert json.loads(redis[f'apex:acct:{call_id}']).get('reconciled') is True
# Duplicate/delayed callback must not refund or charge again (total cost, not incremental).
ok, err, outcome = db.release_call_slot(call_id, cost_delta=0.5)
assert (ok, err, outcome) == (True, None, 'already_released'), (ok, err, outcome)
assert abs(float(redis[f'apex:spend:{month_key}']) - 1.2) < 1e-9, redis[f'apex:spend:{month_key}']
print('PASS: budget release idempotent on duplicate/delayed callbacks (total cost semantics)')


# 7) Release reconciles correctly even if lock already expired (marker still present)
reset_state()
month_key = __import__('datetime').datetime.utcnow().strftime('%Y-%m')
call_id = 'CA_lock_expired'
# lock gone, marker present
redis[f'apex:spend:{month_key}'] = '3.0'
redis[f'apex:acct:{call_id}'] = json.dumps({'call_id': call_id, 'month': month_key, 'reserve': 3.0, 'reconciled': False})
ok, err, outcome = db.release_call_slot(call_id, cost_delta=0.8)
assert (ok, err, outcome) == (True, None, 'released'), (ok, err, outcome)
assert abs(float(redis[f'apex:spend:{month_key}']) - 0.8) < 1e-9, redis[f'apex:spend:{month_key}']
ok, err, outcome = db.release_call_slot(call_id, cost_delta=0.0)
assert (ok, err, outcome) == (True, None, 'already_released'), (ok, err, outcome)
assert abs(float(redis[f'apex:spend:{month_key}']) - 0.8) < 1e-9, redis[f'apex:spend:{month_key}']
print('PASS: release reconciles when lock expired and is idempotent')


# 8) Blank/missing CallSid rejected in Vercel path (no fabricated state)
reset_state()
r = signed_voice_post({'From': '+15195550000', 'To': '+12267732234', 'CallSid': ''})
assert r.status_code == 200
assert '<Hangup' in r.text and '<Gather' not in r.text, r.text
assert redis.get('apex:active_call_lock') is None
assert not any(k.startswith('apex:call:') for k in redis), redis
print('PASS: blank CallSid rejected without fabricated state')

print('ALL P0 RELIABILITY TESTS PASSED')
