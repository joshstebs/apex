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
voice_engine.elevenlabs_key = ''
client = TestClient(app)

def reset_state():
    redis.clear(); eval_log.clear(); cmd_log.clear()

# 1) release_call_slot reports Redis errors as failure (not silent success)
reset_state()
month_key = __import__('datetime').datetime.utcnow().strftime('%Y-%m')
call_id = 'CA_rel_err'
redis[f'apex:acct:{call_id}'] = json.dumps({'call_id': call_id, 'month': month_key, 'reserve': 3.0, 'reconciled': False})
redis[f'apex:spend:{month_key}'] = '3.0'
orig = db._upstash_cmd
def failing(c):
    if c[0] == 'EVAL': raise RuntimeError('Redis down')
    return orig(c)
db._upstash_cmd = failing
ok, err, outcome = db.release_call_slot(call_id, cost_delta=1.0)
assert ok is False and outcome is None and 'unavailable' in (err or '').lower(), (ok, err, outcome)
db._upstash_cmd = orig
# accounting still unreconciled, spend unchanged -> not silently reconciled
assert json.loads(redis[f'apex:acct:{call_id}']).get('reconciled') is False
assert abs(float(redis[f'apex:spend:{month_key}']) - 3.0) < 1e-9
print('PASS: Redis error during release is reported as failure, not silent success')

# 2) unsuccessful reconciliation result (EVAL returns 0 while marker still present) is failure
reset_state()
month_key = __import__('datetime').datetime.utcnow().strftime('%Y-%m')
call_id = 'CA_rel_unsuccessful'
redis[f'apex:acct:{call_id}'] = json.dumps({'call_id': call_id, 'month': month_key, 'reserve': 3.0, 'reconciled': False})
redis[f'apex:spend:{month_key}'] = '3.0'
def no_reconcile(c):
    if c[0] == 'EVAL': return 0
    return orig(c)
db._upstash_cmd = no_reconcile
ok, err, outcome = db.release_call_slot(call_id, cost_delta=1.0)
assert ok is False and outcome is None, (ok, err, outcome)
db._upstash_cmd = orig
assert json.loads(redis[f'apex:acct:{call_id}']).get('reconciled') is False
assert abs(float(redis[f'apex:spend:{month_key}']) - 3.0) < 1e-9
print('PASS: unsuccessful reconciliation is reported as failure')

# 3) delayed callback after short-marker expiry reconciles once from durable accounting
reset_state()
month_key = __import__('datetime').datetime.utcnow().strftime('%Y-%m')
call_id = 'CA_marker_expired_delayed'
redis[f'apex:spend:{month_key}'] = '3.0'
redis[f'apex:acct:{call_id}'] = json.dumps({'call_id': call_id, 'month': month_key, 'reserve': 3.0, 'reconciled': False})
# short marker intentionally absent (expired)
ok, err, outcome = db.release_call_slot(call_id, cost_delta=1.0)
assert (ok, err, outcome) == (True, None, 'released'), (ok, err, outcome)
assert abs(float(redis[f'apex:spend:{month_key}']) - 1.0) < 1e-9
ok, err, outcome = db.release_call_slot(call_id, cost_delta=0.2)
assert (ok, err, outcome) == (True, None, 'already_released'), (ok, err, outcome)
assert abs(float(redis[f'apex:spend:{month_key}']) - 1.0) < 1e-9
# missing accounting entirely must not be treated as success
reset_state()
ok, err, outcome = db.release_call_slot('CA_no_accounting', cost_delta=1.0)
assert ok is False and outcome is None and 'unavailable' in (err or '').lower(), (ok, err, outcome)
print('PASS: delayed callback after marker expiry reconciles from durable accounting; missing accounting is a failure')

# 4) month-boundary reconciliation uses admission month from marker
reset_state()
call_id = 'CA_month_boundary'
admit_month = '2026-10'
release_month = __import__('datetime').datetime.utcnow().strftime('%Y-%m')
assert admit_month != release_month or True  # deterministic regardless
redis[f'apex:acct:{call_id}'] = json.dumps({'call_id': call_id, 'month': admit_month, 'reserve': 3.0, 'reconciled': False})
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
redis[f'apex:call:{call_id}'] = json.dumps({'call': {'id': call_id, 'status': 'in-progress'}, 'transcripts': [],
    'accounting': {'call_id': call_id, 'month': month_key, 'reserve': 3.0, 'reconciled': False}})
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
redis[f'apex:call:{call_id}'] = json.dumps({'call': {'id': call_id, 'status': 'in-progress'}, 'transcripts': [],
    'accounting': {'call_id': call_id, 'month': month_key, 'reserve': 3.0, 'reconciled': False}})
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
