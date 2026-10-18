"""업로드한 현장 실제 근무표는 생성 규칙 위반 표시를 하지 않는다 (2026-10-12 사용자 확정)."""
import os
import tempfile
import unittest
from datetime import date
from unittest import mock


class FieldRecordTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        os.environ["NIGHT_SHIFT_HISTORY_DIR"] = self.tmp.name
        import day_ui
        self.day_ui = day_ui
        self.day = date(2026, 10, 8)
        self.schedule = mock.Mock(day=self.day)

    def tearDown(self):
        os.environ.pop("NIGHT_SHIFT_HISTORY_DIR", None)
        self.tmp.cleanup()

    def check(self, data, key="saved_2026-10-08_base_0", originals=None):
        with mock.patch.object(self.day_ui, "load_day", return_value=data), \
                mock.patch.object(self.day_ui.st, "session_state", {"day_originals": originals or {}}):
            return self.day_ui._field_record(self.schedule, key)

    def test_uploaded_record_is_not_checked(self):
        self.assertEqual(self.check({"source": "excel-bulk"}), "엑셀")
        self.assertEqual(self.check({"source": "image"}), "이미지")

    def test_generated_or_edited_records_are_checked(self):
        self.assertEqual(self.check({"source": "generated"}), "")
        self.assertEqual(self.check({"source": "excel-bulk", "final_save_method": "screen-edit"}), "")
        self.assertEqual(self.check({"source": "excel-bulk"}, originals={id(self.schedule): ()}), "")
        self.assertEqual(self.check({"source": "excel-bulk"}, key="saved_2026-10-08_em_0"), "")
        self.assertEqual(self.check({"source": "excel-bulk"}, key="new_base_0"), "")


if __name__ == "__main__":
    unittest.main()
