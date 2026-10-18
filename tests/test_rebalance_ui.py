import os
import tempfile

# Keep UI tests independent of the user's confirmed history folder.
os.environ["NIGHT_SHIFT_HISTORY_DIR"] = tempfile.mkdtemp(prefix="night_shift_history_")

import unittest
from datetime import date
from pathlib import Path

from streamlit.testing.v1 import AppTest


APP = Path(__file__).resolve().parents[1] / "app.py"


class RebalanceUiTests(unittest.TestCase):
    def test_19_hour_half_day_rebalance_keeps_original_candidate(self):
        app = AppTest.from_file(str(APP), default_timeout=90).run()
        app.session_state["shift_date"] = date(2026, 9, 28)
        app.run()   # 월요일 야간 -> N1
        self.assertEqual(app.selectbox(key="night_type_select").value, "N1")
        app.button(key="generate_button").click().run()
        self.assertFalse(app.exception)
        original = app.session_state["schedule_results"][0]

        # 주간과 같은 방식: 표의 18시 칸을 눌러 LOCK → 이름(1번 직원)을 눌러 후반부 반차
        self.assertFalse([b for b in app.button if str(b.key).startswith("rebalance_time_")])   # 아래 버튼 줄은 없음
        app.session_state["night_leave_request_0"] = {"kind": "lockhour", "t": 0}
        app.run()
        self.assertEqual(app.session_state["night_lock_0"], 0)
        app.session_state["night_leave_request_0"] = {"kind": "leave", "pid": "1", "choice": "half"}
        app.run()

        self.assertFalse(app.exception)
        self.assertFalse(app.error)
        self.assertEqual(len(app.session_state["schedule_results"]), 2)
        self.assertIs(app.session_state["schedule_results"][0], original)
        revised = app.session_state["schedule_results"][1]
        self.assertTrue(revised.valid)
        self.assertEqual(revised.rebalance_info.reoptimization_start_index, 1)
        self.assertEqual(app.session_state["selected_schedule_index"], 1)


if __name__ == "__main__":
    unittest.main()
