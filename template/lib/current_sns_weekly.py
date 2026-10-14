"""주간 조회 전용 대조. 일정 코드는 실행하지 않고 선언된 값만 읽는다.

정확한 업무 연결이 없는 슬롯은 목표 편수가 아니다. 그런 행은 빈 정상 대신
확인 불가로 남긴다. 생성 tick 시각은 발행 시각으로 사용하지 않는다.
"""
from __future__ import annotations

import ast
from collections import defaultdict
from datetime import date, datetime, timedelta
import json

import current_sns_common as ops

GRACE = ops.OVERDUE_GRACE
STATES = {'rejected': '− 직접 반려', 'done': '✓ 완료', 'scheduled': '◷ 예약', 'attention': '! 확인 필요',
          'failed': '× 실패', 'none': '— 예정 없음', 'unknown': '? 확인 불가'}
DAILY = {'new': '신규 레포', 'hero': '오늘의 한 끼', 'random': '랜덤 식단',
         'free': '자유 주제', 'feature': '기능 소개'}


def monday(value=None, *, now):
    day = date.fromisoformat(value) if value else now.astimezone(ops.KST).date()
    return day - timedelta(days=day.weekday())


def kind(rec):
    src = rec.get('job_source', '')
    if src.startswith('gitbap-daily-'):
        return '일반 글 · ' + DAILY.get(src.removeprefix('gitbap-daily-'), '기타')
    for prefix, label in [('banzzak-insta-', '카드뉴스'), ('banzzak-daily-', '일반 글')]:
        if src.startswith(prefix):
            return label + ' · ' + src[len(prefix):]
    if src.startswith('gitbap-top-repo-'):
        return '인기 레포 카드뉴스'
    if 'webtoon' in src:
        return '웹툰'
    if rec.get('video') or 'shorts' in src:
        return '영상'
    if rec.get('images'):
        return '카드뉴스'
    return '일반 글'


def family(src):
    for prefix in ('gitbap-top-repo-', 'gitbap-insta-', 'gitbap-webtoon-ep'):
        if src.startswith(prefix):
            return prefix.rstrip('-')
    return src or 'unmapped'


def _values(path):
    """모듈 import는 운영 상태·환경을 읽을 수 있다. 제한된 AST만 해석한다."""
    tree = ast.parse(path.read_text())
    def literal(node):
        if isinstance(node, ast.Name) and node.id in values:
            return values[node.id]
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Name) and node.func.id == 'date':
            return date(*(ast.literal_eval(a) for a in node.args)).isoformat()
        if isinstance(node, ast.Dict):
            return {literal(k): literal(v) for k, v in zip(node.keys, node.values)}
        return ast.literal_eval(node)
    values = {}
    for node in tree.body:
        target = node.targets[0] if isinstance(node, ast.Assign) else node.target if isinstance(node, ast.AnnAssign) else None
        if isinstance(target, ast.Name):
            try:
                values[target.id] = literal(node.value)
            except (ValueError, TypeError):
                pass
    return values, tree


def definitions(root, *, now, week=None):
    """현재 코드·중지 상태로 확인 가능한 일정만 반환한다."""
    plans, notes = [], []
    base = root / 'orchestrator'
    try:
        policy = json.loads((base/'config/publish_policy.json').read_text())
        paused_path = base/'state/paused_jobs.json'
        paused = json.loads(paused_path.read_text())['paused'] if paused_path.exists() else {}
        if not isinstance(paused, dict):
            raise ValueError('停止一覧形式')
        registry = ast.parse((base/'schedules.py').read_text())
        jobs = {}
        for node in ast.walk(registry):
            if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute) and node.func.attr == 'Schedule':
                kw = {k.arg: k.value for k in node.keywords}
                try:
                    name = ast.literal_eval(kw['name'])
                    jobs[name] = bool(ast.literal_eval(kw['retired'])) if 'retired' in kw else False
                except (ValueError, KeyError):
                    continue
        def add(job, pf, task, label, **spec):
            if job not in jobs:
                raise ValueError('업무 연결 미확인')
            account = policy['accounts']['gitbap'][pf]
            stop = paused.get(job)
            stop_at = ops.iso(stop.get('paused_at')) if isinstance(stop, dict) else ''
            plans.append(dict(brand='깃밥', platform=pf, account=account, task=task, label=label,
                              retired=jobs[job], paused_at=stop_at,
                              pause_unknown=stop is not None and not stop_at, **spec))
        calendar, _ = _values(base/'gitbap_webtoon.py')
        for pf, hour in calendar['PUBLISH_HOUR'].items():
            add('gitbap-webtoon', pf, 'gitbap-webtoon-ep', '웹툰',
                dates={d: [f'{hour:02}:00'] for d in calendar['CALENDAR']}, known=True)
        short, tree = _values(base/'gitbap_shorts/__init__.py')
        # 실제 승인 예약 경로의 now.replace(hour=...)에서 읽는다. 제작 cron 아님.
        fn = next(n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name == 'queue_internal')
        hours = [k.value for n in ast.walk(fn) if isinstance(n, ast.Call)
                 and isinstance(n.func, ast.Attribute) and n.func.attr == 'replace'
                 for k in n.keywords if k.arg == 'hour']
        hour = next(h for h in hours if isinstance(h, ast.IfExp))
        if ast.dump(hour.test) != ast.dump(ast.parse("channel == 'threads'", mode='eval').body):
            raise ValueError('영상 발행 시각 규칙 변경')
        for pf, value in [('threads', hour.body), ('instagram', hour.orelse)]:
            add('gitbap-shorts-prepare', pf, 'gitbap-shorts-mwf', '영상',
                weekdays=list(short['WEEKDAYS']), start=short['START'],
                times=[f'{ast.literal_eval(value):02}:00'], known=True)
            plan = plans[-1]
            # 전날·당일 제작 경로 둘 중 하나가 멈춰도 기존 예약은 살아 있다.
            # 재개 이력 없이 이를 휴무로 단정하지 않는다.
            if any(job in paused for job in ('gitbap-shorts-prepare', 'gitbap-shorts-prepare-eve')):
                plan['pause_unknown'] = True
            plan['overrides'] = {}
            for i in range(7):
                day = (monday(week, now=now)+timedelta(days=i)).isoformat()
                path = base/'state/gitbap_shorts/episodes'/day/'dispatch.json'
                if path.exists():
                    try:
                        phase = json.loads(path.read_text()).get(pf, {}).get('phase')
                        if phase == 'fallback':
                            plan['overrides'][day] = []
                    except (OSError, ValueError, AttributeError):
                        plan['overrides'][day] = None
        # 반짝의 실제 생성기가 사용하는 정책 표. 기본 슬롯을 모든 업무의 목표로
        # 확대하지 않고, source와 편성 종류가 직접 연결되는 두 경로만 사용한다.
        for pf, prefix, job, label in [('threads', 'banzzak-daily-', 'banzzak-daily', '일반 글'),
                                        ('instagram', 'banzzak-insta-', 'banzzak-insta', '카드뉴스')]:
            table = policy['schedules']['banzzak'][pf]
            if table['type'] != 'weekly':
                raise ValueError('반짝 편성 형식 변경')
            for weekday, (category, at) in table['slots'].items():
                stop = paused.get(job)
                stop_at = ops.iso(stop.get('paused_at')) if isinstance(stop, dict) else ''
                plans.append(dict(brand='반짝', platform=pf, account=policy['accounts']['banzzak'][pf],
                    task=prefix+category, label=label+' · '+category, known=True,
                    weekdays=[int(weekday)], times=[at], paused_at=stop_at,
                    pause_unknown=stop is not None and not stop_at))
        # 일일 재료 선정·영상 대체 조건이 있으므로 조회 가능한 업무 목록만 등록한다.
        daily, _ = _values(base/'gitbap_daily.py')
        for name in daily['PUBLISH_HOUR_BY_KIND']:
            plans.append(dict(brand='깃밥', platform='threads', account=policy['accounts']['gitbap']['threads'],
                              task='gitbap-daily-'+name, label='일반 글 · '+DAILY.get(name, '기타'), known=False))
        for pf, task, label in [('threads','gitbap-top-repo','인기 레포 카드뉴스'),
                                ('instagram','gitbap-insta','카드뉴스')]:
            plans.append(dict(brand='깃밥', platform=pf, account=policy['accounts']['gitbap'][pf],
                              task=task, label=label, known=False))
    except (OSError, ValueError, KeyError, TypeError, StopIteration, SyntaxError):
        notes.append('일부 정기 일정 정의·운영 중지 상태를 확인하지 못했습니다.')
    # 1위 레포는 데이터 부재/최근 소개면 쉰다. 매일 12시 상수만으로 누락을 만들지 않는다.
    notes.append('재료·검토 결과에 따라 쉬는 업무와 연결되지 않은 업무는 일정 확인 불가입니다. 현재 정의 기준이며 과거 중지·순연 이력은 별도 확인이 필요합니다.')
    return plans, notes


def _times(plan, day):
    if day in plan.get('overrides', {}):
        return plan['overrides'][day]
    if not plan.get('known') or plan.get('pause_unknown'):
        return None
    if plan.get('retired'):
        return []
    if day < plan.get('start', '') or (plan.get('end') and day > plan['end']):
        return []
    if day in plan.get('holidays', []):
        return []
    if 'dates' in plan:
        times = plan['dates'].get(day, [])
    else:
        times = plan.get('times', []) if date.fromisoformat(day).weekday() in plan.get('weekdays', []) else []
    if not isinstance(times, list) or any(not isinstance(t, str) or len(t) != 5 or
            ops.stamp(f'{day}T{t}:00+09:00') is None for t in times):
        return None
    paused = ops.stamp(plan.get('paused_at'))
    return [f'{day}T{t}:00+09:00' for t in times
            if not paused or ops.stamp(f'{day}T{t}:00+09:00') < paused]


def _key(row):
    return row['brand'], row['platform'], ops.account_name(row['account']), family(row.get('job_source', '')), kind(row)


def _state(row, now):
    if row['status'] == 'failed':
        return 'failed'
    if row['status'] == 'published':
        return 'done' if row.get('publish_evidence') else 'unknown'
    if row['status'] == 'cancelled' and row.get('manual_rejected'):
        return 'rejected'
    if row['status'] in {'unknown', 'cancelled'}:
        return 'unknown' if row['status'] == 'unknown' else 'attention'
    when = ops.stamp(row.get('scheduled_at'))
    if not when:
        return 'unknown'
    if row['status'] in {'pending', 'held'} or now - when > GRACE:
        return 'attention'
    return 'scheduled'


def build(records, accounts, plans, *, now, week=None, complete=True, notes=()):
    start = monday(week, now=now)
    days = [(start+timedelta(days=i)).isoformat() for i in range(7)]
    groups, specs = defaultdict(list), {}
    # 같은 콘텐츠 ID여도 채널과 계정이 다르면 분리한다.
    unique, aliases = {}, {}
    for r in records:
        scope = r['brand'], r['platform'], ops.account_name(r['account'])
        keys = [(*scope, field, r[field]) for field in ('post_id', 'approval_id', 'server_id', 'id') if r.get(field)]
        matches = {aliases[k] for k in keys if k in aliases}
        identity = min(matches) if matches else len(aliases)
        candidates = [r] + [unique[k] for k in matches]
        # 서로 모순되는 실패를 성공으로 가리지 않는다.
        chosen = max(candidates, key=lambda x: (x['status'] == 'failed', bool(x.get('publish_evidence')), bool(x.get('scheduled_at'))))
        for old in matches:
            unique.pop(old)
        unique[identity] = chosen
        for key, old in list(aliases.items()):
            if old in matches:
                aliases[key] = identity
        for key in keys:
            aliases[key] = identity
    for r in unique.values():
        groups[_key(r)].append(r)
    for p in plans:
        key = p['brand'], p['platform'], ops.account_name(p['account']), p['task'], p['label']
        specs[key] = p
        groups[key]
    # source별 슬롯 대조는 유지하되 이번 주 기록/유효 슬롯이 없는 과거 업무는 제외한다.
    groups = defaultdict(list, {key: values for key, values in groups.items()
        if any((r.get('scheduled_at') or r.get('published_at') or r.get('prepared_at', ''))[:10] in days for r in values)
        or any(_times(specs.get(key, {}), day) for day in days)})
    for a in accounts:
        for brand in a.get('brands', [a.get('brand', '미분류')]):
            if not any(k[:3] == (brand, a['platform'], ops.account_name(a['account'])) for k in groups):
                groups[(brand, a['platform'], ops.account_name(a['account']), 'unmapped', '정기 콘텐츠 미확인')]
    metadata = {(a["platform"], ops.account_name(a["account"])): a for a in accounts}
    rows, issues = [], []
    for key, records in sorted(groups.items()):
        brand, pf, account, task, label = key
        plan = specs.get(key, {})
        cells = []
        for day in days:
            expected = _times(plan, day)
            hits = [r for r in records if (r.get('scheduled_at') or r.get('published_at') or r.get('prepared_at', ''))[:10] == day]
            items, unmatched = [], list(expected or [])
            for r in hits:
                actual = r.get('scheduled_at', '')
                # 다른 시각의 임시 글로 정기 슬롯을 채우지 않는다. 늦은 발행은 원래 예약에 연결한다.
                if actual in unmatched:
                    unmatched.remove(actual)
                elif not actual and len(unmatched) == 1 and len(hits) == 1:
                    unmatched.clear()  # 같은 업무의 시각 미정 초안은 상세에서 확인한다.
                state = _state(r, now)
                items.append(dict(id=r['id'], title=r['title'], state=state, label=STATES[state],
                    scheduled_at=actual, published_at=r.get('published_at', ''),
                    attention_kind='approval' if r['status']=='pending' else 'delayed' if r['status']=='approved' and state=='attention' else 'review',
                    reason=r.get('reason') or ('직접 반려한 콘텐츠 · 발행하지 않음' if state == 'rejected' else '승인 대기' if r['status'] == 'pending' else '취소·반려는 정기 일정의 휴무가 아닙니다' if r['status'] == 'cancelled' else ''),
                    url=r.get('verified_url', '') if state == 'done' else '',
                    evidence='성공 발행 기록 확인 · 온라인 재조회 안 함' if state == 'done' else '사용자 반려 결정 기록 확인' if state == 'rejected' else '발행 결과 확인 필요'))
            for at in unmatched:
                due = now - ops.stamp(at) > GRACE
                state = 'unknown' if not complete else 'attention' if due else 'scheduled'
                items.append(dict(id='', title='예정 콘텐츠', state=state, label=STATES[state],
                    scheduled_at=at, published_at='', url='', evidence='',
                    reason='조회 미완료' if not complete else '초안·발행 기록 없음' if due else '발행 예정 · 아직 기록 없음'))
            states = {i['state'] for i in items}
            uncertain = expected is None or not complete
            state = next((s for s in ('failed', 'attention', 'unknown') if s in states), None)
            state = state or ('unknown' if uncertain else 'scheduled' if 'scheduled' in states else 'done' if items else 'none')
            done = sum(i['state'] == 'done' for i in items)
            cell = dict(day=day, state=state, label=STATES[state], done=done,
                        total=len(items), expected=len(expected) if expected is not None else None,
                        schedule_known=expected is not None, items=items)
            cells.append(cell)
            for item in items:
                if item['state'] in {'failed', 'attention', 'unknown'}:
                    issues.append(dict(brand=brand, channel=ops.PLATFORMS[pf], account=account,
                                       kind=label, day=day, **item))
        meta = metadata.get((pf, account), {})
        rows.append(dict(brand=brand, platform=pf, channel=ops.PLATFORMS[pf],
            account='' if meta.get('identity_pending') else account,
            display_name=meta.get('display_name', account), market=meta.get('market', '언어·시장 확인 필요'),
            identity_pending=bool(meta.get('identity_pending')), connection_label=meta.get('label', '연결 상태 미확인'),
            kind=label, cells=cells))
    # 판정 단위(source별 슬롯)와 표시 단위(사업부·채널·계정·형식)를 분리한다.
    # 서로 다른 업무의 동시간 슬롯을 합치면 실제 예정 건수가 사라지므로 items는 그대로 합산한다.
    merged = {}
    for row in rows:
        label = row['kind']
        content_type = ('카드뉴스' if '카드뉴스' in label else '일반 글' if label.startswith('일반 글') else label)
        key = row['brand'], row['platform'], row['account'], content_type
        if key not in merged:
            merged[key] = dict(row, kind=content_type, cells=[dict(c, items=list(c['items'])) for c in row['cells']])
        else:
            for target, cell in zip(merged[key]['cells'], row['cells']):
                target['items'].extend(cell['items'])
                target['schedule_known'] = target['schedule_known'] and cell['schedule_known']
                target['expected'] = (target['expected'] + cell['expected']
                    if target['expected'] is not None and cell['expected'] is not None else None)
    rows, issues = list(merged.values()), []
    for row in rows:
        row['schedule_known'] = all(c['schedule_known'] for c in row['cells'])
        for cell in row['cells']:
            items = cell['items']; states = {i['state'] for i in items}
            # 전체 정기 일정 완전성은 행에 표시한다. 확인된 성공을 물음표로 바꾸지 않는다.
            state = next((s for s in ('failed', 'attention', 'unknown') if s in states), None)
            state = state or ('unknown' if not complete else 'scheduled' if 'scheduled' in states
                else 'done' if items else 'none' if cell['schedule_known'] else 'unknown')
            rejected = sum(i['state']=='rejected' for i in items)
            cell.update(state=state, label='✓ 처리 완료 · 직접 반려 포함' if state=='done' and rejected else STATES[state],
                        done=sum(i['state']=='done' for i in items), rejected=rejected, total=len(items))
            for item in items:
                if item['state'] in {'failed', 'attention', 'unknown'}:
                    issues.append(dict(brand=row['brand'], channel=row['channel'], account=row['account'],
                        kind=row['kind'], day=cell['day'], **item))
    return dict(start=days[0], end=days[-1], days=days, rows=rows, issues=issues,
                attention_count=len(issues), checked_at=now.astimezone(ops.KST).isoformat(),
                complete=complete, notes=list(notes), grace_minutes=int(GRACE.total_seconds()/60))


def operation_notices(root, *, now):
    """현재 중지/실행 공백 안내. 발행 판정이나 제어 상태는 변경하지 않는다."""
    notices = []
    labels = {'gitbap-webtoon': ('깃밥', '웹툰'), 'banzzak-insta-mia': ('반짝', '미아 노트')}
    try:
        paused = json.loads((root/'orchestrator/state/paused_jobs.json').read_text())['paused']
        for job, (brand, label) in labels.items():
            if job in paused:
                at = ops.iso(paused[job].get('paused_at'))
                notices.append(dict(brand=brand, kind='paused', title=f'{brand} {label}',
                    detail=f'{at[:10] or "시점 미확인"}부터 운영 중지 · 재개 전 운영 결정 확인'))
    except (OSError, ValueError, KeyError, TypeError, AttributeError):
        notices.append(dict(brand='', kind='unknown', title='중지 상태 확인 필요', detail='운영 중지 자료 조회 불가'))
    try:
        state = json.loads((root/'orchestrator/state/scheduler.json').read_text())
        last = state.get('gitmeshi-zenn-article', {}).get('last_run')
        if last and (now.astimezone(ops.KST).date()-date.fromisoformat(last)).days > 2:
            notices.append(dict(brand='깃밥', kind='check', title='Zenn 실행 기록 확인 필요',
                detail=f'마지막 실행 기록 {last} · 발행 중지 여부는 별도 확인 필요'))
    except (OSError, ValueError, TypeError, AttributeError):
        notices.append(dict(brand='', kind='unknown', title='실행 이력 확인 필요', detail='정기 실행 자료 조회 불가'))
    return notices
