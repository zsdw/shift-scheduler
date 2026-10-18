import unittest
from dataclasses import replace
from test_models import initial_context
from night_shift.models import Mode
from night_shift.profiles import make_record


class ProfilesTests(unittest.TestCase):
    def test_flexible_midnight_accounting(self):
        r = make_record(initial_context(), "test-1", 6, "I1")
        self.assertEqual((r.fatigue_value, r.actual_work_time_value, r.actual_rest_time_value), (0, 0, 1))
        self.assertTrue(r.counts_for_same_post_consecutive)
        self.assertTrue(r.counts_as_post_patrol_rest)
        self.assertFalse(r.counts_for_continuous_work_restriction)

    def test_flexible_install_standby_and_gate(self):
        c = initial_context()
        standby = make_record(c, "test-1", 2, "보안실 대기", install=True)
        gate = make_record(c, "test-2", 2, "G2", install=True)
        self.assertEqual((standby.fatigue_value, gate.fatigue_value), (1, 2))
        self.assertTrue(standby.counts_as_meal_opportunity)
        self.assertFalse(standby.counts_for_continuous_work_restriction)

    def test_flexible_04_confirmed_exclusion(self):
        r = make_record(initial_context(), "test-1", 10, "I1")
        self.assertFalse(r.counts_for_continuous_work_restriction)
        self.assertTrue(r.counts_for_same_post_consecutive)
        self.assertTrue(r.barrier_remove_flag)
        self.assertEqual((r.actual_work_time_value, r.fatigue_value), (1, 1))

    def test_fm_night_i1_is_work(self):
        c = replace(initial_context(), requested_mode=Mode.FM, effective_mode=Mode.FM)
        for i in range(6, 11):
            r = make_record(c, "test-1", i, "I1")
            self.assertEqual((r.fatigue_value, r.actual_work_time_value, r.actual_rest_time_value), (1, 1, 0))
            self.assertFalse(r.barrier_remove_flag)
            self.assertFalse(r.counts_as_post_patrol_rest)

    def test_fm_barrier_cannot_use_post(self):
        c = replace(initial_context(), requested_mode=Mode.FM, effective_mode=Mode.FM)
        for slot, flag in ((2, "install"), (10, "remove")):
            with self.assertRaises(ValueError):
                make_record(c, "test-1", slot, "I1", **{flag: True})
            r = make_record(c, "test-1", slot, "보안실 대기", **{flag: True})
            self.assertEqual((r.fatigue_value, r.actual_work_time_value, r.actual_rest_time_value), (1, 0, 0))   # 11-0
            self.assertFalse(r.counts_for_continuous_work_restriction)
            self.assertFalse(r.counts_as_post_patrol_rest)
