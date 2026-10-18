"""Read-only explanations for a generated v2.20 schedule.

This module consumes ServiceResult only.  It does not validate a schedule and
does not recreate solver constraints; it explains observable soft outcomes
that the v2.20 engine already optimizes.
"""

from __future__ import annotations

from dataclasses import dataclass

from .models import AssignmentKind, Posture
from .service import ServiceResult


GENERIC_REASON = "상위 제약 및 전체 최적화 결과 해당 권장사항을 충족하지 못함"


@dataclass(frozen=True)
class SoftRuleFinding:
    rule_id: str
    title: str
    employee_id: str
    employee_name: str
    display_number: int | None
    time_range: str
    detail: str

    @property
    def employee_label(self) -> str:
        if self.employee_id == "A":
            return self.employee_name
        prefix = self.display_number if self.display_number is not None else "A"
        return f"{prefix} {self.employee_name}"


AUTO_DETECTABLE_SOFT_RULES = {
    "8-3": "관리자 07시 실제 휴게 우선",
    "H-06": "같은 자세의 실제근무 3시간 연속 회피",
    "H-06-1": "실제 휴게성 상태 4시간 이상 연속 회피",
    "H-08": "연속근무 제한 적용시간 4시간 회피",
    "14-7": "이력상 순찰 회전 대상자의 하층부 순찰 우선",
    "15-4": "전 회차 설치자의 다음 회차 철수 회피",
    "15-5": "전 회차 철수자의 다음 회차 설치 회피",
    "15-7": "실제 포스트 근무 사이 차단봉 단독업무 회피",
}


NOT_AUTOMATICALLY_DETECTABLE = {
    "정상해에서 소프트 미충족의 정확한 원인": "Solver가 각 미충족의 인과관계를 결과 데이터로 제공하지 않으므로 일반 설명만 가능함",
}


def _time_range(start: int, end_exclusive: int) -> str:
    start_hour = (18 + start) % 24
    last_hour = (18 + end_exclusive - 1) % 24
    return f"{start_hour:02d}~{last_hour:02d}시" if end_exclusive - start > 1 else f"{start_hour:02d}시"


def _maximal_runs(rows, predicate, minimum: int):
    runs, current = [], []
    for row in sorted(rows, key=lambda item: item.slot.index):
        if predicate(row):
            current.append(row)
        elif current:
            if len(current) >= minimum:
                runs.append(tuple(current))
            current = []
    if len(current) >= minimum:
        runs.append(tuple(current))
    return tuple(runs)


def analyze_soft_rules(result: ServiceResult) -> tuple[SoftRuleFinding, ...]:
    """Explain missed v2.13 soft preferences visible in one ServiceResult."""
    if result.record is None:
        return ()
    findings: list[SoftRuleFinding] = []
    stats = result.employee_stats
    rows_by_person = {
        employee_id: tuple(row for row in result.record.assignments if row.employee_id == employee_id)
        for employee_id in stats
    }

    def add(rule_id, title, employee_id, start, end, detail=GENERIC_REASON):
        person = stats[employee_id]
        findings.append(SoftRuleFinding(rule_id, title, employee_id, person.name,
                                        person.display_number, _time_range(start, end), detail))

    for employee_id, rows in rows_by_person.items():
        for posture, posture_name in ((Posture.STANDING, "입식"), (Posture.SEATED, "좌식")):
            for run in _maximal_runs(
                rows,
                lambda row, value=posture: row.actual_work_time_value == 1 and row.posture_or_mode == value,
                3,
            ):
                add("H-06", f"{posture_name} 실제근무 3시간 연속 회피", employee_id,
                    run[0].slot.index, run[-1].slot.index + 1)
        for run in _maximal_runs(rows, lambda row: row.actual_rest_time_value == 1, 4):
            add("H-06-1", "실제 휴게성 상태 4시간 이상 연속 회피", employee_id,
                run[0].slot.index, run[-1].slot.index + 1)
        for run in _maximal_runs(
            rows,
            lambda row: row.counts_for_continuous_work_restriction
            or row.actual_post_or_work_type.kind == AssignmentKind.PATROL,
            4,
        ):
            add("H-08", "연속근무 제한 적용시간 4시간 회피", employee_id,
                run[0].slot.index, run[-1].slot.index + 1)
        for index in (2, 10):
            middle = next((row for row in rows if row.slot.index == index), None)
            before = next((row for row in rows if row.slot.index == index - 1), None)
            after = next((row for row in rows if row.slot.index == index + 1), None)
            if (middle and before and after
                    and middle.actual_post_or_work_type.kind == AssignmentKind.BARRIER_ONLY
                    and before.actual_work_time_value == 1 and after.actual_work_time_value == 1):
                add("15-7", "실제 포스트 근무 사이 차단봉 단독업무 회피", employee_id,
                    index - 1, index + 2)

    manager_ids = tuple(att.employee_id for att in result.context.attendance
                        if att.present and att.acts_as_manager)
    if manager_ids:
        manager_id = manager_ids[0]
        manager_rows = {row.slot.index: row for row in rows_by_person[manager_id]}
        # 8-6 관리자 04시 I1 선호는 2026-10-05 삭제(통제A 04시 I1 금지, 8-10) → 권장 미충족으로 표시하지 않는다.
        for t in range(6, 13):                    # 8-9: 00시 이후 관리자 L3 연속 강한 비권장
            here, nxt = manager_rows.get(t), manager_rows.get(t + 1)
            if (here and nxt and here.displayed_assignment.label == "L3"
                    and nxt.displayed_assignment.label == "L3"):
                add("8-9", "00시 이후 관리자 L3 연속 배치 회피", manager_id, t, t + 2)
        at_07 = manager_rows.get(13)
        general_at_07 = sum(att.is_available(13) for att in result.context.attendance
                            if att.present and att.is_general_worker)
        # v2.18 §8-3-1: with four general workers at 07 (N1/N3) the manager's
        # L3/I1 work is required, not an unmet preference.
        forced_07 = (result.rules_version in ("2.18", "2.19", "2.20") and general_at_07 == 4
                     and result.context.night_type.value in ("N1", "N3"))
        if at_07 and at_07.actual_work_time_value == 1 and not forced_07:
            add("8-3", "관리자 07시 실제 휴게 우선", manager_id, 13, 14)

    previous_install = set(result.prepared_inputs.previous_install_ids)
    previous_remove = set(result.prepared_inputs.previous_remove_ids)
    rotation_due = set(result.prepared_inputs.patrol_rotation_priority_ids)
    for employee_id, rows in rows_by_person.items():
        if employee_id in previous_install and any(row.barrier_remove_flag for row in rows):
            add("15-4", "전 회차 설치자의 다음 회차 철수 회피", employee_id, 10, 11)
        if employee_id in previous_remove and any(row.barrier_install_flag for row in rows):
            add("15-5", "전 회차 철수자의 다음 회차 설치 회피", employee_id, 2, 3)
        if employee_id in rotation_due:
            patrols = tuple(row for row in rows if row.actual_post_or_work_type.kind == AssignmentKind.PATROL)
            if patrols and not any(row.actual_post_or_work_type.label == "lower" for row in patrols):
                add("14-7", "순찰 회전 대상자의 하층부 순찰 우선", employee_id,
                    patrols[0].slot.index, patrols[-1].slot.index + 1)

    return tuple(sorted(findings, key=lambda item: (item.employee_label, item.time_range, item.rule_id)))


def validation_rows(result: ServiceResult) -> tuple[dict[str, str], ...]:
    """Normalize, without interpreting, fields emitted by the Validator."""
    return tuple({
        "규칙": str(error.get("rule_id", error.get("rule", "규칙"))),
        "대상 직원": str(error.get("employee_name", error.get("employee_id", "—"))),
        "시간대": str(error.get("time_range", error.get("slot", "—"))),
        "실제 위반내용": str(error.get("detail", error)),
    } for error in result.validation_errors)
