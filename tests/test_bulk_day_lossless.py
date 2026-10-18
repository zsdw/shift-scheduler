"""편성표 엑셀 주간 시트 무손실 가져오기 (2026-10-11 사용자 지적: 10/7 원본과 다른 프로그램 근무표).

- 4C 'A.10'·공동근무 '8.11'·CP 칸은 원본 그대로 보존(source_layout), 번호는 이름이 같아도 합치지 않는다.
- 명단 오기(같은 이름 두 번호·이름 없는 번호)·읽을 수 없는 칸이 있으면 그 날짜는 건너뛰고 기존 저장본 유지.
- 편성표 번호 이름 고침(order_name_fix)을 적용하면 저장된다."""
import unittest
from datetime import date

from night_shift import bulk_import as b

DAY = date(2026, 10, 7)
HEAD = ["근무시간", "G1", "G2", "G3", "4C", "L1", "L2", "C1", "C2", "CP", "1C", "셔틀", "순찰", "대기", "휴게"]
# 시간마다 1~8번이 G1·G2·G3·L1·L2·C1·순찰·대기·휴게에 한 번씩 (8.11 공동근무, 10번은 4C 동행)
BODY = [
    ["08:00", 1, 2, 3, "A.10", 4, 6, 5, "", "CP1.CP2", "", "5(해지)", 7, "8", "CP3"],
    ["09:00", 7, 1, "8.11", "", 5, 3, "", "", "cp1", "", "", 6, "2", "A.4 10.CP1"],
    ["10:00", 6, 7, 2, "A.10", "8.11", 4, "", "", "cp2", "", "", 5, "교육:", "1.3.CP1"],
    ["11:00", 5, 6, 1, "", 2, 3, 4, "", "CP1.CP2", "", "4(설치)", "A", "8", "7.10.11"],
    ["12:00", 3, 5, 7, "A.10", 1, "8.11", "", "", "CP1", "", "", "", "4", "2.6"],
    ["13:00", 4, "8.11", 6, "", 7, 2, "", "", "CP2.CP3", "", "2(해지)", "", "1", "A.3.5.10"],
    ["14:00", 3, 4, 5, "A.10", 6, 1, 2, "", "CP1", "", "", "A", "교육:", "7.8.11"],
    ["15:00", "8.11", 3, 1, "", 5, 7, "", "", "CP2.CP3", "", "", 2, "4", "A.6.10"],
    ["16:00", 2, "8.11", 4, "A.10", 7, 6, "", "", "CP1.CP3", "", "6(설치)", 3, "5", "1"],
    ["17:00", 1, 2, 3, "", 4, 5, 6, "", "CP1.CP2", "", "CP3", "8.11", "7", "A.10"],
]


def sheet(names):
    top = ["근무자명", "통제D", *names[:5]]
    bottom = ["", "통제A", *names[5:], "CP1혁준", "CP2덕영", "CP3철룡"]
    return [["주간 근무 편성표"], ["2026년 10월 07일 수요일 근무조 : A조"], top, bottom, HEAD, *BODY]


NAMES = ["1원종", "2제욱", "3준형", "4광희", "5만년", "6도운", "7준호", "8용주", "10여진", "11지훈"]


class BulkDayLosslessTests(unittest.TestCase):
    def test_keeps_original_cells_and_numbers(self):
        schedule, note = b.day_schedule(DAY, sheet(NAMES), ())
        numbers = {p.name: p.number for p in schedule.people if p.number}
        self.assertEqual(numbers["준형"], 3)
        self.assertEqual(numbers["광희"], 4)
        self.assertEqual(numbers["지훈"], 11)                      # 8.11 공동근무의 11번도 사람으로
        self.assertEqual(schedule.grid["용주"][1], "G3")           # 09시 8.11 → 8번 G3
        self.assertEqual(schedule.grid["지훈"][1], "G3")           # 11번도 같은 칸
        rows = schedule.source_layout["rows"]
        self.assertEqual(rows[0]["4C"], "A.10")                    # 원본 칸 그대로
        self.assertEqual(rows[1]["G3"], "8.11")
        self.assertIn("A.4.10", rows[1]["휴게"])                    # 띄어쓰기 구분도 점으로 읽음
        self.assertEqual(schedule.source_layout["extra_names"]["CP3"], "철룡")
        self.assertEqual(rows[2]["휴게"], "교육: 1.3.CP1")           # 대기·휴게 합친 교육 칸

    def test_listed_but_not_scheduled_is_other(self):
        """명단 머리에 있는데 시간표에 없음 = 출근했지만 다른 곳 근무 → 기타 (사용자 확정, 예: 준호)."""
        schedule, note = b.day_schedule(DAY, sheet([*NAMES[:8], "9성욱", *NAMES[8:]]), ())
        person = next(p for p in schedule.people if p.name == "성욱")
        self.assertEqual((person.status, person.number), ("기타", None))
        self.assertIn("다른 곳 근무", person.note)
        schedule, _ = b.day_schedule(DAY, sheet([*NAMES[:8], "9성욱", *NAMES[8:]]), (), {"성욱": ("연차", "")})
        self.assertEqual(next(p for p in schedule.people if p.name == "성욱").status, "연차")   # 연차일정이 있으면 연차

    def test_bad_roster_is_skipped(self):
        dup = ["1원종", "2제욱", "3광희", "4광희", *NAMES[4:]]
        with self.assertRaisesRegex(ValueError, "광희.*3·4번.*건너뜀"):
            b.day_schedule(DAY, sheet(dup), ())
        with self.assertRaisesRegex(ValueError, "11번 이름이 명단에 없음"):
            b.day_schedule(DAY, sheet(NAMES[:-1]), ())         # 11번이 포스트에 있으면 건너뜀
        rows = sheet(NAMES)
        rows[5 + 9][-1] = "A.10.12"                                  # 9/8처럼 명단에 없는 번호가 휴게 칸에만
        schedule, note = b.day_schedule(DAY, rows, ())
        self.assertEqual(schedule.source_layout["rows"][9]["휴게"], "A.10")
        self.assertIn("명단에 없는 번호, 대기·휴게 칸에만 있음", note)
        schedule, note = b.day_schedule(DAY, sheet(dup), (), fixes={"3": "준형"})   # 번호 이름 고침
        self.assertEqual({p.name: p.number for p in schedule.people if p.number}["준형"], 3)
        self.assertIn("3번 준형", note)

    def test_missing_dots_read_from_neighbours(self):
        """점이 빠진 칸은 명단 번호로 쪼갠다 (사용자 확정: 옆 칸을 보면 하나로 정해진다)."""
        self.assertEqual(b._repair("E.CP235", {str(n) for n in range(1, 11)}, {"3"}), "E.CP2.3.5")
        self.assertEqual(b._repair("E.1.310..CP2", {str(n) for n in range(1, 11)}, set()), "E.1.3.10.CP2")
        # 쪼개는 방법이 여럿이면 그 시간에 없는 사람 쪽, 그래도 못 정하면 None
        valid = {"1", "2", "3", "12", "23"}
        self.assertIsNone(b._repair("123", valid, set()))
        self.assertEqual(b._repair("123", valid, {"12", "23"}), "1.2.3")
        self.assertIsNone(b._repair("휴무 3", {"3"}, set()))                  # 다른 글자는 추측 안 함
        rows = sheet(NAMES)
        rows[5 + 8][-1] = "1.CP235"                                 # 16시 휴게: 다른 칸에 없는 번호로
        schedule, note = b.day_schedule(DAY, rows, ())
        # 포스트·순찰·대기를 먼저 본다: 16시 3번 순찰·5번 대기라 휴게에는 남지 않는다 (사용자 확정)
        self.assertEqual(schedule.source_layout["rows"][8]["휴게"], "1.CP2")
        self.assertEqual((schedule.grid["준형"][8], schedule.grid["만년"][8]), ("순찰", "대기"))
        self.assertIn("엑셀 오기 자동 해석: 16시 휴게 '1.CP235' → '1.CP2.3.5'", note)


class BulkNightGuardTests(unittest.TestCase):
    def test_night_duplicate_roster_is_skipped(self):
        rows = [["야간 근무 편성표"], ["2026년 10월 10일 토요일 근무조 : A조"],
                ["근무자명", "통제A", "1제욱", "2만년", "3광희", "4광희", "5원종"]]
        with self.assertRaisesRegex(ValueError, "광희.*두 번호.*건너뜀"):
            b.night_record(date(2026, 10, 10), rows)


if __name__ == "__main__":
    unittest.main()
