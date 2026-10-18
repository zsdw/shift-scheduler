"""최고·최저·동률 여부에 관계없이 당일 부담만으로 사람별 비고를 만들지 않는다."""
import unittest
from types import SimpleNamespace
from night_shift.balance_notes import lightest_lines


def notes(values):
    stats = {str(i): SimpleNamespace(employee_id=str(i), name=f'사람{i}', display_number=i,
                                    is_manager=False, available_time=14,
                                    actual_work_time_value=work, fatigue_value=fatigue,
                                    patrol_count=1, post_standing=3)
             for i, (work, fatigue) in enumerate(values, 1)}
    return '\n'.join(lightest_lines(SimpleNamespace(assignments=()), stats, manual=True))


class UniqueExtremeNotesTests(unittest.TestCase):
    def test_both_unique(self):
        text = notes([(7, 10), (8, 12), (9, 14)])
        self.assertNotIn('가장 가벼운 근무자', text)
        self.assertNotIn('가장 무거운 근무자', text)

    def test_tied_low_does_not_hide_unique_high(self):
        text = notes([(7, 10), (7, 10), (9, 14)])
        self.assertNotIn('가장 가벼운 근무자', text)
        self.assertNotIn('가장 무거운 근무자', text)

    def test_tied_high_keeps_unique_low(self):
        text = notes([(7, 10), (9, 14), (9, 14)])
        self.assertNotIn('가장 가벼운 근무자', text)
        self.assertNotIn('가장 무거운 근무자', text)

    def test_all_equal(self):
        self.assertEqual(notes([(8, 12), (8, 12)]), '')

    def test_different_people_hold_each_extreme(self):
        self.assertEqual(notes([(7, 14), (9, 10), (8, 12)]), '')

    def test_no_joint_low_keeps_joint_high(self):
        text = notes([(7, 12), (8, 10), (9, 14)])
        self.assertNotIn('가장 가벼운 근무자', text)
        self.assertNotIn('가장 무거운 근무자', text)
