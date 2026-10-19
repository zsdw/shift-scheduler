"""Streamlit front end for the v2.20 night-shift service."""

from __future__ import annotations

from dataclasses import asdict, replace
from datetime import date
from html import escape
import json
from pathlib import Path
import random
from types import SimpleNamespace
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

# 엔진 파일 내용 지문 (2026-10-19): 엔진을 고치면 손으로 버전을 올리지 않아도 다음 실행에서 자동으로 다시 불러온다.
# (종전에는 SERVICE_API_VERSION 비교값을 매번 손으로 올려야 했고, 빼먹으면 옛 엔진이 조용히 돌았다.)
# service가 처음 불러올 때 지문을 기록하므로 막 불러온 엔진은 다시 불러오지 않는다.
from night_shift.engine_fingerprint import engine_fingerprint as _engine_fingerprint
_ENGINE_FINGERPRINT = _engine_fingerprint()
if (not hasattr(_models_module.AssignmentKind, "UNAVAILABLE")
        or not hasattr(_models_module, "DEFAULT_POST_OPERATIONS")      # 유도리 포스트별 운영 (2026-10-02)
        or getattr(_service_module, "ENGINE_FINGERPRINT", None) != _ENGINE_FINGERPRINT):
    import night_shift.common as _common_module
    import night_shift.leave_context as _leave_context_module
    import night_shift.fatigue_ledger as _fatigue_ledger_module
    import night_shift.engine_fingerprint as _engine_fp_module
    import night_shift.profiles as _profiles_module
    import night_shift.preferences as _preferences_module
    import night_shift.soft_history as _soft_history_module
    import night_shift.solver as _solver_module
    import night_shift.validator as _validator_module
    import night_shift.presentation as _presentation_module
    import night_shift.analysis as _analysis_module
    import night_shift.excel_exporter as _excel_module
    import night_shift.field_exporter as _field_module

    for _module in (_engine_fp_module, _models_module, _common_module, _profiles_module, _preferences_module, _soft_history_module,
                    _leave_context_module, _fatigue_ledger_module, _solver_module, _validator_module, _service_module,
                    _presentation_module, _analysis_module, _excel_module, _field_module):
        importlib.reload(_module)

# Small UI helper modules change often; reload them on every run so an
# already-running server never serves a stale copy (e.g. a missing function).
import night_shift.cp_schedule as _cp_schedule_module
importlib.reload(_cp_schedule_module)
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
if "night_shift.weekend_day" in _sys.modules:
    importlib.reload(_sys.modules["night_shift.weekend_day"])
if "weekend_day_ui" in _sys.modules:
    importlib.reload(_sys.modules["weekend_day_ui"])
if "mobile_ui" in _sys.modules:
    importlib.reload(_sys.modules["mobile_ui"])
for _helper in ("night_shift.source_attachment", "night_shift.leave_schedule", "night_shift.cp_schedule", "night_shift.history_import", "night_shift.cp_image", "cp_image_ui", "night_shift.bulk_import", "night_shift.schedule_image", "night_shift.import_compare", "night_shift.newcomers", "night_shift.schedule_image_import", "image_import_ui", "import_ui",
                "night_shift.daily_report", "leave_view_ui", "daily_report_ui", "night_shift.date_check", "night_shift.document_basis", "date_check_ui",
                "night_shift.order_source", "night_shift.security_order", "security_order_ui", "night_shift.day_image", "night_shift.day_excel_image", "night_shift.day_form_draw", "night_shift.weekend_form", "night_shift.upload_review", "night_shift.kakao_sync", "night_shift.wedding"):
    if _helper in _sys.modules:
        importlib.reload(_sys.modules[_helper])

if 'night_shift.fatigue_ledger_ui' in _sys.modules:
    importlib.reload(_sys.modules['night_shift.fatigue_ledger_ui'])

from night_shift.models import (AssignmentKind, DEFAULT_POST_OPERATIONS, GENERATION_POST_OPERATIONS, Mode, NightType,
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
    run_lock_regeneration,
    run_schedule,
    run_schedule_manager_half, run_schedule_manager_early_half,
)
# 관리자 상태 (2026-10-18: 통제A 후반부 반차 추가 — 01시부터 준호가 관리자 대행, 야간 중도 인계와 같은 방식)
MANAGER_STATES = ("A 출근", "A 전반부 반차 (01시 출근)", "A 후반부 반차 (01시 퇴근)", "A 결근 (준호 대행)")
MANAGER_EARLY_HALF = MANAGER_STATES[1]
MANAGER_LATE_HALF = MANAGER_STATES[2]
from night_shift.soft_history import TRACKED_SOFT_RULES
from night_shift.schedule_edit import explain_errors, grid_payload, swap_person_schedules, swap_schedule_cells
from night_shift.service import (calculate_all_stats, prepare_engine_inputs, revalidate, rulebook_label,
                                 seat_form_record)
from night_shift.balance_notes import balance_reasons, monthly_direction

from history_ui import (
    confirm_button, history_caption, load_saved, render_history_editor, render_monthly, render_trash,
    saved_dates_caption,
    saved_status, day_store_dir, duty_frame, duty_grid_html,
    store_dir, stored_before,
)
from night_shift import history_store as _history_store
from day_ui import render_day_page
from weekend_day_ui import render_weekend_day_page
from night_shift import wedding
import mobile_ui
from night_shift.calendar_info import (
    HOLIDAYS, PATTERN_LABELS, PATTERN_START, holiday_name, is_off_day, next_night, night_type_for, shift_kind,
)

_DRAG_GRID = components.declare_component(
    "drag_schedule", path=str(Path(__file__).resolve().parent / "night_shift" / "drag_grid"))
_CALENDAR = components.declare_component(
    "shift_calendar", path=str(Path(__file__).resolve().parent / "night_shift" / "calendar_picker"))


_ROSTER_PICKER = components.declare_component(
    "night_roster_picker", path=str(Path(__file__).resolve().parent / "night_shift" / "roster_picker"))

ROSTER = (("1", "만년"), ("2", "원종"), ("3", "제욱"),
          ("4", "광희"), ("5", "성호"), ("6", "준호"))
ABSENCE_OPTIONS = ("연차", "전반부 반차 (01시 출근)", "후반부 반차 (01시 퇴근)")
NIGHT_STATUSES = ("출근",) + ABSENCE_OPTIONS + ("기타",)   # 기타 = 그날 근무에서 빠짐 + 비고 (2026-10-04)
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


def conflict_explanation(attempt, options: SolveOptions) -> str:
    """해가 없을 때 어떤 필수 규칙 묶음이 막는지 (2026-10-18). 규칙을 실제로 풀지는 않고, 결정은 사용자가 한다."""
    from night_shift.service import find_conflicting_rules
    with st.spinner("어떤 필수 규칙끼리 부딪히는지 찾는 중입니다…"):
        found = find_conflicting_rules(attempt, options)
    if found["single"]:
        return ("막는 규칙(이 중 하나만 예외로 하면 표가 나옴): " + ", ".join(found["single"])
                + ". 어느 규칙을 양보할지 정해 주세요.")
    if found["pairs"]:
        return ("막는 규칙 조합(둘을 함께 예외로 해야 표가 나옴): "
                + " / ".join(f"{a} + {b}" for a, b in found["pairs"][:6]) + ". 어느 쪽을 양보할지 정해 주세요.")
    return ("점검한 규칙 묶음을 하나나 둘 빼서는 풀리지 않습니다. 인원·LOCK 조건 자체가 부족하거나 "
            "목록 밖의 기본 규칙(포스트 인원·순찰 구역 등)과 부딪힙니다.")


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
        present = status not in ("연차", "기타")
        staff.append(StaffInput(employee_id, name, present, not is_proxy,
                                visible_numbers.get(employee_id), is_proxy, available_slots))
    return tuple(staff)


NIGHT_HOURS = tuple(f"{(18 + t) % 24:02d}시" for t in range(14))
OPERATION_POSTS = ("I1", "G1", "L3", "G2", "G3")           # G2·G3 = 남문 (18~20시, 06~07시 운영)
OPERATION_STATES = {"휴게성": "rest", "좌식": "seated"}


def flexible_operations_input(slot):
    """유도리 포스트별 운영 (사용자 지정). 룰북 기본(I1 22~03시 휴게성)에서 시작해 고치거나 줄을 더한다.

    운영 모드 바로 아래 접힌 설정에 그린다. Returns None(룰북 기본 그대로) 또는 ((post, from, to, state), ...).
    """
    with slot, st.expander("유도리 포스트 운영", expanded=False):
        st.caption("끝 시간도 포함합니다.")
        if "flexible_operation_rows" not in st.session_state:
            rows = [{"포스트": "I1", "시작": "22시", "끝": "03시", "운영": "휴게성", "id": 0}]
            previous = st.session_state.get("flexible_operations", {})
            for index, changes in previous.get("edited_rows", {}).items():
                if int(index) == 0:
                    rows[0].update(changes)
            rows += [dict(row, id=i + 1) for i, row in enumerate(previous.get("added_rows", []))]
            rows = [row for i, row in enumerate(rows) if i not in previous.get("deleted_rows", [])]
            st.session_state["flexible_operation_rows"] = rows
            st.session_state["flexible_operation_next_id"] = max([row["id"] for row in rows], default=0) + 1
        rows = st.session_state["flexible_operation_rows"]
        for row in rows:
            prefix = f"flex_op_{row['id']}_"
            left, right = st.columns(2)
            with left:
                row["포스트"] = st.selectbox("포스트", OPERATION_POSTS,
                    index=OPERATION_POSTS.index(row.get("포스트", "I1")), key=prefix + "post")
                row["시작"] = st.selectbox("시작", NIGHT_HOURS,
                    index=NIGHT_HOURS.index(row.get("시작", "00시")), key=prefix + "start")
            with right:
                row["운영"] = st.selectbox("운영", tuple(OPERATION_STATES),
                    index=tuple(OPERATION_STATES).index(row.get("운영", "휴게성")), key=prefix + "state")
                row["끝"] = st.selectbox("끝", NIGHT_HOURS,
                    index=NIGHT_HOURS.index(row.get("끝", "03시")), key=prefix + "end")
            if st.button("삭제", key=prefix + "delete", width="stretch"):
                st.session_state["flexible_operation_rows"] = [r for r in rows if r["id"] != row["id"]]
                st.rerun()
        if st.button("＋ 포스트 추가", key="flex_op_add", width="stretch"):
            number = st.session_state["flexible_operation_next_id"]
            rows.append({"포스트": "I1", "시작": "22시", "끝": "03시", "운영": "휴게성", "id": number})
            st.session_state["flexible_operation_next_id"] = number + 1
            st.rerun()
        operations, problems = [], []
        for row in rows:
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
        if operations == GENERATION_POST_OPERATIONS and not problems:
            st.caption("룰북 기본 유도리와 같습니다.")
            return None
        return operations


def apply_night_leave_defaults(day: date) -> None:
    """날짜를 고르면 연차일정(저장된 텍스트)대로 야간 상태·관리자 상태·기타 비고를 기본 설정한다 (2026-10-04)."""
    from night_shift import leave_schedule
    names = {name: eid for eid, name in ROSTER}
    defaults, notices = leave_schedule.defaults_for(leave_schedule.load(store_dir(), day.year), day, "night", names)
    statuses = {eid: "출근" for eid, _ in ROSTER}
    for name, (status, _) in defaults.items():
        if name in names and status in NIGHT_STATUSES:
            statuses[names[name]] = status
    manager = defaults.get("A")
    st.session_state["manager_state"] = ("A 결근 (준호 대행)" if manager and manager[0] in ("연차", OTHER_STATUS)
                                         else MANAGER_EARLY_HALF if manager and manager[0].startswith("전반부")
                                         else MANAGER_LATE_HALF if manager and manager[0].startswith("후반부")
                                         else "A 출근")
    saved = leave_schedule.load_notes(store_dir()).get(day.isoformat(), {}).get("night", {})
    st.session_state["night_other_notes"] = {
        names[name]: saved.get(name, note) for name, (status, note) in defaults.items()
        if status == OTHER_STATUS and name in names}
    for name, note in saved.items():                     # 화면에서 저장해 둔 기타가 우선
        if name in names:
            statuses[names[name]] = OTHER_STATUS
            st.session_state["night_other_notes"][names[name]] = note
    st.session_state["night_statuses"] = statuses
    changed = [f"{name} {status}" + (f"({note})" if note else "") for name, (status, note) in defaults.items()
               if name in names or name == "A"]
    st.session_state["leave_notices"] = (["연차일정 반영: " + ", ".join(changed)] if changed else []) + notices


OTHER_STATUS = "기타"


def night_other_notes_input(day: date, statuses: dict[str, str]) -> None:
    """상태 '기타'인 사람마다 짧은 비고 입력칸 (PC·폰 공통). 날짜별로 저장한다."""
    from night_shift import leave_schedule
    names = dict(ROSTER)
    notes = st.session_state.setdefault("night_other_notes", {})
    others = [eid for eid, status in statuses.items() if status == OTHER_STATUS]
    for eid in others:
        notes[eid] = st.text_input(f"{names[eid]} 기타 비고", value=notes.get(eid, ""),
                                   key=f"night_note_{day}_{eid}", placeholder="예: 예비군, 교육, 하계휴가")
    leave_schedule.save_notes(store_dir(), day, "night", {names[eid]: notes.get(eid, "") for eid in others})


def night_other_labels(day: date) -> dict[str, str]:
    """특이사항·월간 기록용: 그날 '기타'로 빠진 사람 {employee_id: 비고}."""
    from night_shift import leave_schedule
    ids = {name: eid for eid, name in ROSTER}
    return {ids[name]: note for name, note in
            leave_schedule.other_labels(store_dir(), day, "night", list(ids)).items() if name in ids}


def night_known_presence(a_present: bool, statuses: dict[str, str]) -> dict[str, bool]:
    """표시번호를 받을 사람: 출근·반차(일부 근무)는 포함, 연차는 제외. A 결근이면 준호(대행)는 항상 포함."""
    known = {employee_id: statuses.get(employee_id, "출근") not in ("연차", "기타") for employee_id, _ in ROSTER}
    if not a_present:
        known["6"] = True
    return known


def rotate_display_numbers() -> None:
    a_present = st.session_state.get("manager_state", "A 출근") != "A 결근 (준호 대행)"
    presence = night_known_presence(a_present, st.session_state.get("night_statuses", {}))
    st.session_state["display_numbers"] = random_display_numbers(a_present, presence)


def request_night_regeneration() -> None:
    rotate_display_numbers()
    st.session_state["night_regenerate_requested"] = True


def restore_generated_schedule(index, on_change=None) -> None:
    """생성 후보의 최초 상태 복원. 저장 파일은 쓰지 않는다."""
    baseline = st.session_state.get("generated_initial_results", {}).get(index)
    original = st.session_state.get("generated_originals", {}).get(index)
    if baseline is None and original is not None:
        results = st.session_state.get("schedule_results", [])
        baseline = revalidate(results[index], original)
    if baseline is None:
        return
    if on_change is not None:
        on_change(baseline)
    else:
        results = list(st.session_state.get("schedule_results", []))
        results[index] = baseline
        st.session_state["schedule_results"] = results
        if index == st.session_state.get("selected_schedule_index", 0):
            st.session_state["last_result"] = baseline
    st.session_state.get("generated_originals", {}).pop(index, None)
    st.session_state.pop("drag_rejection", None)


def candidate_reasons(selected_result, selected_index) -> list[str]:
    """생성 후보의 특이사항·비고 문장(화면 표시와 확정 저장 스냅샷이 같은 문장을 쓴다, 2026-10-20)."""
    shift_date = selected_result.context.shift_start_date
    original = st.session_state.get("generated_originals", {}).get(selected_index)
    reasons = balance_reasons(
        selected_result.record, selected_result.employee_stats, selected_result.prepared_inputs,
        plan_stats=calculate_all_stats(original) if original is not None else None,
        emergency=_emergency_info(selected_result), attempts=selected_result.solve_result.attempts,
        others=night_other_labels(shift_date))
    if getattr(selected_result, "post_cap_relaxed", False):   # H-17 예외 (PC·폰 공통 특이사항)
        reasons.insert(0, "⚠️ 2명 완전결원이라 '같은 포스트 최대 3번'(H-17)을 지키는 표가 없어 "
                          "이 회차만 해제했습니다. 같은 포스트를 4번 이상 서는 사람이 있을 수 있습니다.")
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
    return reasons


def confirm_and_regenerate(result, index, params, history, options) -> None:
    with mobile_ui.action_columns(f"night_{index}", spec=3) as (confirm_col, reset_col, regenerate_col):
        with confirm_col:
            confirm_button(result, f"confirm_{index}", notes=lambda: candidate_reasons(result, index))
        with reset_col:
            if st.button("↩ 초기 생성표로", key=f"restore_initial_{index}", width="stretch",
                         disabled=index not in st.session_state.get("generated_originals", {}),
                         help="이 후보를 처음 생성했을 때의 배정·피로도·수정 내역으로 되돌립니다."):
                restore_generated_schedule(index)
                st.rerun()
        with regenerate_col:
            lock_start = _lock_regen_start(index)
            if params:
                if st.button("🔁 근무표 재생성", key=f"regen_lock_{index}", width="stretch",
                             help="현재 LOCK과 이탈 조건을 유지해 다른 후보를 만듭니다."):
                    regenerate_locked(index, params, history, options)
            elif lock_start is not None:                 # LOCK 시간만 고른 상태 (2026-10-18 사용자 요청)
                if st.button("🔁 근무표 재생성", key=f"regen_lockonly_{index}", width="stretch",
                             help=f"{(17 + lock_start) % 24:02d}시까지는 그대로 두고 그 뒤 시간만 다시 짭니다."):
                    regenerate_lock_only(index, lock_start, history, options)
            else:
                st.button("🔁 근무표 재생성", key=f"regenerate_{index}", width="stretch",
                          on_click=request_night_regeneration,
                          help="현재 생성 조건으로 이전 후보와 다른 근무표를 만듭니다.")

def person_ui_label(person) -> str:
    if person.is_manager and person.employee_id == "A":
        return "통제"
    prefix = person.display_number if person.display_number is not None else "A"
    return f"{prefix} {person.name}"


_DOWNLOAD_SLOT = None
_CHECK_SLOT = None


def field_download(record, key: str, caption: str = "") -> None:
    """현장 양식 이미지 다운로드는 업로드 칸 옆 한 곳에 (2026-10-05 사용자 요청). PC·폰 공통."""
    from night_shift.schedule_image import download_button
    from night_shift import cp_schedule                   # CP 근무표 기본값도 같이 그린다 (2026-10-05)
    cp = cp_schedule.for_day(store_dir(), record.context.shift_start_date, "night")
    slot = _DOWNLOAD_SLOT if _DOWNLOAD_SLOT is not None else st.container()
    with slot:
        if caption:
            st.caption(caption)
        if cp:
            st.caption(cp_schedule.caption(cp))
        download_button(record, key, cp)


def extra_south_input(shift_date, night_name: str) -> tuple[tuple[int, ...], bool]:
    """룰북 5-7 (2026-10-05 사용자 확정): 남문을 원래 안 여는 시간이 있는 회차(N2/N3/N4)는 생성 전에
    'G2 추가 운영 시간'을 꼭 확인받는다. 답하기 전에는 생성 버튼을 잠근다 (PC·폰 공통)."""
    from night_shift.models import extra_south_choices
    choices = extra_south_choices(night_name)
    if not choices:
        return (), True
    hour = lambda t: f"{(18 + t) % 24:02d}시"  # noqa: E731
    key = f"extra_south_{shift_date}_{night_name}"
    st.markdown("**G2 추가 운영이 있나요?**")
    answer = st.radio("남문 G2 추가 운영", ("고르세요", "추가 없음", "추가 있음"), horizontal=True, key=key,
                      label_visibility="collapsed")
    if answer == "추가 있음":
        picked = st.multiselect("G2를 여는 시간 (여러 개 가능)", list(choices), format_func=hour, key=key + "_hours")
        if not picked:
            st.warning("G2를 여는 시간을 골라야 근무표를 만들 수 있습니다.")
        return tuple(sorted(picked)), bool(picked)
    if answer == "고르세요":
        st.warning("남문 G2 추가 운영 여부를 골라야 근무표를 만들 수 있습니다.")
        return (), False
    return (), True


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
                    help="'저장된 실제 이력'은 확정 저장된 근무표의 실제 근무(최근 4회 평균)를 반영합니다. "
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


def schedule_html(result: ServiceResult, compact: bool = False) -> str:
    """Present recorded assignments; all accounting stays in ServiceResult.

    compact: 폰 화면용 — 시간을 세로로 놓아 하루 전체를 화면 너비 안에 표시한다.
    """
    record = result.record
    assert record is not None
    slots = sorted({row.slot for row in record.assignments}, key=lambda slot: slot.index)
    rows = {(row.employee_id, row.slot.index): row for row in record.assignments}
    people = sorted(result.employee_stats.values(), key=lambda p: (not p.is_manager, p.display_number or 0))
    band = flexible_band(record.context)
    if compact:
        return _mobile_overview_html(record, slots, rows, people, band)

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


def _mobile_overview_html(record, slots, rows, people, band) -> str:
    """14시간 × 출근자 전체. 표기 배정은 유지하고 긴 설명은 상세 보기에 둔다."""
    parts = ["<style>.mobile-overview{width:100%;table-layout:fixed;border-collapse:collapse;"
             "background:#fff;color:#111827;font-size:12px;text-align:center}"
             ".mobile-overview th,.mobile-overview td{border:1px solid #fff;padding:1px;"
             "height:25px;line-height:1.1;vertical-align:middle;overflow-wrap:anywhere}"
             ".mobile-overview thead th{height:32px;background:#f1f5f9;font-size:11px}"
             ".mobile-overview tbody th{background:#f1f5f9;font-size:11px}"
             ".mobile-overview small{display:block;font-size:9px;line-height:1.05;font-weight:400}"
             ".mobile-overview .midnight>*{border-top:2px solid #64748b}"
             "</style><table class='mobile-overview' aria-label='야간 하루 전체 근무표'>"
             "<colgroup><col style='width:27px'>" + "<col>" * len(people) + "</colgroup>"
             "<thead><tr><th scope='col'>시</th>"]
    for person in people:
        number = "관리자" if person.is_manager else str(person.display_number or "")
        parts.append(f"<th scope='col' title='{escape(person_ui_label(person), quote=True)}'>"
                     f"{escape(person.name)}<small>{number}</small></th>")
    parts.append("</tr></thead><tbody>")
    short = {"휴게": "휴", "보안실 대기": "대기"}
    for slot in slots:
        parts.append(f"<tr{' class=midnight' if slot.hour == 0 else ''}><th scope='row'>{slot.hour:02d}</th>")
        for person in people:
            row = rows.get((person.employee_id, slot.index))
            if row is None:
                parts.append("<td>—</td>")
                continue
            label, notes, color, _ = assignment_view(row, record.context)
            marker = "↑" if row.barrier_install_flag else "↓" if row.barrier_remove_flag else ""
            rest_post = row.displayed_assignment.kind == AssignmentKind.POST and row.actual_rest_time_value == 1
            if rest_post:
                marker += "·휴"
            elif notes and not marker:
                marker = "*"
            tip = f"{person.name} {slot.hour:02d}시: {label}" + (" · " + " · ".join(notes) if notes else "")
            parts.append(f"<td style='background:#{color};font-weight:600' title='{escape(tip, quote=True)}'>"
                         f"{escape(short.get(label, label))}"
                         f"{f'<small>{escape(marker)}</small>' if marker else ''}</td>")
        parts.append("</tr>")
    parts.append("</tbody></table>")
    return "".join(parts)


def _compact_schedule_html(record, slots, rows, people, band) -> str:
    """폰 전체 표: 이름 열은 고정, 시간 칸은 옆으로 밀어서 본다. 유도리 휴게성 시간대는 시간 머리에 굵은 밑줄."""
    head = ("padding:3px 2px;border:1px solid #cbd5e1;text-align:center;background:#fff;color:#111827;"
            "white-space:nowrap;font-size:.72rem")
    name = f"position:sticky;left:0;z-index:2;{head};font-size:.74rem"
    in_band = lambda t: bool(band) and band[0] <= t <= band[1]  # noqa: E731
    parts = ["<div style='overflow-x:auto;-webkit-overflow-scrolling:touch'>"
             "<table style='border-collapse:collapse;table-layout:fixed;min-width:"
             f"{60 + 46 * len(slots)}px;width:100%'>"
             f"<colgroup><col style='width:60px'>{''.join('<col>' for _ in slots)}</colgroup>"
             f"<thead><tr><th style='{name}'>직원</th>"]
    parts += [f"<th style='{head}{';border-bottom:3px solid #0f172a' if in_band(slot.index) else ''}'>"
              f"{slot.hour:02d}</th>" for slot in slots]
    parts.append("</tr></thead><tbody>")
    for person in people:
        parts.append(f"<tr><th style='{name}'>{escape(person_ui_label(person))}</th>")
        for slot in slots:
            row = rows.get((person.employee_id, slot.index))
            if row is None:
                parts.append("<td style='border:1px solid #e2e8f0;text-align:center'>—</td>")
                continue
            label, notes, color, _ = assignment_view(row, record.context)
            detail = ("<div style='font-size:.56rem;line-height:1.05;color:#334155'>"
                      + escape(" · ".join(notes)) + "</div>") if notes else ""
            parts.append(f"<td style='background:#{color};color:#111827;height:44px;text-align:center;"
                         "vertical-align:middle;padding:1px;border:1px solid #fff;overflow:hidden'>"
                         f"<div style='font-size:.8rem;font-weight:700;line-height:1.1'>{escape(label)}</div>"
                         f"{detail}</td>")
        parts.append("</tr>")
    parts.append("</tbody></table></div>")
    return "".join(parts)


def person_actual_state(row) -> str:
    if row.displayed_assignment.kind == AssignmentKind.UNAVAILABLE:
        state = "근무불가"
    elif row.barrier_install_flag or row.barrier_remove_flag:
        state = "차단봉 설치" if row.barrier_install_flag else "차단봉 철수"
        state += f"(피로도 {row.fatigue_value:g})"
    elif row.actual_post_or_work_type.kind == AssignmentKind.PATROL:
        state = f"순찰(피로도 {row.fatigue_value:g})"
    elif row.actual_rest_time_value == 1:
        state = "휴게" if row.displayed_assignment.kind == AssignmentKind.REST else "휴게성"
        if row.actual_post_or_work_type.kind == AssignmentKind.SECURITY_STANDBY:
            state += " · 보안실 대기"
    else:
        state = {"standing": "입식", "seated": "좌식"}.get(getattr(row.posture_or_mode, "value", None), "실제근무")
        actual = row.actual_post_or_work_type.label
        if row.actual_post_or_work_type.kind == AssignmentKind.POST and actual != row.displayed_assignment.label:
            state += " · 실제 " + actual
    return state


def person_schedule_html(result, employee_id: str) -> str:
    """폰 사람별 보기: 시간 / 표시 배정 / 실제 자세·휴게성."""
    record = result.record
    rows = sorted((r for r in record.assignments if r.employee_id == employee_id), key=lambda r: r.slot.index)
    parts = ["<table class='person-schedule' style='border-collapse:collapse;width:100%;table-layout:fixed'>"
             "<colgroup><col style='width:48px'><col><col></colgroup>"]
    for row in rows:
        label, notes, color, _ = assignment_view(row, record.context)
        state = person_actual_state(row)
        tooltip = escape(" · ".join(notes), quote=True)
        parts.append(
            "<tr><td style='font-weight:700;font-size:.8rem;white-space:nowrap;padding:3px 2px;text-align:center'>"
            f"{row.slot.hour:02d}시</td>"
            f"<td title='{tooltip}' style='background:#{color};color:#111827;padding:5px 8px;height:32px;"
            f"font-size:.9rem;font-weight:700;border-bottom:1px solid #fff'>{escape(label)}</td>"
            f"<td title='{tooltip}' style='background:#{color};color:#111827;padding:5px 8px;font-size:.78rem;"
            f"border-left:1px solid #64748b;border-bottom:1px solid #fff'>{escape(state)}</td></tr>")
    parts.append("</table>")
    return "".join(parts)


def person_timeline_html(result, employee_id: str) -> str:
    """PC 원래 가로 시간표: 최장 실제근무·실휴게 구간을 굵은 테두리로 강조."""
    person = result.employee_stats[employee_id]
    rows = sorted((r for r in result.record.assignments if r.employee_id == employee_id), key=lambda r: r.slot.index)
    work_slots = {index for window in person.longest_actual_work
                  for index in range(window.start_index, window.end_index_exclusive)}
    rest_slots = {index for window in person.longest_rest
                  for index in range(window.start_index, window.end_index_exclusive)}
    # 흰 바탕 패널 (다크모드에서 시간 머리글·칸 글자가 묻히지 않게)
    parts = ["<div style='overflow-x:auto;background:#fff;color:#111827;border-radius:10px;padding:6px'>"
             "<table class='person-timeline' style='border-collapse:separate;border-spacing:4px;width:100%;min-width:1100px'>",
             "<tr>"]
    parts.extend(f"<th style='padding:5px;color:#475569'>{row.slot.hour:02d}</th>" for row in rows)
    parts.append("</tr><tr>")
    for row in rows:
        display_label, notes, color, category = assignment_view(row, result.record.context)
        actual_label = actual_state_label(row)
        status = person_actual_state(row)
        # '휴게 / 휴게성 / 실제 휴게성'처럼 같은 말이 반복되면 '실제 …' 줄은 뺀다
        special = row.actual_post_or_work_type.kind == AssignmentKind.PATROL or row.barrier_install_flag or row.barrier_remove_flag
        differs = not special and row.actual_post_or_work_type.kind == AssignmentKind.POST and actual_label not in (display_label, status) and actual_label not in notes
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
    return "".join(parts)


def render_mobile_schedule(result, key: str) -> None:
    """개인 시간표는 직원 분석에서 통계와 함께 확인한다."""
    st.markdown(schedule_html(result, compact=True), unsafe_allow_html=True)
    st.caption("휴=휴게 · 대기=보안실 · ↑설치 ↓철수 · ·휴=실제 휴게 · *=메모")


NIGHT_HALF_LEAVE_SLOT = 7        # 후반부 반차 = 01시 퇴근


def _night_leaver_hours(index: int, result: ServiceResult) -> dict[str, int]:
    """긴급 반차·이탈자 → 빠지는 시간 칸 (연쇄 재편성 포함, 표 이름 칸 표시용 2026-10-18)."""
    out, params, seen = {}, st.session_state.get("rebalance_params", {}), set()
    results = st.session_state.get("schedule_results", [])
    while index is not None and index not in seen and 0 <= index < len(results):
        seen.add(index)
        info = results[index].rebalance_info
        if info is None:
            break
        out.setdefault(info.unavailable_employee_id, info.unavailable_from_index)
        index = params.get(index, {}).get("source")
    if result.rebalance_info:
        out[result.rebalance_info.unavailable_employee_id] = result.rebalance_info.unavailable_from_index
    return out


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


def _night_steps_html(lock: int | None, short: bool = False) -> str:
    hour = lambda t: f"{(18 + t) % 24:02d}시"  # noqa: E731
    if short:                                   # 폰: 짧은 안내 (2026-10-05)
        items = ([("now", "🚨 긴급: ① 지난 시간 칸 누르기"), ("", "② 이름"), ("", "③ 재편성")] if lock is None
                 else [("done", f"① {hour(lock)}까지 LOCK ✓"), ("now", "② 빠질 사람 이름 누르기")])
    elif lock is None:
        items = [("now", "① 긴급 반차·이탈: 위쪽 파란 시간 칸에서 이미 지나간(진행 중) 마지막 시간을 누르세요"),
                 ("", "② 빠지는 사람 이름 누르기"), ("", "③ 재편성표가 후보에 추가됨")]
    else:
        items = [("done", f"① {hour(lock)}까지 LOCK ✓ (같은 시간을 다시 누르면 취소)"),
                 ("now", "② 빠지는 사람의 이름(노란 칸)을 누르세요"), ("", "③ 재편성표가 후보에 추가됨")]
    return "<div class='steps'>" + "".join(f"<span class='{c}'>{escape(t)}</span>" for c, t in items) + "</div>"


def _night_leave_choices(index: int, result: ServiceResult) -> tuple[list[int], set[str], set[str]]:
    """긴급 반차·이탈에서 LOCK 가능한 시간, 빠질 수 있는 사람, 이미 빠진 사람 (PC 표·폰 입력칸 공통)."""
    info = result.rebalance_info
    floor = info.locked_through_index + 1 if info is not None else 0
    lock_hours = list(range(floor, 13))                  # 07시는 LOCK 뒤에 남는 시간이 없어 제외
    leavers = _night_leavers(index, result)
    handover = result.context.manager_handover
    eligible = {p.employee_id for p in result.employee_stats.values()
                if (not p.is_manager or (p.employee_id == "A" and not handover))
                and not (handover and p.employee_id == handover[1])
                and p.employee_id not in leavers}
    return lock_hours, eligible, leavers


def render_mobile_leave_form(index: int, result: ServiceResult, on_leave) -> None:
    """폰 긴급 반차·이탈 (2026-10-03 사용자 요청): 표 칸 클릭 대신 '몇 시까지 진행 → 누가 → 반차/이탈' 입력칸.
    재편성 엔진·LOCK 규칙은 PC와 같다 (on_leave = start_rebalance). 표 위 '긴급 반차·이탈' 버튼을 켜야 보인다."""
    lock_hours, eligible, _ = _night_leave_choices(index, result)
    if not lock_hours or not eligible:
        return
    hour = lambda t: f"{(18 + t) % 24:02d}시"  # noqa: E731
    from history_ui import emergency_box
    with emergency_box(f"night_emergency_{index}"):   # 표 위 '🚨 긴급 반차·이탈 재편성' 접힌 칸 안 (2026-10-05)
        st.markdown("**입력칸으로 재편성**")
        lock = st.selectbox("① 이미 진행된(진행 중) 마지막 시간 — 여기까지 LOCK", lock_hours,
                            format_func=lambda t: f"{hour(t)}까지 그대로", key=f"m_night_lock_{index}")
        start = lock + 1
        people = sorted((p for p in result.employee_stats.values() if p.employee_id in eligible),
                        key=lambda p: (p.display_number is None, p.display_number or 0))
        names = {p.employee_id: person_ui_label(p) for p in people}
        employee_id = st.selectbox("② 빠지는 사람", list(names), format_func=names.get,
                                   key=f"m_night_pid_{index}")
        kinds = (["half"] if start <= NIGHT_HALF_LEAVE_SLOT else []) + ["leave"]
        labels = {"half": "후반부 반차 (01시 퇴근)", "leave": f"긴급 이탈 ({hour(start)}부터)"}
        choice = st.radio("③ 종류", kinds, format_func=labels.get, horizontal=True, key=f"m_night_kind_{index}")
        st.caption(f"{hour(lock)}까지는 기존 배정을 그대로 두고 {hour(start)}부터 다시 편성합니다. "
                   "재편성표는 후보에 추가됩니다.")
        if st.button("재편성", type="primary", width="stretch", key=f"m_night_rebalance_{index}"):
            on_leave(start, employee_id,
                     "후반부 반차 (01시 퇴근)" if choice == "half" else "긴급 이탈 (선택 시간부터)")


def _saved_rebalance_base(record, history: HistorySelection) -> ServiceResult:
    """저장된 실제 기록을 긴급 재편성 바탕으로 감싼다 (Solver 실행 없음).

    LOCK되는 과거는 실제로 수행한 기록이라 바꾸지 않는다. 재편성 결과 14칸 전체는 run_reoptimization 안에서
    독립 Validator가 다시 검사하므로, 바탕 기록 자체의 룰북 경고 때문에 재편성을 막지 않는다."""
    from night_shift.solver import SolveResult
    return ServiceResult(record.context, SolveResult("SAVED", record, [], True), (), calculate_all_stats(record),
                         prepare_engine_inputs(record.context, history), "2.20")


def _saved_leave_people(record, start: int) -> list:
    """저장본 긴급 반차·이탈에서 start부터 빠질 수 있는 사람 (표 클릭·입력칸 공통)."""
    handover = record.context.manager_handover
    attendance = {a.employee_id: a for a in record.context.attendance}
    return sorted((p for p in calculate_all_stats(record).values()
                   if attendance[p.employee_id].present and attendance[p.employee_id].is_available(start)
                   and (not p.is_manager or (p.employee_id == "A" and not handover))
                   and not (handover and p.employee_id == handover[1])),
                  key=lambda p: (p.display_number is None, p.display_number or 0))


def _run_saved_rebalance(shift_date: date, plan, record, start: int, employee_id: str, half: bool,
                         history: HistorySelection, options: SolveOptions) -> None:
    """저장된 실제 기록에서 재편성. 성공하면 화면 아래 재편성표로, 실패하면 이유를 남긴다 (표 클릭·입력칸 공통)."""
    event = "후반부 반차 (01시 퇴근)" if half and start <= NIGHT_HALF_LEAVE_SLOT else "긴급 이탈 (선택 시간부터)"
    unavailable_from = NIGHT_HALF_LEAVE_SLOT if half and start <= NIGHT_HALF_LEAVE_SLOT else start
    error_key = f"saved_rebalance_error_{shift_date}"
    try:
        with st.spinner("저장된 기록의 LOCK 구간은 그대로 두고 남은 시간대를 재편성 중입니다…"):
            outcome = run_reoptimization(_saved_rebalance_base(record, history), start, employee_id,
                                         unavailable_from, history, options, event)
    except Exception as exc:
        st.session_state[error_key] = [friendly_exception_message(exc, "긴급 재편성")]
        return
    if outcome.valid:
        st.session_state[f"saved_rebalance_{shift_date}_{plan.record_id}"] = outcome
        st.session_state.pop(error_key, None)
        return
    diagnosis = outcome.failure_diagnosis
    conflict = ([conflict_explanation(lambda opts: run_reoptimization(_saved_rebalance_base(record, history), start, employee_id,
                                                                    unavailable_from, history, opts, event), options)]
                if outcome.record is None and outcome.solve_result.status == "INFEASIBLE" else [])   # 10/18
    if outcome.record is None and diagnosis:
        st.session_state[error_key] = [diagnosis.title, diagnosis.summary] + (
            [diagnosis.next_action] if diagnosis.next_action else []) + conflict
    elif outcome.record is None:
        st.session_state[error_key] = [solver_failure_message(outcome.solve_result.status, "긴급 재편성")] + conflict
    else:
        st.session_state[error_key] = ["재편성 결과가 하드룰 검증을 통과하지 못했습니다. 저장된 근무표는 그대로입니다."] + [
            f"- {r}" for r in explain_errors(outcome.validation_errors, outcome.context)]


def saved_leave_handler(shift_date: date, history: HistorySelection, options: SolveOptions) -> dict:
    """render_history_editor의 표 클릭(시간 칸 LOCK → 이름 → 반차·이탈)용."""
    return {"eligible": lambda record, start: {p.employee_id for p in _saved_leave_people(record, start)},
            "run": lambda plan, record, start, pid, half: _run_saved_rebalance(
                shift_date, plan, record, start, pid, half, history, options)}


def render_saved_rebalance(shift_date: date, shown: dict, history: HistorySelection, options: SolveOptions,
                           mobile: bool) -> None:
    """저장된 야간 근무표에서 긴급 반차·이탈 재편성 (2026-10-03 사용자 요청, PC·폰 공통 입력칸).

    결과는 후보로 보여 주고, 확정하면 기존 저장본을 휴지통에 옮긴 뒤 저장한다 (confirm_button 덮어쓰기 확인)."""
    record = shown["actual"]
    hour = lambda t: f"{(18 + t) % 24:02d}시"  # noqa: E731
    lock_hours = list(range(shown["lock"] + 1 if shown["lock"] >= 0 else 0, 13))   # 07시는 남는 시간이 없어 제외
    state_key = f"saved_rebalance_{shift_date}_{shown['plan'].record_id}"   # 저장본이 바뀌면 이전 재편성표는 버림
    saved = st.session_state.get(state_key)
    for line in st.session_state.pop(f"saved_rebalance_error_{shift_date}", None) or []:
        st.error(line)
    from history_ui import emergency_box
    with emergency_box(f"saved_emergency_{shift_date}"):   # 표 위 '🚨 긴급 반차·이탈 재편성' 접힌 칸 안 (2026-10-05)
        st.markdown("**입력칸으로 재편성**")
        if not lock_hours:
            st.caption("LOCK 뒤에 남는 시간이 없습니다.")
            return
        lock = st.selectbox("① 이미 진행된(진행 중) 마지막 시간 — 여기까지 LOCK", lock_hours,
                            format_func=lambda t: f"{hour(t)}까지 그대로", key=f"saved_lock_{shift_date}")
        start = lock + 1
        people = _saved_leave_people(record, start)
        if not people:
            st.caption("이 시간 이후 빠질 수 있는 근무자가 없습니다.")
            return
        names = {p.employee_id: person_ui_label(p) for p in people}
        employee_id = st.selectbox("② 빠지는 사람", list(names), format_func=names.get,
                                   key=f"saved_pid_{shift_date}")
        kinds = (["half"] if start <= NIGHT_HALF_LEAVE_SLOT else []) + ["leave"]
        labels = {"half": "후반부 반차 (01시 퇴근)", "leave": f"긴급 이탈 ({hour(start)}부터)"}
        choice = st.radio("③ 종류", kinds, format_func=labels.get, horizontal=True, key=f"saved_kind_{shift_date}")
        st.caption(f"저장된 실제 기록의 {hour(lock)}까지는 그대로 두고 {hour(start)}부터 다시 편성합니다.")
        if st.button("재편성", type="primary", width="stretch", key=f"saved_rebalance_go_{shift_date}"):
            _run_saved_rebalance(shift_date, shown["plan"], record, start, employee_id, choice == "half",
                                 history, options)
            st.rerun()
    if saved is None:
        return
    info = saved.rebalance_info
    person = saved.employee_stats.get(info.unavailable_employee_id)
    st.markdown("#### 🔒 긴급 재편성표 (아직 저장 안 됨)")
    st.info(f"{hour(info.locked_through_index)}까지 저장된 실제 기록 LOCK · {hour(info.reoptimization_start_index)}부터 "
            f"재편성 · {person_ui_label(person) if person else info.unavailable_employee_id} "
            f"{hour(info.unavailable_from_index)}부터 × · 하드룰 위반 0건")
    render_editable_schedule(state_key, saved, tap_swap=mobile,
                             on_change=lambda updated: st.session_state.__setitem__(state_key, updated))
    field_download(saved.record, f"saved_rebalance_image_{shift_date}", "↓ 긴급 재편성표")
    # 재편성표 특이사항·비고 (2026-10-05 사용자 요청: 저장본 긴급 재편성에도 이유를 보여 줌)
    reasons = balance_reasons(
        saved.record, saved.employee_stats, saved.prepared_inputs, attempts=saved.solve_result.attempts,
        emergency={"employee": info.unavailable_employee_id, "from": info.unavailable_from_index,
                   "reason": info.reason, "locked_through": info.locked_through_index},
        others=night_other_labels(shift_date))
    st.markdown("##### 📝 재편성표 특이사항 · 비고")
    from night_shift.fatigue_ledger_ui import render as render_ledger
    render_ledger(store_dir(), shift_date, current=saved.record, key='saved_rebalance')
    for line in reasons:
        st.markdown("- " + line.replace("~", "\\~"))
    with mobile_ui.action_columns(f"saved_rebalance_{shift_date}") as (confirm_col, drop_col):
        with confirm_col:
            confirm_button(saved, f"saved_rebalance_confirm_{shift_date}", notes=reasons)
        with drop_col:
            if st.button("재편성표 버리기", key=f"saved_rebalance_drop_{shift_date}", width="stretch"):
                st.session_state.pop(state_key, None)
                st.rerun()
    from history_ui import render_recent_fatigue
    render_recent_fatigue(shift_date)


def render_editable_schedule(index, result: ServiceResult, on_leave=None, tap_swap: bool = False, on_change=None,
                             slot=None) -> None:
    """Drag and drop before confirming: real, hard-rule-checked edits.

    on_leave(start, employee_id, event_label): 긴급 반차·이탈 재편성 (주간과 같은 방식 — 표의 시간 칸을 눌러
    LOCK 빗금, 이름을 눌러 반차·이탈 선택).
    tap_swap: 폰(터치) — 끌기 대신 칸(이름)을 차례로 눌러 교환. 같은 교환·검증 함수를 쓴다.
    """
    from night_shift.presentation import barrier_role_summary
    st.caption(barrier_role_summary(result.record))
    lock_key = f"night_lock_{index}"
    if on_leave is not None:                             # 눌러야 켜지는 긴급 반차·이탈 (2026-10-05)
        from history_ui import emergency_toggle
        opened = emergency_toggle(f"night_emergency_{index}",
                                  force=st.session_state.get(lock_key) is not None
                                  or f"night_leave_request_{index}" in st.session_state, lock_key=lock_key)
    else:
        opened = False
    originals = st.session_state.setdefault("generated_originals", {})
    original = originals.get(index)
    baselines = st.session_state.setdefault("generated_initial_results", {})
    if index not in baselines:
        baselines[index] = revalidate(result, original) if original is not None else result
    changed = set()
    if original is not None:
        now = {(r.employee_id, r.slot.index): r for r in result.record.assignments}
        changed = {(r.employee_id, r.slot.index) for r in original.assignments
                   if now.get((r.employee_id, r.slot.index)) != r}
    hint_bar(("✋ 칸을 꾹 누른 채 같은 시간의 다른 칸으로 끌기 → 근무 교환", "👆 이름 누르고 다른 이름 누르기 → 자리 교환",
              "🚫 규칙 위반이면 이유 표시 후 취소", "빗금 = LOCK") if tap_swap else
             ("✋ 칸 끌기 → 근무 교환", "✋ 이름 끌기 → 자리 교환", "🚫 규칙 위반이면 이유 표시 후 취소",
              "빗금 = LOCK"))
    payload = grid_payload(result, {})
    payload["tap_swap"] = tap_swap
    payload["compact"] = tap_swap                        # 폰: 시간 = 줄, 사람 = 열 한 화면 표 (2026-10-05)
    for row in payload["rows"]:
        for cell in row["cells"]:
            cell["changed"] = (row["id"], cell["t"]) in changed
    # 긴급 반차·이탈자는 이름 칸에 빗금 + 'HH시 퇴근' 표시 (2026-10-18 사용자 요청, 생성표·저장표·PC·폰 공통)
    leave_from = _night_leaver_hours(index, result)
    for row in payload["rows"]:
        row["leaver"] = row["id"] in leave_from
    if payload.get("sheet"):
        payload["sheet"]["heads"] = [[pid, f"{name} ({(18 + leave_from[pid]) % 24:02d}시 퇴근)" if pid in leave_from else name]
                                     for pid, name in payload["sheet"].get("heads", [])]
    lock, menus = st.session_state.get(lock_key), {}
    if on_leave is not None and opened:
        lock_hours, eligible, leavers = _night_leave_choices(index, result)
        if lock not in lock_hours:
            lock = st.session_state[lock_key] = None
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
        payload.update(lock_hours=lock_hours, pending_lock=lock, menus=menus, steps_html=_night_steps_html(lock, tap_swap))
    from history_ui import handle_view_event, view_toggle
    view_toggle(payload, result.record, f"night_fmview_{index}")      # 제목 줄 FM·유도리 보기 (2026-10-13)
    from contextlib import nullcontext
    with slot if slot is not None else nullcontext():   # slot: 날짜를 누르면 표가 맨 먼저 보이게 (2026-10-13)
        event = _DRAG_GRID(data=payload, key=f"drag_grid_{index}", default=None)
    if handle_view_event(event, f"night_fmview_{index}"):
        event = None
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
                    if on_change: on_change(updated)
                    else: results[index] = updated
            elif event.get("kind") == "person":
                updated, reasons = swap_person_schedules(result, str(event["source"]), str(event["target"]))
                if updated is None:
                    st.session_state["drag_rejection"] = reasons
                else:
                    originals.setdefault(index, result.record)
                    if on_change: on_change(updated)
                    else: results[index] = updated
            st.session_state["schedule_results"] = results
        except (ValueError, KeyError, IndexError, TypeError) as exc:
            st.session_state["drag_rejection"] = [str(exc) if isinstance(exc, ValueError) else "옮길 수 없는 위치입니다."]
        st.rerun()
    reasons = st.session_state.pop("drag_rejection", None)
    if reasons:
        st.error("이 변경은 적용할 수 없습니다:\n\n" + "\n".join(f"- {r}" for r in reasons))
    if changed:
        st.caption(f"생성 원본과 달라진 칸 {len(changed)}개 (빨간 테두리). 모든 하드룰 검증을 통과한 상태입니다.")
        st.markdown("**수정 반영 요약** (생성 원본 대비 · 직원 분석에도 변화량이 표시됩니다)")
        render_summary_table(result, heading=False, baseline=calculate_all_stats(original),
                             key=f"edit_summary_cols_{index}")
        if on_change is not None or index != st.session_state.get("selected_schedule_index", 0):
            if st.button("↩ 초기 생성표로", key=f"reset_edit_{index}"):
                restore_generated_schedule(index, on_change)
                st.rerun()


def render_summary(result, baseline: dict | None = None, key: str = "analysis") -> None:
    tab_all, tab_person = st.tabs(("전체 비교", "직원 상세분석"))
    with tab_all:
        render_summary_table(result, heading=False, baseline=baseline, key=f"{key}_columns")
    with tab_person:
        render_summary_detail(result, f"{key}_employee", heading=False)


SUMMARY_COLUMNS = (
    ("실근무", "actual_work_time_value", ""), ("실휴게", "actual_rest_time_value", ""),
    ("피로도", "fatigue_value", ""), ("입식", "post_standing", ""), ("좌식", "post_seated", ""),
    ("순찰 피로도", "patrol_fatigue", ""), ("기타 피로도", "other_fatigue", ""), ("순찰 횟수", "patrol_count", ""), ("표시 포스트", "displayed_post_total", ""),
    ("가용시간", "available_time", ""), ("근무부담률", "workload_rate", "%"),
    ("실제 업무 연속시간", "max_actual_work_run", "시간"),
    ("연속근무 제한 적용시간", "max_rule_work_run", "시간"),
    ("최대 연속 실휴게", "max_rest_run", "시간"),
)


def _summary_value(p, attr):
    value = getattr(p, attr)
    return value * 100 if attr == "workload_rate" else value


def _other_fatigue_text(p, number: str | None = None) -> str:
    """기타 피로도 칸: '숫자 (사유)' — 입식×2·좌식×1·순찰로 설명 안 되는 칸의 시간·사유 (2026-10-05 사용자 요청)."""
    number = number if number is not None else f"{p.other_fatigue:g}"
    reasons = getattr(p, "other_fatigue_reasons", ())
    return f"{number} ({', '.join(reasons)})" if reasons else number


def _patrol_text(p, number: str | None = None) -> str:
    """순찰 피로도 칸: 숫자만, 하층 순찰이 있으면 '1 (하층)' (2026-10-05 사용자 요청)."""
    number = number if number is not None else f"{p.patrol_fatigue:g}"
    return f"{number} (하층)" if "하층" in getattr(p, "patrol_reasons", ()) else number


CORE_SUMMARY = ("직원", "실근무", "실휴게", "피로도", "입식", "좌식", "순찰 피로도", "기타 피로도")


def render_summary_table(result, heading: bool = True, baseline: dict | None = None,
                         key: str = "summary_all_columns") -> None:
    """전 직원 핵심 비교. With ``baseline`` (stats before edits) changed values are marked."""
    stats = sorted(result.employee_stats.values(), key=lambda p: (not p.is_manager, p.display_number or 0))
    if heading:
        st.subheader("전 직원 핵심 비교")
    show_all = st.toggle("모든 열 보기", key=key, help="표시 포스트, 가용시간, 근무부담률, 연속시간까지 보기")
    order = None if show_all else list(CORE_SUMMARY)
    st.caption("피로도 = 입식×2 + 좌식×1 + 순찰 피로도(상·중층 2점, 하층 1점) + 기타 피로도. 기타 괄호 안에 그 칸의 "
               "시간·사유를 적습니다(보안실 대기 차단봉 +1, 유도리 04시 철수 칸, 현장 피로도 주석 등).")
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
            row["기타 피로도"] = _other_fatigue_text(p, row["기타 피로도"])
            row["순찰 피로도"] = _patrol_text(p, row["순찰 피로도"])
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
    st.dataframe(pd.DataFrame([{
        "직원": person_ui_label(p),
        **{label: _summary_value(p, attr) for label, attr, _ in SUMMARY_COLUMNS},
        "기타 피로도": _other_fatigue_text(p),
        "순찰 피로도": _patrol_text(p),
    } for p in stats]), hide_index=True, width="stretch", column_order=order, column_config={
        "피로도": st.column_config.NumberColumn("피로도", format="%g"),
        "실근무": st.column_config.NumberColumn("실근무", format="%g"),
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
    values = (("실근무", person.actual_work_time_value, "시간"),
              ("실휴게", person.actual_rest_time_value, "시간"),
              ("피로도", person.fatigue_value, "점"),
              ("입식", person.post_standing, "시간"),
              ("좌식", person.post_seated, "시간"),
              ("순찰", person.patrol_count, "회"))
    cards = "".join(f"<div class='staff-stat'><span>{label}</span><strong>{value:g}<small>{unit}</small></strong></div>"
                    for label, value, unit in values)
    st.markdown("<style>.staff-stats{display:grid;grid-template-columns:repeat(6,minmax(0,1fr));gap:4px;margin:4px 0 8px}"
                ".staff-stat{border:1px solid #8884;border-radius:6px;padding:5px 6px}"
                ".staff-stat span{display:block;font-size:.72rem;opacity:.8}"
                ".staff-stat strong{font-size:1rem}.staff-stat small{font-size:.65rem;font-weight:400;margin-left:3px}"
                "@media(max-width:640px){.staff-stats{grid-template-columns:repeat(3,minmax(0,1fr))}}"
                "</style><div class='staff-stats'>" + cards + "</div>", unsafe_allow_html=True)
    cells = [r for r in result.record.assignments if r.employee_id == selected_id]
    barrier_points = sum(r.fatigue_value for r in cells if r.barrier_install_flag or r.barrier_remove_flag)
    post_points = person.fatigue_value - person.patrol_fatigue - barrier_points
    st.caption(f"입식·좌식은 포스트만 집계 · 피로도: 포스트 {post_points:g} + 순찰 {person.patrol_fatigue:g} + 차단봉 {barrier_points:g}")
    if mobile_ui.is_mobile():
        st.markdown(person_schedule_html(result, selected_id), unsafe_allow_html=True)
    else:
        st.markdown(person_timeline_html(result, selected_id), unsafe_allow_html=True)
        st.caption("굵은 테두리: 최장 실제근무·실휴게 구간")
        work_col, rest_col = st.columns(2)
        work_col.markdown("**최장 실제근무:** " + (run_text(person.longest_actual_work) or "없음"))
        rest_col.markdown("**최장 실휴게:** " + (run_text(person.longest_rest) or "없음"))
        st.caption("연속근무 제한 적용구간: " + (run_text(person.longest_rule_work) or "없음"))
    with st.expander("연속시간 · 포스트 횟수", expanded=False):
        st.caption(f"가용 {person.available_time:g}시간 · 근무부담률 {person.workload_rate * 100:.1f}% · "
                   f"표시 포스트 {person.displayed_post_total:g}시간")
        st.caption("포스트 횟수: " + " · ".join(f"{label} {count}회" for label, count in person.displayed_counts.items() if count))
        if mobile_ui.is_mobile():
            st.write("최장 실제근무:", run_text(person.longest_actual_work) or "없음")
            st.write("최장 실휴게:", run_text(person.longest_rest) or "없음")
            st.write("연속근무 제한 적용구간:", run_text(person.longest_rule_work) or "없음")


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


def _lock_regen_start(index: int) -> int | None:
    """LOCK만 고른 재생성의 시작 시간 칸: 지금 고른 LOCK 시간 다음 칸, 없으면 이 후보가 LOCK 재생성으로 만든 것일 때 그 값."""
    picked = st.session_state.get(f"night_lock_{index}")
    if picked is not None:
        return int(picked) + 1
    return st.session_state.get("lock_regen_params", {}).get(index, {}).get("start")


def regenerate_lock_only(index: int, start: int, history: HistorySelection, options: SolveOptions) -> None:
    """빠지는 사람 없이 LOCK까지 그대로 두고 남은 시간만 다른 후보로 (2026-10-18 사용자 요청)."""
    results = list(st.session_state.get("schedule_results", []))
    all_params = st.session_state.setdefault("lock_regen_params", {})
    source = all_params.get(index, {}).get("source", index)
    params = {"source": source, "start": start}
    siblings = [results[i] for i in {source, index, *(i for i, p in all_params.items() if p == params)}
                if i < len(results)]
    started = perf_counter()
    try:
        with st.spinner(f"{(17 + start) % 24:02d}시까지는 그대로 두고 남은 시간을 다시 짜는 중입니다…"):
            outcome = run_lock_regeneration(results[index], start, history, options,
                                            exclude=exclusion_payloads(siblings) or None)
    except Exception as exc:
        st.session_state["regen_message"] = friendly_exception_message(exc, "LOCK 재생성")
        st.rerun()
    st.session_state["elapsed"] = perf_counter() - started
    if outcome.valid:
        all_params[len(results)] = params
        st.session_state.pop(f"night_lock_{index}", None)
        st.session_state["schedule_results"] = [*results, outcome]
        st.session_state["pending_selected_schedule_index"] = len(results)
        st.session_state["last_result"] = outcome
        st.session_state["run_state"] = "생성 완료"
    elif outcome.record is None and outcome.solve_result.status == "INFEASIBLE":
        st.session_state["regen_message"] = (
            f"{(17 + start) % 24:02d}시까지 그대로 둔 조건에서는 이미 만든 후보와 충분히 다른 근무표가 더 없습니다. "
            "LOCK 이후 남은 시간이 짧으면 다른 해가 나오기 어렵습니다.")
    elif outcome.record is None:
        st.session_state["regen_message"] = solver_failure_message(outcome.solve_result.status, "LOCK 재생성")
    else:
        st.session_state["regen_message"] = "재생성 결과가 하드룰 검증을 통과하지 못했습니다: " + ", ".join(
            explain_errors(outcome.validation_errors, outcome.context))
    st.rerun()


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
    chips = "".join(f"<span style='display:block;background:#F1F5F9;border:1px solid #E2E8F0;"
                    f"border-radius:999px;padding:3px 9px;font-size:.78rem;line-height:1.5;"
                    f"color:#334155;max-width:100%;box-sizing:border-box;overflow-wrap:anywhere'>{escape(i)}</span>"
                    for i in items)
    st.markdown(f"<div class='night-hints' style='display:flex;flex-wrap:wrap;align-items:flex-start;"
                f"gap:6px;line-height:1.5;padding-bottom:12px;margin-bottom:8px'>{chips}</div>",
                unsafe_allow_html=True)


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


MORE_COLOR, LESS_COLOR = "#F97316", "#3B82F6"      # 피로도 많이(주황)·적게(파랑) — 밝은/어두운 화면 모두 보이게
MORE_WORDS = ("더 맡", "많이 맡", "많이 받", "높게 편성", "더 많이")
LESS_WORDS = ("낮게 편성", "덜 맡", "덜 받", "적게 받", "적게 맡", "손해 보상")


def note_lines_html(reasons: list[str], record=None) -> list[str]:
    """특이사항·비고 줄 (2026-10-13 사용자 요청): 그날 피로도를 남들보다 많이/적게 받은 내용은 글자색으로.
    맨 위에 '오늘 피로도 많이/적게' 요약 한 줄(온전 출근 일반근무자 최고·최저, 차이 있을 때만)."""
    out = []
    if record is not None:
        stats = calculate_all_stats(record)
        full = [p for p in stats.values() if not p.is_manager and p.available_time == 14]
        values = [p.fatigue_value for p in full]
        if len(full) >= 2 and max(values) > min(values):
            high = [p for p in full if p.fatigue_value == max(values)]
            low = [p for p in full if p.fatigue_value == min(values)]
            names = lambda ps: "·".join(escape(p.name) for p in ps)
            out.append(f"- 오늘 피로도 — <b style='color:{MORE_COLOR}'>많이: {names(high)}({max(values):g}점)</b>"
                       f" · <b style='color:{LESS_COLOR}'>적게: {names(low)}({min(values):g}점)</b>")
    for line in reasons:
        text = escape(line).replace("~", "\\~")
        color = (LESS_COLOR if any(w in line for w in LESS_WORDS)
                 else MORE_COLOR if any(w in line for w in MORE_WORDS) else None)
        out.append(f"- <span style='color:{color};font-weight:600'>{text}</span>" if color else "- " + text)
    return out


def flexible_note_numbers(reasons: list[str], record) -> tuple[list[str], object]:
    """유도리 보기용 비고 (2026-10-13 사용자 확정): 점수가 들어간 줄만 유도리로 다시 계산한 표 기준으로 바꾼다.
    '밸런스 판정 —' 줄과 그 아래 '· 피로도:/· 실휴게:' 설명 → 유도리 숫자(정수 나눗셈 한계 설명만 유지).
    배정 이유를 설명하는 줄(보상·차단봉·순찰·07시 휴게 등)은 모드와 무관하므로 그대로. 반환: (줄, 유도리 기록)."""
    from night_shift.balance_notes import balance_verdict
    from night_shift.service import flexible_view
    flex = flexible_view(record)
    verdict = [line for line in balance_verdict(flex, calculate_all_stats(flex))
               if line.startswith("밸런스 판정") or "똑같이 나눌 수 없습니다" in line]
    out, skipping, replaced = [], False, False
    for line in reasons:
        if line.startswith("밸런스 판정 —"):
            out += verdict if not replaced else []
            skipping = replaced = True
            continue
        if skipping and line.startswith(("· 피로도:", "· 실휴게:")):
            continue
        skipping = False
        out.append(line)
    return out, flex


def render_balance_notes(reasons: list[str], monthly_rows: list[dict], duties=None, shift_date=None, record=None,
                         view_key: str | None = None, caption: str | None = None, extras=()) -> None:
    """Page bottom: why someone gained or lost balance, and the monthly direction."""
    st.divider()
    st.markdown("#### 📝 특이사항 · 비고")
    if shift_date is not None:
        from night_shift.fatigue_ledger_ui import render as render_ledger
        render_ledger(store_dir(), shift_date, current=record)
    if len(reasons) > 1 and "특이사항 없음." in reasons:
        reasons = [line for line in reasons if line != "특이사항 없음."]
    from history_ui import view_mode
    if record is not None and view_key and view_mode(view_key, record) == "유도리":   # 표 제목 줄 '유도리' 보기
        reasons, record = flexible_note_numbers(reasons, record)
        st.caption("🟣 유도리 기준 숫자입니다(오늘 피로도 많이/적게·밸런스 판정). 배정 이유 설명은 FM·유도리 같습니다.")
    if caption:                                   # 2026-10-20: 저장 당시 문장인지 현재 규칙 계산인지 표시
        st.caption(caption)
    for line in note_lines_html(reasons, record):
        st.markdown(line, unsafe_allow_html=True)
    for title, lines in extras:                   # 현재 규칙 기준 다시 계산·참고 검사 (접힌 칸, PC·폰 공통)
        with st.expander(title, expanded=False):
            for line in lines or ["차이 없음."]:
                st.markdown("- " + str(line).replace("~", "\\~"))
    if duties is not None and not duties.empty:
        st.markdown("**근무자별 최근 3싸이클 차단봉·순찰**")
        st.caption("차단봉 집계는 2026년 10월 4일 야간부터 계산합니다.")
        st.markdown(duty_grid_html(duties), unsafe_allow_html=True)
        st.caption("합계 열은 이번 근무를 뺀 최근 6근무 기준입니다. 근무표 생성은 상층·중층 순찰은 이 6근무에서 "
                   "밤당 덜 맡은 사람에게, 차단봉은 마지막으로 설치·철수한 날이 오래된 사람에게, 하층 순찰은 "
                   "마지막 하층 뒤 다른 층 순찰 3회 이상(공휴일 주간 포함)인 사람 중 마지막 하층이 오래된 사람에게 먼저 줍니다.")
    if shift_date is not None:                     # 막타임(07시) 휴게 표 — 비고 문장 대신 순찰표처럼 (2026-10-13 사용자 요청)
        from history_ui import last_rest_table_html
        html = last_rest_table_html(shift_date, record)
        if html:
            st.markdown("**근무자별 최근 3싸이클 막타임(07시) 휴게**")
            st.markdown(html, unsafe_allow_html=True)
    with st.expander("🧭 앞으로의 편성 방향 (월간 기록 기준)", expanded=False):
        from history_ui import link_night_dates               # 날짜 누르면 그 근무표로 (2026-10-13 사용자 요청)
        year = shift_date.year if shift_date is not None else date.today().year
        for line in monthly_direction(monthly_rows):
            st.markdown("- " + link_night_dates(line, year).replace("~", "\\~"), unsafe_allow_html=True)
    if shift_date is not None:
        from history_ui import render_recent_fatigue
        render_recent_fatigue(shift_date)


def history_store_exists(day) -> bool:
    return _history_store.exists(store_dir(), day)


def main() -> None:
    st.set_page_config(page_title="근무표 자동 생성기", layout="wide")
    mobile = mobile_ui.is_mobile()               # 폰 화면: 사이드바 대신 본문 맨 위 '근무 조건' 칸
    if mobile:
        mobile_ui.apply_style()
    import os
    from night_shift.order_source import SOURCE_DIR, sync_leave
    try:
        # 업무일지 폴더 연차일정은 실제 저장소에만 반영한다(별도 저장 폴더를 지정한 실행은 그 폴더 자료 그대로).
        if not os.environ.get("NIGHT_SHIFT_HISTORY_DIR") or os.environ.get("NIGHT_SHIFT_SOURCE_DIR"):
            folder = os.environ.get("NIGHT_SHIFT_SOURCE_DIR") or SOURCE_DIR
            if not os.environ.get("NIGHT_SHIFT_SOURCE_DIR"):  # 카톡으로 받은 연차일정이 더 최신이면 그것 (2026-10-11)
                from night_shift.kakao_sync import leave_folder
                folder = leave_folder(folder)
            sync_leave(store_dir(), folder)
    except (OSError, ValueError) as exc:
        st.warning(f"자료 폴더 연차일정 확인 필요: {exc}")
    # 카톡으로 받은 최신 편성표 자동 반영 (2026-10-11 사용자 요청). 실제 저장소에서만, 새 파일일 때만 읽는다.
    if not os.environ.get("NIGHT_SHIFT_HISTORY_DIR"):
        from night_shift import kakao_sync
        try:
            if kakao_sync.newest() is not None:
                with st.spinner("카톡으로 받은 편성표 확인 중…"):
                    message = kakao_sync.sync(store_dir())
                if message:
                    st.session_state["kakao_sync_message"] = message
        except PermissionError:
            st.caption("카톡 편성표 파일이 다른 프로그램에서 쓰는 중이라 다음에 다시 확인합니다.")
        except (OSError, ValueError) as exc:
            st.warning(f"카톡 편성표를 반영하지 못했습니다(기존 자료 유지): {exc}")
    if st.session_state.get("kakao_sync_message"):
        st.success(st.session_state["kakao_sync_message"])
        if st.button("확인", key="kakao_sync_ok"):
            st.session_state.pop("kakao_sync_message", None)
            st.rerun()
    from history_ui import apply_fatigue_navigation
    apply_fatigue_navigation()
    # 프로그램 맨 위 탭 (2026-10-06 사용자 요청): 근무표와 근태관리 일보를 분리
    tab = st.segmented_control("화면", ("🗓 근무표", "📋 근태관리 일보", "📝 보안근무명령서", "📅 연차일정"), default="🗓 근무표",
                               key="app_tab", label_visibility="collapsed") or "🗓 근무표"
    if tab != "🗓 근무표":
        if tab == "📋 근태관리 일보":
            import daily_report_ui
            daily_report_ui.page()
        elif tab == "📝 보안근무명령서":
            import security_order_ui
            security_order_ui.page()
        else:                                    # 연차일정 한눈에 보기 (2026-10-06 사용자 요청)
            import leave_view_ui
            leave_view_ui.page()
        mobile_ui.view_switch()
        return
    global _CHECK_SLOT
    _CHECK_SLOT = st.container()                 # 날짜를 고르면 문서 대조 결과 (맨 위, 2026-10-07)
    title_slot = st.empty()                      # 날짜를 고른 뒤 주간/야간 제목으로 채움
    badge_slot = st.container()
    if mobile:
        current_day = st.session_state.get("shift_date")
        has_output = bool(st.session_state.get("schedule_results") or st.session_state.get("day_results")
                          or (current_day and (history_store_exists(current_day)
                                               or _history_store.exists(day_store_dir(), current_day))))
        side = mobile_ui.controls(expanded=not has_output)
    else:
        side = st.sidebar
    if st.session_state.get("flash"):
        st.success(st.session_state.pop("flash"))
    st.session_state.setdefault("schedule_results", [])
    st.session_state.setdefault("selected_schedule_index", 0)
    st.session_state.setdefault("display_numbers", {})
    _night_page(mobile, side, title_slot, badge_slot)
    if mobile:                                   # 폰: 휴지통 (근무 조건 칸 안에는 접힘 칸을 넣을 수 없어 맨 아래)
        render_trash("mobile")
    mobile_ui.view_switch()


def _night_page(mobile: bool, side, title_slot, badge_slot) -> None:
    """날짜 선택 → (주간이면 주간 화면) → 야간 조건·생성·근무표. side = 사이드바 또는 폰의 '근무 조건' 칸."""
    from import_ui import render_importer                 # 폰에서도 엑셀·이미지 이력 가져오기
    global _DOWNLOAD_SLOT
    _DOWNLOAD_SLOT = render_importer()                    # 업로드 옆 현장 양식 다운로드 자리
    if message := st.session_state.pop("import_saved_message", None):
        st.success(message)
    with side:
        if not mobile:
            st.header("근무 조건")
        st.session_state.setdefault("shift_date", next_night(date.today()))
        saved = sorted(set(_history_store.list_dates(store_dir()))
                       | set(_history_store.list_dates(day_store_dir()))
                       | set(_history_store.list_dates(day_store_dir().parent / "weekend_day")))   # 주말 주간 (2026-10-13)
        picked = _CALENDAR(data={
            "selected": st.session_state["shift_date"].isoformat(), "today": date.today().isoformat(),
            "saved": [d.isoformat() for d in saved], "pattern_start": PATTERN_START.isoformat(),
            "weddings": [d.isoformat() for d in wedding.load(store_dir())],   # 💒 웨딩 있는 날 (2026-10-13)
            "holidays": {d.isoformat(): name for d, name in HOLIDAYS.items()},
            "year_from": 2025, "year_to": max(2028, date.today().year + 1),
        }, key="shift_calendar", default=None)
        if isinstance(picked, dict) and picked.get("nonce") != st.session_state.get("calendar_nonce"):
            st.session_state["calendar_nonce"] = picked.get("nonce")
            st.session_state["shift_date"] = date.fromisoformat(picked["date"])
            st.rerun()
        shift_date = st.session_state["shift_date"]
        if _CHECK_SLOT is not None:
            import date_check_ui
            with _CHECK_SLOT:
                date_check_ui.banner(shift_date)
                try:                                  # 지난 빨간날 주간 유도리 운영 여부 확인 (2026-10-18, 고르지 않으면 유도리)
                    from weekend_day_ui import flex_confirm_banner
                    flex_confirm_banner()
                except Exception as exc:              # 배너 하나 때문에 화면 전체가 멈추지 않게
                    st.caption(f"유도리 운영 확인 배너를 표시하지 못했습니다: {exc}")
        # Night type follows the chosen date (N1~N4) unless the user changes it afterwards.
        if st.session_state.get("night_type_date") != shift_date:
            st.session_state["night_type_date"] = shift_date
            st.session_state["night_type_select"] = night_type_for(shift_date)
        from night_shift.leave_schedule import refresh_manual_inputs
        refresh_manual_inputs(st.session_state, store_dir(), shift_date, "night")
        if st.session_state.get("night_status_date") != shift_date:      # 연차일정 → 상태 기본값 (2026-10-04)
            st.session_state["night_status_date"] = shift_date
            apply_night_leave_defaults(shift_date)
        kind = shift_kind(shift_date)
        holiday = holiday_name(shift_date)
        st.markdown(f"**근무 기준일 {shift_date:%Y-%m-%d} ({'월화수목금토일'[shift_date.weekday()]})** · "
                    f"{PATTERN_LABELS[kind]}" + (f" · 🔴 {holiday}" if holiday else "")
                    + "  \n<span style='font-size:.75rem;color:#64748b'>18시 시작 야간 기준</span>",
                    unsafe_allow_html=True)
        has_saved = history_store_exists(shift_date)
        day_page = kind == "주" and not is_off_day(shift_date)
        title_slot.title("주간 근무표 자동 생성기" if kind == "주" else
                         ("야간 근무표" if mobile else "야간 근무표 자동 생성기"))
        if kind == "주" and not day_page:
            st.info("주말·공휴일 주간근무입니다.")
            return_early = False
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
    if kind == "주" and not day_page:
        render_weekend_day_page(shift_date, badge_slot, side, mobile)
        return
    if day_page:
        render_day_page(shift_date, badge_slot, side, mobile)
        return
    if mobile:
        mobile_ui.apply_night_style()
    with side:
        mode_name = st.radio("운영 모드", ("FM", "유도리"), horizontal=True)
        post_operations = flexible_operations_input(side) if mode_name == "유도리" else None
        night_name = st.selectbox("야간 유형", tuple(n.value for n in NightType),
                                  format_func=night_type_label, key="night_type_select",
                                  help="날짜를 고르면 평일/주말·공휴일에 맞춰 자동으로 정해집니다. 필요하면 바꿀 수 있습니다.")
        manager = st.radio("관리자 상태", MANAGER_STATES, key="manager_state",
                           help="전반부: 00시까지 준호가 대행, 01시 통제A 출근. 후반부: 01시 통제A 퇴근, 이후 준호가 대행.")
        a_present = manager != "A 결근 (준호 대행)"        # 후반부 반차도 A 출근(00시까지)
        late_half = manager == MANAGER_LATE_HALF
        early_half = manager == MANAGER_EARLY_HALF
        manager_half = late_half or early_half
        st.subheader("야간 근무자")
        # 주간과 같은 표: 이름·상태·역할. 상태만 고치고, 상태는 session_state["night_statuses"]에 보관.
        statuses = st.session_state.setdefault("night_statuses", {})

        def night_role(employee_id, name):
            if employee_id == "6" and not a_present:
                return "관리자 대행"
            if employee_id == "6" and early_half:
                return "관리자 대행 (~00시)"
            if employee_id == "6" and late_half:
                return "관리자 대행 (01시~)"
            return "선임" if name == "준호" else "일반"   # 준호 = 선임 (룰북 8-8)
        if mobile:
            new_statuses = {eid: statuses.get(eid, NIGHT_STATUSES[0]) for eid, _ in ROSTER}
            if not a_present or manager_half:
                new_statuses["6"] = NIGHT_STATUSES[0]
            event = _ROSTER_PICKER(rows=[{
                "id": eid, "name": name, "status": new_statuses[eid],
                "role": night_role(eid, name), "locked": eid == "6" and (not a_present or manager_half)
            } for eid, name in ROSTER], options=NIGHT_STATUSES, key="night_roster", default=None)
            if isinstance(event, dict) and event.get("nonce") != st.session_state.get("night_roster_nonce"):
                st.session_state["night_roster_nonce"] = event.get("nonce")
                eid, status = event.get("employee"), event.get("status")
                if eid in new_statuses and status in NIGHT_STATUSES and ((a_present and not manager_half) or eid != "6"):
                    new_statuses[eid] = status
                    st.session_state["night_statuses"] = new_statuses
                    st.rerun()
        else:
            edited = st.data_editor(
                pd.DataFrame([{"이름": name, "상태": statuses.get(employee_id, "출근"),
                               "역할": night_role(employee_id, name)} for employee_id, name in ROSTER]),
                hide_index=True, num_rows="fixed", width="stretch", disabled=("이름", "역할"), key=f"night_roster_{shift_date}",
                column_config={"상태": st.column_config.SelectboxColumn(options=NIGHT_STATUSES, required=True)})
            new_statuses = {employee_id: (row["상태"] or "출근")
                            for (employee_id, _), (_, row) in zip(ROSTER, edited.iterrows())}
        if (not a_present or manager_half) and new_statuses["6"] != "출근":
            st.warning("A 결근·반차면 준호가 관리자 대행이라 출근으로 고정합니다.")
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
        night_other_notes_input(shift_date, new_statuses)
        for line in st.session_state.get("leave_notices", []):
            st.caption("📅 " + line)
        st.caption("상태에서 연차·전반부 반차(01시 출근)·후반부 반차(01시 퇴근)·기타(근무 제외 + 비고)를 고릅니다. "
                   "통제A는 위 '관리자 상태'로 정하고, A 결근이면 준호가 관리자 대행이라 출근이 필수입니다.")
        general = tuple(p for p in staff if p.present and p.is_general_worker)
        # 과거 이력은 항상 저장된 실제 이력 (2026-10-08 사용자 확정: '이력 입력' 칸 없앰, 반영 날짜만 상세 설정 안에)
        has_history = bool(stored_before(shift_date))
        history = (_history_store.history_selection(_history_store_path(), shift_date) if has_history
                   else HistorySelection(long_term_records=()))
        with st.expander("생성 상세 설정"):
            st.caption(history_caption(shift_date) if has_history
                       else "이 날짜 전 저장된 실제 근무 이력이 없어 이력 없이 생성합니다.")
            seconds = int(st.number_input("Solver 제한시간 (초)", min_value=5, max_value=300,
                                          value=45, step=5))
            prioritize_history = st.checkbox("당일 목표 안에서 이력 균형 우선", value=False)
        extra_south, south_confirmed = extra_south_input(shift_date, night_name)
        generate = st.button("근무표 생성", type="primary", width="stretch", key="generate_button",
                             on_click=rotate_display_numbers, disabled=not south_confirmed)
        if not mobile:
            render_trash("side")

    request = ShiftRequest(shift_date, NightType(night_name),
                           Mode.FM if mode_name == "FM" else Mode.FLEXIBLE, staff, post_operations=post_operations,
                           extra_south_slots=extra_south)
    options = SolveOptions(rules_version="2.20", seconds=seconds,
                           prioritize_history_within_daily_targets=prioritize_history)
    signature = (condition_signature(request, history, options), st.session_state.get("manager_state"))
    if st.session_state.get("input_signature") != signature:
        st.session_state["input_signature"] = signature
        st.session_state["schedule_results"] = []
        st.session_state["generated_originals"] = {}
        st.session_state["generated_initial_results"] = {}
        st.session_state["rebalance_params"] = {}
        st.session_state["lock_regen_params"] = {}
        st.session_state["selected_schedule_index"] = 0
        st.session_state["last_result"] = None
        st.session_state["run_state"] = "입력 확인 후 생성"
        st.session_state["run_error"] = None
        st.session_state["elapsed"] = None
        for key in [k for k in st.session_state if str(k).startswith("night_fmview_") and not str(k).endswith("_nonce")]:
            del st.session_state[key]                      # 새 조건 → 처음 보기는 FM (2026-10-13)
    regenerate_requested = st.session_state.pop("night_regenerate_requested", False)
    if generate or regenerate_requested:
        prior_results = st.session_state.get("schedule_results", [])
        st.session_state.pop(f"night_fmview_{len(prior_results)}", None)   # 새로 생성한 표는 FM 보기부터
        excluded = exclusion_payloads(prior_results) or None
        st.session_state["run_state"] = "생성 중"
        st.session_state["run_error"] = None
        started = perf_counter()
        try:
            with st.spinner("근무표 생성 및 하드룰 검증 중입니다…"):
                runner = (run_schedule_manager_early_half if st.session_state.get("manager_state") == MANAGER_EARLY_HALF
                          else run_schedule_manager_half if st.session_state.get("manager_state") == MANAGER_LATE_HALF
                          else run_schedule)               # A 후반부 반차: 01시부터 준호 관리자 대행 (10/18)
                outcome = runner(request, history, replace(options, exclude_assignments=excluded))
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
                    if outcome.solve_result.status == "INFEASIBLE":        # 막는 규칙 자동 진단 (2026-10-18)
                        st.session_state["run_error"] += "  \n" + conflict_explanation(
                            lambda opts: runner(request, history, opts), options)
            else:
                st.session_state["last_result"] = outcome
                st.session_state["run_state"] = "검증 실패"
                st.session_state["run_error"] = f"Validator 오류 {len(outcome.validation_errors)}건. 이 결과는 정상 근무표로 표시하지 않습니다."
        except Exception as exc:
            st.session_state["elapsed"] = perf_counter() - started
            st.session_state["run_state"] = "실행 오류"
            st.session_state["run_error"] = friendly_exception_message(exc, "근무표 생성")
        if mobile:                                  # 폰: '근무 조건' 칸을 접고 결과부터 보이게
            st.rerun()

    schedule_results: list[ServiceResult] = st.session_state.get("schedule_results", [])
    pending_selection = st.session_state.pop("pending_selected_schedule_index", None)
    if pending_selection is not None:
        st.session_state["selected_schedule_index"] = pending_selection
    selected_index = st.session_state.get("selected_schedule_index", 0)
    selected_result: ServiceResult | None = (
        schedule_results[selected_index] if schedule_results and selected_index < len(schedule_results) else None
    )
    summary_items = (
        ("기준 날짜", f"{shift_date} ({'월화수목금토일'[shift_date.weekday()]})"),
        ("야간 유형", night_type_label(selected_result.context.night_type if selected_result else night_name)),
        ("룰북", rulebook_label(selected_result.rules_version if selected_result else options.rules_version)),
        ("생성 상태", st.session_state["run_state"]),
        ("검증 상태", "하드룰 통과 · 위반 0건" if selected_result and selected_result.valid else
         f"위반 {len(selected_result.validation_errors)}건" if selected_result and selected_result.validation_errors
         else "미검증"))
    if mobile:
        mobile_ui.summary_line(value for _, value in summary_items)
    else:
        for column, (label, value) in zip(st.columns(5), summary_items):
            column.metric(label, value)
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
        from night_shift.source_attachment import label as source_label
        source_kind = source_label(_history_store.load(store_dir(), shift_date) or {})
        if mobile:
            st.caption(f"📅 {shift_date} 저장된 근무표 ({source_kind})")
        else:
            st.subheader(f"📅 {shift_date} 저장된 근무표 ({source_kind})")
        # 폰도 PC와 같은 저장본 화면 (실제 근무 교환·피로도·포스트별 운영·수정 내역·저장·되돌리기)
        shown = render_history_editor("saved", _DRAG_GRID, shift_date, render_summary_table, render_summary_detail,
                                      mobile=mobile, leave=saved_leave_handler(shift_date, history, options))
        if shown:
            field_download(shown["actual"], f"saved_image_{shift_date}")
            render_saved_rebalance(shift_date, shown, history, options, mobile)
        with st.expander("📊 월간 기록", expanded=False):
            monthly_rows = render_monthly(shift_date)
        if shown:
            record = shown["actual"]
            try:
                prepared = prepare_engine_inputs(record.context, _history_store.history_selection(store_dir(), shift_date))
            except Exception:
                prepared = None
            plan = shown["plan"]
            all_note = [line for line in (shown.get("note") or "").splitlines() if line.strip()]
            # 2026-10-20 사용자 확정: 업로드 당시 규칙으로 검사한 경고줄('[규칙] …')은 기본 화면에서 뺀다
            # (손대지 않은 업로드 저장본은 생성 규칙 검사 대상 아님). 필요하면 접힌 칸에서 현재 규칙으로 다시 검사.
            note_lines = [line for line in all_note if not line.startswith("[")]
            # 2026-10-05 사용자 확정: 특이사항은 생성(저장) 당시 표 기준. 현장에서 생긴 교환·피로도 주석 변동은
            # 넣지 않고 월간 분석에서 날짜·사람·시간·사유로 따로 설명한다.
            current = balance_reasons(
                plan, calculate_all_stats(plan), prepared, manual=bool(shown.get("source")),
                emergency=({**(shown["rebalance"] or {}), "locked_through": shown["lock"]}
                           if shown["lock"] >= 0 else None), others=night_other_labels(shift_date))
            snapshot = (shown.get("snapshot") or {}).get("lines")
            extras = []
            if snapshot:      # 2026-10-20: 확정 당시 문장을 그대로, 지금 규칙으로 다시 계산한 문장이 다르면 접힌 칸
                body, caption = list(snapshot), f"확정 저장 당시 특이사항입니다({(shown['snapshot'].get('saved_at') or '')[:10]})."
                if [x for x in current if x not in snapshot]:
                    extras.append(("🔄 현재 규칙으로 다시 계산한 특이사항", current))
            else:
                body = current
                caption = ("업로드한 현장 실제 근무표입니다. 아래 설명은 현재 프로그램 기준으로 계산합니다."
                           if shown.get("source") else
                           "이 저장본에는 확정 당시 문장이 없어 현재 규칙 기준으로 계산한 설명입니다.")
            if shown.get("source"):
                from night_shift.models import HistoryInput as _HistoryInput
                from night_shift.schedule_edit import explain_errors as _explain
                from night_shift.validator import validate_first_trial as _validate
                try:
                    checked = _explain(_validate(plan, _HistoryInput((), ()), rules_v220=True), plan.context)
                except Exception as exc:          # 참고 검사 실패가 화면을 막지 않게
                    checked = [f"참고 검사를 하지 못했습니다: {exc}"]
                hidden = len(all_note) - len(note_lines)
                extras.append(("🔎 현재 규칙으로 참고 검사(업로드 원본은 생성 규칙 검사 대상 아님)",
                               (checked or ["현재 규칙 기준 위반 없음."])
                               + ([f"(업로드 당시 규칙으로 적힌 경고 {hidden}줄은 숨겼습니다.)"] if hidden else [])))
            render_balance_notes(note_lines + body, monthly_rows,
                duty_frame(shift_date, record), shift_date, record, view_key=f"saved_fmview_{shift_date}",
                caption=caption, extras=extras)
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
    tabs = st.tabs(("근무표", "직원 분석", "검증 결과", "월간 기록"))
    with tabs[0]:
        if schedule_results:
            labels = [schedule_choice_label(index, item)
                      for index, item in enumerate(schedule_results)]
            selected_index = st.radio("표시할 근무표", range(len(schedule_results)),
                                      format_func=lambda index: labels[index],
                                      key="selected_schedule_index", label_visibility="collapsed" if mobile else "visible") if not mobile or len(schedule_results) > 1 else 0
            selected_result = schedule_results[selected_index]
            table_slot = st.container()                 # 근무표를 맨 먼저, 확정·안내 등은 표 아래 (2026-10-13)
            st.session_state["last_result"] = selected_result
            params = st.session_state.setdefault("rebalance_params", {}).get(selected_index)
            if mobile:
                pass                                # 폰: 확정 버튼은 표를 본 뒤 (표 아래)
            else:
                confirm_and_regenerate(selected_result, selected_index, params, history, options)
            if st.session_state.get("regen_message"):
                st.warning(st.session_state.pop("regen_message"))
            st.caption(("" if mobile else "후보를 선택하면 요약·검증 결과도 같은 근무표로 바뀝니다. ")   # PC·폰 공통 색상 설명
                       + "색상: 휴게(회색), 보안실(파랑), G1(초록), L3(파랑), I1(노랑), 남문(빨강), 순찰(보라), 차단봉(분홍).")
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
                    f"{unavailable_hour:02d}시부터 ×" + (f"  \n{info.reason}" if "차단봉" in (info.reason or "") else "")
                )
                # 긴급 재편성은 순찰 뒤 회복을 가능하면 지킬 규칙으로 (2026-10-18 사용자 확정) → 못 지킨 곳 안내
                from night_shift.service import patrol_recovery_misses
                misses = patrol_recovery_misses(selected_result.record, info.reoptimization_start_index)
                if misses:
                    st.warning("남은 인원으로 순찰 뒤 2시간 회복을 다 지킬 수 없어 최소로 어긴 곳(긴급 재편성만 허용):  \n"
                               + "  \n".join("· " + m for m in misses))
            elif selected_index in st.session_state.get("lock_regen_params", {}):
                lock_start = st.session_state["lock_regen_params"][selected_index]["start"]
                st.info(f"LOCK 재생성 후보 · {(17 + lock_start) % 24:02d}시까지 기존 배정 그대로 · "
                        f"{(18 + lock_start) % 24:02d}시부터 다시 짠 표 (빠지는 사람 없음, 일반 생성 규칙으로 검증)")
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
                        if outcome.solve_result.status == "INFEASIBLE":       # 막는 규칙 자동 진단 (2026-10-18)
                            st.warning(conflict_explanation(lambda opts: run_reoptimization(
                                selected_result, rebalance_start, employee_id, unavailable_from, history, opts, event), options))
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
                if mobile:
                    st.caption("✅ FM·유도리 모두 만족 · 피로도 차이 ≤1점 · 실휴게 차이 ≤1시간")
                else:
                    st.success("✅ FM·유도리 모두 만족 — 현장에서 유도리(I1 22~03시 휴게성)로 운영하게 되어도 "
                           "하드룰 위반이 없고, 두 기준 모두 일반근무자 피로도 차이 1점·실휴게 차이 1시간 이하입니다.")
            elif selected_result.dual_mode is True:                                          # 2단계
                st.info("FM·유도리 하드룰은 모두 만족 — 다만 두 기준 모두 밸런스 목표(피로도 1점·실휴게 1시간 이하)를 "
                        f"맞추는 표는 없었습니다. ({spread_text('FM')} / {spread_text('유도리')})")
            elif selected_result.dual_mode is False:
                st.warning("FM만 만족 — 이 조건에서는 유도리로 운영해도 되는 표를 찾지 못해 FM 기준으로만 만들었습니다. "
                           "현장에서 유도리로 바뀌면 유도리로 다시 생성해 주세요.")
            if mobile:                              # 폰: PC와 같은 기능 — 보기·눌러서 교환·LOCK 클릭·확정·긴급 재편성
                render_editable_schedule(selected_index, selected_result, on_leave=start_rebalance, tap_swap=True,
                                         slot=table_slot)
                confirm_and_regenerate(selected_result, selected_index, params, history, options)
                render_mobile_leave_form(selected_index, selected_result, start_rebalance)
            else:
                render_editable_schedule(selected_index, selected_result, on_leave=start_rebalance, slot=table_slot)
            field_download(selected_result.record, f"generated_image_{selected_index}")
            if len(schedule_results) > 1:
                st.subheader("이전에 생성한 근무표")
                for index, candidate in enumerate(schedule_results):
                    if index == selected_index:
                        continue
                    with st.expander(labels[index], expanded=False):
                        st.button("이 근무표 선택", key=f"select_schedule_{index}",
                                  on_click=select_schedule, args=(index,))
                        render_editable_schedule(index, candidate, tap_swap=mobile)
        else:
            st.info("검증을 통과한 근무표가 없습니다. "
                    + ("위 '근무 조건'을 열어 조건을 확인하고 생성해 주세요." if mobile
                       else "왼쪽에서 조건을 선택하고 생성해 주세요."))
    with tabs[1]:
        if selected_result and selected_result.valid:
            original = st.session_state.get("generated_originals", {}).get(selected_index)
            from history_ui import view_mode, view_record
            view_key = f"night_fmview_{selected_index}"
            if view_mode(view_key, selected_result.record) == "유도리":   # 표 제목 줄 '유도리' 버튼 (2026-10-13)
                st.caption("🟣 유도리 기준으로 다시 계산한 값입니다(배정은 같음, 유도리 적용 칸은 휴게성·좌식 회계). "
                           "근무표 탭 표 제목 줄의 'FM'을 누르면 FM 기준으로 돌아갑니다.")
                flex = view_record(selected_result.record, view_key)
                # record는 solve_result.record에서 읽는 속성이라 solve_result를 바꾼다 (2026-10-18 TypeError 수정)
                shown_result = replace(selected_result, solve_result=replace(selected_result.solve_result, record=flex),
                                       employee_stats=calculate_all_stats(flex))
                baseline = calculate_all_stats(view_record(original, view_key)) if original is not None else None
            else:
                shown_result = selected_result
                baseline = calculate_all_stats(original) if original is not None else None
            render_summary(shown_result, baseline, key=f"analysis_{view_mode(view_key, selected_result.record)}")
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
        reasons = candidate_reasons(selected_result, selected_index)
        render_balance_notes(reasons, monthly_rows, duty_frame(shift_date, selected_result.record), shift_date,
                             selected_result.record, view_key=f"night_fmview_{selected_index}")


if __name__ == "__main__":
    main()
