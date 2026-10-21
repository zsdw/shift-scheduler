"""Manual on-screen edits of a generated schedule (drag and drop in the UI).

Two operations, both of which leave the engine's accounting untouched:

* Cell swap (display only): two cells exchange what is *shown*. The recorded
  assignments, validation and Excel exports keep the solver's schedule.
* Person swap: two general workers exchange their display numbers. Each
  person's row (their actual assignments) stays with them; only the numbering
  and therefore the row order change.

LOCKed slots of an emergency re-optimization and unavailable cells can never
be moved, whatever the browser sends.
"""
from dataclasses import replace

from .models import AssignmentKind, post_operation
from .presentation import assignment_view, flexible_band
from .service import ServiceResult, calculate_all_stats

HOUR_LABELS = tuple(f"{(18 + t) % 24:02d}시" for t in range(14))
# 번호 칸 색: 주간 편성표와 같은 색 (day_shift.NUMBER_COLORS). 3번 빨간 계열·4번 노랑 (2026-10-06 사용자 요청)
SHEET_COLORS = {1: "70AD47", 2: "00B0F0", 3: "FF7C80", 4: "FFE699", 5: "DEEBF7", 6: "8FAADC"}


def sheet_meta(context) -> dict:
    """야간 편성표 모양(세로 시간 × 가로 포스트, 2026-10-06 사용자 요청) 머리글·번호·CP.

    표 컴포넌트는 같은 칸(사람·시간)을 이 정보로 다시 배치만 한다 (교환·기록·LOCK·반차는 그대로)."""
    import os
    from pathlib import Path
    day = context.shift_start_date
    names = {e.employee_id: e.name for e in context.employees}
    tokens, colors, heads = {}, {}, []
    present = sorted((a for a in context.attendance if a.present),
                     key=lambda a: (a.display_number is not None, a.display_number or 0))
    for a in present:
        token = str(a.display_number) if a.display_number is not None else "A"
        tokens[a.employee_id] = token
        colors[a.employee_id] = SHEET_COLORS.get(a.display_number, "FFFFFF")
        heads.append([a.employee_id, "통제A" if token == "A" and names[a.employee_id] == "통제"
                      else ("A" if token == "A" else token) + names[a.employee_id]])
    cp, shuttle = [""] * 14, [""] * 14
    try:                                            # CP: 엑셀 표준 형태(같은 인원) 우선 (2026-10-11 사용자 확정)
        from .cp_schedule import for_day, hourly, short
        store = Path(os.environ.get("NIGHT_SHIFT_HISTORY_DIR") or Path(__file__).resolve().parent.parent / "history")
        on = for_day(store, day, "night")
        if on:
            pattern = hourly(store, day, "night", on)
            cp, shuttle[13] = pattern["hours"], pattern["shuttle"]
            heads += [[f"cp{k}", f"CP{k}{short(v)}"] for k, v in sorted(on.items())]   # 명단 칸에 CP 이름도
    except Exception:
        pass
    return {"title": "야간 근무 편성표",
            "sub": f"{day.year}년 {day.month:02d}월 {day.day:02d}일 {'월화수목금토일'[day.weekday()]}요일 근무조 : A조",
            "operations": {post: [post_operation(context, post, t) for t in range(14)]
                           for post in ("G1", "L3", "I1", "G2", "G3")},
            "tokens": tokens, "colors": colors, "heads": heads, "cp": cp, "shuttle": shuttle,
            "hours": [f"{24 if t == 6 else (18 + t) % 24:02d}:00" for t in range(14)]}


def locked_through(result: ServiceResult) -> int:
    """Last LOCKed slot index of a re-optimized schedule, or -1."""
    info = result.rebalance_info
    return info.locked_through_index if info is not None else -1


def _row_map(result: ServiceResult):
    return {(row.employee_id, row.slot.index): row for row in result.record.assignments}


def _key(employee_id: str, slot: int) -> str:
    return f"{employee_id}|{slot}"


def cell_movable(result: ServiceResult, employee_id: str, slot: int) -> bool:
    row = _row_map(result).get((employee_id, slot))
    return (row is not None and slot > locked_through(result)
            and row.displayed_assignment.kind != AssignmentKind.UNAVAILABLE)


def swap_cells(result: ServiceResult, view: dict[str, str], source, target) -> dict[str, str]:
    """Return a new display map after swapping two cells (display only)."""
    (p1, t1), (p2, t2) = (str(source[0]), int(source[1])), (str(target[0]), int(target[1]))
    if (p1, t1) == (p2, t2):
        return dict(view)
    if not (cell_movable(result, p1, t1) and cell_movable(result, p2, t2)):
        raise ValueError("LOCK된 시간대나 근무불가 칸은 옮길 수 없습니다.")
    new_view = dict(view)
    a, b = _key(p1, t1), _key(p2, t2)
    new_view[a], new_view[b] = view.get(b, b), view.get(a, a)
    return {k: v for k, v in new_view.items() if k != v}


def person_movable(result: ServiceResult, employee_id: str) -> bool:
    person = result.employee_stats.get(employee_id)
    return person is not None and not person.is_manager and person.display_number is not None


def swap_person_numbers(result: ServiceResult, first: str, second: str) -> ServiceResult:
    """Exchange two general workers' display numbers; schedules stay with people."""
    if first == second:
        return result
    if not (person_movable(result, first) and person_movable(result, second)):
        raise ValueError("관리자나 번호가 없는 직원은 번호를 바꿀 수 없습니다.")
    numbers = {a.employee_id: a.display_number for a in result.context.attendance}
    numbers[first], numbers[second] = numbers[second], numbers[first]
    context = replace(result.context, attendance=tuple(
        replace(a, display_number=numbers[a.employee_id]) for a in result.context.attendance))
    record = replace(result.record, context=context)
    return replace(result, context=context,
                   solve_result=replace(result.solve_result, record=record),
                   employee_stats=calculate_all_stats(record))


def person_label(person) -> str:
    if person.is_manager and person.employee_id == "A":
        return "통제"
    prefix = person.display_number if person.display_number is not None else "A"
    return f"{prefix} {person.name}"


def grid_payload(result: ServiceResult, view: dict[str, str]) -> dict:
    """JSON payload for the drag-and-drop grid component."""
    rows = _row_map(result)
    lock = locked_through(result)
    people = sorted(result.employee_stats.values(),
                    key=lambda p: (not p.is_manager, p.display_number or 0))
    payload_rows = []
    for person in people:
        cells = []
        for t in range(14):
            key = _key(person.employee_id, t)
            source = view.get(key, key)
            source_id, source_slot = source.split("|")
            shown = rows.get((source_id, int(source_slot)))
            if shown is None:
                cells.append({"t": t, "label": "—", "notes": "", "color": "FFFFFF",
                              "locked": t <= lock, "movable": False, "edited": False})
                continue
            label, notes, color, _ = assignment_view(shown, result.context)
            cells.append({"t": t, "label": label, "notes": " · ".join(notes), "color": color,
                          "locked": t <= lock,
                          "movable": cell_movable(result, person.employee_id, t),
                          "edited": source != key})
        payload_rows.append({"id": person.employee_id, "label": person_label(person),
                             "movable": person_movable(result, person.employee_id),
                             "cells": cells})
    return {"hours": list(HOUR_LABELS), "rows": payload_rows, "band": flexible_band(result.context),
            "sheet": sheet_meta(result.context)}


def record_grid_payload(record, changed: set | None = None, selected_hours=(),
                        hour_click: bool = False, editable: bool = True, notes: dict | None = None,
                        cell_click: bool = False, selected_cell=None, locked_through: int = -1) -> dict:
    """Grid payload straight from a record (past actual-shift editing).

    Every available cell can be dragged (actual corrections); cells that differ
    from the confirmed plan are outlined red.
    """
    changed = changed or set()
    rows = {(r.employee_id, r.slot.index): r for r in record.assignments}
    names = {e.employee_id: e.name for e in record.context.employees}
    present = [a for a in record.context.attendance if a.present]
    present.sort(key=lambda a: (not a.acts_as_manager or a.display_number is not None,
                                a.display_number or 0))
    payload_rows = []
    for a in present:
        label = "통제" if a.acts_as_manager and a.display_number is None else f"{a.display_number} {names[a.employee_id]}"
        cells = []
        for t in range(14):
            row = rows.get((a.employee_id, t))
            if row is None:
                cells.append({"t": t, "label": "—", "notes": "", "color": "FFFFFF", "locked": t <= locked_through,
                              "movable": False, "edited": False, "changed": False})
                continue
            text, notes_text, color, _ = assignment_view(row, record.context)
            if (a.employee_id, t) in changed and row.actual_post_or_work_type.kind == AssignmentKind.POST \
                    and row.posture_or_mode is not None and row.actual_work_time_value == 1:
                notes_text = tuple(notes_text) + (("좌식",) if row.posture_or_mode.value == "seated" else ())
            if (a.employee_id, t) in changed and row.displayed_assignment.kind == AssignmentKind.POST \
                    and row.actual_rest_time_value == 1 and "휴게성" not in notes_text:
                notes_text = tuple(notes_text) + ("휴게성",)
            comment = (notes or {}).get((a.employee_id, t))
            cells.append({"t": t, "label": text, "notes": " · ".join(notes_text), "color": color,
                          "locked": t <= locked_through,
                          "movable": (editable and t > locked_through
                                      and row.displayed_assignment.kind != AssignmentKind.UNAVAILABLE),
                          "edited": False, "changed": (a.employee_id, t) in changed,
                          "fatigue_override": comment["value"] if comment else None,
                          "note": (f"피로도 {comment['value']}" + (f"\n{comment['note']}" if comment["note"] else ""))
                          if comment else ""})
        payload_rows.append({"id": a.employee_id, "label": label, "movable": False, "cells": cells})
    return {"hours": list(HOUR_LABELS), "rows": payload_rows,
            "selected_hours": list(selected_hours), "hour_click": hour_click,
            "cell_click": cell_click, "selected_cell": list(selected_cell) if selected_cell else None,
            "band": flexible_band(record.context), "sheet": sheet_meta(record.context)}


# ------------------------------------------------------------ real edits (pre-confirm)
RULE_HINTS = {
    "H-21": "연속 4시간 안에 같은 포스트를 세 번 설 수 없습니다",
    "H-22": "결원 0~1명 날에는 4시간 연속 근무를 할 수 없습니다(유도리 휴게성 칸은 쉼)",
    "8-10-2": "관리자(통제A·대행 준호)는 04시에 근무할 수 없습니다(결원 1명 날은 권장)",
    "15-0-대행": "통제 결근 날 대행 준호는 차단봉 설치·철수를 하지 않습니다(04시 I1 불가)",
    "대행준호-순찰앞뒤휴게": "통제 결근 날(결원 1명까지) 대행 준호는 순찰 앞뒤 2시간(총 4시간) 중 휴게가 2시간을 넘을 수 없습니다",
    "대행준호-최저피로도": "통제 결근 날 대행 준호 피로도는 각 일반근무자보다 1~2점 낮아야 합니다",
    "8-15": "통제A는 야간 전체 대기 표기를 두 번까지만 받을 수 있습니다",
    "8-14": "통제A는 04시를 제외한 시간에 I1을 최소 한 번 맡아야 합니다",
    "12-gap": "통제A를 제외한 출근자 사이의 대기 횟수 차이는 최대 한 번이어야 합니다",
    "12-required": "결원 2명인 시간을 제외하고 18시부터 05시까지 대기자가 최소 한 명 있어야 합니다",
    "12-block": "세 시간 연속 쉬는 구간에는 휴게 두 시간을 붙여 표시해야 합니다",
    "12-protected": "순찰 뒤 두 시간의 쉬는 칸은 휴게로 표시해야 합니다",
    "12-third": "순찰 뒤 세 번째 쉬는 칸은 대기로 표시해야 합니다",
    "16-next": "직전 출근 야간에 막타임 휴게를 받아 이번에는 받을 수 없습니다",
    "5-3-1": "다음날 평일·결원 2명 외에는 남문을 2시간 연속 맡을 수 없습니다",
    "H-02/§5": "필수 포스트 인원이 맞지 않게 됩니다",
    "§5": "남문 인원 구성이 맞지 않게 됩니다",
    "§14": "순찰 배치가 규칙과 맞지 않게 됩니다",
    "§14-1/14-4": "순찰 인원 배분이 규칙과 맞지 않게 됩니다",
    "§14-2": "순찰 인원 배분이 규칙과 맞지 않게 됩니다",
    "§14-3": "순찰 인원 배분이 규칙과 맞지 않게 됩니다",
    "§14-3-1": "순찰 인원 배분이 규칙과 맞지 않게 됩니다",
    "H-12": "관리자의 21시 상층 순찰이 깨집니다",
    "H-03": "초저녁 같은 포스트 연속 배치가 됩니다",
    "H-04": "같은 실제 업무가 3시간 연속됩니다",
    "H-05": "G1이 연속으로 배치됩니다",
    "H-06/H-07": "입식 근무가 3시간 연속됩니다",
    "H-07": "아침 같은 포스트 연속 표기가 됩니다",
    "H-08": "연속근무 제한(5시간 금지 / 4시간이면 좌식 1시간)을 넘습니다",
    "H-10": "18~20시 식사 기회가 없어집니다",
    "H-11": "순찰 뒤 휴게가 보장되지 않습니다",
    "H-11-2": "순찰 뒤 휴게가 보장되지 않습니다",
    "H-11-immediate-recovery": "입식 → 순찰 → 입식이 됩니다",
    "H-14": "18~20시 남문 배치 제한을 넘습니다",
    "H-15": "관리자와의 실근무 차이 2시간 제한을 넘습니다",
    "8-4-2": "관리자 피로도 격차 기준을 넘습니다",
    "H-16": "보안실 대기 인원이 맞지 않게 됩니다",
    "§8-1": "관리자 05시 휴게가 깨집니다",
    "§8-2": "관리자 06시 G2가 깨집니다",
    "§8-3": "관리자 07시 규칙이 깨집니다",
    "§8-3-1": "관리자 07시 규칙이 깨집니다",
    "§6": "관리자 18~19시 L3 고정이 깨집니다",
    "§10/§11": "차단봉 설치·철수 규칙이 깨집니다",
    "§10-4": "차단봉 설치 인원 구성이 맞지 않게 됩니다",
    "§15-2": "같은 사람이 설치와 철수를 모두 하게 됩니다",
    "user-A-00-05": "관리자 00~05시 연속근무 제한을 넘습니다",
    "user-display": "순찰 뒤 휴게 표기가 맞지 않게 됩니다",
    "handover": "관리자 대행 교대 전후로 준호의 연속근무·휴게 제한을 넘습니다",
}


def explain_errors(errors, context) -> list[str]:
    """Short Korean explanation per violated hard rule (deduplicated)."""
    names = {e.employee_id: e.name for e in context.employees}
    messages = []
    for error in errors:
        rule = str(error.get("rule", ""))
        hint = RULE_HINTS.get(rule, "하드룰을 만족하지 못합니다")
        detail = str(error.get("detail", ""))
        who = next((names[token.split("/")[0]] for token in detail.replace(":", " ").split()
                    if token.split("/")[0] in names), None)
        messages.append(f"[{rule}] {who + ': ' if who else ''}{hint}")
    return list(dict.fromkeys(messages))


def swap_schedule_cells(result: ServiceResult, source, target):
    """Really swap two cells of an unconfirmed schedule, only if every hard rule holds.

    Returns (new_result, []) on success or (None, explanations) when refused.
    """
    from .actual_edit import apply_edits
    from .service import revalidate
    (p1, t1), (p2, t2) = (str(source[0]), int(source[1])), (str(target[0]), int(target[1]))
    if (p1, t1) == (p2, t2):
        return result, []
    if not (cell_movable(result, p1, t1) and cell_movable(result, p2, t2)):
        return None, ["LOCK된 시간대나 근무불가(×) 칸은 옮길 수 없습니다."]
    try:
        record = apply_edits(result.record, [{"type": "swap", "a": [p1, t1], "b": [p2, t2]}])
    except ValueError as exc:
        return None, [str(exc)]
    checked = revalidate(result, record)
    if checked.validation_errors:
        return None, explain_errors(checked.validation_errors, record.context)
    return checked, []


def swap_person_schedules(result: ServiceResult, first: str, second: str):
    """Swap two people's places: the schedule rows stay where they are.

    Person X takes Y's number and Y's whole schedule (and vice versa). This is
    a real edit, so it is refused unless every hard rule still holds.
    Returns (new_result, []) or (None, reasons).
    """
    from .service import revalidate
    if first == second:
        return result, []
    if not (person_movable(result, first) and person_movable(result, second)):
        return None, ["관리자(통제)나 번호가 없는 직원은 자리를 바꿀 수 없습니다."]
    context = result.context
    handover = context.manager_handover
    if handover and handover[1] in (first, second):
        return None, ["관리자 대행 중인 준호는 자리를 바꿀 수 없습니다."]
    attendance = {a.employee_id: a for a in context.attendance}
    if attendance[first].available_slot_indices != attendance[second].available_slot_indices:
        return None, ["근무 가능 시간이 다른 사람끼리는 자리를 바꿀 수 없습니다 (반차·이탈자)."]
    rows = _row_map(result)
    lock = locked_through(result)
    if any(rows[(first, t)] != replace(rows[(second, t)], employee_id=first) for t in range(lock + 1)):
        return None, ["LOCK된 시간대에 이미 한 근무가 서로 달라서 자리를 바꿀 수 없습니다."]
    other = {first: second, second: first}
    numbers = {a.employee_id: a.display_number for a in context.attendance}
    numbers[first], numbers[second] = numbers[second], numbers[first]
    new_context = replace(context, attendance=tuple(
        replace(a, display_number=numbers[a.employee_id]) for a in context.attendance))
    record = replace(result.record, context=new_context, assignments=tuple(
        replace(r, employee_id=other[r.employee_id]) if r.employee_id in other else r
        for r in result.record.assignments))
    checked = revalidate(result, record)
    if checked.validation_errors:
        return None, explain_errors(checked.validation_errors, new_context)
    return checked, []
