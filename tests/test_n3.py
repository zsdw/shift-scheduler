import unittest

from night_shift.common import compile_common_policy
from night_shift.models import HistoryInput, NightType
from night_shift.profiles import make_record
from night_shift.solver import solve_first_trial
from night_shift.validator import validate_first_trial
from run_sep28_n2_fm import context


class N3Tests(unittest.TestCase):
    def test_no_evening_gate_and_weekday_morning(self):
        c = context(NightType.N3)
        policy = compile_common_policy(c)
        gates = [(r.slot_index,r.displayed_post) for r in policy.requirements if r.displayed_post in ("G2","G3","G2(1)")]
        self.assertEqual(gates, [(12,"G2"),(12,"G2(1)"),(13,"G2"),(13,"G3")])
        self.assertEqual((make_record(c,"1",0,"I1").actual_post_or_work_type.label,
                          make_record(c,"1",13,"I1").actual_post_or_work_type.label), ("I1","L3"))

    def test_generated_schedule_validates(self):
        c = context(NightType.N3)
        h = HistoryInput((), ())
        result = solve_first_trial(c,h,seconds=25,rules_v210=True)
        self.assertIsNotNone(result.record,result.attempts)
        self.assertEqual(validate_first_trial(result.record,h,rules_v210=True),[])


if __name__ == "__main__":
    unittest.main()
