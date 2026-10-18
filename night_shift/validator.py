"""Stage 6: independent N1/6/A/no-history validator.

Deliberately does not import solver, common predicates or mode profiles.
Reconstructs accounting from displayed labels and barrier facts; never trusts
cached flags or solver status. This is not a validator for other scenarios.
"""
from collections import Counter
from datetime import date
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


def validate_first_trial(record, history, *, refinement=False, rules_v22=False, vacancy_policy=False, rules_v26=False, rules_v27=False, rules_v29=False, rules_v210=False, rules_v212=False, rules_v215=False, rules_v216=False, rules_v218=False, rules_v219=False, rules_v220=False, reoptimization=False, forbid_patrol_exclusion_ids=(), post_cap=None, work_spread=True, half_day_ids=None, locked_cells=(), manager_a_end_slot=14, manager_a_start_slot=0, patrol_actuals=(), patrol_events=(), last_rest_records=(),
                        emergency_leaver_cells=()):
    # H-17 (2026-10-05): None = v2.20 검사에 포함. 2명 완전결원 일시 해제·LOCK 과거 초과 시 서비스가 False를 넘긴다.
    post_cap = rules_v220 if post_cap is None else post_cap
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
    # Solver와 공유하지 않고 과거 실제 출근 2회를 독립 검사한다.
    for person in c.attendance:
        if not person.present or not person.is_general_worker:
            continue
        prior = []
        for old in sorted(patrol_actuals, key=lambda r:r.context.shift_start_date, reverse=True):
            if old.context.shift_start_date >= c.shift_start_date:
                continue
            if any(a.employee_id == person.employee_id and a.present for a in old.context.attendance):
                prior.append(old)
                if len(prior) == 2:
                    break
        needs_patrol = False
        for old in prior:
            all_present = sum(a.present for a in old.context.attendance) == 7
            was_general = any(a.employee_id == person.employee_id and a.is_general_worker
                              for a in old.context.attendance)
            performed = any(x.employee_id == person.employee_id and x.actual_post_or_work_type.kind == K.PATROL
                            for x in old.assignments)
            if all_present and was_general and not performed:
                needs_patrol = True
        if patrol_events:
            personal = sorted((e for e in patrol_events if e['name'] == next(
                p.name for p in c.employees if p.employee_id == person.employee_id)[-2:]),
                key=lambda e:(e['date'],e['shift']))
            needs_patrol = any(e['excluded'] for e in personal[-2:])
        if needs_patrol:
            check(any(x.employee_id == person.employee_id and x.actual_post_or_work_type.kind == K.PATROL
                      for x in record.assignments), '14-1-2',
                  f'{person.employee_id}: 순찰 제외 후 다음 출근 2회 순찰 필수')
    for attendance in c.attendance:
        if not attendance.present:
            continue
        pid = attendance.employee_id
        streak = 0
        for old in sorted(patrol_actuals, key=lambda item:item.context.shift_start_date, reverse=True):
            if old.context.shift_start_date >= c.shift_start_date:
                continue
            if not any(a.employee_id == pid and a.present for a in old.context.attendance):
                continue
            if any(row.employee_id == pid and row.actual_post_or_work_type.kind == K.PATROL
                   and row.actual_post_or_work_type.label == 'lower' for row in old.assignments):
                streak += 1
            else:
                break
            if streak == 2:
                break
        if streak >= 2:
            for row in record.assignments:
                if (row.employee_id == pid and row.actual_post_or_work_type.kind == K.PATROL
                        and row.actual_post_or_work_type.label == 'lower'):
                    check((pid,row.slot.index) in set(locked_cells), '14-9',
                          f'{pid}/{row.slot.index}: 하층 순찰 3회 연속 금지')
    for person in c.attendance:
        if not person.present or not person.is_general_worker:continue
        previous = None
        for old in sorted(last_rest_records,key=lambda r:r.context.shift_start_date,reverse=True):
            if old.context.shift_start_date>=c.shift_start_date:continue
            if any(a.employee_id==person.employee_id and a.present and a.is_general_worker for a in old.context.attendance):
                previous=old
                break
        if previous is not None and any(x.employee_id==person.employee_id and x.slot.index==13
                and x.actual_rest_time_value==1 for x in previous.assignments):
            for current in record.assignments:
                if current.employee_id==person.employee_id and current.slot.index==13:
                    check(current.actual_rest_time_value!=1 or (person.employee_id,13) in set(locked_cells),
                          '16-next',f'{person.employee_id}/13: 직전 출근 야간 막타임 휴게 연속 금지')
    if rules_v220:
        for person in c.attendance:
            if not person.present:continue
            person_rows={r.slot.index:r for r in record.assignments if r.employee_id==person.employee_id}
            for t in range(11):
                rows=[person_rows.get(j) for j in range(t,t+4)]
                if not all(rows):continue
                if rows[0].actual_post_or_work_type.kind==K.PATROL and all(
                        r.actual_rest_time_value==1 for r in rows[1:3]):
                    for j in (1,2):
                        check(rows[j].displayed_assignment.label!='보안실 대기'
                              or (person.employee_id,t+j) in set(locked_cells),'12-protected',
                              f'{person.employee_id}/{t+j}: 순찰 직후 2시간 비포스트는 휴게 표기')
                if (rows[0].actual_post_or_work_type.kind==K.PATROL
                    and rows[1].actual_rest_time_value==1 and rows[2].actual_rest_time_value==1
                    and rows[3].actual_rest_time_value==1
                    and rows[3].displayed_assignment.label in ('휴게','보안실 대기')):
                    check(rows[3].displayed_assignment.label=='보안실 대기'
                          or (person.employee_id,t+3) in set(locked_cells),'12-third',
                          f'{person.employee_id}/{t+3}: 순찰 후 세 번째 비포스트 휴게는 대기 표기')
    if rules_v220:
        protected=set(locked_cells)
        for a in c.attendance:
            if not a.present:continue
            rows={r.slot.index:r for r in record.assignments if r.employee_id==a.employee_id}
            for start in range(12):
                block=[rows.get(j) for j in range(start,start+3)]
                if not all(block):continue
                if all(r.displayed_assignment.label in ('휴게','보안실 대기')
                       and r.actual_rest_time_value==1 for r in block):
                    labels=[r.displayed_assignment.label for r in block]
                    pair=labels[:2]==['휴게','휴게'] or labels[1:]==['휴게','휴게']
                    check(pair or all((a.employee_id,j) in protected for j in range(start,start+3)),
                          '12-block',f'{a.employee_id}/{start}: 비포스트 3시간에는 연속 휴게 2시간 필요')
    if rules_v220:
        locked_standby=set(locked_cells)
        for slot in range(12):
            vacancies=7-sum(a.present and a.is_available(slot) for a in c.attendance)
            # 결원 1명 시간은 가능하면 지킬 규칙(2026-10-18 사용자 확정) — 하드 검증 대상 아님
            if vacancies in (1,2):continue
            people_here=[a.employee_id for a in c.attendance if a.present]
            fully_locked=all((pid,slot) in locked_standby for pid in people_here)
            has_standby=any(r.slot.index==slot and r.displayed_assignment.label=='보안실 대기'
                            for r in record.assignments)
            check(has_standby or fully_locked,'12-required',f'{slot}: 18~05시 결원2명 외 대기자 최소1명 필요')
    if rules_v220:
        # 12-6: 긴급 반차·이탈자는 제외 (2026-10-18 사용자 확정). 재편성표의 부분 출근 일반근무자 중
        # 미리 정한 반차자(half_day_ids)·관리자 대행 준호가 아니면 긴급 이탈자다.
        out_126 = set()
        if reoptimization:
            partial_126 = {a.employee_id for a in c.attendance if a.present and a.is_general_worker
                           and not all(a.is_available(t) for t in range(14))}
            out_126 = ({p for p, _ in emergency_leaver_cells if p != 'A'}
                       | (partial_126 - set(half_day_ids or ())
                          - ({"6"} if manager_a_start_slot > 0 or manager_a_end_slot < 14 else set())))
        standby_counts={a.employee_id:sum(r.employee_id==a.employee_id
            and r.displayed_assignment.label=='보안실 대기' for r in record.assignments)
            for a in c.attendance if a.present and a.employee_id!='A' and a.employee_id not in out_126}
        if len(standby_counts)>=2:
            check(max(standby_counts.values())-min(standby_counts.values())<=1,'12-gap',
                  f'통제A 제외 대기 횟수 차이2회 이상: {standby_counts}')
    if rules_v220 and not any(p == 'A' for p, _ in emergency_leaver_cells):   # 통제A 긴급 반차 날 8-14 면제(10/18)
        a_att=next((a for a in c.attendance if a.employee_id=='A' and a.present),None)
        if a_att is not None:
            available=[t for t in range(manager_a_start_slot,min(14,manager_a_end_slot)) if a_att.is_available(t)]
            completed=available and all(('A',t) in set(locked_cells) for t in available)
            check(not available or completed or any(r.employee_id=='A' and r.slot.index in available
                  and r.displayed_assignment.label=='I1' for r in record.assignments),
                  '8-14','A: 통제A 출근 야간 I1 최소1회 필요')
    if rules_v220:
        a_standby=[r for r in record.assignments if r.employee_id=='A' and manager_a_start_slot<=r.slot.index<manager_a_end_slot
                   and r.displayed_assignment.label=='보안실 대기']
        completed=sum(('A',r.slot.index) in set(locked_cells) for r in a_standby)
        check(len(a_standby)<=max(2,completed),'8-15','A: 통제A 야간 대기 최대2회 초과')
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
    if post_cap:                                         # H-17: 같은 포스트(표시) 한 회차 최대 3번, G2(n) = G2
        per_post = {}
        for r in record.assignments:
            if (c.night_type in (NightType.N1, NightType.N2) and r.slot.index == 0
                    and r.employee_id == managers[0]):
                continue                                 # 평일 시작 18시 관리자 L3는 표기만(6-1) → 세지 않음
            if r.displayed_assignment.kind == K.POST:
                key = (r.employee_id, r.displayed_assignment.label.partition("(")[0])
                per_post[key] = per_post.get(key, 0) + 1
        for (p, post), n in sorted(per_post.items()):
            check(n <= 3, "H-17", f"Same post more than three times {p}/{post}/{n}")
    # 6-2-1 [하드, 2026-10-05]: 주말 시작(N3/N4) 통제A(관리자대행 아님) 18시 휴게 고정. 재편성은 LOCK 과거라 보지 않는다.
    if rules_v220 and not reoptimization and c.night_type in (NightType.N3, NightType.N4) and managers == ["A"]:
        first = next((r for r in record.assignments if r.employee_id == "A" and r.slot.index == 0), None)
        check(first is not None and first.displayed_assignment.label == "휴게"
              and first.actual_post_or_work_type.label == "휴게", "6-2-1", "Weekend-start manager A must rest at 18:00")
    # 8-10 [하드, 2026-10-05]: 통제A(관리자대행 아님) 04시 보안실 대기 금지·차단봉 철수 불참. 재편성은 LOCK 과거라 보지 않는다.
    if rules_v220 and not reoptimization and managers == ["A"]:
        for r in record.assignments:
            if r.employee_id == "A":
                check(not r.barrier_remove_flag, "8-10", "Manager A must not remove the barrier")
                if r.slot.index == 10:
                    check(r.displayed_assignment.label != "보안실 대기", "8-10", "Manager A 04:00 rest must be 휴게, not standby")
                    check(r.displayed_assignment.label != "I1", "8-10", "Manager A must not be 04:00 I1 (rulebook 8-6/15-0)")
    # H-18 [하드, 2026-10-05]: 하루 전체 근무하는 일반근무자끼리 실근무 차이 최대 1시간 (실제 모드 표 기준).
    # 유도리 다시 계산 표(0-2-1 판정용)는 서비스가 work_spread=False로 검사한다.
    if rules_v220 and work_spread:
        whole = {a.employee_id for a in present if a.is_general_worker and not a.acts_as_manager
                 and all(a.is_available(t) for t in range(14))}
        worked = Counter()
        for r in record.assignments:
            if r.employee_id in whole:
                worked[r.employee_id] += r.actual_work_time_value
        if len(whole) >= 2:
            totals = [worked[p] for p in whole]
            check(max(totals) - min(totals) <= 1, "H-18", f"General actual work spread over one hour {sorted(worked.items())}")
    # 8-11 [하드, 2026-10-05]: 당일 관리자 18시·07시 실근무 없음. N1/N3 07시 가용 일반근무자 4명(8-3-1)이면 07시 예외.
    if rules_v220:
        from datetime import timedelta
        from .calendar_info import holiday_name, is_off_day
        if not is_off_day(c.shift_start_date + timedelta(days=1)):
            locked_south = set(locked_cells)
            for a in c.attendance:
                if not a.present:continue
                south_slots={r.slot.index for r in record.assignments if r.employee_id==a.employee_id
                             and r.displayed_assignment.label in {'G2','G3','G2(1)'}}
                for slot in range(13):
                    if slot not in south_slots or slot+1 not in south_slots:continue
                    # 2026-10-18 사용자 확정: 결원 2명 구간 예외 삭제
                    check((a.employee_id,slot) in locked_south and (a.employee_id,slot+1) in locked_south,
                          '5-3-1',f'{a.employee_id}/{slot}: 다음날 평일 남문 2시간 연속 금지')
        next_holiday = holiday_name(c.shift_start_date + timedelta(days=1))
        four_profile = (c.partial_vacancy_profile or c.flexible_from_slot is not None
                        or 7 - len(present) == 2)
        # 독립 검사: 토·일·법정·대체공휴일 포함, 그날 06시 관리자(통제A 또는 준호 대행) — 2026-10-13 대행 포함.
        # 중도 인계 뒤에는 관리자 줄("A")을 준호가 이어서 서므로 같은 줄을 본다. LOCK 과거 제외.
        if is_off_day(c.shift_start_date + timedelta(days=1)) and managers:
            locked = set(locked_cells)
            boss06 = managers[0]
            for row in record.assignments:
                if row.employee_id == boss06 and row.slot.index == 12 and (boss06, 12) not in locked:
                    check(row.displayed_assignment.label != "G1" and row.actual_post_or_work_type.label != "G1",
                          "8-13", "Next holiday: manager (A or proxy) must not work G1 at 06:00")
        if next_holiday and four_profile:
            boss = managers[0]
            for r in record.assignments:
                if (r.employee_id == boss and r.slot.index in (12, 13)
                        and (not reoptimization or c.flexible_from_slot is None or r.slot.index >= c.flexible_from_slot)):
                    check(r.displayed_assignment.label in ("휴게", "보안실 대기") and r.actual_work_time_value == 0,
                          "8-12", "Next holiday: vacancy-2 manager 06/07 must rest or standby")
    if rules_v220 and not reoptimization:
        boss = managers[0]
        four_at_07 = (c.night_type in (NightType.N1, NightType.N3)
                      and sum(a.is_available(13) for a in present if a.is_general_worker and not a.acts_as_manager) == 4)
        for r in record.assignments:
            if r.employee_id == boss and (r.slot.index == 0 or (r.slot.index == 13 and not four_at_07)):
                check(r.actual_work_time_value == 0, "8-11", f"Manager first/last slot must be no work {boss}/{r.slot.index}")
    for post, lo, hi, state in (c.post_operations or ()):
        check(state in _ALLOWED_OPERATIONS.get(post, set()) and 0 <= lo <= hi <= 13,
              "유도리 운영", f"고를 수 없는 포스트 운영 {post} {lo}~{hi} {state}")
    expected_mode = Mode.FLEXIBLE if profile_absence == 2 and c.requested_mode == Mode.FM else c.requested_mode
    check(c.effective_mode == expected_mode, "§0", "Incorrect effective mode")
    if c.requested_mode != expected_mode:
        check(bool(c.mode_change_reason), "§0-4", "Automatic switch reason missing")
    manager = managers[0]
    people = general + [manager]
    # 15-0 차단봉 고정 담당은 2026-10-05 야간부터 (Validator 쪽 기준일, Solver 상수와 따로 적음)
    barrier_v2 = c.shift_start_date >= date(2026, 10, 5)
    barrier_single = c.shift_start_date >= date(2026, 10, 9)
    installer_post = ("G2" if profile_general_count >= 5 else "I1") if rules_v218 else ("G2" if headcount >= 5 else "I1")
    if switch is not None and switch <= 2:
        installer_post = "I1"
    if c.night_type in (NightType.N3, NightType.N4):   # §10-4: N3/N4 설치는 20시 I1 + 보안실 대기
        installer_post = "I1"
    attendance_by_id = {a.employee_id: a for a in present}
    partial_general = {p for p in general if sum(attendance_by_id[p].is_available(t) for t in range(14)) < 14}
    # 미리 정한 통제A 반차의 준호 대행(긴급 재편성 제외, 2026-10-18): 준호 하루 = 자기 줄 + 대행한 관리자 자리
    proxy_handover = (rules_v220 and manager == "A" and "6" in partial_general
                      and (manager_a_start_slot > 0 or manager_a_end_slot < 14))   # 반차·긴급 이탈 승계 모두
    planned_half_proxy = proxy_handover and not reoptimization
    late_half_proxy = planned_half_proxy and manager_a_start_slot == 0
    leaver_slots = {t for p, t in emergency_leaver_cells if p == manager}
    # H-09-1 미리 정한 반차자 (계획: 반차자 전원 / 재편성: 서비스가 넘긴 원래 반차자만)
    half_day = ((partial_general if half_day_ids is None and not reoptimization
                 else set(half_day_ids or ()) & partial_general) if rules_v220 else set())
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
    # 5-7 추가 남문: 원래 남문이 없는 시간(주말 시작 18~20시, 다음날 주말 06·07시)에만, G2 1명(통제 포함 누구나)
    extra_south = set(c.extra_south_slots)
    for t in extra_south:
        allowed = (t <= 2 and c.night_type in (NightType.N3, NightType.N4)) or \
                  (t >= 12 and c.night_type in (NightType.N2, NightType.N4))
        check(allowed and t not in south, "§5-7", f"Extra south gate outside closed hours {t}")
        south[t] = {"G2": 1}
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
            if barrier_v2:                                 # 15-0: 설치 G2·I1·대기, 철수 I1 (모드 무관)
                allowed = (r.barrier_install_flag and label in (("G2", "I1") if barrier_single else ("G2", "I1", "보안실 대기"))
                           or r.barrier_remove_flag and label == "I1")
            else:
                allowed = label == "보안실 대기" if slot_mode(t) == Mode.FM else (
                    r.barrier_install_flag and label in (installer_post, "보안실 대기") or r.barrier_remove_flag and label == "I1")
            check(allowed, "§10/§11", f"Invalid barrier worker {p}/{t}/{label}")
            if label == "보안실 대기":                     # 대기자가 한 차단봉만 피로도 1 (포스트 겸임은 원래 회계)
                actual_kind = K.BARRIER_ONLY
                actual_label = "barrier_install" if r.barrier_install_flag else "barrier_remove"
                posture, fatigue, work, rest = None, 1, 0, 0   # 2026-10-04: 실근무는 포스트·순찰만 (차단봉 제외)
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
    # 긴급 반차 통제A가 빠지기 전(LOCK 구간)에 이미 실휴게 2시간 이상이면 남은 칸 연속근무 규칙 제외 (2026-10-18)
    leaver_free = bool(leaver_slots) and sum(facts[manager, t]["rest"] for t in range(min(leaver_slots or {0}))) >= 2
    # 표시·운영으로 독립 재계산한 실휴게 사용. 근무불가는 rest=0.
    if rules_v220:
        locked = set(locked_cells)
        for pid in people:
            if pid == "A" or (pid == "6" and (manager == "6" or manager_a_end_slot <= 13)):
                continue
            cells = [("A" if pid == "6" and t >= manager_a_end_slot else pid, t)
                     for t in (11, 12, 13)]
            if all(cell in locked for cell in cells):
                continue
            check(sum(facts[cell]["rest"] for cell in cells) <= 2,
                  "H-19", f"Non-A worker must not rest all of 05/06/07: {pid}")
    for t in range(14):
        labels = Counter(facts[p, t]["label"] for p in people if facts[p, t]["label"] in post_labels)
        expected = Counter({"G1": 1, "L3": 1, "I1": 1, **south.get(t, {})})
        check(labels == expected, "H-02/§5", f"Post coverage mismatch at {t}")
        for label in south.get(t, {}):
            if t in extra_south:
                continue                                 # 추가 남문은 통제 포함 누구나 (일반근무자 인원 고정 없음)
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
    elif headcount == 5 and not manager_is_proxy and planned_half_proxy and absence_count == 1:
        # 14-2 예외 [하드, 2026-10-18 사용자 확정]: 결원 1명 + 미리 정한 통제A 반차 → 준호 0회(관리자 자리 순찰만),
        # 나머지 일반근무자 정확히 1명 2회(14-3: 전반부·후반부 1회씩)
        others = [p for p in general if p != "6"]
        check(patrol_counts[manager] == 1 and patrol_counts["6"] == 0
              and sorted(patrol_counts[p] for p in others) == [1, 1, 1, 2], "§14-2/14-3", "Half-day proxy patrol exception distribution")
        for p in others:
            for half in ((3, 4, 5), (7, 8, 9)):
                check(sum(facts[p, t]["kind"] == K.PATROL for t in half) <= 1, "§14-3", f"Patrol half distribution {p}")
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
            def leaver_window(start, n):
                return p == manager and leaver_free and bool(set(range(start, start + n)) & leaver_slots)
            for start in range(10):
                check(leaver_window(start, 5) or not all(counted[start:start+5]), "H-08", f"Five continuous work slots {p}/{start}")
            for start in range(11):
                check(leaver_window(start, 4) or not all(counted[start:start+4]) or any(x["work"] == 1 and x["posture"] == Posture.SEATED for x in f[start:start+4]), "H-08", f"Four hours without seated work {p}/{start}")
        else:
            check(not all(x["continuous"] for x in f[10:14]), "H-08", f"04–07 continuous work {p}")
        if any(attendance_by_id[p].is_available(t) for t in (0, 1, 2)):
            check(any(x["meal"] for x in f[:3]), "H-10", f"No meal {p}")
        protected_ok = []
        locked_rest_p = sum(f[t]["rest"] for t in range(14) if (p, t) in set(locked_cells))
        leaver_left = sum(1 for q, _ in emergency_leaver_cells if q == p)
        if p in half_day and leaver_left:                   # 긴급 반차·이탈자: 채울 수 있는 만큼 2시간 이상 (10/18)
            check(sum(x["rest"] for x in f) >= min(2, locked_rest_p + leaver_left), "H-09-1",
                  f"Leaving worker needs two rest hours {p}")
        elif p in half_day:                                 # H-09-1: 미리 정한 반차자 휴게 정확히 2시간 (10/18)
            rest_p = sum(x["rest"] for x in f)
            check(2 <= rest_p <= max(2, locked_rest_p), "H-09-1", f"Half-day worker needs exactly two rest hours {p}/{rest_p}")
        leaving_manager = p == manager and bool(leaver_slots)   # 긴급 반차 통제A도 반차자처럼 (2026-10-18)
        if leaving_manager:
            check(sum(f[t]["rest"] for t in range(max(leaver_slots) + 1))
                  >= min(2, locked_rest_p + len(leaver_slots)), "H-09-1", f"Leaving manager needs two rest hours {p}")
        for t in patrol_slots:
            if f[t]["kind"] == K.PATROL and (p in half_day or leaving_manager):
                # H-09-1: 반차자 순찰 후 휴게는 하드 아님. 입식→순찰→입식만 금지
                if f[t - 1]["work"] == 1 and f[t - 1]["posture"] == Posture.STANDING:
                    check(f[t + 1]["work"] == 0 or f[t + 1]["posture"] == Posture.SEATED,
                          "H-11-immediate-recovery", f"Standing-patrol-standing {p}/{t}")
                continue
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
                    def full_rest(j):
                        return (f[j]["post_rest"] and f[j]["work"] == 0 and not by[p, j].barrier_install_flag
                                and not by[p, j].barrier_remove_flag and (slot_mode(j) != Mode.FM or f[j]["label"] == "휴게"))
                    # 2026-10-18 사용자 확정: 긴급 재편성일 때만 순찰 뒤 회복은 가능하면 지킬 규칙(Solver가 최소화) → 오류로 보지 않음.
                    # 다만 순찰 직후 쉬는 칸이면 '휴게' 표기(대기 아님)는 그대로 검사.
                    soft_recovery = rules_v220 and reoptimization
                    if rules_v220 and p == "A" and managers == ["A"] and t == 3 and f[2]["work"] == 0:
                        # H-12-1 (2026-10-05): 20시 실근무 없는 통제A는 22·23시 중 1칸만 휴게여도 된다
                        if not soft_recovery:
                            check(full_rest(4) or full_rest(5), "H-12-1", f"Manager A needs one rest at 22/23 {p}")
                    else:
                        for j in (t + 1, t + 2):
                            rested = f[j]["post_rest"] and f[j]["work"] == 0 and not by[p, j].barrier_install_flag and not by[p, j].barrier_remove_flag
                            if not soft_recovery:
                                check(rested, "H-11", f"Post patrol rest {p}/{j}")
                            if slot_mode(j) == Mode.FM and (not soft_recovery or rested):
                                check(f[j]["label"] == "휴게", "user-display", f"Explicit post patrol rest {p}/{j}")
                    protected_ok.append(True)
        if rules_v220 and protected_ok and not reoptimization:   # 긴급 재편성은 가능하면 지킬 규칙(10/18)
            check(any(protected_ok), "H-11-2", f"No protected patrol recovery {p}")
        check(not (any(by[p, t].barrier_install_flag for t in range(14)) and any(by[p, t].barrier_remove_flag for t in range(14))), "§15-2", f"Install/remove overlap {p}")
    installers = [r for r in record.assignments if r.barrier_install_flag]
    removers = [r for r in record.assignments if r.barrier_remove_flag]
    if barrier_v2:
        # 15-0 (2026-10-05): 20시 G2 운영이면 G2+대기, 아니면 I1+대기 / 04시 철수는 I1 근무자 1명 / 통제A 불참
        expect = Counter(["G2" if "G2" in south.get(2, {}) else "I1"] + ([] if barrier_single else ["보안실 대기"]))
        check(Counter(r.displayed_assignment.label for r in installers) == expect, "15-0",
              f"Barrier installers must be {dict(expect)}")
        check([r.displayed_assignment.label for r in removers] == ["I1"], "15-0", "Barrier removal must be the 04:00 I1")
        check(all(by[p, 10].barrier_remove_flag for p in people if by[p, 10].displayed_assignment.label == "I1"),
              "15-0", "04:00 I1 must remove the barrier")
        if managers == ["A"] and not reoptimization:
            check(not any(r.employee_id == "A" for r in installers + removers), "15-0", "Manager A takes no barrier duty")
    else:
        check(len(installers) == (1 if slot_mode(2) == Mode.FM else 2) and len(removers) == 1, "§10/§11", "Barrier staffing count")
    if slot_mode(2) == Mode.FLEXIBLE and not barrier_v2:
        check(Counter(r.displayed_assignment.label for r in installers) == Counter([installer_post, "보안실 대기"]), "§10-4", "Flexible installer composition")
    if refinement:
        for t in range(14):
            count = sum(facts[p, t]["label"] == "보안실 대기" for p in people)
            if rules_v26:
                if t in (2,10):
                    check(count >= 1, "H-16", f"Missing required standby {t}")
                if rules_v212 and t == 10:
                    check(count == 1, "H-16", f"04 standby count must be one, got {count}")
                if rules_v212 and t == 2 and barrier_v2:
                    check(count == 1, "H-16", f"20 standby count must be one (2026-10-05~), got {count}")
                elif rules_v212 and t == 2:
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
        # (옛 버전용) 04 I1 선호는 검증 오류로 보지 않았다. v2.20은 통제A 04시 I1 금지(8-10 블록)로 대체.
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
                    limit = 3 if rules_v220 else 2
                    check(0 <= p_fatigue - a_fatigue <= limit, "8-4-2", f"A fatigue must be 0-{limit} below general: {p}/{p_fatigue}/{a_fatigue}")
                else:
                    check(abs(p_fatigue - a_fatigue) <= 4, "8-4-2", f"A/general fatigue gap over four points: {p}/{p_fatigue}/{a_fatigue}")
        def proxy_total(key):
            k = manager_a_start_slot or manager_a_end_slot
            own, seat = (range(k, 14), range(k)) if manager_a_start_slot else (range(k), range(k, 14))
            return sum(facts["6", t][key] for t in own) + sum(facts[manager, t][key] for t in seat)
        full_fatigue = [sum(facts[p, t]["fatigue"] for t in range(14)) for p in general if p not in partial_general]
        if planned_half_proxy:
            # [하드, 2026-10-18 사용자 확정] 관리자 승계: 준호 순찰은 관리자 자리의 21시 상층 1회뿐, 자기 줄 순찰 금지
            k = manager_a_start_slot or manager_a_end_slot
            for t in (range(k, 14) if manager_a_start_slot else range(k)):
                check(facts["6", t]["kind"] != K.PATROL, "H-12/§14-1", f"Half-day proxy patrols only as manager: 6/{t}")
        # [하드, 2026-10-18 사용자 확정] 통제A 긴급 반차·이탈: 빠지기 전 남은 칸은 I1 없이 근무.
        # 이미 실휴게 2시간 이상이면 연속근무 규칙 제외(최대한 근무는 Solver 목표), 아니면 4연속 근무 안의 입식 3연속 금지.
        if leaver_slots:
            for t in sorted(leaver_slots):
                check(facts[manager, t]["label"] != "I1", "긴급반차-통제A근무", f"Leaving manager I1 before leaving: {t}")
            if not leaver_free:
                st = [facts[manager, t]["work"] == 1 and facts[manager, t]["posture"] == Posture.STANDING for t in range(14)]
                wk = [facts[manager, t]["work"] == 1 for t in range(14)]
                for t in range(12):
                    if {t, t + 1, t + 2} & leaver_slots and all(st[t:t + 3]):
                        check(not ((t > 0 and wk[t - 1]) or (t + 3 < 14 and wk[t + 3])), "긴급반차-통제A근무",
                              f"Leaving manager standing triple inside a four-hour run: {t}")
        if proxy_handover and full_fatigue and reoptimization:
            # [하드, 2026-10-18 사용자 확정] 긴급 이탈 승계면 준호 하루 피로도 = 일반근무자 중 최저 (동점 최저 허용)
            check(proxy_total("fatigue") <= min(full_fatigue), "준호-최저피로도",
                  f"Emergency proxy fatigue must be the lowest: {proxy_total('fatigue')}/{min(full_fatigue)}")
        elif proxy_handover and full_fatigue:
            # [하드, 2026-10-18 사용자 확정] 통제A 반차면 준호 하루 피로도 < 온전 출근 일반근무자 최고 (동점 최고 금지)
            check(proxy_total("fatigue") < max(full_fatigue), "준호-최고피로도",
                  f"Half-day proxy fatigue must be below the top general: {proxy_total('fatigue')}/{max(full_fatigue)}")
        # 2026-10-18 사용자 확정: 후반부 반차의 준호 하루 합계(자기 18~00시 + 대행 01~07시)에 통제A와 같은 H-15·8-4-2.
        if late_half_proxy:
            for p in general:
                if p in partial_general:
                    continue
                work = sum(facts[p, t]["work"] for t in range(14))
                if not manager_vacancy_policy:
                    check(abs(work - proxy_total("work")) <= 2, "H-15", f"Late-half proxy/general work gap over two hours: {p}/{work}/{proxy_total('work')}")
                if headcount in (5, 6) and profile_absence < 2 and switch is None:
                    p_fatigue = sum(facts[p, t]["fatigue"] for t in range(14))
                    check(0 <= p_fatigue - proxy_total("fatigue") <= 3, "8-4-2",
                          f"Late-half proxy fatigue must be 0-3 below general: {p}/{p_fatigue}/{proxy_total('fatigue')}")
        for p in people:
            visits = sum(facts[p, t]["label"] in ("G2", "G3") for t in range(3))
            check(visits <= (0 if p == manager else 1), "H-14", f"Evening south gate assignment: {p}/{visits}")
    return errors
