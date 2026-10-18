"""웨딩(결혼식) 있는 날 표시 (2026-10-13 사용자 요청). 표기만 하며 근무 규칙에는 쓰지 않는다.

연차일정 탭에서 사용자가 직접 날짜를 추가·삭제한다. 저장: history/wedding_days.json = {"days": ["YYYY-MM-DD", ...]}.
연차일정 파일을 새로 올려도 지우지 않는다(연차일정과 별개 자료).
"""
from __future__ import annotations

import json
import os
import tempfile
from datetime import date
from pathlib import Path

FILE = "wedding_days.json"
MARK = "💒"


def load(store) -> list[date]:
    path = Path(store) / FILE
    try:
        days = json.loads(path.read_text(encoding="utf-8")).get("days", [])
    except (OSError, ValueError):
        return []
    out = set()
    for d in days:
        try:
            out.add(date.fromisoformat(d))
        except (TypeError, ValueError):
            pass
    return sorted(out)


def _write(store, days) -> None:
    store = Path(store)
    store.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(prefix=".wedding-", suffix=".tmp", dir=store)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump({"days": [d.isoformat() for d in sorted(set(days))]}, f, ensure_ascii=False, indent=1)
        os.replace(tmp, store / FILE)
    finally:
        Path(tmp).unlink(missing_ok=True)


def add(store, day: date) -> bool:
    days = load(store)
    if day in days:
        return False
    _write(store, days + [day])
    return True


def remove(store, day: date) -> bool:
    days = load(store)
    if day not in days:
        return False
    _write(store, [d for d in days if d != day])
    return True


def has(store, day: date) -> bool:
    return day in load(store)
