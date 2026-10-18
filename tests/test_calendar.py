"""Shift pattern (주주야야휴휴 from 2026-09-01), holidays and automatic N1~N4."""
import unittest
from datetime import date

from night_shift.calendar_info import (
    holiday_name, is_off_day, month_calendar_html, next_night, night_type_for, shift_kind,
)


class CalendarTests(unittest.TestCase):
    def test_pattern(self):
        self.assertEqual([shift_kind(date(2026, 9, d)) for d in range(1, 8)],
                         ["주", "주", "야", "야", "휴", "휴", "주"])
        self.assertEqual(shift_kind(date(2026, 8, 31)), "휴")      # cycle runs backwards too
        self.assertEqual(next_night(date(2026, 9, 30)), date(2026, 10, 3))

    def test_holidays_and_night_types(self):
        self.assertEqual(holiday_name(date(2026, 10, 9)), "한글날")
        self.assertTrue(is_off_day(date(2026, 10, 5)))            # 대체공휴일
        self.assertFalse(is_off_day(date(2026, 10, 7)))
        self.assertEqual(night_type_for(date(2026, 9, 4)), "N2")   # Friday -> Saturday
        self.assertEqual(night_type_for(date(2026, 9, 3)), "N1")
        self.assertEqual(night_type_for(date(2026, 9, 6)), "N3")   # Sunday -> Monday
        self.assertEqual(night_type_for(date(2026, 10, 3)), "N4")  # 개천절(토) -> 일
        self.assertEqual(night_type_for(date(2026, 10, 8)), "N2")  # 목 -> 한글날

    def test_calendar_html(self):
        html = month_calendar_html(date(2026, 10, 3), {date(2026, 10, 4)})
        self.assertIn("2026년 10월", html)
        self.assertIn("●", html)


if __name__ == "__main__":
    unittest.main()
