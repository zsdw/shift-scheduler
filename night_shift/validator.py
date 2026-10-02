"""Stage 6: independent N1/6/A/no-history validator.

Deliberately does not import solver, common predicates or mode profiles.
Reconstructs accounting from displayed labels and barrier facts; never trusts
cached flags or solver status. This is not a validator for other scenarios.
"""
from collections import Counter
from .models import AssignmentKind as K, Mode, NightType, Posture, RecordKind

# 유도리 포스트별 운영 — Solver(models.post_operation)와 따로 적은 Validator 쪽 규칙 (사용자 확정 2026-10-02)
_ALLOWED_OPERATIONS = {"I1": {"rest", "seated"}, "G1": {"seated"}, "L3": {"seated"},
                       "G2": {"rest"}, "G3": {"rest"}, "G2(1)": {"rest"}}
_RULEBOOK_FLEXIBLE = (("I1", 6, 9, "rest"),)     # 룰북 10-1 기본
_BARRIER_FIXED = {("I1", 2), ("G2", 2), ("I1", 10)}   # 20시 설치·04시 철수 칸은 운영 변경 불가


def _expected_operation(context, label, t, mode):
    if mode != Mode.FLEXIBLE or (label, t) in _BARRIER_FIXED:
        return None
    chosen = None
    for post, lo, hi, state in (context.post_operations if context.post_operations is not None
                                else _RULEBOOK_FLEXIBLE):
        if post == label and lo <= t <= hi:
            chosen = state                       # 뒤에 적은 항목이 우선
    return chosen


def validate_first_trial(record, history, *, refinement=False, rules_v22=False, vacancy_policy=False, rules_v26=False, rules_v27=False, rules_v29=False, rules_v210=False, rules_v212=False, rules_v215=False, rules_v216=False, rules_v218=False, rules_v219=False, rules_v220=False, reoptimization=False, forbid_patrol_exclusion_ids=()):
    if rules_v220:
        rules_v219 = True
    if rules_v219:
        rules_v218 = True
    if rules_v218:
        rules_v216 = True
    if rules_v216:
        rules_v215 = True
    if rules_v215:
        rules_v212 = True
    if rules_v212:
        rules_v210 = True
    if rules_v210:
        rules_v29 = True
    if rules_v29:
        rules_v27 = True
    if rules_v27:
        rules_v26 = True
    if rules_v26:
        refinement = rules_v22 = vacancy_policy = True
    errors = []
    def check(condition, rule, detail):
        if not condition:
            errors.append({"rule": rule, "detail": detail})

    c = record.context
    present = [a for a in c.attendance if a.present]
    general = [a.employee_id for a in present if a.is_general_worker]
    role_general_count = len(general)
    managers = [a.employee_id for a in present if a.acts_as_manager]
    manager_is_proxy = len(managers) == 1 and next(a for a in present if a.employee_id == managers[0]).display_number is not None
    headcount = len(general) + int(manager_is_proxy)
    absence_count = 7 - len(present)
    # v2.20 §0-4-2: emergency switch of the unlocked remainder.
    switch = c.flexible_from_slot
    if switch is not None and not (rules_v220 and reoptimization):
        return [{"rule": "§0-4-2", "detail": "Mid-shift flexible switch outside v2.20 re-optimization"}]
    # v2.18 §0-4-1, recomputed independently from attendance: the fewest
    # present people available in any slot.
    fewest_available = min(sum(a.is_available(t) for a in present) for t in range(14))
    effective_absence = 7 - fewest_available
    if rules_v218 and not reoptimization:
        if effective_absence > 2:
            return [{"rule": "scope", "detail": "Some slot has three or fewer available general workers (§0-4-1)"}]
        expected_partial = effective_absence == 2 and absence_count < 2
    else:
        # Re-optimization keeps the original plan's profile (§0-4-1 is planning-time).
        expected_partial = c.partial_vacancy_profile if rules_v218 else False
    if c.partial_vacancy_profile != expected_partial:
        return [{"rule": "§0-4-1", "detail": "Partial vacancy profile flag mismatch"}]
    profile_absence = 2 if c.partial_vacancy_profile else absence_count
    profile_general_count = 6 - profile_absence
    manager_vacancy_policy = rules_v218 and (profile_absence == 2 or switch is not None)
    if switch is not None:
        remaining = min(sum(a.is_available(t) for a in present if a.is_general_worker)
                        for t in range(switch, 14))
        check(remaining <= 4 and absence_count < 2 and not c.partial_vacancy_profile,
              "§0-4-2", "Mid-shift switch without a four-worker remainder")

    def slot_mode(t):
        return Mode.FLEXIBLE if switch is not None and t >= switch else c.effective_mode
    if c.night_type not in (NightType.N1, NightType.N2, NightType.N3, NightType.N4) or absence_count not in (0,1,2) or len(managers) != 1 or managers[0] in general or (absence_count > 0 and not vacancy_policy):
        return [{"rule": "scope", "detail": "Unsupported scenario"}]
    if history.actual_nights != () or history.barrier_entries != () or c.day_instructions:
        return [{"rule": "scope", "detail": "Only explicit first trial with no overrides/history is supported"}]
    check(record.kind == RecordKind.PLAN and record.confirmed_at is None, "§20", "Trial must remain an unconfirmed plan")
    for post, lo, hi, state in (c.post_operations or ()):
        check(state in _ALLOWED_OPERATIONS.get(post, set()) and 0 <= lo <= hi <= 13,
              "유도리 운영", f"고를 수 없는 포스트 운영 {post} {lo}~{hi} {state}")
    expected_mode = Mode.FLEXIBLE if profile_absence == 2 and c.requested_mode == Mode.FM else c.requested_mode
    check(c.effective_mode == expected_mode, "§0", "Incorrect effective mode")
    if c.requested_mode != expected_mode:
        check(bool(c.mode_change_reason), "§0-4", "Automatic switch reason missing")
    manager = managers[0]
    people = general + [manager]
    installer_post = ("G2" if profile_general_count >= 5 else "I1") if rules_v218 else ("G2" if headcount >= 5 else "I1")
    if switch is not None and switch <= 2:
        installer_post = "I1"
    if c.night_type in (NightType.N3, NightType.N4):   # §10-4: N3/N4 설치는 20시 I1 + 보안실 대기
        installer_post = "I1"
    attendance_by_id = {a.employee_id: a for a in present}
    partial_general = {p for p in general if sum(attendance_by_id[p].is_available(t) for t in range(14)) < 14}
    keys = [(r.employee_id, r.slot.index) for r in record.assignments]
    if Counter(keys) != Counter((p, t) for p in people for t in range(14)):
        return errors + [{"rule": "§3/§4", "detail": "Missing, duplicate or unknown employee/slot record"}]
    by = {(r.employee_id, r.slot.index): r for r in record.assignments}
    facts = {}
    post_labels = {"G1", "L3", "I1", "G2", "G3", "G2(1)"}
    patrol_slots = {3: "upper", 4: "middle", 5: "lower", 7: "upper", 8: "middle", 9: "lower"}
    south = {0: {"G2": 1, "G3": 1}, 1: {"G2": 1}, 2: {"G2": 1},
             12: {"G2": 2, "G2(1)": 1}, 13: {"G2": 1, "G3": 1}}
    if profile_general_count < 6:
        south = {0: {"G2": 1}, 1: {"G2": 1}, 2: {"G2": 1}, 12: {"G2": 1, "G2(1)": 1}, 13: {"G2": 1, "G3": 1}}
    if profile_general_count == 4:
        south.pop(1, None); south.pop(2, None)
    if switch is not None:
        # Four-worker vacancy profile from the switch slot onward.
        four = {0: {"G2": 1}, 12: {"G2": 1, "G2(1)": 1}, 13: {"G2": 1, "G3": 1}}
        south = {t: posts for t, posts in south.items() if t < switch}
        south.update({t: posts for t, posts in four.items() if t >= switch})
    if c.night_type == NightType.N4:
        south = {}
    elif c.night_type == NightType.N3:
        south = {t: posts for t, posts in south.items() if t >= 12}
    elif c.night_type == NightType.N2:
        south = {t: posts for t, posts in south.items() if t < 3}
    for (p, t), r in by.items():
        label = r.displayed_assignment.label
        if not attendance_by_id[p].is_available(t):
            expected = (K.UNAVAILABLE, K.UNAVAILABLE, "근무불가", Posture.REST_LIKE,
                        0, 0, 0, False, False, False, False, slot_mode(t))
            observed = (r.displayed_assignment.kind, r.actual_post_or_work_type.kind,
                        r.actual_post_or_work_type.label, r.posture_or_mode, r.fatigue_value,
                        r.actual_work_time_value, r.actual_rest_time_value,
                        r.counts_for_same_post_consecutive,
                        r.counts_for_continuous_work_restriction,
                        r.counts_as_meal_opportunity, r.counts_as_post_patrol_rest, r.mode)
            check(observed == expected, "§21-7", f"Unavailable slot accounting mismatch {p}/{t}")
            facts[p, t] = dict(label="근무불가", actual="근무불가", kind=K.UNAVAILABLE,
                               posture=Posture.REST_LIKE, fatigue=0, work=0, rest=0,
                               same=False, continuous=False, meal=False, post_rest=False)
            continue
        check(r.displayed_assignment.kind != K.UNAVAILABLE, "§21-7", f"Available slot marked unavailable {p}/{t}")
        if label not in post_labels | {"upper", "middle", "lower", "휴게", "보안실 대기"}:
            check(False, "§3", f"Unknown label {p}/{t}/{label}")
            continue
        dk = K.POST if label in post_labels else K.PATROL if label in ("upper", "middle", "lower") else K.REST if label == "휴게" else K.SECURITY_STANDBY
        actual_kind, actual_label = dk, label
        posture, fatigue, work, rest = Posture.REST_LIKE, 0, 0, 1
        same = continuous = False
        meal = post_rest = dk in (K.REST, K.SECURITY_STANDBY)
        if dk == K.POST:
            posture, fatigue, work, rest = Posture.STANDING, 2, 1, 0
            same = continuous = True
            meal = post_rest = False
            if label == "G1" and t in (6, 7, 8, 9, 10):
                posture, fatigue = Posture.SEATED, 1
            if label == "I1":
                if t == 0 and c.night_type in (NightType.N1, NightType.N2) or t == 13 and c.night_type in (NightType.N1, NightType.N3):
                    actual_label = "L3"
                else:
                    posture, fatigue = Posture.SEATED, 1
                if slot_mode(t) == Mode.FLEXIBLE and t == 10:
                    posture, continuous = None, False
                    check(r.barrier_remove_flag, "§10-5", "Flexible 04 I1 must remove barrier")
            if c.night_type in (NightType.N1, NightType.N2) and p == manager and t == 0 and label == "L3":
                actual_kind, actual_label = K.SECURITY_STANDBY, "보안실 대기"
                posture, fatigue, work, rest = Posture.REST_LIKE, 0, 0, 1
                same = continuous = False
                meal = post_rest = True
            # 유도리 포스트별 운영: Validator가 직접 다시 계산 (Solver 쪽 함수를 쓰지 않음)
            operation = _expected_operation(c, label, t, slot_mode(t))
            if operation is not None and actual_kind == K.POST and actual_label == label:
                if operation == "rest":
                    actual_kind, actual_label = K.REST, f"{label} 휴게성"
                    posture, fatigue, work, rest = Posture.REST_LIKE, 0, 0, 1
                    continuous, post_rest = False, True
                else:
                    posture, fatigue = Posture.SEATED, 1
        elif dk == K.PATROL:
            posture, fatigue, work, rest = Posture.STANDING if rules_v210 else None, 1 if label == "lower" else 2, 1, 0
            meal = post_rest = False
            check(patrol_slots.get(t) == label, "§14", f"Unexpected patrol {p}/{t}")
        if r.barrier_install_flag or r.barrier_remove_flag:
            check(not (r.barrier_install_flag and r.barrier_remove_flag), "§15-2", "Both barrier operations in one slot")
            check(not r.barrier_install_flag or t == 2, "§10/§11", "Installation at wrong hour")
            check(not r.barrier_remove_flag or t == 10, "§10/§11", "Removal at wrong hour")
            allowed = label == "보안실 대기" if slot_mode(t) == Mode.FM else (
                r.barrier_install_flag and label in (installer_post, "보안실 대기") or r.barrier_remove_flag and label == "I1")
            check(allowed, "§10/§11", f"Invalid barrier worker {p}/{t}/{label}")
            if label == "보안실 대기":
                actual_kind = K.BARRIER_ONLY
                actual_label = "barrier_install" if r.barrier_install_flag else "barrier_remove"
                posture, fatigue, work, rest = None, 1, 1, 0
                same = continuous = False
                meal = True
            post_rest = False
        expected = (dk, actual_kind, actual_label, posture, fatigue, work, rest, same, continuous, meal, post_rest, slot_mode(t))
        observed = (r.displayed_assignment.kind, r.actual_post_or_work_type.kind, r.actual_post_or_work_type.label,
                    r.posture_or_mode, r.fatigue_value, r.actual_work_time_value, r.actual_rest_time_value,
                    r.counts_for_same_post_consecutive, r.counts_for_continuous_work_restriction,
                    r.counts_as_meal_opportunity, r.counts_as_post_patrol_rest, r.mode)
        check(observed == expected, "§4/§6–§11", f"Accounting or mode mismatch {p}/{t}")
        facts[p, t] = dict(label=label, actual=actual_label, kind=actual_kind, posture=posture,
                           fatigue=fatigue, work=work, rest=rest, same=same, continuous=continuous,
                           meal=meal, post_rest=post_rest)
    if len(facts) != len(people)*14:
        return errors
    for t in range(14):
        labels = Counter(facts[p, t]["label"] for p in people if facts[p, t]["label"] in post_labels)
        expected = Counter({"G1": 1, "L3": 1, "I1": 1, **south.get(t, {})})
        check(labels == expected, "H-02/§5", f"Post coverage mismatch at {t}")
        for label in south.get(t, {}):
            count = sum(facts[p, t]["label"] == label for p in general)
            check(count == ((1 if profile_absence == 0 and (switch is None or t < switch) else 0) if t == 12 and label == "G2" else south[t][label]), "§5", f"General south staffing {t}/{label}")
        patrols = [facts[p, t]["label"] for p in people if facts[p, t]["kind"] == K.PATROL]
        check(patrols == ([patrol_slots[t]] if t in patrol_slots else []), "§14", f"Patrol coverage at {t}")
    if c.night_type in (NightType.N1, NightType.N2):
        check(facts[manager, 0]["label"] == facts[manager, 1]["label"] == "L3", "§6", "Manager L3 first two displayed slots")
    if c.night_type in (NightType.N1, NightType.N3):
        check(facts[manager, 12]["label"] == "G2", "§8-2", "Manager 06 G2")
    check(facts[manager, 11]["work"] == 0, "§8-1", "Manager 05 rest")
    general_at_07 = sum(attendance_by_id[p].is_available(13) for p in general)
    if rules_v218 and c.night_type in (NightType.N1, NightType.N3) and general_at_07 == 4:
        check(facts[manager, 13]["work"] == 1 and facts[manager, 13]["label"] in ("L3", "I1"), "§8-3-1", "Manager must work 07 on L3/I1 with four general workers")
    elif rules_v215 and c.night_type in (NightType.N1, NightType.N3):
        check(facts[manager, 13]["rest"] == 1, "§8-3", "N1/N3 manager must rest at 07")
    else:
        check(facts[manager, 13]["work"] == 0 or facts[manager, 13]["label"] in ("L3", "I1"), "§8-3", "Manager 07 permitted assignment")
    check(facts[manager, 3]["label"] == "upper", "H-12", "Manager 21 upper patrol")
    patrol_counts = {p: sum(facts[p, t]["kind"] == K.PATROL for t in range(14)) for p in people}
    if switch is not None:
        for p in people:
            check(patrol_counts[p] <= 2, "§14-3-1", f"More than two patrols {p}")
            for half in ((3, 4, 5), (7, 8, 9)):
                check(sum(facts[p, t]["kind"] == K.PATROL for t in half) <= 1, "§14-3-1", f"Patrol half distribution {p}")
            if all(attendance_by_id[p].is_available(t) for t in range(14)):
                check(patrol_counts[p] >= 1, "§14-3-1", f"Available all night but no patrol {p}")
    elif headcount == 6:
        expected_patrols = [1, 1, 1, 1, 1] if manager_is_proxy else [0, 1, 1, 1, 1, 1]
        check(patrol_counts[manager] == 1 and sorted(patrol_counts[p] for p in general) == expected_patrols, "§14-1/14-4", "Patrol distribution")
        if rules_v212 and not manager_is_proxy and absence_count == 0:
            for p in forbid_patrol_exclusion_ids:
                if p in general:
                    check(patrol_counts[p] == 1, "§14-1", f"Previous patrol exclusion repeated: {p}")
    elif headcount == 5 and not manager_is_proxy:
        check(patrol_counts[manager] == 1 and all(patrol_counts[p] == 1 for p in general), "§14-2", "Five-worker patrol distribution")
    if rules_v26 and (headcount == 4 or manager_is_proxy and headcount < 6) and switch is None:
        check(sorted(patrol_counts.values()) == [1,1,1,1,2], "§14-3", "Exactly one double patrol")
        for p in people:
            for half in ((3,4,5),(7,8,9)):
                check(sum(facts[p,t]["kind"] == K.PATROL for t in half) <= 1, "§14-3", f"Patrol half distribution {p}")
    for p in people:
        f = [facts[p, t] for t in range(14)]
        same_keys = [x["actual"] if x["same"] and x["kind"] == K.POST else "I1" if x["same"] and x["label"] == "I1" else None for x in f]
        for t in range(13):
            check(not (f[t]["label"] == f[t + 1]["label"] == "G1"), "H-05", f"G1 consecutive {p}/{t}")
            if t in (0, 1, 2, 3) and not (c.night_type in (NightType.N3, NightType.N4) and p == manager and t == 0 and f[t]["label"] == f[t+1]["label"] == "L3"):
                check(same_keys[t] is None or same_keys[t] != same_keys[t + 1], "H-03", f"Evening same post {p}/{t}")
            if t in (11, 12):
                check(f[t]["label"] not in post_labels or f[t]["label"] != f[t + 1]["label"], "H-07", f"Morning repeated display {p}/{t}")
        for t in (range(12) if rules_v26 else range(5, 10)):
            check(not (same_keys[t] is not None and len(set(same_keys[t:t + 3])) == 1), "H-04", f"Night triple {p}/{t}")
        for t in range(12):
            all_standing = all(x["work"] == 1 and x["posture"] == Posture.STANDING for x in f[t:t + 3]) if rules_v210 else all(x["kind"] == K.POST and x["posture"] == Posture.STANDING for x in f[t:t + 3])
            allowed = t == 11 and any(x["label"] in ("G2", "G3") for x in f[11:14])
            if not rules_v27 or t == 11:
                check(not all_standing or allowed, "H-06/H-07", f"Standing triple {p}/{t}")
        if rules_v26:
            counted=[x["continuous"] or x["kind"] == K.PATROL for x in f]
            for start in range(10):
                check(not all(counted[start:start+5]), "H-08", f"Five continuous work slots {p}/{start}")
            for start in range(11):
                check(not all(counted[start:start+4]) or any(x["work"] == 1 and x["posture"] == Posture.SEATED for x in f[start:start+4]), "H-08", f"Four hours without seated work {p}/{start}")
        else:
            check(not all(x["continuous"] for x in f[10:14]), "H-08", f"04–07 continuous work {p}")
        if any(attendance_by_id[p].is_available(t) for t in (0, 1, 2)):
            check(any(x["meal"] for x in f[:3]), "H-10", f"No meal {p}")
        protected_ok = []
        for t in patrol_slots:
            if f[t]["kind"] == K.PATROL:
                relaxed_patrol_rest = profile_absence == 2 or (switch is not None and t + 2 >= switch)
                if relaxed_patrol_rest:
                    window = (t + 1, t + 2)
                    has_rest = any(f[j]["post_rest"] and f[j]["work"] == 0 and not by[p, j].barrier_install_flag and not by[p, j].barrier_remove_flag for j in window)
                    i1_ok = t < 7 or all(f[j]["work"] == 0 or f[j]["label"] == "I1" for j in window)
                    if rules_v220:
                        # H-11-2: at least one of the person's patrols must keep
                        # the H-11 recovery; the other may be ordinary work.
                        protected_ok.append(has_rest and i1_ok)
                    else:
                        check(has_rest, "H-11", f"Flexible patrol rest missing {p}/{t}")
                        if t >= 7:
                            for j in window:
                                check(f[j]["work"] == 0 or f[j]["label"] == "I1", "H-11", f"Post-00 patrol work must display I1 {p}/{j}")
                    if rules_v29 and f[t - 1]["work"] == 1 and f[t - 1]["posture"] == Posture.STANDING:
                        check(f[t + 1]["work"] == 0 or f[t + 1]["posture"] == Posture.SEATED,
                              "H-11-immediate-recovery", f"Standing-patrol-standing {p}/{t}")
                else:
                    for j in (t + 1, t + 2):
                        check(f[j]["post_rest"] and f[j]["work"] == 0 and not by[p, j].barrier_install_flag and not by[p, j].barrier_remove_flag, "H-11", f"Post patrol rest {p}/{j}")
                        if slot_mode(j) == Mode.FM:
                            check(f[j]["label"] == "휴게", "user-display", f"Explicit post patrol rest {p}/{j}")
                    protected_ok.append(True)
        if rules_v220 and protected_ok:
            check(any(protected_ok), "H-11-2", f"No protected patrol recovery {p}")
        check(not (any(by[p, t].barrier_install_flag for t in range(14)) and any(by[p, t].barrier_remove_flag for t in range(14))), "§15-2", f"Install/remove overlap {p}")
    installers = [r for r in record.assignments if r.barrier_install_flag]
    removers = [r for r in record.assignments if r.barrier_remove_flag]
    check(len(installers) == (1 if slot_mode(2) == Mode.FM else 2) and len(removers) == 1, "§10/§11", "Barrier staffing count")
    if slot_mode(2) == Mode.FLEXIBLE:
        check(Counter(r.displayed_assignment.label for r in installers) == Counter([installer_post, "보안실 대기"]), "§10-4", "Flexible installer composition")
    if refinement:
        for t in range(14):
            count = sum(facts[p, t]["label"] == "보안실 대기" for p in people)
            if rules_v26:
                if t in (2,10):
                    check(count >= 1, "H-16", f"Missing required standby {t}")
                if rules_v212 and t == 10:
                    check(count == 1, "H-16", f"04 standby count must be one, got {count}")
                if rules_v212 and t == 2:
                    required_duty = sum(facts[p,t]["kind"] in (K.POST,K.PATROL) for p in people)
                    check(count == min(2, len(people)-required_duty), "H-16", f"20 standby count must match capacity, got {count}")
            elif vacancy_policy and headcount < 6 and t not in (2,10):
                check(count <= 1, "user-standby", f"Too many optional standby at {t}")
            else:
                check(count == 1, "user-standby", f"Expected one displayed standby at {t}, got {count}")
        if profile_absence == 0 and switch is None:
            for t in range(6, 10):
                check(sum(facts[manager, j]["work"] for j in range(t, t + 3)) <= 2,
                      "user-A-00-05", f"Manager three consecutive actual work hours at {t}")
        # 04 I1 is a preference, deliberately not an unconditional validation error.
    if rules_v22:
        a_work = sum(facts[manager, t]["work"] for t in range(14))
        for p in general:
            work = sum(facts[p, t]["work"] for t in range(14))
            if (not rules_v215 or p not in partial_general) and not manager_vacancy_policy:
                check(abs(work - a_work) <= 2, "H-15", f"A/general work gap over two hours: {p}/{work}/{a_work}")
            if headcount in (5, 6) and not (rules_v218 and profile_absence == 2) and switch is None and (not rules_v215 or p not in partial_general):
                a_fatigue = sum(facts[manager, t]["fatigue"] for t in range(14))
                p_fatigue = sum(facts[p, t]["fatigue"] for t in range(14))
                if rules_v219 and not manager_is_proxy:
                    check(0 <= p_fatigue - a_fatigue <= 2, "8-4-2", f"A fatigue must be 0-2 below general: {p}/{p_fatigue}/{a_fatigue}")
                else:
                    check(abs(p_fatigue - a_fatigue) <= 4, "8-4-2", f"A/general fatigue gap over four points: {p}/{p_fatigue}/{a_fatigue}")
        for p in people:
            visits = sum(facts[p, t]["label"] in ("G2", "G3") for t in range(3))
            check(visits <= (0 if p == manager else 1), "H-14", f"Evening south gate assignment: {p}/{visits}")
    return errors
