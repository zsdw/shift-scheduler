"""Application boundary around the unchanged scheduling and validation engines.

UI and exporters consume ServiceResult. This module prepares inputs and derives
read-only summaries; it does not decide staffing rules or validate assignments.
"""
from collections import Counter
from dataclasses import dataclass, replace
from datetime import date
from typing import Mapping

from .models import (
    AssignmentKind, Attendance, Employee, HistoryInput, Mode, NightType, GENERATION_POST_OPERATIONS,
    Posture, RecordKind, ShiftContext, ShiftRecord, barrier_v2, barrier_history_counts,
)
from .common import compile_common_policy
from .preferences import avoid_cells, preference_weights
from .profiles import _installer_post, make_record
from .soft_history import patrol_rotation_due
from .solver import SolveResult, solve_first_trial
from .validator import validate_first_trial
from .leave_context import reoptimization_half_day_ids


SERVICE_API_VERSION = "2.21.86"         # 사람이 읽는 표시용. 앱 재로딩은 app.py 엔진 파일 지문으로 자동 (2026-10-18)
from .engine_fingerprint import engine_fingerprint as _engine_fingerprint
ENGINE_FINGERPRINT = _engine_fingerprint()   # 이 엔진을 불러온 시점의 파일 지문 (app.py 재로딩 판단, 2026-10-19)


def rulebook_label(rules_version: str) -> str:
    """화면·엑셀에 보이는 룰북 표기. 엔진 분기값 "2.20"은 v2.21 룰북 전체를 구현한다
    (v2.21 조항은 별도 분기값 없이 2.20 경로에 들어감)."""
    return "v2.21" if rules_version == "2.20" else f"v{rules_version}"


POST_LABELS = ("G1", "L3", "I1", "G2", "G3", "G2(1)")
HISTORY_TOTAL_KEYS = (
    "fatigue_value", "standing", "seated", "actual_work_time_value",
    "actual_rest_time_value", "patrol_fatigue",
)


@dataclass(frozen=True)
class StaffInput:
    employee_id: str
    name: str
    present: bool
    is_general_worker: bool
    display_number: int | None
    acts_as_manager: bool
    available_slot_indices: tuple[int, ...] | None = None


@dataclass(frozen=True)
class ShiftRequest:
    shift_start_date: date
    night_type: NightType
    requested_mode: Mode
    staff: tuple[StaffInput, ...]
    day_instructions: tuple[str, ...] = ()
    # 유도리 포스트별 운영 (None = 룰북 기본). models.ShiftContext.post_operations 참고.
    post_operations: tuple[tuple[str, int, int, str], ...] | None = None
    # 5-7 추가 남문 G2 슬롯 (생성 전 사용자 확인값). models.ShiftContext.extra_south_slots 참고.
    extra_south_slots: tuple[int, ...] = ()


@dataclass(frozen=True)
class HistorySelection:
    """Explicitly selected history; assumed totals are never called actuals.

    `actual_records` are confirmed shifts selected upstream. `assumed_*` can
    hold a user-approved comparison such as 27 September's FM estimate.
    `previous_*` overrides are supplied explicitly when that comparison is used
    for immediate predecessor constraints. None means derive from latest actual.
    """
    actual_records: tuple[ShiftRecord, ...] = ()
    assumed_totals: Mapping[str, Mapping[str, int | float]] | None = None
    assumed_nights: Mapping[str, int] | None = None
    soft_debt: Mapping[str, Mapping[str, int]] | None = None
    previous_install_ids: tuple[str, ...] | None = None
    previous_remove_ids: tuple[str, ...] | None = None
    previous_last_rest_ids: tuple[str, ...] | None = None
    previous_patrol_exclusion_ids: tuple[str, ...] | None = None
    forbid_install_ids: tuple[str, ...] | None = None
    # Per-record weights for actual_records (same order), e.g. 0.3/0.3/0.2/0.2
    # for the last two cycles (5:5 since 2026-10-13). None = every night counts equally.
    actual_weights: tuple[float, ...] | None = None
    # Up to six recent actual nights (3 cycles) for barrier/patrol-zone balance.
    duty_records: tuple[ShiftRecord, ...] = ()
    patrol_events: tuple = ()
    last_rest_records: tuple = ()
    long_term_records: tuple | None = None  # 10/04부터 전체 실제 기록. None=레거시 직접 호출


@dataclass(frozen=True)
class SolveOptions:
    rules_version: str = "2.13"
    seconds: int = 30
    prioritize_history_within_daily_targets: bool = False
    manager_a_end_slot: int = 14
    # One legacy flat schedule or multiple schedules. Display numbers are not
    # part of an exclusion: employee_id + slot + complete assignment state is.
    exclude_assignments: tuple[dict, ...] | tuple[tuple[dict, ...], ...] | None = None
    locked_assignments: tuple | None = None
    diagnostic_relaxation_level: int = 0
    # v2.20 §21-8: relax only the listed rule families (single-family probe).
    diagnostic_relaxed_families: tuple[int, ...] | None = None
    # Cells (employee_id, slot) that must be actual rest (manager handover boundary).
    forced_rest_cells: tuple[tuple[str, int], ...] = ()
    # 룰북 0-2-1: FM이면 'FM·유도리 모두 만족' 해를 먼저 찾고, 없으면 FM만 만족하는 해.
    prefer_dual_mode: bool = True
    # H-17 일시 해제 (2명 완전결원 + 해 없음일 때만 run_schedule이 켠다)
    relax_post_cap: bool = False
    # H-09-1 미리 정한 반차자 (None = 계획 생성이면 반차자 전원, 긴급 재편성은 원래 표의 반차자만)
    half_day_ids: tuple[str, ...] | None = None
    manager_a_start_slot: int = 0
    # 긴급 반차·이탈자의 빠지기 전 남은 칸 (자리 형태, 2026-10-18): 배려 없이 실근무·입식 많게(최후순위)
    emergency_leaver_cells: tuple[tuple[str, int], ...] = ()
    # 충돌 진단 전용 (2026-10-18): 끌 하드 규칙 묶음, 목표 없이 해 유무만 보기. 실제 생성에서는 기본값 그대로.
    disabled_rule_groups: tuple[str, ...] = ()
    feasibility_only: bool = False
    # 🧪 테스트 생성 버튼 전용(2026-10-23 사용자 요청): 관리자 우대 확대 시험 규칙. 실제 생성에서는 항상 False.
    test_manager_relief: bool = False


@dataclass(frozen=True)
class RebalanceInfo:
    source_record_id: str
    reoptimization_start_index: int
    locked_through_index: int
    unavailable_employee_id: str
    unavailable_from_index: int
    reason: str


@dataclass(frozen=True)
class FailureDiagnosis:
    kind: str
    title: str
    summary: str
    relaxation_level: str | None = None
    exceptions: tuple[str, ...] = ()
    next_action: str = ""


@dataclass(frozen=True)
class RunWindow:
    start_index: int
    end_index_exclusive: int
    display_labels: tuple[str, ...]
    actual_labels: tuple[str, ...]
    postures: tuple[Posture | None, ...]
    detail_labels: tuple[str, ...] = ()

    @property
    def hours(self) -> int:
        return self.end_index_exclusive - self.start_index


@dataclass(frozen=True)
class EmployeeStats:
    employee_id: str
    name: str
    display_number: int | None
    is_manager: bool
    fatigue_value: float
    actual_work_time_value: float
    actual_rest_time_value: float
    standing: int
    seated: int
    patrol_count: int
    patrol_fatigue: float
    displayed_post_total: int
    displayed_counts: Mapping[str, int]
    posture_by_post: Mapping[str, Mapping[str, int]]
    max_actual_work_run: int
    max_rule_work_run: int
    max_rest_run: int
    longest_actual_work: tuple[RunWindow, ...]
    longest_rule_work: tuple[RunWindow, ...]
    longest_rest: tuple[RunWindow, ...]
    available_time: int
    workload_rate: float
    # 화면 자세 통계: 순찰·차단봉을 제외한 순수 포스트 실근무만 집계.
    # standing/seated는 기존 이력 엔진 입력 의미를 유지한다.
    post_standing: int = 0
    post_seated: int = 0
    # 입식(칸당 2)·좌식(칸당 1)·순찰 점수로 설명되지 않는 나머지 피로도 (2026-10-05 사용자 요청):
    # 대기 차단봉 1점, 표시와 실제가 다른 특수 칸, 현장 피로도 주석 등
    other_fatigue: float = 0
    other_fatigue_reasons: tuple[str, ...] = ()
    patrol_reasons: tuple[str, ...] = ()      # 하층 순찰이 있으면 ('하층',) — 순찰 피로도 칸 괄호 표시용


@dataclass(frozen=True)
class PreparedEngineInputs:
    engine_history: HistoryInput
    actual_record_count: int
    assumed_history_used: bool
    historical_totals: Mapping[str, Mapping[str, int | float]] | None
    historical_nights: Mapping[str, int] | None
    forbid_install_ids: tuple[str, ...]
    forbid_last_rest_ids: tuple[str, ...]
    forbid_patrol_exclusion_ids: tuple[str, ...]
    patrol_rotation_priority_ids: tuple[str, ...]
    previous_install_ids: tuple[str, ...]
    previous_remove_ids: tuple[str, ...]
    soft_debt: Mapping[str, Mapping[str, int]] | None
    # 3-cycle duty rates ×100 per night: {"barrier"|"upper"|"middle"|"lower": {id: rate}}
    duty_rates: Mapping[str, Mapping[str, int]] | None = None
    # 17-1 선호 (2026-10-02): 공통 선호 보너스 가중치 {id: weight}, 개인 회피 칸 ((id, slot, label), ...)
    history_fatigue_averages: Mapping[str, float] | None = None
    preference_weights: Mapping[str, int] | None = None
    avoid_cells: tuple[tuple[str, int, str], ...] = ()
    patrol_actuals: tuple = ()
    patrol_events: tuple = ()
    last_rest_records: tuple = ()
    long_term_balances: Mapping | None = None


DUTY_METRICS = ("barrier", "upper", "middle", "lower")


def duty_rates_from(records, general_ids) -> dict | None:
    """Per-night rate (×100) of barrier duty and each patrol zone over recent nights."""
    if not records:
        return None
    counts = {m: {p: 0 for p in general_ids} for m in DUTY_METRICS}
    nights = {p: 0 for p in general_ids}
    barrier_nights = {p: 0 for p in general_ids}
    for record in records:
        present = {a.employee_id for a in record.context.attendance if a.present}
        for p in general_ids:
            if p not in present:
                continue
            nights[p] += 1
            rows = [r for r in record.assignments if r.employee_id == p]
            if barrier_history_counts(record.context):
                barrier_nights[p] += 1
                counts["barrier"][p] += sum(r.barrier_install_flag or r.barrier_remove_flag for r in rows)
            for r in rows:
                if r.actual_post_or_work_type.kind == AssignmentKind.PATROL and r.actual_post_or_work_type.label in counts:
                    counts[r.actual_post_or_work_type.label][p] += 1
    rates = {}
    for m in DUTY_METRICS:
        metric_nights = barrier_nights if m == "barrier" else nights
        seen = [counts[m][p] / metric_nights[p] for p in general_ids if metric_nights[p]]
        team = sum(seen) / len(seen) if seen else 0
        rates[m] = {p: round(100 * (counts[m][p] / metric_nights[p] if metric_nights[p] else team)) for p in general_ids}
    return rates


def mixed_zone_rates(rates, events, names, general_ids, window: int = 6):
    """14-8 (2026-10-20 사용자 확정): 상·중·하층 순찰 횟수는 야간 + 공휴일 주간을 같은 그룹으로,
    최근 6근무(날짜·주야 순)에서 각자 출근한 근무당 비율(×100). 층 정보가 없는 이벤트면 기존 야간 값 유지."""
    if not events or not all('zones' in e for e in events):
        return rates
    slots = sorted({(e['date'], e['shift']) for e in events})[-window:]
    recent = [e for e in events if (e['date'], e['shift']) in set(slots)]
    out = {k: dict(v) for k, v in (rates or {}).items()}
    for zone in ("upper", "middle", "lower"):
        per = {}
        for p in general_ids:
            mine = [e for e in recent if e['name'] == str(names.get(p, p))[-2:]]
            if mine:
                per[p] = sum(zone in e['zones'] for e in mine) / len(mine)
        team = sum(per.values()) / len(per) if per else 0
        out[zone] = {p: round(100 * per.get(p, team)) for p in general_ids}
    return out


@dataclass(frozen=True)
class ServiceResult:
    context: ShiftContext
    solve_result: SolveResult
    validation_errors: tuple[dict, ...]
    employee_stats: Mapping[str, EmployeeStats]
    prepared_inputs: PreparedEngineInputs
    rules_version: str
    rebalance_info: RebalanceInfo | None = None
    failure_diagnosis: FailureDiagnosis | None = None
    # 룰북 0-2-1: True = FM·유도리 하드룰 모두 만족(유도리 Validator도 0건), False = FM만 만족, None = 해당 없음
    dual_mode: bool | None = None
    # dual_mode=True일 때: 두 기준 모두 17장 당일 목표(피로도 1점·실휴게 1시간 이하)까지 만족했는지와 실제 차이
    dual_balanced: bool | None = None
    dual_spreads: Mapping[str, Mapping[str, int]] | None = None
    # H-17(같은 포스트 최대 3번)을 2명 완전결원 예외로 이 회차만 해제했는지
    post_cap_relaxed: bool = False
    # 🧪 테스트 규칙이 이 표에 실제로 적용됐는지(다음날 평일·통제A 온전 출근·결원 0~1명일 때만)
    test_manager_relief: bool = False
    # 🧪 테스트 생성 버튼으로 만든 후보(규칙 적용 여부와 무관) — 화면에서 확정 저장을 막는다
    test_requested: bool = False

    @property
    def record(self) -> ShiftRecord | None:
        return self.solve_result.record

    @property
    def valid(self) -> bool:
        return self.record is not None and not self.validation_errors


def build_context(request: ShiftRequest) -> ShiftContext:
    """Map UI fields to the existing model, without inferring a night type."""
    employees = tuple(Employee(p.employee_id, p.name) for p in request.staff)
    attendance = tuple(Attendance(p.employee_id, p.present, p.is_general_worker,
                                  p.display_number, p.acts_as_manager,
                                  p.available_slot_indices) for p in request.staff)
    mode = Mode(request.requested_mode)
    return ShiftContext(request.shift_start_date, NightType(request.night_type), mode,
                        mode, employees, attendance, day_instructions=request.day_instructions,
                        post_operations=(request.post_operations if request.post_operations is not None
                                         else GENERATION_POST_OPERATIONS),
                        extra_south_slots=tuple(sorted(request.extra_south_slots)))


def consecutive_runs(rows, *, rule=False, rest=False):
    """Return contiguous read-only windows from recorded accounting fields."""
    if rule and rest:
        raise ValueError("Choose either rule-work or rest runs")
    blocks, block = [], []
    for row in sorted(rows, key=lambda r: r.slot.index):
        counted = (row.actual_rest_time_value == 1 if rest else
                   row.counts_for_continuous_work_restriction or row.actual_post_or_work_type.kind == AssignmentKind.PATROL
                   if rule else row.actual_work_time_value == 1)
        if counted:
            if block and row.slot.index != block[-1].slot.index + 1:
                blocks.append(tuple(block)); block = []
            block.append(row)
        elif block:
            blocks.append(tuple(block)); block = []
    if block:
        blocks.append(tuple(block))
    return tuple(blocks)


def _window(rows) -> RunWindow:
    return RunWindow(rows[0].slot.index, rows[-1].slot.index + 1,
                     tuple(r.displayed_assignment.label for r in rows),
                     tuple(r.actual_post_or_work_type.label for r in rows),
                     tuple(r.posture_or_mode for r in rows),
                     tuple(("차단봉 설치" if r.barrier_install_flag else "차단봉 철수") + f"(피로도 {r.fatigue_value:g})"
                           if r.barrier_install_flag or r.barrier_remove_flag else
                           f"순찰(피로도 {r.fatigue_value:g})" if r.actual_post_or_work_type.kind == AssignmentKind.PATROL else ""
                           for r in rows))


def _longest(rows, *, rule=False, rest=False):
    blocks = consecutive_runs(rows, rule=rule, rest=rest)
    maximum = max((len(b) for b in blocks), default=0)
    return maximum, tuple(_window(b) for b in blocks if len(b) == maximum)


def calculate_employee_stats(record: ShiftRecord, employee_id: str) -> EmployeeStats:
    person = next(p for p in record.context.employees if p.employee_id == employee_id)
    attendance = next(a for a in record.context.attendance if a.employee_id == employee_id and a.present)
    rows = tuple(r for r in record.assignments if r.employee_id == employee_id)
    if len(rows) != 14:
        raise ValueError(f"Expected 14 assignments for {employee_id}")
    # 포스트 근무 칸 (G2·I1 근무자가 겸임한 차단봉 칸도 포스트로 셈, 2026-10-05 15-0). 대기 차단봉은 별도(BARRIER_ONLY).
    pure_posts = tuple(r for r in rows if r.actual_work_time_value == 1
                       and r.actual_post_or_work_type.kind == AssignmentKind.POST)
    other_reasons = []                       # 기타 피로도 사유 (입식×2·좌식×1·순찰 점수로 설명 안 되는 칸)
    patrol_reasons = []                      # 순찰 피로도 내역 (시간·구역·점수)
    for r in rows:
        hour = f"{(18 + r.slot.index) % 24:02d}시"
        if r.actual_post_or_work_type.kind == AssignmentKind.PATROL:
            # 순찰 점수는 '순찰 피로도' 칸에 시간·구역과 함께 (기타에 넣지 않음, 사용자 요청)
            if r.actual_post_or_work_type.label == "lower":   # 사용자 요청: 하층만 '(하층)'으로 표시
                patrol_reasons.append("하층")
            continue
        expected = (2 if r.posture_or_mode == Posture.STANDING else 1 if r.posture_or_mode == Posture.SEATED else 0) \
            if r in pure_posts else 0
        diff = r.fatigue_value - expected
        if not diff:
            continue
        shown, actual = r.displayed_assignment.label, r.actual_post_or_work_type.label
        if r.actual_post_or_work_type.kind == AssignmentKind.BARRIER_ONLY:
            why = f"{hour} 대기 차단봉{'설치' if r.barrier_install_flag else '철수'}"
        elif r in pure_posts and r.posture_or_mode not in (Posture.STANDING, Posture.SEATED):
            why = f"{hour} {shown}(유도리 04시 철수 칸)"
        elif r in pure_posts:
            why = f"{hour} {shown} 현장 피로도 주석"
        else:
            why = f"{hour} {shown}{'→' + actual if actual != shown else ''} 현장 피로도 주석"
        other_reasons.append(f"{why} {diff:+g}")
    counts = Counter(r.displayed_assignment.label for r in rows)
    posture_by_post = {
        label: {
            "standing": sum(r.displayed_assignment.label == label and r.posture_or_mode == Posture.STANDING for r in pure_posts),
            "seated": sum(r.displayed_assignment.label == label and r.posture_or_mode == Posture.SEATED for r in pure_posts),
        } for label in POST_LABELS
    }
    max_work, work_windows = _longest(rows)
    max_rule, rule_windows = _longest(rows, rule=True)
    max_rest, rest_windows = _longest(rows, rest=True)
    patrol_rows = tuple(r for r in rows if r.actual_post_or_work_type.kind == AssignmentKind.PATROL)
    available_time = sum(r.displayed_assignment.kind != AssignmentKind.UNAVAILABLE for r in rows)
    actual_work = sum(r.actual_work_time_value for r in rows)
    return EmployeeStats(
        employee_id=employee_id, name=person.name, display_number=attendance.display_number,
        is_manager=attendance.acts_as_manager,
        fatigue_value=sum(r.fatigue_value for r in rows),
        actual_work_time_value=actual_work,
        actual_rest_time_value=sum(r.actual_rest_time_value for r in rows),
        standing=sum(r.actual_work_time_value == 1 and r.posture_or_mode == Posture.STANDING for r in rows),
        seated=sum(r.actual_work_time_value == 1 and r.posture_or_mode == Posture.SEATED for r in rows),
        patrol_count=len(patrol_rows), patrol_fatigue=sum(r.fatigue_value for r in patrol_rows),
        displayed_post_total=sum(counts[label] for label in POST_LABELS),
        displayed_counts=dict(counts), posture_by_post=posture_by_post,
        max_actual_work_run=max_work, max_rule_work_run=max_rule, max_rest_run=max_rest,
        longest_actual_work=work_windows, longest_rule_work=rule_windows, longest_rest=rest_windows,
        available_time=available_time,
        workload_rate=(actual_work / available_time if available_time else 0),
        post_standing=sum(r.posture_or_mode == Posture.STANDING for r in pure_posts),
        post_seated=sum(r.posture_or_mode == Posture.SEATED for r in pure_posts),
        other_fatigue=(sum(r.fatigue_value for r in rows)
                       - 2 * sum(r.posture_or_mode == Posture.STANDING for r in pure_posts)
                       - sum(r.posture_or_mode == Posture.SEATED for r in pure_posts)
                       - sum(r.fatigue_value for r in patrol_rows)),   # 순찰 점수는 '순찰 피로도' 칸
        other_fatigue_reasons=tuple(other_reasons),
        patrol_reasons=tuple(patrol_reasons),
    )


def calculate_all_stats(record: ShiftRecord) -> dict[str, EmployeeStats]:
    return {a.employee_id: calculate_employee_stats(record, a.employee_id)
            for a in record.context.attendance if a.present}


def prepare_engine_inputs(context: ShiftContext, selection: HistorySelection) -> PreparedEngineInputs:
    """Normalize explicitly selected history for the current trial engine API."""
    actuals = tuple(selection.actual_records)
    for record in actuals:
        if record.kind != RecordKind.ACTUAL or record.confirmed_at is None:
            raise ValueError("Selected history must contain confirmed actual shifts")
        if record.context.shift_start_date >= context.shift_start_date:
            raise ValueError("History must precede the requested shift")
    general_ids = tuple(a.employee_id for a in context.attendance if a.present and a.is_general_worker)
    if (selection.assumed_totals is None) != (selection.assumed_nights is None):
        raise ValueError("Assumed totals and attendance counts must be supplied together")
    if selection.assumed_totals is not None:
        if any(set(values) != set(general_ids) for values in selection.assumed_totals.values()) or set(selection.assumed_nights) != set(general_ids):
            raise ValueError("Assumed history must identify every present general worker")
    included_keys = HISTORY_TOTAL_KEYS if actuals else tuple((selection.assumed_totals or {}).keys())
    totals = {key: {p: 0 for p in general_ids} for key in included_keys}
    nights = {p: 0 for p in general_ids}
    if selection.assumed_totals is not None:
        for key, values in selection.assumed_totals.items():
            if key not in HISTORY_TOTAL_KEYS:
                raise ValueError(f"Unknown history total: {key}")
            for p in general_ids:
                totals[key][p] += values[p]
        for p in general_ids:
            nights[p] += selection.assumed_nights[p]
    # 반차·이탈자는 당일 온전 출근 일반근무자 평균으로 피로도 이력만 대입한다.
    # 실제 저장본·그 외 업무 지표는 변경하지 않는다.
    def history_fatigue(actual_stats, pid):
        person = actual_stats[pid]
        full = [p.fatigue_value for p in actual_stats.values()
                if not p.is_manager and p.available_time == 14]
        return sum(full) / len(full) if person.available_time < 14 and full else person.fatigue_value

    fatigue_weighted = {p: 0.0 for p in general_ids}
    fatigue_weights = {p: 0.0 for p in general_ids}
    for actual, weight in zip(actuals, selection.actual_weights or (1.0,) * len(actuals)):
        actual_stats = calculate_all_stats(actual)
        for pid in general_ids:
            if pid in actual_stats:
                fatigue_weighted[pid] += weight * history_fatigue(actual_stats, pid)
                fatigue_weights[pid] += weight
    averages = {p: fatigue_weighted[p] / fatigue_weights[p] for p in general_ids if fatigue_weights[p]}
    weights = selection.actual_weights
    if weights is not None and len(weights) != len(actuals):
        raise ValueError("History weights must match the selected actual records")
    if weights is None:
        for actual in actuals:
            actual_stats = calculate_all_stats(actual)
            for p in general_ids:
                if p not in actual_stats:
                    continue
                stats = actual_stats[p]
                nights[p] += 1
                for key in included_keys:
                    totals[key][p] += (history_fatigue(actual_stats, p) if key == "fatigue_value" else getattr(stats, key))
    else:
        # Weighted per-night average over the nights each person attended,
        # re-expressed as a total over those nights for the engine's
        # (prior + current) / (nights + 1) balance.
        weighted = {key: {p: 0.0 for p in general_ids} for key in included_keys}
        weight_sum = {p: 0.0 for p in general_ids}
        for actual, weight in zip(actuals, weights):
            actual_stats = calculate_all_stats(actual)
            for p in general_ids:
                if p not in actual_stats:
                    continue
                nights[p] += 1
                weight_sum[p] += weight
                for key in included_keys:
                    weighted[key][p] += weight * (history_fatigue(actual_stats, p) if key == "fatigue_value" else getattr(actual_stats[p], key))
        for key in included_keys:
            for p in general_ids:
                if weight_sum[p] > 0:
                    totals[key][p] += round(weighted[key][p] / weight_sum[p] * nights[p])
    last = max(actuals, key=lambda r: r.context.shift_start_date) if actuals else None
    last_rows = last.assignments if last else ()
    barrier_last_rows = last_rows if last and barrier_history_counts(last.context) else ()
    derived_install = tuple(dict.fromkeys(r.employee_id for r in barrier_last_rows if r.barrier_install_flag))
    # 15-3: 연속 회차 설치 금지 대상 = 직전 회차 설치자 전원(G2·I1 포함, 2026-10-19 사용자 확정)
    derived_forbid = derived_install
    derived_remove = tuple(dict.fromkeys(r.employee_id for r in barrier_last_rows if r.barrier_remove_flag))
    rest_records = tuple(selection.last_rest_records or selection.duty_records or actuals)
    derived_last_rest = []
    for pid in general_ids:
        attended = sorted((r for r in rest_records if any(a.employee_id==pid and a.present
            and a.is_general_worker for a in r.context.attendance)),key=lambda r:r.context.shift_start_date)
        if attended and any(x.employee_id==pid and x.slot.index==13 and x.actual_rest_time_value==1
                            for x in attended[-1].assignments):
            derived_last_rest.append(pid)
    derived_last_rest = tuple(derived_last_rest)
    derived_patrol_excluded = ()
    if last and sum(a.present and a.is_general_worker for a in last.context.attendance) == 6:
        patrolled = {r.employee_id for r in last_rows if r.actual_post_or_work_type.kind == AssignmentKind.PATROL}
        derived_patrol_excluded = tuple(p for p in general_ids if p in {a.employee_id for a in last.context.attendance if a.present and a.is_general_worker} and p not in patrolled)
    if selection.patrol_events:
        current_names={e.employee_id:e.name[-2:] for e in context.employees}
        derived_patrol_excluded=tuple(p for p in general_ids if any(e['excluded'] for e in
            [e for e in selection.patrol_events if e['name']==current_names[p]][-2:]))
    previous_install = selection.previous_install_ids if selection.previous_install_ids is not None else derived_install
    previous_remove = selection.previous_remove_ids if selection.previous_remove_ids is not None else derived_remove
    forbid_install = (selection.forbid_install_ids if selection.forbid_install_ids is not None
                      else selection.previous_install_ids if selection.previous_install_ids is not None else derived_forbid)
    from .fatigue_ledger import night_from_records
    ledger = (night_from_records(selection.long_term_records, context.shift_start_date)[0]
              if selection.long_term_records is not None else None)
    ledger_by_id = ({e.employee_id: ledger.get(e.name, 0) for e in context.employees}
                    if ledger is not None else None)
    return PreparedEngineInputs(
        engine_history=HistoryInput((), ()),
        actual_record_count=len(actuals), assumed_history_used=selection.assumed_totals is not None,
        historical_totals=totals if actuals or selection.assumed_totals is not None else None,
        historical_nights=nights if actuals or selection.assumed_nights is not None else None,
        forbid_install_ids=tuple(forbid_install),
        forbid_last_rest_ids=tuple(selection.previous_last_rest_ids if selection.previous_last_rest_ids is not None else derived_last_rest),
        forbid_patrol_exclusion_ids=tuple(selection.previous_patrol_exclusion_ids if selection.previous_patrol_exclusion_ids is not None else derived_patrol_excluded),
        patrol_rotation_priority_ids=tuple(sorted(patrol_rotation_due(actuals, selection.soft_debt))),
        previous_install_ids=tuple(previous_install), previous_remove_ids=tuple(previous_remove),
        soft_debt=selection.soft_debt,
        duty_rates=mixed_zone_rates(duty_rates_from(selection.duty_records, general_ids), selection.patrol_events,
                                    {e.employee_id: e.name for e in context.employees}, general_ids),
        history_fatigue_averages=averages or None,
        preference_weights=preference_weights(selection.duty_records, general_ids),
        avoid_cells=avoid_cells(context),
        patrol_actuals=tuple(selection.duty_records or actuals),
        patrol_events=selection.patrol_events,
        last_rest_records=rest_records,
        long_term_balances=ledger_by_id,
    )


RULE_FLAGS = {"2.6": "rules_v26", "2.10": "rules_v210", "2.12": "rules_v212",
              "2.13": "rules_v213", "2.15": "rules_v215", "2.16": "rules_v216",
              "2.17": "rules_v217", "2.18": "rules_v218", "2.19": "rules_v219", "2.20": "rules_v220"}


def test_relief_applies(context: ShiftContext, config: "SolveOptions") -> bool:
    """🧪 테스트 규칙 적용 범위(2026-10-23 사용자 확정): 다음날 평일(N1·N3), 통제A 본인 온전 출근, 결원 0~1명,
    반차·교대·긴급 재편성·부분 가용 없음. 그 밖의 날은 테스트 버튼이어도 지금 규칙 그대로."""
    if not config.test_manager_relief or config.rules_version != "2.20":
        return False
    present = [a for a in context.attendance if a.present]
    a_on_duty = any(a.employee_id == "A" and a.acts_as_manager and a.display_number is None for a in present)
    return (context.night_type in (NightType.N1, NightType.N3) and a_on_duty
            and 7 - len(present) <= 1 and not context.partial_vacancy_profile
            and context.manager_handover is None and context.flexible_from_slot is None
            and config.locked_assignments is None and not config.half_day_ids
            and config.manager_a_start_slot == 0 and config.manager_a_end_slot == 14
            and all(a.is_available(t) for a in present for t in range(14)))


def validator_flags_for(rules_version: str, reoptimization: bool) -> dict:
    """Independent validator flags for a rules version (shared by revalidation)."""
    if rules_version == "2.13":
        return {"rules_v212": True}
    if rules_version == "2.17":
        return {"rules_v216": True}
    if rules_version in ("2.18", "2.19", "2.20"):
        return {RULE_FLAGS[rules_version]: True, "reoptimization": reoptimization}
    return {RULE_FLAGS[rules_version]: True}


def _manager_leaver_cells(result: "ServiceResult") -> tuple:
    """긴급 반차·이탈표의 빠지기 전 남은 칸 (자리 형태, 2026-10-18). 통제A면 관리자 자리, 일반근무자면 그 사람."""
    info = result.rebalance_info
    if info is None:
        return ()
    return tuple((info.unavailable_employee_id, t)
                 for t in range(info.reoptimization_start_index, info.unavailable_from_index))


def revalidate(result: "ServiceResult", record: ShiftRecord) -> "ServiceResult":
    """Validate a manually edited record exactly like a generated one."""
    errors = validate_first_trial(
        seat_form_record(record), result.prepared_inputs.engine_history,
        manager_a_end_slot=(record.context.manager_handover[0] if record.context.manager_handover
                            and not record.context.manager_handover_reverse else 14),
        manager_a_start_slot=(record.context.manager_handover[0] if record.context.manager_handover
                              and record.context.manager_handover_reverse else 0),
        locked_cells=tuple((r.employee_id, r.slot.index) for r in seat_form_record(record).assignments
                           if result.rebalance_info is not None and r.slot.index <= result.rebalance_info.locked_through_index),
        forbid_patrol_exclusion_ids=result.prepared_inputs.forbid_patrol_exclusion_ids,
        patrol_actuals=result.prepared_inputs.patrol_actuals,
        patrol_events=result.prepared_inputs.patrol_events,
        last_rest_records=result.prepared_inputs.last_rest_records,
        post_cap=not result.post_cap_relaxed and result.rules_version == "2.20",
        half_day_ids=(None if result.rebalance_info is None and not record.context.manager_handover else tuple(
            # H-09-1: 관리자 교대표(미리 정한 통제A 반차·긴급 이탈 승계)는 대행자 제외.
            # 긴급 반차·이탈자 본인은 반차자로 본다(10/18 사용자 확정: 휴게 2시간만 하드).
            a for a in reoptimization_half_day_ids(record.context.attendance, exclude=(
                ({record.context.manager_handover[1]} if record.context.manager_handover else set())
                | ({result.rebalance_info.unavailable_employee_id}            # 바로 빠져 남은 칸 없는 긴급 이탈자
                   if result.rebalance_info is not None
                   and result.rebalance_info.unavailable_from_index <= result.rebalance_info.reoptimization_start_index
                   else set()))))),
        emergency_leaver_cells=_manager_leaver_cells(result),
        test_manager_relief=result.test_manager_relief,
        **validator_flags_for(result.rules_version, result.rebalance_info is not None))
    if record.context.manager_handover and not errors:
        k, proxy = record.context.manager_handover
        errors = [{"rule": "handover", "detail": f"{proxy}/{k}: 교대 시점 {issue}"}
                  for issue in handover_boundary_issues(
                      record, proxy, k, (result.rebalance_info.locked_through_index + 1) if result.rebalance_info else 0)]
    stats = calculate_all_stats(record) if not errors else result.employee_stats
    return replace(result, context=record.context,
                   solve_result=replace(result.solve_result, record=record),
                   validation_errors=tuple(errors), employee_stats=stats)


def flexible_view(record: ShiftRecord) -> ShiftRecord:
    """FM 표의 칸 배정은 그대로 두고 유도리로 다시 계산한 표 (룰북 0-2-1 확인용).

    표에 저장된 유도리 운영값을 사용한다(새 생성 I1 22~03시, 종전 None 기록은 00~03시).
    차단봉은 해당 날짜의 기존 규칙으로 다시 계산한다.
    """
    context = replace(record.context, requested_mode=Mode.FLEXIBLE, effective_mode=Mode.FLEXIBLE,
                      post_operations=record.context.post_operations)
    installer = _installer_post(compile_common_policy(context), context)
    fm_installers = {r.employee_id for r in record.assignments if r.barrier_install_flag and r.slot.index == 2}
    rows = []
    for r in record.assignments:
        label, slot = r.displayed_assignment.label, r.slot.index
        if r.displayed_assignment.kind == AssignmentKind.UNAVAILABLE:
            rows.append(replace(r, mode=Mode.FLEXIBLE))
            continue
        if barrier_v2(context):                           # 15-0: 차단봉 담당은 모드와 무관 → 그대로
            install, remove = r.barrier_install_flag, r.barrier_remove_flag
        else:
            install = slot == 2 and (label == installer or (label == "보안실 대기" and r.employee_id in fm_installers))
            remove = slot == 10 and label == "I1"
        rows.append(make_record(context, r.employee_id, slot, label, install=install,
                                remove=remove, patrol_standing=True))
    return replace(record, record_id=record.record_id + "-flexible-view", context=context, assignments=tuple(rows))


def _post_cap(config: SolveOptions) -> tuple[bool, bool]:
    """H-17 적용 여부 (Solver, Validator). LOCK 과거가 이미 3번을 넘었으면 Validator는 그 회차 검사를 끈다
    (Solver는 미래 추가 배정만 막는다)."""
    solver_cap = config.rules_version == "2.20" and not config.relax_post_cap
    counts: dict = {}
    for r in config.locked_assignments or ():
        if r.slot.index == 0 and r.employee_id == "A":
            continue                       # 18시 통제는 평일 L3 표기(세지 않음)·주말 휴게 고정이라 초과 판정에 영향 없음
        if r.displayed_assignment.kind == AssignmentKind.POST:
            key = (r.employee_id, r.displayed_assignment.label.partition("(")[0])
            counts[key] = counts.get(key, 0) + 1
    return solver_cap, solver_cap and all(n <= 3 for n in counts.values())


def _full_absence_two(context: ShiftContext) -> bool:
    """H-17 예외 대상: 출근 인원이 2명 빠진 회차(반차 등 부분 결원은 아님)."""
    return sum(not a.present for a in context.attendance) == 2


def run_schedule(request: ShiftRequest | ShiftContext, history: HistorySelection | None = None,
                 options: SolveOptions | None = None) -> ServiceResult:
    """H-17: 해가 없고 2명 완전결원 회차일 때만 같은 포스트 최대 3번을 그 회차에 한해 해제해 다시 찾는다."""
    context = request if isinstance(request, ShiftContext) else build_context(request)
    config = options if options is not None else SolveOptions()
    result = _run_schedule_modes(context, history, config)
    if (result.record is None and result.solve_result.status == "INFEASIBLE" and config.rules_version == "2.20"
            and not config.relax_post_cap and _full_absence_two(context)):
        relaxed = _run_schedule_modes(context, history, replace(config, relax_post_cap=True))
        if relaxed.record is not None:
            return replace(relaxed, post_cap_relaxed=True)
    return result


def _run_schedule_modes(context: ShiftContext, history: HistorySelection | None,
                        config: SolveOptions) -> ServiceResult:
    """룰북 0-2-1: FM이면 두 기준(하드룰+당일 목표) → 두 기준 하드룰 → FM만 순서로 찾는다."""
    dual_applies = (config.prefer_dual_mode and context.requested_mode == Mode.FM
                    and context.flexible_from_slot is None and context.manager_handover is None
                    and config.diagnostic_relaxation_level == 0 and config.diagnostic_relaxed_families is None
                    and config.rules_version == "2.20")
    if not dual_applies:
        return _run_schedule_once(context, history, config, dual=0)
    # 1단계: 두 기준 하드룰 + 두 기준 당일 목표(피로도 1점·실휴게 1시간) → 2단계: 두 기준 하드룰 → 3단계: FM만
    for level in (2, 1):
        dual = _run_schedule_once(context, history, config, dual=level)
        if dual.record is not None and dual.record.context.effective_mode != Mode.FM:
            return dual                               # 0-4·0-4-1 자동 유도리 전환: 두 기준 확인 대상 아님
        if not dual.valid:
            continue
        flexible = flexible_view(dual.record)
        flexible_errors = validate_first_trial(        # 유도리 판정은 독립 Validator로 (Solver 제약만 믿지 않음)
            flexible, dual.prepared_inputs.engine_history,
            manager_a_end_slot=config.manager_a_end_slot, manager_a_start_slot=config.manager_a_start_slot,
            locked_cells=tuple((r.employee_id, r.slot.index) for r in config.locked_assignments or ()),
            forbid_patrol_exclusion_ids=dual.prepared_inputs.forbid_patrol_exclusion_ids,
        patrol_actuals=dual.prepared_inputs.patrol_actuals,
        patrol_events=dual.prepared_inputs.patrol_events,
        last_rest_records=dual.prepared_inputs.last_rest_records,
            post_cap=_post_cap(config)[1], work_spread=False,   # H-18은 실제 운영 모드(FM) 표만 본다
            half_day_ids=config.half_day_ids, emergency_leaver_cells=config.emergency_leaver_cells,
            test_manager_relief=dual.test_manager_relief,
            **validator_flags_for(config.rules_version, config.locked_assignments is not None))
        if flexible_errors:
            continue
        spreads = {"FM": daily_spreads(dual.record), "유도리": daily_spreads(flexible)}
        balanced = all(v <= 1 for both in spreads.values() for v in both.values())   # 표에서 직접 잰 값
        return replace(dual, dual_mode=True, dual_balanced=balanced, dual_spreads=spreads)
    single = _run_schedule_once(context, history, config, dual=0)
    return replace(single, dual_mode=False) if single.record is not None else single


def daily_spreads(record: ShiftRecord) -> dict[str, int]:
    """17장 당일 목표 확인용: 전일 일반근무자 사이 피로도·실휴게 최대-최소 차이 (표에서 직접 계산)."""
    full = {a.employee_id for a in record.context.attendance
            if a.present and a.is_general_worker and all(a.is_available(t) for t in range(14))}
    fatigue, rest = {}, {}
    for r in record.assignments:
        if r.employee_id in full:
            fatigue[r.employee_id] = fatigue.get(r.employee_id, 0) + r.fatigue_value
            rest[r.employee_id] = rest.get(r.employee_id, 0) + r.actual_rest_time_value
    if len(fatigue) < 2:
        return {"피로도": 0, "실휴게": 0}
    return {"피로도": max(fatigue.values()) - min(fatigue.values()), "실휴게": max(rest.values()) - min(rest.values())}


def _run_schedule_once(context: ShiftContext, history: HistorySelection | None, config: SolveOptions, *,
                       dual: int) -> ServiceResult:
    """Run the existing solver and validator once; expose one result to clients."""
    selection = history if history is not None else HistorySelection()
    prepared = prepare_engine_inputs(context, selection)
    flags = {"2.6": "rules_v26", "2.10": "rules_v210", "2.12": "rules_v212",
             "2.13": "rules_v213", "2.15": "rules_v215", "2.16": "rules_v216",
             "2.17": "rules_v217", "2.18": "rules_v218",
             "2.19": "rules_v219", "2.20": "rules_v220"}
    if config.rules_version not in flags:
        raise ValueError(f"Unsupported rule version: {config.rules_version}")
    solver_flags = {flags[config.rules_version]: True}
    # v2.17 changes only the manager objective, not any hard rule, so the
    # independent validator checks the same v2.16 hard-rule set.
    validator_flags = ({"rules_v212": True} if config.rules_version == "2.13"
                       else {"rules_v216": True} if config.rules_version == "2.17"
                       else {flags[config.rules_version]: True,
                             "reoptimization": config.locked_assignments is not None}
                       if config.rules_version in ("2.18", "2.19", "2.20")
                       else solver_flags)
    relief = test_relief_applies(context, config)
    solved = solve_first_trial(
        context, prepared.engine_history, seconds=config.seconds,
        manager_a_end_slot=config.manager_a_end_slot, manager_a_start_slot=config.manager_a_start_slot,
        compensation_averages=prepared.history_fatigue_averages,
        long_term_balances=prepared.long_term_balances,
        historical_totals=prepared.historical_totals, historical_nights=prepared.historical_nights,
        prioritize_history_within_daily_targets=config.prioritize_history_within_daily_targets,
        forbid_install_ids=prepared.forbid_install_ids,
        forbid_last_rest_ids=prepared.forbid_last_rest_ids,
        forbid_patrol_exclusion_ids=prepared.forbid_patrol_exclusion_ids,
        patrol_actuals=prepared.patrol_actuals,
        patrol_events=prepared.patrol_events,
        last_rest_records=prepared.last_rest_records,
        patrol_rotation_priority_ids=prepared.patrol_rotation_priority_ids,
        soft_debt=prepared.soft_debt,
        duty_rates=prepared.duty_rates,
        previous_install_ids=prepared.previous_install_ids,
        previous_remove_ids=prepared.previous_remove_ids,
        exclude_assignments=config.exclude_assignments,
        locked_assignments=config.locked_assignments,
        diagnostic_relaxation_level=config.diagnostic_relaxation_level,
        diagnostic_relaxed_families=(frozenset(config.diagnostic_relaxed_families)
                                     if config.diagnostic_relaxed_families is not None else None),
        forced_rest_cells=config.forced_rest_cells,
        dual_flexible=dual >= 1, dual_balance=dual >= 2,
        preference_weights=prepared.preference_weights, avoid_cells=prepared.avoid_cells,
        post_cap=_post_cap(config)[0], half_day_ids=config.half_day_ids,
        emergency_leaver_cells=config.emergency_leaver_cells,
        disabled_rule_groups=frozenset(config.disabled_rule_groups), feasibility_only=config.feasibility_only,
        test_manager_relief=relief,
        **solver_flags,
    )
    if solved.record is None:
        return ServiceResult(context, solved, (), {}, prepared, config.rules_version, test_manager_relief=relief)
    errors = validate_first_trial(solved.record, prepared.engine_history,
                                  manager_a_end_slot=config.manager_a_end_slot, manager_a_start_slot=config.manager_a_start_slot,
                                  locked_cells=tuple((r.employee_id, r.slot.index) for r in config.locked_assignments or ()),
                                  forbid_patrol_exclusion_ids=prepared.forbid_patrol_exclusion_ids,
        patrol_actuals=prepared.patrol_actuals,
        patrol_events=prepared.patrol_events,
        last_rest_records=prepared.last_rest_records,
                                  post_cap=_post_cap(config)[1], half_day_ids=config.half_day_ids,
                                  emergency_leaver_cells=config.emergency_leaver_cells,
                                  test_manager_relief=relief,
                                  **validator_flags)
    stats = calculate_all_stats(solved.record) if not errors else {}
    return ServiceResult(solved.record.context, solved, tuple(errors), stats, prepared,
                         config.rules_version, test_manager_relief=relief)


def _hour(slot_index: int) -> str:
    return f"{(18 + slot_index) % 24:02d}시"


def _natural_exception(error: Mapping, context: ShiftContext) -> str:
    detail = str(error.get("detail", ""))
    rule = str(error.get("rule", ""))
    names = {employee.employee_id: employee.name for employee in context.employees}
    parts = detail.replace(":", " ").split()
    employee_id = next((part.split("/")[0] for part in parts if "/" in part
                        and part.split("/")[0] in names), None)
    slot = None
    for part in parts:
        fields = part.strip(".,").split("/")
        if employee_id and fields[0] == employee_id and len(fields) > 1:
            try:
                slot = int(fields[1])
            except ValueError:
                pass
    who = names.get(employee_id, "특정 직원")
    when = f" {_hour(slot)} 부근" if slot is not None and slot in range(14) else ""
    if rule in ("H-03", "H-04", "H-03/H-07"):
        return f"{who}{when}: 평소 피하는 동일 포스트 반복 배치가 필요합니다."
    if rule == "H-15":
        return f"{who}: 관리자와의 실근무시간 차이 2시간 기준을 일부 넘겨야 합니다."
    if rule == "8-4-2":
        return f"{who}: 관리자와의 피로도 차이 기준(A는 일반근무자보다 0~2점 낮게, 또는 4점 이내)을 일부 넘겨야 합니다."
    if rule.startswith("H-11"):
        return f"{who}{when}: 순찰 뒤 보장하던 회복시간 일부를 근무로 바꿔야 합니다."
    if rule == "H-08" and detail.startswith("Four"):
        return f"{who}{when}: 4시간 연속근무 구간에서 좌식근무 1시간을 확보하지 못합니다."
    if rule == "H-08" and detail.startswith("Five"):
        return f"{who}{when}: 평소 금지된 5시간 연속근무가 필요합니다."
    if rule in ("H-06/H-07", "H-07"):
        return f"{who}{when}: 연속 입식 또는 아침 배치 보호조건의 예외가 필요합니다."
    return f"{who}{when}: 정상 배치조건 일부에 예외가 필요합니다."


def _diagnose_reoptimization(context: ShiftContext, locked: tuple,
                             history: HistorySelection, config: SolveOptions) -> FailureDiagnosis:
    """v2.16+ §21-8 diagnosis only; never returns an approved schedule."""
    diagnostic_history = replace(
        history,
        previous_last_rest_ids=(), previous_patrol_exclusion_ids=(),
        forbid_install_ids=(),
    )
    level_titles = {
        1: ("R1", "낮음", "과거 회차의 순환·공정성 제한"),
        2: ("R2", "보통", "반복 배치와 역할 간 균형 제한"),
        3: ("R3", "주의", "순찰 후 회복시간 보호"),
        4: ("R4", "높음", "4시간 연속근무 중 좌식 1시간 보호"),
        5: ("R5", "매우 높음", "5시간 연속근무 금지"),
    }
    if config.rules_version == "2.20":
        # v2.20: after the history-only step, try each rule family on its own
        # so the report lists only the exceptions that are actually needed;
        # fall back to the cumulative ladder only if no single family works.
        attempts = [(1, None)] + [(level, (level,)) for level in range(2, 6)] + \
                   [(level, None) for level in range(3, 6)]
    else:
        attempts = [(level, None) for level in range(1, 6)]
    for level, families in attempts:
        probe = run_schedule(
            context,
            diagnostic_history,
            replace(config, seconds=min(config.seconds, 15), exclude_assignments=None,
                    locked_assignments=locked, diagnostic_relaxation_level=level,
                    diagnostic_relaxed_families=families),
        )
        if probe.solve_result.status == "UNKNOWN":
            return FailureDiagnosis(
                "timeout", "계산시간 안에 판단하지 못했습니다",
                "해가 없다고 확정된 상태가 아닙니다. 최소 예외 진단도 제한시간 안에 끝나지 않았습니다.",
                next_action="Solver 제한시간을 늘려 다시 계산하거나 인원 조건을 확인해 주세요.",
            )
        if probe.record is not None:
            code, severity, title = level_titles[level]
            if families is None and level >= 3 and config.rules_version == "2.20":
                code = f"R2~{code}"
            if level == 1:
                details = ("최근 회차의 순찰 제외·마지막 휴게·차단봉 순환 제한 중 일부를 예외로 하면 정상 안전조건을 유지한 표를 만들 수 있습니다.",)
            else:
                messages = [_natural_exception(error, context) for error in probe.validation_errors]
                generic = "정상 배치조건 일부에 예외가 필요합니다."
                specific_prefixes = {m.split(":")[0] for m in messages if not m.endswith(generic)}
                details = tuple(dict.fromkeys(
                    m for m in messages
                    if not (m.endswith(generic) and m.split(":")[0] in specific_prefixes)
                )) or (f"{title}에 최소 예외를 두면 근무표를 만들 수 있습니다.",)
            return FailureDiagnosis(
                "infeasible", "정상조건으로는 근무표를 만들 수 없습니다",
                "현재 LOCK된 근무와 남은 인원으로 모든 정상조건을 동시에 만족하는 표가 없습니다.",
                f"{code} · 예외 수준 {severity}", details,
                "이 결과는 진단일 뿐 자동 적용되지 않습니다. 기존표 유지 또는 인원변경 후 다시 계산해 주세요.",
            )
    return FailureDiagnosis(
        "infeasible", "정의된 예외 범위에서도 해가 없습니다",
        "LOCK과 근무불가 시간을 지키면서 필수 포스트를 채울 수 있는 근무표를 찾지 못했습니다.",
        next_action="기존표를 유지하고 대체인력, 운영축소 또는 다른 인원변경을 검토해 주세요.",
    )


def _reoptimize_core(base: ServiceResult, reoptimization_start_index: int,
                     unavailable_employee_id: str, unavailable_from_index: int,
                     history: HistorySelection | None = None,
                     options: SolveOptions | None = None,
                     reason: str = "긴급 반차", exclude=None, forced_rest=(), extra_locked=(),
                     leaver_cells=None) -> ServiceResult:
    """Lock the performed prefix and optimize the remaining v2.15+ shift.

    The returned record still contains all 14 slots, so the ordinary independent
    validator checks both the boundary and the newly generated suffix.
    """
    if not base.valid or base.record is None:
        raise ValueError("검증을 통과한 기존 근무표만 재편성할 수 있습니다.")
    if reoptimization_start_index not in range(1, 14):
        raise ValueError("재편성 시작시간은 19시부터 07시 사이여야 합니다.")
    if unavailable_from_index not in range(reoptimization_start_index, 14):
        raise ValueError("근무불가 시작시간은 재편성 시작시간보다 빠를 수 없습니다.")
    # ShiftContext intentionally separates stable people (`employees`) from
    # per-shift participation (`attendance`).  Do not reconstruct this through
    # ShiftRequest.staff: ServiceResult already contains the canonical context.
    employees = {employee.employee_id: employee for employee in base.context.employees}
    attendance = {item.employee_id: item for item in base.context.attendance}
    if set(attendance) - set(employees):
        raise ValueError("근무정보에 등록되지 않은 직원이 포함되어 있습니다.")
    if unavailable_employee_id not in attendance or not attendance[unavailable_employee_id].present:
        raise ValueError("현재 근무표의 출근자만 반차자로 선택할 수 있습니다.")
    target = attendance[unavailable_employee_id]
    available = tuple(t for t in range(14)
                      if target.is_available(t) and t < unavailable_from_index)
    revised_attendance = tuple(
        replace(a, available_slot_indices=available)
        if a.employee_id == unavailable_employee_id else a
        for a in base.context.attendance
    )
    revised_context = replace(base.context, attendance=revised_attendance)
    requested_version = (options.rules_version if options is not None else base.rules_version)
    if (requested_version == "2.20" and base.context.flexible_from_slot is None
            and not base.context.partial_vacancy_profile
            and 7 - sum(a.present for a in base.context.attendance) < 2):
        # v2.20 §0-4-2: if the unlocked remainder is left with four available
        # general workers, switch that remainder to flexible + vacancy-2 rules.
        general_after = [sum(a.is_available(t) for a in revised_attendance
                             if a.present and a.is_general_worker)
                         for t in range(reoptimization_start_index, 14)]
        if min(general_after) == 4:
            hour = f"{(18 + reoptimization_start_index) % 24:02d}시"
            revised_context = replace(
                revised_context, flexible_from_slot=reoptimization_start_index,
                mode_change_reason=(f"§0-4-2: 긴급 인원변동으로 {hour} 이후 가용 일반근무자가 4명이 되어 "
                                    f"{hour}부터 유도리·결원 2명 규칙으로 전환"))
    locked = tuple(row for row in base.record.assignments
                   if row.slot.index < reoptimization_start_index) + tuple(extra_locked)
    config = options if options is not None else SolveOptions(rules_version=base.rules_version)
    if config.rules_version not in ("2.15", "2.16", "2.17", "2.18", "2.19", "2.20"):
        raise ValueError("긴급 부분고정 재편성은 룰북 v2.15 이상에서만 지원합니다.")
    outcome = run_schedule(
        revised_context,
        history,
        replace(config, exclude_assignments=exclude or None, locked_assignments=locked,
                forced_rest_cells=tuple(forced_rest),
                # H-09-1: 원래 표의 미리 정한 반차자 + 긴급 반차·이탈자 본인(10/18 사용자 확정: 휴게 2시간만 하드).
                # leaver_cells가 따로 오면(통제A 이탈 → 자리 형태의 준호 줄이 빠짐) 준호는 반차자가 아니다.
                half_day_ids=reoptimization_half_day_ids(
                    revised_context.attendance,
                    exclude=({unavailable_employee_id}         # 통제A 이탈: 자리 형태 준호 줄 / 남은 칸 없이 바로 빠짐
                             if leaver_cells is not None or unavailable_from_index <= reoptimization_start_index
                             else ())),
                emergency_leaver_cells=tuple(leaver_cells if leaver_cells is not None else
                                             ((unavailable_employee_id, t)
                                              for t in range(reoptimization_start_index, unavailable_from_index)))),
    )
    info = RebalanceInfo(
        source_record_id=base.record.record_id,
        reoptimization_start_index=reoptimization_start_index,
        locked_through_index=reoptimization_start_index - 1,
        unavailable_employee_id=unavailable_employee_id,
        unavailable_from_index=unavailable_from_index,
        reason=reason,
    )
    if outcome.record is None:
        diagnosis = None
        # 차단봉 유지 고정(extra_locked)으로 해가 없으면 호출한 쪽이 고정 없이 다시 찾으므로 진단하지 않는다
        # (진단은 고정 칸을 모르는 문맥이라 오류가 났음, 2026-10-18).
        if (config.rules_version in ("2.16", "2.17", "2.18", "2.19", "2.20") and outcome.solve_result.status == "INFEASIBLE"
                and not extra_locked and not config.feasibility_only and not config.disabled_rule_groups):
            diagnosis = _diagnose_reoptimization(revised_context, locked,
                                                 history or HistorySelection(), config)
        elif outcome.solve_result.status == "UNKNOWN":
            diagnosis = FailureDiagnosis(
                "timeout", "계산시간 안에 해를 찾지 못했습니다",
                "해가 없다고 확정된 상태가 아닙니다.",
                next_action="Solver 제한시간을 늘려 다시 시도해 주세요.",
            )
        return replace(outcome, rebalance_info=info, failure_diagnosis=diagnosis)
    revised_record = replace(
        outcome.record,
        record_id=f"{outcome.record.record_id}-rebalance-{reoptimization_start_index}",
        source_plan_id=base.record.record_id,
    )
    revised_solve = replace(outcome.solve_result, record=revised_record)
    return replace(outcome, solve_result=revised_solve, rebalance_info=info)


# ---------------------------------------------------------------- manager handover
# When 통제 A leaves mid-shift, 준호 succeeds as acting manager from slot k.
# The engine solves an equivalent "seat form": the manager seat (id A) runs the
# whole night, and 준호 is a general worker who becomes unavailable at k. The
# displayed record swaps A/준호 rows for slots >= k (A shows ×, 준호 continues
# as manager). Seat form <-> display form is a pure relabeling.
HANDOVER_PROXY_ID = "6"


def _swap_rows_from(rows, first: str, second: str, start: int, stop: int = 14):
    other = {first: second, second: first}
    return tuple(replace(r, employee_id=other[r.employee_id])
                 if start <= r.slot.index < stop and r.employee_id in other else r for r in rows)


def _handover_context(context: ShiftContext, manager: str, proxy: str, k: int, seat: bool,
                      reverse: bool = False) -> ShiftContext:
    attendance = []
    for a in context.attendance:
        if a.employee_id == manager:
            a = replace(a, available_slot_indices=None if seat else tuple(range(k, 14) if reverse else range(k)))
        elif a.employee_id == proxy:
            a = replace(a, available_slot_indices=tuple(range(k, 14) if reverse else range(k)) if seat else None)
        attendance.append(a)
    return replace(context, attendance=tuple(attendance),
                   manager_handover=None if seat else (k, proxy), manager_handover_reverse=reverse if not seat else False)


def _manager_id(context: ShiftContext) -> str:
    return next(a.employee_id for a in context.attendance if a.present and a.acts_as_manager)


def seat_form_record(record: ShiftRecord) -> ShiftRecord:
    """Engine view of a record (identity when there is no manager handover)."""
    handover = record.context.manager_handover
    if not handover:
        return record
    k, proxy = handover
    manager = _manager_id(record.context)
    reverse = record.context.manager_handover_reverse
    return replace(record, context=_handover_context(record.context, manager, proxy, k, True, reverse),
                   assignments=_swap_rows_from(record.assignments, manager, proxy, 0 if reverse else k, k if reverse else 14))


def display_form_record(record: ShiftRecord, k: int, proxy: str, reverse: bool = False) -> ShiftRecord:
    manager = _manager_id(record.context)
    return replace(record, context=_handover_context(record.context, manager, proxy, k, False, reverse),
                   assignments=_swap_rows_from(record.assignments, manager, proxy, 0 if reverse else k, k if reverse else 14))


def _seat_result(result: ServiceResult) -> ServiceResult:
    record = seat_form_record(result.record)
    return replace(result, context=record.context,
                   solve_result=replace(result.solve_result, record=record))


def handover_boundary_issues(record: ShiftRecord, proxy: str, k: int, locked_before: int = 0) -> list[str]:
    """준호's own continuity across the handover (display form).

    locked_before: 이 칸 앞은 LOCK된 과거(긴급 재편성). 교대 직전 두 칸이 이미 LOCK된 입식이면 교대 시점
    입식 3연속은 허용한다(2026-10-20 사용자 확정 — 바꿀 수 없는 과거라 불가피).
    """
    rows = {r.slot.index: r for r in record.assignments if r.employee_id == proxy}
    work = lambda t: t in rows and rows[t].actual_work_time_value == 1  # noqa: E731
    counted = lambda t: t in rows and (rows[t].counts_for_continuous_work_restriction  # noqa: E731
                                       or rows[t].actual_post_or_work_type.kind == AssignmentKind.PATROL)
    seated = lambda t: work(t) and rows[t].posture_or_mode == Posture.SEATED  # noqa: E731
    standing = lambda t: work(t) and rows[t].posture_or_mode == Posture.STANDING  # noqa: E731
    patrol = lambda t: t in rows and rows[t].actual_post_or_work_type.kind == AssignmentKind.PATROL  # noqa: E731
    issues = []
    for s in range(max(0, k - 4), min(k, 10) + 1):
        if s + 4 < 14 and all(counted(t) for t in range(s, s + 5)):
            issues.append("5시간 연속근무")
    for s in range(max(0, k - 3), min(k, 11) + 1):
        if s + 3 < 14 and all(counted(t) for t in range(s, s + 4)) and not any(seated(t) for t in range(s, s + 4)):
            issues.append("4시간 연속근무 중 좌식 없음")
    for s in range(max(0, k - 2), min(k, 12) + 1):
        if s + 2 < 14 and s < k <= s + 2 and all(standing(t) for t in range(s, s + 3)):
            if s == k - 2 and k - 1 < locked_before:
                continue
            issues.append("입식 3시간 연속")
    for t in (k - 2, k - 1):
        if t >= 0 and patrol(t):
            window = [rows.get(j) for j in (t + 1, t + 2) if j < 14]
            if window and not any(w is not None and w.actual_work_time_value == 0 for w in window):
                issues.append("순찰 뒤 휴게 없음")
            if t >= 1 and standing(t - 1) and t + 1 < 14 and work(t + 1) and not seated(t + 1):
                issues.append("입식 → 순찰 → 입식")
    return list(dict.fromkeys(issues))


def run_reoptimization(base: ServiceResult, reoptimization_start_index: int,
                       unavailable_employee_id: str, unavailable_from_index: int,
                       history: HistorySelection | None = None,
                       options: SolveOptions | None = None,
                       reason: str = "긴급 반차", exclude=None) -> ServiceResult:
    """Emergency re-optimization. 통제 A leaving hands the manager role to 준호."""
    handover = base.record.context.manager_handover if base.record else None
    target = next((a for a in base.context.attendance if a.employee_id == unavailable_employee_id), None)
    if handover or (target and target.acts_as_manager and target.display_number is None):
        reverse = bool(handover and base.context.manager_handover_reverse)
        end = handover[0] if handover and not reverse else (14 if reverse else unavailable_from_index)
        options = replace(options or SolveOptions(rules_version=base.rules_version), manager_a_end_slot=end,
                          manager_a_start_slot=handover[0] if reverse else 0)
    if base.record is not None and base.record.context.manager_handover:
        k, proxy = base.record.context.manager_handover
        manager = _manager_id(base.context)
        if unavailable_employee_id in (manager, proxy):
            raise ValueError("이미 관리자 교대가 있는 근무표에서는 통제·관리자 대행자의 추가 이탈을 재편성할 수 없습니다.")
        outcome = _reoptimize_core(_seat_result(base), reoptimization_start_index, unavailable_employee_id,
                                   unavailable_from_index, history, options, reason, exclude)
        return _to_display(outcome, k, proxy, base.context.manager_handover_reverse)

    attendance = {a.employee_id: a for a in base.context.attendance}
    target = attendance.get(unavailable_employee_id)
    if target is None or not (target.acts_as_manager and target.display_number is None):
        return _reoptimize_core(base, reoptimization_start_index, unavailable_employee_id,
                                unavailable_from_index, history, options, reason, exclude)

    # 통제 A leaves: 준호 succeeds as acting manager from `unavailable_from_index`.
    k, proxy = unavailable_from_index, HANDOVER_PROXY_ID
    successor = attendance.get(proxy)
    if successor is None or not successor.present or not successor.is_general_worker:
        raise ValueError("준호가 출근하지 않아 관리자 대행을 맡을 수 없습니다.")
    if not all(successor.is_available(t) for t in range(14)):
        raise ValueError("준호가 반차라서 관리자 대행을 끝까지 맡을 수 없습니다.")
    label = f"{reason} · {_hour(k)}부터 준호 관리자 대행"
    manager = _manager_id(base.context)
    # 2026-10-18 사용자 확정(권장, 하드 아님): 긴급 통제A 이탈로 준호가 대행이 되어도, 원래 표에서 준호가 맡은 차단봉
    # (20시 설치·04시 철수)은 가능하면 그대로 → 자리 형태에서 그 칸을 관리자 자리 칸으로 고정(LOCK이라 통제A 04시
    # 철수 금지 규칙은 적용 안 됨). 그렇게 해가 없으면 고정 없이 다시 찾는다(차단봉은 다른 사람에게).
    keep_barrier = tuple(replace(row, employee_id=manager) for row in base.record.assignments
                         if row.employee_id == proxy and row.slot.index >= max(k, reoptimization_start_index)
                         and (row.barrier_install_flag or row.barrier_remove_flag))
    if keep_barrier:
        label += f" · 준호 차단봉 {'·'.join(_hour(r.slot.index) for r in keep_barrier)} 그대로"
    last = None
    # Boundary ladder: plain → seat rests at k → seat rests at k and k+1.
    for forced in ((), (k,), (k, k + 1)):
        cells = tuple((manager, t) for t in forced if t < 14)
        if forced and len(cells) == (len(last_cells) if last is not None else -1):
            break
        last_cells = cells
        leaver = tuple((manager, t) for t in range(reoptimization_start_index, k))   # 빠지기 전 통제A 칸
        try:
            seat = _reoptimize_core(base, reoptimization_start_index, proxy, k, history, options, label,
                                    exclude, forced_rest=cells, extra_locked=keep_barrier, leaver_cells=leaver)
        except ValueError:
            # 차단봉 유지 고정 칸이 FM·유도리 동시 확인의 유도리 계산과 맞지 않으면 오류가 났음(10/18) → 고정 없이 다시
            if not keep_barrier:
                raise
            seat = None
        if keep_barrier and (seat is None or seat.record is None):      # 차단봉 유지는 권장(10/18 사용자): 안 되면 원래대로 옮겨 다시
            keep_barrier = ()
            label = label.split(" · 준호 차단봉")[0]
            seat = _reoptimize_core(base, reoptimization_start_index, proxy, k, history, options, label,
                                    exclude, forced_rest=cells, leaver_cells=leaver)
        shown = _to_display(seat, k, proxy)
        shown = replace(shown, rebalance_info=(replace(shown.rebalance_info, unavailable_employee_id=manager)
                                               if shown.rebalance_info else None))
        if seat.record is None or seat.validation_errors:
            return shown if last is None else last
        issues = handover_boundary_issues(shown.record, proxy, k, reoptimization_start_index)
        if not issues:
            return shown
        last = replace(shown, validation_errors=tuple(
            {"rule": "handover", "detail": f"{proxy}/{k}: 교대 시점 {issue}"} for issue in issues))
    return last


def run_lock_regeneration(base: ServiceResult, reoptimization_start_index: int,
                          history: HistorySelection | None = None,
                          options: SolveOptions | None = None, exclude=None) -> ServiceResult:
    """빠지는 사람 없이 LOCK만 고른 재생성 (2026-10-18 사용자 요청): 시작 전 배정은 그대로, 남은 시간만 다른 후보.

    긴급 재편성이 아니므로 결과는 일반 생성표와 같은 규칙(긴급 완화 없음)으로 다시 검증한다."""
    if not base.valid or base.record is None:
        raise ValueError("검증을 통과한 근무표만 LOCK 재생성할 수 있습니다.")
    if base.record.context.manager_handover:
        raise ValueError("통제A 반차·교대가 있는 근무표는 LOCK만 고른 재생성을 아직 지원하지 않습니다. "
                         "빠지는 사람을 고르거나 일반 재생성을 써 주세요.")
    if reoptimization_start_index not in range(1, 14):
        raise ValueError("LOCK 다음 시간은 19시부터 07시 사이여야 합니다.")
    locked = tuple(row for row in base.record.assignments if row.slot.index < reoptimization_start_index)
    config = options if options is not None else SolveOptions(rules_version=base.rules_version)
    outcome = run_schedule(base.context, history, replace(
        config, exclude_assignments=exclude or None, locked_assignments=locked,
        half_day_ids=tuple(a.employee_id for a in base.context.attendance          # 미리 정한 반차자 그대로
                           if a.present and a.is_general_worker and not all(a.is_available(t) for t in range(14)))))
    if outcome.record is None:
        return outcome
    return revalidate(outcome, outcome.record)


# 충돌 진단에 쓰는 하드 규칙 묶음 (solver.rule_off()의 이름과 같아야 한다, 2026-10-18)
RULE_GROUPS = (
    "준호 피로도(반차·승계)", "준호 자기 줄 순찰 금지", "통제A 긴급 반차(I1 금지·입식 3연속)",
    "순찰 배분(14-1·14-2)", "H-11 순찰 뒤 휴게", "H-08 연속근무", "반차자 휴게 2시간(H-09-1)",
    "관리자 실근무·피로도 격차(H-15·8-4-2)", "8-10 통제A 04시", "8-14 통제A I1 최소 1회", "8-15 통제A 대기 최대 2회",
    "12-3 순찰 뒤 3번째 칸 대기 표기", "12-4 연속 휴게 표기", "12-5 매시간 대기자", "12-6 대기 횟수 차이",
    "H-19 05~07시 휴게 3연속 금지", "H-20 06·07시 휴게 2연속 금지", "5-3-1 남문 2시간 연속 금지", "15-3 연속 회차 설치 금지",
    "관리자 하대 금지(결원 2명)",
    "교대 경계(준호 연속근무)",
    "H-21 4시간 같은 포스트 3번 금지", "H-22 4시간 연속 근무 금지(결원 0~1명)", "대행 준호 순찰 앞뒤 휴게 최대 2시간", "8-10-2 관리자 04시 근무 금지",
)


def find_conflicting_rules(attempt, options: SolveOptions, seconds: int = 8, pairs: bool = True) -> dict:
    """해가 없을 때 어떤 하드 규칙 묶음이 막는지 찾는다 (2026-10-18, 사용자 결정용 — 규칙을 실제로 풀지는 않는다).

    attempt(options) -> ServiceResult 는 원래 생성·재편성 호출을 그대로 감싼 함수.
    묶음을 하나씩 끄고 목표 없이 해가 있는지만 본다. 하나로 안 풀리면 두 개씩 끈 조합도 본다(pairs).
    반환: {"single": [묶음], "pairs": [(묶음, 묶음)], "checked": 시도 수, "seconds": 걸린 시간}"""
    from time import perf_counter
    started = perf_counter()
    probe = replace(options, feasibility_only=True, seconds=seconds)

    def solvable(groups):
        try:
            out = attempt(replace(probe, disabled_rule_groups=tuple(groups)))
        except ValueError:
            return False
        return out.solve_result.status in ("FEASIBLE", "OPTIMAL")

    checked = 0
    single = []
    for group in RULE_GROUPS:
        checked += 1
        if solvable((group,)):
            single.append(group)
    found_pairs = []
    if pairs and not single:
        for i, first in enumerate(RULE_GROUPS):
            for second in RULE_GROUPS[i + 1:]:
                checked += 1
                if solvable((first, second)):
                    found_pairs.append((first, second))
    return {"single": single, "pairs": found_pairs, "checked": checked, "seconds": perf_counter() - started}


def patrol_recovery_misses(record: ShiftRecord, from_slot: int = 0) -> list[str]:
    """긴급 재편성표에서 순찰 직후 2시간 회복을 못 지킨 곳 (2026-10-18: 긴급일 때만 가능하면 지킬 규칙 → 화면 안내용)."""
    names = {e.employee_id: ("통제" if e.employee_id == "A" else e.name) for e in record.context.employees}
    rows = {(r.employee_id, r.slot.index): r for r in record.assignments}
    out = []
    for (p, t), r in sorted(rows.items(), key=lambda kv: (kv[0][1], kv[0][0])):
        if t < from_slot or r.actual_post_or_work_type.kind != AssignmentKind.PATROL:
            continue
        worked = [j for j in (t + 1, t + 2) if j < 14 and (p, j) in rows and rows[p, j].actual_work_time_value == 1]
        if worked:
            out.append(f"{names.get(p, p)} {_hour(t)} 순찰 뒤 {'·'.join(_hour(j) for j in worked)} 근무")
    return out


MANAGER_HALF_SLOT = 7          # 통제A 반차 경계 = 01시 (일반근무자 전반부·후반부 반차와 같음)


def _seat_exclusions(exclude, manager: str, proxy: str, k: int, reverse: bool = False):
    """화면(표시 형태) 근무표 제외 목록을 자리 형태로: k 이후 A·준호 줄 교체."""
    if not exclude:
        return exclude
    other = {manager: proxy, proxy: manager}

    def swap(row):
        t = row.get("slot", {}).get("index", -1) if isinstance(row, dict) else -1
        if isinstance(row, dict) and (0 <= t < k if reverse else t >= k) and row.get("employee_id") in other:
            return {**row, "employee_id": other[row["employee_id"]]}
        return row
    if exclude and isinstance(exclude[0], dict):
        return tuple(swap(r) for r in exclude)
    return tuple(tuple(swap(r) for r in plan) for plan in exclude)


def run_schedule_manager_half(request: ShiftRequest, history: HistorySelection | None = None,
                              options: SolveOptions | None = None) -> ServiceResult:
    """미리 정한 통제A 후반부 반차(01시 퇴근) (2026-10-18 사용자 확정, 야간 중도 인계와 같은 자리 방식).

    엔진은 '관리자 자리 밤새 + 준호는 01시까지 일반근무'로 풀고, 화면은 01시부터 A·준호 줄을 바꿔 보여 준다
    (A는 01시부터 ×, 준호가 관리자 대행). 01시 이후 통제A 규칙(04시 대기·I1·철수 금지, 07시 실근무 없음,
    다음날 공휴일 06시 G1 금지 등)은 준호가 계승한다. 통제A 본인 규칙(I1 최소 1번·대기 최대 2회)은 00시까지만."""
    k, proxy = MANAGER_HALF_SLOT, HANDOVER_PROXY_ID
    context = build_context(request)
    attendance = {a.employee_id: a for a in context.attendance}
    manager, successor = attendance.get("A"), attendance.get(proxy)
    if manager is None or not manager.present or not manager.acts_as_manager:
        raise ValueError("통제A 반차는 통제A가 출근(반나절)하는 날만 고를 수 있습니다.")
    if (successor is None or not successor.present or not successor.is_general_worker
            or not all(successor.is_available(t) for t in range(14))):
        raise ValueError("준호가 하루 전체 출근이 아니라 01시부터 관리자 대행을 맡을 수 없습니다.")
    seat = replace(context, attendance=tuple(
        replace(a, available_slot_indices=tuple(range(k))) if a.employee_id == proxy else a
        for a in context.attendance))
    config = options if options is not None else SolveOptions(rules_version="2.20")
    # H-09-1 반차자 규칙은 진짜 반차자만 (자리 형태의 준호 '01시 퇴근'은 대행이라 제외)
    half_ids = tuple(a.employee_id for a in seat.attendance if a.present and a.is_general_worker
                     and a.employee_id != proxy and not all(a.is_available(t) for t in range(14)))
    # exclusion_payload는 이미 자리 형태로 직렬화하므로 여기서 다시 뒤집지 않는다.
    config = replace(config, manager_a_end_slot=k, half_day_ids=half_ids)
    last = None
    # 교대 경계: 그대로 → 01시 자리 휴게 → 01·02시 자리 휴게 (긴급 중도 인계와 같은 사다리)
    for forced in ((), (k,), (k, k + 1)):
        result = run_schedule(seat, history, replace(config, forced_rest_cells=tuple(("A", t) for t in forced)))
        shown = _to_display(result, k, proxy)
        if result.record is None or result.validation_errors:
            return shown if last is None else last
        issues = handover_boundary_issues(shown.record, proxy, k)
        if not issues:
            return shown
        last = replace(shown, validation_errors=tuple(
            {"rule": "handover", "detail": f"{proxy}/{k}: 교대 시점 {issue}"} for issue in issues))
    return last


def run_schedule_manager_early_half(request: ShiftRequest, history: HistorySelection | None = None,
                                    options: SolveOptions | None = None) -> ServiceResult:
    """전반부 반차: 18~00시 준호 대행, 01시부터 통제A·일반근무 준호."""
    k, proxy = MANAGER_HALF_SLOT, HANDOVER_PROXY_ID
    context = build_context(request)
    attendance = {a.employee_id: a for a in context.attendance}
    manager, successor = attendance.get('A'), attendance.get(proxy)
    if manager is None or not manager.present or not manager.acts_as_manager:
        raise ValueError('통제A 반차는 통제A가 반나절 출근하는 날만 고를 수 있습니다.')
    if (successor is None or not successor.present or not successor.is_general_worker
            or not all(successor.is_available(t) for t in range(14))):
        raise ValueError('준호가 하루 전체 출근이 아니라 전반부 관리자 대행을 맡을 수 없습니다.')
    seat = replace(context, attendance=tuple(
        replace(a, available_slot_indices=tuple(range(k, 14))) if a.employee_id == proxy else a
        for a in context.attendance))
    config = options if options is not None else SolveOptions(rules_version='2.20')
    half_ids = tuple(a.employee_id for a in seat.attendance if a.present and a.is_general_worker
                     and a.employee_id != proxy and not all(a.is_available(t) for t in range(14)))
    config = replace(config, manager_a_start_slot=k, manager_a_end_slot=14, half_day_ids=half_ids)
    last = None
    # 준호의 관리자→일반 전환 경계에서도 기존 연속근무·순찰 회복을 확인한다.
    for forced in ((), (k,), (k, k + 1)):
        cells = tuple(dict.fromkeys(config.forced_rest_cells + tuple((proxy, t) for t in forced)))
        result = run_schedule(seat, history, replace(config, forced_rest_cells=cells))
        shown = _to_display(result, k, proxy, True)
        if result.record is None or result.validation_errors:
            return shown if last is None else last
        issues = handover_boundary_issues(shown.record, proxy, k)
        if not issues:
            return shown
        last = replace(shown, validation_errors=tuple(
            {'rule': 'handover', 'detail': f'{proxy}/{k}: 교대 시점 {issue}'} for issue in issues))
    return last


def _to_display(outcome: ServiceResult, k: int, proxy: str, reverse: bool = False) -> ServiceResult:
    if outcome.record is None:
        return outcome
    record = display_form_record(outcome.record, k, proxy, reverse)
    stats = calculate_all_stats(record) if not outcome.validation_errors else outcome.employee_stats
    return replace(outcome, context=record.context,
                   solve_result=replace(outcome.solve_result, record=record), employee_stats=stats)
