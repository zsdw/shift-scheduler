import unittest

from run_v27_a_absent import context
from night_shift.common import compile_common_policy
from night_shift.models import HistoryInput, Mode
from night_shift.solver import solve_first_trial


class V27AAbsentTests(unittest.TestCase):
    def test_proxy_manager_keeps_five_person_fm_profile(self):
        c = context()
        policy = compile_common_policy(c)
        self.assertEqual(policy.manager_id, "1")
        self.assertEqual(policy.general_ids, ("2", "3", "4", "5"))
        self.assertEqual(policy.staffing_count, 5)
        self.assertTrue(policy.manager_is_proxy)
        self.assertEqual(policy.absence_count, 2)
        self.assertEqual(c.effective_mode, Mode.FM)
        evening_g2 = [r.slot_index for r in policy.requirements if r.displayed_post == "G2" and r.slot_index < 3]
        self.assertEqual(evening_g2, [0])

    def test_current_hard_rules_are_feasible(self):
        result = solve_first_trial(context(), HistoryInput((), ()), seconds=10, rules_v27=True)
        self.assertEqual(result.status, "FEASIBLE")
        self.assertIsNotNone(result.record)


if __name__ == "__main__":
    unittest.main()
