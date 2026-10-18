"""저장된 야간 기록의 반차·연차 시간 '휴게' → 근무불가(×) 일괄 수정 (2026-10-05, 룰북 21-7).

사용:  .venv\\Scripts\\python.exe tools_leave_fix.py          (미리보기만)
       .venv\\Scripts\\python.exe tools_leave_fix.py --apply  (원본은 history/.trash 에 백업 후 수정)
"""
from __future__ import annotations

import json
import shutil
import sys
from datetime import datetime
from pathlib import Path

from night_shift import history_store, leave_schedule
from night_shift import history_import as imp
from night_shift.validator import validate_first_trial
from night_shift.models import HistoryInput

NAMES = {name: eid for eid, name in imp.ROSTER.items() if eid != "A"}


def main(apply: bool) -> None:
    store = Path(history_store.store_dir()) if hasattr(history_store, "store_dir") else Path("history")
    entries = leave_schedule.load(store)
    for day in history_store.list_dates(store):
        statuses = leave_schedule.defaults_for(entries, day, "night", list(NAMES))[0]
        slots = {("A" if who == "A" else NAMES[who]): leave_schedule.night_unavailable_slots(st)
                 for who, (st, _) in statuses.items()}
        slots = {k: v for k, v in slots.items() if v}
        if not slots:
            continue
        path = store / f"{day}.json"
        data = json.loads(path.read_text(encoding="utf-8"))
        record = history_store.record_from_json(data["plan"])
        fixed, cells = imp.leave_fix_record(record, slots)
        busy = sorted({imp.ROSTER[r.employee_id] for r in record.assignments
                       if r.slot.index in slots.get(r.employee_id, ())
                       and r.actual_post_or_work_type.kind.value not in ("rest", "unavailable")})
        if busy:
            print(f"{day}: {', '.join(busy)} — 연차일정은 반차·연차인데 그 시간에 근무 기록 있음 → 손대지 않음(확인 필요)")
        if not cells:
            continue
        who = sorted({imp.ROSTER[e] for e, _ in cells})
        before = len(validate_first_trial(record, HistoryInput((), ()), rules_v220=True))
        after = len(validate_first_trial(fixed, HistoryInput((), ()), rules_v220=True))
        print(f"{day}: {', '.join(who)} {len(cells)}칸 휴게→근무불가 "
              f"({', '.join(f'{(18 + t) % 24:02}시' for _, t in cells)}) · 검증 위반 {before}→{after}")
        if apply:
            trash = store / ".trash"
            trash.mkdir(exist_ok=True)
            shutil.copy2(path, trash / f"{day}__before-leave-fix-{datetime.now().strftime('%Y%m%d-%H%M%S')}.json")
            data["plan"] = history_store.record_to_json(fixed)
            data["note"] = (data.get("note") or "") + "\n연차일정 반차·연차 시간 휴게 → 근무불가(×) 수정 (2026-10-05)"
            path.write_text(json.dumps(data, ensure_ascii=False, indent=1), encoding="utf-8")


if __name__ == "__main__":
    main("--apply" in sys.argv)
