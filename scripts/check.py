#!/usr/bin/env python3
"""Cairn status checker. Run by .github/workflows/check.yml every 5 minutes.

- Checks every service in services.json. Any HTTP reply below 500 counts as up (the Backend's health
  address answers 401 without a key, which still proves it is up). 5xx, no reply in 10 s, or a network
  error counts as down.
- data/daily.json: one row per service per day (UTC): runs, failed, worst_ms. Keeps 90 days.
- data/latest.json: the latest result per service, read by the page.
- data/state.json: consecutive failures, the open incident issue, and when data was last committed.
- Alerts: two failures in a row open a GitHub issue "<Service> down" (label: incident); the first good
  check after that closes it. data/incidents.json lists recent incident issues for the page.
- Writes commit=true to $GITHUB_OUTPUT when a service changed state, an issue opened or closed, or
  the last commit was over an hour ago. Otherwise the workflow keeps data in the Actions cache only.
Standard library only. Needs GH_TOKEN and GITHUB_REPOSITORY for issues (skipped when missing).
"""
import json, os, sys, time, datetime, urllib.request, urllib.error, subprocess, ssl

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DATA = os.path.join(ROOT, 'data')
KEEP_DAYS = 90
FAILS_TO_OPEN = 2
COMMIT_EVERY = 3600


def load(name, default):
    try:
        with open(os.path.join(DATA, name)) as f:
            return json.load(f)
    except (OSError, ValueError):
        return default


def save(name, obj):
    os.makedirs(DATA, exist_ok=True)
    with open(os.path.join(DATA, name), 'w') as f:
        json.dump(obj, f, indent=1, sort_keys=True)
        f.write('\n')


def probe(url):
    t0 = time.monotonic()
    req = urllib.request.Request(url, headers={'User-Agent': 'cairn-status-check', 'Cache-Control': 'no-cache'})
    try:
        with urllib.request.urlopen(req, timeout=10, context=ssl.create_default_context()) as r:
            code = r.status
    except urllib.error.HTTPError as e:
        code = e.code
    except Exception:
        return False, None
    ms = int((time.monotonic() - t0) * 1000)
    return code < 500, ms


def gh(*args):
    if not os.environ.get('GH_TOKEN') or not os.environ.get('GITHUB_REPOSITORY'):
        return None
    out = subprocess.run(['gh', *args, '--repo', os.environ['GITHUB_REPOSITORY']], capture_output=True, text=True)
    if out.returncode != 0:
        print('gh failed:', ' '.join(args), out.stderr.strip(), file=sys.stderr)
        return None
    return out.stdout.strip()


def refresh_incidents():
    raw = gh('issue', 'list', '--label', 'incident', '--state', 'all', '--limit', '20',
             '--json', 'number,title,state,createdAt,closedAt,url')
    if raw is None:
        return
    items = json.loads(raw or '[]')
    items.sort(key=lambda i: i['createdAt'], reverse=True)
    save('incidents.json', [{'number': i['number'], 'title': i['title'], 'state': i['state'].lower(),
                            'opened': i['createdAt'], 'closed': i['closedAt'], 'url': i['url']} for i in items])


def main():
    with open(os.path.join(ROOT, 'services.json')) as f:
        services = json.load(f)['services']
    now = datetime.datetime.now(datetime.timezone.utc)
    today = now.date().isoformat()
    daily = load('daily.json', {})
    state = load('state.json', {'services': {}, 'last_commit': 0})
    latest = {'checked_at': now.isoformat(timespec='seconds'), 'services': {}}
    changed = False

    for s in services:
        up, ms = probe(s['url'])
        st = state['services'].setdefault(s['id'], {'up': True, 'fails': 0, 'issue': None})
        if up != st['up']:
            changed = True
        st['up'] = up
        st['fails'] = 0 if up else st['fails'] + 1
        row = daily.setdefault(s['id'], {}).setdefault(today, {'runs': 0, 'failed': 0, 'worst_ms': 0})
        row['runs'] += 1
        if not up:
            row['failed'] += 1
        if ms is not None:
            row['worst_ms'] = max(row['worst_ms'], ms)
        latest['services'][s['id']] = {'name': s['name'], 'up': up, 'ms': ms}
        print(f"{s['name']}: {'up' if up else 'DOWN'} {ms if ms is not None else '-'} ms")

        if not up and st['fails'] >= FAILS_TO_OPEN and not st['issue']:
            url = gh('issue', 'create', '--title', f"{s['name']} down", '--label', 'incident',
                     '--body', f"Automatic check: {s['name']} failed {st['fails']} checks in a row, first at about {now.strftime('%Y-%m-%d %H:%M')} UTC.")
            if url:
                st['issue'] = int(url.rstrip('/').split('/')[-1])
                changed = True
        if up and st['issue']:
            if gh('issue', 'close', str(st['issue']), '--comment', f"Recovered at about {now.strftime('%Y-%m-%d %H:%M')} UTC.") is not None:
                st['issue'] = None
                changed = True

    # keep 90 days; drop services no longer listed
    ids = {s['id'] for s in services}
    if set(state['services']) != ids or set(daily) - ids:
        changed = True  # a service was added or removed
    cutoff = (now.date() - datetime.timedelta(days=KEEP_DAYS - 1)).isoformat()
    daily = {sid: {d: v for d, v in days.items() if d >= cutoff} for sid, days in daily.items() if sid in ids}
    state['services'] = {k: v for k, v in state['services'].items() if k in ids}
    latest['order'] = [s['id'] for s in services]

    commit = changed or (time.time() - state.get('last_commit', 0) >= COMMIT_EVERY)
    if commit:
        state['last_commit'] = int(time.time())
        refresh_incidents()
    save('daily.json', daily)
    save('latest.json', latest)
    save('state.json', state)
    if os.environ.get('GITHUB_OUTPUT'):
        with open(os.environ['GITHUB_OUTPUT'], 'a') as f:
            f.write(f"commit={'true' if commit else 'false'}\n")
    print('commit:', commit)


if __name__ == '__main__':
    main()
