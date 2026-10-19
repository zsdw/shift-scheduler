"""엔진 파일 내용 지문 (2026-10-19): 앱이 엔진 수정 여부를 알아서 판단하게 한다(버전 손으로 올리기 대체).

service.py가 처음 불러올 때 지문을 기록하고, app.py는 매 실행마다 현재 파일 지문과 비교해 다를 때만 다시 불러온다.
처음 불러온 직후에는 같으므로 재로딩하지 않는다(재로딩하면 이미 만든 객체의 클래스가 바뀌어 isinstance가 깨진다).
"""
from __future__ import annotations

import hashlib
from pathlib import Path

ENGINE_MODULES = ("models", "common", "profiles", "preferences", "soft_history", "leave_context", "fatigue_ledger", "solver",
                  "validator", "service", "presentation", "analysis", "excel_exporter", "field_exporter")


def engine_fingerprint() -> str:
    digest = hashlib.sha1()
    base = Path(__file__).parent
    for name in ENGINE_MODULES:
        digest.update((base / f"{name}.py").read_bytes())
    return digest.hexdigest()
