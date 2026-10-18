"""카톡으로 받은 최신 편성표 자동 반영 (2026-10-11 사용자 요청): 새 파일만 반영, 같은 파일은 다시 안 읽음,
덮어쓸 때 생긴 이전 근무표 사본은 남기지 않는다(휴지통 보냄 함수는 가짜로 대체해 검사)."""
import os
import tempfile
import time
import unittest
from pathlib import Path
from unittest.mock import patch

import sys
sys.path.insert(0, str(Path(__file__).resolve().parent))
from night_shift import kakao_sync
from test_upload_final import DAY_NAMES, workbook


class KakaoSyncTests(unittest.TestCase):
    def test_new_file_applied_once_and_copies_purged(self):
        with tempfile.TemporaryDirectory() as folder:
            store, kakao = Path(folder) / "h", Path(folder) / "kakao"
            (store / "day").mkdir(parents=True)
            kakao.mkdir()
            (store / "day_roster.json").write_text(__import__("json").dumps(list(DAY_NAMES), ensure_ascii=False),
                                                    encoding="utf-8")
            self.assertIsNone(kakao_sync.sync(store, kakao))              # 파일 없음
            (kakao / "다른파일.xlsx").write_bytes(b"x")
            (kakao / "26년 근무표 편성표(7월~12월).xlsx").write_bytes(workbook())
            (store / ".trash").mkdir()
            old = store / ".trash" / "2026-10-03__deleted-import-20261001-000000000000.json"
            old.write_text("{}", encoding="utf-8")                        # 같은 날짜의 더 최근 사본이 있으면 정리
            (store / ".trash" / "2026-10-03__deleted-import-20261002-000000000000.json").write_text("{}", encoding="utf-8")
            removed = []
            with patch.object(kakao_sync, "recycle", side_effect=lambda paths: removed.extend(paths) or len(removed)):
                message = kakao_sync.sync(store, kakao)
                self.assertIn("카톡으로 받은 새 편성표 반영", message)
                self.assertTrue((store / "2026-10-03.json").exists())   # A조 야간 저장
                self.assertIn(old, removed)                               # 이전 사본 정리
                self.assertIsNone(kakao_sync.sync(store, kakao))          # 같은 파일은 다시 안 읽음
                time.sleep(0.02)
                os.utime(kakao / "26년 근무표 편성표(7월~12월).xlsx")       # 수정시각만 바뀌고 내용 같음
                self.assertIsNone(kakao_sync.sync(store, kakao))

    def test_newest_ignores_temp_files(self):
        with tempfile.TemporaryDirectory() as folder:
            kakao = Path(folder)
            (kakao / "편성표A.xlsx").write_bytes(b"1")
            time.sleep(0.02)
            (kakao / "~$편성표B.xlsx").write_bytes(b"2")
            self.assertEqual(kakao_sync.newest(kakao).name, "편성표A.xlsx")


if __name__ == "__main__":
    unittest.main()
