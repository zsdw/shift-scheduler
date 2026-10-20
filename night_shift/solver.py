"""Stage 5. CP-SAT first-trial solver, N1/six general workers/A, no history.

Balance targets are optional feasibility probes, never relaxed hard rules.
No claim of global multiobjective optimality is made for this first trial.
"""
from dataclasses import dataclass, replace
from itertools import permutations
from math import lcm
from ortools.sat.python import cp_model
from .models import BIG_REST_SLOTS, BIG_REST_STARTS, barrier_history_counts, barrier_single, barrier_v2, mode_at, AssignmentKind as K, HistoryInput, Mode, Posture, RecordKind, ShiftRecord
from .soft_history import lower_patrol_wait
from .common import compile_common_policy, forbidden_same_post_pair, _actual_key
from .profiles import options_for
from .soft_history import debt_weight


@dataclass
class SolveResult:
    status: str
    record: ShiftRecord | None
    attempts: list[dict]
    targets_met: bool


def _flexible_delta(row, slot, context=None):
    """FM → 해당 표의 유도리 운영 회계 차이. context 없는 종전 호출은 00~03시."""
    label = row.displayed_assignment.label
    if context is not None:
        from .models import post_operation
        operation = post_operation(context, label, slot)
        if row.actual_post_or_work_type.kind == K.POST and row.actual_post_or_work_type.label == label:
            if operation == "rest":
                return -row.fatigue_value, -row.actual_work_time_value
            if operation == "seated":
                return 1 - row.fatigue_value, 0
        if slot == 10 and row.barrier_remove_flag and label == "보안실 대기":
            return -row.fatigue_value, -row.actual_work_time_value
        return 0, 0
    if label == "I1" and 6 <= slot <= 9 and row.actual_post_or_work_type.kind == K.POST:
        return -row.fatigue_value, -row.actual_work_time_value
    if slot == 10 and row.barrier_remove_flag and label == "보안실 대기":
        return -row.fatigue_value, -row.actual_work_time_value
    return 0, 0


def _add_dual_flexible_constraints(model, opts, variables, policy, context, people, partial_general_ids, *,
                                   gap_rule, fatigue_rule, fatigue_band, skip_partial, balance=False,
                                   big_rest_rule=True, manager_a_end_slot=14, locked_keys=frozenset()):
    """FM 표를 유도리로 계산했을 때의 A 격차·차단봉 조건 (룰북 0-2-1).

    balance=True면 17장 당일 목표(전일 일반근무자 피로도 최대-최소 1점 이하, 실휴게 1시간 이하)를
    FM 기준과 유도리 기준 모두에서 지키게 한다 (0-2-1 1단계).
    """
    from .profiles import _installer_post
    manager = policy.manager_id
    flex_context = replace(context, requested_mode=Mode.FLEXIBLE, effective_mode=Mode.FLEXIBLE)
    installer = _installer_post(policy, flex_context)

    def total(p, attribute, index):
        return sum((getattr(r, attribute) + _flexible_delta(r, t, flex_context)[index]) * v
                   for t in range(14) for r, v in zip(opts[p, t], variables[p, t]))
    work = {p: total(p, "actual_work_time_value", 1) for p in people}
    fatigue = {p: total(p, "fatigue_value", 0) for p in people}
    low, high = fatigue_band
    for p in policy.general_ids:
        if skip_partial and p in partial_general_ids:
            continue
        if gap_rule:                                            # H-15
            model.add(work[p] - work[manager] <= 2)
            model.add(work[manager] - work[p] <= 2)
        if fatigue_rule:                                        # 8-4-2
            model.add(fatigue[p] - fatigue[manager] >= low)
            model.add(fatigue[p] - fatigue[manager] <= high)
    for p in people:                                            # §15-2: 유도리 20시 설치자는 04시 철수(I1) 불가
        if barrier_v2(context):
            break                                               # 15-0: 담당자가 모드와 무관 → 본 제약(설치+철수≤1)으로 충분
        install = sum(v for r, v in zip(opts[p, 2], variables[p, 2])
                      if r.displayed_assignment.label == installer or r.barrier_install_flag)
        remove = sum(v for r, v in zip(opts[p, 10], variables[p, 10]) if r.displayed_assignment.label == "I1")
        model.add(install + remove <= 1)
    if big_rest_rule:                                           # 16-big: 유도리 계산 표에서도 막타임 수혜자의 대폭 휴게 동시 금지
        def flex_rest(p, t):
            return sum(v for r, v in zip(opts[p, t], variables[p, t])
                       if (r.actual_rest_time_value - _flexible_delta(r, t, flex_context)[1]) == 1)
        for pid in people:
            if pid == "A" or (pid == "6" and (manager == "6" or manager_a_end_slot <= 13)):
                continue
            for s in BIG_REST_STARTS:
                window = (s, s + 1, s + 2, 13)
                if all((pid, t) in locked_keys for t in window):
                    continue
                model.add(sum(flex_rest(pid, t) for t in window) <= 3)
    if balance:                                                 # 17장 당일 목표를 두 기준 모두에서
        full = [p for p in policy.general_ids if p not in partial_general_ids]
        for flexible in (False, True):
            for attribute, index, sign in (("fatigue_value", 0, 1), ("actual_rest_time_value", 1, -1)):
                totals = [sum((getattr(r, attribute) + (sign * _flexible_delta(r, t, flex_context)[index] if flexible else 0)) * v
                              for t in range(14) for r, v in zip(opts[p, t], variables[p, t])) for p in full]
                if len(totals) < 2:
                    continue
                hi, lo = model.new_int_var(0, 60, ""), model.new_int_var(0, 60, "")
                model.add_max_equality(hi, totals)
                model.add_min_equality(lo, totals)
                model.add(hi - lo <= 1)


def manager_objectives(manager_work, manager_fatigue, *, rules_v217, manager_is_proxy):
    """Ordered manager-favouring objectives (§0-5, §8-4, §8-4-1).

    v2.17: with A on duty only A's actual work time is minimized; A's fatigue
    is not a manager tie-breaker. When 준호 acts as manager (A absent), actual
    work -> fatigue is kept. Before v2.17 both cases used work -> fatigue.
    This is an objective policy only; no hard rule depends on it.
    """
    objectives = [("manager_work", manager_work)]
    if not rules_v217 or manager_is_proxy:
        objectives.append(("manager_fatigue", manager_fatigue))
    return objectives


def planned_vacancy(context):
    """v2.18 §0-4-1 facts: (effective absence, slot hours with the minimum).

    Effective absence counts the minimum number of present people available in
    any slot, so one full-day leave plus one half-day leave is 2.
    """
    per_slot = [sum(a.is_available(t) for a in context.attendance) for t in range(14)]
    fewest = min(per_slot)
    return 7 - fewest, tuple(t for t, n in enumerate(per_slot) if n == fewest)


# Measured 2026-10-01: these history-balance stages can use the full limit
# (13~45 s each) while every other stage finishes in < 2 s. They keep their best
# value as an upper bound when capped, so later stages still run.
STAGE_TIME_CAPS = {
    "long_term_fatigue_worst": 6.0,
    "long_term_fatigue_spread": 6.0,
    "vacancy_manager_fatigue_gap": 6.0,
    "history_patrol_fatigue_spread": 6.0,
    "duty_3cycle_balance": 6.0,
    "history_standing_spread": 8.0,
    "history_seated_spread": 8.0,
    # 2026-10-18 측정: 맨 마지막 '통제A 0~2점 유지' 목표가 상한 없이 24~45초(전체의 약 1/3)를 썼다.
    # 10/16·21·24·27 실제 이력으로 5초 상한과 비교 → 목표 값·피로도 결과 모두 같고 6~36초 단축.
    "manager_normal_gap_preference": 5.0,
}

from .leave_context import HANDOVER_PROXY, build_leave_context   # 관리자 대행 준호·반차/승계 판정 (2026-10-18)
EARLY_PROXY_FATIGUE_PRIVILEGE = 2   # 통제A 전반부 반차 때 준호 하루 피로도 우대 (2026-10-18 사용자 확정)


def solve_first_trial(context, history: HistoryInput, seconds=30, *, compensation_averages=None, long_term_balances=None, manager_a_end_slot=14, manager_a_start_slot=0, dual_flexible=False, dual_balance=False, post_cap=False, half_day_ids=None, preference_weights=None, avoid_cells=(), refinement=False, baseline_assignments=None, exclude_assignments=None, locked_assignments=None, historical_totals=None, historical_nights=None, prioritize_history_within_daily_targets=False, forbid_install_ids=(), forbid_last_rest_ids=(), forbid_patrol_exclusion_ids=(), patrol_rotation_priority_ids=(), soft_debt=None, previous_install_ids=(), previous_remove_ids=(), minimize_a=False, rules_v22=False, vacancy_policy=False, rules_v26=False, rules_v27=False, rules_v29=False, rules_v210=False, rules_v212=False, rules_v213=False, rules_v215=False, rules_v216=False, rules_v217=False, rules_v218=False, rules_v219=False, rules_v220=False, diagnostic_relaxation_level=0, diagnostic_relaxed_families=None, forced_rest_cells=(), duty_rates=None, patrol_actuals=(), patrol_events=(), last_rest_records=(), emergency_leaver_cells=(), disabled_rule_groups=frozenset(), feasibility_only=False):
    if rules_v220:
        rules_v219 = True
    if rules_v219:
        rules_v218 = True
    if rules_v218:
        rules_v217 = True
    if rules_v217:
        rules_v216 = True
    if rules_v216:
        rules_v215 = True
    if rules_v215:
        rules_v213 = True
    if rules_v213:
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
        refinement = minimize_a = rules_v22 = vacancy_policy = True
        if baseline_assignments is not None:
            raise ValueError("v2.6 requires its own ordered objectives")
    if history.actual_nights != () or history.barrier_entries != ():
        raise NotImplementedError("This trial requires explicitly empty history")
    role_general_count = sum(a.present and a.is_general_worker for a in context.attendance)
    present_manager = next((a.employee_id for a in context.attendance if a.present and a.acts_as_manager), None)
    manager_is_proxy = present_manager is not None and next(a for a in context.attendance if a.employee_id == present_manager).display_number is not None
    headcount = role_general_count + int(manager_is_proxy)
    if headcount < 6 and not vacancy_policy:
        raise NotImplementedError("4/5 worker scenarios require the explicit vacancy policy")
    absence_count = 7 - sum(a.present for a in context.attendance)
    if rules_v218 and locked_assignments is None and not context.partial_vacancy_profile:
        # v2.18 §0-4-1 is decided at planning time only.  Emergency
        # re-optimization keeps the original plan's mode and profile.
        effective_absence, short_slots = planned_vacancy(context)
        if effective_absence > 2:
            raise NotImplementedError("가용 일반근무자가 3명 이하인 시간대가 있어 지원 범위를 벗어납니다 (§0-4-1)")
        if effective_absence == 2 and absence_count < 2:
            hours = ", ".join(f"{(18 + t) % 24:02d}시" for t in short_slots)
            context = replace(context, partial_vacancy_profile=True, effective_mode=Mode.FLEXIBLE,
                              mode_change_reason=f"§0-4-1: 반차 등으로 가용 일반근무자 4명인 시간대({hours})가 있어 회차 전체를 유도리·결원 2명 규칙으로 편성")
    profile_absence = 2 if context.partial_vacancy_profile else absence_count
    if absence_count == 2 and context.requested_mode == Mode.FM:
        context = replace(context, effective_mode=Mode.FLEXIBLE, mode_change_reason="§0-4: FM with four general workers automatically switches to flexible")
    # v2.20 §0-4-2: emergency switch of the unlocked remainder to flexible +
    # vacancy-2 rules (set by the service before re-optimization).
    switch_slot = context.flexible_from_slot
    if switch_slot is not None and not rules_v220:
        raise ValueError("Mid-shift flexible switch requires rules v2.20")
    # v2.18 §8-7: on vacancy-2 days the manager has no minimum-burden privilege.
    manager_vacancy_policy = rules_v218 and (profile_absence == 2 or switch_slot is not None)

    def rule_off(group):
        """충돌 진단용(2026-10-18): 이 하드 규칙 묶음을 끈 채 해가 있는지만 본다. 실제 생성에서는 항상 False."""
        return group in disabled_rule_groups

    def relaxed(level):
        """21-8 diagnosis: a rule family is relaxed only for diagnostic probes."""
        if diagnostic_relaxed_families is not None:
            return level in diagnostic_relaxed_families
        return diagnostic_relaxation_level >= level
    policy = compile_common_policy(context)
    people = (*policy.general_ids, policy.manager_id)
    attendance_by_id = {a.employee_id: a for a in context.attendance}
    available_counts = {
        p: sum(attendance_by_id[p].is_available(t) for t in range(14)) for p in people
    }
    partial_general_ids = tuple(p for p in policy.general_ids if available_counts[p] < 14)
    # v2.18 §8-3-1: N1/N3 07 needs five general-or-manager bodies; with four
    # available general workers the manager works 07 on L3 or I1.
    manager_works_07 = (rules_v218 and context.night_type.value in ("N1", "N3")
                        and sum(attendance_by_id[p].is_available(13) for p in policy.general_ids) == 4)
    full_general_ids = tuple(p for p in policy.general_ids if available_counts[p] == 14)
    # 통제A 반차·준호 승계·긴급 반차/이탈 판정은 leave_context 한곳에서 (2026-10-18, Validator·서비스와 같은 판정)
    leave = build_leave_context(manager_id=policy.manager_id, general_ids=policy.general_ids,
                                partial_general_ids=partial_general_ids, half_day_ids=half_day_ids,
                                emergency=locked_assignments is not None, emergency_leaver_cells=emergency_leaver_cells,
                                manager_a_start_slot=manager_a_start_slot, manager_a_end_slot=manager_a_end_slot,
                                rules_v220=rules_v220)
    # 준호 관리자 승계(미리 정한 반차 + 긴급 이탈 인계 모두): 자리 형태에서 준호 줄이 반나절, 관리자 자리가 나머지.
    # 전반부 반차 → 준호 하루 합계 2점 우대 n빵, 후반부 반차 → 준호 하루 합계에 통제A 피로도·실근무 규칙.
    proxy_handover = leave.proxy_handover
    planned_handover = leave.planned
    late_proxy_manager_rules = leave.late_half
    # 14-2 예외 [하드, 2026-10-18 사용자 확정]: 결원 1명 + 미리 정한 통제A 반차 → 준호는 관리자 자리 순찰만,
    # 나머지 일반근무자 4명이 5회(정확히 1명 2회, 14-3: 전반부·후반부 1회씩, 14-6 소프트 우선순위).
    proxy_patrol_exception = planned_handover and absence_count == 1
    # 결원 2명 규칙 날(§8-7)은 통제A도 관리자 우대가 없으므로 후반부 준호도 우대 대신 n빵.
    proxy_in_balance = planned_handover and (manager_a_start_slot > 0 or manager_vacancy_policy)
    # H-09-1 반차자 = 미리 정한 반차자 + 긴급 반차·이탈자(빠지기 전 남은 칸이 있는 사람).
    # 긴급 반차·이탈자는 빠지기 전 남은(LOCK 아닌) 시간에 배려하지 않는다: 실휴게 2시간 이상·입식 3연속 금지만 하드.
    half_day = set(leave.half_day_ids)
    leaver_ids = set(leave.leaver_ids)
    manager_leaves = leave.manager_leaves
    # 통제A 긴급 반차·이탈 (2026-10-18 사용자 확정): 빠지기 전 남은 칸은 I1 금지(하드), 휴게는 최대한 적게(소프트 맨 앞).
    # 이미(LOCK 구간) 실휴게가 2시간 이상이면 연속근무 규칙(H-08·4시간 좌식) 없이 최대한 근무
    # ('전부 근무' 하드는 준호 최저 피로도와 충돌 → 사용자 결정으로 통제A 쪽을 양보),
    # 1시간 이하면 연속근무 규칙을 지키며 필요한 곳만 휴게 — 3연속 입식(순찰 포함)은 허용하되 4연속 근무 안에서는 입식 3연속 금지.
    manager_leaver_slots = set(leave.manager_leaver_slots)
    manager_prior_rest = sum(int(r.actual_rest_time_value) for r in locked_assignments or ()
                             if r.employee_id == policy.manager_id)
    manager_leaver_free = bool(manager_leaver_slots) and manager_prior_rest >= 2
    attempts = []
    # Optional all-target probe first. Fallback preserves every hard rule.
    for target_probe in ((False,) if rules_v26 else (True, False)):
        model = cp_model.CpModel()
        opts, variables = {}, {}
        for p in people:
            for t in range(14):
                opts[p, t] = options_for(context, p, t, patrol_standing=rules_v210)
                variables[p, t] = [model.new_bool_var(f"{p}_{t}_{i}") for i in range(len(opts[p, t]))]
                model.add_exactly_one(variables[p, t])

        def expression(p, t, predicate):
            return sum(v for r, v in zip(opts[p, t], variables[p, t]) if predicate(r))

        def proxy_day_total(attr):
            """미리 정한 통제A 반차의 준호 화면 기준 하루 합계 = 자기 줄 + 대행한 관리자 자리 (2026-10-18)."""
            k = manager_a_start_slot or manager_a_end_slot
            own, seat = (range(k, 14), range(k)) if manager_a_start_slot else (range(k), range(k, 14))
            return (sum(int(getattr(r, attr)) * v for t in own for r, v in zip(opts[HANDOVER_PROXY, t], variables[HANDOVER_PROXY, t]))
                    + sum(int(getattr(r, attr)) * v for t in seat
                          for r, v in zip(opts[policy.manager_id, t], variables[policy.manager_id, t])))

        # [하드, 2026-10-18 사용자 확정] 통제A 긴급 반차·이탈: 빠지기 전 남은 칸 (위 manager_leaver_* 설명)
        manager_leaver_rests = 0
        if manager_leaver_slots:
            m = policy.manager_id
            def work(t):
                return expression(m, t, lambda r: r.actual_work_time_value == 1)
            def standing(t):
                return expression(m, t, lambda r: r.actual_work_time_value == 1 and r.posture_or_mode == Posture.STANDING)
            for t in sorted(manager_leaver_slots):
                if not rule_off("통제A 긴급 반차(I1 금지·입식 3연속)"):
                    model.add(expression(m, t, lambda r: r.displayed_assignment.label == "I1") == 0)
            if not manager_leaver_free and not rule_off("통제A 긴급 반차(I1 금지·입식 3연속)"):
                for t in range(12):
                    if not {t, t + 1, t + 2} & manager_leaver_slots:
                        continue
                    triple = model.new_bool_var(f"manager_leaver_standing_triple_{t}")
                    model.add(triple >= standing(t) + standing(t + 1) + standing(t + 2) - 2)
                    for j in (t - 1, t + 3):
                        if 0 <= j < 14:
                            model.add(triple + work(j) <= 1)     # 4연속 근무 안의 입식 3연속 금지
            manager_leaver_rests = sum(1 - work(t) for t in manager_leaver_slots)
        def day_fatigue(pid):
            return sum(int(r.fatigue_value) * v for t in range(14) for r, v in zip(opts[pid, t], variables[pid, t]))
        if (rules_v220 and manager_is_proxy and not proxy_handover and full_general_ids
                and not rule_off("준호 피로도(반차·승계)")):
            # [하드, 2026-10-20 사용자 확정] 미리 정한 A 결근(하루 종일 준호 대행)도 긴급 승계와 같이
            # 준호 하루 피로도 = 온전 출근 일반근무자 중 최저(동점 허용). 결원 0·1·2명 공통.
            proxy_low = model.new_int_var(0, 60, "full_proxy_low_general_fatigue")
            model.add_min_equality(proxy_low, [day_fatigue(p) for p in full_general_ids])
            model.add(day_fatigue(policy.manager_id) <= proxy_low)
        if (rules_v220 and policy.manager_id == "A" and not manager_is_proxy and manager_vacancy_policy
                and full_general_ids and not rule_off("관리자 하대 금지(결원 2명)")):
            # [하드, 2026-10-20 사용자 확정] 결원 2명 날 관리자 우대는 없어도 하대는 없다:
            # 통제A 하루 피로도 ≤ 온전 출근 일반근무자 최고.
            manager_top = model.new_int_var(0, 60, "vacancy_manager_top_general_fatigue")
            model.add_max_equality(manager_top, [day_fatigue(p) for p in full_general_ids])
            model.add(day_fatigue("A") <= manager_top)
        if proxy_handover and full_general_ids and not rule_off("준호 피로도(반차·승계)"):
            # [하드, 2026-10-18 사용자 확정] 통제A 반차(전반부·후반부·긴급 이탈 승계 모두)면 준호 하루 피로도는
            # 온전 출근 일반근무자 최고 피로도보다 낮게 (동점 최고도 금지).
            top_general = model.new_int_var(0, 60, "proxy_top_general_fatigue")
            model.add_max_equality(top_general, [sum(int(r.fatigue_value) * v for t in range(14)
                                                     for r, v in zip(opts[p, t], variables[p, t]))
                                                 for p in full_general_ids])
            if locked_assignments is not None:
                # 긴급 이탈 승계(10/18 사용자 확정): 준호 하루 피로도는 일반근무자 중 최저 (동점 최저 허용)
                low_general = model.new_int_var(0, 60, "proxy_low_general_fatigue")
                model.add_min_equality(low_general, [sum(int(r.fatigue_value) * v for t in range(14)
                                                         for r, v in zip(opts[p, t], variables[p, t]))
                                                     for p in full_general_ids])
                model.add(proxy_day_total("fatigue_value") <= low_general)
            else:
                model.add(proxy_day_total("fatigue_value") <= top_general - 1)
        if planned_handover and not rule_off("준호 자기 줄 순찰 금지"):
            # [하드, 2026-10-18 사용자 확정] 관리자 승계: 준호 순찰도 통제A와 같이 관리자 자리의 21시 상층 1회뿐
            # → 자기 줄(일반근무 시간)에서는 순찰하지 않는다 (예: 전반부 대행 뒤 01시 상층 순찰 + 휴게 2시간 강제 없음).
            # 결원 1명 날은 14-2 예외(proxy_patrol_exception)로 다른 일반근무자 1명이 2회.
            for t in leave.proxy_own_slots:
                model.add(expression(HANDOVER_PROXY, t, lambda r: r.actual_post_or_work_type.kind == K.PATROL) == 0)

        # 혼합 이력: 다음 출근 2회 보호 및 제외 경험이 적은 사람 우선.
        exclusion_cost = []
        for p in policy.general_ids:
            name = next(e.name for e in context.employees if e.employee_id == p)[-2:]
            events = [e for e in patrol_events if e['name'] == name]
            if not patrol_events:
                for r in sorted(patrol_actuals,key=lambda r:r.context.shift_start_date):
                    if r.context.shift_start_date >= context.shift_start_date:continue
                    if not any(a.employee_id==p and a.present for a in r.context.attendance):continue
                    patrol=any(x.employee_id==p and x.actual_post_or_work_type.kind==K.PATROL for x in r.assignments)
                    events.append({'excluded':sum(a.present for a in r.context.attendance)==7 and not patrol})
            count = sum(expression(p,t,lambda r:r.actual_post_or_work_type.kind == K.PATROL) for t in range(14))
            if any(e['excluded'] for e in events[-2:]):model.add(count >= 1)
            excluded = model.new_bool_var('patrol_excluded_'+p)
            model.add(count==0).only_enforce_if(excluded)
            model.add(count>=1).only_enforce_if(excluded.Not())
            exclusion_cost.append(sum(e['excluded'] for e in events)*excluded)

        # 하층 순찰 3회 연속 금지. 출근했으나 하층을 안 한 날은 연속 종료.
        # 2026-10-20 사용자 확정: 야간 + 공휴일 주간 순찰을 같은 그룹으로 센다(순찰 이벤트에 층이 있으면).
        zoned_events = bool(patrol_events) and all('zones' in e for e in patrol_events)
        for p in people:
            name = next(e.name for e in context.employees if e.employee_id == p)[-2:]
            mine = [e for e in patrol_events if e['name'] == name] if zoned_events else []
            if mine:
                lower_streak = len(mine) >= 2 and all('lower' in e['zones'] for e in mine[-2:])
            else:
                recent = [r for r in sorted(patrol_actuals, key=lambda r:r.context.shift_start_date)
                          if r.context.shift_start_date < context.shift_start_date
                          and any(a.employee_id == p and a.present for a in r.context.attendance)][-2:]
                lower_streak = len(recent) == 2 and all(any(x.employee_id == p and x.actual_post_or_work_type.kind == K.PATROL
                        and x.actual_post_or_work_type.label == 'lower' for x in r.assignments) for r in recent)
            if lower_streak:
                locked_lower = {(x.employee_id, x.slot.index) for x in locked_assignments or ()
                                if x.actual_post_or_work_type.kind == K.PATROL and x.actual_post_or_work_type.label == 'lower'}
                for t in range(14):
                    if (p,t) not in locked_lower:
                        model.add(expression(p,t,lambda r:r.actual_post_or_work_type.kind == K.PATROL
                                             and r.actual_post_or_work_type.label == 'lower') == 0)

        # v2.15 §21-7: assignments already performed or in progress are facts,
        # not preferences.  Pin the exact recorded option so every downstream
        # whole-shift constraint also crosses the LOCK/reoptimization boundary.
        if locked_assignments:
            seen = set()
            for old in locked_assignments:
                key = (old.employee_id, old.slot.index)
                if key in seen or key not in variables:
                    raise ValueError(f"Invalid locked assignment: {key}")
                seen.add(key)
                matches = [v for r, v in zip(opts[key], variables[key]) if r == old]
                if len(matches) != 1:
                    raise ValueError(f"Locked assignment is unavailable in the new context: {key}")
                model.add(matches[0] == 1)

        # H-17 [하드, 2026-10-05 사용자 확정]: 누구든 같은 포스트(표시 기준) 한 회차 최대 3번.
        # G2(1)·G2(2)는 G2로 센다. LOCK 과거가 이미 넘었으면 과거는 그대로, 미래 추가 배정만 막는다.
        weekday_start = context.night_type.value in ("N1", "N2")
        if post_cap:
            def post_family(r):
                if r.displayed_assignment.kind != K.POST:
                    return None
                # N1/N2 18시 관리자 L3는 표기만(실제 보안실 대기, 6-1) → 세지 않음 (2026-10-05 사용자 확정)
                if weekday_start and r.slot.index == 0 and r.employee_id == policy.manager_id:
                    return None
                return r.displayed_assignment.label.split("(")[0]
            locked_count = {}
            for old in locked_assignments or ():
                family = post_family(old)
                if family:
                    locked_count[old.employee_id, family] = locked_count.get((old.employee_id, family), 0) + 1
            for p in people:
                families = {post_family(r) for t in range(14) for r in opts[p, t]} - {None}
                for family in families:
                    count = sum(expression(p, t, lambda r, family=family: post_family(r) == family) for t in range(14))
                    model.add(count <= max(3, locked_count.get((p, family), 0)))
        # H-18 [하드, 2026-10-05 사용자 확정]: 하루 전체 근무하는 일반근무자끼리 실근무 차이 최대 1시간.
        # 0-2-1(FM·유도리 두 기준 해)보다 앞선다 — 하드라 두 기준 단계에도 그대로 걸린다. 실제 모드 표 기준.
        if rules_v220 and len(full_general_ids) >= 2:
            works = {p: sum(int(r.actual_work_time_value) * v for t in range(14)
                            for r, v in zip(opts[p, t], variables[p, t])) for p in full_general_ids}
            for p in full_general_ids:
                for q in full_general_ids:
                    if p != q:
                        model.add(works[p] - works[q] <= 1)
        # 6-2-1 [하드, 2026-10-05 사용자 확정]: 주말·공휴일 시작(N3/N4) 통제A 18시는 휴게 고정.
        # 관리자대행에게는 적용하지 않는다. LOCK된 18시는 기록 그대로 둔다.
        if (rules_v220 and not weekday_start and policy.manager_id == "A" and not manager_is_proxy
                and not any(old.employee_id == "A" and old.slot.index == 0 for old in locked_assignments or ())):
            model.add(expression("A", 0, lambda r: r.displayed_assignment.kind == K.REST
                                 and r.actual_post_or_work_type.kind == K.REST) == 1)
        # 8-10 [하드, 2026-10-05 사용자 확정]: 통제A는 04시 보안실 대기로 넣지 않고(쉬면 '휴게'),
        # 차단봉 철수에 참여하지 않는다. 관리자대행 제외, LOCK된 04시는 기록 그대로.
        if (rules_v220 and policy.manager_id == "A" and not manager_is_proxy and not rule_off("8-10 통제A 04시")
                and not any(old.employee_id == "A" and old.slot.index == 10 for old in locked_assignments or ())):
            # 룰북 8-6·15-0: 통제A는 04시 I1에도 배정하지 않는다(2026-10-13 누락 보완). 옛 차단봉 규칙 날짜는
            # 유도리로 다시 계산하면 04시 I1이 철수 담당이 되어, 빠져 있으면 FM·유도리 동시 판정이 어긋났다.
            model.add(expression("A", 10, lambda r: r.displayed_assignment.label in ("보안실 대기", "I1")
                                 or r.barrier_remove_flag) == 0)
        # 8-11 [하드, 2026-10-05 사용자 확정]: 당일 관리자(통제A·관리자대행)는 18시·07시 실근무 없음.
        # 예외: 8-3-1(N1/N3 07시 가용 일반근무자 4명)이면 07시 근무 허용. LOCK된 칸은 기록 그대로.
        if rules_v220:
            locked_keys = {(old.employee_id, old.slot.index) for old in locked_assignments or ()}
            from datetime import timedelta
            from .calendar_info import holiday_name, is_off_day
            # 5-3-1: 다음날 평일 남문 연속 배정 금지 (2026-10-18 사용자 확정: 결원 2명 구간도 적용, 예외 삭제).
            if not is_off_day(context.shift_start_date + timedelta(days=1)) and not rule_off("5-3-1 남문 2시간 연속 금지"):
                for p in people:
                    for t in range(13):
                        if (p,t) in locked_keys and (p,t+1) in locked_keys:
                            continue
                        model.add(sum(expression(p,j,lambda r:r.displayed_assignment.label in
                            ('G2','G3','G2(1)')) for j in (t,t+1)) <= 1)
            # 8-13: 다음날 공휴일(토·일 포함)이면 그날 관리자(통제A 또는 준호 대행, 2026-10-13 대행 포함) 06시 G1 금지.
            # 중도 인계 뒤에는 관리자 줄을 준호가 이어서 서므로 같은 줄(policy.manager_id)에 건다. LOCK은 보존.
            if (is_off_day(context.shift_start_date + timedelta(days=1)) and policy.manager_id
                    and (policy.manager_id, 12) not in locked_keys):
                model.add(expression(policy.manager_id, 12, lambda r: r.displayed_assignment.label == "G1"
                                     or r.actual_post_or_work_type.label == "G1") == 0)
            if (policy.profile_general_count == 4 or context.flexible_from_slot is not None) and holiday_name(context.shift_start_date + timedelta(days=1)):
                for slot in (12, 13):
                    if ((policy.manager_id, slot) not in locked_keys
                            and (context.flexible_from_slot is None or slot >= context.flexible_from_slot)):
                        model.add(expression(policy.manager_id, slot, lambda r:
                            r.displayed_assignment.label in ("휴게", "보안실 대기")
                            and r.actual_work_time_value == 0) == 1)
            for slot in (0, 13):
                if (slot == 13 and manager_works_07) or (policy.manager_id, slot) in locked_keys:
                    continue
                model.add(expression(policy.manager_id, slot, lambda r: r.actual_work_time_value == 0) == 1)

        # 순찰 후 실휴게 3번째 칸이 비포스트면 반드시 대기 표기.
        patrol_third_standby = {t:[] for t in range(14)}
        if rules_v220 and not rule_off("12-3 순찰 뒤 3번째 칸 대기 표기"):
            locked_display={(r.employee_id,r.slot.index) for r in locked_assignments or ()}
            for p in people:
                for t in range(11):
                    patrol=expression(p,t,lambda r:r.actual_post_or_work_type.kind==K.PATROL)
                    first=expression(p,t+1,lambda r:r.actual_rest_time_value==1)
                    second=expression(p,t+2,lambda r:r.actual_rest_time_value==1)
                    for j in (t+1,t+2):
                        if (p,j) not in locked_display:
                            model.add(patrol+first+second+expression(p,j,lambda r:
                                r.displayed_assignment.label=='보안실 대기')<=3)
                    off=expression(p,t+3,lambda r:r.displayed_assignment.label in ('휴게','보안실 대기')
                                   and r.actual_rest_time_value==1)
                    flag=model.new_bool_var(f'patrol_third_standby_{p}_{t}')
                    model.add(patrol+first+second+off==4).only_enforce_if(flag)
                    model.add(patrol+first+second+off<=3).only_enforce_if(flag.Not())
                    patrol_third_standby[t+3].append(flag)
                    if (p,t+3) not in locked_display:
                        model.add(expression(p,t+3,lambda r:r.displayed_assignment.label=='보안실 대기')>=flag)

        # 12-4: 비포스트로 3시간 연속 쉬면 붙어 있는 휴게 2시간을 확보한다.
        if rules_v220 and not rule_off("12-4 연속 휴게 표기"):
            locked_three={(r.employee_id,r.slot.index) for r in locked_assignments or ()}
            for p in people:
                for t in range(12):
                    if all((p,j) in locked_three for j in range(t,t+3)):continue
                    off=[expression(p,j,lambda r:r.displayed_assignment.label in ('휴게','보안실 대기')
                                    and r.actual_rest_time_value==1) for j in range(t,t+3)]
                    rest=[expression(p,j,lambda r:r.displayed_assignment.label=='휴게') for j in range(t,t+3)]
                    left=model.new_bool_var(f'plain_rest_left_{p}_{t}')
                    right=model.new_bool_var(f'plain_rest_right_{p}_{t}')
                    model.add(left<=rest[0]);model.add(left<=rest[1])
                    model.add(right<=rest[1]);model.add(right<=rest[2])
                    model.add(left+right>=sum(off)-2)

        # 12-5: 결원 2명 구간 외 18~05시 대기 최소 1명. 결원 0명 시간은 필수(하드),
        # 결원 1명 시간은 가능하면 지킬 규칙(2026-10-18 사용자 확정 — 순찰 뒤 휴게·연속 휴게 등과 겹쳐 해가 없던 문제):
        # 대기자 없는 시간 수를 소프트 목표 맨 앞에서 최소화.
        required_standby_slots=set()
        vacancy1_standby_missing=[]
        if rules_v220:
            already_locked={(r.employee_id,r.slot.index) for r in locked_assignments or ()}
            for t in range(12):
                vacancies=7-sum(a.present and a.is_available(t) for a in context.attendance)
                if vacancies==2:continue
                required_standby_slots.add(t)
                if all((p,t) in already_locked for p in people):continue
                standby_here=sum(expression(p,t,lambda r:r.displayed_assignment.label=='보안실 대기')
                                 for p in people)
                if vacancies==1:
                    missing=model.new_bool_var(f'vacancy1_missing_standby_{t}')
                    model.add(standby_here+missing>=1)
                    vacancy1_standby_missing.append(missing)
                elif not rule_off("12-5 매시간 대기자"):
                    model.add(standby_here>=1)

        # 12-6: 통제A 제외, 출근자 전체 대기 횟수 차이 최대1(미리 정한 반차 포함).
        # 긴급 반차·이탈자는 제외 (2026-10-18 사용자 확정: 빠지기 전 배려 없이 근무)
        if rules_v220 and not rule_off("12-6 대기 횟수 차이"):
            emergency_out = leave.emergency_out_ids
            standby_people=[p for p in people if p!='A' and p not in emergency_out]
            standby_totals={p:sum(expression(p,t,lambda r:r.displayed_assignment.label=='보안실 대기')
                                  for t in range(14)) for p in standby_people}
            for index,p in enumerate(standby_people):
                for q in standby_people[index+1:]:
                    model.add(standby_totals[p]-standby_totals[q]<=1)
                    model.add(standby_totals[q]-standby_totals[p]<=1)

        # 8-14: 실제 통제A 출근 시 I1 최소1회, 04시 금지는 그대로.
        # 통제A 긴급 반차·이탈 날은 면제 (2026-10-18 사용자 확정: 빠지기 전 I1 금지와 충돌)
        if rules_v220 and 'A' in people and not manager_leaves and not rule_off("8-14 통제A I1 최소 1회"):
            a_slots=[t for t in range(manager_a_start_slot,min(14,manager_a_end_slot))
                     if next(a for a in context.attendance if a.employee_id=='A').is_available(t)]
            locked_a={(r.employee_id,r.slot.index) for r in locked_assignments or ()}
            if a_slots and not all(('A',t) in locked_a for t in a_slots):
                model.add(sum(expression('A',t,lambda r:r.displayed_assignment.label=='I1') for t in a_slots)>=1)

        # 8-15: 실제 통제A 대기 표기는 야간 전체 최대2회.
        if rules_v220 and 'A' in people and not rule_off("8-15 통제A 대기 최대 2회"):
            a_end=min(14,manager_a_end_slot)
            completed_standby=sum(r.employee_id=='A' and manager_a_start_slot<=r.slot.index<a_end
                and r.displayed_assignment.label=='보안실 대기' for r in locked_assignments or ())
            model.add(sum(expression('A',t,lambda r:r.displayed_assignment.label=='보안실 대기')
                          for t in range(manager_a_start_slot,a_end))<=max(2,completed_standby))

        # H-19: 05~07시 실휴게 3연속 금지. 통제A·준호 관리자 대행은 예외.
        if rules_v220 and not rule_off("H-19 05~07시 휴게 3연속 금지"):
            locked_keys = {(old.employee_id, old.slot.index) for old in locked_assignments or ()}
            for pid in people:
                if pid == "A" or (pid == "6" and (policy.manager_id == "6" or manager_a_end_slot <= 13)):
                    continue
                cells = [("A" if pid == "6" and t >= manager_a_end_slot else pid, t)
                         for t in (11, 12, 13)]
                if all(cell in locked_keys for cell in cells):
                    continue
                model.add(sum(expression(person, t, lambda row: row.actual_rest_time_value == 1)
                              for person, t in cells) <= 2)

        # 관리자 교대 경계(2026-10-20): 자리 형태에서는 준호 한 사람이 교대 전 자기 줄(6) + 교대 후 관리자 자리(A)
        # (전반부 반차는 반대)로 나뉘어 Solver가 연속근무를 몰랐다 → 표를 만든 뒤 service.handover_boundary_issues로
        # 걸러 최대 3번 다시 풀었고, 시간이 모자라면 가끔 모두 걸려 실패했다. 같은 검사를 이어 붙인 줄에 하드로 건다.
        # 규칙 의미는 그대로(5시간 연속근무·4시간 연속 중 좌식 없음·교대 걸친 입식 3연속·교대 직전 순찰 뒤 휴게·입식→순찰→입식).
        handover_k = manager_a_start_slot if manager_a_start_slot > 0 else (manager_a_end_slot if manager_a_end_slot < 14 else None)
        handover_standing_misses = []                   # 교대 직전 두 칸이 LOCK된 입식일 때만: 입식 3연속은 가능하면 피함

        def handover_boundary(k, reverse):
            locked_rows = {(old.employee_id, old.slot.index): old for old in locked_assignments or ()}
            cell = lambda t: (("A" if t < k else HANDOVER_PROXY) if reverse      # noqa: E731
                              else (HANDOVER_PROXY if t < k else "A"), t)
            work = lambda t: expression(*cell(t), lambda r: r.actual_work_time_value == 1)          # noqa: E731
            counted = lambda t: expression(*cell(t), lambda r: r.counts_for_continuous_work_restriction  # noqa: E731
                                           or r.actual_post_or_work_type.kind == K.PATROL)
            seated = lambda t: expression(*cell(t), lambda r: r.actual_work_time_value == 1           # noqa: E731
                                          and r.posture_or_mode == Posture.SEATED)
            standing = lambda t: expression(*cell(t), lambda r: r.actual_work_time_value == 1         # noqa: E731
                                            and r.posture_or_mode == Posture.STANDING)
            patrol = lambda t: expression(*cell(t), lambda r: r.actual_post_or_work_type.kind == K.PATROL)  # noqa: E731

            def hard(constraint):                       # LOCK·근무불가로 양쪽이 상수가 되면 파이썬 bool이 온다
                if isinstance(constraint, bool):
                    if not constraint:
                        model.add_bool_or([])           # 이미 LOCK된 과거가 위반 → 해 없음으로 드러냄
                else:
                    model.add(constraint)
            for s in range(max(0, k - 4), min(k, 10) + 1):
                if s + 4 < 14:
                    hard(sum(counted(t) for t in range(s, s + 5)) <= 4)
            for s in range(max(0, k - 3), min(k, 11) + 1):
                if s + 3 < 14:
                    hard(sum(counted(t) for t in range(s, s + 4)) <= 3 + sum(seated(t) for t in range(s, s + 4)))
            for s in range(max(0, k - 2), min(k, 12) + 1):
                if s + 2 < 14 and s < k <= s + 2:
                    # 2026-10-20 사용자 확정: 교대 직전 두 칸이 이미 LOCK된 입식이면(지난 과거라 바꿀 수 없음)
                    # 교대 시점 입식 3연속을 허용 — 하드 대신 가능하면 지킬 규칙(소프트 맨 앞).
                    before = [cell(t) for t in (k - 2, k - 1) if t >= 0]
                    if (s == k - 2 and len(before) == 2 and all(
                            c in locked_rows and locked_rows[c].actual_work_time_value == 1
                            and locked_rows[c].posture_or_mode == Posture.STANDING for c in before)):
                        miss = model.new_bool_var("handover_standing_miss")
                        model.add(sum(standing(t) for t in range(s, s + 3)) <= 2 + miss)
                        handover_standing_misses.append(miss)
                        continue
                    hard(sum(standing(t) for t in range(s, s + 3)) <= 2)
            for t in (k - 2, k - 1):
                if t >= 0:
                    window = [j for j in (t + 1, t + 2) if j < 14]
                    if window:
                        hard(patrol(t) <= sum(1 - work(j) for j in window))
                    if t >= 1 and t + 1 < 14:
                        hard(standing(t - 1) + patrol(t) + work(t + 1) - seated(t + 1) <= 2)

        if (rules_v220 and handover_k is not None and HANDOVER_PROXY in people and "A" in people
                and not rule_off("교대 경계(준호 연속근무)")):
            handover_boundary(handover_k, manager_a_start_slot > 0)

        # H-20: 막타임 2시간(06·07시) 연속 휴게 금지 — 일반근무자 신분만, 결원 무관, FM 표기 기준(휴게·업무 없는 대기).
        # 통제A·준호 관리자 대행은 관리자 역할 예외 (H-19와 같은 범위, 2026-10-20 사용자 확정). 두 칸 모두 LOCK이면 보존.
        if rules_v220 and not rule_off("H-20 06·07시 휴게 2연속 금지"):
            locked_keys = {(old.employee_id, old.slot.index) for old in locked_assignments or ()}
            for pid in people:
                if pid == "A" or (pid == "6" and (policy.manager_id == "6" or manager_a_end_slot <= 13)):
                    continue
                if all((pid, t) in locked_keys for t in (12, 13)):
                    continue
                model.add(sum(expression(pid, t, lambda row: row.displayed_assignment.label in ("휴게", "보안실 대기")
                                         and row.actual_rest_time_value == 1) for t in (12, 13)) <= 1)

        # 16-big: 막타임(07시) 실휴게 수혜자는 같은 날 대폭 휴게(23시~07시 전 3연속 실휴게, models.BIG_REST_SLOTS) 동시 수혜 금지(하드).
        # 통제A·준호 관리자 대행은 예외. 4칸 모두 LOCK이면 보존.
        if rules_v220 and not rule_off("16-big 막타임·대폭 휴게 동시 금지"):
            locked_keys = {(old.employee_id, old.slot.index) for old in locked_assignments or ()}
            for pid in people:
                if pid == "A" or (pid == "6" and (policy.manager_id == "6" or manager_a_end_slot <= 13)):
                    continue
                for s in BIG_REST_STARTS:
                    window = (s, s + 1, s + 2, 13)
                    if all((pid, t) in locked_keys for t in window):
                        continue
                    model.add(sum(expression(pid, t, lambda row: row.actual_rest_time_value == 1) for t in window) <= 3)

        for p, t in forced_rest_cells:
            if (p, t) in variables:
                model.add(expression(p, t, lambda r: r.actual_work_time_value == 0) == 1)
        locked_install_keys = {(old.employee_id, old.slot.index) for old in locked_assignments or ()}
        for p in (() if rule_off("15-3 연속 회차 설치 금지") else forbid_install_ids):
            if p in people and (p, 2) not in locked_install_keys:   # 15-3: 직전 회차 설치자(G2·I1 포함)는 이번 설치 금지 (2026-10-19)
                model.add(expression(p, 2, lambda r: r.barrier_install_flag) == 0)
        for p in forbid_last_rest_ids:
            if p in policy.general_ids and (p,13) not in {(r.employee_id,r.slot.index) for r in locked_assignments or ()}:
                model.add(expression(p, 13, lambda r:r.actual_rest_time_value == 1) == 0)
        if rules_v212 and absence_count == 0 and not manager_is_proxy:
            for p in forbid_patrol_exclusion_ids:
                if p in policy.general_ids:
                    model.add(sum(expression(p, t, lambda r:r.actual_post_or_work_type.kind == K.PATROL) for t in range(14)) == 1)

        if exclude_assignments is not None:
            # Backwards compatible with the old single flat payload while the
            # UI can now exclude every previously generated schedule at once.
            excluded_schedules = ((exclude_assignments,)
                                  if exclude_assignments and isinstance(exclude_assignments[0], dict)
                                  else exclude_assignments)
            expected = {(p, t) for p in people for t in range(14)}

            def old_matches(record, old):
                displayed = old["displayed_assignment"]
                actual = old.get("actual_post_or_work_type")
                posture = old.get("posture_or_mode")
                return (
                    record.displayed_assignment.label == displayed["label"]
                    and ("kind" not in displayed
                         or record.displayed_assignment.kind.value == displayed["kind"])
                    and (actual is None or (
                        record.actual_post_or_work_type.label == actual["label"]
                        and record.actual_post_or_work_type.kind.value == actual["kind"]))
                    and ("posture_or_mode" not in old
                         or (record.posture_or_mode.value if record.posture_or_mode else None) == posture)
                    and ("actual_work_time_value" not in old
                         or record.actual_work_time_value == old["actual_work_time_value"])
                    and ("actual_rest_time_value" not in old
                         or record.actual_rest_time_value == old["actual_rest_time_value"])
                    and ("fatigue_value" not in old
                         or record.fatigue_value == old["fatigue_value"])
                    and ("counts_for_continuous_work_restriction" not in old
                         or record.counts_for_continuous_work_restriction
                         == old["counts_for_continuous_work_restriction"])
                    and record.barrier_install_flag == old["barrier_install_flag"]
                    and record.barrier_remove_flag == old["barrier_remove_flag"]
                )

            for excluded_index, excluded in enumerate(excluded_schedules):
                previous = {(r["employee_id"], r["slot"]["index"]): r for r in excluded}
                if set(previous) != expected or len(excluded) != len(expected):
                    raise ValueError(
                        "Excluded schedule must contain exactly one assignment per present employee and slot")

                general_ids = tuple(policy.general_ids)
                if rules_v219:
                    # Name-invariant difference: however the previous
                    # general-worker rows are matched to the new people, at
                    # least three people must each differ in three or more
                    # hourly assignments.  Shuffling rows between names plus a
                    # single swap is not a different schedule.
                    seen_row_orders = set()
                    for perm_index, old_order in enumerate(permutations(general_ids)):
                        row_order = tuple(
                            tuple((previous[old_id, t]["displayed_assignment"]["label"],
                                   previous[old_id, t]["barrier_install_flag"],
                                   previous[old_id, t]["barrier_remove_flag"])
                                  for t in range(14))
                            for old_id in old_order
                        )
                        if row_order in seen_row_orders:
                            continue
                        seen_row_orders.add(row_order)
                        old_for_new = dict(zip(general_ids, old_order))
                        old_for_new[policy.manager_id] = policy.manager_id
                        changed_people = []
                        for p in people:
                            same = []
                            for t in range(14):
                                old = previous[old_for_new[p], t]
                                same.extend(v for r, v in zip(opts[p, t], variables[p, t])
                                            if old_matches(r, old))
                            changed = model.new_bool_var(
                                f"invariant_change_{excluded_index}_{perm_index}_{p}")
                            model.add(14 - sum(same) >= 3).only_enforce_if(changed)
                            model.add(14 - sum(same) <= 2).only_enforce_if(changed.Not())
                            changed_people.append(changed)
                        model.add(sum(changed_people) >= 3)
                    continue

                # A candidate is materially different only when at least three
                # people each have at least three changed hourly assignments.
                # Apply this independently against every previously generated
                # schedule, not merely the most recently selected one.
                materially_changed_people = []
                for p in people:
                    matching_slots = []
                    for t in range(14):
                        old = previous[p, t]
                        matching_slots.extend(
                            v for r, v in zip(opts[p, t], variables[p, t])
                            if old_matches(r, old)
                        )
                    changed_slots = 14 - sum(matching_slots)
                    changed_three = model.new_bool_var(
                        f"material_change_{excluded_index}_{p}"
                    )
                    model.add(changed_slots >= 3).only_enforce_if(changed_three)
                    model.add(changed_slots <= 2).only_enforce_if(changed_three.Not())
                    materially_changed_people.append(changed_three)
                model.add(sum(materially_changed_people) >= 3)

                # Reject both the exact employee mapping and every mere
                # permutation of complete general-worker rows. Changing only
                # visible numbers or moving the same row patterns to different
                # names is not a genuinely different schedule.
                seen_row_orders = set()
                for old_order in permutations(general_ids):
                    row_order = tuple(
                        tuple((previous[old_id, t]["displayed_assignment"]["label"],
                               previous[old_id, t]["barrier_install_flag"],
                               previous[old_id, t]["barrier_remove_flag"])
                              for t in range(14))
                        for old_id in old_order
                    )
                    if row_order in seen_row_orders:
                        continue
                    seen_row_orders.add(row_order)
                    old_for_new = dict(zip(general_ids, old_order))
                    old_for_new[policy.manager_id] = policy.manager_id
                    exact_matches = []
                    for p in people:
                        old_p = old_for_new[p]
                        for t in range(14):
                            old = previous[old_p, t]
                            exact_matches.extend(
                                v for r, v in zip(opts[p, t], variables[p, t])
                                if old_matches(r, old)
                            )
                    model.add(sum(exact_matches) <= len(expected) - 1)

        if rules_v22:
            if context.night_type.value in ("N1", "N2"):
                for p in people:
                    evening_gate = sum(expression(p, t, lambda r: r.displayed_assignment.label in ("G2", "G3")) for t in range(3))
                    model.add(evening_gate <= (0 if p == policy.manager_id else 1))
            work_totals = {p: sum(int(r.actual_work_time_value) * v for t in range(14)
                                  for r, v in zip(opts[p, t], variables[p, t])) for p in people}
            if not relaxed(2) and not manager_vacancy_policy and not rule_off("관리자 실근무·피로도 격차(H-15·8-4-2)"):
                for p in full_general_ids if rules_v215 else policy.general_ids:
                    model.add(work_totals[p] - work_totals[policy.manager_id] <= 2)
                    model.add(work_totals[policy.manager_id] - work_totals[p] <= 2)
                    if late_proxy_manager_rules:         # 후반부 반차 준호 = 통제A와 같은 H-15
                        model.add(work_totals[p] - proxy_day_total("actual_work_time_value") <= 2)
                        model.add(proxy_day_total("actual_work_time_value") - work_totals[p] <= 2)
            if headcount in (5, 6) and profile_absence < 2 and switch_slot is None:
                fatigue_totals = {p: sum(int(r.fatigue_value) * v for t in range(14)
                                        for r, v in zip(opts[p, t], variables[p, t])) for p in people}
                if not relaxed(2) and not rule_off("관리자 실근무·피로도 격차(H-15·8-4-2)"):
                    for p in full_general_ids if rules_v215 else policy.general_ids:
                        if rules_v219 and not manager_is_proxy:
                            # v2.19 §8-4-2: with A on duty and at most one
                            # absence, A's total fatigue is not above any
                            # full-time general worker and at most 2 below.
                            model.add(fatigue_totals[policy.manager_id] <= fatigue_totals[p])
                            model.add(fatigue_totals[p] - fatigue_totals[policy.manager_id] <= (3 if rules_v220 else 2))
                            if late_proxy_manager_rules:     # 후반부 반차 준호 = 통제A와 같은 8-4-2
                                model.add(proxy_day_total("fatigue_value") <= fatigue_totals[p])
                                model.add(fatigue_totals[p] - proxy_day_total("fatigue_value") <= 3)
                        else:
                            model.add(fatigue_totals[policy.manager_id] >= fatigue_totals[p] - 4)
                            model.add(fatigue_totals[p] >= fatigue_totals[policy.manager_id] - 4)

        for req in policy.requirements:
            def matches(r):
                return r.displayed_assignment.kind == K.POST and r.displayed_assignment.label == req.displayed_post
            model.add(sum(expression(p, req.slot_index, matches) for p in people) == req.total_count)
            if req.general_count is not None:
                model.add(sum(expression(p, req.slot_index, matches) for p in policy.general_ids) == req.general_count)
            if req.fixed_employee_id:
                model.add(expression(req.fixed_employee_id, req.slot_index, matches) == 1)
        for patrol in policy.patrols:
            model.add(sum(expression(p, patrol.slot_index, lambda r: r.actual_post_or_work_type.label == patrol.area) for p in people) == 1)
        model.add(expression(policy.manager_id, 3, lambda r: r.actual_post_or_work_type.label == "upper") == 1)
        patrol_total = {p: sum(expression(p, t, lambda r: r.actual_post_or_work_type.kind == K.PATROL) for t in range(14)) for p in people}
        switch_double_patrols = []
        if switch_slot is not None:
            # v2.20 §14-3-1: after an emergency switch the remaining patrols
            # follow the vacancy-2 rule: at most two per person, one per half,
            # everyone available all night patrols at least once.
            for p in people:
                model.add(patrol_total[p] <= 2)
                for half in ((3, 4, 5), (7, 8, 9)):
                    model.add(sum(expression(p, t, lambda r: r.actual_post_or_work_type.kind == K.PATROL) for t in half) <= 1)
                if available_counts[p] == 14:
                    model.add(patrol_total[p] >= 1)
                if p != policy.manager_id:
                    double = model.new_bool_var(f"switch_double_{p}")
                    model.add(patrol_total[p] >= 2).only_enforce_if(double)
                    model.add(patrol_total[p] <= 1).only_enforce_if(double.Not())
                    switch_double_patrols.append(double)
        elif headcount == 6:
            model.add(sum(expression(policy.manager_id, t, lambda r: r.actual_post_or_work_type.kind == K.PATROL) for t in range(14)) == 1)
            if manager_is_proxy:
                for p in policy.general_ids:
                    model.add(sum(expression(p, t, lambda r: r.actual_post_or_work_type.kind == K.PATROL) for t in range(14)) == 1)
        if headcount >= 5 and not manager_is_proxy and switch_slot is None and not rule_off("순찰 배분(14-1·14-2)"):
            for p in policy.general_ids:
                patrol_count = sum(expression(p, t, lambda r: r.actual_post_or_work_type.kind == K.PATROL) for t in range(14))
                if proxy_patrol_exception:
                    if p == HANDOVER_PROXY:
                        model.add(patrol_count == 0)
                    else:
                        model.add(patrol_count >= 1)
                        model.add(patrol_count <= 2)
                        for half in ((3, 4, 5), (7, 8, 9)):
                            model.add(sum(expression(p, t, lambda r: r.actual_post_or_work_type.kind == K.PATROL) for t in half) <= 1)
                    continue
                model.add(patrol_count <= 1)
                if headcount == 5:
                    model.add(patrol_count == 1)
            if headcount == 5:
                model.add(sum(expression(policy.manager_id, t, lambda r: r.actual_post_or_work_type.kind == K.PATROL) for t in range(14)) == 1)
        if rules_v26 and (headcount == 4 or manager_is_proxy and headcount < 6) and switch_slot is None:
            for p in people:
                n = sum(expression(p, t, lambda r: r.actual_post_or_work_type.kind == K.PATROL) for t in range(14))
                model.add(n >= 1)
                model.add(n <= 2)
                for half in ((3,4,5), (7,8,9)):
                    model.add(sum(expression(p,t,lambda r:r.actual_post_or_work_type.kind == K.PATROL) for t in half) <= 1)
        model.add(expression(policy.manager_id, 11, lambda r: r.actual_work_time_value == 0 and r.actual_rest_time_value == 1) == 1)
        # §8-3: v2.15 makes N1/N3 manager 07 rest-like time a hard rule.
        if manager_works_07:
            model.add(expression(policy.manager_id, 13, lambda r: r.actual_work_time_value == 1 and r.displayed_assignment.label in ("L3", "I1")) == 1)
        elif rules_v215 and context.night_type.value in ("N1", "N3"):
            model.add(expression(policy.manager_id, 13, lambda r: r.actual_rest_time_value == 1) == 1)
        else:
            model.add(expression(policy.manager_id, 13, lambda r: r.actual_work_time_value == 0 or r.displayed_assignment.label in ("L3", "I1")) == 1)
        if target_probe and headcount >= 5 and not rules_v215:
            model.add(expression(policy.manager_id, 13, lambda r: r.actual_work_time_value == 0) == 1)
        if refinement:
            # User revision: one explicitly displayed standby; remaining off-duty = rest.
            for t in range(14):
                standby_count = sum(expression(p, t, lambda r: r.displayed_assignment.label == "보안실 대기") for p in people)
                if rules_v26:
                    if t in (2, 10):
                        model.add(standby_count >= 1)
                    if rules_v212 and t == 10:
                        model.add(standby_count == 1)
                    if rules_v212 and t == 2 and barrier_v2(context):
                        model.add(standby_count == 1)          # H-16 (2026-10-05~): 20시 대기 표기 1명, 나머지는 휴게
                    elif rules_v212 and t == 2:
                        available = len(people) - sum(req.total_count for req in policy.requirements if req.slot_index == t)
                        model.add(standby_count == min(2, available))
                elif vacancy_policy and headcount < 6 and t not in (2, 10):
                    model.add(standby_count <= 1)
                else:
                    model.add(standby_count == 1)
            # Six-worker A: at most two consecutive actual working hours in 00–05.
            if profile_absence == 0 and switch_slot is None and not relaxed(2):
                for t in range(6, 10):
                    model.add(sum(expression(policy.manager_id, j, lambda r: r.actual_work_time_value == 1) for j in range(t, t + 3)) <= 2)
            if target_probe:
                # Prefer I1 if working at 04; do not force an extra working hour.
                model.add(expression(policy.manager_id, 10, lambda r: r.actual_work_time_value == 0 or r.displayed_assignment.label == "I1") == 1)

        patrol_recovery_costs = []
        half_day_rest_misses = []
        leaver_rest_misses = []                       # 긴급 반차·이탈자 순찰 뒤 휴게 (최후순위 권장, 10/18)
        # 2026-10-18 사용자 확정: 긴급 재편성(LOCK 있음)일 때만 순찰 뒤 회복(H-11·H-11-2·H-12-1)을 가능하면 지킬 규칙으로
        # — 남은 인원으로 못 지키는 만큼만 어기고, 어긴 칸 수를 소프트 목표 맨 앞에서 최소화. 평소 생성은 하드 그대로.
        soft_recovery = rules_v220 and locked_assignments is not None
        recovery_misses = []

        def recovery_slack(name):
            if not soft_recovery:
                return 0
            miss = model.new_bool_var(f"recovery_miss_{name}")
            recovery_misses.append(miss)
            return miss
        # H-09-1 [하드, 2026-10-05]: 미리 정한 반차자는 나오는 시간 안에서 실제 휴게 합계 2시간 이상
        locked_rest = {}
        for r in locked_assignments or ():
            locked_rest[r.employee_id] = locked_rest.get(r.employee_id, 0) + int(r.actual_rest_time_value)
        for p in (() if rule_off("반차자 휴게 2시간(H-09-1)") else half_day):
            rest_total = sum(expression(p, t, lambda r: r.actual_rest_time_value == 1) for t in range(14))
            if p in leaver_ids:
                # 긴급 반차·이탈자: 실휴게 2시간 이상, 다만 남은(LOCK 아닌) 칸으로 채울 수 있는 만큼만 (10/18)
                left = sum(1 for q, _ in emergency_leaver_cells if q == p)
                model.add(rest_total >= min(2, locked_rest.get(p, 0) + left))
            else:
                # 미리 정한 반차자: 실휴게 정확히 2시간 (2026-10-18 사용자 확정, 이미 LOCK된 휴게가 더 많으면 그대로)
                model.add(rest_total >= 2)
                model.add(rest_total <= max(2, locked_rest.get(p, 0)))
        if manager_leaver_slots and not rule_off("반차자 휴게 2시간(H-09-1)"):   # 긴급 반차 통제A: 나오는 시간 중 실휴게 2시간 이상(10/18)
            model.add(sum(expression(policy.manager_id, t, lambda r: r.actual_rest_time_value == 1)
                          for t in range(max(manager_leaver_slots) + 1))
                      >= min(2, locked_rest.get(policy.manager_id, 0) + len(manager_leaver_slots)))
        for p in people:
            if any(attendance_by_id[p].is_available(t) for t in (0, 1, 2)):
                model.add(sum(expression(p, t, lambda r: r.counts_as_meal_opportunity) for t in (0, 1, 2)) >= 1)
            for t in range(13):
                for a, ra in enumerate(opts[p, t]):
                    for b, rb in enumerate(opts[p, t + 1]):
                        forbidden = forbidden_same_post_pair(ra, rb, allow_manager_weekend_first_pair=(context.night_type.value in ("N3", "N4") and p == policy.manager_id))
                        protects_g1 = ra.displayed_assignment.label == "G1" or rb.displayed_assignment.label == "G1"
                        if forbidden and (not relaxed(2) or protects_g1):
                            model.add(variables[p, t][a] + variables[p, t + 1][b] <= 1)
            if not relaxed(2):
                for t in (range(12) if rules_v26 else range(5, 10)):
                    keys = {_actual_key(r) for j in range(t, t + 3) for r in opts[p, j]} - {None}
                    for key in keys:
                        model.add(sum(expression(p, j, lambda r: _actual_key(r) == key) for j in range(t, t + 3)) <= 2)
            standing = lambda r: r.actual_work_time_value == 1 and r.posture_or_mode == Posture.STANDING
            for t in range(12):
                count = sum(expression(p, j, standing) for j in range(t, t + 3))
                if t == 11:
                    gates = sum(expression(p, j, lambda r: r.displayed_assignment.label in ("G2", "G3")) for j in range(11, 14))
                    model.add(count <= 2 + gates)
                elif not rules_v27:
                    model.add(count <= 2)
            if rules_v26:
                counted = lambda r: r.counts_for_continuous_work_restriction or r.actual_post_or_work_type.kind == K.PATROL
                def leaver_free(start, n):         # 휴게 2시간 이상 받은 긴급 반차 통제A 칸은 연속근무 규칙 제외
                    return p == policy.manager_id and manager_leaver_free and bool(set(range(start, start + n)) & manager_leaver_slots)
                if not relaxed(5) and not rule_off("H-08 연속근무"):
                    for start in range(10):
                        if leaver_free(start, 5):
                            continue
                        model.add(sum(expression(p,j,counted) for j in range(start,start+5)) <= 4)
                if not relaxed(4) and not rule_off("H-08 연속근무"):
                    for start in range(11):
                        if leaver_free(start, 4):
                            continue
                        model.add(sum(expression(p,j,counted) for j in range(start,start+4)) <=
                                  3 + sum(expression(p,j,lambda r:r.actual_work_time_value == 1 and r.posture_or_mode == Posture.SEATED) for j in range(start,start+4)))
            else:
                model.add(sum(expression(p, t, lambda r: r.counts_for_continuous_work_restriction) for t in range(10, 14)) <= 3)
            protected_flags = []
            for patrol in policy.patrols:
                t = patrol.slot_index
                is_patrol = expression(p, t, lambda r: r.actual_post_or_work_type.kind == K.PATROL)
                relaxed_patrol_rest = profile_absence == 2 or (switch_slot is not None and t + 2 >= switch_slot)
                if relaxed(3) or rule_off("H-11 순찰 뒤 휴게"):
                    continue
                if p in half_day or (p == policy.manager_id and manager_leaver_slots):
                    # 긴급 반차 통제A도 반차자처럼(2026-10-18 사용자 확정: 순찰 뒤 휴게 배려는 최후순위)
                    # H-09-1 (2026-10-05): 미리 정한 반차자는 순찰 후 휴게가 하드 아님. 입식→순찰→입식만 금지하고,
                    # 순찰 직후 휴게는 밸런스 다음 권장(half_day_patrol_rest).
                    stood_before = expression(p, t - 1, lambda r: r.actual_work_time_value == 1 and r.posture_or_mode == Posture.STANDING)
                    bad_after = expression(p, t + 1, lambda r: r.actual_work_time_value == 1 and r.posture_or_mode != Posture.SEATED)
                    model.add(stood_before + is_patrol + bad_after <= 2)
                    for j in (t + 1, t + 2):
                        miss = model.new_bool_var(f"half_day_patrol_rest_miss_{p}_{t}_{j}")
                        model.add(miss >= is_patrol - expression(p, j, lambda r: r.actual_rest_time_value == 1))
                        (leaver_rest_misses if p in leaver_ids or p == policy.manager_id else half_day_rest_misses).append(miss)
                    continue
                if relaxed_patrol_rest:
                    rest_flags = []
                    seated_flags = []
                    if rules_v220:
                        # v2.20 H-11-2: one "protected" patrol per patroller
                        # keeps the H-11 recovery; a double patroller's other
                        # patrol is ordinary standing work.
                        guard = model.new_bool_var(f"protected_patrol_{p}_{t}")
                        model.add(guard <= is_patrol)
                        protected_flags.append((t, guard))
                    else:
                        guard = None
                    for j in (t + 1, t + 2):
                        legal_rest = lambda r: r.counts_as_post_patrol_rest and r.actual_work_time_value == 0 and not r.barrier_install_flag and not r.barrier_remove_flag
                        rest_flags.append(expression(p, j, legal_rest))
                        seated_flags.append(expression(p, j, lambda r: r.actual_work_time_value == 1 and r.posture_or_mode == Posture.SEATED))
                        if t >= 7:
                            i1_or_rest = expression(p, j, lambda r: r.actual_work_time_value == 0 or r.displayed_assignment.label == "I1")
                            if guard is None:
                                model.add(is_patrol <= i1_or_rest + recovery_slack(f"i1_{p}_{t}_{j}"))
                            else:
                                model.add(i1_or_rest + recovery_slack(f"i1_{p}_{t}_{j}") >= 1).only_enforce_if(guard)
                    if guard is None:
                        model.add(is_patrol <= sum(rest_flags) + recovery_slack(f"rest_{p}_{t}"))
                    else:
                        model.add(sum(rest_flags) + recovery_slack(f"rest_{p}_{t}") >= 1).only_enforce_if(guard)
                        # Ladder: rest+rest 0 < rest+seated 3 < rest+standing 6;
                        # a double patroller protecting the early patrol +1.
                        quality = model.new_int_var(0, 12, f"patrol_recovery_{p}_{t}")
                        model.add(quality >= 3 * (4 - 2 * sum(rest_flags) - sum(seated_flags)) - 12 * (1 - guard))
                        patrol_recovery_costs.append(quality)
                    if rules_v29:
                        stood_before = expression(p, t - 1, lambda r: r.actual_work_time_value == 1 and r.posture_or_mode == Posture.STANDING)
                        bad_after = expression(p, t + 1, lambda r: r.actual_work_time_value == 1 and r.posture_or_mode != Posture.SEATED)
                        model.add(stood_before + is_patrol + bad_after <= 2)
                else:
                    rests = []
                    for j in (t + 1, t + 2):
                        legal_rest = lambda r, j=j: r.counts_as_post_patrol_rest and (mode_at(context, j) != Mode.FM or r.displayed_assignment.label == "휴게")
                        rests.append(expression(p, j, legal_rest))
                    if rules_v220 and p == "A" and not manager_is_proxy and t == 3:
                        # H-12-1 [하드, 2026-10-05 사용자 확정]: 통제A 21시 상층 순찰 직전 20시에 실근무가 없으면
                        # (휴게·보안실 대기, 차단봉 설치 포함) 22·23시 중 1칸은 포스트 허용, 나머지 1칸은 휴게.
                        free_before = expression(p, t - 1, lambda r: r.actual_work_time_value == 0)
                        model.add(sum(rests) + recovery_slack(f"h121a_{p}_{t}") >= 2 * is_patrol - free_before)
                        model.add(sum(rests) + recovery_slack(f"h121b_{p}_{t}") >= is_patrol)
                    else:
                        for n, rest in enumerate(rests):
                            model.add(is_patrol <= rest + recovery_slack(f"h11_{p}_{t}_{n}"))
                    if rules_v220:
                        guard = model.new_bool_var(f"protected_patrol_{p}_{t}")
                        model.add(guard == is_patrol)
                        protected_flags.append((t, guard))
            if protected_flags:
                has_patrol = model.new_bool_var(f"has_patrol_ladder_{p}")
                model.add(patrol_total[p] >= 1).only_enforce_if(has_patrol)
                model.add(patrol_total[p] == 0).only_enforce_if(has_patrol.Not())
                model.add(sum(g for _, g in protected_flags) + recovery_slack(f"h112_{p}") >= 1).only_enforce_if(has_patrol)
                double = model.new_bool_var(f"double_ladder_{p}")
                model.add(patrol_total[p] >= 2).only_enforce_if(double)
                model.add(patrol_total[p] <= 1).only_enforce_if(double.Not())
                for t, g in protected_flags:
                    if t in (3, 4, 5):
                        early = model.new_bool_var(f"early_protected_{p}_{t}")
                        model.add(early >= g + double - 1)
                        patrol_recovery_costs.append(early)
            install = expression(p, 2, lambda r: r.barrier_install_flag)
            remove = expression(p, 10, lambda r: r.barrier_remove_flag)
            model.add(install + remove <= 1)
            if target_probe:
                for t, barrier in ((2, install), (10, remove)):
                    # Soft preference: avoid a barrier-only job between actual posts.
                    standalone = expression(p, t, lambda r: r.actual_post_or_work_type.kind == K.BARRIER_ONLY)
                    before = expression(p, t - 1, lambda r: r.actual_work_time_value == 1)
                    after = expression(p, t + 1, lambda r: r.actual_work_time_value == 1)
                    model.add(standalone + before + after <= 2)
        if barrier_v2(context):
            # 15-0 (2026-10-05): 설치 2명 = G2+대기(20시 G2 운영) 또는 I1+대기 1명, 철수 = 04시 I1. 통제A는 설치·철수 안 함.
            model.add(sum(expression(p, 2, lambda r: r.barrier_install_flag) for p in people) == (1 if barrier_single(context) else 2))
            model.add(sum(expression(p, 2, lambda r: r.barrier_install_flag and r.displayed_assignment.label == "보안실 대기")
                          for p in people) == (0 if barrier_single(context) else 1))
            if policy.manager_id == "A" and not manager_is_proxy and ("A", 2) not in {
                    (old.employee_id, old.slot.index) for old in locked_assignments or ()}:
                model.add(expression("A", 2, lambda r: r.barrier_install_flag) == 0)
        elif mode_at(context, 2) == Mode.FM:
            model.add(sum(expression(p, 2, lambda r: r.barrier_install_flag) for p in people) == 1)
        else:
            model.add(sum(expression(p, 2, lambda r: r.barrier_install_flag) for p in people) == 2)
        if mode_at(context, 2) == Mode.FLEXIBLE and not barrier_v2(context):
            # §10-4: exactly one of the two flexible installers is the 20:00 보안실 대기.
            model.add(sum(expression(p, 2, lambda r: r.barrier_install_flag and r.displayed_assignment.label == "보안실 대기")
                          for p in people) == 1)
        model.add(sum(expression(p, 10, lambda r: r.barrier_remove_flag) for p in people) == 1)
        if target_probe:
            totals = {}
            for attribute in ("fatigue_value", "actual_rest_time_value"):
                for p in policy.general_ids:
                    totals[attribute, p] = sum(int(getattr(r, attribute)) * v for t in range(14) for r, v in zip(opts[p, t], variables[p, t]))
                for i, p in enumerate(policy.general_ids):
                    for q in policy.general_ids[i + 1:]:
                        model.add(totals[attribute, p] - totals[attribute, q] <= 1)
                        model.add(totals[attribute, q] - totals[attribute, p] <= 1)
        if baseline_assignments is not None:
            baseline = {(r["employee_id"], r["slot"]["index"]): r for r in baseline_assignments}
            if set(baseline) != {(p, t) for p in people for t in range(14)} or len(baseline_assignments) != 98:
                raise ValueError("Baseline must contain one record per employee/slot")
            def signature(label, install, remove):
                return ("off" if label in ("휴게", "보안실 대기") else label, install, remove)
            retained = []
            for p in people:
                for t in range(14):
                    old = baseline[p, t]
                    sig = signature(old["displayed_assignment"]["label"], old["barrier_install_flag"], old["barrier_remove_flag"])
                    retained.extend(v for r, v in zip(opts[p, t], variables[p, t]) if signature(r.displayed_assignment.label, r.barrier_install_flag, r.barrier_remove_flag) == sig)
            model.maximize(sum(retained))
        if minimize_a:
            if baseline_assignments is not None:
                raise ValueError("Choose A minimization or baseline preservation explicitly")
            a_work = sum(int(r.actual_work_time_value) * v for t in range(14) for r, v in zip(opts[policy.manager_id, t], variables[policy.manager_id, t]))
            a_fatigue = sum(int(r.fatigue_value) * v for t in range(14) for r, v in zip(opts[policy.manager_id, t], variables[policy.manager_id, t]))
            # Exact lexical order: fatigue <= 28, so 29 makes one work hour
            # dominate the entire fatigue range, not an arbitrary tradeoff weight.
            model.minimize(29 * a_work + a_fatigue)
            if vacancy_policy and headcount < 6 and not rules_v26:
                # Exact lexical retention: 00–05 standby before other optional
                # hours, then minimize A work/fatigue. Bounds fix dominance.
                absent_mid = sum(1 - sum(expression(p, t, lambda r: r.displayed_assignment.label == "보안실 대기") for p in people) for t in range(6, 12))
                absent_outer = sum(1 - sum(expression(p, t, lambda r: r.displayed_assignment.label == "보안실 대기") for p in people) for t in (*range(6), 12, 13))
                model.minimize(3915 * absent_mid + 435 * absent_outer + 29 * a_work + a_fatigue)
        solver = cp_model.CpSolver()
        solver.parameters.max_time_in_seconds = seconds
        solver.parameters.num_search_workers = 8
        solver.parameters.random_seed = 28
        if feasibility_only:
            # 충돌 진단(2026-10-18): 목표 없이 하드 규칙만으로 해가 있는지만 본다.
            if hasattr(model, "clear_objective"):
                model.clear_objective()
            status = solver.solve(model)
            attempts.append({"stage": "feasibility_only", "status": solver.status_name(status), "seconds": solver.wall_time})
            if status in (cp_model.OPTIMAL, cp_model.FEASIBLE):
                return SolveResult("FEASIBLE", None, attempts, False)
            continue
        if rules_v26:
            # Exact staged optimization. Never freeze an unproven objective.
            if manager_vacancy_policy:
                # v2.18: no manager work/fatigue privilege; strongly prefer
                # that the manager does not install or remove the barrier.
                manager_barrier = sum(expression(policy.manager_id, t, lambda r: r.barrier_install_flag or r.barrier_remove_flag) for t in (2, 10))
                objectives = [("manager_barrier_avoidance", manager_barrier)]
            elif manager_leaves:
                # 통제A 긴급 반차·이탈(10/18 사용자 확정): 빠지기 전 통제A에게 관리자 우대 없음 → 준호 승계 우대만(아래)
                objectives = []
            else:
                objectives = manager_objectives(a_work, a_fatigue, rules_v217=rules_v217,
                                                manager_is_proxy=manager_is_proxy)
            if ((late_proxy_manager_rules or (proxy_handover and locked_assignments is not None))
                    and not manager_vacancy_policy):     # 후반부 반차·긴급 승계 준호: 통제A와 같은 실근무 최소 우대
                objectives.append(("late_proxy_work", proxy_day_total("actual_work_time_value")))
            # 17-4 [강한 권장, 2026-10-05 사용자 확정]: 통제A 00시 이후 연속 휴게 2시간 (관리자 우대 바로 다음)
            if rules_v220 and policy.manager_id == "A" and not manager_is_proxy:
                late_pairs = []
                for t in range(6, 13):
                    pair = model.new_bool_var(f"manager_late_rest_pair_{t}")
                    for j in (t, t + 1):
                        model.add(pair <= expression("A", j, lambda r: r.actual_rest_time_value == 1))
                    late_pairs.append(pair)
                has_late_rest = model.new_bool_var("manager_late_two_hour_rest")
                model.add(has_late_rest <= sum(late_pairs))
                objectives.append(("manager_late_two_hour_rest", 1 - has_late_rest))
            # 17-2 [최상위 권장, 2026-10-04 사용자 확정]: 반차·이탈 없이 모두 온전히 근무하는 날,
            # 일반근무자마다 G1·L3·I1을 각각 최소 1번. 하드 바로 다음 순위이며 못 지키면 표는 만들고 사유를 표시한다.
            coverage_posts = ("G1", "L3", "I1")
            post_counts = {}
            if not partial_general_ids and len(full_general_ids) >= 2:
                missing_posts = []
                for p in full_general_ids:
                    for post in coverage_posts:
                        count = sum(expression(p, t, lambda r, post=post: r.displayed_assignment.label == post)
                                    for t in range(14))
                        post_counts[p, post] = count
                        missed = model.new_bool_var(f"post_missing_{p}_{post}")
                        model.add(missed >= 1 - count)
                        missing_posts.append(missed)
                objectives.insert(0, ("post_coverage", sum(missing_posts)))
            if switch_double_patrols:
                # §14-3: prefer as few double patrols as possible, A first.
                objectives.append(("switch_general_double_patrols", sum(switch_double_patrols)))
            if patrol_recovery_costs:
                objectives.append(("patrol_recovery_ladder", sum(patrol_recovery_costs)))
            # 8-9 [soft, strong, 2026-09-30]: after 00:00 the manager should not
            # stand L3 in two consecutive hours.
            manager_l3_pairs = []
            for t in range(6, 13):
                pair = model.new_bool_var(f"manager_l3_pair_{t}")
                model.add(pair >= expression(policy.manager_id, t, lambda r: r.displayed_assignment.label == "L3")
                          + expression(policy.manager_id, t + 1, lambda r: r.displayed_assignment.label == "L3") - 1)
                manager_l3_pairs.append(pair)
            objectives.append(("manager_l3_repeat_after_00", sum(manager_l3_pairs)))
            # 17-6 권장: 최근 2싸이클 평균 격차>=1이면 최대 손해자에게 1점 낮게.
            # 먼저 1점 초과 격차를 최소화하고, 그 범위 안에서 보상한다. HARD 완화 없음.
            averages = {p: compensation_averages[p] for p in full_general_ids
                        if compensation_averages and p in compensation_averages}
            if rules_v220 and long_term_balances is None and len(averages) >= 2:
                high = max(averages, key=lambda p: (averages[p], p))
                low = min(averages, key=lambda p: (averages[p], p))
                if averages[high] - averages[low] >= 1 - 1e-9:
                    fatigue = {p: sum(int(r.fatigue_value)*v for t in range(14)
                                      for r,v in zip(opts[p,t],variables[p,t])) for p in full_general_ids}
                    hi = model.new_int_var(0,40,"compensation_max")
                    lo = model.new_int_var(0,40,"compensation_min")
                    model.add_max_equality(hi,list(fatigue.values()))
                    model.add_min_equality(lo,list(fatigue.values()))
                    excess = model.new_int_var(0,40,"compensation_excess")
                    model.add_max_equality(excess,[0,hi-lo-1])
                    shortfall = model.new_int_var(0,41,"compensation_shortfall")
                    model.add_max_equality(shortfall,[0,1-fatigue[low]+fatigue[high]])
                    objectives.append(("compensation_gap_limit",excess))
                    objectives.append(("history_one_point_compensation",shortfall))
            spreads=[]
            for attr in ("fatigue_value", "actual_rest_time_value"):
                balance_ids = full_general_ids if rules_v215 and partial_general_ids else policy.general_ids
                totals=[sum(int(getattr(r,attr))*v for t in range(14) for r,v in zip(opts[p,t],variables[p,t])) for p in balance_ids]
                if proxy_in_balance and manager_a_start_slot > 0:
                    if attr == "fatigue_value":       # 전반부 반차 준호: 피로도 2점 우대 (10/18)
                        totals.append(proxy_day_total(attr) + EARLY_PROXY_FATIGUE_PRIVILEGE)
                elif proxy_in_balance:                # 결원 2명 규칙 날 후반부 준호: 우대 없이 n빵
                    totals.append(proxy_day_total(attr))
                if len(totals) >= 2:
                    hi=model.new_int_var(0,40,attr+"_max"); lo=model.new_int_var(0,40,attr+"_min")
                    model.add_max_equality(hi,totals); model.add_min_equality(lo,totals)
                    spreads.append(hi-lo)
            if prioritize_history_within_daily_targets:
                if historical_totals is None:
                    raise ValueError("History-priority balance requires historical totals")
                for spread in spreads:
                    model.add(spread <= 1)
            else:
                objectives.append(("general_balance",sum(spreads)))
            if rules_v220 and long_term_balances is not None:
                from .fatigue_ledger import objectives as ledger_objectives
                eligible = list(full_general_ids)
                fatigue = {p: sum(int(r.fatigue_value)*v for t in range(14)
                                  for r,v in zip(opts[p,t],variables[p,t])) for p in eligible}
                objectives.extend(ledger_objectives(model, fatigue, long_term_balances))
            if post_counts:                     # 17-2: 피로도·실휴게 n빵 다음, 포스트별 횟수 차이를 줄인다
                post_spreads = []
                for post in coverage_posts:
                    counts = [post_counts[p, post] for p in full_general_ids]
                    hi = model.new_int_var(0, 14, f"post_{post}_max"); lo = model.new_int_var(0, 14, f"post_{post}_min")
                    model.add_max_equality(hi, counts); model.add_min_equality(lo, counts)
                    post_spreads.append(hi - lo)
                objectives.append(("post_spread", sum(post_spreads)))
            if half_day_rest_misses:            # H-09-1: 반차자 순찰 직후 휴게는 다른 사람 밸런스 다음 권장
                objectives.append(("half_day_patrol_rest", sum(half_day_rest_misses)))
            # 17-1 개인 회피 [강한 소프트, 2026-10-02]: 당일 밸런스 다음, 이력 밸런스·선호 보너스보다 먼저
            avoid_terms = [expression(p, t, lambda r, label=label: r.displayed_assignment.label == label)
                           for p, t, label in avoid_cells if p in people]
            if avoid_terms:
                objectives.append(("personal_avoid", sum(avoid_terms)))
            if rules_v212:
                rest_four=[]
                actual_five=[]
                for p in people:
                    for start in range(11):
                        n=sum(expression(p,j,lambda r:r.actual_rest_time_value == 1) for j in range(start,start+4))
                        flag=model.new_bool_var(f"rest_four_{p}_{start}")
                        model.add(n == 4).only_enforce_if(flag)
                        model.add(n <= 3).only_enforce_if(flag.Not())
                        rest_four.append(debt_weight(soft_debt, "H-06-1", p) * flag if rules_v213 else flag)
                    for start in range(10):
                        n=sum(expression(p,j,lambda r:r.actual_work_time_value == 1) for j in range(start,start+5))
                        flag=model.new_bool_var(f"actual_five_{p}_{start}")
                        model.add(n == 5).only_enforce_if(flag)
                        model.add(n <= 4).only_enforce_if(flag.Not())
                        actual_five.append(flag)
                objectives.append(("rest_4plus_windows",sum(rest_four)))
                objectives.append(("actual_work_5plus_windows",sum(actual_five)))
                posture_triples = []
                for p in people:
                    for posture in (Posture.STANDING, Posture.SEATED):
                        for start in range(12):
                            n = sum(expression(p, j, lambda r: r.actual_work_time_value == 1 and r.posture_or_mode == posture) for j in range(start, start + 3))
                            flag = model.new_bool_var(f"v212_posture_triple_{p}_{posture}_{start}")
                            model.add(n == 3).only_enforce_if(flag)
                            model.add(n <= 2).only_enforce_if(flag.Not())
                        posture_triples.append(debt_weight(soft_debt, "H-06", p) * flag if rules_v213 else flag)
                objectives.append(("same_posture_triples", sum(posture_triples)))
                if previous_install_ids or previous_remove_ids:
                    recent_role_reversal = sum(expression(p,10,lambda r:r.barrier_remove_flag) for p in previous_install_ids if p in people)
                    recent_role_reversal += sum(expression(p,2,lambda r:r.barrier_install_flag) for p in previous_remove_ids if p in people)
                    objectives.append(("previous_barrier_role_reversal",recent_role_reversal))
                # 14-7 '다른 층 2회 연속이면 하층 우선'·soft debt는 2026-10-19 하층 순번(lower_oldest_*)으로 대체
            if historical_totals is not None:
                if historical_nights is None or set(historical_nights) != set(policy.general_ids):
                    raise ValueError("Historical attendance counts must identify every present general worker")
                denominator = {p:int(historical_nights[p])+1 for p in policy.general_ids}
                if any(n <= 0 for n in denominator.values()):
                    raise ValueError("Historical attendance counts cannot be negative")
                scale = lcm(*denominator.values())
                for attr in ("fatigue_value", "standing", "seated", "actual_work_time_value", "actual_rest_time_value", "patrol_fatigue"):
                    prior = historical_totals.get(attr)
                    if prior is None:
                        continue
                    if set(prior) != set(policy.general_ids):
                        raise ValueError(f"Historical {attr} must identify every present general worker")
                    values = []
                    for p in policy.general_ids:
                        if attr == "fatigue_value":
                            current = sum(int(r.fatigue_value)*v for t in range(14) for r,v in zip(opts[p,t], variables[p,t]))
                        elif attr == "standing":
                            current = sum(expression(p,t,lambda r:r.actual_work_time_value == 1 and r.posture_or_mode == Posture.STANDING) for t in range(14))
                        elif attr == "seated":
                            current = sum(expression(p,t,lambda r:r.actual_work_time_value == 1 and r.posture_or_mode == Posture.SEATED) for t in range(14))
                        elif attr in ("actual_work_time_value", "actual_rest_time_value"):
                            current = sum(int(getattr(r,attr))*v for t in range(14) for r,v in zip(opts[p,t],variables[p,t]))
                        else:
                            current = sum(int(r.fatigue_value)*v for t in range(14) for r,v in zip(opts[p,t],variables[p,t]) if r.actual_post_or_work_type.kind == K.PATROL)
                        values.append((int(prior[p])+current)*(scale//denominator[p]))
                    hi=model.new_int_var(0,1000,"history_"+attr+"_max")
                    lo=model.new_int_var(0,1000,"history_"+attr+"_min")
                    model.add_max_equality(hi, values); model.add_min_equality(lo, values)
                    objectives.append(("history_"+attr+"_spread",hi-lo))
            if not rules_v212 and (previous_install_ids or previous_remove_ids):
                recent_role_reversal = sum(expression(p,10,lambda r:r.barrier_remove_flag) for p in previous_install_ids if p in people)
                recent_role_reversal += sum(expression(p,2,lambda r:r.barrier_install_flag) for p in previous_remove_ids if p in people)
                objectives.append(("previous_barrier_role_reversal",recent_role_reversal))
            if prioritize_history_within_daily_targets:
                objectives.append(("general_balance",sum(spreads)))
            if rules_v27 and not rules_v212:
                posture_triples = []
                for p in people:
                    for posture in (Posture.STANDING, Posture.SEATED):
                        for start in range(12):
                            n = sum(expression(p, j, lambda r: r.actual_work_time_value == 1 and r.posture_or_mode == posture) for j in range(start, start + 3))
                            flag = model.new_bool_var(f"posture_triple_{p}_{posture}_{start}")
                            model.add(n == 3).only_enforce_if(flag)
                            model.add(n <= 2).only_enforce_if(flag.Not())
                            posture_triples.append(flag)
                # H-06 is a strong preference, not a feasibility constraint.
                objectives.append(("same_posture_triples", sum(posture_triples)))
            if exclusion_cost:
                objectives.append(("patrol_exclusion_rotation",sum(exclusion_cost)))
            # 15-8/14-8 [soft, 2026-09-30]: over the last 3 cycles (6 nights), give
            # barrier duty and each patrol zone to whoever has done it least per night.
            if duty_rates:
                duty_cost = []
                duty_preds = {      # 차단봉은 횟수 대신 마지막 참여일 순(15-8, 2026-10-19) — 아래 barrier_oldest_*
                    "upper": lambda r: r.actual_post_or_work_type.kind == K.PATROL and r.actual_post_or_work_type.label == "upper",
                    "middle": lambda r: r.actual_post_or_work_type.kind == K.PATROL and r.actual_post_or_work_type.label == "middle",
                    # 하층은 횟수 대신 마지막 하층일 순(14-7, 2026-10-19) — 아래 lower_oldest_*
                }
                for metric, pred in duty_preds.items():
                    for p in policy.general_ids:
                        # coarse 0~10 scale: same ordering, far easier to prove optimal
                        rate = round(int((duty_rates.get(metric) or {}).get(p, 0)) / 10)
                        if rate:
                            duty_cost.append(rate * sum(expression(p, t, pred) for t in range(14)))
                if duty_cost:
                    objectives.append(("duty_3cycle_balance", sum(duty_cost)))
            # Soft actual-work burden includes barriers: their exclusion from
            # H-08 must not make long uninterrupted duty look preferable.
            actual_long=[]
            for p in people:
                for length in range(4,15):
                    for start in range(15-length):
                        n=sum(expression(p,j,lambda r:r.actual_work_time_value == 1) for j in range(start,start+length))
                        flag=model.new_bool_var(f"actual_run_{p}_{start}_{length}")
                        model.add(n == length).only_enforce_if(flag)
                        model.add(n < length).only_enforce_if(flag.Not())
                        actual_long.append(flag)
            objectives.append(("actual_work_long_runs",sum(actual_long)))
            four=[]
            for p in people:
                for start in range(11):
                    n=sum(expression(p,j,lambda r:r.counts_for_continuous_work_restriction or r.actual_post_or_work_type.kind == K.PATROL) for j in range(start,start+4))
                    flag=model.new_bool_var(f"four_{p}_{start}")
                    model.add(n == 4).only_enforce_if(flag)
                    model.add(n <= 3).only_enforce_if(flag.Not())
                    four.append(debt_weight(soft_debt, "H-08", p) * flag if rules_v213 else flag)
            objectives.append(("four_hour_runs",sum(four)))
            sandwiches=[]
            for p in people:
                for t in (2,10):
                    n=expression(p,t,lambda r:r.actual_post_or_work_type.kind == K.BARRIER_ONLY)+expression(p,t-1,lambda r:r.actual_work_time_value == 1)+expression(p,t+1,lambda r:r.actual_work_time_value == 1)
                    flag=model.new_bool_var(f"barrier_between_{p}_{t}")
                    model.add(n == 3).only_enforce_if(flag)
                    model.add(n <= 2).only_enforce_if(flag.Not())
                    sandwiches.append(debt_weight(soft_debt, "15-7", p) * flag if rules_v213 else flag)
            objectives.append(("avoid_barrier_between_work",sum(sandwiches)))
            # 8-6 관리자 04시 I1 저우선 권장은 2026-10-05 사용자 요청으로 삭제(v2.20 호출부터). 07시 근무 회피만 남김.
            prefer04=0 if rules_v220 else expression(policy.manager_id,10,lambda r:r.actual_work_time_value == 1 and r.displayed_assignment.label != "I1")
            prefer07=expression(policy.manager_id,13,lambda r:r.actual_work_time_value == 1)
            objectives.append(("manager_post_preferences",prefer04+prefer07))
            if rules_v215 and partial_general_ids:
                ratio_ids = tuple(p for p in policy.general_ids if available_counts[p] > 0
                                  and p not in leaver_ids)          # 긴급 반차·이탈자는 비율 배려 없음(10/18)
                scale = lcm(*(available_counts[p] for p in ratio_ids))
                rates = [sum(int(r.actual_work_time_value) * v for t in range(14)
                             for r, v in zip(opts[p, t], variables[p, t]))
                         * (scale // available_counts[p]) for p in ratio_ids]
                if len(rates) >= 2:
                    hi = model.new_int_var(0, scale, "available_work_rate_max")
                    lo = model.new_int_var(0, scale, "available_work_rate_min")
                    model.add_max_equality(hi, rates)
                    model.add_min_equality(lo, rates)
                    objectives.append(("availability_normalized_workload", hi - lo))
            if rules_v27 and (headcount == 4 or rules_v210 and headcount == 5):
                # §14-3: prefer the repeat patrol at 03, then A for that patrol.
                repeat_at03 = []
                for p in people:
                    early = sum(expression(p,t,lambda r:r.actual_post_or_work_type.kind == K.PATROL) for t in (3,4,5))
                    late = expression(p,9,lambda r:r.actual_post_or_work_type.kind == K.PATROL)
                    both = model.new_bool_var(f"repeat_at03_{p}")
                    model.add(early + late == 2).only_enforce_if(both)
                    model.add(early + late <= 1).only_enforce_if(both.Not())
                    repeat_at03.append(both)
                if rules_v210 and not (rules_v220 and manager_is_proxy):
                    # 2026-10-20 사용자 확정: 준호 대행 날 2회 순찰자는 누구든 상관없음(관리자 우선 선호 없음)
                    manager_patrols = sum(expression(policy.manager_id, t, lambda r:r.actual_post_or_work_type.kind == K.PATROL) for t in (3,4,5,7,8,9))
                    objectives.append(("prefer_manager_double_patrol", 2-manager_patrols))
                objectives.append(("repeat_patrol_at03", 1-sum(repeat_at03)))
                if not rules_v210:
                    objectives.append(("manager_second_patrol", 1-expression(policy.manager_id,9,lambda r:r.actual_post_or_work_type.kind == K.PATROL)))
                if rules_v210:
                    late_two_hour_rest = []
                    for p in people:
                        for t in (7,8,9):
                            patrol = expression(p,t,lambda r:r.actual_post_or_work_type.kind == K.PATROL)
                            rest1 = expression(p,t+1,lambda r:r.displayed_assignment.label == "휴게")
                            rest2 = expression(p,t+2,lambda r:r.displayed_assignment.label == "휴게")
                            flag = model.new_bool_var(f"late_patrol_two_rest_{p}_{t}")
                            model.add(patrol + rest1 + rest2 == 3).only_enforce_if(flag)
                            model.add(patrol + rest1 + rest2 <= 2).only_enforce_if(flag.Not())
                            late_two_hour_rest.append(flag)
                    objectives.append(("prefer_late_double_patrol_rest", 1-sum(late_two_hour_rest)))
            # 17-1 공통 선호 보너스 [소프트, 2026-10-02]: 밸런스·룰북 소프트룰을 다 맞춘 뒤 남는 선택지에서
            # 00~05시 2시간 이상 연속 실휴게, 07시 실휴게를 준다. 최근 3싸이클 손해 본 사람일수록 가중치↑.
            if preference_weights:
                missed_preferences = []
                rest = lambda r: r.actual_rest_time_value == 1  # noqa: E731
                for p in policy.general_ids:
                    weight = int(preference_weights.get(p, 0))
                    if weight <= 0:
                        continue
                    pairs = []
                    for t in range(6, 11):                       # (00·01) … (04·05)
                        pair = model.new_bool_var(f"pref_rest_pair_{p}_{t}")
                        model.add(pair <= expression(p, t, rest))
                        model.add(pair <= expression(p, t + 1, rest))
                        pairs.append(pair)
                    long_rest = model.new_bool_var(f"pref_long_rest_{p}")
                    model.add(long_rest <= sum(pairs))
                    missed_preferences.append(weight * (1 - long_rest))
                    # 07시 수혜는 별도 최근 수혜일 우선순위로 결정한다.
                if missed_preferences:
                    objectives.append(("preference_bonus", sum(missed_preferences)))
            standby20=sum(expression(p,2,lambda r:r.displayed_assignment.label == "보안실 대기") for p in people)
            if context.effective_mode == Mode.FM and profile_absence == 0:
                deficit=model.new_int_var(0,2,"standby20_deficit")
                excess=model.new_int_var(0,len(people),"standby20_excess")
                model.add_max_equality(deficit,[0,2-standby20])
                model.add_max_equality(excess,[0,standby20-2])
                objectives.append(("optional_second_standby",deficit+excess))
            # 12장 보완 (2026-10-01): FM 시간(20·04시 제외)에는 비근무자가 2명 이상이면
            # 정확히 1명을 보안실 대기, 나머지는 휴게. 1명 이하면 보안실 대기 없음.
            # 보안실 대기는 밤 전체에서 사람마다 고르게 돌린다.
            standby_pairs=[]
            for p in people:
                for t in range(13):
                    pair=model.new_bool_var(f'consecutive_standby_{p}_{t}')
                    model.add(pair >= expression(p,t,lambda r:r.displayed_assignment.label=='보안실 대기')
                        + expression(p,t+1,lambda r:r.displayed_assignment.label=='보안실 대기')-1)
                    standby_pairs.append(pair)
            objectives.append(('avoid_consecutive_standby',sum(standby_pairs)))
            fm_slots = [t for t in range(14) if t not in (2, 10) and mode_at(context, t) == Mode.FM]
            is_standby = lambda r: r.displayed_assignment.label == "보안실 대기"  # noqa: E731
            is_off = lambda r: r.displayed_assignment.label in ("휴게", "보안실 대기") and r.actual_work_time_value == 0  # noqa: E731
            missing_standby = []
            for t in fm_slots:
                standby_t = sum(expression(p, t, is_standby) for p in people)
                off_t = sum(expression(p, t, is_off) for p in people)
                two_off = model.new_bool_var(f"fm_two_off_{t}")
                model.add(off_t >= 2).only_enforce_if(two_off)
                model.add(off_t <= 1).only_enforce_if(two_off.Not())
                if t not in required_standby_slots:
                    model.add(standby_t <= two_off + sum(patrol_third_standby[t]))
                model.add(standby_t <= 1)
                missing=model.new_int_var(0,1,f'fm_missing_standby_{t}')
                model.add_max_equality(missing,[0,two_off-standby_t])
                missing_standby.append(missing)
            if fm_slots:
                objectives.append(("fm_one_standby", sum(missing_standby)))
            # 20시·04시 필수 대기와 유도리 시간까지 포함한 당일 전체 대기 횟수.
            standby_squares=[]
            for p in people:
                if p=='A':continue  # 통제A 대기 표기는 일반근무자 부담 균등을 위해 허용
                count=model.new_int_var(0,14,f'all_standby_count_{p}')
                model.add(count==sum(expression(p,t,is_standby) for t in range(14)))
                square=model.new_int_var(0,196,f'all_standby_square_{p}')
                model.add_multiplication_equality(square,[count,count])
                standby_squares.append(square)
            objectives.append(('standby_total_load',sum(standby_squares)))
            flexible_slots = [t for t in range(14) if t not in (2, 10) and t not in fm_slots]
            if flexible_slots:
                optional=sum(expression(p,t,is_standby) for p in people for t in flexible_slots)
                objectives.append(("remaining_off_duty_rest",optional))
            # 룰북 0-2-1 (2026-10-02 사용자 확정): FM을 고르면 먼저 'FM·유도리 모두 만족' 해를 찾는다.
            # 같은 표시표를 유도리(해당 표의 I1 휴게성 운영, 10-4·10-5 차단봉)로 계산해도 지켜야 하는
            # 조건 중 FM과 달라지는 것만 더한다: A 격차(H-15·8-4-2)와 유도리 20시 설치자 ≠ 04시 I1(철수).
            # 최종 판정은 서비스가 유도리로 계산한 표를 독립 Validator로 다시 검사해서 한다.
            if dual_flexible and context.effective_mode == Mode.FM and switch_slot is None:
                _add_dual_flexible_constraints(
                    model, opts, variables, policy, context, people, partial_general_ids,
                    gap_rule=not manager_vacancy_policy,
                    fatigue_rule=headcount in (5, 6) and not (rules_v218 and profile_absence == 2),
                    fatigue_band=(0, 3 if rules_v220 else 2) if rules_v219 and not manager_is_proxy else (-4, 4),
                    skip_partial=rules_v215, balance=dual_balance,
                    big_rest_rule=rules_v220 and not rule_off("16-big 막타임·대폭 휴게 동시 금지"),
                    manager_a_end_slot=manager_a_end_slot,
                    locked_keys={(old.employee_id, old.slot.index) for old in locked_assignments or ()})
            # A stage that runs out of time keeps its best value as an upper bound
            # (never frozen as if proven) and later stages still run, warm-started
            # from the previous solution; the whole staged run shares a time budget.
            all_vars = [v for key in variables for v in variables[key]]
            budget = max(seconds * 3, 30)
            spent = 0.0
            best_status = None
            best_values = None
            if rules_v220 and manager_vacancy_policy and policy.general_ids:
                n = len(policy.general_ids)
                boss_fatigue = sum(int(r.fatigue_value) * v for t in range(14)
                                   for r, v in zip(opts[policy.manager_id,t], variables[policy.manager_id,t]))
                general_fatigue = sum(int(r.fatigue_value) * v for p in policy.general_ids for t in range(14)
                                      for r, v in zip(opts[p,t], variables[p,t]))
                difference = model.new_int_var(0, 1000, "vacancy_manager_average_gap_scaled")
                model.add_abs_equality(difference, n * boss_fatigue - general_fatigue)
                excess = model.new_int_var(0, 1000, "vacancy_manager_average_gap_excess")
                model.add_max_equality(excess, [0, difference - 4 * n])
                position = next((i + 1 for i, (name, _) in enumerate(objectives) if name == "general_balance"),
                                next((i + 1 for i, (name, _) in enumerate(objectives) if name == "post_coverage"), 0))
                objectives.insert(position, ("vacancy_manager_fatigue_gap", excess))
            # 8-4-2: 다른 소프트 목표가 먼저. 0~2점 유지 목표는 맨 마지막,
            # HARD 상한3점·A가 일반보다 높은 배정 금지는 그대로 지킨다.
            if (rules_v220 and not manager_is_proxy and headcount in (5,6)
                    and not manager_vacancy_policy and switch_slot is None):
                penalties = []
                contexts = (context, replace(context, requested_mode=Mode.FLEXIBLE,
                                             effective_mode=Mode.FLEXIBLE)) if dual_flexible else (context,)
                for index, accounting in enumerate(contexts):
                    totals = {p: sum((int(r.fatigue_value) +
                                      (_flexible_delta(r,t,accounting)[0] if index else 0))*v
                                     for t in range(14) for r,v in zip(opts[p,t],variables[p,t]))
                              for p in (*full_general_ids,policy.manager_id)}
                    for p in full_general_ids:
                        penalty = model.new_int_var(0,40,f"a_gap_preference_{index}_{p}")
                        model.add_max_equality(penalty,[0,totals[p]-totals[policy.manager_id]-2])
                        penalties.append(penalty)
                        if late_proxy_manager_rules and index == 0:   # 후반부 반차 준호도 통제A처럼 0~2점 유지 목표
                            proxy_penalty = model.new_int_var(0,40,f"late_proxy_gap_preference_{p}")
                            model.add_max_equality(proxy_penalty,[0,totals[p]-proxy_day_total("fatigue_value")-2])
                            penalties.append(proxy_penalty)
                objectives.append(("manager_normal_gap_preference",sum(penalties)))
            # 전반부 반차 통제A는 01~04시 실근무 최대(10/18 사용자 확정).
            # 05~07시 기존 규칙은 그대로. 준호가 대행한 전반부는 이 목표에서 제외.
            # 기존 관리자 최소근무보다 앞서 맞추고, 막타임 순번 목표는 유지한다.
            if manager_a_start_slot > 0 and policy.manager_id == 'A':
                active_a_work = sum(expression('A', t, lambda r: r.actual_work_time_value == 1)
                                    for t in range(manager_a_start_slot, min(11, manager_a_end_slot)))
                objectives.insert(0, ('manager_early_active_work_max', -active_a_work))
            # 14-7 (2026-10-19 사용자 확정): 하층 순찰 순번. 야간·공휴일 주간 이력에서 마지막 하층 뒤
            # 상층·중층 순찰한 출근 3회 이상이면 후보, 마지막 하층이 오래된 그룹부터. 막타임→차단봉 다음.
            lower_groups = {}
            for p in policy.general_ids:
                if not any(a.employee_id == p and a.present for a in context.attendance):
                    continue
                name = next(e.name for e in context.employees if e.employee_id == p)[-2:]
                wait = lower_patrol_wait(patrol_events, name)
                if wait is not None:
                    lower_groups.setdefault(wait, []).append(p)
            lower_priorities = []
            for day, group in sorted(lower_groups.items()):
                got = []
                for p in group:
                    lower_count = sum(expression(p, t, lambda r: r.actual_post_or_work_type.kind == K.PATROL
                                                 and r.actual_post_or_work_type.label == "lower") for t in range(14))
                    flag = model.new_bool_var(f"lower_turn_{p}")
                    model.add(lower_count >= 1).only_enforce_if(flag)
                    got.append(flag)
                lower_priorities.append(('lower_oldest_' + (day or 'never'), -sum(got)))
            # 16장·15-8·대폭 휴게(2026-10-20 사용자 확정): 순번 기준 = 미수혜자 1순위(출근 많은 순) → 마지막 수혜 뒤 본인 출근 횟수 많은 순.
            # 대폭 휴게(23시~07시 전 3시간+ 연속 실휴게): 결원 1.5명 미만 날 최대 인원 확보(big_rest_max) 후 순번 배정(big_rest_oldest_*).
            def _turn_key(records_for_p, check_fn):
                idx = max((i for i, r in enumerate(records_for_p) if check_fn(r)), default=-1)
                return (0, -len(records_for_p)) if idx < 0 else (1, -(len(records_for_p) - 1 - idx))

            def _had_big_rest(rec, pid):
                if rec.context.manager_handover and not rec.context.manager_handover_reverse:
                    if rec.context.manager_handover[1] == pid and rec.context.manager_handover[0] <= 13:
                        return False
                rest_t = {x.slot.index for x in rec.assignments if x.employee_id == pid and x.actual_rest_time_value == 1}
                return any(all(t in rest_t for t in (s, s + 1, s + 2)) for s in BIG_REST_STARTS)

            big_rest_priorities = []
            if rules_v220 and not manager_vacancy_policy and (absence_count + 0.5 * len(partial_general_ids)) < 1.5:
                big_vars = {}
                for p in policy.general_ids:
                    if p == "6" and (policy.manager_id == "6" or manager_a_end_slot <= 13):
                        continue
                    att = next((a for a in context.attendance if a.employee_id == p and a.present), None)
                    if att is None or sum(att.is_available(t) for t in BIG_REST_SLOTS) < 3:
                        continue
                    wins = []
                    for s in BIG_REST_STARTS:
                        win = model.new_bool_var(f"big_rest_win_{p}_{s}")
                        for j in (s, s + 1, s + 2):
                            model.add(win <= expression(p, j, lambda r: r.actual_rest_time_value == 1))
                        model.add(win >= sum(expression(p, j, lambda r: r.actual_rest_time_value == 1) for j in (s, s + 1, s + 2)) - 2)
                        wins.append(win)
                    got_big = model.new_bool_var(f"big_rest_person_{p}")
                    for win in wins:
                        model.add(got_big >= win)
                    model.add(got_big <= sum(wins))
                    big_vars[p] = got_big
                if big_vars:
                    big_rest_priorities.append(("big_rest_max", -sum(big_vars.values())))
                    if last_rest_records:
                        big_groups = {}
                        for p in big_vars:
                            att_b = sorted((r for r in last_rest_records
                                            if barrier_history_counts(r.context) and r.context.shift_start_date < context.shift_start_date
                                            and any(a.employee_id == p and a.present and a.is_general_worker for a in r.context.attendance)),
                                           key=lambda r: r.context.shift_start_date)
                            big_groups.setdefault(_turn_key(att_b, lambda r, p=p: _had_big_rest(r, p)), []).append(p)
                        if len(big_groups) > 1:
                            for key, group in sorted(big_groups.items()):
                                big_rest_priorities.append((f"big_rest_oldest_{key[0]}_{-key[1]}", -sum(big_vars[p] for p in group)))

            if not last_rest_records:
                objectives = lower_priorities + big_rest_priorities + objectives
            if last_rest_records:
                groups = {}
                for p in policy.general_ids:
                    attended=sorted((r for r in last_rest_records if r.context.shift_start_date < context.shift_start_date
                        and any(a.employee_id==p and a.present and a.is_general_worker for a in r.context.attendance)),
                        key=lambda r:r.context.shift_start_date)
                    received=[r.context.shift_start_date.toordinal() for r in attended if any(
                        x.employee_id==p and x.slot.index==13 and x.actual_rest_time_value==1 for x in r.assignments)]
                    if attended and any(x.employee_id==p and x.slot.index==13 and x.actual_rest_time_value==1
                                        for x in attended[-1].assignments):
                        if (p,13) not in {(x.employee_id,x.slot.index) for x in locked_assignments or ()}:
                            model.add(expression(p,13,lambda r:r.actual_rest_time_value==1)==0)
                        continue
                    if not next(a for a in context.attendance if a.employee_id==p).is_available(13):continue
                    groups.setdefault(_turn_key(attended, lambda r, p=p: any(
                        x.employee_id == p and x.slot.index == 13 and x.actual_rest_time_value == 1 for x in r.assignments)), []).append(p)
                priorities = [(f'last_rest_oldest_{key[0]}_{-key[1]}', sum(1 - expression(p, 13, lambda r: r.actual_rest_time_value == 1)
                               for p in group)) for key, group in sorted(groups.items())]
                # 15-8 (2026-10-19 사용자 확정): 차단봉 설치·철수 중 아무거나 마지막으로 한 날이 오래된 사람부터,
                # 막타임 다음 최우선. 10/04 야간 이후 저장된 실제 야간 전체, 이력에 없으면 가장 오래 기다린 그룹.
                barrier_groups = {}
                for p in policy.general_ids:
                    if not any(a.employee_id == p and a.present for a in context.attendance):
                        continue
                    done = [r.context.shift_start_date.toordinal() for r in last_rest_records
                            if barrier_history_counts(r.context) and r.context.shift_start_date < context.shift_start_date
                            and any(x.employee_id == p and (x.barrier_install_flag or x.barrier_remove_flag) for x in r.assignments)]
                    att_b = sorted((r for r in last_rest_records
                                    if barrier_history_counts(r.context) and r.context.shift_start_date < context.shift_start_date
                                    and any(a.employee_id == p and a.present and a.is_general_worker for a in r.context.attendance)),
                                   key=lambda r: r.context.shift_start_date)
                    barrier_groups.setdefault(_turn_key(att_b, lambda r, p=p: any(
                        x.employee_id == p and (x.barrier_install_flag or x.barrier_remove_flag) for x in r.assignments)), []).append(p)
                if len(barrier_groups) > 1:
                    priorities += [(f'barrier_oldest_{key[0]}_{-key[1]}', -sum(expression(p, t, lambda r: r.barrier_install_flag or r.barrier_remove_flag)
                                    for p in group for t in (2, 10))) for key, group in sorted(barrier_groups.items())]
                objectives = priorities + lower_priorities + big_rest_priorities + objectives
            if vacancy1_standby_missing:                 # 12-5 결원 1명 시간: 가능하면 지킬 규칙 → 소프트 목표 맨 앞
                objectives.insert(0, ("vacancy1_required_standby", sum(vacancy1_standby_missing)))
            # 긴급 반차·이탈자(통제A·일반근무자 모두): 빠지기 전 남은 칸은 필요한 곳만 휴게 → 소프트 맨 앞
            # (2026-10-18 사용자 확정: 배려(휴게)가 최후순위 — 종전엔 일반근무자의 '실근무 많이'를 맨 뒤에 둬서 반대로 됐음)
            general_leaver_rests = sum(1 - expression(p, t, lambda r: r.actual_work_time_value == 1)
                                       for p, t in emergency_leaver_cells if p in leaver_ids and (p, t) in opts)
            if not isinstance(manager_leaver_rests, int):
                objectives.insert(0, ("manager_leaver_rest", manager_leaver_rests))
            if not isinstance(general_leaver_rests, int):
                objectives.insert(0, ("emergency_leaver_rest", general_leaver_rests))
            if recovery_misses:                          # 긴급 재편성 순찰 뒤 회복(10/18): 가능하면 지킬 규칙 → 그보다도 앞
                objectives.insert(0, ("emergency_patrol_recovery", sum(recovery_misses)))
            if handover_standing_misses:                 # 교대 직전 LOCK 입식 2칸 뒤 입식 3연속(10/20): 가능하면 지킬 규칙
                objectives.insert(0, ("handover_standing", sum(handover_standing_misses)))
            # 8-10-1 (2026-10-20 사용자 확정, 아주 강한 권장): 관리자(통제A·준호 대행 모두) 04시는 최대한 비운다(실근무 없음).
            # 빠진 근무는 그 이전(00~03시)으로 — 05·06시 관리자 실근무는 그다음으로 최소화. 가능하면 지킬 규칙 바로 다음,
            # 막타임 순번보다 앞. A 피로도는 8-4-2 하드(0~3점 낮음) 안에서 움직이고 0~2점 목표는 최후순위 그대로. LOCK 보존.
            # 통제A 전반부 반차(01시 출근) 날은 제외 — 0-4-4 '01~04시 실근무 최대'가 우선 (2026-10-20 사용자 확정)
            manager_row = policy.manager_id
            if rules_v220 and manager_row in people and manager_a_start_slot == 0:
                locked_now = {(old.employee_id, old.slot.index) for old in locked_assignments or ()}
                free = [t for t in (10, 11, 12) if (manager_row, t) not in locked_now]
                work_at = {t: expression(manager_row, t, lambda r: r.actual_work_time_value == 1) for t in free}
                early = [("manager_04_rest", work_at[10])] if 10 in free else []
                early += [("manager_0506_work", sum(work_at[t] for t in (11, 12) if t in free))] if {11, 12} & set(free) else []
                front_count = sum(1 for o in objectives if o[0] in ("handover_standing", "emergency_patrol_recovery", "emergency_leaver_rest",
                                                                      "manager_leaver_rest", "vacancy1_required_standby"))
                objectives[front_count:front_count] = [o for o in early if not isinstance(o[1], int)]
            if rules_v220:
                run_goals = [o for o in objectives if o[0] in ("actual_work_long_runs", "four_hour_runs")]
                objectives = [o for o in objectives if o[0] not in ("actual_work_long_runs", "four_hour_runs")]
                run_pos = sum(1 for o in objectives if o[0] in ("handover_standing", "emergency_patrol_recovery", "emergency_leaver_rest",
                                                                  "manager_leaver_rest", "vacancy1_required_standby", "manager_04_rest", "manager_0506_work"))
                objectives[run_pos:run_pos] = run_goals
            if emergency_leaver_cells:                   # 긴급 반차·이탈자 배려 없음 — 맨 마지막 권장(10/18 사용자 확정)
                leaver_load = sum(expression(p, t, lambda r: r.actual_work_time_value == 1)
                                  + expression(p, t, lambda r: r.actual_work_time_value == 1 and r.posture_or_mode == Posture.STANDING)
                                  for p, t in emergency_leaver_cells if (p, t) in opts)
                if not isinstance(leaver_load, int):
                    objectives.append(("emergency_leaver_load", -leaver_load))
            if leaver_rest_misses:
                objectives.append(("emergency_leaver_patrol_rest", sum(leaver_rest_misses)))
            if rules_v220 and long_term_balances is not None:
                # 사용자 확정 10/20 (가): 가능하면 지킬 규칙 → 막타임 → 차단봉 → 하층 순번 → 당일 균형 → 장기 미상환 → 기타.
                front_names = ("handover_standing", "emergency_patrol_recovery", "emergency_leaver_rest", "manager_leaver_rest",
                               "vacancy1_required_standby", "manager_04_rest", "manager_0506_work", "actual_work_long_runs", "four_hour_runs")
                turn_prefixes = ("last_rest_oldest_", "barrier_oldest_", "lower_oldest_", "big_rest_")
                front_goals = [o for o in objectives if o[0] in front_names]
                turn_goals = [o for o in objectives if o[0].startswith(turn_prefixes)]
                # 결원 2명 조장-일반 평균 4점 이내(17-5)는 당일 균형 묶음의 맨 앞(2026-10-20 사용자 확정:
                # 일반근무자끼리 완벽 균형을 위해 조장과 크게 벌어지지 않게).
                balance_goals = ([o for o in objectives if o[0] == 'vacancy_manager_fatigue_gap']
                                 + [o for o in objectives if o[0] == 'general_balance'])
                ledger_goals = [o for o in objectives if o[0].startswith('long_term_fatigue_')]
                placed = {id(o) for o in front_goals + turn_goals + balance_goals + ledger_goals}
                other_goals = [o for o in objectives if id(o) not in placed]
                objectives = front_goals + turn_goals + balance_goals + ledger_goals + other_goals
            for objective_name, objective in objectives:
                model.minimize(objective)
                cap = STAGE_TIME_CAPS.get(objective_name, float(seconds))
                solver.parameters.max_time_in_seconds = max(3.0, min(float(seconds), cap, budget - spent))
                status=solver.solve(model)
                spent += solver.wall_time
                attempts.append({"stage":objective_name,"status":solver.status_name(status),"seconds":solver.wall_time,
                                 "value":solver.value(objective) if status in (cp_model.OPTIMAL,cp_model.FEASIBLE) else None})
                if status not in (cp_model.OPTIMAL, cp_model.FEASIBLE):
                    if best_status is None:
                        break
                    status = best_status        # keep the last good solution below
                    break
                value = solver.value(objective)
                best_values = {v.index: solver.value(v) for v in all_vars}
                model.clear_hints()
                for v in all_vars:
                    model.add_hint(v, best_values[v.index])
                if status == cp_model.OPTIMAL:
                    model.add(objective == value)
                else:
                    model.add(objective <= value)
                best_status = status
        else:
            status = solver.solve(model)
        name = solver.status_name(status)
        attempts.append({"balance_target_probe": target_probe, "status": name, "seconds": solver.wall_time,
                         "refinement": refinement,
                         "rules_v22": rules_v22,
                         "vacancy_policy": vacancy_policy,
                         "minimize_a": minimize_a,
                         "a_objective_value": solver.objective_value if minimize_a and not rules_v26 and status in (cp_model.OPTIMAL, cp_model.FEASIBLE) else None,
                         "a_objective_bound": solver.best_objective_bound if minimize_a and not rules_v26 else None,
                         "unchanged_duty_slots": solver.objective_value if baseline_assignments is not None and status in (cp_model.OPTIMAL, cp_model.FEASIBLE) else None})
        if status in (cp_model.OPTIMAL, cp_model.FEASIBLE):
            kept = locals().get("best_values")
            value_of = (lambda v: kept[v.index]) if kept else solver.value
            rows = tuple(next(r for r, v in zip(opts[p, t], variables[p, t]) if value_of(v)) for p in people for t in range(14))
            record = ShiftRecord(f"trial-{context.shift_start_date}-{context.effective_mode.value}", RecordKind.PLAN, context, rows)
            # OPTIMAL on a satisfaction problem means feasible, not optimal balance.
            return SolveResult("FEASIBLE", record, attempts, target_probe)
        if status == cp_model.MODEL_INVALID:
            return SolveResult("MODEL_INVALID", None, attempts, False)
    return SolveResult("INFEASIBLE" if status == cp_model.INFEASIBLE else "UNKNOWN", None, attempts, False)
