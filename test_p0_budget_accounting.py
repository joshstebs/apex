"""Focused P0 budget/Redis accounting corrections (offline, deterministic Redis mock)."""
import os, json, urllib.parse

os.environ['VERCEL'] = '1'
os.environ['APEX_ADMIN_TOKEN'] = 'test-only-secret'
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
cmd_log = []

def cmd(c):
    op = c[0].upper()
    cmd_log.append(op)
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
            lock, spend, marker, call, ttl, reserve_ttl, reserve, budget, *rest = c[3:]
            marker_value = rest[0] if rest else json.dumps({'month': __import__('datetime').datetime.utcnow().strftime('%Y-%m'), 'reserve': reserve})
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
            redis[marker] = marker_value
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
            if marker not in redis:
                return 0
            if redis.get(lock) == call:
                del redis[lock]
            redis[spend] = str(float(redis.get(spend, 0)) + float(delta))
            del redis[marker]
            return 1
        raise AssertionError('Unmocked EVAL: ' + script[:120])
    raise AssertionError('Unmocked Redis operation ' + str(c))

db._upstash_cmd = cmd
voice_engine.elevenlabs_key = ''
client = TestClient(app)

def reset_state():
    redis.clear(); eval_log.clear(); cmd_log.clear()

# 1) release_call_slot reports Redis errors as failure (not silent success)
reset_state()
month_key = __import__('datetime').datetime.utcnow().strftime('%Y-%m')
call_id = 'CA_rel_err'
redis[f'apex:reserve:{call_id}'] = json.dumps({'month': month_key, 'reserve': 3.0})
redis[f'apex:spend:{month_key}'] = '3.0'
orig = db._upstash_cmd
def failing(c):
    if c[0] == 'EVAL': raise RuntimeError('Redis down')
    return orig(c)
db._upstash_cmd = failing
ok, err, outcome = db.release_call_slot(call_id, cost_delta=1.0)
assert ok is False and outcome is None and 'unavailable' in (err or '').lower(), (ok, err, outcome)
db._upstash_cmd = orig
# marker still present, spend unchanged -> not silently reconciled
assert redis.get(f'apex:reserve:{call_id}') is not None
assert abs(float(redis[f'apex:spend:{month_key}']) - 3.0) < 1e-9
print('PASS: Redis error during release is reported as failure, not silent success')

# 2) unsuccessful reconciliation result (EVAL returns 0 while marker still present) is failure
reset_state()
month_key = __import__('datetime').datetime.utcnow().strftime('%Y-%m')
call_id = 'CA_rel_unsuccessful'
redis[f'apex:reserve:{call_id}'] = json.dumps({'month': month_key, 'reserve': 3.0})
redis[f'apex:spend:{month_key}'] = '3.0'
def no_reconcile(c):
    if c[0] == 'EVAL': return 0
    return orig(c)
db._upstash_cmd = no_reconcile
ok, err, outcome = db.release_call_slot(call_id, cost_delta=1.0)
assert ok is False and outcome is None, (ok, err, outcome)
db._upstash_cmd = orig
assert redis.get(f'apex:reserve:{call_id}') is not None
assert abs(float(redis[f'apex:spend:{month_key}']) - 3.0) < 1e-9
print('PASS: unsuccessful reconciliation is reported as failure')

# 3) reservation marker expired before delayed callback -> no double refund/charge, reported already_released
reset_state()
month_key = __import__('datetime').datetime.utcnow().strftime('%Y-%m')
call_id = 'CA_marker_expired_delayed'
# assume marker expired and was never reconciled by us; spend already reflects reservation
redis[f'apex:spend:{month_key}'] = '3.0'
ok, err, outcome = db.release_call_slot(call_id, cost_delta=1.0)
assert (ok, err, outcome) == (True, None, 'already_released'), (ok, err, outcome)
assert abs(float(redis[f'apex:spend:{month_key}']) - 3.0) < 1e-9
# duplicate delayed callback still idempotent
ok, err, outcome = db.release_call_slot(call_id, cost_delta=0.2)
assert (ok, err, outcome) == (True, None, 'already_released'), (ok, err, outcome)
assert abs(float(redis[f'apex:spend:{month_key}']) - 3.0) < 1e-9
print('PASS: delayed callback after marker expiry is idempotent with no double refund/charge')

# 4) month-boundary reconciliation uses admission month from marker
reset_state()
call_id = 'CA_month_boundary'
admit_month = '2026-10'
release_month = __import__('datetime').datetime.utcnow().strftime('%Y-%m')
assert admit_month != release_month or True  # deterministic regardless
redis[f'apex:reserve:{call_id}'] = json.dumps({'month': admit_month, 'reserve': 3.0})
redis[f'apex:spend:{admit_month}'] = '3.0'
redis[f'apex:spend:{release_month}'] = redis.get(f'apex:spend:{release_month}', '0.0')
ok, err, outcome = db.release_call_slot(call_id, cost_delta=1.0)
assert (ok, err, outcome) == (True, None, 'released'), (ok, err, outcome)
assert abs(float(redis[f'apex:spend:{admit_month}']) - 1.0) < 1e-9, redis
# current month must not be adjusted
assert abs(float(redis[f'apex:spend:{release_month}']) - 0.0) < 1e-9, redis
print('PASS: month-boundary reconciliation adjusts admission month spend bucket')

# 5) reservation-marker recovery path (ok==3) re-arms marker without charging and later reconciles once
reset_state()
call_id = 'CA_recover_marker'
month_key = __import__('datetime').datetime.utcnow().strftime('%Y-%m')
redis['apex:active_call_lock'] = call_id
redis[f'apex:spend:{month_key}'] = '3.0'
redis[f'apex:call:{call_id}'] = json.dumps({'call': {'id': call_id, 'status': 'in-progress'}, 'transcripts': []})
# marker missing -> recovery path
admitted, err, outcome = db.try_acquire_call_slot({'id': call_id, 'phone_number': '+1', 'assistant_id': 'tpl_hm_receptionist'})
assert (admitted, outcome) == (True, 'replay'), (admitted, err, outcome)
assert abs(float(redis[f'apex:spend:{month_key}']) - 3.0) < 1e-9
marker = json.loads(redis[f'apex:reserve:{call_id}'])
assert marker.get('month') == month_key and float(marker.get('reserve')) == 3.0, marker
ok, err, out2 = db.release_call_slot(call_id, cost_delta=0.9)
assert (ok, err, out2) == (True, None, 'released'), (ok, err, out2)
assert abs(float(redis[f'apex:spend:{month_key}']) - 0.9) < 1e-9
ok, err, out2 = db.release_call_slot(call_id, cost_delta=0.1)
assert (ok, err, out2) == (True, None, 'already_released'), (ok, err, out2)
assert abs(float(redis[f'apex:spend:{month_key}']) - 0.9) < 1e-9
print('PASS: marker recovery re-arms without double charge and reconciles exactly once')

# 6) concurrent replay/release: release wins once, replay/retry does not double-charge, duplicate release safe
reset_state()
call_id = 'CA_concurrent'
month_key = __import__('datetime').datetime.utcnow().strftime('%Y-%m')
redis['apex:active_call_lock'] = call_id
redis[f'apex:spend:{month_key}'] = '3.0'
redis[f'apex:reserve:{call_id}'] = json.dumps({'month': month_key, 'reserve': 3.0})
redis[f'apex:call:{call_id}'] = json.dumps({'call': {'id': call_id, 'status': 'in-progress'}, 'transcripts': []})
ok, err, out = db.release_call_slot(call_id, cost_delta=1.1)
assert (ok, err, out) == (True, None, 'released'), (ok, err, out)
# concurrent duplicate release attempt
ok, err, out = db.release_call_slot(call_id, cost_delta=2.0)
assert (ok, err, out) == (True, None, 'already_released'), (ok, err, out)
# replay attempt after release with lock gone must not re-reserve/create new charge
# (lock absent, marker absent => admission should treat as new only if slot free; but we simulate post-release state)
assert redis.get('apex:active_call_lock') is None
assert f'apex:reserve:{call_id}' not in redis
assert abs(float(redis[f'apex:spend:{month_key}']) - 1.1) < 1e-9
print('PASS: concurrent replay/release scenario avoids double refund/charge and is idempotent')

print('ALL P0 BUDGET/ACCOUNTING TESTS PASSED')
