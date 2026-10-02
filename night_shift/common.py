"""Stage 2: common requirements and rule predicates, initially N1/6/A.

No mode-specific I1/barrier accounting, solver, independent validator or
history repository is implemented here. Predicates consume explicit actual
records; downstream mode profiles will construct those records.
"""

from dataclasses import dataclass

from .models import AssignmentKind as Kind
from .models import AssignmentRecord, NightType, Posture, ShiftContext


@dataclass(frozen=True)
class Requirement:
    slot_index: int
    displayed_post: str
    general_count: int | None
    total_count: int
    fixed_employee_id: str | None
    rule_ref: str


@dataclass(frozen=True)
class Patrol:
    slot_index: int
    area: str
    fatigue: int


PATROLS = (
    Patrol(3, "upper", 2), Patrol(4, "middle", 2), Patrol(5, "lower", 1),
    Patrol(7, "upper", 2), Patrol(8, "middle", 2), Patrol(9, "lower", 1),
)


@dataclass(frozen=True)
class CommonPolicy:
    requirements: tuple[Requirement, ...]
    manager_id: str
    general_ids: tuple[str, ...]
    staffing_count: int
    manager_is_proxy: bool
    absence_count: int
    patrols: tuple[Patrol, ...] = PATROLS
    profile_general_count: int = 6
    flexible_from_slot: int | None = None
    meal_slots: tuple[int, ...] = (0, 1, 2)
    manager_rest_slot: int = 11  # 05:00, §8-1
    rule_refs: tuple[str, ...] = ("§3", "§5", "§6", "§8", "H-01–H-12", "§14-1")


def compile_common_policy(context: ShiftContext) -> CommonPolicy:
    """Compile the first requested scenario; unsupported is not infeasible."""
    present = tuple(a for a in context.attendance if a.present)
    general = tuple(a.employee_id for a in present if a.is_general_worker)
    managers = tuple(a.employee_id for a in present if a.acts_as_manager)
    manager_is_proxy = bool(managers and next(a for a in present if a.employee_id == managers[0]).display_number is not None)
    staffing_count = len(general) + int(manager_is_proxy)
    absence_count = 7 - len(present)  # Normal roster: controller A + six numbered workers.
    profile_general_count = 6 - absence_count
    if context.partial_vacancy_profile:
        # v2.18 §0-4-1: whole-shift four-worker vacancy profile.
        if absence_count not in (0, 1):
            raise NotImplementedError("Partial vacancy profile applies only with 0/1 full-day absences")
        profile_general_count = 4
    if (context.night_type not in (NightType.N1, NightType.N2, NightType.N3, NightType.N4) or absence_count not in (0, 1, 2)
            or len(managers) != 1 or managers[0] in general):
        raise NotImplementedError("Supported scope: N1/N2/N3/N4 + 4/5/6 general workers + manager")
    if context.day_instructions:
        raise NotImplementedError("Day-specific instructions require explicit interpretation; not silently ignored")
    manager = managers[0]
    requirements = []
    for slot in range(14):
        for post in ("G1", "L3", "I1"):
            fixed = manager if context.night_type in (NightType.N1, NightType.N2) and post == "L3" and slot in (0, 1) else None
            requirements.append(Requirement(slot, post, None, 1, fixed, "§3, §6"))
    def south_for(profile_general_count):
        return _south_rows(context, manager, profile_general_count)

    south = south_for(profile_general_count)
    switch = context.flexible_from_slot
    if switch is not None:
        # v2.20 §0-4-2: locked prefix keeps its original profile; the
        # remainder uses the four-worker vacancy profile.
        south = tuple(r for r in south if r[0] < switch) + tuple(r for r in south_for(4) if r[0] >= switch)
    for slot, post, count, total, fixed in south:
        requirements.append(Requirement(slot, post, count, total, fixed, "§5 + user supplement"))
    return CommonPolicy(tuple(requirements), manager, general, staffing_count, manager_is_proxy, absence_count,
                        profile_general_count=profile_general_count, flexible_from_slot=switch)


def _south_rows(context, manager, profile_general_count):
    south = (
        (0, "G2", 1, 1, None), (0, "G3", 1, 1, None),
        (1, "G2", 1, 1, None), (2, "G2", 1, 1, None),
        (12, "G2", 1, 2, manager), (12, "G2(1)", 1, 1, None),
        (13, "G2", 1, 1, None), (13, "G3", 1, 1, None),
    ) if profile_general_count == 6 else (
        (0, "G2", 1, 1, None),
        (1, "G2", 1, 1, None), (2, "G2", 1, 1, None),
        (12, "G2", 0, 1, manager), (12, "G2(1)", 1, 1, None),
        (13, "G2", 1, 1, None), (13, "G3", 1, 1, None),
    )
    if context.night_type == NightType.N4:
        south = ()
    elif context.night_type == NightType.N3:
        south = tuple(r for r in south if r[0] >= 12)
    elif context.night_type == NightType.N2:
        south = tuple(r for r in south if r[0] < 3 and not (profile_general_count == 4 and r[0] in (1, 2)))
    elif profile_general_count == 4:
        south = tuple(r for r in south if r[0] not in (1, 2))
    return south


def core_post_facts(context: ShiftContext, employee_id: str, slot: int, label: str):
    """Return (actual kind, label, posture, fatigue) for common fixed facts.

    None means mode-specific or not defined here. It is never zero work.
    In particular normal I1 accounting belongs to the later mode profiles.
    """
    policy = compile_common_policy(context)
    if context.night_type in (NightType.N1, NightType.N2) and label == "L3" and slot == 0 and employee_id == policy.manager_id:
        return Kind.SECURITY_STANDBY, "보안실 대기", Posture.REST_LIKE, 0
    if label == "I1" and (slot == 0 and context.night_type in (NightType.N1, NightType.N2)
                          or slot == 13 and context.night_type in (NightType.N1, NightType.N3)):
        return Kind.POST, "L3", Posture.STANDING, 2
    if label == "G1":
        seated = 6 <= slot <= 10  # 00–04 inclusive, §9-1
        return Kind.POST, "G1", Posture.SEATED if seated else Posture.STANDING, 1 if seated else 2
    if label == "L3":
        return Kind.POST, "L3", Posture.STANDING, 2
    return None


def _display_key(row: AssignmentRecord):
    return row.displayed_assignment.label if row.displayed_assignment.kind == Kind.POST else None


def _actual_key(row: AssignmentRecord):
    if not row.counts_for_same_post_consecutive:
        return None
    # Rest-like I1 still counts as I1 for same-post rules (§10-1). 유도리 포스트별 운영으로 휴게성이 된
    # 다른 포스트도 같은 취급 (사용자 확정 2026-10-02).
    if _display_key(row) is not None and row.posture_or_mode == Posture.REST_LIKE:
        return _display_key(row)
    return row.actual_post_or_work_type.label if row.actual_post_or_work_type.kind == Kind.POST else None


def forbidden_same_post_pair(left: AssignmentRecord, right: AssignmentRecord, *, allow_manager_weekend_first_pair=False) -> bool:
    if left.employee_id != right.employee_id or right.slot.index != left.slot.index + 1:
        raise ValueError("Expected adjacent records for one employee")
    actual = (_actual_key(left), _actual_key(right))
    displayed = (_display_key(left), _display_key(right))
    if actual == ("G1", "G1") or displayed == ("G1", "G1"):
        return True  # H-05 takes priority even at allowed boundary pairs.
    if allow_manager_weekend_first_pair and left.slot.index == 0 and displayed == ("L3", "L3"):
        return False  # §6-3: optional manager exception on weekend-start nights.
    if left.slot.index in (11, 12):  # 05→06 and 06→07, clarified display rule
        return displayed[0] is not None and displayed[0] == displayed[1]
    if left.slot.index in (0, 1, 2, 3):  # 18→19 through 21→22
        return actual[0] is not None and actual[0] == actual[1]
    return False  # includes 22→23 and 04→05


@dataclass(frozen=True)
class RuleViolation:
    rule_ref: str
    employee_id: str
    slots: tuple[int, ...]
    detail: str


def person_common_violations(rows: tuple[AssignmentRecord, ...], *, is_manager: bool):
    """Shared predicates for a complete person's shift, not final validation.

    No history/mode-specific checks; the independent validator is stage 6.
    """
    rows = tuple(sorted(rows, key=lambda r: r.slot.index))
    if len(rows) != 14 or tuple(r.slot.index for r in rows) != tuple(range(14)):
        raise ValueError("Expected exactly one record in each of the 14 slots")
    employee_id = rows[0].employee_id
    if any(r.employee_id != employee_id for r in rows):
        raise ValueError("Mixed employee identities")
    issues = []

    def add(ref, indices, detail):
        issues.append(RuleViolation(ref, employee_id, tuple(indices), detail))

    for i in range(13):
        if forbidden_same_post_pair(rows[i], rows[i + 1]):
            add("H-05" if _display_key(rows[i]) == "G1" else "H-03/H-07", (i, i + 1), "Forbidden consecutive post")
    for i in range(5, 10):  # triples wholly inside 23–05
        keys = [_actual_key(r) for r in rows[i:i + 3]]
        if keys[0] is not None and len(set(keys)) == 1:
            add("H-04", range(i, i + 3), "Same post for three consecutive slots")
    for i in range(12):
        window = rows[i:i + 3]
        if all(r.actual_post_or_work_type.kind == Kind.POST and r.posture_or_mode == Posture.STANDING for r in window):
            exception = i == 11 and any(_display_key(r) in ("G2", "G3") for r in window)
            if not exception:
                add("H-06/H-07", range(i, i + 3), "Three standing hours outside the morning exception")
    if all(r.counts_for_continuous_work_restriction for r in rows[10:14]):
        add("H-08", range(10, 14), "Four consecutive actual post-work slots at 04–07")
    if not any(r.counts_as_meal_opportunity for r in rows[:3]):
        add("H-10", range(3), "No meal opportunity at 18–20")
    for i, row in enumerate(rows):
        if row.actual_post_or_work_type.kind == Kind.PATROL:
            for j in range(i + 1, min(i + 3, 14)):
                rest = rows[j]
                if (not rest.counts_as_post_patrol_rest or rest.barrier_install_flag
                        or rest.barrier_remove_flag or rest.actual_work_time_value != 0):
                    add("H-09/H-11", (i, j), "Work during mandatory post-patrol rest")
    if is_manager and (rows[11].actual_rest_time_value != 1 or rows[11].actual_work_time_value != 0):
        add("§8-1", (11,), "Manager must have rest-like time at 05")
    if any(r.barrier_install_flag for r in rows) and any(r.barrier_remove_flag for r in rows):
        add("§15-2", tuple(r.slot.index for r in rows if r.barrier_install_flag or r.barrier_remove_flag), "Same shift installation and removal")
    return tuple(issues)


def staffing_common_violations(policy: CommonPolicy, rows: tuple[AssignmentRecord, ...]):
    """Required displayed staffing and patrol distribution, initial case only."""
    issues = []
    for req in policy.requirements:
        assigned = [r.employee_id for r in rows if r.slot.index == req.slot_index
                    and _display_key(r) == req.displayed_post]
        if (len(assigned) != req.total_count
                or (req.general_count is not None and sum(p in policy.general_ids for p in assigned) != req.general_count)
                or (req.fixed_employee_id is not None and req.fixed_employee_id not in assigned)):
            issues.append(RuleViolation("H-02/" + req.rule_ref, "", (req.slot_index,), "Staffing mismatch: " + req.displayed_post))
    patrol_rows = [r for r in rows if r.actual_post_or_work_type.kind == Kind.PATROL]
    for patrol in policy.patrols:
        matching = [r for r in patrol_rows if r.slot.index == patrol.slot_index
                    and r.actual_post_or_work_type.label == patrol.area]
        if len(matching) != 1:
            issues.append(RuleViolation("§14", "", (patrol.slot_index,), "Patrol coverage mismatch"))
    if len(patrol_rows) != 6:
        issues.append(RuleViolation("§14-1", "", (), "Expected six patrols"))
    manager_patrols = [r for r in patrol_rows if r.employee_id == policy.manager_id]
    if len(manager_patrols) != 1 or manager_patrols[0].slot.index != 3 or manager_patrols[0].actual_post_or_work_type.label != "upper":
        issues.append(RuleViolation("H-12/§14-1", policy.manager_id, (3,), "Manager patrol must be 21 upper only"))
    counts = [sum(r.employee_id == p for r in patrol_rows) for p in policy.general_ids]
    if sorted(counts) != [0, 1, 1, 1, 1, 1]:
        issues.append(RuleViolation("§14-1", "", (), "Five distinct general workers must patrol once"))
    return tuple(issues)
