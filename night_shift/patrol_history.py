"""확정 야간·공휴일 주간에서 순찰 제외/출근 이력만 읽는다. 피로도 이력은 합치지 않는다."""
import json
from pathlib import Path
from datetime import date

def key(name):
    return str(name).strip()[-2:]

def load_events(store, before, shift='night'):
    from .history_store import actual_record
    from .calendar_info import is_off_day
    store=Path(store); target=(str(before), 0 if shift=='day' else 1)
    events=[]
    for path in sorted(store.glob('????-??-??.json')):
        if (path.stem,1)>=target:continue
        record=actual_record(store,date.fromisoformat(path.stem))
        names={p.employee_id:p.name for p in record.context.employees}
        full=sum(a.present for a in record.context.attendance)==7 and all(
            a.available_slot_indices is None or len(a.available_slot_indices)==14 for a in record.context.attendance)
        for a in record.context.attendance:
            if not a.present or not a.is_general_worker:continue
            patrol=any(r.employee_id==a.employee_id and r.actual_post_or_work_type.kind.value=='patrol'
                       for r in record.assignments)
            events.append({'date':path.stem,'shift':1,'name':key(names[a.employee_id]),
                           'excluded':full and not patrol,'patrol':patrol})
    for path in sorted((store/'weekend_day').glob('????-??-??.json')):
        if (path.stem,0)>=target or not is_off_day(date.fromisoformat(path.stem)):continue
        data=json.loads(path.read_text(encoding='utf-8'))
        names=data.get('names',{}); grid=data.get('grid',{})
        full=len([p for p,r in grid.items() if p!='A' and any(v not in (None,'×') for v in r)])==6 and not data.get('half_days') and not data.get('leavers')
        for pid,row in grid.items():
            if pid=='A' or not any(v not in (None,'×') for v in row):continue
            patrol='순찰' in row
            events.append({'date':path.stem,'shift':0,'name':key(names[pid]),
                           'excluded':full and not patrol,'patrol':patrol})
    return tuple(sorted(events,key=lambda e:(e['date'],e['shift'],e['name'])))
