"""카카오톡으로 받은 최신 편성표 자동 반영 (2026-10-11 사용자 요청).

`문서\\카카오톡 받은 파일`에서 가장 최근 '*편성표*.xlsx'를 찾아 반영한다. 전체 조 참조는 갱신하고, A조 근무표는
저장본 없는 새 날짜만 바로 저장한다. 이미 저장된 날짜가 바뀌거나 원본 오기·연차 충돌이면 '확인 필요'로 모은다
(upload_review). 같은 파일(크기·수정시각 또는 내용)이면 다시 읽지 않는다.
"""
from __future__ import annotations

import hashlib
import json
from datetime import date
from pathlib import Path

KAKAO_DIR = Path.home() / "Documents" / "카카오톡 받은 파일"
MARKER = "kakao_schedule_source.json"


def newest(folder: Path = KAKAO_DIR) -> Path | None:
    files = [p for p in Path(folder).glob("*편성표*.xls[xm]") if not p.name.startswith("~$")]
    return max(files, key=lambda p: (p.stat().st_mtime_ns, p.name)) if files else None


def leave_folder(default: Path, folder: Path = KAKAO_DIR) -> Path:
    """연차일정 텍스트: 업무일지 폴더와 카톡 받은 파일 폴더 중 더 최근 '*연차*.txt'가 있는 폴더 (2026-10-11)."""
    def latest(where):
        files = [p for p in Path(where).glob("*연차*.txt") if not p.name.startswith("~$")]
        return max((p.stat().st_mtime_ns for p in files), default=-1)
    return Path(folder) if latest(folder) > latest(default) else Path(default)


def recycle(paths) -> int:
    """파일을 Windows 휴지통으로 (완전 삭제 아님). 휴지통을 못 쓰는 환경이면 그대로 둔다."""
    import ctypes
    from ctypes import wintypes
    paths = [str(Path(p).resolve()) for p in paths if Path(p).exists()]
    if not paths:
        return 0

    class SHFILEOPSTRUCTW(ctypes.Structure):
        _fields_ = [("hwnd", wintypes.HWND), ("wFunc", wintypes.UINT), ("pFrom", wintypes.LPCWSTR),
                    ("pTo", wintypes.LPCWSTR), ("fFlags", ctypes.c_uint16), ("fAnyOperationsAborted", wintypes.BOOL),
                    ("hNameMappings", ctypes.c_void_p), ("lpszProgressTitle", wintypes.LPCWSTR)]
    FO_DELETE, FOF_ALLOWUNDO, FOF_NOCONFIRMATION, FOF_SILENT, FOF_NOERRORUI = 3, 0x40, 0x10, 0x4, 0x400
    op = SHFILEOPSTRUCTW(None, FO_DELETE, "\0".join(paths) + "\0\0", None,
                         FOF_ALLOWUNDO | FOF_NOCONFIRMATION | FOF_SILENT | FOF_NOERRORUI, False, None, None)
    try:
        return len(paths) if ctypes.windll.shell32.SHFileOperationW(ctypes.byref(op)) == 0 else 0
    except (AttributeError, OSError):
        return 0


def purge_overwrite_copies(store: Path) -> int:
    """덮어쓴 이전 근무표: 날짜별 직전 1개만 남김 (upload_review, 2026-10-11 사용자 확정)."""
    from .upload_review import purge_overwrite_copies as keep_one
    return keep_one(store)


def sync(store: Path, folder: Path = KAKAO_DIR, start: date = date(2026, 9, 1)) -> str | None:
    """새 파일이면 반영하고 안내 문구를 돌려준다. 바뀐 게 없으면 None. 읽기 실패는 예외(다음 화면에서 다시 시도)."""
    from . import bulk_import, order_source
    from .calendar_info import is_off_day
    from .day_shift import load_roster
    store = Path(store)
    path = newest(folder)
    if path is None:
        return None
    stamp = {"path": str(path), "size": path.stat().st_size, "mtime": path.stat().st_mtime_ns}
    marker = store / MARKER
    if marker.exists() and json.loads(marker.read_text(encoding="utf-8")).get("stamp") == stamp:
        return None
    data = path.read_bytes()
    digest = hashlib.sha256(data).hexdigest()
    if (store / "source_files" / f"{digest}.xlsx").exists():   # 이미 올린 파일과 내용이 같음
        marker.write_text(json.dumps({"stamp": stamp, "sha256": digest}, ensure_ascii=False), encoding="utf-8")
        return None
    from .upload_review import save_pending, triage
    references = order_source.parse_uploaded(data, path.name)
    plans = triage(store, bulk_import.plan(data, store, store / "day", file_name=path.name,
                                           day_roster=load_roster(store / "day_roster.json"), start=start,
                                           is_off_day=is_off_day, force=True))
    todo = [p for p in plans if p.status == "new"]          # 저장본 없는 날짜만 자동 저장
    saved = bulk_import.apply(todo, store, store / "day")
    referenced = order_source.publish_uploaded(store, data, path.name, references)
    waiting = save_pending(store, plans, digest, path.name)
    purge_overwrite_copies(store)
    marker.write_text(json.dumps({"stamp": stamp, "sha256": digest}, ensure_ascii=False), encoding="utf-8")
    from .upload_review import SHIFT
    added = ", ".join(f"{p.day:%m/%d} {SHIFT.get(p.shift, p.shift)}" for p in todo) or "없음"
    text = f"카톡으로 받은 새 편성표 반영: {path.name} · 전체 조 {referenced}일 참조 갱신 · 새 날짜 {saved}건 저장({added})"
    if waiting:
        text += f" · 이미 저장된 날짜가 바뀌거나 오기·연차 충돌인 {waiting}건은 '📥 파일 업로드' 칸에서 확인해 주세요"
    return text
