"""2026-10-05 사용자 요청:
- 긴급 반차·이탈 재편성은 눌러야 켜진다(파란 안내·시간 칸 LOCK·폰 입력칸). 야간·주간, PC·폰.
- 현장 양식 다운로드는 업로드 칸 옆 한 곳.
- 실근무·피로도가 둘 다 가장 적은 사람은 특이사항에 이유를 반드시 설명."""
import os
import tempfile

os.environ["NIGHT_SHIFT_HISTORY_DIR"] = tempfile.mkdtemp(prefix="night_shift_toggle_")

import unittest
from datetime import date
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from streamlit.testing.v1 import AppTest

from night_shift.balance_notes import lightest_lines

APP = str(Path(__file__).resolve().parents[1] / "app.py")


def person(pid, number, work, fatigue, patrol=1, standing=4):
    return SimpleNamespace(employee_id=pid, name=f"사람{pid}", display_number=number, is_manager=False,
                           available_time=14, actual_work_time_value=work, fatigue_value=fatigue,
                           patrol_count=patrol, post_standing=standing)


def cell(pid, label="휴게", install=False):
    kind = "barrier_only" if install and label == "보안실 대기" else "rest"
    return SimpleNamespace(employee_id=pid, displayed_assignment=SimpleNamespace(label=label),
                           actual_post_or_work_type=SimpleNamespace(kind=SimpleNamespace(value=kind)),
                           barrier_install_flag=install, barrier_remove_flag=False)


class EmergencyToggleTests(unittest.TestCase):
    def test_pc_night_toggle_and_download_next_to_upload(self):
        at = AppTest.from_file(APP, default_timeout=300)
        at.query_params["view"] = "pc"
        at.run()
        at.session_state["shift_date"] = date(2026, 9, 28)
        at.run()
        at.button(key="generate_button").click().run()
        self.assertFalse(at.exception)
        seen = []

        def fake(component, **kwargs):
            if component.name.endswith("drag_schedule") and kwargs.get("key") == "drag_grid_0":
                seen.append(kwargs["data"])
            return None
        with patch("streamlit.components.v1.custom_component.CustomComponent.__call__", autospec=True, side_effect=fake):
            at.run()
        self.assertNotIn("lock_hours", seen[-1])                          # 꺼져 있으면 LOCK·안내 없음
        at.toggle(key="night_emergency_0").set_value(True)
        with patch("streamlit.components.v1.custom_component.CustomComponent.__call__", autospec=True, side_effect=fake):
            at.run()
        self.assertTrue(seen[-1]["lock_hours"])
        self.assertIn("steps", seen[-1]["steps_html"])
        upload = next(e for e in at.expander if e.label.startswith("📥"))
        self.assertTrue(upload.get("download_button"))                    # 다운로드는 업로드 칸 안(옆)

    def test_today_only_burden_is_not_explained(self):
        stats = {"1": person("1", 1, 8, 13, patrol=0, standing=3), "2": person("2", 2, 9, 15),
                 "3": person("3", 3, 9, 15)}
        record = SimpleNamespace(assignments=[cell("1"), cell("2", install=True), cell("3", "보안실 대기")])
        lines = lightest_lines(record, stats)
        self.assertEqual(lines, [])  # 오늘 부담 차이만으로 사람별 비고를 만들지 않는다
        same = {k: person(k, int(k), 9, 15) for k in "123"}
        self.assertEqual(lightest_lines(record, same), [])                 # 모두 같으면 설명 없음
        # 17-1 배려·나눗셈 나머지뿐인 사람은 적지 않음 (순찰·차단봉·입식 차이 없음)
        plain = {"1": person("1", 1, 8, 13, patrol=1, standing=4), "2": person("2", 2, 9, 15),
                 "3": person("3", 3, 9, 15)}
        quiet = SimpleNamespace(assignments=[cell("1"), cell("2"), cell("3")])
        prepared = SimpleNamespace(preference_weights={"1": 2, "2": 1, "3": 1})
        self.assertEqual(lightest_lines(quiet, plain, prepared), [])


if __name__ == "__main__":
    unittest.main()
