"""주간 근무자 상태 '교육' → 동행 대상 선택 → 생성표에 마지막 번호·동행 표시 (PC·폰)."""
import os
import re
import tempfile
import unittest
from datetime import date
from pathlib import Path
from unittest.mock import patch

from streamlit.testing.v1 import AppTest

APP = str(Path(__file__).resolve().parent.parent / "app.py")
DAY = date(2026, 10, 8)


class TraineeUiTests(unittest.TestCase):
    def test_status_companion_and_table_pc_and_mobile(self):
        for view in ("pc", "mobile"):
            with self.subTest(view=view), tempfile.TemporaryDirectory() as folder, \
                    patch.dict(os.environ, {"NIGHT_SHIFT_HISTORY_DIR": folder}):
                at = AppTest.from_file(APP, default_timeout=240)
                at.query_params["view"] = view
                at.run()
                at.session_state["shift_date"] = DAY
                at.run()
                def mark():   # AppTest keeps data_editor edits only for one run
                    if view == "mobile":
                        at.session_state[f"day_statuses_{DAY}"] = {"성호": "교육"}
                    else:
                        at.session_state[f"day_roster_{DAY}"] = {"edited_rows": {"9": {"상태": "교육"}},
                                                                 "added_rows": [], "deleted_rows": []}
                mark()
                at.run()
                self.assertFalse(at.exception, [e.value for e in at.exception])
                pick = at.selectbox(key=f"day_trainee_{DAY}_성호")
                self.assertTrue(pick.options[0].startswith("동행 없음"))   # 기본: 동행 없음, 표에서 끌어 붙임
                pick.set_value("원종")
                mark()
                at.run()
                mark()
                at.button(key="day_generate").click().run()
                self.assertFalse(at.exception, [e.value for e in at.exception])
                switch = [s for s in at.selectbox if "동행 번호" in s.label]
                self.assertTrue(switch, (at.session_state["day_error"] if "day_error" in at.session_state else None,
                                         [e.value for e in at.error], at.session_state["day_results"][-1].trainees,
                                         [s.label for s in at.selectbox]))
                html = " ".join(m.value for m in at.markdown if "dsheet" in m.value)
                if not html:   # PC 표는 컴포넌트 안에 그려진다: 저장된 결과로 확인
                    result = at.session_state["day_results"][-1]
                else:
                    result = None
                result = result or at.session_state["day_results"][-1]
                numbers = {p.pid: p.number for p in result.people}
                self.assertEqual(numbers["성호"], max(n for p, n in numbers.items() if n and p != "성호") + 1)
                self.assertEqual(result.grid["성호"], result.grid["원종"])
                self.assertIn(f"{numbers['성호']}번 성호", switch[0].label)


if __name__ == "__main__":
    unittest.main()
