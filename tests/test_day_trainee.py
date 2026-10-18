"""주간 '교육' 신입: 마지막 번호, 고른 사람과 동행, 룰검사 제외 (2026-10-07 사용자 요청)."""
import unittest
from datetime import date

from night_shift.day_shift import (DayPerson, TRAINEE, attach_trainees, from_json, number_people, reoptimize_day,
                                   solve_day, to_json, validate_day)

DAY = date(2026, 10, 8)
NAMES = ("만년", "광희", "제욱", "원종", "도운", "성욱", "용주", "준호")


def people(trainee=TRAINEE):
    return number_people([DayPerson(n, n, "출근") for n in NAMES] + [DayPerson("여진", "여진", trainee)])


class TraineeTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.schedule, cls.status = solve_day(DAY, people(), seconds=20, trainees={"여진": "원종"})

    def test_last_number_and_follows_companion(self):
        s = self.schedule
        self.assertIsNotNone(s, self.status)
        numbers = {p.pid: p.number for p in s.people}
        self.assertEqual(numbers["여진"], max(numbers[n] for n in NAMES) + 1)
        self.assertEqual(s.grid["여진"], s.grid["원종"])
        self.assertIn("여진", s.rule_exempt_names)
        self.assertEqual(validate_day(s), [])
        self.assertEqual(from_json(to_json(s)).trainees, {"여진": "원종"})

    def test_switch_companion_to_control_a_and_number(self):
        s = attach_trainees(self.schedule, {"여진": "A"})
        self.assertEqual(s.trainees, {"여진": "A"})
        self.assertNotEqual(s.grid["여진"], self.schedule.grid["원종"])
        s = attach_trainees(s, {"여진": "광희"})
        self.assertEqual(s.grid["여진"], s.grid["광희"])
        self.assertEqual(validate_day(s), [])

    def test_shown_together_on_the_program_table(self):
        from day_ui import day_sheet_html
        s = self.schedule
        number = {p.pid: p.number for p in s.people}
        import re
        text = re.sub(r"<[^>]+>", "", day_sheet_html(s))
        a, b = sorted((number["원종"], number["여진"]))
        self.assertIn(f"{a}.{b}", text)
        self.assertIn(f"{b}여진", text)
        s = attach_trainees(s, {"여진": "A"})
        text = re.sub(r"<[^>]+>", "", day_sheet_html(s))
        self.assertIn(f"A.{b}", text)          # 통제 칸(08·10·12·14·16시)에 A와 함께

    def test_name_drag_between_workers_swaps_numbers_only(self):
        from night_shift.day_shift import edit_day
        s = attach_trainees(self.schedule, {"여진": "원종"})
        num = {p.pid: p.number for p in s.people}
        out = edit_day(s, {"kind": "rowswap", "a": "광희", "b": "원종"})
        new = {p.pid: p.number for p in out.people}
        self.assertEqual((new["광희"], new["원종"]), (num["원종"], num["광희"]))
        self.assertEqual(out.grid["광희"], s.grid["원종"])
        self.assertEqual(out.grid["여진"], out.grid["원종"])        # 동행자는 같은 사람을 따름
        self.assertEqual(validate_day(out), [])                     # 번호 칸·고정틀 순서 그대로

    def test_no_companion_by_default_then_drag_name_onto_worker(self):
        from night_shift.day_shift import edit_day
        s = attach_trainees(self.schedule, {"여진": ""})
        self.assertEqual(s.grid["여진"], [None] * 10)
        self.assertEqual({p.pid: p.number for p in s.people}["여진"], 9)
        joined = edit_day(s, {"kind": "rowswap", "a": "여진", "b": "준호"})
        self.assertEqual(joined.grid["여진"], s.grid["준호"])
        self.assertEqual(joined.trainees, {"여진": "준호"})

    def test_drag_trainee_onto_worker_joins_instead_of_swapping(self):
        from night_shift.day_shift import edit_day
        s = attach_trainees(self.schedule, {"여진": "A"})
        before = {k: list(v) for k, v in s.grid.items()}
        # 이름 칸끼리: 하루 전체 동행 대상 변경 (상대 근무는 그대로)
        joined = edit_day(s, {"kind": "rowswap", "a": "여진", "b": "제욱"})
        self.assertEqual(joined.grid["여진"], s.grid["제욱"])
        self.assertEqual(joined.grid["제욱"], before["제욱"])
        self.assertEqual(joined.trainees, {"여진": "제욱"})
        # 같은 시간 번호끼리: 그 시간만 그 사람 칸으로 (맞바꾸지 않음)
        one = edit_day(s, {"kind": "swap", "a": ["광희", 3], "b": ["여진", 3]})
        self.assertEqual(one.grid["여진"][3], s.grid["광희"][3])
        self.assertEqual(one.grid["광희"], before["광희"])
        # 빈 칸으로 옮기기: 그 칸 근무자와 맞바꾸지 않음
        moved = edit_day(s, {"kind": "move", "a": ["여진", 1], "col": "G1", "t": 1})
        self.assertEqual(moved.grid["여진"][1], "G1")
        self.assertEqual([r[1] for k, r in moved.grid.items() if k != "여진"], [r[1] for k, r in before.items() if k != "여진"])
        self.assertEqual(validate_day(joined), [])

    def test_emergency_reoptimize_keeps_companion(self):
        s = self.schedule
        target = next(n for n in NAMES if n not in ("원종",))
        result, status = reoptimize_day(s, 3, target, 3, seconds=20)
        self.assertIsNotNone(result, status)
        self.assertEqual(result.trainees, {"여진": "원종"})
        self.assertEqual(result.grid["여진"], result.grid["원종"])


if __name__ == "__main__":
    unittest.main()
