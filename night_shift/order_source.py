"""모든 조의 날짜별 편성표 원문 읽기. 스케줄러 이력과 분리한다."""
from datetime import date, datetime, time
from pathlib import Path
import json
import re
import openpyxl
from io import BytesIO
from .bulk_import import SHEET, TEAM

SOURCE_DIR = Path(r'C:\Users\LJH\Desktop\업무\업무자동화\업무일지')
UPLOAD_REFERENCE = 'uploaded_sources.json'


def parse_uploaded(data, filename):
    """시작일·조 제한 없이 모든 날짜 시트를 읽는다. 실제 근무 이력으로 저장하지 않는다."""
    book=openpyxl.load_workbook(BytesIO(data),read_only=True,data_only=True)
    found={}
    try:
        for ws in book:
            m=SHEET.search(ws.title)
            if not m:continue
            day=date(2000+int(m[1]),int(m[2]),int(m[3]))
            shift='day' if m[4]=='주' else 'night'
            found.setdefault(day.isoformat(),{})[shift]={**parse_sheet(ws,day,shift),'file':Path(filename).name}
    finally:book.close()
    if not found:raise ValueError('날짜별 주간·야간 편성표 시트가 없습니다.')
    return found


def publish_uploaded(store,data,filename,parsed=None):
    sources=parse_uploaded(data,filename) if parsed is None else parsed
    path=Path(store)/'order_source'/UPLOAD_REFERENCE
    path.parent.mkdir(parents=True,exist_ok=True)
    before=json.loads(path.read_text(encoding='utf-8')).get('sources',{}) if path.exists() else {}
    # 모든 조의 참조자료를 누적한다. 새 파일에 없는 날짜·주야간은 보존한다.
    sources={iso:{**shifts,**sources.get(iso,{})} for iso,shifts in before.items()} | {
        iso:shifts for iso,shifts in sources.items() if iso not in before}
    payload={'file':Path(filename).name,'sources':sources}
    tmp=path.with_suffix('.tmp');tmp.write_text(json.dumps(payload,ensure_ascii=False,indent=1),encoding='utf-8');tmp.replace(path)
    # 번호별 이름 고침: 그 날짜·근무의 원본 명단이 그대로면 유지(프로그램에서 고친 것 무시하지 않음, 2026-10-11),
    # 원본 명단이 바뀌었으면(작성자가 고쳤으면) 버린다.
    kept={}
    for iso,shifts in load_name_fixes(store).items():
        for shift,fix in shifts.items():
            old=(before.get(iso) or {}).get(shift,{}).get('names')
            new=(sources.get(iso) or {}).get(shift,{}).get('names')
            if old is not None and old==new:
                kept.setdefault(iso,{})[shift]=fix
    (Path(store)/NAME_FIX_FILE).write_text(json.dumps(kept,ensure_ascii=False,indent=1),encoding='utf-8')
    # 날짜 캐시는 이전 원본의 사본이므로 최신 참조 교체 후 폐기한다.
    for cached in path.parent.glob('????-??-??.json'):
        if cached.resolve().parent==path.parent.resolve():cached.unlink()
    from .source_attachment import stash
    stash(store,data,filename)
    return len(sources)


def days_with_data(store):
    """명령서를 띄울 수 있는 날짜 (2026-10-11 사용자 요청): 올린 편성표 엑셀(모든 조)이나 프로그램 저장본이 있는 날."""
    store=Path(store);found=set()
    path=store/'order_source'/UPLOAD_REFERENCE
    if path.exists():
        found|={date.fromisoformat(d) for d,v in json.loads(path.read_text(encoding='utf-8')).get('sources',{}).items() if v}
    for folder in (store,store/'day',store/'weekend_day'):
        for f in folder.glob('????-??-??.json'):
            try:found.add(date.fromisoformat(f.stem))
            except ValueError:pass
    return found


def document_available(store,day):
    """명령서·근태일보·문서 대조를 하는 날 (2026-10-11): A조 작성일이거나 편성표 자료가 있는 날."""
    from .calendar_info import document_day
    return document_day(day) or day in days_with_data(store)


def reference_sources(store,day):
    path=Path(store)/'order_source'/UPLOAD_REFERENCE
    if path.exists():
        data=json.loads(path.read_text(encoding='utf-8'))
        return cp_sources(data['sources'].get(day.isoformat(),{}),store,day)
    original=latest_file()
    return cp_sources(read_day(original,day,store) if original else {},store,day)


def cp_sources(sources,store,day):
    from .cp_schedule import for_day,covers
    from copy import deepcopy
    found=deepcopy(sources)
    for shift,source in found.items():
        cp=for_day(Path(store),day,shift)
        if cp or covers(store,day):
            source['cp']=cp
            for cells in source.get('cells',{}).values():
                if 'CP' in cells:cells['CP']=''
                if '셔틀' in cells:
                    cells['셔틀']=re.sub(r'CP([123])',lambda m:m[0] if m[1] in cp else '',cells['셔틀'])
    return found


def latest_file(folder=SOURCE_DIR):
    files = [p for p in Path(folder).glob('*편성표*.xlsx') if not p.name.startswith('~$')]
    return max(files, key=lambda p: (p.stat().st_mtime_ns, p.name)) if files else None


def normalize(value):
    return re.sub(r'\s+', '', str(value if value is not None else '')).upper()


def hour(value):
    if isinstance(value, (datetime, time)):
        return value.hour
    m = re.fullmatch(r'\s*(\d{1,2})[:시](?:00)?\s*', str(value))
    return int(m[1]) % 24 if m and 0 <= int(m[1]) <= 24 else None


def parse_sheet(ws, day, shift):
    rows = list(ws.iter_rows(min_row=1, max_row=40, max_col=90, values_only=True))
    heading = ' '.join(str(v) for row in rows[:4] for v in row if v is not None)
    team_match = TEAM.search(heading)
    team = team_match[1] if team_match else ''
    names, cp, controls = {}, {}, []
    for row in rows[:6]:
        for value in row:
            text = normalize(value)
            m = re.fullmatch(r'(\d{1,2})[.,·\-]?([가-힣]{2,4})', text)   # '8.세명'처럼 점 찍힌 칸도 (2026-10-21)
            if m: names[m[1]] = m[2]
            m = re.fullmatch(r'CP([123])([가-힣]{2,4})', text)
            if m: cp[m[1]] = m[2]
            m = re.fullmatch(r'통제([A-Z])', text)
            if m and m[1] not in controls: controls.append(m[1])
    index = next((i for i,row in enumerate(rows) if any(normalize(v) == '근무시간' for v in row)), None)
    if index is None: raise ValueError(f'{ws.title}: 시간표 제목 없음')
    headers = {j: normalize(v).replace('보안실/대기','보안실') for j,v in enumerate(rows[index]) if v is not None}
    time_col = next(j for j,v in headers.items() if v == '근무시간')
    cells = {}
    for row in rows[index+1:]:
        h = hour(row[time_col])
        if h is not None:
            cells[str(h)] = {head: str(row[j]).strip() if row[j] is not None else ''
                             for j,head in headers.items() if j != time_col}
    return {'day': day.isoformat(), 'shift': shift, 'team': team, 'sheet': ws.title,
            'names': names, 'cp': cp, 'controls': controls, 'cells': cells}


def read_day(path, day, store=None):
    path = Path(path)
    stamp = {'path': str(path), 'size': path.stat().st_size, 'mtime': path.stat().st_mtime_ns}
    found = {}
    cache = Path(store) / 'order_source' / f'{day.isoformat()}.json' if store else None
    if cache and cache.exists():
        data = json.loads(cache.read_text(encoding='utf-8'))
        if data.get('stamp') == stamp: return data['sources']
    book = openpyxl.load_workbook(path, read_only=True, data_only=True)
    try:
        for ws in book:
            m = SHEET.search(ws.title)
            if m and date(2000+int(m[1]),int(m[2]),int(m[3])) == day:
                shift = 'day' if m[4] == '주' else 'night'
                found[shift] = {**parse_sheet(ws,day,shift),'file':path.name}
    finally: book.close()
    if cache:
        cache.parent.mkdir(parents=True,exist_ok=True)
        tmp = cache.with_suffix('.tmp')
        tmp.write_text(json.dumps({'stamp':stamp,'sources':found},ensure_ascii=False,indent=1),encoding='utf-8')
        tmp.replace(cache)
    return found


def saved_day_source(store, day):
    """저장된 프로그램 주간 근무표(이미지·엑셀 업로드본 또는 확정 생성표)를 편성표와 같은 모양으로.

    사용자 확정(2026-10-07): 저장된 프로그램 근무표가 진짜 근무표다. 있으면 폴더 편성표 엑셀보다 우선한다.
    업로드본은 원본 칸(4C·CP·셔틀·공동근무)을 그대로, 생성표는 근무표 칸에서 만든다.
    """
    from .day_shift import (CONTROL_SLOTS, EDU, PATROL, REST, SHUTTLE, STANDBY, control_active, control_patrol_at,
                            load_day)
    path = Path(store) / 'day' / f'{day.isoformat()}.json'
    if not path.exists(): return None
    schedule = load_day(Path(store) / 'day', day)['schedule']
    layout = schedule.source_layout or {}
    rows = layout.get('applied_rows') or layout.get('rows')
    raw = json.loads(path.read_text(encoding='utf-8'))
    label = '이미지 저장본' if str(raw.get('source', '')).startswith('image') else '엑셀저장본' if str(raw.get('source', '')).startswith('excel') else '저장본'
    team = layout.get('team') or ''
    if not team:
        from .daily_report import teams_for
        team = str(teams_for(day).get('주간조', '')).replace('조', '')
    if rows and len(rows) == 10:
        names = {str(k): v for k, v in (layout.get('mapping') or {}).items() if str(k).isdigit() and v}
        cp = {k[2:]: v for k, v in (layout.get('extra_names') or {}).items() if k.startswith('CP') and v}
        controls = list(layout.get('controls') or (['A'] if schedule.control else []))
        cells = {str(int(r['시간'][:2])): {k: str(v or '') for k, v in r.items() if k != '시간'} for r in rows}
    else:
        number = {p.pid: p.number for p in schedule.people if p.number}
        names = {str(n): pid for pid, n in number.items()}
        # 평일 주간 통제D·E는 근무표 칸 밖 고정 인원. 연차·휴무면 명령서가 일보를 보고 뺀다.
        cp, controls, cells = {}, ['D', 'E'] + (['A'] if schedule.control else []), {}
        for t in range(10):
            col = {pid: row[t] for pid, row in schedule.grid.items() if pid in number}
            join = lambda labels, extra=(): '.'.join([*extra, *sorted((str(number[p]) for p, l in col.items() if l in labels), key=int)])
            a_here = control_active(schedule, t)
            filled = schedule.fill.get(t, {})
            row = {post: join({post}, [w for p, w in filled.items() if p == post]) for post in ('G1', 'G2', 'G3', 'L1', 'L2', 'C1', 'C2')}
            row['4C'] = join({'통제'}, ['A'] if a_here and t in CONTROL_SLOTS else [])
            patrol = a_here and control_patrol_at(schedule, t)
            row['순찰'] = join({PATROL}, ['A'] if patrol else [])
            row['대기'] = join({STANDBY})
            resting = a_here and t not in CONTROL_SLOTS and not patrol and 'A' not in filled.values()
            row['휴게'] = join({REST, EDU}, ['A'] if resting else [])
            shuttle = schedule.shuttle.get(t)
            row['셔틀'] = f'{number[shuttle]}({SHUTTLE[t]})' if shuttle in number else ''
            cells[str(8 + t)] = row
    if not cp:                                    # CP 이름은 사용자가 준 CP 근무표
        from .cp_schedule import for_day
        cp = for_day(Path(store), day, 'day') or {}
    return {'day': day.isoformat(), 'shift': 'day', 'team': team, 'sheet': f'프로그램 근무표({label})',
            'names': names, 'cp': cp, 'controls': controls, 'cells': cells, 'file': path.name, 'program': True}


def saved_night_source(store, day):
    """저장된 야간 실제 근무표(수정 이력 포함)를 명령서 입력으로 사용한다."""
    from .history_store import actual_record
    from .models import AssignmentKind
    from .daily_report import teams_for
    from .cp_schedule import for_day
    path = Path(store) / f"{day.isoformat()}.json"
    if not path.exists(): return None
    record = actual_record(Path(store), day)
    context = record.context
    employees = {e.employee_id: e.name for e in context.employees}
    attendance = {a.employee_id: a for a in context.attendance if a.present}
    tokens = {pid: str(a.display_number) if a.display_number is not None else "A"
              for pid, a in attendance.items()}
    names = {str(a.display_number): employees[pid] for pid, a in attendance.items()
             if a.display_number is not None}
    controls = ['A'] if any(a.acts_as_manager and a.display_number is None for a in attendance.values()) else []
    cells = {str((18+t)%24): {} for t in range(14)}
    for row in record.assignments:
        if row.employee_id not in attendance: continue
        assignment = row.displayed_assignment
        if assignment.kind == AssignmentKind.UNAVAILABLE: continue
        label = assignment.label
        post = ('순찰' if assignment.kind == AssignmentKind.PATROL else
                '휴게' if assignment.kind == AssignmentKind.REST else
                '보안실' if label == '보안실 대기' else label)
        values = cells[str((18+row.slot.index)%24)]
        token = tokens[row.employee_id]
        values[post] = '.'.join(filter(None, [values.get(post), token]))
    # 편성표 본표와 동일: 남문 두 명일 때 관리자 외 인원은 G3 칸.
    for values in cells.values():
        g2 = values.get('G2', '').split('.')
        if len(g2) > 1 and not values.get('G3'):
            g2.sort(key=lambda x: (x != 'A', int(x) if x.isdigit() else 0))
            values['G2'], values['G3'] = g2[0], '.'.join(g2[1:])
    cp = for_day(Path(store), day, 'night') or {}
    return {'day': day.isoformat(), 'shift': 'night', 'team': str(teams_for(day)['야간조']).replace('조',''),
            'sheet': '프로그램 야간 근무표(실제 저장본)', 'names': names, 'controls': controls,
            'cp': cp, 'cells': cells, 'file': path.name, 'program': True}


def sources_for(store, day):
    """명령서·대조에 쓸 주간·야간 근무 자료: 저장된 프로그램 근무표 우선, 없으면 폴더 편성표 엑셀."""
    found = dict(reference_sources(store,day))
    program = saved_day_source(store, day)
    if program:
        found['day'] = program
    night = saved_night_source(store, day)
    if night:
        found['night'] = night
    return cp_sources(apply_name_fixes(found, store, day),store,day)


NAME_FIX_FILE ='order_name_fix.json'   # 편성표 번호 이름 오기 바로잡기 (예: 10/8 6만년 → 6여진, 2026-10-07)


def load_name_fixes(store):
    path = Path(store) / NAME_FIX_FILE
    return json.loads(path.read_text(encoding='utf-8')) if path.exists() else {}


def save_name_fix(store, day, shift, names):
    """names = {번호: 짧은 이름}; 편성표 원문과 같은 번호는 저장하지 않는다. 원본 엑셀은 그대로."""
    fixes = load_name_fixes(store)
    fixes.setdefault(day.isoformat(), {})[shift] = {str(k): v for k, v in names.items() if v}
    if not fixes[day.isoformat()][shift]: fixes[day.isoformat()].pop(shift)
    if not fixes[day.isoformat()]: fixes.pop(day.isoformat())
    path = Path(store) / NAME_FIX_FILE
    path.write_text(json.dumps(fixes, ensure_ascii=False, indent=1), encoding='utf-8')


def apply_name_fixes(sources, store, day):
    fixed = {}
    for shift, source in sources.items():
        # 이름 고침은 폴더 편성표 엑셀의 오기용. 프로그램 근무표는 번호가 다르므로 적용하지 않는다.
        change = {} if source.get('program') else load_name_fixes(store).get(day.isoformat(), {}).get(shift, {})
        fixed[shift] = {**source, 'names': {**source['names'], **change}, 'name_fixes': change} if change else source
    return fixed


def sync_leave(store, folder=SOURCE_DIR):
    """새 폴더 자료가 바뀐 경우만 연차일정을 갱신한다. 이전 내용 보존."""
    from .leave_schedule import save_text, parse
    files = [p for p in Path(folder).glob('*연차*.txt') if not p.name.startswith('~$')]
    if not files: return None
    path = max(files,key=lambda p:(p.stat().st_mtime_ns,p.name))
    stamp = {'path':str(path),'size':path.stat().st_size,'mtime':path.stat().st_mtime_ns}
    marker = Path(store)/'folder_leave_source.json'
    if marker.exists() and json.loads(marker.read_text(encoding='utf-8')) == stamp: return path.name
    raw = path.read_bytes()
    for encoding in ('utf-8-sig','cp949','utf-16'):
        try: text = raw.decode(encoding); break
        except UnicodeError: continue
    else: raise ValueError('연차일정 인코딩을 확인할 수 없습니다.')
    if not parse(text): raise ValueError('연차일정에서 날짜별 항목을 읽지 못했습니다.')
    old = Path(store)/'leave_schedule.txt'
    if old.exists() and old.read_text(encoding='utf-8') != text:
        backup = Path(store)/'.trash'/f'leave_schedule_{datetime.now():%Y%m%d_%H%M%S_%f}.txt'
        backup.parent.mkdir(parents=True,exist_ok=True)
        backup.write_bytes(old.read_bytes())
        from .kakao_sync import recycle                 # 이전 연차일정은 직전 1개만 (2026-10-11)
        recycle(sorted(backup.parent.glob('leave_schedule_*.txt'))[:-1])
    save_text(Path(store),text)
    marker.write_text(json.dumps(stamp,ensure_ascii=False),encoding='utf-8')
    return path.name
