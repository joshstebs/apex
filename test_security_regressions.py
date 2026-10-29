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
settings.RECEPTIONIST_ENABLED=True
# Test-only provider presence flags; no live API calls are made.
settings.ELEVENLABS_API_KEY="test-only"
settings.HUGGINGFACE_API_KEY="test-only"
settings.PUBLIC_URL="https://example.vercel.app"
redis={}
def cmd(c):
    op=c[0].upper()
    if op=='GET':return redis.get(c[1])
    if op=='SET':
        if 'NX' in c and c[1] in redis:return None
        redis[c[1]]=c[2];return 'OK'
    if op=='EVAL':
        script=c[1]
        if 'local spent' in script:
            lock,spend,call,ttl,reserve,budget=c[3:]
            if lock in redis or float(redis.get(spend,0))+float(reserve)>float(budget):return 0
            redis[lock]=call;redis[spend]=str(float(redis.get(spend,0))+float(reserve));return 1
        if 'local raw' in script:
            key,updates,transcript=c[3:]
            if key not in redis:return 0
            state=json.loads(redis[key]);state['call'].update(json.loads(updates))
            if transcript:state['transcripts'].append(json.loads(transcript))
            redis[key]=json.dumps(state);return 1
        if "redis.call('DEL'" in script:
            lock,spend,call,delta=c[3:]
            if redis.get(lock)!=call:return 0
            del redis[lock];redis[spend]=str(float(redis.get(spend,0))+float(delta));return 1
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
