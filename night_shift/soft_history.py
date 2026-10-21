"""v2.13 soft-rule history. Only confirmed actual shifts can change debt."""
from collections import defaultdict
from fractions import Fraction

from .models import AssignmentKind, RecordKind, barrier_history_counts


TRACKED_SOFT_RULES = ("H-06-1", "H-06", "H-08", "15-7", "14-7")


def recent_six_fatigue_averages(records, before):
    """최근 실제 6근무 평균: 화면과 같이 반차·이탈은 당일 일반 평균 대입."""
    from .service import calculate_all_stats
    totals = defaultdict(list)
    recent = sorted((r for r in records if r.context.shift_start_date < before
                     and r.kind == RecordKind.ACTUAL and r.confirmed_at is not None),
                    key=lambda r: r.context.shift_start_date)[-6:]
    for record in recent:
        stats = calculate_all_stats(record)
        full = [Fraction(str(p.fatigue_value)) for p in stats.values()
                if not p.is_manager and p.available_time == 14]
        average = sum(full) / len(full) if full else None
        for pid, person in stats.items():
            value = average if person.available_time < 14 else Fraction(str(person.fatigue_value))
            if value is not None:
                totals[pid].append(value)
    return {pid: sum(values) / len(values) for pid, values in totals.items()}


def rest_tie_groups(group, averages):
    """동일 순번 안에서만 낮은 평균 우선. 기록 없는 사람이 섞이면 기존 목표로 결정."""
    if any(p not in averages for p in group):
        return []
    values = sorted({averages[p] for p in group})
    if len(values) < 2:
        return []
    return [[p for p in group if averages[p] == value] for value in values[:-1]]


def debt_weight(debt, rule, employee_id):
    value = int((debt or {}).get(rule, {}).get(employee_id, 0))
    if value < 0:
        raise ValueError("Soft debt cannot be negative")
    return 1 + value


def patrol_rotation_due(actual_records, debt=None):
    """Employees with two recent actual upper/middle patrols or carried debt."""
    recent = defaultdict(list)
    for record in sorted(actual_records, key=lambda r: r.context.shift_start_date):
        if record.kind != RecordKind.ACTUAL or record.confirmed_at is None:
            raise ValueError("Patrol rotation must use confirmed actual records")
        for attendance in record.context.attendance:
            if not attendance.present or not attendance.is_general_worker:
                continue
            patrols = tuple(r.actual_post_or_work_type.label for r in record.assignments
                            if r.employee_id == attendance.employee_id and r.actual_post_or_work_type.kind == AssignmentKind.PATROL)
            recent[attendance.employee_id].append(patrols)
    due = set()
    for person, nights in recent.items():
        if len(nights) >= 2 and all(patrols and all(area in ("upper", "middle") for area in patrols)
                                     for patrols in nights[-2:]):
            due.add(person)
    due.update(p for p, amount in (debt or {}).get("14-7", {}).items() if amount > 0)
    return frozenset(due)


def update_soft_debt(actual_record, current_debt, rotation_due=()):
    """Apply a completed actual shift; a plan can never update history."""
    if actual_record.kind != RecordKind.ACTUAL or actual_record.confirmed_at is None:
        raise ValueError("Soft debt can only be updated from a confirmed actual shift")
    result = {rule: dict(values) for rule, values in (current_debt or {}).items()}
    by_person = defaultdict(list)
    for row in actual_record.assignments:
        by_person[row.employee_id].append(row)
    general = {a.employee_id for a in actual_record.context.attendance if a.present and a.is_general_worker}
    for person, rows in by_person.items():
        rows.sort(key=lambda r: r.slot.index)
        if len(rows) != 14:
            raise ValueError("Actual shift requires 14 slots per present employee")
        rest_four = any(all(r.actual_rest_time_value for r in rows[i:i+4]) for i in range(11))
        posture_three = any(all(r.actual_work_time_value and r.posture_or_mode == posture for r in rows[i:i+3])
                            for i in range(12) for posture in ("standing", "seated"))
        counted = [r.counts_for_continuous_work_restriction or r.actual_post_or_work_type.kind == AssignmentKind.PATROL for r in rows]
        work_four = any(all(counted[i:i+4]) for i in range(11))
        sandwich = any(rows[i].actual_post_or_work_type.kind == AssignmentKind.BARRIER_ONLY and
                       rows[i-1].actual_work_time_value and rows[i+1].actual_work_time_value for i in (2,10))
        outcomes = {"H-06-1": rest_four, "H-06": posture_three, "H-08": work_four}
        if barrier_history_counts(actual_record.context) and any(r.barrier_install_flag or r.barrier_remove_flag for r in rows):
            outcomes["15-7"] = sandwich
        if person in general and person in rotation_due:
            patrols = [r.actual_post_or_work_type.label for r in rows if r.actual_post_or_work_type.kind == AssignmentKind.PATROL]
            if patrols:
                outcomes["14-7"] = "lower" not in patrols
        for rule, missed in outcomes.items():
            prior = int(result.get(rule, {}).get(person, 0))
            if prior < 0:
                raise ValueError("Soft debt cannot be negative")
            result.setdefault(rule, {})[person] = prior + 1 if missed else 0
    return result


def lower_patrol_wait(events, name):
    """하층 순찰 순번(14-7, 2026-10-19 사용자 확정): 야간·공휴일 주간 순찰 이력에서
    마지막 하층 뒤 상층·중층 순찰을 실제로 한 출근이 3회 이상이면 후보.
    후보면 마지막 하층 날짜('' = 하층 기록 없음, 가장 오래 기다림), 아니면 None."""
    mine = [e for e in events if e.get('name') == name]
    last = max((i for i, e in enumerate(mine) if 'lower' in e.get('zones', ())), default=-1)
    other = sum(1 for e in mine[last + 1:] if e.get('patrol') and set(e.get('zones', ())) & {'upper', 'middle'})
    if other < 3:
        return None
    return mine[last]['date'] if last >= 0 else ''
