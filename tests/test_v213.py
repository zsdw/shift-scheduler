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

    def test_old_two_shift_lower_rotation_is_replaced(self):
        # 2026-10-19: 14-7 '다른 층 2회 연속이면 하층 우선'·soft debt 목표는 하층 순찰 순번(lower_oldest_*)으로
        # 대체됐다(tests/test_lower_patrol_order). 옛 회전 대상자를 넘겨도 옛 목표 단계는 더 이상 없다.
        c, history = context(NightType.N3), HistoryInput((), ())
        result = solve_first_trial(c, history, seconds=15, rules_v213=True,
                                   patrol_rotation_priority_ids=("1",), soft_debt={"14-7": {"1": 2}})
        self.assertIsNotNone(result.record, result.attempts)
        self.assertEqual(validate_first_trial(result.record, history, rules_v212=True), [])
        self.assertNotIn("patrol_lower_rotation", [a.get("stage") for a in result.attempts])


if __name__ == "__main__":
    unittest.main()
