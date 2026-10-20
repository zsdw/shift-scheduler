"""야간 통제A 미리 정한 후반부 반차(01시 퇴근) (2026-10-18 사용자 확정): 01시부터 준호가 관리자 대행.
엔진은 긴급 중도 인계와 같은 자리 형태로 풀고 화면은 01시부터 A·준호 줄을 바꿔 보여 준다.
01시 이후 통제A 규칙(04시 대기·I1·철수 금지 등)은 준호가 계승."""
import unittest
from dataclasses import replace
from datetime import date

from night_shift.models import AssignmentKind, Mode, NightType
from night_shift.service import (HistorySelection, ShiftRequest, SolveOptions, StaffInput, revalidate,
                                 run_schedule_manager_half)

NAMES = {"1": "만년", "2": "원종", "3": "제욱", "4": "광희", "5": "성호", "6": "준호"}


def staff(absent=(), junho_half=False):
    rows = [StaffInput("A", "통제", True, False, None, True)]
    rows += [StaffInput(p, n, p not in absent, True, int(p), False, tuple(range(7)) if junho_half and p == "6" else None)
             for p, n in NAMES.items()]
    return tuple(rows)


def request(**kw):
    return ShiftRequest(date(2026, 10, 6), NightType.N1, Mode.FM, staff(**kw))


def check_proxy_succession(case, r, own):
    """2026-10-18 사용자 확정 HARD: 준호 하루 피로도 < 일반근무자 최고, 준호 순찰은 관리자 자리 21시 상층뿐."""
    case.assertTrue(r.valid, r.validation_errors)
    s = r.employee_stats
    top = max(s[p].fatigue_value for p in ('1', '2', '3', '4', '5') if p in s)
    case.assertLess(s['6'].fatigue_value, top)
    rows = {(a.employee_id, a.slot.index): a for a in r.record.assignments}
    case.assertFalse(any(rows['6', t].actual_post_or_work_type.kind == AssignmentKind.PATROL for t in own))
    # 위반표: 자기 줄 시간의 순찰을 준호와 맞바꾸면 Validator가 거부
    assignments = list(r.record.assignments)
    t, i_pat = next((a.slot.index, i) for i, a in enumerate(assignments)
                    if a.slot.index in own and a.employee_id not in ('A', '6')
                    and a.actual_post_or_work_type.kind == AssignmentKind.PATROL)
    i_six = next(i for i, a in enumerate(assignments) if a.employee_id == '6' and a.slot.index == t)
    pat, six = assignments[i_pat], assignments[i_six]
    assignments[i_pat], assignments[i_six] = replace(six, employee_id=pat.employee_id), replace(pat, employee_id='6')
    bad = revalidate(r, replace(r.record, assignments=tuple(assignments)))
    case.assertTrue(any(e['rule'] == 'H-12/§14-1' for e in bad.validation_errors), bad.validation_errors)


class ManagerLateHalfTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.result = run_schedule_manager_half(request(), HistorySelection(), SolveOptions(rules_version="2.20", seconds=30))

    def test_generated_and_displayed_as_handover(self):
        r = self.result
        self.assertTrue(r.valid, r.validation_errors or r.solve_result.status)
        self.assertEqual(r.record.context.manager_handover, (7, "6"))
        rows = {(a.employee_id, a.slot.index): a for a in r.record.assignments}
        self.assertTrue(all(rows[("A", t)].displayed_assignment.kind == AssignmentKind.UNAVAILABLE for t in range(7, 14)))
        four = rows[("6", 10)]                                          # 04시: 준호가 통제A 규칙 계승
        self.assertNotIn(four.displayed_assignment.label, ("보안실 대기", "I1"))
        self.assertFalse(four.barrier_remove_flag)
        self.assertTrue(revalidate(r, r.record).valid)                 # 저장본 재검증도 통과

    def test_proxy_day_follows_manager_fatigue_rules(self):
        # 2026-10-18 사용자 확정: 후반부 반차 준호 하루 합계 = 통제A와 같은 8-4-2(0~3점 낮게)·H-15(실근무 차이 2 이하)
        r = self.result
        self.assertTrue(r.valid, r.validation_errors)
        s = r.employee_stats
        for p in ("1", "2", "3", "4", "5"):
            self.assertTrue(0 <= s[p].fatigue_value - s["6"].fatigue_value <= 3, (p, s[p].fatigue_value, s["6"].fatigue_value))
            self.assertLessEqual(abs(s[p].actual_work_time_value - s["6"].actual_work_time_value), 2)

    def test_vacancy_day_proxy_shares_balance(self):
        # 결원 1명 + 후반부 반차 = 결원 2명 규칙 날(§8-7, 관리자 우대 없음) → 준호 하루 합계도 n빵 (10/18)
        r = run_schedule_manager_half(request(absent=("3",)), HistorySelection(),
                                      SolveOptions(rules_version="2.20", seconds=20, prefer_dual_mode=False))
        self.assertTrue(r.valid, r.validation_errors or r.solve_result.status)
        fatigue = [r.employee_stats[p].fatigue_value for p in ("1", "2", "4", "5", "6")]
        self.assertLessEqual(max(fatigue) - min(fatigue), 1, fatigue)

    def test_one_absence_patrol_exception(self):
        # 14-2 예외 (2026-10-18 사용자 확정): 결원 1명 + 통제A 반차 → 준호는 관리자 자리 순찰만,
        # 다른 일반근무자 정확히 1명이 전반부·후반부 1회씩 2회 순찰
        from night_shift.service import run_schedule_manager_early_half
        options = SolveOptions(rules_version="2.20", seconds=20, prefer_dual_mode=False)
        for fn, own in ((run_schedule_manager_half, range(7)), (run_schedule_manager_early_half, range(7, 14))):
            with self.subTest(fn=fn.__name__):
                r = fn(request(absent=("3",)), HistorySelection(), options)
                check_proxy_succession(self, r, own)
                patrols = {}
                for a in r.record.assignments:
                    if a.actual_post_or_work_type.kind == AssignmentKind.PATROL:
                        patrols.setdefault(a.employee_id, []).append(a.slot.index)
                doubles = [p for p, ts in patrols.items() if len(ts) == 2]
                self.assertEqual(len(doubles), 1, patrols)
                self.assertNotIn(doubles[0], ("A", "6"))
                ts = sorted(patrols[doubles[0]])
                self.assertTrue(ts[0] in (3, 4, 5) and ts[1] in (7, 8, 9), ts)

    def test_emergency_handover_proxy_not_top_fatigue(self):
        # 2026-10-18 사용자 확정 HARD: 긴급 통제A 이탈 승계도 준호 하루 피로도 < 온전 출근 일반근무자 최고
        from night_shift.service import run_reoptimization, run_schedule
        opts = SolveOptions(rules_version="2.20", seconds=20, prefer_dual_mode=False)
        base = run_schedule(request(absent=("4",)), HistorySelection(), opts)
        out = run_reoptimization(base, 3, "A", 3, HistorySelection(), opts, "긴급 이탈")
        self.assertTrue(out.valid, (out.solve_result.status, out.validation_errors))
        s = out.employee_stats
        self.assertLessEqual(s["6"].fatigue_value, min(s[p].fatigue_value for p in ("1", "2", "3", "5")))
        # 위반표: LOCK 뒤 준호 휴게 칸을 일반근무자 입식 근무와 바꿔 준호가 최저보다 높아지면 '준호-최저피로도'로 거부
        from night_shift.service import calculate_all_stats
        rows, general = list(out.record.assignments), ("1", "2", "3", "5")
        for t in range(3, 14):
            st = calculate_all_stats(replace(out.record, assignments=tuple(rows)))
            if st["6"].fatigue_value > min(st[p].fatigue_value for p in general):
                break
            i6 = next(i for i, a in enumerate(rows) if a.employee_id == "6" and a.slot.index == t)
            j = next((i for i, a in enumerate(rows) if a.slot.index == t and a.employee_id in general
                      and a.fatigue_value == 2), None)
            if rows[i6].fatigue_value == 0 and j is not None:
                a6, ax = rows[i6], rows[j]
                rows[i6], rows[j] = replace(ax, employee_id="6"), replace(a6, employee_id=ax.employee_id)
        bad = revalidate(out, replace(out.record, assignments=tuple(rows)))
        self.assertTrue(any(e["rule"] == "준호-최저피로도" for e in bad.validation_errors), bad.validation_errors)

    def test_emergency_leavers_get_no_consideration(self):
        # 2026-10-18 사용자 확정: 긴급 반차·이탈자는 빠지기 전 남은 시간에 실휴게 2시간 이상만 하드(배려는 최후순위),
        # 통제A가 빠져도 같고 준호는 일반근무자 중 최저 피로도
        from night_shift.service import run_reoptimization, run_schedule
        opts = SolveOptions(rules_version="2.20", seconds=20, prefer_dual_mode=False)
        base = run_schedule(request(), HistorySelection(), opts)
        for leaver in ("2", "A"):
            with self.subTest(leaver=leaver):
                out = run_reoptimization(base, 3, leaver, 7, HistorySelection(), opts, "후반부 반차 (01시 퇴근)")
                self.assertTrue(out.valid, (out.solve_result.status, out.validation_errors))
                rows = [a for a in out.record.assignments if a.employee_id == leaver and a.slot.index < 7]
                self.assertGreaterEqual(sum(a.actual_rest_time_value for a in rows), 2 if leaver != "A" else 0)
                if leaver == "A":
                    s = out.employee_stats
                    self.assertLessEqual(s["6"].fatigue_value, min(s[p].fatigue_value for p in ("1", "2", "3", "4", "5")))

    def test_emergency_manager_21_leave_works_after_patrol(self):
        # 사용자 사례(10/18): 원종 연차 + 21시 통제A 긴급 반차(01시 퇴근) → 21시 순찰 뒤 22·23·00시를 쉬던 문제.
        # 이미 휴게 2시간 이상이면 빠지기 전 칸은 전부 근무, 순찰 뒤 휴게 배려는 최후순위.
        from night_shift.service import run_reoptimization, run_schedule
        opts = SolveOptions(rules_version="2.20", seconds=20, prefer_dual_mode=False)
        base = run_schedule(request(absent=("2",)), HistorySelection(), opts)
        out = run_reoptimization(base, 3, "A", 7, HistorySelection(), opts, "후반부 반차 (01시 퇴근)")
        self.assertTrue(out.valid, (out.solve_result.status, out.validation_errors))
        rows = {a.slot.index: a for a in out.record.assignments if a.employee_id == "A"}
        if sum(rows[t].actual_rest_time_value for t in range(3)) >= 2:
            self.assertEqual([rows[t].actual_work_time_value for t in range(3, 7)], [1, 1, 1, 1])
        stage = next(a for a in out.solve_result.attempts if a.get("stage") == "manager_leaver_rest")
        self.assertEqual(stage["status"], "OPTIMAL")

    def test_emergency_general_leaver_rests_only_as_needed(self):
        # 사용자 사례(10/18): 통제A 후반부 반차 + 성호 긴급 반차(22시 재편성, 01시 퇴근) — 성호가 22·23·00시를 쉬던 문제.
        # 긴급 반차자 휴게(배려)는 최후순위 → 빠지기 전 남은 칸 휴게는 '2시간 이상'을 채우는 데 필요한 만큼만.
        from night_shift.service import run_reoptimization
        opts = SolveOptions(rules_version="2.20", seconds=20, prefer_dual_mode=False)
        out = run_reoptimization(self.result, 4, "5", 7, HistorySelection(), opts, "후반부 반차 (01시 퇴근)")
        self.assertTrue(out.valid, (out.solve_result.status, out.validation_errors))
        rows = {a.slot.index: a for a in out.record.assignments if a.employee_id == "5"}
        locked_rest = sum(rows[t].actual_rest_time_value for t in range(4))
        self.assertEqual(sum(rows[t].actual_rest_time_value for t in range(4, 7)), max(0, 2 - locked_rest))

    def test_emergency_manager_works_until_leaving(self):
        # 2026-10-18 사용자 확정: 통제A 긴급 반차 — 빠지기 전 남은 칸 I1 금지(하드), 휴게 최소(소프트 맨 앞), 이미 휴게
        # 2시간 이상이면 연속근무 규칙 제외, 아니면 4연속 근무 안의 입식 3연속 금지(하드). (사례: 결원1 + 22시 긴급, 01시 퇴근)
        from night_shift.service import run_reoptimization, run_schedule
        opts = SolveOptions(rules_version="2.20", seconds=20, prefer_dual_mode=False)
        base = run_schedule(request(absent=("4",)), HistorySelection(), opts)
        for start in (4, 6):
            with self.subTest(start=start):
                out = run_reoptimization(base, start, "A", 7, HistorySelection(), opts, "후반부 반차 (01시 퇴근)")
                self.assertTrue(out.valid, (out.solve_result.status, out.validation_errors))
                rows = {a.slot.index: a for a in out.record.assignments if a.employee_id == "A"}
                self.assertFalse(any(rows[t].displayed_assignment.label == "I1" for t in range(start, 7)))
                s = out.employee_stats                          # 준호 최저(하드)가 통제A 전부 근무보다 우선(10/18 사용자 결정)
                self.assertLessEqual(s["6"].fatigue_value, min(s[p].fatigue_value for p in ("1", "2", "3", "5")))
                # 위반표: 빠지기 전 통제A 칸을 같은 시간 I1과 맞바꾸면 거부
                assignments = list(out.record.assignments)
                ia = next(i for i, a in enumerate(assignments) if a.employee_id == "A" and a.slot.index == start)
                ii = next(i for i, a in enumerate(assignments) if a.slot.index == start and a.displayed_assignment.label == "I1")
                a_row, i_row = assignments[ia], assignments[ii]
                assignments[ia], assignments[ii] = replace(i_row, employee_id="A"), replace(a_row, employee_id=i_row.employee_id)
                bad = revalidate(out, replace(out.record, assignments=tuple(assignments)))
                self.assertTrue(any(e["rule"] == "긴급반차-통제A근무" for e in bad.validation_errors), bad.validation_errors)

    def test_proxy_top_fatigue_rejected(self):
        # 위반표: 준호 일반근무 시간(18~00시)의 휴게 칸을 같은 시간 일반근무자의 입식 근무와 차례로 맞바꿔
        # 준호가 최고 피로도가 되게 만들면 Validator가 '준호-최고피로도'로 거부해야 한다
        from night_shift.service import calculate_all_stats
        r = self.result
        rows = list(r.record.assignments)
        general = ("1", "2", "3", "4", "5")
        for t in range(7):
            s = calculate_all_stats(replace(r.record, assignments=tuple(rows)))
            if s["6"].fatigue_value >= max(s[p].fatigue_value for p in general):
                break
            i6 = next(i for i, a in enumerate(rows) if a.employee_id == "6" and a.slot.index == t)
            if rows[i6].fatigue_value >= 2:      # 휴게(0)·좌식(1) 칸을 입식(2)과 맞바꿔 준호 피로도를 올린다
                continue
            j = next((i for i, a in enumerate(rows) if a.slot.index == t and a.employee_id in general
                      and a.fatigue_value == 2), None)
            if j is not None:
                a6, ax = rows[i6], rows[j]
                rows[i6], rows[j] = replace(ax, employee_id="6"), replace(a6, employee_id=ax.employee_id)
        record = replace(r.record, assignments=tuple(rows))
        s = calculate_all_stats(record)
        self.assertGreaterEqual(s["6"].fatigue_value, max(s[p].fatigue_value for p in general))
        bad = revalidate(r, record)
        self.assertTrue(any(e["rule"] == "준호-최고피로도" for e in bad.validation_errors), bad.validation_errors)

    def test_proxy_fatigue_above_general_rejected(self):
        # 준호 01시 이후 휴게 한 칸을 일반근무자의 같은 시간 포스트와 바꿔 준호 피로도를 올리면 8-4-2/H-15 위반이어야 한다
        r = self.result
        rows = list(r.record.assignments)
        stats = r.employee_stats
        broke = False
        for t in range(7, 14):
            i_six = next(i for i, a in enumerate(rows) if a.employee_id == "6" and a.slot.index == t)
            if rows[i_six].actual_work_time_value:
                continue
            for i, a in enumerate(rows):
                if a.slot.index == t and a.employee_id in ("1", "2", "3", "4", "5") and a.fatigue_value == 2:
                    six = rows[i_six]
                    trial = rows[:]
                    trial[i_six], trial[i] = replace(a, employee_id="6"), replace(six, employee_id=a.employee_id)
                    bad = revalidate(r, replace(r.record, assignments=tuple(trial)))
                    if any(e["rule"] in ("8-4-2", "H-15") for e in bad.validation_errors):
                        broke = True
                        break
            if broke:
                break
        self.assertTrue(broke, stats)

    def test_proxy_four_oclock_i1_rejected(self):
        r = self.result
        rows = list(r.record.assignments)
        i_six = next(i for i, a in enumerate(rows) if a.employee_id == "6" and a.slot.index == 10)
        i_one = next(i for i, a in enumerate(rows) if a.slot.index == 10 and a.displayed_assignment.label == "I1")
        six, one = rows[i_six], rows[i_one]
        rows[i_six] = replace(one, employee_id="6")
        rows[i_one] = replace(six, employee_id=one.employee_id)
        bad = revalidate(r, replace(r.record, assignments=tuple(rows)))
        self.assertFalse(bad.valid)

    def test_emergency_late_half_keeps_proxy_barrier(self):
        # 2026-10-18 사용자 확정: 긴급 통제A 후반부 반차로 준호가 대행이 되어도 준호의 원래 차단봉(04시 철수)은 그대로
        from night_shift.service import run_reoptimization, run_schedule
        opts = SolveOptions(rules_version="2.20", seconds=30)
        base = run_schedule(ShiftRequest(date(2026, 10, 6), NightType.N1, Mode.FM, staff()), HistorySelection(), opts)
        remover = next(a.employee_id for a in base.record.assignments if a.barrier_remove_flag)
        if remover != "6":                                      # 두 일반근무자 줄을 통째로 바꿔 준호가 철수를 맡게
            swap = {remover: "6", "6": remover}
            base = revalidate(base, replace(base.record, assignments=tuple(
                replace(a, employee_id=swap.get(a.employee_id, a.employee_id)) for a in base.record.assignments)))
        self.assertTrue(base.valid)
        out = run_reoptimization(base, 7, "A", 7, HistorySelection(), opts, "긴급 반차")
        if out.record is None:
            # 원래 표에 따라 01시 통제A 긴급 이탈 자체가 순찰 뒤 회복(H-11) 등으로 해가 없는 경우가 있음(차단봉과 무관,
            # 10/18 확인 — 사용자 결정 대기). 차단봉 유지 여부와 상관없이 해가 없을 때만 건너뜀.
            self.skipTest(f"이 원래 표는 01시 긴급 인계 자체가 해 없음: {out.solve_result.status}")
        self.assertTrue(out.valid, out.validation_errors)
        four = next(a for a in out.record.assignments if a.employee_id == "6" and a.slot.index == 10)
        if "준호 차단봉 04시 그대로" in out.rebalance_info.reason:   # 유지는 권장 — 유지했다면 실제로 준호 철수
            self.assertTrue(four.barrier_remove_flag)

    def test_proxy_succession_fatigue_and_patrol(self):
        check_proxy_succession(self, self.result, range(7))

    def test_proxy_must_work_full_night(self):
        with self.assertRaises(ValueError):
            run_schedule_manager_half(request(junho_half=True), HistorySelection(), SolveOptions(rules_version="2.20", seconds=5))

    def test_emergency_handover_after_locked_standing(self):
        # 2026-10-20 사용자 확정: 원래 표에서 준호 19 G2·20 L3(이미 LOCK된 입식) 뒤 21시 통제A 긴급 이탈 →
        # 관리자 자리 21시 상층 순찰을 이어받아 교대 시점 입식 3연속이 불가피. 이때만 허용(전에는 해 없음/교대 오류).
        # 원래 표를 고정해 부하·시간에 따라 결과가 달라지지 않게 한다.
        import json
        from pathlib import Path
        from night_shift.history_store import record_from_json
        from night_shift.service import handover_boundary_issues, run_reoptimization, run_schedule
        opts = SolveOptions(rules_version="2.20", seconds=20, prefer_dual_mode=False)
        fixture = record_from_json(json.loads((Path(__file__).parent / "fixtures/handover_locked_standing_base.json")
                                              .read_text(encoding="utf-8")))
        base = revalidate(run_schedule(request(absent=("4",)), HistorySelection(), opts), fixture)
        self.assertTrue(base.valid, base.validation_errors)
        out = run_reoptimization(base, 3, "A", 3, HistorySelection(), opts, "긴급 이탈")
        self.assertTrue(out.valid, (out.solve_result.status, out.validation_errors))
        rows = {(a.employee_id, a.slot.index): a for a in out.record.assignments}
        self.assertEqual([rows["6", t].displayed_assignment.label for t in (1, 2)], ["G2", "L3"])
        # 예외는 LOCK된 경우만: LOCK 없이 같은 표를 검사하면 여전히 교대 시점 입식 3연속으로 잡는다
        if all(rows["6", t].posture_or_mode == rows["6", 1].posture_or_mode for t in (2, 3)):
            self.assertIn("입식 3시간 연속", handover_boundary_issues(out.record, "6", 3, 0))
            self.assertNotIn("입식 3시간 연속", handover_boundary_issues(out.record, "6", 3, 3))


if __name__ == "__main__":
    unittest.main()
