"""Resolve paired newcomers from the daily roster and current leave personnel notices."""
from datetime import date
from pathlib import Path
from . import daily_report,leave_schedule

def detect(store,day,rows,mapping):
    from .schedule_image_import import persons
    roster=daily_report.load_roster(Path(store));entries=leave_schedule.load(Path(store),day.year)
    # The shared work folder is also the authoritative source used by document automation.
    if not entries and Path(store).resolve()==Path(__file__).resolve().parent.parent/"history":
        source=Path.home()/'Desktop'/'업무'/'업무자동화'/'업무일지'/f'연차일정({day.year}).txt'
        if source.is_file():entries=leave_schedule.parse(source.read_text(encoding='utf-8-sig'),day.year)
    dates={};evidence={}
    for token,name in mapping.items():
        matches=[r for r in roster if r['이름']==name or r['이름'].endswith(name)]
        fullnames={r['이름'] for r in matches}|{item['name'] for items in entries.values() for item in items if item['name']==name or item['name'].endswith(name)}
        if name in fullnames:fullnames={name}
        if len(fullnames)!=1:continue
        full=next(iter(fullnames));employee=next((r for r in matches if r['이름']==full),{})
        start=employee.get('시작')
        if start and date.fromisoformat(start[:10])<=day:
            dates[token]=date.fromisoformat(start[:10]);evidence[token]=f'조별 명단: {full} {start[:10]} 입사'
        for when,items in entries.items():
            for item in items:
                kind=item['kind']
                if when<=day and item['name']==full and '입사' in kind and not any(x in kind for x in ('예정','퇴사')):
                    if token not in dates or when>=dates[token]:
                        dates[token]=when;evidence[token]=f'연차일정: {full} {when} {kind}'
    result={};solo=set()
    for row in rows:
        for post,value in row.items():
            if post in ('시간','휴게','대기','보안실','CP','셔틀'):continue
            try:everyone=persons(value);ids=[p for p in everyone if p in mapping]
            except ValueError:continue
            if len(everyone)==1 and ids and post not in NOT_POST and '교육' not in str(value):solo.add(ids[0])
            if len(ids)<2:continue
            latest=max((dates[p] for p in ids if p in dates),default=None)
            newest=[p for p in ids if dates.get(p)==latest]
            if latest and len(newest)==1 and any(p not in dates or dates[p]<latest for p in ids):
                result[newest[0]]=evidence[newest[0]]
    # Records start from the first day the newcomer stands a post alone (user rule, 2026-10-07).
    for token in list(result):
        if token in solo or recorded_before(store,day,dates[token],mapping[token]):result.pop(token)
    return result


NOT_POST=('순찰','순회','대기','보안실','휴 게')


def _recorded_names(data):
    """Names a saved actual record counts as recorded (newcomers paired that day excluded)."""
    exempt=set(data.get('rule_exempt_names') or ())
    if 'plan' in data:
        context=data['plan'].get('context',{});present={a['employee_id'] for a in context.get('attendance',[]) if a.get('present')}
        return {e['name'] for e in context.get('employees',[]) if e['employee_id'] in present}-exempt
    if 'people' in data:return {p['pid'] for p in data['people']}-exempt
    if 'names' in data:return set(data['names'].values())-exempt
    return set()


def recorded_before(store,day,since,name):
    """True when a saved record between the join date and the day already counts this person (worked alone)."""
    import json
    root=Path(store)
    for folder in (root,root/'day',root/'weekend_day'):
        if not folder.is_dir():continue
        for path in folder.glob('????-??-??.json'):
            try:when=date.fromisoformat(path.stem)
            except ValueError:continue
            if not since<=when<day:continue
            try:data=json.loads(path.read_text(encoding='utf-8'))
            except (OSError,ValueError):continue
            if name in _recorded_names(data):return True
    return False
