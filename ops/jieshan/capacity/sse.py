"""Bounded SSE capacity fixture for the disposable, internal js-capacity network only."""

import asyncio
import http.client
import json
import math
import secrets
import sys
import time
from collections import Counter

MODEL = 'js-capacity-local'
TEXT = ' capacity'
INPUT_TOKENS = 12
LONG_INPUT_TOKENS = 8192
LONG_INPUT_TEXT = ' intro' * LONG_INPUT_TOKENS   # 48 KiB request; reported usage is a test fixture, not a tokenizer benchmark.
STAGES = {1: 2, 100: 10, 300: 12, 600: 15, 1000: 30}
HZ = 10


def sse(data):
    body = b'data: ' + json.dumps(data, separators=(',', ':')).encode() + b'\n\n'
    return b'%x\r\n' % len(body) + body + b'\r\n'


async def mock():
    active = peak = accepted = finished = 0

    async def handle(reader, writer):
        nonlocal active, peak, accepted, finished
        in_stream = False
        try:
            head = await asyncio.wait_for(reader.readuntil(b'\r\n\r\n'), 5)
            request, *fields = head.split(b'\r\n')
            if request.startswith(b'GET /stats '):
                body = json.dumps(dict(active=active, peak=peak, accepted=accepted, finished=finished)).encode()
                writer.write(b'HTTP/1.1 200 OK\r\nConnection: close\r\nContent-Length: %d\r\n\r\n' % len(body) + body)
                await writer.drain()
                return
            if not request.startswith(b'POST /v1/chat/completions '):
                raise ValueError('path')
            headers = dict(f.lower().split(b':', 1) for f in fields if b':' in f)
            length = int(headers.get(b'content-length', 0))
            if not 0 < length <= 65536:
                raise ValueError('body length')
            req = json.loads(await reader.readexactly(length))
            tag = req['messages'][0]['content'].splitlines()[0]
            kind, stage = tag.split(':',1)
            stage = int(stage)
            soak = kind=='soak'
            if (stage not in STAGES or kind not in ('soak','fixture') or (soak and stage!=1000)
                    or req['model'] != MODEL or req['stream'] is not True or active >= 1000):
                raise ValueError('unsupported fixture input')
            active += 1
            accepted += 1
            peak = max(peak, active)
            in_stream = True
            count = HZ * (300 if soak else STAGES[stage])
            inputs = LONG_INPUT_TOKENS if soak else INPUT_TOKENS
            base = {'id': f'chatcmpl-cap-{accepted}', 'object': 'chat.completion.chunk', 'created': int(time.time()), 'model': MODEL}
            def chunk(delta, reason=None):
                return sse({**base, 'choices': [{'index': 0, 'delta': delta, 'finish_reason': reason}]})
            data = chunk({'content': TEXT})
            writer.write(b'HTTP/1.1 200 OK\r\nContent-Type: text/event-stream\r\nConnection: close\r\nTransfer-Encoding: chunked\r\n\r\n' + chunk({'role': 'assistant'}))
            for _ in range(count):
                writer.write(data)
                await writer.drain()
                await asyncio.sleep(1 / HZ)
            usage = {'prompt_tokens': inputs, 'completion_tokens': count, 'total_tokens': inputs + count}
            writer.write(chunk({}, 'stop') + sse({**base, 'choices': [], 'usage': usage}) + b'e\r\ndata: [DONE]\n\n\r\n0\r\n\r\n')
            await writer.drain()
            finished += 1
        except (ValueError, IndexError, KeyError, asyncio.IncompleteReadError, TimeoutError, ConnectionError):
            if not in_stream:
                writer.write(b'HTTP/1.1 400 Bad Request\r\nContent-Length: 0\r\nConnection: close\r\n\r\n')
        finally:
            if in_stream:
                active -= 1
            writer.close()

    server = await asyncio.start_server(handle, '0.0.0.0', 8080, backlog=4096)
    async with server:
        await server.serve_forever()


def api(path, data=None, *, token=None, method=None):
    conn = http.client.HTTPConnection('new-api', 3000, timeout=15)
    headers = {'Content-Type': 'application/json'}
    if token:
        headers['Authorization'] = 'Bearer ' + token
    try:
        conn.request(method or ('POST' if data is not None else 'GET'), path,
                     json.dumps(data).encode() if data is not None else None, headers)
        resp = conn.getresponse()
        body = json.load(resp)
        if resp.status != 200 or not body.get('success'):
            raise ValueError(f'{path} HTTP {resp.status}: {body.get("message", "failed")}')
        return body.get('data')
    finally:
        conn.close()


def provision():
    # Refuse an already initialized installation. No live credentials are used.
    if api('/api/setup')['status']:
        raise ValueError('requires a fresh disposable instance')
    pwd = 'Aa1!' + secrets.token_urlsafe(24)
    api('/api/setup', {'username':'captest', 'password':pwd, 'confirmPassword':pwd})
    token = api('/api/user/login', {'username':'captest', 'password':pwd})['access_token']
    snapshot = api('/api/option/model_pricing?model=' + MODEL, token=token)
    api('/api/option/model_pricing', {'changes':[{'model_name':MODEL, 'expected_version':snapshot['empty_version'],
        'pricing':{'ModelRatio':1, 'CompletionRatio':1}}]}, token=token, method='PATCH')
    api('/api/channel/', {'mode':'single', 'channel':{'type':1, 'name':'internal-sse', 'key':'local-only',
        'base_url':'http://stream-fixture:8080', 'models':MODEL, 'group':'default', 'priority':1, 'weight':1, 'status':1}}, token=token)
    api('/api/token/', {'name':'capacity-only', 'group':'default', 'remain_quota':20000000,
        'expired_time':int(time.time())+3600, 'model_limits_enabled':True, 'model_limits':MODEL}, token=token)
    items = api('/api/token/?p=1&page_size=10', token=token)['items']
    tid = next(row['id'] for row in items if row['name']=='capacity-only')
    key = api(f'/api/token/{tid}/key', {}, token=token)['key']
    for _ in range(65):
        nodes = api('/api/system-info/sync', token=token)['nodes']
        if any(n['node_name']=='js-capacity-test' and n['online'] and all(n['topics'].get(t, {}).get('synced') for t in ('options','channels')) for n in nodes):
            return key if key.startswith('sk-') else 'sk-' + key
        time.sleep(1)
    raise ValueError('disposable node did not synchronize')


def stats():
    conn = http.client.HTTPConnection('stream-fixture', 8080, timeout=3)
    try:
        conn.request('GET', '/stats')
        return json.load(conn.getresponse())
    finally:
        conn.close()


async def stage_run(stage, key, ramp, rounds, soak=False):
    # Observe the number of clients actually receiving content at the same time.
    active = peak = 0
    at_target = 0.0
    target_since = None
    firsts, totals = [], []
    errors = Counter()
    seconds = 300 if soak else STAGES[stage]
    count = HZ * seconds
    inputs = LONG_INPUT_TOKENS if soak else INPUT_TOKENS
    before = stats()
    prompt = f'soak:{stage}\n'+LONG_INPUT_TEXT if soak else f'fixture:{stage}'
    req = json.dumps({'model':MODEL, 'messages':[{'role':'user', 'content':prompt}], 'stream':True,
        'stream_options':{'include_usage':True}, 'max_tokens':count + 16}).encode()
    frame = (b'POST /v1/chat/completions HTTP/1.1\r\nHost: new-api:3000\r\nConnection: close\r\n'
             b'Content-Type: application/json\r\nAuthorization: Bearer ' + key.encode() + b'\r\nContent-Length: %d\r\n\r\n' % len(req) + req)

    async def slot(index):
        nonlocal active, peak, at_target, target_since
        await asyncio.sleep(index * ramp / stage)
        for _ in range(rounds):
            writer = None
            first = None
            t0 = time.monotonic()
            fragments = 0
            done = stop = valid_usage = False
            try:
                async with asyncio.timeout(2 * seconds + 20):
                    reader, writer = await asyncio.open_connection('new-api', 3000)
                    writer.write(frame)
                    await writer.drain()
                    header = (await reader.readuntil(b'\r\n\r\n')).lower()
                    code = int(header.split(b' ', 2)[1])
                    if code != 200:
                        raise ValueError(f'HTTP {code}')
                    if b'text/event-stream' not in header or b'transfer-encoding: chunked' not in header:
                        raise ValueError('not chunked SSE')
                    pending = b''
                    while True:
                        line = await reader.readline()
                        n = int(line.split(b';', 1)[0].strip(), 16)
                        if n == 0:
                            break
                        pending += await reader.readexactly(n)
                        if await reader.readexactly(2) != b'\r\n':
                            raise ValueError('invalid chunk')
                        while b'\n' in pending:
                            line, pending = pending.split(b'\n', 1)
                            if not line.startswith(b'data:'):
                                continue
                            payload = line[5:].strip()
                            if payload == b'[DONE]':
                                done = True
                                continue
                            item = json.loads(payload)
                            choices = item.get('choices') or []
                            if choices:
                                text = choices[0].get('delta', {}).get('content')
                                if text:
                                    if text != TEXT:
                                        raise ValueError('unexpected content')
                                    fragments += 1
                                    if first is None:
                                        first = time.monotonic()
                                        active += 1
                                        peak = max(peak, active)
                                        if active == stage:
                                            target_since = first
                                stop |= choices[0].get('finish_reason') == 'stop'
                            usage = item.get('usage') or {}
                            valid_usage |= (usage.get('prompt_tokens'),usage.get('completion_tokens'),usage.get('total_tokens')) == (inputs,count,inputs+count)
                    if fragments != count or not (done and stop and valid_usage):
                        raise ValueError(f'incomplete SSE ({fragments}/{count}, done={done}, stop={stop}, usage={valid_usage})')
                    finished = time.monotonic()
                    firsts.append((first-t0)*1000)
                    totals.append(finished-t0)
            except Exception as exc:
                errors[str(exc)[:130] or type(exc).__name__] += 1
            finally:
                if first is not None:
                    if active == stage and target_since is not None:
                        at_target += time.monotonic() - target_since
                        target_since = None
                    active -= 1
                if writer:
                    writer.close()

    await asyncio.gather(*(slot(i) for i in range(stage)))
    after = stats()
    def percentile(values, fraction):
        return round(sorted(values)[math.ceil(len(values)*fraction)-1], 2) if values else None
    result = dict(target=stage, profile='soak' if soak else 'short', rounds=rounds, stream_seconds=seconds,
                  request_body_bytes=len(req), input_tokens_reported=inputs, events_per_second=HZ, ramp_seconds=ramp,
                  expected=stage*rounds, ok=len(firsts), errors=dict(errors), peak_receiving=peak,
                  seconds_at_target=round(at_target,2), upstream_peak=after['peak'],
                  upstream_accepted=after['accepted']-before['accepted'], upstream_completed=after['finished']-before['finished'],
                  first_content_p95_ms=percentile(firsts,.95), first_content_p99_ms=percentile(firsts,.99), total_p95_seconds=percentile(totals,.95))
    print(json.dumps(result), flush=True)
    if (errors or peak != stage or after['peak'] != stage or at_target < seconds*(.85 if soak else .4)
            or after['finished']-before['finished'] != stage*rounds or result['first_content_p95_ms'] > 1000):
        raise SystemExit(1)


if __name__ == '__main__':
    if sys.argv[1:] == ['mock']:
        asyncio.run(mock())
    elif sys.argv[1:] == ['provision']:
        # The controller captures stdout via a pipe; never log this disposable credential.
        print(provision())
    elif len(sys.argv)==3 and sys.argv[1]=='soak' and sys.argv[2]=='1000':
        asyncio.run(stage_run(1000, sys.stdin.readline().strip(), 10, 1, soak=True))
    elif len(sys.argv)==3 and sys.argv[1]=='run' and int(sys.argv[2]) in STAGES:
        target = int(sys.argv[2])
        asyncio.run(stage_run(target, sys.stdin.readline().strip(), 0 if target==1 else min(6,target/100), 3 if target==1000 else 1))
    else:
        raise SystemExit('unsupported fixture mode')
