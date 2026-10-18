"""2026-10-03 주간 순환·비포스트 전환·A 조건부 편입 회귀검증."""
import unittest
import tempfile
from datetime import date
from unittest.mock import patch
from ortools.sat.python import cp_model

from night_shift import day_shift as d

DAY = date(2026, 10, 7)


def team(n):
    return [d.DayPerson("준호" if i == 0 else f"p{i}", "준호" if i == 0 else f"p{i}", "출근") for i in range(n)]


class DayRotationPolicyTests(unittest.TestCase):
    def test_transition_validator_requires_nonpost_and_respects_lock(self):
        for before, after in (("G2", "G3"), ("L1", "L2")):
            row = [d.REST] * 10
            row[0:2] = [before, after]
            s = d.DaySchedule(DAY, (d.DayPerson("p", "p", "출근", 1),), {"p": row})
            self.assertIn("주간-28", {e["rule"] for e in d.validate_day(s)})
            for off in (d.REST, d.STANDBY, d.PATROL, d.EDU):
                s.grid["p"] = [before, off, after] + [d.REST] * 7
                self.assertNotIn("주간-28", {e["rule"] for e in d.validate_day(s)})
            s.grid["p"] = [before, after] + [d.REST] * 8
            s.emergency = {"start": 2}
            self.assertNotIn("주간-28", {e["rule"] for e in d.validate_day(s)})
            s.emergency = {"start": 1}
            self.assertIn("주간-28", {e["rule"] for e in d.validate_day(s)})

    def test_rotation_dominates_other_soft_penalties(self):
        m = cp_model.CpModel()
        second_g2, second_g3 = m.new_bool_var("G2"), m.new_bool_var("G3")
        m.add_exactly_one(second_g2, second_g3)
        def cell(pid, t, label):
            if t == 0:
                return int(label == "G1")
            return {"G2": second_g2, "G3": second_g3}.get(label, 0)
        work = lambda pid, t: 1
        closed = {t: 0 for t in d.SLOTS}
        cost = d._rotation_cost(m, ["p"], {"p": {0, 1}}, cell, work, closed, closed)
        solver, status = d._solve_priorities(m, cost, [1_000_000_000 * second_g2], 2, 0)
        self.assertIn(status, (cp_model.OPTIMAL, cp_model.FEASIBLE))
        self.assertEqual(solver.value(second_g2), 1)  # 다른 소프트가 아무리 커도 순환을 깨지 않음
        self.assertEqual(solver.value(cost), 0)

    def test_c_posts_are_optional_when_closed(self):
        people = (d.DayPerson("p", "p", "출근", 1),)
        s = d.DaySchedule(DAY, people, {"p": ["L2", d.REST, "G1"] + [None] * 7})
        self.assertEqual(d.rotation_advisories(s), [])
        s.grid["c"] = [None, None, "C1"] + [None] * 7
        s.people += (d.DayPerson("c", "c", "출근", 2),)
        self.assertEqual(len(d.rotation_advisories(s)), 1)
        s.grid["p"][2] = "C1"
        s.grid["c"][2] = None
        self.assertEqual(d.rotation_advisories(s), [])

    def test_seven_workers_use_a_as_ordinary_worker_and_roundtrip(self):
        result, status = d.solve_day(DAY, team(7), seconds=20)
        self.assertIsNotNone(result, status)
        self.assertEqual(d.validate_day(result), [])
        self.assertTrue(result.strict)
        self.assertIsNone(result.fixed_template)
        self.assertEqual(result.control_as_worker_from, 0)
        self.assertIn("A", result.grid)
        self.assertFalse(any(d.control_active(result, t) for t in d.SLOTS))
        self.assertIsNone(result.control_patrol)
        for row in result.grid.values():
            on = "".join("W" if label in d.POSTS else "O" for label in row)
            self.assertTrue(any(on == (phase * 4)[:10] for phase in ("WWO", "WOW", "OWW")))
            self.assertFalse(any((row[t], row[t+1]) in (("G2", "G3"), ("L1", "L2")) for t in range(9)))
        with tempfile.TemporaryDirectory() as store:
            d.save_day(store, result)
            loaded = d.load_day(store, DAY)["schedule"]
            self.assertEqual(loaded.grid, result.grid)
            self.assertEqual(loaded.control_as_worker_from, 0)
            self.assertEqual(d.validate_day(loaded), [])

    def test_a_absent_or_still_insufficient_returns_infeasible(self):
        result, status = d.solve_day(DAY, team(7), seconds=2, control=False)
        self.assertIsNone(result)
        self.assertIn("INFEASIBLE", status)
        result, status = d.solve_day(DAY, team(5), seconds=2, control=True)
        self.assertIsNone(result)
        self.assertIn("INFEASIBLE", status)

    def test_timeout_does_not_recruit_a_or_claim_infeasible(self):
        with patch.object(d, "_solve_day", return_value=(None, "UNKNOWN")) as run:
            result, status = d.solve_day(DAY, team(7), control=True)
        self.assertIsNone(result)
        self.assertEqual(status, "UNKNOWN")
        self.assertEqual(run.call_count, 1)

    def test_fixed_templates_remain_exempt(self):
        for n in (8, 9, 10, 11):
            result, status = d.solve_day(DAY, team(n), seconds=2)
            self.assertIsNotNone(result, status)
            self.assertEqual(result.fixed_template, n)
            self.assertIsNone(result.control_as_worker_from)
            self.assertNotIn("A", result.grid)
            self.assertEqual(d.validate_day(result), [])


if __name__ == "__main__":
    unittest.main()
