"""Isolated production audio cache regression checks; no external API traffic."""
import os, base64
os.environ['VERCEL']='1'
os.environ['APEX_ADMIN_TOKEN']='test-only'
from fastapi.testclient import TestClient
from app import app, db, voice_engine, settings
settings.UPSTASH_REDIS_REST_URL='https://mock.invalid'
settings.UPSTASH_REDIS_REST_TOKEN='test'
store={}
def redis(cmd):
    op=cmd[0]
    if op=='GET':return store.get(cmd[1])
    if op=='SET':
        if 'NX' in cmd and cmd[1] in store:return None
        store[cmd[1]]=cmd[2];return 'OK'
    if op=='DEL':return 1 if store.pop(cmd[1],None) is not None else 0
    raise AssertionError(cmd)
db._upstash_cmd=redis
clip={'text':'Hello there','voice_id':'test-voice'}
db.get_tts_clip=lambda _id: clip
calls=[]
def synth(text,voice_id):
    calls.append((text,voice_id))
    return b'ID3-mp3-test'
voice_engine.synthesize_speech_elevenlabs=synth
client=TestClient(app)
url='/api/tts/clip/clip_1234567890abcdef.mp3'
a=client.get(url);b=client.get(url)
assert a.status_code==200 and b.status_code==200,(a.text,b.text)
assert a.content==b.content==b'ID3-mp3-test'
assert len(calls)==1,calls
assert client.get('/api/cost/calculate').status_code==401
assert client.get('/api/cost/calculate',headers={'Authorization':'Bearer test-only'},params={'calls_count':-1}).status_code==422
print('PASS: same audio on retry, one synthesis, cost endpoint auth and validation')
