"""평일 주간근무표 (룰북 v0.7: 반차 없는 8~11인 고정틀, 반차 시 근근휴 HARD 편성, 통제A 17시 순찰 금지, 08시 번호순)."""
import tempfile
import unittest
from datetime import date

from night_shift.day_shift import (
    C_POSTS, CONTROL_SLOTS, DEFAULT_ROSTER, FIRST_ROW_ORDER, FIXED_TEMPLATES, TEMPLATE_OUTSIDE_PATROL, EDU, EDU_SLOTS, PATROL, PATROL_SLOTS, POSTS, REST, STANDBY,
    CORE, HALF_DAY_LEAVE, EMERGENCY_KINDS, DayPerson, day_findings, day_stats, emergency_advisories,
    emergency_candidates, fill_warnings, reoptimize_day,
    load_day, number_people, save_day, solve_day, strict_cycle_possible, validate_day,
)

DAY = date(2026, 10, 7)   # 수요일 주간


def people(statuses=None):
    statuses = statuses or {}
    return number_people([DayPerson(n, n, statuses.get(n, "출근")) for n in DEFAULT_ROSTER],
                         __import__("random").Random(7))


class DayShiftTests(unittest.TestCase):
    def solve(self, statuses=None, **kw):
        schedule, status = solve_day(DAY, people(statuses), seconds=20, **kw)
        self.assertIsNotNone(schedule, status)
        self.assertEqual(validate_day(schedule), [])
        return schedule

    def test_full_team_of_ten(self):
        s = self.solve()
        counts = [sum(c in POSTS for c in row) for row in s.grid.values()]
        self.assertLessEqual(max(counts) - min(counts), 1)
        for row in s.grid.values():
            self.assertLessEqual(sum(c in C_POSTS for c in row), 2)
            for t in range(8):   # 2 posts -> 1 off: no three posts in a row
                self.assertFalse(all(c in POSTS for c in row[t:t + 3]), row)
        self.assertIn(s.grid["준호"][0], (PATROL, REST, STANDBY))
        for t in range(10):
            staff = [row[t] for row in s.grid.values()].count(PATROL)
            self.assertEqual(staff + (s.control_patrol == t), 1 if t in PATROL_SLOTS else 0)
        self.assertEqual(set(s.shuttle), {0, 3, 5, 8})
        self.assertTrue(day_stats(s) and day_findings(s))

    def test_education_and_standby(self):
        s = self.solve()
        for t in range(10):
            column = [row[t] for row in s.grid.values()]
            if t in EDU_SLOTS:          # 10시·14시: 휴게자 전원 교육, 대기 없음
                self.assertNotIn(STANDBY, column)
                self.assertNotIn(REST, column)
                self.assertIn(EDU, column)
            else:
                self.assertNotIn(EDU, column)
                self.assertLessEqual(column.count(STANDBY), 1)
        standby = [row.count(STANDBY) for row in s.grid.values()]
        self.assertLessEqual(max(standby) - min(standby), 1)

    def test_half_days_and_leave(self):
        s = self.solve({"도운": "연차", "만년": "오후반차", "성욱": "오전반차"})
        self.assertEqual(s.grid["도운"], [None] * 10)
        morning = s.grid["만년"]
        self.assertEqual(morning[5:], [None] * 5)
        self.assertEqual([c in POSTS for c in morning[:5]], [True, True, False, True, True])
        self.assertEqual(morning[2], PATROL)                   # §13 정배: 오후반차(오전 근무) 10시 순찰
        self.assertEqual(s.grid["성욱"][:5], [None] * 5)
        self.assertEqual(s.grid["성욱"][7], PATROL)            # 오전반차(13시 출근) 15시 비포스트 턴도 순찰

    def test_one_and_half_absent_nobody_patrols_twice(self):
        s = self.solve({"도운": "연차", "준형": "오후반차"})          # 결원 1.5명
        self.assertLessEqual(max(row.count(PATROL) for row in s.grid.values()), 1)

    def test_small_team_drops_c_posts(self):
        s = self.solve({"도운": "연차", "준형": "연차", "용주": "연차"})
        c_hours = sum(1 for t in range(10) if any(row[t] in C_POSTS for row in s.grid.values()))
        self.assertLess(c_hours, 10)

    def test_regeneration_differs_and_validator_catches_errors(self):
        first = self.solve()
        second, _ = solve_day(DAY, list(first.people), seconds=20, exclude=[first.grid], seed=1)
        self.assertIsNotNone(second)
        diff = sum(a != b for pid in first.grid for a, b in zip(first.grid[pid], second.grid[pid]))
        self.assertGreaterEqual(diff, 12)
        broken = type(first)(first.day, first.people, {k: list(v) for k, v in first.grid.items()}, first.shuttle)
        pid = next(p for p, row in broken.grid.items() if row[1] in POSTS)
        broken.grid[pid][2] = broken.grid[pid][1]              # same post twice in a row
        rules = {e["rule"] for e in validate_day(broken)}
        self.assertIn("주간-4", rules)

    def test_strict_cycle_and_senior(self):
        s = self.solve({"도운": "연차", "만년": "오전반차"})   # 반차가 있으면 룰북 편성: 근근휴 HARD
        self.assertTrue(s.strict)
        self.assertIsNone(s.fixed_template)
        cycles = ("WWO" * 4, "WOW" * 4, "OWW" * 4)
        for pid, row in s.grid.items():
            text = "".join("W" if c in POSTS else "O" for c in row if c is not None)
            self.assertTrue(any(text == c[:len(text)] for c in cycles), (pid, row))
        senior = s.grid["준호"]
        self.assertNotIn(senior[0], POSTS)          # §21: 선임은 휴근근 시작
        self.assertNotIn(senior[9], POSTS)          # → 마지막 17시도 휴게성 타임

    def test_strict_cycle_possible_matches_fixed_templates(self):
        def team(n):
            return [DayPerson(f"p{i}", "준호" if i == 0 else f"p{i}", "출근") for i in range(n)]
        self.assertEqual([strict_cycle_possible(team(n)) for n in (7, 8, 9, 10, 11)],
                         [False, True, True, True, False])      # 11인 고정틀은 §3-2 완화

    def test_c2_only_when_c1_every_hour_and_standby_marking(self):
        s = self.solve()
        columns = [[row[t] for row in s.grid.values()] for t in range(10)]
        if any("C2" in col for col in columns):
            self.assertTrue(all("C1" in col for col in columns))
        for t, col in enumerate(columns):
            if t not in EDU_SLOTS and REST in col:
                self.assertEqual(col.count(STANDBY), 1)

    def test_control_patrols_once_before_anyone_patrols_twice(self):
        # 2026-10-02 형태: 준호 연차, 만년 오전반차 -> 휴근근 그룹이 08·11·14·17 순찰을 다 못 맡음
        s = self.solve({"준호": "연차", "만년": "오전반차"})
        self.assertTrue(s.strict)
        self.assertLessEqual(max(row.count(PATROL) for row in s.grid.values()), 1)
        self.assertIsNotNone(s.control_patrol)
        self.assertNotIn(s.control_patrol, CONTROL_SLOTS)

    def test_validator_rejects_v05_hard_violations(self):
        s = self.solve({"도운": "연차", "만년": "오전반차"})
        def copy():
            return type(s)(s.day, s.people, {k: list(v) for k, v in s.grid.items()}, dict(s.shuttle),
                           control=s.control, control_patrol=s.control_patrol, strict=s.strict,
                           fixed_template=s.fixed_template)
        broken = copy()                                   # 선임 08시 포스트
        jh = broken.grid["준호"]
        other = next(pid for pid, row in broken.grid.items() if row[0] == "G1")
        jh[0], broken.grid[other][0] = "G1", jh[0]
        rules = {e["rule"] for e in validate_day(broken)}
        self.assertIn("주간-21", rules)
        self.assertIn("주간-3", rules)
        broken = copy()                                   # 휴게자가 있는데 대기 없음
        t = next(t for t in range(10) if t not in EDU_SLOTS and STANDBY in [r[t] for r in broken.grid.values()])
        pid = next(p for p, r in broken.grid.items() if r[t] == STANDBY)
        broken.grid[pid][t] = REST
        self.assertIn("주간-8", {e["rule"] for e in validate_day(broken)})

    def test_full_house_uses_fixed_template(self):
        s = self.solve()                                  # 10인 전원 전일 출근 -> 고정틀 (§23)
        self.assertEqual(s.fixed_template, 10)
        numbers = {p.name: p.number for p in s.people}
        self.assertEqual(numbers["준호"], 8)              # 선임 자리: 08 순찰 → 17 휴게
        self.assertEqual(s.grid["준호"][0], PATROL)
        rows = FIXED_TEMPLATES[10]
        for p in s.people:
            got = [REST if c == STANDBY else c for c in s.grid[p.pid]]
            self.assertEqual(got, list(rows[p.number - 1]))
        broken = type(s)(s.day, s.people, {k: list(v) for k, v in s.grid.items()}, dict(s.shuttle),
                         control=s.control, fixed_template=None, strict=True)
        self.assertIn("주간-23", {e["rule"] for e in validate_day(broken)})   # 풀출근인데 고정틀 아님
        eleven = number_people([DayPerson(n, n, "출근") for n in DEFAULT_ROSTER + ("수호",)],
                               __import__("random").Random(3))
        s11, _ = solve_day(DAY, eleven, seconds=5)
        self.assertEqual(s11.fixed_template, 11)
        self.assertEqual(validate_day(s11), [])
        half, _ = solve_day(DAY, people({"만년": "오전반차"}), seconds=20)   # 반차가 있으면 고정틀 아님
        self.assertIsNone(half.fixed_template)
        self.assertEqual(validate_day(half), [])

    def test_eight_and_nine_without_half_days_use_template(self):
        # v0.7: 연차로 8·9인이 되어도 반차자가 없으면 통합 근무표 고정틀 그대로
        for statuses, size in (({"도운": "연차"}, 9), ({"도운": "연차", "준형": "연차"}, 8)):
            s = self.solve(statuses)
            self.assertEqual(s.fixed_template, size)
            jh = next(p for p in s.people if p.name == "준호")
            self.assertEqual(jh.number, 7)                   # 선임: 08 순찰 → 17 휴게 자리
            self.assertEqual(s.control_patrol, 3)            # 고정틀대로 11시 순찰은 통제A
            for p in s.people:
                if p.number:
                    got = [REST if c == STANDBY else c for c in s.grid[p.pid]]
                    for t, (a, b) in enumerate(zip(got, FIXED_TEMPLATES[size][p.number - 1])):
                        if a != b:
                            self.assertIn(t, TEMPLATE_OUTSIDE_PATROL[size])
                            self.assertEqual(a, PATROL)
        # 8인 14시 순찰(엑셀은 통제E)은 §7 순서대로 선임이 2회째로 맡음
        self.assertEqual(s.grid["준호"][6], PATROL)
        self.assertEqual(s.grid["준호"].count(PATROL), 2)

    def test_control_never_takes_last_patrol(self):
        for statuses in ({"준호": "연차", "만년": "오전반차"}, {"도운": "연차", "만년": "오후반차", "성욱": "오전반차"}):
            s = self.solve(statuses)
            self.assertNotEqual(s.control_patrol, 9)
            if s.control_patrol is not None:
                self.assertIn(s.control_patrol, (1, 3, 7))
        broken = type(s)(s.day, s.people, {k: list(v) for k, v in s.grid.items()}, dict(s.shuttle),
                         control=True, control_patrol=9, strict=s.strict)
        pid = next(p for p, row in broken.grid.items() if row[9] == PATROL)
        broken.grid[pid][9] = REST
        self.assertIn("통제A가 마지막 17시 순찰을 맡음 (금지)", [e["detail"] for e in validate_day(broken)])

    def test_first_row_numbered_g1_onwards(self):
        # v0.7 HARD: 08시는 번호 1→G1, 2→G2, 3→G3, 4→L1, 5→L2, 6→C1, 7→C2 순서
        for statuses in ({}, {"도운": "연차"}, {"도운": "연차", "준형": "연차"},
                         {"만년": "오전반차"}, {"도운": "연차", "만년": "오후반차", "성욱": "오전반차"}):
            s = self.solve(statuses)
            ordered = sorted((p for p in s.people if p.number), key=lambda p: p.number)
            self.assertEqual([p.number for p in ordered], list(range(1, len(ordered) + 1)))
            firsts = [s.grid[p.pid][0] for p in ordered]
            k = sum(f in POSTS for f in firsts)
            self.assertEqual(firsts[:k], list(FIRST_ROW_ORDER[:k]), statuses)
        a, b = ordered[0], ordered[1]                         # 번호만 바꿔치기하면 Validator가 잡아야 함
        swapped = tuple(type(a)(p.pid, p.name, p.status, {a.pid: b.number, b.pid: a.number}.get(p.pid, p.number))
                        for p in s.people)
        broken = type(s)(s.day, swapped, s.grid, dict(s.shuttle), control=s.control,
                         control_patrol=s.control_patrol, strict=s.strict, fixed_template=s.fixed_template)
        self.assertIn("주간-6", {e["rule"] for e in validate_day(broken)})

    # ---------------------------------------------------------------- §25 긴급 반차·이탈 재편성
    def emergency(self, statuses=None, start=3, kind=EMERGENCY_KINDS[0], pick=2, **kw):
        base = self.solve(statuses)
        who = emergency_candidates(base, start)[pick]
        leave = HALF_DAY_LEAVE if kind == EMERGENCY_KINDS[0] else start
        s, status = reoptimize_day(base, start, who.pid, leave, kind, seconds=10, **kw)
        self.assertIsNotNone(s, status)
        return base, who, s

    def assert_cycle_pattern(self, s, start):
        for pid, row in s.grid.items():
            on = ["W" if c in POSTS else "O" if c is not None else None for c in row]
            for t in range(9):
                if t + 1 >= start and on[t] == on[t + 1] == "O":
                    self.fail(f"{pid} {t} 휴 2칸 연속 {row}")
            for t in range(8):
                if t + 2 >= start and None not in on[t:t + 3]:
                    self.assertNotIn("".join(on[t:t + 3]), ("WWW", "OWO"), (pid, row))

    def test_emergency_half_day_locks_past_and_keeps_cycle(self):
        base, who, s = self.emergency(start=3)                 # 11시에 긴급 오후반차 (13시 퇴근)
        self.assertEqual(s.locked_through, 2)
        for pid in base.grid:                                   # LOCK: 08~10시 그대로
            self.assertEqual(s.grid[pid][:3], base.grid[pid][:3])
        self.assertEqual(s.grid[who.pid][5:], [None] * 5)
        self.assertEqual(validate_day(s), [])
        self.assert_cycle_pattern(s, 3)
        self.assertEqual(s.emergency["pid"], who.pid)
        self.assertTrue(any("긴급 재편성" in n for n in day_findings(s)))
        for t in range(3, 10):                                  # 사람이 충분하면 핵심 포스트·순찰은 그대로 채움
            column = [row[t] for row in s.grid.values()]
            for post in CORE:
                self.assertEqual(column.count(post), 1, (t, post))
        store = tempfile.mkdtemp()
        save_day(store, s)
        loaded = load_day(store, DAY)["schedule"]
        self.assertEqual(loaded.grid, s.grid)
        self.assertEqual(loaded.locked_through, 2)
        self.assertEqual(loaded.emergency, s.emergency)
        self.assertEqual(next(p for p in loaded.people if p.pid == who.pid).leave_from, HALF_DAY_LEAVE)
        self.assertEqual(validate_day(loaded), [])

    def test_emergency_leave_now_from_solver_base_and_regenerate(self):
        base, who, s = self.emergency({"만년": "오전반차"}, start=7, kind=EMERGENCY_KINDS[1])   # 15시 긴급 이탈
        self.assertEqual(s.grid[who.pid][7:], [None] * 3)
        self.assertEqual(validate_day(s), [])
        self.assert_cycle_pattern(s, 7)
        again, _ = reoptimize_day(base, 7, who.pid, 7, EMERGENCY_KINDS[1], seconds=10, exclude=[s.grid], seed=1)
        if again is not None:                                   # 남은 칸이 적으면 다른 해가 없을 수 있음
            self.assertNotEqual(again.grid, s.grid)
            self.assertEqual(validate_day(again), [])

    def test_emergency_only_cycle_is_hard(self):
        _, _, s = self.emergency(start=3)
        def copy():
            return type(s)(s.day, s.people, {k: list(v) for k, v in s.grid.items()}, dict(s.shuttle),
                           control=s.control, control_patrol=s.control_patrol, strict=s.strict,
                           locked_through=s.locked_through, emergency=dict(s.emergency))
        broken = copy()                                         # 미래 칸에 휴 2칸 연속 → HARD 위반
        pid, t = next((pid, t) for pid, row in broken.grid.items() for t in range(3, 9)
                      if row[t] in POSTS and row[t + 1] not in POSTS and row[t + 1] is not None)
        broken.grid[pid][t] = REST
        self.assertIn("주간-3", {e["rule"] for e in validate_day(broken)})
        soft = copy()                                           # 같은 포스트 연속은 강력 권장(HARD 아님)
        pid, t = next((pid, t) for pid, row in soft.grid.items() for t in range(3, 9)
                      if row[t] in CORE and row[t + 1] in CORE)
        other = next(q for q, row in soft.grid.items() if row[t + 1] == soft.grid[pid][t])
        soft.grid[pid][t + 1], soft.grid[other][t + 1] = soft.grid[other][t + 1], soft.grid[pid][t + 1]
        self.assertNotIn("주간-4", {e["rule"] for e in validate_day(soft)})
        self.assertIn("주간-4", {e["rule"] for e in emergency_advisories(soft)})
        self.assertIn("주간-4", {e["rule"] for e in validate_day(type(s)(
            s.day, s.people, soft.grid, dict(s.shuttle), control=s.control, control_patrol=s.control_patrol))})

    def assert_core_full(self, s):
        for t in range(10):
            column = [row[t] for row in s.grid.values()]
            for post in CORE:
                self.assertEqual(column.count(post) + (post in s.fill.get(t, {})), 1, (t, post, s.fill))

    def test_emergency_small_team_integrates_a_or_has_no_solution(self):
        # 사용자 2026-10-03: 미래 A/E 단독 메움 대신 A를 같은 근근휴 인원으로 추가한다.
        two_off = {"도운": "연차", "준형": "연차"}
        for control in (True, False):
            base, _ = solve_day(DAY, people(two_off), seconds=20, control=control)
            result, status = reoptimize_day(base, 2, "광희", 2, EMERGENCY_KINDS[1], seconds=20)
            if not control:
                self.assertIsNone(result)
                self.assertIn("INFEASIBLE", status)
                continue
            self.assertIsNotNone(result, status)
            self.assertEqual(validate_day(result), [])
            self.assertEqual(result.control_as_worker_from, 2)
            self.assertIn("A", result.grid)
            self.assertEqual(result.grid["A"][:2], [None, None])
            self.assertEqual(next(p for p in result.people if p.pid == "A").join_from, 2)
            for pid, row in base.grid.items():
                self.assertEqual(result.grid[pid][:2], row[:2])
            self.assertFalse(result.fill)
            self.assert_cycle_pattern(result, 2)
            self.assert_core_full(result)
            self.assertTrue(any("통제A" in n and "편입" in n for n in day_findings(result)))
            store = tempfile.mkdtemp()
            save_day(store, result)
            loaded = load_day(store, DAY)["schedule"]
            self.assertEqual(loaded.grid, result.grid)
            self.assertEqual(loaded.control_as_worker_from, 2)
            self.assertEqual(validate_day(loaded), [])

    def test_emergency_no_solution_when_even_a_and_e_cannot_fill(self):
        # v1.0 §27: 통제A·통제E로도 빈자리가 남으면 해 없음
        base, _ = solve_day(DAY, people({"도운": "연차", "준형": "연차"}), seconds=20)
        s, _ = reoptimize_day(base, 2, "광희", 2, EMERGENCY_KINDS[1], seconds=10)
        again, status = reoptimize_day(s, 3, "용주", 3, EMERGENCY_KINDS[1], seconds=10)
        self.assertIsNone(again)
        self.assertEqual(status, "INFEASIBLE")

    def test_validator_rejects_future_a_e_fills_after_policy_change(self):
        from dataclasses import replace
        base, _ = solve_day(DAY, people({"도운": "연차", "준형": "연차"}), seconds=20)
        result, status = reoptimize_day(base, 2, "광희", 2, EMERGENCY_KINDS[1], seconds=20)
        self.assertIsNotNone(result, status)
        for who in ("A", "E"):
            broken = replace(result, fill={2: {"G1": who}})
            self.assertIn("주간-27", {e["rule"] for e in validate_day(broken)})
        missing = {pid: list(row) for pid, row in result.grid.items()}
        pid, t = next((pid, t) for pid, row in missing.items() for t in range(2, 10) if row[t] == "G1")
        missing[pid][t] = REST
        self.assertIn("주간-2-1", {e["rule"] for e in validate_day(replace(result, grid=missing))})

    def test_control_absence_only_blanks_control_spots(self):
        # v0.9: 통제A 결근이어도 일반근무자 표는 그대로, 통제A 자리(11시 순찰 등)만 빈칸
        for statuses in ({"도운": "연차"}, {"만년": "오전반차"}):
            with_a = self.solve(statuses)
            without, _ = solve_day(DAY, list(with_a.people), seconds=20, control=False)
            self.assertEqual(validate_day(without), [])
            if with_a.fixed_template:
                self.assertEqual(without.grid, with_a.grid)
                self.assertEqual(without.control_patrol, with_a.control_patrol)
            self.assertTrue(any("통제A 결근" in n for n in day_findings(without)))

    def test_emergency_groups_rotate_and_spread(self):
        # v0.9 강력 권장: (G1)(G2·G3)(L1·L2) 묶음이 사람마다 고르게, 순서는 G1→G2→G3→L1→L2
        base, who, s = self.emergency(start=2)
        order = ("G1", "G2", "G3", "L1", "L2")
        follows = total = 0
        for row in s.grid.values():
            posts = [(t, c) for t, c in enumerate(row) if c in order and t >= 2]
            for (t1, a), (t2, b) in zip(posts, posts[1:]):
                if t2 - t1 <= 2:
                    total += 1
                    follows += order[(order.index(a) + 1) % 5] == b
        self.assertGreaterEqual(follows, total * 0.6, (follows, total))

    def test_fatigue_in_summary(self):
        s = self.solve()
        for row in day_stats(s):
            self.assertEqual(row["피로도"], 2 * row["G·L"] + row["C"] + row["순찰"])

    def test_storage_roundtrip(self):
        s = self.solve()
        store = tempfile.mkdtemp()
        save_day(store, s)
        loaded = load_day(store, DAY)["schedule"]
        self.assertEqual(loaded.grid, s.grid)
        self.assertEqual(loaded.shuttle, s.shuttle)
        self.assertTrue(loaded.control)
        self.assertEqual(loaded.control_patrol, s.control_patrol)
        self.assertEqual(loaded.strict, s.strict)
        self.assertEqual(loaded.fixed_template, s.fixed_template)


if __name__ == "__main__":
    unittest.main()
