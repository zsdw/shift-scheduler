"""근태일보에 따른 평일 주간 통제E 표기. 일반 근무 배정은 변경하지 않는다."""
from pathlib import Path
import re
from . import daily_report as dr


def control_e_slots(store: Path, day) -> list[int]:
    if dr.is_off_day(day):
        return []
    saved = dr.load_saved(store, day)
    if saved:
        notes = [r.get('비고', '') for r in saved.get('rows', {}).values()]
        kinds = []
        for note in notes:
            for match in re.finditer(r'([^,()\n]+?)\s*\d+\s*명\s*\(([^)]*)\)', note):
                if '최정식' in match[2].replace(' ', ''):
                    kinds.append(match[1].strip())
    else:
        kinds = [e['kind'] for e in dr.entries_for(store, day) if e['name'] == '최정식']
    if any('야간지원' in k.replace(' ', '') or any(what == 'absent' for what, _ in dr.classify(k)) for k in kinds):
        return []
    roster = dr.active(dr.load_roster(store), day)
    if not any(r['이름'] == '최정식' and r.get('직책') == '통제E' for r in roster):
        return []
    slots = [1, 3, 5, 7, 9]
    if any('오전반차' in k.replace(' ', '') for k in kinds):
        slots = [t for t in slots if t >= 5]
    if any('오후반차' in k.replace(' ', '') for k in kinds):
        slots = [t for t in slots if t < 5]
    return slots
