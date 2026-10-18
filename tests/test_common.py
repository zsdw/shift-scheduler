import unittest
from dataclasses import replace

from night_shift.common import (
    compile_common_policy, core_post_facts, forbidden_same_post_pair,
    person_common_violations, staffing_common_violations,
)
from night_shift.models import Assignment, AssignmentKind as K, AssignmentRecord, Mode, Posture, SLOTS
from test_models import initial_context


def record(index, display="휴게", actual=None, *, standing=False, patrol=False, barrier=False):
    kind = K.REST if display == "휴게" else K.PATROL if patrol else K.POST
    work = kind in (K.POST, K.PATROL) or barrier
    return AssignmentRecord(
        "test-1", SLOTS[index], Assignment(kind, display),
        Assignment(K.BARRIER_ONLY if barrier else kind, actual or display),
        2 if standing else int(work), int(work), int(not work),
        Posture.STANDING if standing else Posture.SEATED if work else Posture.REST_LIKE,
        kind == K.POST, kind == K.POST, not work, not work,
        barrier, False, Mode.FLEXIBLE, ("test",),
    )


class CommonTests(unittest.TestCase):
    def setUp(self):
        self.context = initial_context()
        self.policy = compile_common_policy(self.context)

    def test_south_gate_exact_counts(self):
        expected = {0: {"G2": 1, "G3": 1}, 1: {"G2": 1}, 2: {"G2": 1},
                    12: {"G2": 2, "G2(1)": 1}, 13: {"G2": 1, "G3": 1}}
        for slot in range(14):
            demands = {r.displayed_post: r.total_count for r in self.policy.requirements
                       if r.slot_index == slot and r.displayed_post.startswith("G2") or
                       r.slot_index == slot and r.displayed_post == "G3"}
            self.assertEqual(demands, expected.get(slot, {}))

    def test_fixed_manager(self):
        fixed = [(r.slot_index, r.displayed_post) for r in self.policy.requirements if r.fixed_employee_id]
        self.assertEqual(fixed, [(0, "L3"), (1, "L3"), (12, "G2")])
        self.assertEqual(self.policy.manager_rest_slot, 11)

    def test_g1_seated_boundary(self):
        for i in range(14):
            facts = core_post_facts(self.context, "test-1", i, "G1")
            self.assertEqual(facts[2], Posture.SEATED if 6 <= i <= 10 else Posture.STANDING)

    def test_special_display_actual(self):
        facts = core_post_facts(self.context, "test-A", 0, "L3")
        self.assertEqual(facts, (K.SECURITY_STANDBY, "보안실 대기", Posture.REST_LIKE, 0))
        for i in (0, 13):
            self.assertEqual(core_post_facts(self.context, "test-1", i, "I1"),
                             (K.POST, "L3", Posture.STANDING, 2))
        self.assertIsNone(core_post_facts(self.context, "test-1", 6, "I1"))

    def test_confirmed_pair_boundaries(self):
        for i, expected in ((3, True), (4, False), (10, False), (11, True), (12, True)):
            self.assertEqual(forbidden_same_post_pair(record(i, "L3"), record(i + 1, "L3")), expected)

    def test_morning_display_switch_actual_l3_allowed(self):
        self.assertFalse(forbidden_same_post_pair(record(12, "L3", standing=True), record(13, "I1", "L3", standing=True)))

    def test_g1_never_consecutive(self):
        for i in range(13):
            self.assertTrue(forbidden_same_post_pair(record(i, "G1"), record(i + 1, "G1")))

    def test_rest_like_i1_three_consecutive(self):
        rows = [record(i) for i in range(14)]
        for i in (6, 7, 8):
            rows[i] = replace(record(i), displayed_assignment=Assignment(K.POST, "I1"), counts_for_same_post_consecutive=True)
        self.assertIn("H-04", [v.rule_ref for v in person_common_violations(tuple(rows), is_manager=False)])

    def test_standing_exception_does_not_erase_four_hour_limit(self):
        rows = [record(i) for i in range(14)]
        for i, label in ((11, "L3"), (12, "G2"), (13, "I1")):
            rows[i] = record(i, label, "L3" if label == "I1" else label, standing=True)
        refs = [v.rule_ref for v in person_common_violations(tuple(rows), is_manager=False)]
        self.assertNotIn("H-06/H-07", refs)
        rows[10] = record(10, "I1")
        self.assertIn("H-08", [v.rule_ref for v in person_common_violations(tuple(rows), is_manager=False)])

    def test_barrier_cannot_fill_patrol_rest_even_with_bad_rest_flag(self):
        rows = [record(i) for i in range(14)]
        rows[8] = record(8, "middle", patrol=True)
        rows[10] = replace(record(10, barrier=True), counts_as_post_patrol_rest=True)
        self.assertIn("H-09/H-11", [v.rule_ref for v in person_common_violations(tuple(rows), is_manager=False)])

    def test_meal_and_manager_rest(self):
        rows = [record(i) for i in range(14)]
        for i, label in enumerate(("G1", "I1", "L3")):
            rows[i] = record(i, label)
        rows[11] = record(11, "I1")
        refs = [v.rule_ref for v in person_common_violations(tuple(rows), is_manager=True)]
        self.assertIn("H-10", refs)
        self.assertIn("§8-1", refs)

    def test_no_silent_ignore_or_infeasible_claim(self):
        with self.assertRaises(NotImplementedError):
            compile_common_policy(replace(self.context, day_instructions=("special event",)))
        self.assertTrue(staffing_common_violations(self.policy, ()))


if __name__ == "__main__":
    unittest.main()
