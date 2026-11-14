"""Offline tests for Redis-authoritative serverless state; no provider calls."""
import os, time, json, urllib.parse
os.environ['VERCEL']='1'
os.environ['APEX_ADMIN_TOKEN']='test-only-secret'
from fastapi.testclient import TestClient
from app import app, db, settings, telephony
settings.UPSTASH_REDIS_REST_URL='https://mock.invalid'
settings.UPSTASH_REDIS_REST_TOKEN='test-only'
settings.SIGNALWIRE_SIGNING_KEY='test-signature-key'
settings.ENFORCE_WEBHOOK_SIGNATURE=True
settings.CRON_SECRET = 'fixture-scheduler'
settings.RECEPTIONIST_ENABLED=True
# Test-only provider presence flags; no live API calls are made.
settings.ELEVENLABS_API_KEY="test-only"
settings.HUGGINGFACE_API_KEY="test-only"
settings.PUBLIC_URL="https://example.vercel.app"
redis={db.SCHEDULER_KEY: "1"}
def cmd(c):
    op=c[0].upper()
    if op == 'EXISTS':
        return int(c[1] in redis)
    if op=='GET':return redis.get(c[1])
    if op=='SET':
        if 'NX' in c and c[1] in redis:return None
        redis[c[1]]=c[2];return 'OK'
    if op=='EVAL':
        script=c[1]
        if 'local lock = redis.call' in script and 'KEYS[5]' in script:
            lock, spend, marker, acct, state, pause, scheduler = c[3:10]
            call,lock_ttl,marker_ttl,reserve,budget,acct_json,acct_ttl=c[10:]
            if pause in redis:
                return 6
            if lock_ttl == "0" and scheduler not in redis:
                return 7
            if redis.get(lock)==call:
                if acct in redis or marker in redis:return 2
                return 3
            if lock in redis:return 0
            raw_state=redis.get(state)
            if raw_state:
                try: decoded=json.loads(raw_state)
                except Exception: decoded=None
                if isinstance(decoded,dict) and isinstance(decoded.get('call'),dict):
                    if decoded['call'].get('status')=='in-progress':
                        acct_raw=redis.get(acct)
                        if acct_raw is not None:
                            try: acct_obj=json.loads(acct_raw)
                            except Exception: return 5
                            if not isinstance(acct_obj,dict) or acct_obj.get('reconciled') is True: return 5
                            redis[lock]=call;redis[marker]=acct_raw;return 4
                        state_acct=decoded.get('accounting')
                        if isinstance(state_acct,dict) and state_acct.get('reconciled') is not True:
                            state_json=json.dumps(state_acct);chosen=state_json
                            if acct not in redis: redis[acct]=state_json
                            else:
                                chosen=redis[acct]
                                try: racing=json.loads(chosen)
                                except Exception: return 5
                                if not isinstance(racing,dict) or racing.get('reconciled') is True: return 5
                            redis[lock]=call;redis[marker]=chosen;return 4
                        return 5
                    return 5
            if acct in redis:return 5
            if float(redis.get(spend,0))+float(reserve)>float(budget):return 0
            redis[lock]=call;redis[spend]=str(float(redis.get(spend,0))+float(reserve));redis[acct]=acct_json;redis[marker]=acct_json;return 1
        if "local raw = redis.call('GET', KEYS[1])" in script:
            key,updates,transcript=c[3:]
            if key not in redis:return 0
            state=json.loads(redis[key]);state['call'].update(json.loads(updates))
            if transcript:state['transcripts'].append(json.loads(transcript))
            redis[key]=json.dumps(state);return 1
        if "local raw = redis.call('GET', KEYS[3])" in script:
            lock,spend,acct,marker=c[3:7]
            call,delta,now,acct_ttl=c[7:]
            raw=redis.get(acct)
            if not raw:return 0
            try: accounting=json.loads(raw)
            except Exception: return 3
            if accounting.get('reconciled') is True:return 2
            if redis.get(lock)==call:redis.pop(lock,None)
            redis[spend]=str(float(redis.get(spend,0))+float(delta))
            accounting['reconciled']=True;accounting['reconciled_at']=now
            redis[acct]=json.dumps(accounting);redis.pop(marker,None);return 1
    raise AssertionError('Unmocked Redis operation '+str(c))
db._upstash_cmd=cmd
client=TestClient(app)
assert client.get('/api/assistants').status_code==401
assert client.get('/api/assistants',headers={'Authorization':'Bearer test-only-secret'}).status_code==200
assert client.post('/api/assistants',headers={'Authorization':'Bearer test-only-secret'},json={}).status_code==422
assert client.post('/api/calls/dispatch',headers={'Authorization':'Bearer test-only-secret'},json={'assistant_id':'x','phone_number':'x','provider':'signalwire'}).status_code==403
assert client.get('/api/calls',headers={'Authorization':'Bearer test-only-secret'}).status_code==503
assert client.get('/').status_code==200
assert 'cfg_elevenlabs_key' not in client.get('/').text
params={'CallSid':'CA_secure_1','From':'+15195550000','To':'+12267732234'}
body=urllib.parse.urlencode(params)
url='https://example.vercel.app/webhooks/signalwire/voice'
headers={'X-Forwarded-Proto':'https','X-Forwarded-Host':'example.vercel.app','X-SignalWire-Signature':telephony.compute_signalwire_laml_signature(settings.SIGNALWIRE_SIGNING_KEY,url,params),'Content-Type':'application/x-www-form-urlencoded'}
assert client.post('/webhooks/signalwire/voice',content=body).status_code==403
r=client.post('/webhooks/signalwire/voice',content=body,headers=headers)
assert r.status_code==200,r.text
assert '<Gather' in r.text,r.text
assert redis.get('apex:active_call_lock')=='CA_secure_1'
assert db.get_call('CA_secure_1')['id']=='CA_secure_1'
db.add_transcript_message('CA_secure_1','human','hello')
db.update_call('CA_secure_1',{'duration_seconds':12})
assert db.get_call_transcripts('CA_secure_1')[-1]['message']=='hello'
assert db.get_call('CA_secure_1')['duration_seconds']==12
params['CallSid']='CA_secure_2';body=urllib.parse.urlencode(params)
headers['X-SignalWire-Signature']=telephony.compute_signalwire_laml_signature(settings.SIGNALWIRE_SIGNING_KEY,url,params)
r=client.post('/webhooks/signalwire/voice',content=body,headers=headers)
assert '<Hangup' in r.text and '<Gather' not in r.text,r.text
# No local fallback on Redis outage
original=db._upstash_cmd
def outage(c):raise RuntimeError('Redis down')
db._upstash_cmd=outage
params['CallSid']='CA_secure_3';body=urllib.parse.urlencode(params)
headers['X-SignalWire-Signature']=telephony.compute_signalwire_laml_signature(settings.SIGNALWIRE_SIGNING_KEY,url,params)
r=client.post('/webhooks/signalwire/voice',content=body,headers=headers)
assert '<Hangup' in r.text and '<Gather' not in r.text,r.text
print('PASS: auth, browser safety, outbound lock, signed webhooks, Redis canonical state, atomic lock, concurrency rejection, fail-closed outage')
