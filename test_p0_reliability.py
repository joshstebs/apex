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
        # Admission: lock + spend + reservation marker (idempotent per CallSid)
        if 'local lock = redis.call' in script and 'KEYS[3]' in script:
            lock, spend, marker, call, ttl, reserve_ttl, reserve, budget = c[3:]
            if redis.get(lock) == call:
                if marker in redis:
                    return 2
                return 3
            if lock in redis:
                return 0
            if float(redis.get(spend, 0)) + float(reserve) > float(budget):
                return 0
            redis[lock] = call
            redis[spend] = str(float(redis.get(spend, 0)) + float(reserve))
            redis[marker] = '1'
            return 1
        # Atomic state update
        if 'local raw' in script:
            key, updates, transcript = c[3:]
            if key not in redis:
                return 0
            state = json.loads(redis[key])
            state['call'].update(json.loads(updates))
            if transcript:
                state['transcripts'].append(json.loads(transcript))
            redis[key] = json.dumps(state)
            return 1
        # Idempotent release / budget reconciliation
        if "redis.call('GET', KEYS[3])" in script and 'INCRBYFLOAT' in script and 'DEL' in script:
            lock, spend, marker, call, delta = c[3:]
            if redis.get(marker) != '1':
                return 0
            if redis.get(lock) == call:
                del redis[lock]
            redis[spend] = str(float(redis.get(spend, 0)) + float(delta))
            del redis[marker]
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
assert redis.get('apex:reserve:CA_retry_1') == '1'
print('PASS: same-CallSid retry reuses state without duplicate greeting/reservation')


# 3) Same-CallSid retry during lock-before-state race (lock held, state missing)
reset_state()
call_id = 'CA_race_1'
month_key = __import__('datetime').datetime.utcnow().strftime('%Y-%m')
redis['apex:active_call_lock'] = call_id
redis[f'apex:spend:{month_key}'] = '3.0'
redis[f'apex:reserve:{call_id}'] = '1'
# state intentionally absent
r = signed_voice_post({'CallSid': call_id, 'From': '+15195550000', 'To': '+12267732234'})
assert r.status_code == 200 and '<Gather' in r.text, r.text
state = json.loads(redis.get(f'apex:call:{call_id}') or 'null')
assert state is not None and state.get('call', {}).get('id') == call_id, state
assert float(redis.get(f'apex:spend:{month_key}', 0)) == 3.0, 'reservation must not double-charge on recovery'
assert redis.get(f'apex:reserve:{call_id}') == '1'
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
    'transcripts': [{'speaker': 'assistant', 'message': 'hi', 'latency_ms': 1}]
})
# marker intentionally absent
r = signed_voice_post({'CallSid': call_id, 'From': '+15195550000', 'To': '+12267732234'})
assert r.status_code == 200 and '<Gather' in r.text, r.text
state = json.loads(redis[f'apex:call:{call_id}'])
assert len(state['transcripts']) == 1, state['transcripts']
assert float(redis.get(f'apex:spend:{month_key}', 0)) == 3.0, 'must not re-reserve when lock/state exist'
assert redis.get(f'apex:reserve:{call_id}') == '1', 'marker must be re-armed for idempotent reconciliation'
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
redis[f'apex:reserve:{call_id}'] = '1'
db.release_call_slot(call_id, cost_delta=1.2)
assert abs(float(redis[f'apex:spend:{month_key}']) - 1.2) < 1e-9, redis[f'apex:spend:{month_key}']
assert redis.get('apex:active_call_lock') is None
assert f'apex:reserve:{call_id}' not in redis
# Duplicate/delayed callback must not refund or charge again.
db.release_call_slot(call_id, cost_delta=0.5)
assert abs(float(redis[f'apex:spend:{month_key}']) - 1.2) < 1e-9, redis[f'apex:spend:{month_key}']
print('PASS: budget release idempotent on duplicate/delayed callbacks')


# 7) Release reconciles correctly even if lock already expired (marker still present)
reset_state()
month_key = __import__('datetime').datetime.utcnow().strftime('%Y-%m')
call_id = 'CA_lock_expired'
# lock gone, marker present
redis[f'apex:spend:{month_key}'] = '3.0'
redis[f'apex:reserve:{call_id}'] = '1'
db.release_call_slot(call_id, cost_delta=0.8)
assert abs(float(redis[f'apex:spend:{month_key}']) - 0.8) < 1e-9, redis[f'apex:spend:{month_key}']
db.release_call_slot(call_id, cost_delta=0.0)
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
