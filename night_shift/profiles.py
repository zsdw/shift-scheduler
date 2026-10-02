"""Stages 3/4: explicit operating records for the initial N1/6/A scenario."""
from dataclasses import replace
from .models import mode_at, post_operation, Assignment, AssignmentKind as K, AssignmentRecord, Mode, Posture, SLOTS
from .common import compile_common_policy, core_post_facts

PATROL_FATIGUE = {"upper": 2, "middle": 2, "lower": 1}


def _installer_post(policy, context=None):
    """Flexible 20:00 installer post (§10-4): N1/N2 G2 with 5+ workers, I1 with four;
    N3/N4 always I1."""
    if context is not None and context.night_type.value in ("N3", "N4"):
        return "I1"
    if policy.flexible_from_slot is not None and policy.flexible_from_slot <= 2:
        return "I1"
    return "G2" if policy.profile_general_count >= 5 else "I1"


def make_record(context, employee_id, slot, label, *, install=False, remove=False,
                flexible_04_continuous=False, patrol_standing=False):
    """User confirmed flexible 04 removal is excluded from continuous work."""
    policy = compile_common_policy(context)  # Explicit supported-scope guard.
    mode = mode_at(context, slot)
    dk = K.PATROL if label in PATROL_FATIGUE else K.REST if label == "휴게" else K.SECURITY_STANDBY if label == "보안실 대기" else K.POST
    actual_kind, actual_label = dk, label
    posture = None
    fatigue, work, rest = 0, 0, 1
    same = continuous = False
    meal = patrol_rest = dk in (K.REST, K.SECURITY_STANDBY)
    facts = core_post_facts(context, employee_id, slot, label)
    if facts:
        actual_kind, actual_label, posture, fatigue = facts
        work = int(actual_kind == K.POST)
        rest = 1 - work
        same = continuous = bool(work)
        meal = patrol_rest = not work
    elif label in ("G2", "G3", "G2(1)"):
        posture, fatigue, work, rest = Posture.STANDING, 2, 1, 0
        same = continuous = True
        meal = patrol_rest = False
    elif label == "I1":
        posture, fatigue, work, rest = Posture.SEATED, 1, 1, 0
        same = continuous = True
        meal = patrol_rest = False
        if mode == Mode.FLEXIBLE and slot == 10:
            if flexible_04_continuous is None:
                raise ValueError("Flexible 04 I1 continuous-work interpretation awaits user confirmation")
            # §10-3: one work hour and one fatigue point, posture unspecified.
            posture = None
            continuous = flexible_04_continuous
            remove = True
    elif dk == K.PATROL:
        fatigue, work, rest = PATROL_FATIGUE[label], 1, 0
        posture = Posture.STANDING if patrol_standing else None
        meal = patrol_rest = False
    elif dk in (K.REST, K.SECURITY_STANDBY):
        posture = Posture.REST_LIKE
    else:
        raise ValueError("Unknown assignment: " + label)

    # 유도리 포스트별 운영 (기본: 10-1 I1 00~03시 휴게성, 사용자 지정 시 그 설정). 표시 포스트 그대로인 칸만.
    operation = (post_operation(context, label, slot)
                 if dk == K.POST and actual_kind == K.POST and actual_label == label else None)
    if operation == "rest":                      # 10-1 휴게성 I1과 같은 취급 (사용자 확정)
        actual_kind, actual_label = K.REST, f"{label} 휴게성"
        posture, fatigue, work, rest = Posture.REST_LIKE, 0, 0, 1
        continuous, patrol_rest = False, True
    elif operation == "seated":
        posture, fatigue = Posture.SEATED, 1

    if install and slot != 2 or remove and slot != 10:
        raise ValueError("Default barrier times are 20 and 04")
    if install and remove:
        raise ValueError("Cannot install and remove in one slot")
    if install or remove:
        if mode == Mode.FM and label != "보안실 대기":
            raise ValueError("FM barriers require security standby, never a post")
        if mode == Mode.FLEXIBLE and not (
            label == "보안실 대기" or install and label == _installer_post(policy, context) or remove and label == "I1"
        ):
            raise ValueError("Unsupported flexible barrier assignment for N1/6/A")
        if label == "보안실 대기":
            actual_kind, actual_label = K.BARRIER_ONLY, "barrier_install" if install else "barrier_remove"
            posture, fatigue, work, rest = None, 1, 1, 0
            same = continuous = False
            meal = True  # §13 preserves meal opportunity; relevant only at 18–20.
        patrol_rest = False
    return AssignmentRecord(
        employee_id, SLOTS[slot], Assignment(dk, label), Assignment(actual_kind, actual_label),
        fatigue, work, rest, posture, same, continuous, meal, patrol_rest,
        install, remove, mode, ("§4", "§6–§11", "§13", "user-supplement"),
    )


def options_for(context, employee_id, slot, *, flexible_04_continuous=False, patrol_standing=False):
    policy = compile_common_policy(context)
    attendance = next(a for a in context.attendance if a.employee_id == employee_id)
    if not attendance.is_available(slot):
        unavailable = Assignment(K.UNAVAILABLE, "근무불가")
        return (AssignmentRecord(
            employee_id, SLOTS[slot], unavailable, unavailable,
            0, 0, 0, Posture.REST_LIKE, False, False, False, False,
            False, False, mode_at(context, slot), ("§21-7 availability",),
        ),)
    labels = list(dict.fromkeys(r.displayed_post for r in policy.requirements if r.slot_index == slot))
    labels += [p.area for p in policy.patrols if p.slot_index == slot]
    labels += ["휴게", "보안실 대기"]
    records = []
    for label in labels:
        row = make_record(context, employee_id, slot, label,
                          flexible_04_continuous=flexible_04_continuous, patrol_standing=patrol_standing)
        # Flexible normal I1 at 04 automatically carries removal (§10-5).
        records.append(row)
        if label == "보안실 대기" and slot in (2, 10):
            if mode_at(context, slot) == Mode.FM or slot == 2:
                records.append(make_record(context, employee_id, slot, label,
                    install=slot == 2, remove=slot == 10,
                    flexible_04_continuous=flexible_04_continuous, patrol_standing=patrol_standing))
    if mode_at(context, slot) == Mode.FLEXIBLE and slot == 2:
        installer_post = _installer_post(policy, context)
        records = [replace(r, barrier_install_flag=True) if r.displayed_assignment.label == installer_post else r for r in records]
    return tuple(records)
