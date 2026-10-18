"""연차일정 탭 A조 월간표·연간표 (2026-10-18 사용자 요청: 월·연 단위, 다른 조 무시)."""
import tempfile
import unittest
from datetime import date
from unittest import mock

import leave_view_ui as lv

ROSTER = [{"이름": "갑통제", "소속": "A조", "직책": "통제A", "종료": "2026-09-15"},
          {"이름": "을대원", "소속": "A조", "직책": "대원"},
          {"이름": "병CP", "소속": "A조", "직책": "CP"},
          {"이름": "정신입", "소속": "A조", "직책": "대원", "시작": "2026-10-20"},
          {"이름": "무다른", "소속": "B조", "직책": "대원"}]


class ATeamLeaveTests(unittest.TestCase):
    def test_members_by_period_and_team(self):
        with mock.patch.object(lv.dr, "load_roster", return_value=ROSTER):
            self.assertEqual(lv.a_team_members(None, date(2026, 10, 1), date(2026, 10, 31)), ["을대원", "정신입", "병CP"])
            self.assertEqual(lv.a_team_members(None, date(2026, 9, 1), date(2026, 9, 30)), ["갑통제", "을대원", "병CP"])

    def test_short_labels_and_use_days(self):
        self.assertEqual([lv.short_kind(k) for k in ("연차", "오전 반차", "후반반차", "전반부 반차")], ["연", "전", "후", "전"])
        self.assertEqual(lv._use([{"kind": "연차"}]), 1.0)
        self.assertEqual(lv._use([{"kind": "오후 반차"}]), 0.5)
        entries = {date(2026, 10, 3): [{"name": "을대원", "kind": "연차"}, {"name": "무다른", "kind": "연차"}]}
        items = lv._a_team_items(entries, ["을대원"], date(2026, 10, 1), date(2026, 10, 31))
        self.assertEqual(list(items), [("을대원", date(2026, 10, 3))])                # 다른 조 제외


if __name__ == "__main__":
    unittest.main()
