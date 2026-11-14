"""P0 idempotency/recovery hardening regressions (offline, deterministic Redis fault injection).

No production Redis keys, carrier calls, or external providers are used.
"""
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
settings.CRON_SECRET = 'fixture-scheduler'
settings.RECEPTIONIST_ENABLED = True
settings.ELEVENLABS_API_KEY = 'test-only'
settings.HUGGINGFACE_API_KEY = 'test-only'
settings.PUBLIC_URL = 'https://example.vercel.app'
settings.REQUIRE_MATCHING_INBOUND_NUMBER = True
settings.SIGNALWIRE_PHONE_NUMBER = '+12267732234'

redis = {db.SCHEDULER_KEY: "1"}

def cmd(c):
    op = c[0].upper()
    if op == 'EXISTS':
        return int(c[1] in redis)
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
        if 'local lock = redis.call' in script and 'KEYS[5]' in script:
            lock, spend, marker, acct, state, pause, scheduler = c[3:10]
            call, lock_ttl, marker_ttl, reserve, budget, acct_json, acct_ttl = c[10:]
            if pause in redis:
                return 6
            if lock_ttl == "0" and scheduler not in redis:
                return 7
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
        if "local raw = redis.call('GET', KEYS[1])" in script:
            key, updates, transcript = c[3:]
            if key not in redis:
                return 0
            state = json.loads(redis[key])
            state['call'].update(json.loads(updates))
            if transcript:
                state['transcripts'].append(json.loads(transcript))
            redis[key] = json.dumps(state)
            return 1
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
orig_cmd = cmd


def reset_state():
    redis.clear()
    redis[db.SCHEDULER_KEY] = "1"


def month_key():
    return __import__('datetime').datetime.utcnow().strftime('%Y-%m')


def signed_voice_post(params):
    url = 'https://example.vercel.app/webhooks/signalwire/voice'
    body = urllib.parse.urlencode(params, doseq=True)
    sig = telephony.compute_signalwire_laml_signature(settings.SIGNALWIRE_SIGNING_KEY, url, params)
    headers = {
        'X-Forwarded-Proto': 'https',
        'X-Forwarded-Host': 'example.vercel.app',
        'X-SignalWire-Signature': sig,
        'Content-Type': 'application/x-www-form-urlencoded',
    }
    return client.post('/webhooks/signalwire/voice', content=body, headers=headers)


def complete_and_release(call_id, total_cost):
    db.update_call(call_id, {'status': 'completed'})
    return db.release_call_slot(call_id, cost_delta=total_cost)


# 1) Duplicate inbound webhook after successful call completion
reset_state()
m = month_key()
base = {'CallSid': 'CA_dup_complete', 'From': '+15195550000', 'To': '+12267732234'}
r1 = signed_voice_post(base)
assert r1.status_code == 200 and '<Gather' in r1.text
ok, err, outcome = complete_and_release('CA_dup_complete', 1.0)
assert (ok, err, outcome) == (True, None, 'released'), (ok, err, outcome)
spend_before = float(redis[f'apex:spend:{m}'])
acct_before = redis[f'apex:acct:CA_dup_complete']
r2 = signed_voice_post(base)
assert r2.status_code == 200, r2.text
assert '<Hangup' in r2.text and '<Gather' not in r2.text, r2.text
assert float(redis[f'apex:spend:{m}']) == spend_before, 'duplicate call must not be re-billed'
assert redis.get('apex:active_call_lock') is None
assert redis[f'apex:acct:CA_dup_complete'] == acct_before
print('PASS: duplicate inbound webhook after call completion is refused without new charges')

# 2) Delayed callback after reservation-marker expiry
reset_state()
m = month_key()
call_id = 'CA_delayed'
redis[f'apex:spend:{m}'] = '3.0'
redis[f'apex:acct:{call_id}'] = json.dumps({'call_id': call_id, 'month': m, 'reserve': 3.0, 'reconciled': False})
# short marker intentionally absent (expired)
ok, err, outcome = db.release_call_slot(call_id, cost_delta=1.4)
assert (ok, err, outcome) == (True, None, 'released'), (ok, err, outcome)
assert abs(float(redis[f'apex:spend:{m}']) - 1.4) < 1e-9
ok, err, outcome = db.release_call_slot(call_id, cost_delta=0.2)
assert (ok, err, outcome) == (True, None, 'already_released'), (ok, err, outcome)
assert abs(float(redis[f'apex:spend:{m}']) - 1.4) < 1e-9
assert json.loads(redis[f'apex:acct:{call_id}'])['reconciled'] is True
print('PASS: delayed callback after marker expiry reconciles exactly once from durable accounting')

# 3) Redis unavailable during reconciliation, then restored (and competing call blocked meanwhile)
reset_state()
m = month_key()
call_id = 'CA_redis_restore'
redis['apex:active_call_lock'] = call_id
redis[f'apex:spend:{m}'] = '3.0'
redis[f'apex:acct:{call_id}'] = json.dumps({'call_id': call_id, 'month': m, 'reserve': 3.0, 'reconciled': False})
redis[f'apex:call:{call_id}'] = json.dumps({
    'call': {'id': call_id, 'status': 'in-progress', 'started_at': __import__('datetime').datetime.utcnow().isoformat()},
    'transcripts': [],
    'accounting': {'call_id': call_id, 'month': m, 'reserve': 3.0, 'reconciled': False},
})

def outage(c):
    if c[0] == 'EVAL':
        raise RuntimeError('Redis down')
    return orig_cmd(c)

db._upstash_cmd = outage
ok, err, outcome = db.release_call_slot(call_id, cost_delta=0.9)
assert ok is False and outcome is None and 'unavailable' in (err or '').lower(), (ok, err, outcome)
# recovery information retained: lock + unreconciled accounting intact
assert redis.get('apex:active_call_lock') == call_id
assert json.loads(redis[f'apex:acct:{call_id}'])['reconciled'] is False
assert abs(float(redis[f'apex:spend:{m}']) - 3.0) < 1e-9
# competing call must be rejected while the failed release still owns the lock
r = signed_voice_post({'CallSid': 'CA_competing_during_failure', 'From': '+15195550001', 'To': '+12267732234'})
assert '<Hangup' in r.text and '<Gather' not in r.text, r.text
assert redis.get('apex:active_call_lock') == call_id
assert 'apex:acct:CA_competing_during_failure' not in redis
# restored Redis: retried reconciliation succeeds exactly once
db._upstash_cmd = orig_cmd
ok, err, outcome = db.release_call_slot(call_id, cost_delta=0.9)
assert (ok, err, outcome) == (True, None, 'released'), (ok, err, outcome)
assert abs(float(redis[f'apex:spend:{m}']) - 0.9) < 1e-9
ok, err, outcome = db.release_call_slot(call_id, cost_delta=0.9)
assert (ok, err, outcome) == (True, None, 'already_released'), (ok, err, outcome)
assert abs(float(redis[f'apex:spend:{m}']) - 0.9) < 1e-9
print('PASS: Redis outage defers reconciliation (fail closed) and restored Redis reconciles once')

# 4) Two simultaneous completion callbacks (serialized by Redis)
reset_state()
m = month_key()
call_id = 'CA_two_callbacks'
redis['apex:active_call_lock'] = call_id
redis[f'apex:spend:{m}'] = '3.0'
redis[f'apex:acct:{call_id}'] = json.dumps({'call_id': call_id, 'month': m, 'reserve': 3.0, 'reconciled': False})
first = db.release_call_slot(call_id, cost_delta=1.1)
second = db.release_call_slot(call_id, cost_delta=1.1)
assert first == (True, None, 'released'), first
assert second == (True, None, 'already_released'), second
assert abs(float(redis[f'apex:spend:{m}']) - 1.1) < 1e-9
print('PASS: two simultaneous completion callbacks reconcile once and are idempotent')

# 5) Month rollover with a missing marker
reset_state()
call_id = 'CA_month_roll'
admit_month, current = '2026-10', month_key()
redis[f'apex:acct:{call_id}'] = json.dumps({'call_id': call_id, 'month': admit_month, 'reserve': 3.0, 'reconciled': False})
redis[f'apex:spend:{admit_month}'] = '3.0'
redis[f'apex:spend:{current}'] = '0.0'
ok, err, outcome = db.release_call_slot(call_id, cost_delta=1.2)
assert (ok, err, outcome) == (True, None, 'released'), (ok, err, outcome)
assert abs(float(redis[f'apex:spend:{admit_month}']) - 1.2) < 1e-9
assert abs(float(redis[f'apex:spend:{current}']) - 0.0) < 1e-9
ok, err, outcome = db.release_call_slot(call_id, cost_delta=5.0)
assert (ok, err, outcome) == (True, None, 'already_released'), (ok, err, outcome)
assert abs(float(redis[f'apex:spend:{admit_month}']) - 1.2) < 1e-9
print('PASS: month rollover with missing marker reconciles against admission month')

# 6) Repeated recovery without additional charges
reset_state()
m = month_key()
call_id = 'CA_repeat_recovery'
redis['apex:active_call_lock'] = call_id
redis[f'apex:spend:{m}'] = '3.0'
redis[f'apex:call:{call_id}'] = json.dumps({
    'call': {'id': call_id, 'status': 'in-progress', 'started_at': __import__('datetime').datetime.utcnow().isoformat()},
    'transcripts': [],
    'accounting': {'call_id': call_id, 'month': m, 'reserve': 3.0, 'reconciled': False},
})
record = {'id': call_id, 'phone_number': '+15195550000', 'assistant_id': 'tpl_hm_receptionist'}
for _ in range(3):
    admitted, err, outcome = db.try_acquire_call_slot(record)
    assert (admitted, outcome) == (True, 'replay'), (admitted, err, outcome)
    assert abs(float(redis[f'apex:spend:{m}']) - 3.0) < 1e-9, 'recovery must not add charges'
    assert redis[f'apex:acct:{call_id}']
ok, err, outcome = db.release_call_slot(call_id, cost_delta=0.7)
assert (ok, err, outcome) == (True, None, 'released'), (ok, err, outcome)
assert abs(float(redis[f'apex:spend:{m}']) - 0.7) < 1e-9
print('PASS: repeated recovery adds no charges and reconciles once')


# 7) Reconciled accounting must win over stale in-progress call state
reset_state()
m = month_key()
call_id = 'CA_stale_reconciled'
redis[f'apex:spend:{m}'] = '1.0'
redis[f'apex:acct:{call_id}'] = json.dumps({'call_id': call_id, 'month': m, 'reserve': 3.0, 'reconciled': True})
redis[f'apex:call:{call_id}'] = json.dumps({
    'call': {'id': call_id, 'status': 'in-progress', 'started_at': __import__('datetime').datetime.utcnow().isoformat()},
    'transcripts': [],
    'accounting': {'call_id': call_id, 'month': m, 'reserve': 3.0, 'reconciled': False},
})
acct_before = redis[f'apex:acct:{call_id}']
admitted, err, outcome = db.try_acquire_call_slot({'id': call_id, 'phone_number': '+15195550000', 'assistant_id': 'tpl_hm_receptionist'})
assert (admitted, outcome) == (False, 'duplicate'), (admitted, err, outcome)
assert redis.get('apex:active_call_lock') is None, 'reconciled call must not be reactivated'
assert redis[f'apex:acct:{call_id}'] == acct_before, 'reconciled accounting must not be overwritten'
assert abs(float(redis[f'apex:spend:{m}']) - 1.0) < 1e-9
print('PASS: reconciled accounting with stale in-progress state is not reactivated')

# 8) Duplicate inbound webhook after partial completion failure (released, state update failed)
reset_state()
m = month_key()
call_id = 'CA_partial_complete'
entry = {'CallSid': call_id, 'From': '+15195550000', 'To': '+12267732234'}
r = signed_voice_post(entry)
assert r.status_code == 200 and '<Gather' in r.text
ok, err, outcome = db.release_call_slot(call_id, cost_delta=1.3)
assert (ok, err, outcome) == (True, None, 'released'), (ok, err, outcome)
# simulate failed status update: state still says in-progress
state = json.loads(redis[f'apex:call:{call_id}'])
assert state['call']['status'] == 'in-progress'
acct_before = redis[f'apex:acct:{call_id}']
spend_before = float(redis[f'apex:spend:{m}'])
r2 = signed_voice_post(entry)
assert r2.status_code == 200
assert '<Hangup' in r2.text and '<Gather' not in r2.text, r2.text
assert redis.get('apex:active_call_lock') is None
assert redis[f'apex:acct:{call_id}'] == acct_before
assert abs(float(redis[f'apex:spend:{m}']) - spend_before) < 1e-9
print('PASS: duplicate inbound webhook after partial completion failure is refused safely')

# 9) Deterministic release/admission interleavings (real Redis concurrency not available here)
reset_state()
m = month_key()
call_id_a = 'CA_interleave_a'
redis['apex:active_call_lock'] = call_id_a
redis[f'apex:spend:{m}'] = '3.0'
redis[f'apex:acct:{call_id_a}'] = json.dumps({'call_id': call_id_a, 'month': m, 'reserve': 3.0, 'reconciled': False})
redis[f'apex:call:{call_id_a}'] = json.dumps({
    'call': {'id': call_id_a, 'status': 'in-progress'},
    'transcripts': [],
    'accounting': {'call_id': call_id_a, 'month': m, 'reserve': 3.0, 'reconciled': False},
})
record_a = {'id': call_id_a, 'phone_number': '+15195550000', 'assistant_id': 'tpl_hm_receptionist'}
a1 = db.try_acquire_call_slot(record_a)
assert (a1[0], a1[2]) == (True, 'replay'), a1
assert abs(float(redis[f'apex:spend:{m}']) - 3.0) < 1e-9
a2 = db.release_call_slot(call_id_a, cost_delta=1.0)
assert a2 == (True, None, 'released'), a2
a3 = db.try_acquire_call_slot(record_a)
assert (a3[0], a3[2]) == (False, 'duplicate'), a3
assert abs(float(redis[f'apex:spend:{m}']) - 1.0) < 1e-9

reset_state()
call_id_b = 'CA_interleave_b'
redis['apex:active_call_lock'] = call_id_b
redis[f'apex:spend:{m}'] = '3.0'
redis[f'apex:acct:{call_id_b}'] = json.dumps({'call_id': call_id_b, 'month': m, 'reserve': 3.0, 'reconciled': False})
redis[f'apex:call:{call_id_b}'] = json.dumps({
    'call': {'id': call_id_b, 'status': 'in-progress'},
    'transcripts': [],
    'accounting': {'call_id': call_id_b, 'month': m, 'reserve': 3.0, 'reconciled': False},
})
record_b = {'id': call_id_b, 'phone_number': '+15195550001', 'assistant_id': 'tpl_hm_receptionist'}
b1 = db.release_call_slot(call_id_b, cost_delta=1.0)
assert b1 == (True, None, 'released'), b1
b2 = db.try_acquire_call_slot(record_b)
assert (b2[0], b2[2]) == (False, 'duplicate'), b2
assert abs(float(redis[f'apex:spend:{m}']) - 1.0) < 1e-9
print('PASS: deterministic release/admission interleavings avoid reactivation and double charges')
print('NOTE: true concurrent execution against real Redis is UNVERIFIED (no isolated Redis instance available)')

print('ALL P0 RECOVERY HARDENING TESTS PASSED')
