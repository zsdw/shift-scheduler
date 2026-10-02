"""Streamlit front end for the v2.20 night-shift service."""

from __future__ import annotations

from dataclasses import asdict, replace
from datetime import date
from html import escape
import json
from pathlib import Path
import random
from time import perf_counter

import pandas as pd
import streamlit as st
import streamlit.components.v1 as components

# Streamlit reruns app.py inside the existing server process.  Reload the local
# dependency graph once when an already-running v2.13 server sees the v2.15
# model, so the desktop user does not have to kill the server manually.
import importlib
import night_shift.models as _models_module
import night_shift.service as _service_module

if (not hasattr(_models_module.AssignmentKind, "UNAVAILABLE")
        or not hasattr(_models_module, "DEFAULT_POST_OPERATIONS")      # 유도리 포스트별 운영 (2026-10-02)
        or getattr(_service_module, "SERVICE_API_VERSION", None) != "2.21.11"):
    import night_shift.common as _common_module
    import night_shift.profiles as _profiles_module
    import night_shift.preferences as _preferences_module
    import night_shift.soft_history as _soft_history_module
    import night_shift.solver as _solver_module
    import night_shift.validator as _validator_module
    import night_shift.presentation as _presentation_module
    import night_shift.analysis as _analysis_module
    import night_shift.excel_exporter as _excel_module
    import night_shift.field_exporter as _field_module

    for _module in (_models_module, _common_module, _profiles_module, _preferences_module, _soft_history_module,
                    _solver_module, _validator_module, _service_module,
                    _presentation_module, _analysis_module, _excel_module, _field_module):
        importlib.reload(_module)

# Small UI helper modules change often; reload them on every run so an
# already-running server never serves a stale copy (e.g. a missing function).
import sys as _sys
import night_shift.schedule_edit as _schedule_edit_module
import night_shift.history_store as _history_store_module
import night_shift.actual_edit as _actual_edit_module
import night_shift.balance_notes as _balance_notes_module
import night_shift.calendar_info as _calendar_info_module
import night_shift.day_shift as _day_shift_module
for _module in (_history_store_module, _actual_edit_module, _schedule_edit_module,
                _balance_notes_module, _calendar_info_module, _day_shift_module):
    importlib.reload(_module)
# history_ui imports from the modules above, so load it only after they are fresh.
if "history_ui" in _sys.modules:
    importlib.reload(_sys.modules["history_ui"])
if "day_ui" in _sys.modules:
    importlib.reload(_sys.modules["day_ui"])

from night_shift.models import (AssignmentKind, DEFAULT_POST_OPERATIONS, Mode, NightType,
                                POST_OPERATION_CHOICES)
from night_shift.analysis import analyze_soft_rules, validation_rows
from night_shift.presentation import (
    PATROL_LABELS,
    POSTURE_LABELS,
    assignment_view,
    flexible_band,
    run_text,
)
from night_shift.service import (
    HistorySelection,
    ServiceResult,
    ShiftRequest,
    SolveOptions,
    StaffInput,
    run_reoptimization,
    run_schedule,
)
from night_shift.soft_history import TRACKED_SOFT_RULES
from night_shift.schedule_edit import explain_errors, grid_payload, swap_person_schedules, swap_schedule_cells
from night_shift.service import calculate_all_stats, prepare_engine_inputs, revalidate, seat_form_record
from night_shift.balance_notes import balance_reasons, monthly_direction

from history_ui import (
    confirm_button, history_caption, render_history_editor, render_monthly, render_trash, saved_dates_caption,
    saved_status, day_store_dir, duty_frame, duty_grid_html,
    store_dir, stored_before,
)
from night_shift import history_store as _history_store
from day_ui import render_day_page
from night_shift.calendar_info import (
    HOLIDAYS, PATTERN_LABELS, PATTERN_START, holiday_name, is_off_day, next_night, night_type_for, shift_kind,
)

_DRAG_GRID = components.declare_component(
    "drag_schedule", path=str(Path(__file__).resolve().parent / "night_shift" / "drag_grid"))
_CALENDAR = components.declare_component(
    "shift_calendar", path=str(Path(__file__).resolve().parent / "night_shift" / "calendar_picker"))


ROSTER = (("1", "만년"), ("2", "원종"), ("3", "제욱"),
          ("4", "광희"), ("5", "성호"), ("6", "준호"))
ABSENCE_OPTIONS = ("연차", "전반부 반차 (01시 출근)", "후반부 반차 (01시 퇴근)")
NIGHT_STATUSES = ("출근",) + ABSENCE_OPTIONS
HISTORY_LABELS = {
    "fatigue_value": "누적 피로도", "standing": "누적 입식", "seated": "누적 좌식",
    "actual_work_time_value": "누적 실근무", "actual_rest_time_value": "누적 실휴게",
    "patrol_fatigue": "누적 순찰 피로도",
}
NIGHT_TYPE_LABELS = {
    "N1": "N1 (평일 → 평일)", "N2": "N2 (평일 → 공휴일)",
    "N3": "N3 (공휴일 → 평일)", "N4": "N4 (공휴일 → 공휴일)",
}


def night_type_label(value) -> str:
    key = getattr(value, "value", value)
    return NIGHT_TYPE_LABELS.get(str(key), str(key))


def actual_state_label(row) -> str:
    """UI label from the accounting fields already recorded by the engine."""
    if row.displayed_assignment.kind == AssignmentKind.UNAVAILABLE:
        return "×"
    if row.actual_post_or_work_type.kind == AssignmentKind.PATROL:
        return PATROL_LABELS.get(row.actual_post_or_work_type.label,
                                 row.actual_post_or_work_type.label)
    if row.actual_rest_time_value == 1:
        return "보안실 대기" if row.displayed_assignment.kind == AssignmentKind.SECURITY_STANDBY else "휴게성"
    if row.barrier_install_flag:
        return "차단봉 설치"
    if row.barrier_remove_flag:
        return "차단봉 철수"
    return row.actual_post_or_work_type.label


def friendly_exception_message(exc: Exception, operation: str) -> str:
    """Keep Python exception names and internal object details out of operator UI."""
    if isinstance(exc, ValueError):
        return f"{operation} 입력을 확인해 주세요: {exc}"
    if isinstance(exc, AttributeError):
        return (f"{operation}에 필요한 내부 정보가 연결되지 않았습니다. "
                "화면을 새로고침한 뒤 다시 시도해 주세요. 계속되면 프로그램 점검이 필요합니다.")
    return (f"{operation} 중 프로그램 내부 문제가 발생했습니다. 기존 근무표는 유지됩니다. "
            "화면을 새로고침한 뒤 다시 시도해 주세요.")


def solver_failure_message(status: str, operation: str = "근무표 생성") -> str:
    if status == "INFEASIBLE":
        return f"{operation} 불가: 현재 인원과 조건으로 모든 필수규칙을 만족하는 해가 없습니다."
    if status == "UNKNOWN":
        return (f"{operation} 미완료: 제한시간 안에 해를 찾지 못했습니다. "
                "해가 없다고 확정된 것은 아니므로 제한시간을 늘려 다시 시도해 주세요.")
    if status == "MODEL_INVALID":
        return f"{operation} 불가: 계산 모델에 내부 문제가 있습니다. 프로그램 점검이 필요합니다."
    return f"{operation}을 완료하지 못했습니다. 현재 상태: {status}"


def random_display_numbers(a_present: bool, presence: dict[str, bool]) -> dict[str, int]:
    """Assign visible 1..N numbers independently of stable employee IDs."""
    present_ids = [employee_id for employee_id, _ in ROSTER
                   if (employee_id == "6" and not a_present) or presence.get(employee_id, False)]
    numbers = list(range(1, len(present_ids) + 1))
    random.SystemRandom().shuffle(numbers)
    return dict(zip(present_ids, numbers))


def staff_for_input(a_present: bool, presence: dict[str, bool],
                    display_numbers: dict[str, int] | None = None,
                    absence_types: dict[str, str] | None = None) -> tuple[StaffInput, ...]:
    # The fallback keeps direct service/UI tests backwards-compatible. The app
    # always supplies a randomized mapping for a generated plan.
    visible_numbers = display_numbers or {employee_id: int(employee_id) for employee_id, _ in ROSTER}
    staff = [StaffInput("A", "통제", a_present, False, None, a_present)]
    absence_types = absence_types or {}
    for employee_id, name in ROSTER:
        is_proxy = employee_id == "6" and not a_present
        status = "출근" if presence[employee_id] or is_proxy else absence_types.get(employee_id, "연차")
        available_slots = (None if status == "출근" else
                           tuple(range(7, 14)) if status.startswith("전반부") else
                           tuple(range(0, 7)) if status.startswith("후반부") else ())
        present = status != "연차"
        staff.append(StaffInput(employee_id, name, present, not is_proxy,
                                visible_numbers.get(employee_id), is_proxy, available_slots))
    return tuple(staff)


NIGHT_HOURS = tuple(f"{(18 + t) % 24:02d}시" for t in range(14))
OPERATION_POSTS = ("I1", "G1", "L3", "G2", "G3")           # G2·G3 = 남문 (18~20시, 06~07시 운영)
OPERATION_STATES = {"휴게성": "rest", "좌식": "seated"}


def flexible_operations_input(slot):
    """유도리 포스트별 운영 (사용자 지정). 룰북 기본(I1 00~03시 휴게성)에서 시작해 고치거나 줄을 더한다.

    사이드바는 좁아 본문 위쪽(slot)에 그린다. Returns None(룰북 기본 그대로) 또는 ((post, from, to, state), ...).
    """
    with slot, st.expander("🌙 유도리 포스트별 운영 — 생성 전에 정하기", expanded=False):
        st.caption("어느 포스트를 몇 시~몇 시에 휴게성·좌식으로 운영할지 정합니다. '끝'은 그렇게 운영하는 마지막 "
                   "근무투입시간입니다(예: 00시~03시 = 00·01·02·03시 네 칸). 휴게성 칸도 표에는 사람이 "
                   "배정되고 피로도 0·실휴게 1로 계산해 밸런스를 맞춥니다(룰북 10-1·10-2). "
                   "남문(G2·G3)은 휴게성만, G1·L3는 좌식만, I1은 둘 다 고를 수 있습니다. "
                   "20시 차단봉 설치(I1·남문 G2)와 04시 I1 철수 칸은 룰북대로 둡니다. 줄을 지우면 그 설정이 빠집니다.")
        default = pd.DataFrame([{"포스트": "I1", "시작": "00시", "끝": "03시", "운영": "휴게성"}])
        edited = st.data_editor(
            default, num_rows="dynamic", hide_index=True, width="stretch", key="flexible_operations",
            column_config={
                "포스트": st.column_config.SelectboxColumn(options=OPERATION_POSTS, required=True),
                "시작": st.column_config.SelectboxColumn(options=NIGHT_HOURS, required=True),
                "끝": st.column_config.SelectboxColumn("끝 (근무투입시간)", options=NIGHT_HOURS, required=True),
                "운영": st.column_config.SelectboxColumn(options=tuple(OPERATION_STATES), required=True)})
        operations, problems = [], []
        for _, row in edited.iterrows():
            if not row["포스트"] or not row["시작"] or not row["끝"] or not row["운영"]:
                continue
            post, state = row["포스트"], OPERATION_STATES[row["운영"]]
            lo, hi = NIGHT_HOURS.index(row["시작"]), NIGHT_HOURS.index(row["끝"])
            if lo > hi:
                problems.append(f"{post}: 시작({row['시작']})이 끝({row['끝']})보다 늦습니다 (18시→07시 순서).")
            elif state not in POST_OPERATION_CHOICES[post]:
                problems.append(f"{post}: {row['운영']} 운영은 고를 수 없습니다.")
            else:
                operations.append((post, lo, hi, state))
        for problem in problems:
            st.error(problem)
        operations = tuple(operations)
        if operations == DEFAULT_POST_OPERATIONS and not problems:
            st.caption("룰북 기본 유도리와 같습니다.")
            return None
        return operations


def night_known_presence(a_present: bool, statuses: dict[str, str]) -> dict[str, bool]:
    """표시번호를 받을 사람: 출근·반차(일부 근무)는 포함, 연차는 제외. A 결근이면 준호(대행)는 항상 포함."""
    known = {employee_id: statuses.get(employee_id, "출근") != "연차" for employee_id, _ in ROSTER}
    if not a_present:
        known["6"] = True
    return known


def rotate_display_numbers() -> None:
    a_present = st.session_state.get("manager_state", "A 출근") == "A 출근"
    presence = night_known_presence(a_present, st.session_state.get("night_statuses", {}))
    st.session_state["display_numbers"] = random_display_numbers(a_present, presence)


def person_ui_label(person) -> str:
    if person.is_manager and person.employee_id == "A":
        return "통제"
    prefix = person.display_number if person.display_number is not None else "A"
    return f"{prefix} {person.name}"


def condition_signature(request: ShiftRequest, history: HistorySelection,
                        options: SolveOptions) -> str:
    """Ignore visible number permutations when deciding whether inputs changed."""
    normalized_staff = tuple(replace(person, display_number=None) for person in request.staff)
    normalized_request = replace(request, staff=normalized_staff)
    return signature_for(normalized_request, history,
                         replace(options, exclude_assignments=None, locked_assignments=None))


def exclusion_payload(result: ServiceResult) -> tuple[dict, ...]:
    """Serialize one schedule without any display-number or row-order identity."""
    if result.record is None:
        return ()
    return tuple({
        "employee_id": row.employee_id,
        "slot": {"index": row.slot.index},
        "displayed_assignment": {
            "kind": row.displayed_assignment.kind.value,
            "label": row.displayed_assignment.label,
        },
        "actual_post_or_work_type": {
            "kind": row.actual_post_or_work_type.kind.value,
            "label": row.actual_post_or_work_type.label,
        },
        "posture_or_mode": row.posture_or_mode.value if row.posture_or_mode else None,
        "actual_work_time_value": row.actual_work_time_value,
        "actual_rest_time_value": row.actual_rest_time_value,
        "fatigue_value": row.fatigue_value,
        "counts_for_continuous_work_restriction": row.counts_for_continuous_work_restriction,
        "barrier_install_flag": row.barrier_install_flag,
        "barrier_remove_flag": row.barrier_remove_flag,
    } for row in seat_form_record(result.record).assignments)


def exclusion_payloads(results: list[ServiceResult]) -> tuple[tuple[dict, ...], ...]:
    """Return every valid prior name-by-slot schedule as a solver no-good set."""
    return tuple(payload for item in results if (payload := exclusion_payload(item)))


def signature_for(request: ShiftRequest, history: HistorySelection, options: SolveOptions) -> str:
    return json.dumps((asdict(request), asdict(history), asdict(options)),
                      ensure_ascii=False, sort_keys=True, default=str)


def history_inputs(general: tuple[StaffInput, ...], present: tuple[StaffInput, ...],
                   shift_date: date | None = None) -> HistorySelection:
    has_stored = bool(shift_date and stored_before(shift_date))
    modes = (("저장된 실제 이력",) if has_stored else ()) + ("이력 없음", "누적값 직접 입력")
    mode = st.radio("과거 이력", modes, horizontal=True,
                    help="'저장된 실제 이력'은 확정 저장된 근무표의 실제 근무(최근 4회, 6:4)를 반영합니다. "
                         "'이력 없음'은 과거 회차를 참조하지 않는다는 명시적 선택입니다.")
    if mode == "저장된 실제 이력":
        st.caption(history_caption(shift_date))
        return _history_store.history_selection(_history_store_path(), shift_date)
    if mode == "이력 없음":
        return HistorySelection()

    st.caption("직접 입력한 값은 확정된 실제 근무표가 아니라 **가정 누적값**으로 전달됩니다. 실제 근무표 파일 불러오기는 아직 지원하지 않습니다.")
    general_ids = tuple(p.employee_id for p in general)
    names = {p.employee_id: p.name for p in present}
    summary_rows = [{"ID": p.employee_id, "이름": p.name, "과거 출근 횟수": 0,
                     **{label: 0 for label in HISTORY_LABELS.values()}} for p in general]
    summary = st.data_editor(
        pd.DataFrame(summary_rows), hide_index=True, width="stretch",
        disabled=("ID", "이름"), num_rows="fixed", key=f"history_summary_{'_'.join(general_ids)}",
        column_config={"과거 출근 횟수": st.column_config.NumberColumn(min_value=0, step=1),
                       **{label: st.column_config.NumberColumn(min_value=0, step=1)
                          for label in HISTORY_LABELS.values()}},
    )
    assumed_nights = {str(row["ID"]): int(row["과거 출근 횟수"]) for _, row in summary.iterrows()}
    assumed_totals = {
        key: {str(row["ID"]): float(row[label]) for _, row in summary.iterrows()}
        for key, label in HISTORY_LABELS.items()
    }

    choices = [p.employee_id for p in present]
    format_person = lambda employee_id: f"{employee_id} {names[employee_id]}"
    with st.expander("직전 근무 담당자와 soft debt (선택)"):
        st.caption("모르면 빈칸으로 두세요. 선택한 ID만 서비스 이력 입력으로 전달됩니다.")
        prior_install = tuple(st.multiselect("직전 차단봉 설치", choices, format_func=format_person))
        prior_remove = tuple(st.multiselect("직전 차단봉 철수", choices, format_func=format_person))
        prior_last_rest = tuple(st.multiselect("직전 07시 실휴게자", general_ids, format_func=format_person))
        prior_patrol_exclusion = tuple(st.multiselect("직전 순찰 제외자", general_ids, format_func=format_person))
        debt_rows = [{"ID": p.employee_id, "이름": p.name,
                      **{rule: 0 for rule in TRACKED_SOFT_RULES}} for p in present]
        debt_table = st.data_editor(
            pd.DataFrame(debt_rows), hide_index=True, width="stretch",
            disabled=("ID", "이름"), num_rows="fixed", key=f"soft_debt_{'_'.join(choices)}",
            column_config={rule: st.column_config.NumberColumn(min_value=0, step=1)
                           for rule in TRACKED_SOFT_RULES},
        )
    soft_debt = {rule: {str(row["ID"]): int(row[rule]) for _, row in debt_table.iterrows()
                        if int(row[rule]) > 0} for rule in TRACKED_SOFT_RULES}
    soft_debt = {rule: values for rule, values in soft_debt.items() if values}
    return HistorySelection(
        assumed_totals=assumed_totals, assumed_nights=assumed_nights,
        previous_install_ids=prior_install, previous_remove_ids=prior_remove,
        previous_last_rest_ids=prior_last_rest,
        previous_patrol_exclusion_ids=prior_patrol_exclusion,
        soft_debt=soft_debt or None,
    )


def _history_store_path():
    from history_ui import store_dir
    return store_dir()


def schedule_html(result: ServiceResult) -> str:
    """Present recorded assignments; all accounting stays in ServiceResult."""
    record = result.record
    assert record is not None
    slots = sorted({row.slot for row in record.assignments}, key=lambda slot: slot.index)
    rows = {(row.employee_id, row.slot.index): row for row in record.assignments}
    people = sorted(result.employee_stats.values(), key=lambda p: (not p.is_manager, p.display_number or 0))
    band = flexible_band(record.context)

    def band_style(t: int, top: bool = False, bottom: bool = False) -> str:
        if not band or not band[0] <= t <= band[1]:
            return ""
        edge = "3px solid #0f172a"
        return ((f"border-left:{edge};" if t == band[0] else "") + (f"border-right:{edge};" if t == band[1] else "")
                + (f"border-top:{edge};" if top else "") + (f"border-bottom:{edge};" if bottom else ""))
    # 밝은 칸에는 글자색을 직접 지정 (다크모드에서 흰 글자가 상속돼 안 보이던 문제)
    head = ("height:40px;padding:4px;border:1px solid #ddd;text-align:center;vertical-align:middle;background:#fff;"
            "color:#111827;white-space:nowrap")
    parts = ["<div style='overflow-x:auto'><table style='border-collapse:collapse;table-layout:fixed;min-width:1150px;width:100%;font-size:0.82rem'>",
             f"<colgroup><col style='width:92px'>{''.join('<col>' for _ in slots)}</colgroup>",
             f"<thead><tr><th style='position:sticky;left:0;z-index:1;{head}'>직원</th>"]
    parts += [f"<th style='{head};{band_style(slot.index, top=True)}'>{slot.hour:02d}시</th>" for slot in slots]
    parts.append("</tr></thead><tbody>")
    for person_index, person in enumerate(people):
        last = person_index == len(people) - 1
        title = person_ui_label(person)
        parts.append(f"<tr><th style='position:sticky;left:0;{head}'>{escape(title)}</th>")
        for slot in slots:
            row = rows.get((person.employee_id, slot.index))
            if row is None:
                parts.append("<td style='border:1px solid #ddd'>—</td>")
                continue
            label, notes, color, _ = assignment_view(row, record.context)
            detail = ("<div style='font-size:.68rem;line-height:1.1;color:#334155;margin-top:2px'>"
                      + escape(" · ".join(notes)) + "</div>") if notes else ""
            parts.append(f"<td style='background:#{color};color:#111827;height:58px;text-align:center;vertical-align:middle;padding:2px;"
                         f"border:1px solid #fff;overflow:hidden;{band_style(slot.index, bottom=last)}'>"
                         f"<div style='font-size:.95rem;font-weight:600'>"
                         f"{escape(label)}</div>{detail}</td>")
        parts.append("</tr>")
    parts.append("</tbody></table></div>")
    return "".join(parts)


NIGHT_HALF_LEAVE_SLOT = 7          # 후반부 반차 = 01시 퇴근


def _night_leavers(index: int, result: ServiceResult) -> set[str]:
    """이 표까지 쌓인 긴급 반차·이탈자 (연쇄 재편성 포함)."""
    out, params, seen = set(), st.session_state.get("rebalance_params", {}), set()
    results = st.session_state.get("schedule_results", [])
    while index is not None and index not in seen and 0 <= index < len(results):
        seen.add(index)
        info = results[index].rebalance_info
        if info is None:
            break
        out.add(info.unavailable_employee_id)
        index = params.get(index, {}).get("source")
    if result.rebalance_info:
        out.add(result.rebalance_info.unavailable_employee_id)
    return out


def _night_steps_html(lock: int | None) -> str:
    hour = lambda t: f"{(18 + t) % 24:02d}시"  # noqa: E731
    if lock is None:
        items = [("now", "① 긴급 반차·이탈: 위쪽 파란 시간 칸에서 이미 지나간(진행 중) 마지막 시간을 누르세요"),
                 ("", "② 빠지는 사람 이름 누르기"), ("", "③ 재편성표가 후보에 추가됨")]
    else:
        items = [("done", f"① {hour(lock)}까지 LOCK ✓ (같은 시간을 다시 누르면 취소)"),
                 ("now", "② 빠지는 사람의 이름(노란 칸)을 누르세요"), ("", "③ 재편성표가 후보에 추가됨")]
    return "<div class='steps'>" + "".join(f"<span class='{c}'>{escape(t)}</span>" for c, t in items) + "</div>"


def render_editable_schedule(index: int, result: ServiceResult, on_leave=None) -> None:
    """Drag and drop before confirming: real, hard-rule-checked edits.

    on_leave(start, employee_id, event_label): 긴급 반차·이탈 재편성 (주간과 같은 방식 — 표의 시간 칸을 눌러
    LOCK 빗금, 이름을 눌러 반차·이탈 선택).
    """
    originals = st.session_state.setdefault("generated_originals", {})
    original = originals.get(index)
    changed = set()
    if original is not None:
        now = {(r.employee_id, r.slot.index): r for r in result.record.assignments}
        changed = {(r.employee_id, r.slot.index) for r in original.assignments
                   if now.get((r.employee_id, r.slot.index)) != r}
    hint_bar(("✋ 칸 끌기 → 근무 교환", "✋ 이름 끌기 → 자리 교환", "🚫 규칙 위반이면 이유 표시 후 취소",
              "빗금 = LOCK"))
    payload = grid_payload(result, {})
    for row in payload["rows"]:
        for cell in row["cells"]:
            cell["changed"] = (row["id"], cell["t"]) in changed
    lock_key = f"night_lock_{index}"
    lock, menus = st.session_state.get(lock_key), {}
    if on_leave is not None:
        info = result.rebalance_info
        floor = info.locked_through_index + 1 if info is not None else 0
        lock_hours = list(range(floor, 13))              # 07시는 LOCK 뒤에 남는 시간이 없어 제외
        if lock not in lock_hours:
            lock = st.session_state[lock_key] = None
        leavers = _night_leavers(index, result)
        handover = result.context.manager_handover
        eligible = {p.employee_id for p in result.employee_stats.values()
                    if (not p.is_manager or (p.employee_id == "A" and not handover))
                    and not (handover and p.employee_id == handover[1])
                    and p.employee_id not in leavers}
        if lock is not None:
            start = lock + 1
            hour = f"{(18 + start) % 24:02d}시"
            for employee_id in eligible:
                menus[employee_id] = ([{"label": "후반부 반차 (01시 퇴근)", "value": "half"}]
                                      if start <= NIGHT_HALF_LEAVE_SLOT else [])
                menus[employee_id].append({"label": f"긴급 이탈 ({hour}부터)", "value": "leave"})
        for row in payload["rows"]:
            row["leaver"] = row["id"] in leavers
            if lock is not None:                          # 이름 선택 중에는 끌기 끔
                row["movable"] = False
                row["pick"] = row["id"] in eligible
                row["off"] = not row["pick"]
                for cell in row["cells"]:
                    cell["movable"] = False
        payload.update(lock_hours=lock_hours, pending_lock=lock, menus=menus, steps_html=_night_steps_html(lock))
    event = _DRAG_GRID(data=payload, key=f"drag_grid_{index}", default=None)
    # 표 컴포넌트 밖에서 같은 동작을 요청하는 길 (화면 테스트용): {"kind": "lockhour"|"leave", ...}
    queued = st.session_state.pop(f"night_leave_request_{index}", None)
    if queued:
        event = {**queued, "nonce": f"queued-{index}-{perf_counter()}"}
    fresh = isinstance(event, dict) and event.get("nonce") and event.get("nonce") != st.session_state.get("drag_nonce")
    if fresh and on_leave is not None and event.get("kind") in ("lockhour", "leave"):
        st.session_state["drag_nonce"] = event["nonce"]
        fresh = False
        if event["kind"] == "lockhour":
            t = int(event["t"])
            st.session_state[lock_key] = None if lock == t else t
            st.rerun()
        if lock is not None and event.get("pid") in menus:
            start = lock + 1
            half = event.get("choice") == "half" and start <= NIGHT_HALF_LEAVE_SLOT
            st.session_state[lock_key] = None
            on_leave(start, str(event["pid"]), "후반부 반차 (01시 퇴근)" if half else "긴급 이탈 (선택 시간부터)")
    if fresh:
        st.session_state["drag_nonce"] = event["nonce"]
        results = list(st.session_state.get("schedule_results", []))
        try:
            if event.get("kind") == "cell":
                updated, reasons = swap_schedule_cells(result, event["source"], event["target"])
                if updated is None:
                    st.session_state["drag_rejection"] = reasons
                else:
                    originals.setdefault(index, result.record)
                    results[index] = updated
            elif event.get("kind") == "person":
                updated, reasons = swap_person_schedules(result, str(event["source"]), str(event["target"]))
                if updated is None:
                    st.session_state["drag_rejection"] = reasons
                else:
                    originals.setdefault(index, result.record)
                    results[index] = updated
            st.session_state["schedule_results"] = results
        except (ValueError, KeyError, IndexError, TypeError) as exc:
            st.session_state["drag_rejection"] = [str(exc) if isinstance(exc, ValueError) else "옮길 수 없는 위치입니다."]
        st.rerun()
    reasons = st.session_state.pop("drag_rejection", None)
    if reasons:
        st.error("이 변경은 적용할 수 없습니다:\n\n" + "\n".join(f"- {r}" for r in reasons))
    if changed:
        st.caption(f"생성 원본과 달라진 칸 {len(changed)}개 (빨간 테두리). 모든 하드룰 검증을 통과한 상태입니다.")
        st.markdown("**수정 반영 요약** (생성 원본 대비 · 요약 정보 탭에도 같은 표시가 나옵니다)")
        render_summary_table(result, heading=False, baseline=calculate_all_stats(original),
                             key=f"edit_summary_cols_{index}")
        if st.button("생성 원본으로 되돌리기", key=f"reset_edit_{index}"):
            results = list(st.session_state.get("schedule_results", []))
            results[index] = revalidate(result, originals.pop(index))
            st.session_state["schedule_results"] = results
            st.rerun()


def render_summary(result: ServiceResult, baseline: dict | None = None) -> None:
    render_summary_table(result, baseline=baseline)
    render_summary_detail(result, "summary_employee_id")


SUMMARY_COLUMNS = (
    ("실근무", "actual_work_time_value", ""), ("실휴게", "actual_rest_time_value", ""),
    ("피로도", "fatigue_value", ""), ("입식", "standing", ""), ("좌식", "seated", ""),
    ("순찰", "patrol_count", ""), ("표시 포스트", "displayed_post_total", ""),
    ("가용시간", "available_time", ""), ("근무부담률", "workload_rate", "%"),
    ("실제 업무 연속시간", "max_actual_work_run", "시간"),
    ("연속근무 제한 적용시간", "max_rule_work_run", "시간"),
    ("최대 연속 실휴게", "max_rest_run", "시간"),
)


def _summary_value(p, attr):
    value = getattr(p, attr)
    return value * 100 if attr == "workload_rate" else value


CORE_SUMMARY = ("직원", "실근무", "실휴게", "피로도", "입식", "좌식", "순찰")


def render_summary_table(result, heading: bool = True, baseline: dict | None = None,
                         key: str = "summary_all_columns") -> None:
    """전 직원 핵심 비교. With ``baseline`` (stats before edits) changed values are marked."""
    stats = sorted(result.employee_stats.values(), key=lambda p: (not p.is_manager, p.display_number or 0))
    if heading:
        st.subheader("전 직원 핵심 비교")
    show_all = st.toggle("모든 열 보기", key=key, help="표시 포스트, 가용시간, 근무부담률, 연속시간까지 보기")
    order = None if show_all else list(CORE_SUMMARY)
    if baseline:
        rows, marks = [], []
        for p in stats:
            before = baseline.get(p.employee_id)
            row, mark = {"직원": person_ui_label(p)}, [False]
            for label, attr, unit in SUMMARY_COLUMNS:
                now = _summary_value(p, attr)
                text = f"{now:.1f}%" if unit == "%" else f"{now:g}{unit}"
                old = _summary_value(before, attr) if before is not None else now
                if abs(now - old) > 1e-9:
                    delta = f"{now - old:+.1f}%p" if unit == "%" else f"{now - old:+g}"
                    text = f"{text} ({delta})"
                    mark.append(True)
                else:
                    mark.append(False)
                row[label] = text
            rows.append(row)
            marks.append(mark)
        frame = pd.DataFrame(rows)
        colors = pd.DataFrame([["background-color:#FEF3C7;color:#111827;font-weight:600" if m else "" for m in mark]
                               for mark in marks], columns=frame.columns)
        st.dataframe(frame.style.apply(lambda _: colors, axis=None), hide_index=True, width="stretch",
                     column_order=order)
        st.caption("노란 칸은 수정 전과 달라진 값이고, 괄호 안은 변화량입니다.")
        return
    general = [p for p in stats if not p.is_manager and p.available_time == 14]
    if len(general) >= 2:
        f = [p.fatigue_value for p in general]
        w = [p.actual_work_time_value for p in general]
        st.caption(f"온전 출근 일반근무자: 피로도 {min(f):g}~{max(f):g} (차이 {max(f) - min(f):g}) · "
                   f"실근무 {min(w):g}~{max(w):g}시간 (차이 {max(w) - min(w):g})")
    top_f = max([p.fatigue_value for p in stats] + [1])
    top_w = max([p.actual_work_time_value for p in stats] + [1])
    st.dataframe(pd.DataFrame([{
        "직원": person_ui_label(p),
        **{label: _summary_value(p, attr) for label, attr, _ in SUMMARY_COLUMNS},
    } for p in stats]), hide_index=True, width="stretch", column_order=order, column_config={
        "피로도": st.column_config.ProgressColumn("피로도", min_value=0, max_value=float(top_f), format="%d"),
        "실근무": st.column_config.ProgressColumn("실근무", min_value=0, max_value=float(top_w), format="%d"),
        "실제 업무 연속시간": st.column_config.NumberColumn(
            help="실제근무가 시간상 연속된 최대 시간.", format="%d시간"),
        "연속근무 제한 적용시간": st.column_config.NumberColumn(
            help=("룰북의 연속근무 제한 판정에 포함되는 업무만 기준으로 계산한 최대 연속시간. "
                  "연속근무 카운트 제외 특수 업무가 있으면 실제 업무 연속시간과 다를 수 있습니다."),
            format="%d시간"),
        "최대 연속 실휴게": st.column_config.NumberColumn(format="%d시간"),
        "근무부담률": st.column_config.NumberColumn(format="%.1f%%"),
    })


def render_summary_detail(result, key: str, heading: bool = True) -> None:
    stats = sorted(result.employee_stats.values(), key=lambda p: (not p.is_manager, p.display_number or 0))
    if heading:
        st.subheader("직원 상세분석")
    selected_id = st.selectbox(
        "직원 선택",
        tuple(p.employee_id for p in stats),
        format_func=lambda employee_id: next(person_ui_label(p) for p in stats if p.employee_id == employee_id),
        key=key,
    )
    person = result.employee_stats[selected_id]
    rows = sorted((row for row in result.record.assignments if row.employee_id == selected_id),
                  key=lambda row: row.slot.index)
    metric_columns = st.columns(6)
    for column, label, value in zip(metric_columns,
                                    ("실근무", "실휴게", "피로도", "입식", "좌식", "순찰"),
                                    (person.actual_work_time_value, person.actual_rest_time_value,
                                     person.fatigue_value, person.standing, person.seated,
                                     person.patrol_count)):
        column.metric(label, value)

    work_slots = {index for window in person.longest_actual_work
                  for index in range(window.start_index, window.end_index_exclusive)}
    rest_slots = {index for window in person.longest_rest
                  for index in range(window.start_index, window.end_index_exclusive)}
    # 흰 바탕 패널 (다크모드에서 시간 머리글·칸 글자가 묻히지 않게)
    parts = ["<div style='overflow-x:auto;background:#fff;color:#111827;border-radius:10px;padding:6px'>"
             "<table style='border-collapse:separate;border-spacing:4px;width:100%;min-width:1100px'>",
             "<tr>"]
    parts.extend(f"<th style='padding:5px;color:#475569'>{row.slot.hour:02d}</th>" for row in rows)
    parts.append("</tr><tr>")
    for row in rows:
        display_label, notes, color, category = assignment_view(row, result.record.context)
        actual_label = actual_state_label(row)
        posture = POSTURE_LABELS.get(row.posture_or_mode, "")
        status = ("순찰" if row.actual_post_or_work_type.kind == AssignmentKind.PATROL else
                  "보안실 대기" if row.displayed_assignment.kind == AssignmentKind.SECURITY_STANDBY else
                  "휴게성" if row.actual_rest_time_value == 1 else
                  "차단봉" if row.barrier_install_flag or row.barrier_remove_flag else posture or category)
        # '휴게 / 휴게성 / 실제 휴게성'처럼 같은 말이 반복되면 '실제 …' 줄은 뺀다
        differs = actual_label not in (display_label, status) and actual_label not in notes
        actual_html = f"<div style='font-size:.68rem;margin-top:4px'>실제 {escape(actual_label)}</div>" if differs else ""
        markers = []
        if row.slot.index in work_slots and person.max_actual_work_run:
            markers.append("최장 근무")
        if row.slot.index in rest_slots and person.max_rest_run:
            markers.append("최장 휴게")
        marker_html = (f"<div style='font-size:.62rem;margin-top:4px;color:#334155'>{' · '.join(markers)}</div>"
                       if markers else "")
        border = "2px solid #0F172A" if markers else "1px solid #CBD5E1"
        parts.append(
            f"<td style='background:#{color};color:#111827;border:{border};border-radius:7px;text-align:center;"
            "padding:8px 3px;min-width:70px;vertical-align:top'>"
            f"<strong>{escape(display_label)}</strong><div style='font-size:.7rem'>{escape(status)}</div>"
            f"{actual_html}{marker_html}</td>"
        )
    parts.append("</tr></table></div>")
    st.markdown("".join(parts), unsafe_allow_html=True)
    st.caption("각 칸은 표시 배정과 실제 상태를 함께 보여줍니다. 굵은 테두리는 해당 직원의 최장 실제근무 또는 최장 실휴게 구간입니다.")

    detail_columns = st.columns(2)
    with detail_columns[0]:
        st.markdown("**표시 포스트 횟수**")
        south_count = sum(person.displayed_counts.get(label, 0) for label in ("G2", "G3", "G2(1)"))
        counts = [(label, person.displayed_counts.get(label, 0)) for label in ("G1", "L3", "I1")]
        counts.append(("G2", south_count))
        maximum = max((value for _, value in counts), default=1) or 1
        for label, value in counts:
            if value:
                st.progress(value / maximum, text=f"{label}  {value}회")
        patrols = [PATROL_LABELS.get(row.actual_post_or_work_type.label, row.actual_post_or_work_type.label)
                   for row in rows if row.actual_post_or_work_type.kind == AssignmentKind.PATROL]
        st.write("순찰구역:", " · ".join(patrols) or "없음")
    with detail_columns[1]:
        st.markdown("**자세·휴게 비교**")
        comparison = [("입식", person.standing), ("좌식", person.seated),
                      ("실휴게", int(person.actual_rest_time_value))]
        maximum = max((value for _, value in comparison), default=1) or 1
        for label, value in comparison:
            st.progress(value / maximum, text=f"{label}  {value}시간")
        posture_detail = []
        for label in ("G1", "I1"):
            counts_by_posture = person.posture_by_post.get(label, {})
            if counts_by_posture.get("standing") or counts_by_posture.get("seated"):
                posture_detail.append(
                    f"{label}: 입식 {counts_by_posture.get('standing', 0)}회 · 좌식 {counts_by_posture.get('seated', 0)}회")
        st.caption(" / ".join(posture_detail) or "G1·I1 자세 전환 없음")
    st.write("**최장 실제근무:**", run_text(person.longest_actual_work) or "없음")
    st.write("**최장 실휴게:**", run_text(person.longest_rest) or "없음")
    st.write("**최장 연속근무 제한 적용구간:**", run_text(person.longest_rule_work) or "없음")


def render_history(result: ServiceResult) -> None:
    prepared = result.prepared_inputs
    st.write(f"확정 실제 이력: **{prepared.actual_record_count}회**")
    st.write("누적값 직접 입력: **사용**" if prepared.assumed_history_used else "누적값 직접 입력: **없음**")
    if prepared.historical_totals is not None:
        names = {p.employee_id: p.name for p in result.context.employees}
        ids = list(prepared.historical_nights or {})
        st.dataframe(pd.DataFrame([{
            "직원": f"{employee_id} {names.get(employee_id, '')}",
            "과거 출근 횟수": prepared.historical_nights[employee_id],
            **{HISTORY_LABELS[key]: values.get(employee_id, 0)
               for key, values in prepared.historical_totals.items()},
        } for employee_id in ids]), hide_index=True, width="stretch")
    st.write("직전 설치자:", ", ".join(prepared.previous_install_ids) or "없음")
    st.write("직전 철수자:", ", ".join(prepared.previous_remove_ids) or "없음")
    st.write("이번 설치 제외자:", ", ".join(prepared.forbid_install_ids) or "없음")
    st.write("직전 07시 실휴게자:", ", ".join(prepared.forbid_last_rest_ids) or "없음")
    st.write("직전 순찰 제외자:", ", ".join(prepared.forbid_patrol_exclusion_ids) or "없음")
    st.write("순찰 회전 우선자:", ", ".join(prepared.patrol_rotation_priority_ids) or "없음")
    st.write("입력 soft debt:")
    st.json(prepared.soft_debt or {})
    st.caption("이 화면은 이번 생성에 사용한 이력 입력을 보여줍니다. 계획표를 확정 실제 이력으로 자동 저장하지 않습니다.")


def render_settings(result: ServiceResult, elapsed: float, options: SolveOptions) -> None:
    solved = result.solve_result
    st.write("Solver 상태:", solved.status)
    st.write("시도 횟수:", len(solved.attempts))
    st.write("목표 충족:", "예" if solved.targets_met else "아니요")
    st.write("실행시간:", f"{elapsed:.1f}초")
    st.write("시간 제한:", f"{options.seconds}초")
    st.write("요청 모드:", result.context.requested_mode.value)
    switch = getattr(result.context, "flexible_from_slot", None)
    mode_text = result.context.effective_mode.value
    if switch is not None:
        mode_text += f" → 유도리 ({(18 + switch) % 24:02d}시부터)"
    st.write("적용 모드:", mode_text)
    if result.context.mode_change_reason:
        st.write("모드 변경 사유:", result.context.mode_change_reason)
    if result.rebalance_info:
        info = result.rebalance_info
        st.write("재편성 원본:", info.source_record_id)
        st.write("LOCK 종료 슬롯:", f"{(18 + info.locked_through_index) % 24:02d}시")
        st.write("재편성 시작 슬롯:", f"{(18 + info.reoptimization_start_index) % 24:02d}시")
        st.write("인원변동:", info.unavailable_employee_id, info.reason)
    st.write("Solver 시도 상세:")
    st.json(solved.attempts)
    st.caption("FEASIBLE은 규칙을 통과한 해를 뜻하며 전역 최적성 증명과는 다릅니다.")


def render_validation(result: ServiceResult) -> None:
    st.subheader("하드룰 검증")
    if result.valid:
        st.success("하드룰 검증 통과 — 위반 0건")
    elif result.validation_errors:
        st.error(f"하드룰 위반 {len(result.validation_errors)}건")
        st.dataframe(pd.DataFrame(validation_rows(result)), hide_index=True, width="stretch")
    else:
        st.warning(f"Solver 상태 {result.solve_result.status}: 검증할 근무표가 없습니다.")

    st.subheader("소프트룰·권장사항")
    try:
        findings = analyze_soft_rules(result)
    except Exception:  # e.g. an unusual manager-handover record; soft analysis is advisory only
        findings = []
        st.caption("이 근무표는 소프트룰 분석을 건너뛰었습니다.")
    if not findings:
        st.success("소프트룰/권장사항 미충족 없음")
    else:
        st.warning(f"소프트룰/권장사항 미충족 {len(findings)}건")
        st.dataframe(pd.DataFrame([{
            "대상 직원": finding.employee_label,
            "시간대": finding.time_range,
            "권장사항": finding.title,
            "룰북 조항": finding.rule_id,
            "미충족 설명": finding.detail,
        } for finding in findings]), hide_index=True, width="stretch")
    st.caption(f"소프트룰 미충족은 하드룰 위반이 아닙니다. 현재 표의 기록값으로 확인 가능한 v{result.rules_version} 권장사항만 분석합니다.")


def select_schedule(index: int) -> None:
    st.session_state["selected_schedule_index"] = index


def schedule_choice_label(index: int, result: ServiceResult) -> str:
    label = f"근무표 {index + 1}"
    if result.rebalance_info:
        info = result.rebalance_info
        person = result.employee_stats.get(info.unavailable_employee_id)
        employee = person_ui_label(person) if person else info.unavailable_employee_id
        hour = (18 + info.reoptimization_start_index) % 24
        label += f" · 긴급 재편성 ({hour:02d}시부터, {employee})"
    # Only surface solver/validator status when something is wrong.
    if result.validation_errors:
        return f"{label} · ⚠ 검증 위반 {len(result.validation_errors)}건"
    if result.solve_result.status not in ("FEASIBLE", "OPTIMAL"):
        return f"{label} · ⚠ {result.solve_result.status}"
    return label


def regenerate_locked(index: int, params: dict, history: HistorySelection, options: SolveOptions) -> None:
    """Another schedule under the same LOCK and absence as schedule `index`."""
    results = list(st.session_state.get("schedule_results", []))
    all_params = st.session_state.get("rebalance_params", {})
    same = [i for i, p in all_params.items() if p == params and i < len(results)]
    siblings = [results[i] for i in same]
    source = results[params["source"]]
    started = perf_counter()
    try:
        with st.spinner("LOCK 구간은 그대로 두고 다른 근무표를 찾는 중입니다…"):
            outcome = run_reoptimization(source, params["start"], params["employee"], params["from"],
                                         history, options, params["event"],
                                         exclude=exclusion_payloads(siblings) or None)
    except Exception as exc:
        st.session_state["regen_message"] = friendly_exception_message(exc, "LOCK 재생성")
        st.rerun()
    st.session_state["elapsed"] = perf_counter() - started
    if outcome.valid:
        all_params[len(results)] = dict(params)
        st.session_state["schedule_results"] = [*results, outcome]
        st.session_state["pending_selected_schedule_index"] = len(results)
        st.session_state["last_result"] = outcome
        st.session_state["run_state"] = "재편성 완료"
    elif outcome.record is None and outcome.solve_result.status == "INFEASIBLE":
        st.session_state["regen_message"] = (
            f"현재 LOCK 조건에서는 이미 만든 {len(siblings)}개와 3명 이상이 각자 3칸 이상 다른 근무표가 더 없습니다. "
            "LOCK 이후 남은 시간이 짧으면 다른 해가 나오기 어렵습니다.")
    elif outcome.record is None:
        st.session_state["regen_message"] = solver_failure_message(outcome.solve_result.status, "LOCK 재생성")
    else:
        st.session_state["regen_message"] = "재생성 결과가 하드룰 검증을 통과하지 못했습니다: " + ", ".join(
            explain_errors(outcome.validation_errors, outcome.context))
    st.rerun()


def hint_bar(items) -> None:
    chips = "".join(f"<span style='display:inline-block;background:#F1F5F9;border:1px solid #E2E8F0;"
                    f"border-radius:999px;padding:1px 9px;margin:0 6px 4px 0;font-size:.78rem;color:#334155'>{escape(i)}</span>"
                    for i in items)
    st.markdown(f"<div>{chips}</div>", unsafe_allow_html=True)


def status_badge(items) -> None:
    """Big state pills under the title: (text, tone) with tone in ok/warn/idle/info."""
    tones = {"ok": ("#DCFCE7", "#166534"), "warn": ("#FEF3C7", "#92400E"),
             "idle": ("#F1F5F9", "#475569"), "info": ("#DBEAFE", "#1E40AF")}
    pills = "".join(f"<span style='display:inline-block;background:{tones[t][0]};color:{tones[t][1]};"
                    f"border-radius:999px;padding:4px 14px;margin:0 8px 6px 0;font-weight:700;font-size:.95rem'>"
                    f"{escape(text)}</span>" for text, t in items)
    st.markdown(f"<div style='margin:-4px 0 10px'>{pills}</div>", unsafe_allow_html=True)


def _emergency_info(result) -> dict | None:
    info = result.rebalance_info
    if info is None:
        return None
    return {"employee": info.unavailable_employee_id, "from": info.unavailable_from_index,
            "reason": info.reason, "locked_through": info.locked_through_index}


def render_balance_notes(reasons: list[str], monthly_rows: list[dict], duties=None) -> None:
    """Page bottom: why someone gained or lost balance, and the monthly direction."""
    st.divider()
    st.markdown("#### 📝 특이사항 · 비고")
    if len(reasons) > 1 and "특이사항 없음." in reasons:
        reasons = [line for line in reasons if line != "특이사항 없음."]
    for line in reasons:
        st.markdown("- " + line.replace("~", "\\~"))
    if duties is not None and not duties.empty:
        st.markdown("**근무자별 최근 3싸이클 차단봉·순찰**")
        st.markdown(duty_grid_html(duties), unsafe_allow_html=True)
        st.caption("합계 열은 이번 근무를 뺀 최근 6근무 기준입니다. 근무표 생성은 이 6근무에서 "
                   "밤당 덜 맡은 사람에게 차단봉·각 순찰 구역을 먼저 주는 방향으로 편성합니다.")
    with st.expander("🧭 앞으로의 편성 방향 (월간 기록 기준)", expanded=False):
        for line in monthly_direction(monthly_rows):
            st.markdown("- " + line.replace("~", "\\~"))


def history_store_exists(day) -> bool:
    return _history_store.exists(store_dir(), day)


def main() -> None:
    st.set_page_config(page_title="근무표 자동 생성기", layout="wide")
    title_slot = st.empty()                      # 날짜를 고른 뒤 주간/야간 제목으로 채움
    badge_slot = st.container()
    operations_slot = st.container()             # 야간 유도리 포스트별 운영 입력 자리 (사이드바보다 넓게)
    if st.session_state.get("flash"):
        st.success(st.session_state.pop("flash"))
    st.session_state.setdefault("schedule_results", [])
    st.session_state.setdefault("selected_schedule_index", 0)
    st.session_state.setdefault("display_numbers", {})
    with st.sidebar:
        st.header("근무 조건")
        st.session_state.setdefault("shift_date", next_night(date.today()))
        saved = sorted(set(_history_store.list_dates(store_dir()))
                       | set(_history_store.list_dates(day_store_dir())))
        picked = _CALENDAR(data={
            "selected": st.session_state["shift_date"].isoformat(), "today": date.today().isoformat(),
            "saved": [d.isoformat() for d in saved], "pattern_start": PATTERN_START.isoformat(),
            "holidays": {d.isoformat(): name for d, name in HOLIDAYS.items()},
            "year_from": 2025, "year_to": max(2028, date.today().year + 1),
        }, key="shift_calendar", default=None)
        if isinstance(picked, dict) and picked.get("nonce") != st.session_state.get("calendar_nonce"):
            st.session_state["calendar_nonce"] = picked.get("nonce")
            st.session_state["shift_date"] = date.fromisoformat(picked["date"])
            st.rerun()
        shift_date = st.session_state["shift_date"]
        # Night type follows the chosen date (N1~N4) unless the user changes it afterwards.
        if st.session_state.get("night_type_date") != shift_date:
            st.session_state["night_type_date"] = shift_date
            st.session_state["night_type_select"] = night_type_for(shift_date)
        kind = shift_kind(shift_date)
        holiday = holiday_name(shift_date)
        st.markdown(f"**근무 기준일 {shift_date:%Y-%m-%d} ({'월화수목금토일'[shift_date.weekday()]})** · "
                    f"{PATTERN_LABELS[kind]}" + (f" · 🔴 {holiday}" if holiday else "")
                    + "  \n<span style='font-size:.75rem;color:#64748b'>18시 시작 야간 기준</span>",
                    unsafe_allow_html=True)
        has_saved = history_store_exists(shift_date)
        day_page = kind == "주" and not is_off_day(shift_date)
        title_slot.title("주간 근무표 자동 생성기" if kind == "주" else "야간 근무표 자동 생성기")
        if kind == "주" and not day_page:
            st.info("주말·공휴일 주간근무입니다.")
            return_early = not has_saved
        elif day_page:
            return_early = False
        elif kind == "휴":
            st.info("A조 휴일입니다.")
            return_early = not has_saved
        else:
            return_early = False
            if history_store_exists(shift_date):
                st.success("이 날짜의 저장된 근무표를 화면 위쪽에 표시합니다.")
    if return_early:
        day_label = f"{shift_date} ({'월화수목금토일'[shift_date.weekday()]})"
        if kind == "휴":
            st.info(f"📅 {day_label}은 A조 휴일입니다.")
        else:
            st.info(f"📅 {day_label}은 주말·공휴일 주간근무입니다. 지금 주간 룰북은 평일용이라 "
                    "주말·공휴일 주간 편성은 아직 지원하지 않습니다.")
        return
    if day_page:
        render_day_page(shift_date, badge_slot)
        return
    with st.sidebar:
        mode_name = st.radio("운영 모드", ("FM", "유도리"), horizontal=True)
        post_operations = flexible_operations_input(operations_slot) if mode_name == "유도리" else None
        if mode_name == "유도리":
            st.caption("유도리 포스트별 운영(몇 시~몇 시 휴게성·좌식)은 본문 위쪽에서 정합니다.")
        night_name = st.selectbox("야간 유형", tuple(n.value for n in NightType),
                                  format_func=night_type_label, key="night_type_select",
                                  help="날짜를 고르면 평일/주말·공휴일에 맞춰 자동으로 정해집니다. 필요하면 바꿀 수 있습니다.")
        manager = st.radio("관리자 상태", ("A 출근", "A 결근 (준호 대행)"), key="manager_state")
        a_present = manager == "A 출근"
        st.subheader("야간 근무자")
        # 주간과 같은 표: 이름·상태·역할. 상태만 고치고, 상태는 session_state["night_statuses"]에 보관.
        statuses = st.session_state.setdefault("night_statuses", {})

        def night_role(employee_id, name):
            if employee_id == "6" and not a_present:
                return "관리자 대행"
            return "선임" if name == "준호" else "일반"   # 준호 = 선임 (룰북 8-8)
        edited = st.data_editor(
            pd.DataFrame([{"이름": name, "상태": statuses.get(employee_id, "출근"),
                           "역할": night_role(employee_id, name)} for employee_id, name in ROSTER]),
            hide_index=True, num_rows="fixed", width="stretch", disabled=("이름", "역할"), key="night_roster",
            column_config={"상태": st.column_config.SelectboxColumn(options=NIGHT_STATUSES, required=True)})
        new_statuses = {employee_id: (row["상태"] or "출근")
                        for (employee_id, _), (_, row) in zip(ROSTER, edited.iterrows())}
        if not a_present and new_statuses["6"] != "출근":
            st.warning("A 결근이면 준호가 관리자 대행이라 출근으로 고정합니다.")
            new_statuses["6"] = "출근"
        st.session_state["night_statuses"] = new_statuses
        presence = {employee_id: status == "출근" for employee_id, status in new_statuses.items()}
        absence_types = {employee_id: status for employee_id, status in new_statuses.items() if status != "출근"}
        known_presence = night_known_presence(a_present, new_statuses)
        population_key = (a_present, tuple(employee_id for employee_id, _ in ROSTER if known_presence[employee_id]))
        if st.session_state.get("display_population_key") != population_key:
            st.session_state["display_population_key"] = population_key
            st.session_state["display_numbers"] = random_display_numbers(a_present, known_presence)
        staff = staff_for_input(a_present, presence, st.session_state["display_numbers"],
                                absence_types)
        st.caption("상태에서 연차·전반부 반차(01시 출근)·후반부 반차(01시 퇴근)를 고릅니다. "
                   "통제A는 위 '관리자 상태'로 정하고, A 결근이면 준호가 관리자 대행이라 출근이 필수입니다.")
        general = tuple(p for p in staff if p.present and p.is_general_worker)
        st.subheader("이력 입력")
        history = history_inputs(general, tuple(p for p in staff if p.present), shift_date)
        with st.expander("생성 상세 설정"):
            seconds = int(st.number_input("Solver 제한시간 (초)", min_value=5, max_value=300,
                                          value=45, step=5))
            prioritize_history = st.checkbox("당일 목표 안에서 이력 균형 우선", value=False)
        generate = st.button("근무표 생성", type="primary", width="stretch", key="generate_button",
                             on_click=rotate_display_numbers)
        render_trash("side")

    request = ShiftRequest(shift_date, NightType(night_name),
                           Mode.FM if mode_name == "FM" else Mode.FLEXIBLE, staff, post_operations=post_operations)
    options = SolveOptions(rules_version="2.20", seconds=seconds,
                           prioritize_history_within_daily_targets=prioritize_history)
    signature = condition_signature(request, history, options)
    if st.session_state.get("input_signature") != signature:
        st.session_state["input_signature"] = signature
        st.session_state["schedule_results"] = []
        st.session_state["generated_originals"] = {}
        st.session_state["rebalance_params"] = {}
        st.session_state["selected_schedule_index"] = 0
        st.session_state["last_result"] = None
        st.session_state["run_state"] = "입력 확인 후 생성"
        st.session_state["run_error"] = None
        st.session_state["elapsed"] = None
    if generate:
        prior_results = st.session_state.get("schedule_results", [])
        excluded = exclusion_payloads(prior_results) or None
        st.session_state["run_state"] = "생성 중"
        st.session_state["run_error"] = None
        started = perf_counter()
        try:
            with st.spinner("근무표 생성 및 하드룰 검증 중입니다…"):
                outcome = run_schedule(request, history,
                                       replace(options, exclude_assignments=excluded))
            st.session_state["elapsed"] = perf_counter() - started
            if outcome.valid:
                st.session_state["schedule_results"] = [*prior_results, outcome]
                st.session_state["selected_schedule_index"] = len(st.session_state["schedule_results"]) - 1
                st.session_state["last_result"] = outcome
                st.session_state["run_state"] = "생성 완료"
            elif outcome.record is None:
                st.session_state["run_state"] = "생성 실패"
                if prior_results and outcome.solve_result.status == "INFEASIBLE":
                    st.session_state["run_error"] = (
                        "현재 조건에서는 기존 모든 근무표와 비교해 최소 3명이 각자 3개 시간대 이상 "
                        f"달라지는 추가 해가 없습니다. 확인된 서로 다른 해는 {len(prior_results)}개입니다."
                    )
                elif prior_results and outcome.solve_result.status == "UNKNOWN":
                    st.session_state["run_error"] = (
                        "제한시간 안에 기존 모든 근무표와 비교해 최소 3명이 각자 3개 시간대 이상 "
                        "달라지는 추가 해를 찾지 못했습니다. "
                        "유일한 해라고 확정된 것은 아니므로 Solver 제한시간을 늘려 다시 시도해 주세요."
                    )
                else:
                    st.session_state["run_error"] = solver_failure_message(outcome.solve_result.status)
            else:
                st.session_state["last_result"] = outcome
                st.session_state["run_state"] = "검증 실패"
                st.session_state["run_error"] = f"Validator 오류 {len(outcome.validation_errors)}건. 이 결과는 정상 근무표로 표시하지 않습니다."
        except Exception as exc:
            st.session_state["elapsed"] = perf_counter() - started
            st.session_state["run_state"] = "실행 오류"
            st.session_state["run_error"] = friendly_exception_message(exc, "근무표 생성")

    schedule_results: list[ServiceResult] = st.session_state.get("schedule_results", [])
    pending_selection = st.session_state.pop("pending_selected_schedule_index", None)
    if pending_selection is not None:
        st.session_state["selected_schedule_index"] = pending_selection
    selected_index = st.session_state.get("selected_schedule_index", 0)
    selected_result: ServiceResult | None = (
        schedule_results[selected_index] if schedule_results and selected_index < len(schedule_results) else None
    )
    c1, c2, c3, c4, c5 = st.columns(5)
    c1.metric("기준 날짜", str(shift_date))
    c2.metric("야간 유형", night_type_label(selected_result.context.night_type if selected_result else night_name))
    c3.metric("룰북", f"v{selected_result.rules_version}" if selected_result else f"v{options.rules_version}")
    c4.metric("생성 상태", st.session_state["run_state"])
    c5.metric("검증 상태", "하드룰 통과 · 위반 0건" if selected_result and selected_result.valid else
              f"위반 {len(selected_result.validation_errors)}건" if selected_result and selected_result.validation_errors else "미검증")
    if st.session_state.get("run_error"):
        st.error(st.session_state["run_error"])
    if history_store_exists(shift_date):
        # A saved night: its schedule, the monthly record and the notes only.
        state = saved_status("saved", shift_date)
        badges = [("✅ 확정됨", "ok")]
        if state.get("has_revision"):
            badges.append(("수정본 있음", "info"))
        if state.get("unsaved"):
            badges.append(("✏️ 저장 안 한 수정 있음", "warn"))
        if state.get("locked"):
            badges.append(("🔒 긴급 재편성", "info"))
        with badge_slot:
            status_badge(badges)
        st.subheader(f"📅 {shift_date} 저장된 근무표")
        shown = render_history_editor("saved", _DRAG_GRID, shift_date, render_summary_table, render_summary_detail)
        with st.expander("📊 월간 기록", expanded=False):
            monthly_rows = render_monthly(shift_date)
        if shown:
            record = shown["actual"]
            try:
                prepared = prepare_engine_inputs(record.context, _history_store.history_selection(store_dir(), shift_date))
            except Exception:
                prepared = None
            plan = shown["plan"]
            note_lines = [line for line in (shown.get("note") or "").splitlines() if line.strip()]
            render_balance_notes(note_lines + balance_reasons(
                record, calculate_all_stats(record), prepared,
                plan_stats=calculate_all_stats(plan) if plan.assignments != record.assignments else None,
                notes=shown["notes"], manual=bool(shown.get("source")),
                emergency=({**(shown["rebalance"] or {}), "locked_through": shown["lock"]}
                           if shown["lock"] >= 0 else None)), monthly_rows,
                duty_frame(shift_date, record))
        return
    if not schedule_results:
        with badge_slot:
            status_badge([("미생성", "idle")])
    else:
        edited = selected_index in st.session_state.get("generated_originals", {})
        with badge_slot:
            status_badge([("🕓 미확정 (생성만 됨)", "warn")]
                     + ([("✏️ 드래그 수정됨", "warn")] if edited else [])
                     + ([("🔒 긴급 재편성", "info")] if selected_result and selected_result.rebalance_info else []))
    tabs = st.tabs(("근무표", "요약 정보", "검증 결과", "월간 기록"))
    with tabs[0]:
        if schedule_results:
            labels = [schedule_choice_label(index, item)
                      for index, item in enumerate(schedule_results)]
            selected_index = st.radio("표시할 근무표", range(len(schedule_results)),
                                      format_func=lambda index: labels[index],
                                      key="selected_schedule_index")
            selected_result = schedule_results[selected_index]
            st.session_state["last_result"] = selected_result
            params = st.session_state.setdefault("rebalance_params", {}).get(selected_index)
            if params:
                c_confirm, c_regen = st.columns(2)
                with c_confirm:
                    confirm_button(selected_result, f"confirm_{selected_index}")
                with c_regen:
                    if st.button("🔁 현재 LOCK 조건으로 근무표 재생성", key=f"regen_lock_{selected_index}"):
                        regenerate_locked(selected_index, params, history, options)
            else:
                confirm_button(selected_result, f"confirm_{selected_index}")
            if st.session_state.get("regen_message"):
                st.warning(st.session_state.pop("regen_message"))
            st.caption("후보를 선택하면 요약·검증 결과도 같은 근무표로 바뀝니다. 색상: 휴게(회색), 보안실(파랑), G1(초록), L3(파랑), I1(노랑), 남문(빨강), 순찰(보라), 차단봉(분홍).")
            if selected_result.rebalance_info:
                info = selected_result.rebalance_info
                lock_hour = (18 + info.locked_through_index) % 24
                start_hour = (18 + info.reoptimization_start_index) % 24
                unavailable_hour = (18 + info.unavailable_from_index) % 24
                person = selected_result.employee_stats.get(info.unavailable_employee_id)
                st.info(
                    f"긴급 재편성표 · {lock_hour:02d}시까지 기존 실제배정 LOCK · "
                    f"{start_hour:02d}시부터 재최적화 · "
                    f"{person_ui_label(person) if person else info.unavailable_employee_id} "
                    f"{unavailable_hour:02d}시부터 ×"
                )
            def start_rebalance(rebalance_start, employee_id, event):
                """표에서 시간 칸(LOCK)·이름(반차/이탈)을 고르면 바로 재편성 (주간과 같은 방식)."""
                unavailable_from = NIGHT_HALF_LEAVE_SLOT if event.startswith("후반부") else rebalance_start
                started = perf_counter()
                try:
                    with st.spinner("기존 실제배정을 LOCK하고 남은 시간대를 재편성 중입니다…"):
                        outcome = run_reoptimization(
                            selected_result, rebalance_start, employee_id,
                            unavailable_from, history, options, event,
                        )
                    st.session_state["elapsed"] = perf_counter() - started
                    if outcome.valid:
                        st.session_state.setdefault("rebalance_params", {})[len(schedule_results)] = {
                            "source": selected_index, "start": rebalance_start, "employee": employee_id,
                            "from": unavailable_from, "event": event}
                        st.session_state["schedule_results"] = [*schedule_results, outcome]
                        st.session_state["pending_selected_schedule_index"] = len(schedule_results)
                        st.session_state["last_result"] = outcome
                        st.session_state["run_state"] = "재편성 완료"
                        st.session_state["run_error"] = None
                        st.rerun()
                    elif outcome.record is None:
                        diagnosis = outcome.failure_diagnosis
                        if diagnosis:
                            st.error(diagnosis.title)
                            st.write(diagnosis.summary)
                            if diagnosis.relaxation_level:
                                st.warning(diagnosis.relaxation_level)
                            for detail in diagnosis.exceptions:
                                st.write("-", detail)
                            if diagnosis.next_action:
                                st.info(diagnosis.next_action)
                        else:
                            st.error(solver_failure_message(outcome.solve_result.status, "긴급 재편성"))
                    else:
                        st.error("재편성 결과가 하드룰 검증을 통과하지 못했습니다. 기존 근무표는 유지됩니다.\n\n"
                                 + "\n".join(f"- {r}" for r in explain_errors(outcome.validation_errors, outcome.context)))
                except Exception as exc:
                    st.session_state["elapsed"] = perf_counter() - started
                    st.error(friendly_exception_message(exc, "긴급 재편성"))

            spreads = selected_result.dual_spreads or {}

            def spread_text(mode):
                values = spreads.get(mode, {})
                return f"{mode} 피로도 차이 {values.get('피로도', '-')}점·실휴게 차이 {values.get('실휴게', '-')}시간"
            if selected_result.dual_mode is True and selected_result.dual_balanced:          # 룰북 0-2-1 1단계
                st.success("✅ FM·유도리 모두 만족 — 현장에서 유도리(I1 00~03시 휴게성)로 운영하게 되어도 "
                           "하드룰 위반이 없고, 두 기준 모두 일반근무자 피로도 차이 1점·실휴게 차이 1시간 이하입니다.")
            elif selected_result.dual_mode is True:                                          # 2단계
                st.info("FM·유도리 하드룰은 모두 만족 — 다만 두 기준 모두 밸런스 목표(피로도 1점·실휴게 1시간 이하)를 "
                        f"맞추는 표는 없었습니다. ({spread_text('FM')} / {spread_text('유도리')})")
            elif selected_result.dual_mode is False:
                st.warning("FM만 만족 — 이 조건에서는 유도리로 운영해도 되는 표를 찾지 못해 FM 기준으로만 만들었습니다. "
                           "현장에서 유도리로 바뀌면 유도리로 다시 생성해 주세요.")
            render_editable_schedule(selected_index, selected_result, on_leave=start_rebalance)
            if len(schedule_results) > 1:
                st.subheader("이전에 생성한 근무표")
                for index, candidate in enumerate(schedule_results):
                    if index == selected_index:
                        continue
                    with st.expander(labels[index], expanded=False):
                        st.button("이 근무표 선택", key=f"select_schedule_{index}",
                                  on_click=select_schedule, args=(index,))
                        st.markdown(schedule_html(candidate), unsafe_allow_html=True)
        else:
            st.info("검증을 통과한 근무표가 없습니다. 왼쪽에서 조건을 선택하고 생성해 주세요.")
    with tabs[1]:
        if selected_result and selected_result.valid:
            original = st.session_state.get("generated_originals", {}).get(selected_index)
            render_summary(selected_result, calculate_all_stats(original) if original is not None else None)
        else:
            st.info("검증을 통과하면 직원별 통계가 표시됩니다.")
    with tabs[2]:
        if selected_result:
            render_validation(selected_result)
        else:
            st.info("아직 검증 결과가 없습니다.")
    with tabs[3]:
        monthly_rows = render_monthly(shift_date)
    if selected_result is not None and selected_result.valid:
        original = st.session_state.get("generated_originals", {}).get(selected_index)
        reasons = balance_reasons(
            selected_result.record, selected_result.employee_stats, selected_result.prepared_inputs,
            plan_stats=calculate_all_stats(original) if original is not None else None,
            emergency=_emergency_info(selected_result))
        if selected_result.dual_mode is not None:          # 룰북 0-2-1
            spreads = selected_result.dual_spreads or {}
            detail = " / ".join(f"{mode} 피로도 차이 {v.get('피로도')}점·실휴게 차이 {v.get('실휴게')}시간"
                                for mode, v in spreads.items())
            note = ("FM·유도리 모두 만족하는 표입니다: 두 기준 모두 하드룰 위반 0건, " + detail + " (0-2-1)."
                    if selected_result.dual_mode and selected_result.dual_balanced else
                    "FM·유도리 하드룰은 모두 만족하지만 두 기준 밸런스 목표를 함께 맞추는 표는 없었습니다: "
                    + detail + " (0-2-1)."
                    if selected_result.dual_mode else
                    "FM·유도리 모두 만족하는 표가 없어 FM만 만족하는 표로 만들었습니다(0-2-1).")
            reasons = [r for r in reasons if r != "특이사항 없음."] + [note]
        render_balance_notes(reasons, monthly_rows, duty_frame(shift_date, selected_result.record))


if __name__ == "__main__":
    main()
