"""문서 작성 기준 선택. 원본 일정과 근무 기록은 수정하지 않는다."""
import hashlib
import json
import copy
import re
from datetime import timedelta
from pathlib import Path
from . import daily_report as dr, date_check, order_source

def state(store, day, sources=None):
    sources=order_source.sources_for(store,day) if sources is None else sources
    sources=order_source.cp_sources(sources,store,day)
    issues=[i for i in date_check.review(store,day,sources) if i['level'] in ('error','warn')]
    roster=dr.load_roster(store)
    entries=dr.entries_for(store,day)
    stamp=hashlib.sha256(json.dumps([sources,entries,dr.entries_for(store,day-timedelta(days=1)),roster,issues],ensure_ascii=False,sort_keys=True,default=str).encode()).hexdigest()
    try:data=json.loads((Path(store)/'document_basis.json').read_text(encoding='utf-8'))
    except (OSError,ValueError):data={}
    choice=data.get(day.isoformat(),{})
    basis=choice.get('basis') if choice.get('stamp')==stamp else None
    return sources,issues,stamp,basis

def save(store,day,stamp,basis):
    if basis not in ('leave','schedule'):raise ValueError(basis)
    path=Path(store)/'document_basis.json'
    try:data=json.loads(path.read_text(encoding='utf-8'))
    except (OSError,ValueError):data={}
    data[day.isoformat()]={'stamp':stamp,'basis':basis}
    path.parent.mkdir(parents=True,exist_ok=True)
    tmp=path.with_suffix('.tmp');tmp.write_text(json.dumps(data,ensure_ascii=False,indent=1),encoding='utf-8');tmp.replace(path)

def report_for(store,day,sources=None):
    sources,issues,stamp,basis=state(store,day,sources)
    if issues and basis is None:return None
    entries=dr.entries_for(store,day)
    roster=dr.load_roster(store)
    if basis=='schedule':
        relevant=[i for i in issues if i['person'] and i['kind'] in ('absent_listed','not_expected','missing','schedule_leave')]
        fixes={i['person']:'absent' for i in relevant}
        fixes.update({i['person']:'present' for i in relevant if i['kind'] in ('absent_listed','not_expected')})
        entries=[e for e in entries if e['name'] not in fixes or fixes[e['name']]=='present' and
                 not any(what=='absent' for what,_ in dr.classify_entry(e))]
        group={p['이름']:p['소속'] for p in roster}
        for name,status in fixes.items():
            issue=next(i for i in relevant if i['person']==name and (status!='present' or i['kind'] in ('absent_listed','not_expected')))
            kind=issue.get('choices',[{}])[0].get('status','출근') if status=='present' else '미출근:근무표 미편성'
            if kind=='출근':kind='출근:근무표 편성'
            entries.append({'team':group.get(name,''),'name':name,'kind':kind if status=='present' else '미출근:근무표 미편성'})
    report=dr.build(day,entries,roster,dr.entries_for(store,day-timedelta(days=1)))
    report['document_basis']=basis or 'matched'
    return report

def sources_for_report(sources,report,roster):
    """연차 기준이면 미출근자의 번호·시간표 제외. 없는 출근자의 시간표는 생성하지 않는다."""
    if report['document_basis']!='leave':return sources
    from .security_order import present
    result=copy.deepcopy(sources)
    active=dr.active(roster,report['day'])
    names=[p['이름'] for p in active]
    for shift,source in result.items():
        excluded=[]
        for number,short in list(source['names'].items()):
            full=date_check._match(short,names)
            if full and not present(full,report['rows'],shift,False):
                excluded.append(number);del source['names'][number]
        for cells in source['cells'].values():
            for post,value in cells.items():
                for number in excluded:
                    value=re.sub(r'(?<![A-Za-z0-9])'+re.escape(number)+r'(?![0-9])','',str(value))
                cells[post]=value
        expected=date_check._expected(report['rows'],active,report['teams'],shift,report['off_day'])
        for name in expected:
            if not any(name.endswith(short) for short in source['names'].values()):
                number=str(max([int(n) for n in source['names']] or [0])+1)
                source['names'][number]=name
                source.setdefault('basis_warnings',[]).append(f'{name}: 연차일정상 출근이지만 근무표에 시간표가 없어 성명만 기재했습니다. 포스트·시간 확인이 필요합니다.')
    return result
