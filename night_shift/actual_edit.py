"""Actual-shift corrections on top of a confirmed plan (§20).

The actual record is ``apply_edits(plan, edits)``. Two edit kinds:

* ``{"type": "swap", "a": [employee, slot], "b": [employee, slot]}``
  Two cells exchanged what was actually done (same or different hours).
  Each cell is rebuilt with the normal accounting for its new slot.
* ``{"type": "state", "from": slot, "to": slot, "posts": {"I1": "rest", "G1": "seated"}}``
  Within the hour range, the listed posts were actually seated work or
  rest-like (e.g. planned FM but run flexibly).

* ``{"type": "fatigue", "cell": [employee, slot], "value": 0..2, "note": "..."}``
  The cell was actually this tiring (e.g. an incident on I1). Applied after
  every other edit; the note is kept as a comment on the cell.

``actual_checks`` records rule outcomes from the *recorded* accounting of the
actual shift. It is a record for history, not an approval gate.
"""
from __future__ import annotations

from dataclasses import replace

from .models import Assignment, AssignmentKind as K, NightType, Posture, ShiftRecord
from .profiles import make_record, options_for

HOUR = lambda t: f"{(18 + t) % 24:02d}시"  # noqa: E731


def _rows(record):
    return {(r.employee_id, r.slot.index): r for r in record.assignments}


def _rebuild(record: ShiftRecord, employee_id: str, slot: int, source) -> object:
    """Row for (employee, slot) doing what ``source`` displayed."""
    label = source.displayed_assignment.label
    allowed = {r.displayed_assignment.label for r in options_for(record.context, employee_id, slot,
                                                                 patrol_standing=True)}
    if label not in allowed:
        raise ValueError(f"{HOUR(slot)}에는 '{label}' 근무가 없어서 옮길 수 없습니다.")
    install, remove = source.barrier_install_flag, source.barrier_remove_flag
    if (install and slot != 2) or (remove and slot != 10):
        raise ValueError("차단봉 설치·철수는 정해진 시간(20시·04시) 밖으로 옮길 수 없습니다.")
    try:
        return make_record(record.context, employee_id, slot, label, install=install, remove=remove,
                           patrol_standing=True)
    except ValueError as exc:
        raise ValueError(f"{HOUR(slot)} '{label}' 배치를 만들 수 없습니다: {exc}") from exc


def _swap(record: ShiftRecord, a, b) -> ShiftRecord:
    rows = _rows(record)
    ka, kb = (str(a[0]), int(a[1])), (str(b[0]), int(b[1]))
    ra, rb = rows[ka], rows[kb]
    if K.UNAVAILABLE in (ra.displayed_assignment.kind, rb.displayed_assignment.kind):
        raise ValueError("근무불가(×) 칸은 바꿀 수 없습니다.")
    new_a = _rebuild(record, ka[0], ka[1], rb)
    new_b = _rebuild(record, kb[0], kb[1], ra)
    rows[ka], rows[kb] = new_a, new_b
    return replace(record, assignments=tuple(rows[(r.employee_id, r.slot.index)] for r in record.assignments))


def _state(record: ShiftRecord, start: int, end: int, posts: dict) -> ShiftRecord:
    lo, hi = sorted((int(start), int(end)))
    out = []
    for r in record.assignments:
        state = posts.get(r.displayed_assignment.label)
        if (state in ("seated", "rest") and lo <= r.slot.index <= hi
                and r.displayed_assignment.kind == K.POST):
            if state == "seated":
                r = replace(r, posture_or_mode=Posture.SEATED, fatigue_value=1, actual_work_time_value=1,
                            actual_rest_time_value=0, counts_for_continuous_work_restriction=True,
                            counts_as_meal_opportunity=False, counts_as_post_patrol_rest=False,
                            actual_post_or_work_type=Assignment(K.POST, r.displayed_assignment.label))
            else:
                r = replace(r, posture_or_mode=Posture.REST_LIKE, fatigue_value=0, actual_work_time_value=0,
                            actual_rest_time_value=1, counts_for_continuous_work_restriction=False,
                            counts_as_meal_opportunity=True, counts_as_post_patrol_rest=True,
                            actual_post_or_work_type=Assignment(K.REST, f"{r.displayed_assignment.label} 휴게성"))
        out.append(r)
    return replace(record, assignments=tuple(out))


def _fatigue(record: ShiftRecord, cell, value: int) -> ShiftRecord:
    key = (str(cell[0]), int(cell[1]))
    if int(value) not in (0, 1, 2):
        raise ValueError("피로도는 0~2 중에서 고를 수 있습니다.")
    out = []
    for r in record.assignments:
        if (r.employee_id, r.slot.index) == key:
            if r.displayed_assignment.kind == K.UNAVAILABLE:
                raise ValueError("근무불가(×) 칸은 피로도를 바꿀 수 없습니다.")
            r = replace(r, fatigue_value=int(value))
        out.append(r)
    return replace(record, assignments=tuple(out))


def add_state_edit(edits: list[dict], post: str, start: int, end: int, state: str) -> list[dict]:
    """포스트 운영 수정을 추가한다. 마지막에 적용한 범위가 그 포스트의 규칙이 된다 (2026-10-02 사용자 확정).

    같은 포스트의 이전 수정 중 새 범위와 겹치는 것은 통째로 지우고 새 범위로 바꾼다.
    예: I1 00~04시 휴게성 다음에 I1 00~03시 휴게성을 적용하면 I1 휴게성은 00~03시뿐(04시는 원래 계획).
    겹치지 않는 별도 범위(예: I1 22~23시 따로, 00~03시 따로)는 그대로 남는다.
    """
    lo, hi = sorted((int(start), int(end)))
    out = []
    for edit in edits:
        posts = edit.get("posts", {}) if edit.get("type") == "state" else {}
        if post not in posts:
            out.append(edit)
            continue
        old_lo, old_hi = sorted((int(edit["from"]), int(edit["to"])))
        if old_hi < lo or old_lo > hi:                      # 겹치지 않는 별도 범위는 유지
            out.append(edit)
            continue
        others = {p: s for p, s in posts.items() if p != post}
        if others:                                          # 같은 수정에 묶인 다른 포스트는 그대로
            out.append({**edit, "posts": others})
    out.append({"type": "state", "from": lo, "to": hi, "posts": {post: state}})
    return out


def cell_notes(edits: list[dict]) -> dict:
    """{(employee, slot): {"value": v, "note": text}} from fatigue edits (last wins)."""
    notes = {}
    for edit in edits:
        if edit.get("type") == "fatigue":
            notes[(str(edit["cell"][0]), int(edit["cell"][1]))] = {"value": int(edit["value"]),
                                                                   "note": edit.get("note", "")}
    return notes


def apply_edits(plan: ShiftRecord, edits: list[dict]) -> ShiftRecord:
    record = plan
    for edit in edits:
        if edit.get("type") == "fatigue":
            continue  # applied last, after every structural edit
        if edit.get("type") == "swap":
            record = _swap(record, edit["a"], edit["b"])
        elif edit.get("type") == "state":
            record = _state(record, edit["from"], edit["to"], edit.get("posts", {}))
        else:
            raise ValueError(f"알 수 없는 수정 항목: {edit.get('type')}")
    for (employee, slot), item in cell_notes(edits).items():
        record = _fatigue(record, (employee, slot), item["value"])
    return record


def describe_edit(edit: dict, names: dict) -> str:
    if edit.get("type") == "swap":
        (p1, t1), (p2, t2) = edit["a"], edit["b"]
        return f"{names.get(p1, p1)} {HOUR(t1)} ↔ {names.get(p2, p2)} {HOUR(t2)} 근무 교환"
    if edit.get("type") == "state":
        lo, hi = sorted((edit["from"], edit["to"]))
        parts = [f"{post} {'좌식' if state == 'seated' else '휴게성'}"
                 for post, state in edit.get("posts", {}).items() if state in ("seated", "rest")]
        return f"{HOUR(lo)}~{HOUR(hi)} 실제 운영: " + ", ".join(parts)
    if edit.get("type") == "fatigue":
        p, t = edit["cell"]
        note = f" — {edit['note']}" if edit.get("note") else ""
        return f"{names.get(p, p)} {HOUR(int(t))} 피로도 {edit['value']}로 변경{note}"
    return str(edit)


def changed_cells(plan: ShiftRecord, actual: ShiftRecord) -> set[tuple[str, int]]:
    a, b = _rows(plan), _rows(actual)
    return {key for key in a if a[key] != b.get(key)}


def actual_checks(record: ShiftRecord) -> list[dict]:
    """Rule outcomes from recorded accounting (history record, not a gate)."""
    names = {e.employee_id: e.name for e in record.context.employees}
    by = {}
    for r in record.assignments:
        by.setdefault(r.employee_id, [None] * 14)[r.slot.index] = r
    present = {a.employee_id: a for a in record.context.attendance if a.present}
    manager = next((a.employee_id for a in present.values() if a.acts_as_manager), None)
    found = []

    def add(rule, person, slots, text):
        found.append({"rule": rule, "person": names.get(person, person),
                      "time": f"{HOUR(slots[0])}~{HOUR(slots[-1])}" if len(slots) > 1 else HOUR(slots[0]),
                      "detail": text})

    for person, rows in by.items():
        counted = [bool(r and (r.counts_for_continuous_work_restriction
                               or r.actual_post_or_work_type.kind == K.PATROL)) for r in rows]
        seated = [bool(r and r.actual_work_time_value == 1 and r.posture_or_mode == Posture.SEATED) for r in rows]
        standing = [bool(r and r.actual_work_time_value == 1 and r.posture_or_mode == Posture.STANDING) for r in rows]
        for s in range(10):
            if all(counted[s:s + 5]):
                add("H-08", person, list(range(s, s + 5)), "5시간 연속 실제근무")
        for s in range(11):
            if all(counted[s:s + 4]) and not any(seated[s:s + 4]):
                add("H-08", person, list(range(s, s + 4)), "4시간 연속근무 중 좌식 없음")
        for s in range(12):
            gates = any(r and r.displayed_assignment.label in ("G2", "G3") for r in rows[11:14])
            if all(standing[s:s + 3]) and not (s == 11 and gates):
                add("H-06", person, list(range(s, s + 3)), "입식 3시간 연속")
        for t in (3, 4, 5, 7, 8, 9):
            r = rows[t]
            if r and r.actual_post_or_work_type.kind == K.PATROL:
                window = [rows[j] for j in (t + 1, t + 2)]
                if not any(w and w.actual_work_time_value == 0 and w.counts_as_post_patrol_rest for w in window):
                    add("H-11", person, [t], "순찰 뒤 2시간 안에 휴게 없음")
                if (standing[t - 1] and window[0] and window[0].actual_work_time_value == 1
                        and window[0].posture_or_mode != Posture.SEATED):
                    add("H-11", person, [t], "입식 → 순찰 → 입식")
        if person in present and any(present[person].is_available(t) for t in (0, 1, 2)):
            if not any(r and r.counts_as_meal_opportunity for r in rows[:3]):
                add("H-10", person, [0, 2], "18~20시 식사기회 없음")
    if manager:
        rows = by.get(manager, [None] * 14)
        if rows[11] and rows[11].actual_work_time_value != 0:
            add("8-1", manager, [11], "관리자 05시 휴게 아님")
        if (record.context.night_type in (NightType.N1, NightType.N3) and rows[13]
                and rows[13].actual_rest_time_value != 1):
            add("8-3", manager, [13], "관리자 07시 휴게 아님 (07시 일반근무자 4명이면 8-3-1 허용)")
    return found
