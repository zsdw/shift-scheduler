import unittest
from dataclasses import replace

from run_v210_a_absent import context
from run_v27 import posture_triples
from night_shift.common import compile_common_policy
from night_shift.models import HistoryInput, Posture
from night_shift.profiles import make_record
from night_shift.solver import solve_first_trial
from night_shift.validator import validate_first_trial


class V210Tests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.history = HistoryInput((), ())
        cls.result = solve_first_trial(context(), cls.history, seconds=30, rules_v210=True)
        cls.plan = cls.result.record
        assert cls.plan is not None

    def test_overall_absence_one_and_proxy(self):
        policy = compile_common_policy(context())
        self.assertEqual((policy.absence_count, policy.manager_id), (1, "1"))
        self.assertEqual(policy.general_ids, ("2", "3", "4", "5", "6"))
        self.assertEqual([r.slot_index for r in policy.requirements if r.displayed_post == "G2" and r.slot_index < 3], [0, 1, 2])
        self.assertEqual(validate_first_trial(self.plan, self.history, rules_v210=True), [])

    def test_patrol_is_actual_standing(self):
        patrols = [r for r in self.plan.assignments if r.actual_post_or_work_type.kind == "patrol"]
        self.assertEqual(len(patrols), 6)
        self.assertTrue(all(r.posture_or_mode == Posture.STANDING and r.actual_work_time_value == 1 for r in patrols))
        self.assertEqual(posture_triples(self.plan), [])

    def test_validator_rejects_patrol_with_false_posture(self):
        target = next(r for r in self.plan.assignments if r.actual_post_or_work_type.kind == "patrol")
        bad = replace(target, posture_or_mode=None)
        record = replace(self.plan, assignments=tuple(bad if r is target else r for r in self.plan.assignments))
        errors = validate_first_trial(record, self.history, rules_v210=True)
        self.assertTrue(any(e["rule"] == "§4/§6–§11" for e in errors))

    def test_five_counted_work_slots_rejected(self):
        labels = ("I1", "G1", "L3", "G1", "upper")
        changes = {("2", t): make_record(self.plan.context, "2", t, label) for t, label in zip(range(3, 8), labels)}
        record = replace(self.plan, assignments=tuple(changes.get((r.employee_id, r.slot.index), r) for r in self.plan.assignments))
        errors = validate_first_trial(record, self.history, rules_v210=True)
        self.assertTrue(any(e["rule"] == "H-08" and "Five" in e["detail"] for e in errors))


if __name__ == "__main__":
    unittest.main()
