import unittest
from datetime import date, datetime, timezone
from types import SimpleNamespace

from night_shift.models import AssignmentKind, Attendance, HistoryInput, NightType, Posture, RecordKind
from night_shift.soft_history import debt_weight, patrol_rotation_due, update_soft_debt
from night_shift.solver import solve_first_trial
from night_shift.validator import validate_first_trial
from run_sep28_n2_fm import context


def actual_shift(day, area):
    rows = []
    for slot in range(14):
        patrol = slot == 3 and area is not None
        rows.append(SimpleNamespace(employee_id="1", slot=SimpleNamespace(index=slot),
                                    actual_post_or_work_type=SimpleNamespace(kind=AssignmentKind.PATROL if patrol else AssignmentKind.REST,
                                                                            label=area if patrol else "휴게"),
                                    actual_rest_time_value=0 if patrol else 1,
                                    actual_work_time_value=1 if patrol else 0,
                                    posture_or_mode=Posture.STANDING if patrol else Posture.REST_LIKE,
                                    counts_for_continuous_work_restriction=patrol,
                                    barrier_install_flag=False, barrier_remove_flag=False))
    return SimpleNamespace(kind=RecordKind.ACTUAL, confirmed_at=datetime(2026,9,day,8,tzinfo=timezone.utc),
                           context=SimpleNamespace(shift_start_date=date(2026, 9, day),
                                                   attendance=(Attendance("1", True, True, 1, False),)),
                           assignments=tuple(rows))


class V213Tests(unittest.TestCase):
    def test_patrol_rotation_and_debt_use_actuals_only(self):
        first, second = actual_shift(21, "upper"), actual_shift(27, "middle")
        self.assertEqual(patrol_rotation_due((first, second)), frozenset(("1",)))
        self.assertEqual(patrol_rotation_due((first, actual_shift(27, None))), frozenset())
        self.assertEqual(debt_weight({"14-7": {"1": 2}}, "14-7", "1"), 3)
        debt = update_soft_debt(second, {}, rotation_due=("1",))
        self.assertEqual(debt["14-7"]["1"], 1)
        self.assertEqual(update_soft_debt(actual_shift(28, None), debt, rotation_due=("1",))["14-7"]["1"], 1)
        self.assertEqual(update_soft_debt(actual_shift(29, "lower"), debt, rotation_due=("1",))["14-7"]["1"], 0)
        plan = SimpleNamespace(kind=RecordKind.PLAN, confirmed_at=None, context=second.context, assignments=second.assignments)
        with self.assertRaises(ValueError):
            patrol_rotation_due((first, plan))
        with self.assertRaises(ValueError):
            update_soft_debt(plan, debt, rotation_due=("1",))

    def test_solver_prefers_due_lower_patrol_when_feasible(self):
        c, history = context(NightType.N3), HistoryInput((), ())
        result = solve_first_trial(c, history, seconds=15, rules_v213=True,
                                   patrol_rotation_priority_ids=("1",), soft_debt={"14-7": {"1": 2}})
        self.assertIsNotNone(result.record, result.attempts)
        self.assertEqual(validate_first_trial(result.record, history, rules_v212=True), [])
        rotation_stage = next(a for a in result.attempts if a.get("stage") == "patrol_lower_rotation")
        self.assertEqual((rotation_stage["status"], rotation_stage["value"]), ("OPTIMAL", 0))
        # 룰북 14-7: 회전 대상자에게 '순찰을 배정할 때' 하층부를 우선한다. 그날 순찰이 아예 없는 해도
        # 같은 최선해라 (6명 중 5명 순찰) 둘 다 허용한다. 순찰을 받았다면 반드시 하층부가 있어야 한다.
        patrols = [r.actual_post_or_work_type.label for r in result.record.assignments
                   if r.employee_id == "1" and r.actual_post_or_work_type.kind == AssignmentKind.PATROL]
        self.assertTrue(not patrols or "lower" in patrols, patrols)


if __name__ == "__main__":
    unittest.main()
