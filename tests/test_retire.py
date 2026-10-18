"""퇴사 (2026-10-12 사용자 확정): 명단 마지막 근무일(종료) 한 곳에 적는다. 그날 일보 비고 '퇴사', 다음 날부터
일보·근무 편성 명단에서 빠짐, 7일 전부터 퇴사 예정 안내."""
import tempfile
import unittest
from datetime import date
from pathlib import Path

from night_shift import daily_report as dr


class RetireTests(unittest.TestCase):
    def test_last_day_flow(self):
        with tempfile.TemporaryDirectory() as folder:
            store = Path(folder)
            dr.save_roster(store, [{"이름": "김도운", "소속": "주간고정", "직책": "대원"},
                                   {"이름": "이준형", "소속": "주간고정", "직책": "대원"}])
            self.assertTrue(dr.set_last_day(store, "도운", date(2026, 10, 12)))      # 짧은 이름으로도
            last = date(2026, 10, 12)
            self.assertEqual(dr.retiring(store, date(2026, 10, 5)), [("김도운", last)])  # 7일 전부터 안내
            self.assertEqual(dr.retiring(store, date(2026, 10, 4)), [])
            self.assertIn({"name": "김도운", "team": "D", "kind": "퇴사"}, dr.entries_for(store, last))
            self.assertEqual(dr.retired(store, last), set())                         # 마지막 날은 출근
            self.assertEqual(dr.retired(store, date(2026, 10, 13)), {"김도운", "도운"})
            names = [r["이름"] for r in dr.active(dr.load_roster(store), date(2026, 10, 13))]
            self.assertEqual(names, ["이준형"])
            report = dr.build(last, dr.entries_for(store, last), dr.load_roster(store))
            rows = dr.build_rows(report) if hasattr(dr, "build_rows") else None
            self.assertTrue(dr.set_last_day(store, "김도운", None))                  # 퇴사 취소
            self.assertEqual(dr.retired(store, date(2026, 10, 13)), set())


if __name__ == "__main__":
    unittest.main()
