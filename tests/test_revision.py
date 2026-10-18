import unittest
from dataclasses import replace
from revise_existing import revised_record
from night_shift.models import HistoryInput
from night_shift.profiles import make_record
from night_shift.validator import validate_first_trial


class RevisionTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.result, cls.baseline = revised_record()
        cls.plan = cls.result.record
        cls.history = HistoryInput((), ())

    def test_revised_plan_valid(self):
        self.assertEqual(validate_first_trial(self.plan, self.history, refinement=True), [])
        self.assertTrue(self.result.targets_met)

    def test_one_standby_and_other_off_duty_rest(self):
        for t in range(14):
            self.assertEqual(sum(r.slot.index == t and r.displayed_assignment.label == "보안실 대기" for r in self.plan.assignments), 1)

    def test_a_has_two_work_blocks_and_04_i1(self):
        rows = sorted((r for r in self.plan.assignments if r.employee_id == "A" and 6 <= r.slot.index <= 11), key=lambda r: r.slot.index)
        self.assertEqual([r.actual_work_time_value for r in rows], [1, 1, 0, 1, 1, 0])
        self.assertEqual(rows[4].displayed_assignment.label, "I1")

    def test_validator_rejects_third_consecutive_a_work(self):
        changed = make_record(self.plan.context, "A", 8, "G1")
        plan = replace(self.plan, assignments=tuple(changed if r.employee_id == "A" and r.slot.index == 8 else r for r in self.plan.assignments))
        errors = validate_first_trial(plan, self.history, refinement=True)
        self.assertTrue(any(e["rule"] == "user-A-00-05" for e in errors))

    def test_validator_rejects_extra_standby(self):
        changed = make_record(self.plan.context, "3", 1, "보안실 대기")
        plan = replace(self.plan, assignments=tuple(changed if r.employee_id == "3" and r.slot.index == 1 else r for r in self.plan.assignments))
        errors = validate_first_trial(plan, self.history, refinement=True)
        self.assertTrue(any(e["rule"] == "user-standby" for e in errors))
