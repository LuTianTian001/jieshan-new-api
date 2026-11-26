"""Linux/cgroup v2, Docker Compose >=2.24.4. Run from this kit on the JieShan host.

Build a fresh offline stack, check the sibling gateway during each load stage, verify
the disposable ledger, then remove only this run's project and private working copy.
Stdout is JSON lines; no keys, prompts, passwords, or customer data are emitted.
"""

import http.client
import json
import os
import secrets
import shutil
import statistics
import subprocess
import sys
import tempfile
import threading
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
SERVICES = ('new-api', 'postgres', 'redis', 'stream-fixture', 'load-client')
MIB = 1024**2


def run(args, **kw):
    return subprocess.check_output(args, text=True, **kw).strip()


def emit(event, **fields):
    print(json.dumps({'event':event, **fields}, separators=(',', ':')), flush=True)


def kv(path):
    return {k: int(v.strip()) for k,v in (row.split(maxsplit=1) for row in path.read_text().splitlines())}


def identity(name):
    return run(['docker','inspect','-f','{{.Id}} {{.State.StartedAt}} {{.RestartCount}} {{.State.Health.Status}}',name])


def cgroup(name):
    pid = run(['docker','inspect','-f','{{.State.Pid}}',name])
    group = Path(f'/proc/{pid}/cgroup').read_text().strip().removeprefix('0::').lstrip('/')
    return Path('/sys/fs/cgroup')/group


def cpu_ticks():
    v = [int(x) for x in Path('/proc/stat').read_text().splitlines()[0].split()[1:9]]
    return sum(v),v[3]+v[4]


def available_mib():
    return int(next(row.split()[1] for row in Path('/proc/meminfo').read_text().splitlines() if row.startswith('MemAvailable:')))//1024


def old_health():
    t = time.monotonic()
    conn = http.client.HTTPConnection('127.0.0.1',4000,timeout=.75)
    try:
        conn.request('GET','/health')
        with conn.getresponse() as r:
            if r.status != 200:
                raise RuntimeError(f'old health HTTP {r.status}')
            r.read(65536)
        return round((time.monotonic()-t)*1000,3)
    finally:
        conn.close()


class Guard(threading.Thread):
    def __init__(self, groups):
        super().__init__(daemon=True)
        self.groups = groups
        self.stop_requested = threading.Event()
        self.reason = None
        self.rows = []

    def run(self):
        ticks = cpu_ticks()
        prev = {k:kv(p/'cpu.stat') for k,p in self.groups.items()}
        start = time.monotonic()
        bad_health = busy = 0
        try:
            while not self.stop_requested.wait(.9):
                now = time.monotonic()
                current = cpu_ticks()
                host_cpu = 100*(1-(current[1]-ticks[1])/max(1,current[0]-ticks[0]))
                ticks = current
                free = available_mib()
                try:
                    health = old_health()
                    bad_health = bad_health + 1 if health > 500 else 0
                except (OSError, http.client.HTTPException, RuntimeError):
                    health = None
                    bad_health += 1
                busy = busy + 1 if host_cpu >= 85 else 0
                row = {'free_mib':free, 'host_cpu':round(host_cpu,1), 'old_health_ms':health}
                for k,p in self.groups.items():
                    cpu = kv(p/'cpu.stat')
                    mem = int((p/'memory.current').read_text())
                    row[k] = {'cores':round((cpu['usage_usec']-prev[k]['usage_usec'])/1e6/(now-start),3),
                              'mib':round(mem/MIB,1),'throttled_periods':cpu.get('nr_throttled',0)-prev[k].get('nr_throttled',0),
                              'periods':cpu.get('nr_periods',0)-prev[k].get('nr_periods',0)}
                    prev[k] = cpu
                    if k != 'old' and kv(p/'memory.events').get('oom_kill',0):
                        self.reason = f'{k}: OOM kill'
                self.rows.append(row)
                start = now
                if free < 3072 or bad_health >= 2 or busy >= 3:
                    self.reason = f'sibling/host guard: available={free} MiB, consecutive slow/failed health={bad_health}, saturated CPU samples={busy}'
                if self.reason:
                    return
        except Exception as e:
            self.reason = f'monitor failed: {type(e).__name__}: {e}'


def summarize(rows, services):
    health = [r['old_health_ms'] for r in rows if r['old_health_ms'] is not None]
    return {'samples':len(rows), 'free_mib_min':min(r['free_mib'] for r in rows),
            'host_cpu_pct_max':max(r['host_cpu'] for r in rows), 'old_health_failures':len(rows)-len(health),
            'old_health_p95_ms':round(statistics.quantiles(health,n=100,method='inclusive')[94],2) if len(health)>1 else health[0] if health else None,
            'old_health_max_ms':max(health, default=None),
            'services':{k:{'cgroup_peak_mib':max(r[k]['mib'] for r in rows), 'cpu_peak_cores':max(r[k]['cores'] for r in rows),
                           'throttled_periods':sum(r[k]['throttled_periods'] for r in rows), 'periods':sum(r[k]['periods'] for r in rows)} for k in services}}


def main():
    if sys.argv[1:] not in ([],['--with-soak']):
        raise SystemExit('usage: python3 verify.py [--with-soak]')
    if sys.platform != 'linux' or available_mib() < 8192 or shutil.disk_usage('/var/tmp').free < 5*1024**3:
        raise SystemExit('requires Linux, >=8 GiB available and >=5 GiB free under /var/tmp')
    old = identity('jieshan')
    if not old.endswith(' healthy') or old_health() > 250:
        raise SystemExit('sibling gateway is not ready')
    os.umask(0o077)
    project = 'js-capacity-' + secrets.token_hex(5)
    tmp = Path(tempfile.mkdtemp(prefix=project+'-',dir='/var/tmp'))
    dc = ['docker','compose','-p',project,'--project-directory',str(tmp),'-f',str(tmp/'compose.yaml'),'-f',str(tmp/'compose.test.yaml')]
    def sql(statement):
        return run(dc+['exec','-T','postgres','psql','-XAt','-F','|','-v','ON_ERROR_STOP=1','-U','jieshan','-d','jieshan_newapi','-c',statement])
    guard = None
    started = False
    try:
        for src in (HERE.parent/'compose.yaml', HERE.parent/'init-env.sh', HERE/'compose.test.yaml', HERE/'sse.py'):
            shutil.copyfile(src,tmp/src.name)
        (tmp/'sse.py').chmod(0o644)  # read-only bind for non-root test helpers
        run(['bash',str(tmp/'init-env.sh')])
        config = json.loads(run(dc+['config','--format','json']))
        assert config['name']==project and set(config['services'])==set(SERVICES)
        assert config['networks']['default']['internal'] and config['networks']['default']['name']==project+'_default'
        assert not any(s.get('ports') or s.get('network_mode') for s in config['services'].values())
        for s in config['services'].values():
            assert set(s['networks'])=={'default'}
            for v in s.get('volumes',[]):
                if v['type']=='bind':
                    assert Path(v['source']).resolve().is_relative_to(tmp)
                else:
                    assert v['type']=='volume' and v['source'] in config['volumes']
        assert all(v['name'].startswith(project+'_') and not v.get('external') for v in config['volumes'].values())
        images = {s['image'] for s in config['services'].values()}
        for image in images:
            run(['docker','image','inspect','-f','{{.Id}}',image])
        emit('start', project=project, available_mib=available_mib(), sibling_health_ms=old_health())
        started = True
        run(dc+['up','-d','--pull','never','--wait','--wait-timeout','120'])
        groups = {k:cgroup(run(dc+['ps','-q',k])) for k in SERVICES}
        groups['old'] = cgroup('jieshan')
        guard = Guard(groups)
        guard.start()
        client = dc+['exec','-T','load-client','python','-B','/work/sse.py']
        key = run(client+['provision'])
        if not key.startswith('sk-') or '\n' in key:
            raise ValueError('failed to obtain disposable key')
        user0 = int(sql("SELECT quota FROM users WHERE username='captest'"))
        key0 = int(sql("SELECT remain_quota FROM tokens WHERE name='capacity-only'"))
        requests = units = 0
        stages = [('run',n) for n in (1,100,300,600,1000)]
        if sys.argv[1:]==['--with-soak']:
            stages.append(('soak',1000))
        for mode,n in stages:
            if guard.reason:
                raise RuntimeError(guard.reason)
            offset = len(guard.rows)
            emit('stage_start', target=n, mode=mode)
            process = subprocess.Popen(client+[mode,str(n)],stdin=subprocess.PIPE,stdout=subprocess.PIPE,stderr=None,text=True)
            process.stdin.write(key+'\n')
            process.stdin.close()
            until = time.monotonic()+(420 if mode=='soak' else 240)
            while process.poll() is None and not guard.reason and time.monotonic()<until:
                time.sleep(.25)
            if guard.reason or process.poll() is None:
                process.terminate()
                process.wait(timeout=10)
                raise RuntimeError(guard.reason or 'stage exceeded its fixed deadline')
            output = process.stdout.read().strip()
            if output:
                result = json.loads(output)
                emit('stage', **result)
            if process.returncode or not output:
                raise RuntimeError(f'stage {n} failed')
            requests += result['expected']
            units += result['expected']*(result['input_tokens_reported']+result['events_per_second']*result['stream_seconds'])
            # Poll for post-stream settlement, validate log identity, amount and both wallet balances.
            query = """SELECT count(*),count(DISTINCT request_id),coalesce(sum(quota),0),
                count(*) FILTER (WHERE is_stream AND prompt_tokens IN (12,8192) AND quota=prompt_tokens+completion_tokens),
                (SELECT quota FROM users WHERE username='captest'),(SELECT remain_quota FROM tokens WHERE name='capacity-only')
                FROM logs WHERE type=2 AND model_name='js-capacity-local' AND token_id=(SELECT id FROM tokens WHERE name='capacity-only')"""
            deadline = time.monotonic()+15
            while time.monotonic()<deadline:
                result_db = tuple(map(int,sql(query).split('|')))
                if result_db==(requests,requests,units,requests,user0-units,key0-units):
                    break
                time.sleep(.5)
            else:
                raise RuntimeError(f'ledger mismatch after {n}: observed {result_db}; expected {(requests,requests,units,requests,user0-units,key0-units)}')
            rows = guard.rows[offset:]
            if not rows or guard.reason:
                raise RuntimeError(guard.reason or 'missing host telemetry')
            emit('stage_checked', target=n, mode=mode, ledger_entries=requests, ledger_units=units, **summarize(rows,SERVICES))
        emit('pass', requests=requests, synthetic_quota=units, **summarize(guard.rows,SERVICES))
    finally:
        if guard:
            guard.stop_requested.set()
            guard.join(timeout=5)
        if started:
            run(dc+['down','--volumes','--timeout','8'])
        assert tmp.parent==Path('/var/tmp') and tmp.name.startswith(project+'-')
        shutil.rmtree(tmp)
        for kind in ('ps','volume','network'):
            args = ['docker','ps','-aq'] if kind=='ps' else ['docker',kind,'ls','-q']
            assert not run(args+['--filter','label=com.docker.compose.project='+project]), 'test resources still present'
        unchanged = identity('jieshan')==old
        emit('cleanup', project_removed=True, sibling_identity_unchanged=unchanged, sibling_health_ms=old_health())
        if not unchanged:
            raise RuntimeError('sibling gateway state changed')


if __name__ == '__main__':
    main()
