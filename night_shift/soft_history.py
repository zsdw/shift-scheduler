"""v2.13 soft-rule history. Only confirmed actual shifts can change debt."""
from collections import defaultdict

from .models import AssignmentKind, RecordKind


TRACKED_SOFT_RULES = ("H-06-1", "H-06", "H-08", "15-7", "14-7")


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
        if any(r.barrier_install_flag or r.barrier_remove_flag for r in rows):
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
