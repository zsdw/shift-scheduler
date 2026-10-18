"""Compare actual schedule content; transport timestamps and OCR metadata are not duties."""
import json
import re
from pathlib import Path
OVERWRITE_NOTE='덮어씌워진 근무표: 업로드 확인본으로 기존 저장본을 교체했습니다.'

def canonical(payload):
    if 'plan' in payload:
        from . import history_store
        from .actual_edit import apply_edits
        record=apply_edits(history_store.record_from_json(payload['plan']),payload.get('edits',[]))
        value=history_store.record_to_json(record)
        for key in ('record_id','kind','source_plan_id','confirmed_at'):value.pop(key,None)
        value['assignments']=sorted(value['assignments'],key=lambda r:(r['employee_id'],r['slot']))
        value['context']['employees']=sorted(value['context']['employees'],key=lambda r:r['employee_id'])
        value['context']['attendance']=sorted(value['context']['attendance'],key=lambda r:r['employee_id'])
    elif payload.get('kind')=='day' or 'people' in payload:
        keys=('date','people','grid','shuttle','control','fill','control_as_worker_from','rule_exempt_names')
        value={k:payload.get(k,{} if k in ('grid','shuttle','fill') else [] if k in ('people','rule_exempt_names') else None) for k in keys}
        value['people']=sorted(value['people'],key=lambda r:r['pid'])
        value['patrols']=sorted(payload.get('control_patrol_slots') or ([] if payload.get('control_patrol') is None else [payload['control_patrol']]))
        value['rule_exempt_names']=sorted(value['rule_exempt_names'])
    else:
        value={k:payload.get(k) for k in ('day','names','grid','half_days','mode','g2_cap','manager_priority')}
        value['rule_exempt_names']=sorted(payload.get('rule_exempt_names') or [])
    review=payload.get('source_review')
    if review:
        from .schedule_image_import import apply_rest_priority,normalize_cell
        rows=apply_rest_priority(review.get('applied_rows',review.get('rows',[])))
        def cell(v):
            text=normalize_cell(str(v))
            if re.fullmatch(r'(?:CP[123]|[A-E]|[0-9]+)(?:\.(?:CP[123]|[A-E]|[0-9]+))*',text):
                return '.'.join(sorted(text.split('.')))
            return text
        value['source_cells']=[{k:cell(v) for k,v in r.items()} for r in rows]
        value['source_names']={**review.get('mapping',{}),**review.get('extra_names',{})}
    return value

def post_signature(payload):
    """A조 시간별 실제 포스트·투입자 비교. 번호·휴게·대기·운영 모드는 제외."""
    duties = set()
    def name(value):
        value = re.sub(r'\s+', '', str(value))
        return '통제A' if value in ('A','통제','통제A') else value
    ignored = {'휴게','휴','휴게실','보안실','보안실 대기','대기','교육','근무불가','×','—','',None}
    if 'plan' in payload:
        from .history_store import record_from_json
        from .actual_edit import apply_edits
        from .models import AssignmentKind
        record = apply_edits(record_from_json(payload['plan']), payload.get('edits', []))
        names = {e.employee_id: name(e.name) for e in record.context.employees}
        for row in record.assignments:
            assignment = row.displayed_assignment
            if assignment.kind in (AssignmentKind.POST, AssignmentKind.PATROL):
                # 야간 G3 칸 = G2 두 번째 사람(현장 양식 표기, 2026-10-06 확정) → 같은 남문 근무로 비교 (2026-10-11)
                label = 'G2' if assignment.label == 'G3' else assignment.label
                duties.add((row.slot.index, label, names[row.employee_id]))
    else:
        people = {p['pid']: p.get('name', p['pid']) for p in payload.get('people', [])}
        people.update(payload.get('names') or {})
        for pid, row in (payload.get('grid') or {}).items():
            for t, label in enumerate(row):
                if label not in ignored:
                    duties.add((t, label, name(people.get(pid, pid))))
        for t, filled in (payload.get('fill') or {}).items():
            for post, token in filled.items():
                duties.add((int(t), post, name(token)))
        layout = payload.get('source_layout') or payload.get('source_review') or {}
        mapping = layout.get('mapping') or {}
        if not layout and payload.get('control'):
            from .day_shift import from_json, control_active, control_patrol_at, CONTROL_SLOTS
            schedule = from_json(payload)
            for t in range(10):
                if control_active(schedule,t) and t in CONTROL_SLOTS:
                    duties.add((t,'4C','통제A'))
                if control_patrol_at(schedule,t):
                    duties.add((t,'순찰','통제A'))
        # 보조 포스트에만 기록된 A조 직원도 비교한다(CP 별도 직원 제외).
        for t, row in enumerate(layout.get('applied_rows') or layout.get('rows') or []):
            for post in ('4C','1C'):
                for token in re.findall(r'CP[123]|[A-E]|[0-9]+', str(row.get(post, ''))):
                    if not token.startswith('CP'):
                        duties.add((t, post, name(mapping.get(token, token))))
    return sorted(duties)


def identical(path,payload):
    path=Path(path)
    return path.exists() and post_signature(json.loads(path.read_text(encoding='utf-8')))==post_signature(payload)

def mark_overwrite(path,payload):
    if Path(path).exists():
        old=json.loads(Path(path).read_text(encoding='utf-8'))
        notes=[payload.get('note',''),OVERWRITE_NOTE]
        payload['note']='\n'.join(dict.fromkeys(line for n in notes for line in n.splitlines() if line))
    return payload
