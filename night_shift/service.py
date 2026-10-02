"""Application boundary around the unchanged scheduling and validation engines.

UI and exporters consume ServiceResult. This module prepares inputs and derives
read-only summaries; it does not decide staffing rules or validate assignments.
"""
from collections import Counter
from dataclasses import dataclass, replace
from datetime import date
from typing import Mapping

from .models import (
    AssignmentKind, Attendance, Employee, HistoryInput, Mode, NightType,
    Posture, RecordKind, ShiftContext, ShiftRecord,
)
from .common import compile_common_policy
from .preferences import avoid_cells, preference_weights
from .profiles import _installer_post, make_record
from .soft_history import patrol_rotation_due
from .solver import SolveResult, solve_first_trial
from .validator import validate_first_trial


SERVICE_API_VERSION = "2.21.11"         # 2026-10-02: 17-1 근무자 선호 (공통 선호 보너스·개인 회피)


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
    # for the last two cycles (6:4). None = every night counts equally.
    actual_weights: tuple[float, ...] | None = None
    # Up to six recent actual nights (3 cycles) for barrier/patrol-zone balance.
    duty_records: tuple[ShiftRecord, ...] = ()


@dataclass(frozen=True)
class SolveOptions:
    rules_version: str = "2.13"
    seconds: int = 30
    prioritize_history_within_daily_targets: bool = False
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
    preference_weights: Mapping[str, int] | None = None
    avoid_cells: tuple[tuple[str, int, str], ...] = ()


DUTY_METRICS = ("barrier", "upper", "middle", "lower")


def duty_rates_from(records, general_ids) -> dict | None:
    """Per-night rate (×100) of barrier duty and each patrol zone over recent nights."""
    if not records:
        return None
    counts = {m: {p: 0 for p in general_ids} for m in DUTY_METRICS}
    nights = {p: 0 for p in general_ids}
    for record in records:
        present = {a.employee_id for a in record.context.attendance if a.present}
        for p in general_ids:
            if p not in present:
                continue
            nights[p] += 1
            rows = [r for r in record.assignments if r.employee_id == p]
            counts["barrier"][p] += sum(r.barrier_install_flag or r.barrier_remove_flag for r in rows)
            for r in rows:
                if r.actual_post_or_work_type.kind == AssignmentKind.PATROL and r.actual_post_or_work_type.label in counts:
                    counts[r.actual_post_or_work_type.label][p] += 1
    rates = {}
    for m in DUTY_METRICS:
        seen = [counts[m][p] / nights[p] for p in general_ids if nights[p]]
        team = sum(seen) / len(seen) if seen else 0
        rates[m] = {p: round(100 * (counts[m][p] / nights[p] if nights[p] else team)) for p in general_ids}
    return rates


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
                        post_operations=request.post_operations)


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
                     tuple(r.posture_or_mode for r in rows))


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
    counts = Counter(r.displayed_assignment.label for r in rows)
    posture_by_post = {
        label: {
            "standing": sum(r.displayed_assignment.label == label and r.posture_or_mode == Posture.STANDING for r in rows),
            "seated": sum(r.displayed_assignment.label == label and r.posture_or_mode == Posture.SEATED for r in rows),
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
                    totals[key][p] += getattr(stats, key)
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
                    weighted[key][p] += weight * getattr(actual_stats[p], key)
        for key in included_keys:
            for p in general_ids:
                if weight_sum[p] > 0:
                    totals[key][p] += round(weighted[key][p] / weight_sum[p] * nights[p])
    last = max(actuals, key=lambda r: r.context.shift_start_date) if actuals else None
    last_rows = last.assignments if last else ()
    derived_install = tuple(dict.fromkeys(r.employee_id for r in last_rows if r.barrier_install_flag))
    derived_remove = tuple(dict.fromkeys(r.employee_id for r in last_rows if r.barrier_remove_flag))
    derived_last_rest = tuple(dict.fromkeys(r.employee_id for r in last_rows if r.slot.index == 13 and r.employee_id in general_ids and r.actual_rest_time_value == 1))
    derived_patrol_excluded = ()
    if last and sum(a.present and a.is_general_worker for a in last.context.attendance) == 6:
        patrolled = {r.employee_id for r in last_rows if r.actual_post_or_work_type.kind == AssignmentKind.PATROL}
        derived_patrol_excluded = tuple(p for p in general_ids if p in {a.employee_id for a in last.context.attendance if a.present and a.is_general_worker} and p not in patrolled)
    previous_install = selection.previous_install_ids if selection.previous_install_ids is not None else derived_install
    previous_remove = selection.previous_remove_ids if selection.previous_remove_ids is not None else derived_remove
    forbid_install = selection.forbid_install_ids if selection.forbid_install_ids is not None else previous_install
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
        duty_rates=duty_rates_from(selection.duty_records, general_ids),
        preference_weights=preference_weights(selection.duty_records, general_ids),
        avoid_cells=avoid_cells(context),
    )


RULE_FLAGS = {"2.6": "rules_v26", "2.10": "rules_v210", "2.12": "rules_v212",
              "2.13": "rules_v213", "2.15": "rules_v215", "2.16": "rules_v216",
              "2.17": "rules_v217", "2.18": "rules_v218", "2.19": "rules_v219", "2.20": "rules_v220"}


def validator_flags_for(rules_version: str, reoptimization: bool) -> dict:
    """Independent validator flags for a rules version (shared by revalidation)."""
    if rules_version == "2.13":
        return {"rules_v212": True}
    if rules_version == "2.17":
        return {"rules_v216": True}
    if rules_version in ("2.18", "2.19", "2.20"):
        return {RULE_FLAGS[rules_version]: True, "reoptimization": reoptimization}
    return {RULE_FLAGS[rules_version]: True}


def revalidate(result: "ServiceResult", record: ShiftRecord) -> "ServiceResult":
    """Validate a manually edited record exactly like a generated one."""
    errors = validate_first_trial(
        seat_form_record(record), result.prepared_inputs.engine_history,
        forbid_patrol_exclusion_ids=result.prepared_inputs.forbid_patrol_exclusion_ids,
        **validator_flags_for(result.rules_version, result.rebalance_info is not None))
    if record.context.manager_handover and not errors:
        k, proxy = record.context.manager_handover
        errors = [{"rule": "handover", "detail": f"{proxy}/{k}: 교대 시점 {issue}"}
                  for issue in handover_boundary_issues(record, proxy, k)]
    stats = calculate_all_stats(record) if not errors else result.employee_stats
    return replace(result, context=record.context,
                   solve_result=replace(result.solve_result, record=record),
                   validation_errors=tuple(errors), employee_stats=stats)


def flexible_view(record: ShiftRecord) -> ShiftRecord:
    """FM 표의 칸 배정은 그대로 두고 유도리로 다시 계산한 표 (룰북 0-2-1 확인용).

    10-1 I1 00~03시 휴게성, 10-4 20시 설치 = 설치 포스트 + 보안실 대기 1명(FM에서 설치한 사람), 10-5 04시 I1 철수.
    """
    context = replace(record.context, requested_mode=Mode.FLEXIBLE, effective_mode=Mode.FLEXIBLE,
                      post_operations=None)
    installer = _installer_post(compile_common_policy(context), context)
    fm_installers = {r.employee_id for r in record.assignments if r.barrier_install_flag and r.slot.index == 2}
    rows = []
    for r in record.assignments:
        label, slot = r.displayed_assignment.label, r.slot.index
        if r.displayed_assignment.kind == AssignmentKind.UNAVAILABLE:
            rows.append(replace(r, mode=Mode.FLEXIBLE))
            continue
        install = slot == 2 and (label == installer or (label == "보안실 대기" and r.employee_id in fm_installers))
        rows.append(make_record(context, r.employee_id, slot, label, install=install,
                                remove=slot == 10 and label == "I1", patrol_standing=True))
    return replace(record, record_id=record.record_id + "-flexible-view", context=context, assignments=tuple(rows))


def run_schedule(request: ShiftRequest | ShiftContext, history: HistorySelection | None = None,
                 options: SolveOptions | None = None) -> ServiceResult:
    """룰북 0-2-1: FM이면 두 기준(하드룰+당일 목표) → 두 기준 하드룰 → FM만 순서로 찾는다."""
    context = request if isinstance(request, ShiftContext) else build_context(request)
    config = options if options is not None else SolveOptions()
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
            forbid_patrol_exclusion_ids=dual.prepared_inputs.forbid_patrol_exclusion_ids,
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
    solved = solve_first_trial(
        context, prepared.engine_history, seconds=config.seconds,
        historical_totals=prepared.historical_totals, historical_nights=prepared.historical_nights,
        prioritize_history_within_daily_targets=config.prioritize_history_within_daily_targets,
        forbid_install_ids=prepared.forbid_install_ids,
        forbid_last_rest_ids=prepared.forbid_last_rest_ids,
        forbid_patrol_exclusion_ids=prepared.forbid_patrol_exclusion_ids,
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
        **solver_flags,
    )
    if solved.record is None:
        return ServiceResult(context, solved, (), {}, prepared, config.rules_version)
    errors = validate_first_trial(solved.record, prepared.engine_history,
                                  forbid_patrol_exclusion_ids=prepared.forbid_patrol_exclusion_ids,
                                  **validator_flags)
    stats = calculate_all_stats(solved.record) if not errors else {}
    return ServiceResult(solved.record.context, solved, tuple(errors), stats, prepared,
                         config.rules_version)


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
                     reason: str = "긴급 반차", exclude=None, forced_rest=()) -> ServiceResult:
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
                   if row.slot.index < reoptimization_start_index)
    config = options if options is not None else SolveOptions(rules_version=base.rules_version)
    if config.rules_version not in ("2.15", "2.16", "2.17", "2.18", "2.19", "2.20"):
        raise ValueError("긴급 부분고정 재편성은 룰북 v2.15 이상에서만 지원합니다.")
    outcome = run_schedule(
        revised_context,
        history,
        replace(config, exclude_assignments=exclude or None, locked_assignments=locked,
                forced_rest_cells=tuple(forced_rest)),
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
        if config.rules_version in ("2.16", "2.17", "2.18", "2.19", "2.20") and outcome.solve_result.status == "INFEASIBLE":
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


def _swap_rows_from(rows, first: str, second: str, start: int):
    other = {first: second, second: first}
    return tuple(replace(r, employee_id=other[r.employee_id])
                 if r.slot.index >= start and r.employee_id in other else r for r in rows)


def _handover_context(context: ShiftContext, manager: str, proxy: str, k: int, seat: bool) -> ShiftContext:
    attendance = []
    for a in context.attendance:
        if a.employee_id == manager:
            a = replace(a, available_slot_indices=None if seat else tuple(range(k)))
        elif a.employee_id == proxy:
            a = replace(a, available_slot_indices=tuple(range(k)) if seat else None)
        attendance.append(a)
    return replace(context, attendance=tuple(attendance),
                   manager_handover=None if seat else (k, proxy))


def _manager_id(context: ShiftContext) -> str:
    return next(a.employee_id for a in context.attendance if a.present and a.acts_as_manager)


def seat_form_record(record: ShiftRecord) -> ShiftRecord:
    """Engine view of a record (identity when there is no manager handover)."""
    handover = record.context.manager_handover
    if not handover:
        return record
    k, proxy = handover
    manager = _manager_id(record.context)
    return replace(record, context=_handover_context(record.context, manager, proxy, k, True),
                   assignments=_swap_rows_from(record.assignments, manager, proxy, k))


def display_form_record(record: ShiftRecord, k: int, proxy: str) -> ShiftRecord:
    manager = _manager_id(record.context)
    return replace(record, context=_handover_context(record.context, manager, proxy, k, False),
                   assignments=_swap_rows_from(record.assignments, manager, proxy, k))


def _seat_result(result: ServiceResult) -> ServiceResult:
    record = seat_form_record(result.record)
    return replace(result, context=record.context,
                   solve_result=replace(result.solve_result, record=record))


def handover_boundary_issues(record: ShiftRecord, proxy: str, k: int) -> list[str]:
    """준호's own continuity across the handover (display form)."""
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
    if base.record is not None and base.record.context.manager_handover:
        k, proxy = base.record.context.manager_handover
        manager = _manager_id(base.context)
        if unavailable_employee_id in (manager, proxy):
            raise ValueError("이미 관리자 교대가 있는 근무표에서는 통제·관리자 대행자의 추가 이탈을 재편성할 수 없습니다.")
        outcome = _reoptimize_core(_seat_result(base), reoptimization_start_index, unavailable_employee_id,
                                   unavailable_from_index, history, options, reason, exclude)
        return _to_display(outcome, k, proxy)

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
    last = None
    # Boundary ladder: plain → seat rests at k → seat rests at k and k+1.
    for forced in ((), (k,), (k, k + 1)):
        cells = tuple((manager, t) for t in forced if t < 14)
        if forced and len(cells) == (len(last_cells) if last is not None else -1):
            break
        last_cells = cells
        seat = _reoptimize_core(base, reoptimization_start_index, proxy, k, history, options, label,
                                exclude, forced_rest=cells)
        shown = _to_display(seat, k, proxy)
        shown = replace(shown, rebalance_info=(replace(shown.rebalance_info, unavailable_employee_id=manager)
                                               if shown.rebalance_info else None))
        if seat.record is None or seat.validation_errors:
            return shown if last is None else last
        issues = handover_boundary_issues(shown.record, proxy, k)
        if not issues:
            return shown
        last = replace(shown, validation_errors=tuple(
            {"rule": "handover", "detail": f"{proxy}/{k}: 교대 시점 {issue}"} for issue in issues))
    return last


def _to_display(outcome: ServiceResult, k: int, proxy: str) -> ServiceResult:
    if outcome.record is None:
        return outcome
    record = display_form_record(outcome.record, k, proxy)
    stats = calculate_all_stats(record) if not outcome.validation_errors else outcome.employee_stats
    return replace(outcome, context=record.context,
                   solve_result=replace(outcome.solve_result, record=record), employee_stats=stats)
