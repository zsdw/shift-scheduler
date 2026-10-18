import unittest
from dataclasses import replace
from run_trial import context
from night_shift.models import HistoryInput, Mode
from night_shift.solver import solve_first_trial
from night_shift.validator import validate_first_trial
from night_shift.profiles import make_record


class IntegrationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.history = HistoryInput((), ())
        cls.result = solve_first_trial(context(Mode.FM), cls.history, seconds=10)
        if cls.result.record is None:
            raise AssertionError(cls.result.status)
        cls.plan = cls.result.record

    def changed(self, old, new):
        return replace(self.plan, assignments=tuple(new if r is old else r for r in self.plan.assignments))

    def test_fm_verified_first_trial(self):
        self.assertEqual(validate_first_trial(self.plan, self.history), [])
        self.assertTrue(self.result.targets_met)
        self.assertIsNone(self.plan.confirmed_at)

    def test_flexible_verified_first_trial(self):
        result = solve_first_trial(context(Mode.FLEXIBLE), self.history, seconds=10)
        self.assertIsNotNone(result.record)
        self.assertEqual(validate_first_trial(result.record, self.history), [])

    def test_forged_accounting_is_rejected(self):
        old = next(r for r in self.plan.assignments if r.fatigue_value > 0)
        bad = self.changed(old, replace(old, fatigue_value=0))
        self.assertTrue(any(e["rule"] == "§4/§6–§11" for e in validate_first_trial(bad, self.history)))

    def test_mode_contamination_is_rejected(self):
        old = next(r for r in self.plan.assignments if r.slot.index == 6 and r.displayed_assignment.label == "I1")
        c = replace(self.plan.context, requested_mode=Mode.FLEXIBLE, effective_mode=Mode.FLEXIBLE)
        flexible = make_record(c, old.employee_id, 6, "I1")
        self.assertTrue(validate_first_trial(self.changed(old, flexible), self.history))

    def test_patrol_rest_violation_is_rejected(self):
        old = next(r for r in self.plan.assignments if r.employee_id == "A" and r.slot.index == 4)
        new = make_record(self.plan.context, "A", 4, "G1")
        errors = validate_first_trial(self.changed(old, new), self.history)
        self.assertTrue(any(e["rule"] == "H-11" for e in errors))

    def test_missing_and_duplicate_records_are_rejected(self):
        self.assertTrue(validate_first_trial(replace(self.plan, assignments=self.plan.assignments[:-1]), self.history))
        self.assertTrue(validate_first_trial(replace(self.plan, assignments=self.plan.assignments + (self.plan.assignments[0],)), self.history))

    def test_barrier_on_fm_i1_is_rejected(self):
        old = next(r for r in self.plan.assignments if r.slot.index == 10 and r.displayed_assignment.label == "I1")
        bad = self.changed(old, replace(old, barrier_remove_flag=True))
        errors = validate_first_trial(bad, self.history)
        self.assertTrue(any(e["rule"] == "§10/§11" for e in errors))

    def test_unknown_history_never_silently_becomes_empty(self):
        self.assertTrue(validate_first_trial(self.plan, HistoryInput(None, None)))
        with self.assertRaises(NotImplementedError):
            solve_first_trial(self.plan.context, HistoryInput(None, None))

    def test_a_minimum_with_mandatory_standby_and_balance_targets(self):
        result = solve_first_trial(context(Mode.FM), self.history, seconds=10, refinement=True, minimize_a=True)
        self.assertIsNotNone(result.record)
        self.assertEqual(validate_first_trial(result.record, self.history, refinement=True), [])
        self.assertTrue(result.targets_met)
        a = [r for r in result.record.assignments if r.employee_id == "A"]
        self.assertEqual(sum(r.actual_work_time_value for r in a), 3)
        self.assertEqual(sum(r.fatigue_value for r in a), 6)
        self.assertEqual(result.attempts[-1]["status"], "OPTIMAL")
