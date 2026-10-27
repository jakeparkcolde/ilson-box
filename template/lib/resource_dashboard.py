"""Bounded, read-only observations. No credentials, process arguments or remote calls."""
from copy import deepcopy
from datetime import datetime, timezone
import os
import platform
import re
import subprocess
import threading
import time
import unicodedata


def iso(value):
    return datetime.fromtimestamp(value, timezone.utc).isoformat(timespec='seconds')


def command(args):
    # Fixed OS binaries only; never execute a command supplied by API/configuration.
    result = subprocess.run(args, stdin=subprocess.DEVNULL, stdout=subprocess.PIPE,
                            stderr=subprocess.DEVNULL, timeout=4, check=True,
                            env={'PATH': '/usr/bin:/bin:/usr/sbin:/sbin', 'LC_ALL': 'C'})
    if len(result.stdout) > 1024 * 1024:
        raise ValueError('oversized observation')
    return result.stdout.decode('utf-8')


def cpu(text):
    matches = re.findall(r'CPU usage:.*?([\d.]+)% idle', text)
    if len(matches) < 2:
        raise ValueError('missing interval sample')
    value = 100 - float(matches[-1])
    if not 0 <= value <= 100:
        raise ValueError('invalid percentage')
    return {'percent': round(value, 1)}


def memory(text, total):
    match = re.search(r'page size of (\d+) bytes', text)
    fields = dict(re.findall(r'^([^:\n]+):\s+(\d+)\.', text, re.M))
    required = ['Anonymous pages', 'Pages purgeable', 'Pages wired down', 'Pages occupied by compressor']
    if not match or any(k not in fields for k in required):
        raise ValueError('missing memory fields')
    anonymous, purgeable, wired, compressed = [int(fields[k]) for k in required]
    used = (max(0, anonymous - purgeable) + wired + compressed) * int(match[1])
    total = int(total.strip())
    if not 0 <= used <= total or total <= 0:
        raise ValueError('invalid memory observation')
    return {'used_bytes': used, 'total_bytes': total, 'percent': round(100 * used / total, 1)}


def launchd(text):
    # Split only record delimiters so controls inside labels cannot disappear.
    lines = text.split('\n')
    if not lines or lines[0].split() != ['PID', 'Status', 'Label']:
        raise ValueError('invalid launchd response')
    rows = []
    for line in lines[1:]:
        if not line:
            continue
        # Native launchctl columns use TABs. Preserve the entire raw label,
        # including leading whitespace, for identity and bounds validation.
        parts = line.split('\t', 2)
        if (len(parts) != 3 or not re.fullmatch(r'-|[0-9]+', parts[0])
                or not re.fullmatch(r'-?[0-9]+', parts[1])
                or not 1 <= len(parts[2]) <= 200 or not parts[2].strip()
                or any(unicodedata.category(char) == 'Cc' for char in parts[2])):
            raise ValueError('invalid launchd row')
        if parts[2].startswith(('com.apple.', 'application.')):
            continue
        rows.append({'id': parts[2], 'pid': None if parts[0] == '-' else int(parts[0]),
                     'exit_code': int(parts[1])})
    if len(rows) > 2000:
        raise ValueError('too many launchd rows')
    return sorted(rows, key=lambda row: row['id'])


class Collector:
    def __init__(self, home, *, run=command, system=platform.system, clock=time.time,
                 monotonic=time.monotonic, disk=os.statvfs):
        self.home, self.run, self.system = home, run, system
        self.clock, self.monotonic, self.disk = clock, monotonic, disk
        self.lock = threading.Lock()
        self.previous = {}
        self.cached = None
        self.deadline = 0

    def observe(self, key, factory):
        try:
            value = factory()
            result = {'state': 'empty' if value == [] else 'ok', 'value': value,
                      'observed_at': iso(self.clock())}
            self.previous[key] = result
            return result
        except (OSError, ValueError, subprocess.SubprocessError, UnicodeError):
            old = self.previous.get(key)
            return dict(old, state='stale') if old else {
                'state': 'failure', 'value': None, 'observed_at': None}

    def snapshot(self, sandbox=False):
        with self.lock:
            now = self.monotonic()
            if self.cached is not None and now < self.deadline and self.cached['sandbox'] == sandbox:
                return deepcopy(self.cached)
            unavailable = {'state': 'unavailable', 'value': None, 'observed_at': None}
            result = {'observed_at': iso(self.clock()), 'sandbox': sandbox, 'refresh_seconds': 30,
                      'platform': self.system()}
            if result['platform'] == 'Darwin':
                result['cpu'] = self.observe('cpu', lambda: cpu(self.run(['/usr/bin/top', '-l', '2', '-s', '1', '-n', '0'])))
                result['memory'] = self.observe('memory', lambda: memory(
                    self.run(['/usr/bin/vm_stat']), self.run(['/usr/sbin/sysctl', '-n', 'hw.memsize'])))
                result['launchd'] = unavailable.copy() if sandbox else self.observe(
                    'launchd', lambda: launchd(self.run(['/bin/launchctl', 'list'])))
            else:
                result.update({key: unavailable.copy() for key in ['cpu', 'memory', 'launchd']})
            def disk_value():
                st = self.disk(self.home)
                total, free = st.f_blocks * st.f_frsize, st.f_bavail * st.f_frsize
                if not 0 <= free <= total or total <= 0:
                    raise ValueError('invalid disk observation')
                return {'total_bytes': total, 'free_bytes': free, 'percent': round(100 * (total - free) / total, 1)}
            result['disk'] = self.observe('disk', disk_value)
            self.cached = result
            self.deadline = self.monotonic() + 30
            return deepcopy(result)


def dashboard(box, collector):
    sandbox_marker = box.files.marker('state/sandbox')
    sandbox = sandbox_marker is not False
    data = deepcopy(collector.snapshot(sandbox))
    jobs, notices = box.jobs(sandbox)
    observed = data.pop('launchd')
    actual = {row['id']: row for row in (observed['value'] or [])}
    rows = []
    for job in jobs:
        identifier = 'com.ilson.' + job['id']
        process = actual.pop(identifier, None)
        rows.append({'id': identifier, 'name': job['label'], 'source': 'box',
                     'schedule': job['schedule'], 'registration': job['registration'],
                     'last_success_at': job['last_success_at'],
                     'last_success_state': job['last_success_state'],
                     'process': process})
    for identifier, process in actual.items():
        rows.append({'id': identifier, 'name': identifier, 'source': 'launchd',
                     'schedule': None, 'registration': 'loaded', 'last_success_at': None,
                     'last_success_state': 'unavailable', 'process': process})
    for row in rows:
        proc = row['process']
        row['state'] = ('unavailable' if sandbox else observed['state'] if observed['state'] in
                        ('failure', 'stale', 'unavailable') else 'running' if proc and proc['pid'] else
                        'exit_nonzero' if proc and proc['exit_code'] != 0 else 'idle' if proc else
                        'paused' if row['registration'] == 'paused' else 'not_loaded')
    data['automations'] = {'state': 'failure' if notices else observed['state'],
                           'observed_at': observed['observed_at'], 'items': rows,
                           'notices': notices}
    return data
