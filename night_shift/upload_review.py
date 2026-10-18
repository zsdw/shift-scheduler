"""편성표 업로드: 새 파일은 '제안', 저장본은 '확정' (2026-10-11 사용자 확정).

- 저장본이 없는 날짜는 바로 저장한다(원본 오기·연차 충돌이 없을 때).
- 이미 저장된 날짜가 바뀌면 바로 덮어쓰지 않고 '확인 필요'로 모은다(무엇이 바뀌는지 요약). 사용자가 반영/기존 유지.
- 원본 오기(치명 오류)·연차 충돌(연차인 사람이 근무표에 있음)도 '확인 필요'. 오기는 반영할 수 없고 기존 유지만.
- 한 번 처리한 원본은 기억한다: 그 원본으로 저장했거나(source_hash) '기존 유지'를 고른 날짜 원본(upload_ignore.json)이
  다음 파일에도 그대로면 건드리지 않는다. 프로그램에서 고친 내용이 다음 업로드로 되돌아가지 않는다.
- 덮어쓴 이전 근무표는 날짜별로 직전 1개만 보관하고 [되돌리기]로 돌아갈 수 있다.
"""
from __future__ import annotations

import json
import shutil
from datetime import date, datetime
from pathlib import Path

IGNORE_FILE = "upload_ignore.json"
PENDING_FILE = "upload_pending.json"
SHIFT = {"night": "야간", "day": "주간", "weekend": "휴일 주간"}


def _store_for(store: Path, shift: str) -> Path:
    return Path(store) if shift == "night" else Path(store) / ("weekend_day" if shift == "weekend" else "day")


def _read(path: Path, default):
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return default


def _write(path: Path, value) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=1), encoding="utf-8")


# ---------------------------------------------------------------- 한 번 처리한 원본
def ignore(store: Path, day: date, shift: str, digest: str) -> None:
    data = _read(Path(store) / IGNORE_FILE, {})
    key = f"{day.isoformat()}|{shift}"
    data[key] = sorted(set(data.get(key, [])) | {digest})
    _write(Path(store) / IGNORE_FILE, data)


def handled(store: Path, day: date, shift: str, digest: str) -> bool:
    """그 원본으로 저장했거나 사용자가 '기존 유지'를 고른 원본이면 True."""
    if digest in _read(Path(store) / IGNORE_FILE, {}).get(f"{day.isoformat()}|{shift}", []):
        return True
    saved = _read(_store_for(store, shift) / f"{day.isoformat()}.json", {})
    return saved.get("source_hash") == digest


# ---------------------------------------------------------------- 연차 충돌·바뀐 내용
def _working(record, shift: str) -> list[str]:
    if shift == "night":
        names = {e.employee_id: e.name for e in record.context.employees}
        return [names[a.employee_id] for a in record.context.attendance
                if a.present and a.employee_id != "A" and a.display_number is not None]
    if shift == "weekend":
        return [record.names[p] for p, row in record.grid.items() if p != "A" and any(v != "×" for v in row)]
    return [p.name for p in record.people if p.number]


def leave_conflicts(store: Path, day: date, shift: str, record) -> list[str]:
    """연차일정상 그날 그 근무에 안 나오는 사람(연차·휴가·교육 등)이 근무표에 있으면 그 이름들."""
    from .leave_schedule import defaults_for, load
    entries = load(Path(store), day.year)
    a_team = {day: [e for e in entries.get(day, []) if e.get("team", "A") in ("A", "", None)]}
    working = _working(record, shift)
    statuses, _ = defaults_for(a_team, day, "day" if shift == "weekend" else shift, working)
    return [f"{name} {status if status != '기타' else note or '미출근'}"
            for name, (status, note) in statuses.items() if name in working and status in ("연차", "기타")]


def _cells(record, shift: str) -> dict:
    """{이름: [시간칸별 표시]}"""
    if shift == "day":
        return {name: list(row) for name, row in record.grid.items() if any(v is not None for v in row)}
    if shift == "weekend":
        return {record.names.get(p, p): list(row) for p, row in record.grid.items()}
    names = {e.employee_id: ("통제A" if e.employee_id == "A" else e.name) for e in record.context.employees}
    present = {a.employee_id for a in record.context.attendance if a.present}
    out = {}
    for r in record.assignments:
        if r.employee_id in present:                   # G3 = G2 두 번째 사람(현장 표기) → 같은 근무로
            label = "G2" if r.displayed_assignment.label == "G3" else r.displayed_assignment.label
            out.setdefault(names[r.employee_id], [None] * 14)[r.slot.index] = label
    return out


def changes(store: Path, day: date, shift: str, record) -> str:
    """저장본 → 새 원본에서 바뀌는 내용 한 줄 요약."""
    path = _store_for(store, shift) / f"{day.isoformat()}.json"
    if not path.exists():
        return "새 날짜"
    try:
        if shift == "night":
            from .history_store import actual_record
            old = actual_record(Path(store), day)
        elif shift == "weekend":
            from .weekend_day import load as load_weekend
            old = load_weekend(Path(store) / "weekend_day", day.isoformat())
        else:
            from .day_shift import load_day
            old = load_day(Path(store) / "day", day)["schedule"]
    except (OSError, ValueError, KeyError):
        return "저장본을 읽지 못함 — 원본으로 교체"
    a, b = _cells(old, shift), _cells(record, shift)
    parts = [f"{n} 빠짐" for n in a if n not in b] + [f"{n} 추가" for n in b if n not in a]
    first = 18 if shift == "night" else 8
    diffs = [f"{(first + t) % 24:02d}시 {n} {a[n][t] or '-'}→{b[n][t] or '-'}"
             for n in a if n in b for t in range(len(a[n])) if a[n][t] != b[n][t]]
    parts += diffs[:4]
    if len(diffs) > 4:
        parts.append(f"외 {len(diffs) - 4}칸")
    return " · ".join(parts) or "시간별 포스트 같음"


# ---------------------------------------------------------------- 분류
def triage(store: Path, plans: list) -> list:
    """plan() 결과를 '바로 저장(new)' / '확인 필요(review)' / 'same' / 'skip'(주말 등)으로. plans를 고쳐서 돌려준다."""
    for p in plans:
        if p.status == "same":
            continue
        if handled(store, p.day, p.shift, p.digest):
            p.status, p.reason = "same", "이전에 처리한 원본(프로그램에서 고친 내용 유지)"
            continue
        if p.status == "skip":
            if "주말·공휴일" not in p.reason:
                p.status, p.reason = "review", "원본 오기: " + p.reason
                p.can_apply = False
            continue
        conflicts = leave_conflicts(store, p.day, p.shift, p.record)
        if conflicts:
            p.status, p.reason = "review", "연차 충돌: " + ", ".join(conflicts) + " (연차일정상 안 나옴)"
            p.can_apply = True
        elif p.status == "changed":
            p.status, p.reason = "review", changes(store, p.day, p.shift, p.record)
            p.can_apply = True
    return plans


def save_pending(store: Path, plans: list, digest: str, file_name: str) -> int:
    items = [{"day": p.day.isoformat(), "shift": p.shift, "digest": p.digest, "reason": p.reason,
              "can_apply": getattr(p, "can_apply", True)} for p in plans if p.status == "review"]
    _write(Path(store) / PENDING_FILE, {"file_sha": digest, "file": file_name, "items": items})
    return len(items)


def pending(store: Path) -> dict:
    return _read(Path(store) / PENDING_FILE, {"items": []})


def resolve(store: Path, decisions: dict) -> tuple[int, int]:
    """decisions = {'날짜|shift': 'apply' | 'keep'} → (반영 수, 기존 유지 수)."""
    from . import bulk_import
    from .calendar_info import is_off_day
    from .day_shift import load_roster
    store = Path(store)
    info = pending(store)
    source = store / "source_files" / f"{info.get('file_sha', '')}.xlsx"
    chosen = {k: v for k, v in decisions.items() if v in ("apply", "keep")}
    apply_keys = {k for k, v in chosen.items() if v == "apply"}
    applied = kept = 0
    if apply_keys:
        if not source.exists():
            raise ValueError("확인할 원본 파일이 없습니다. 편성표를 다시 올려 주세요.")
        plans = bulk_import.plan(source.read_bytes(), store, store / "day", file_name=info.get("file", ""),
                                 day_roster=load_roster(store / "day_roster.json"), start=date(2000, 1, 1),
                                 is_off_day=is_off_day, force=True)
        todo = [p for p in plans if f"{p.day.isoformat()}|{p.shift}" in apply_keys and p.record is not None]
        for p in todo:
            p.status = "changed" if (_store_for(store, p.shift) / f"{p.day.isoformat()}.json").exists() else "new"
        applied = bulk_import.apply(todo, store, store / "day")
        purge_overwrite_copies(store)
    items = []
    for item in info.get("items", []):
        key = f"{item['day']}|{item['shift']}"
        if chosen.get(key) == "keep":
            ignore(store, date.fromisoformat(item["day"]), item["shift"], item["digest"])
            kept += 1
        elif key not in apply_keys:
            items.append(item)
    _write(store / PENDING_FILE, {**info, "items": items})
    return applied, kept


# ---------------------------------------------------------------- 직전 버전 1개·되돌리기
COPY_PATTERNS = ("*__deleted-import-*.json", "*__deleted-image-*.json", "*__deleted-revert-*.json")


def _copies(folder: Path, day: str | None = None) -> list[Path]:
    """최근에 덮어쓴 순서(파일 이름의 덮어쓴 시각 기준, 복사본 수정시각은 원래 저장 시각이라 쓰지 않음)."""
    import re
    found = [p for pattern in COPY_PATTERNS for p in folder.glob(pattern) if day is None or p.name.startswith(day + "__")]
    stamp = lambda p: (re.search(r"(\d{8}-\d{6,})", p.name.split("__", 1)[-1]) or [""])[0]  # noqa: E731
    return sorted(found, key=stamp, reverse=True)


def purge_overwrite_copies(store: Path) -> int:
    """덮어쓴 이전 근무표는 날짜별 가장 최근 1개만 남기고 Windows 휴지통으로 (2026-10-11 사용자 확정)."""
    from .kakao_sync import recycle
    old = []
    for folder in (Path(store) / ".trash", Path(store) / "day" / ".trash", Path(store) / "weekend_day" / ".trash"):
        seen = set()
        for p in _copies(folder):
            day = p.name.split("__")[0]
            if day in seen:
                old.append(p)
            seen.add(day)
    return recycle(old)


def previous(store: Path, day: date, shift: str) -> Path | None:
    found = _copies(_store_for(store, shift) / ".trash", day.isoformat())
    return found[0] if found else None


def revert(store: Path, day: date, shift: str) -> None:
    """직전 버전으로 되돌린다(지금 것은 직전 버전 자리로 — 다시 누르면 원래대로). 되돌린 원본은 다음 업로드에서 무시."""
    folder = _store_for(store, shift)
    path, prev = folder / f"{day.isoformat()}.json", previous(store, day, shift)
    if prev is None or not path.exists():
        raise ValueError("되돌릴 직전 버전이 없습니다.")
    current = _read(path, {})
    if current.get("source_hash"):
        ignore(store, day, shift, current["source_hash"])
    keep = folder / ".trash" / f"{day.isoformat()}__deleted-revert-{datetime.now():%Y%m%d-%H%M%S%f}.json"
    shutil.copy2(path, keep)
    restored = _read(prev, None)
    if restored is None:
        raise ValueError("직전 버전 파일을 읽지 못했습니다.")
    if restored.get("source_hash"):                   # 되돌린 버전이 다음 업로드에서 다시 '바뀜'으로 잡히지 않게
        data = _read(Path(store) / IGNORE_FILE, {})
        key = f"{day.isoformat()}|{shift}"
        data[key] = [d for d in data.get(key, []) if d != restored["source_hash"]]
        _write(Path(store) / IGNORE_FILE, data)
    shutil.copy2(prev, path)
    prev.unlink()
    purge_overwrite_copies(store)


def revert_button(store: Path, day: date, shift: str, key: str, where=None) -> None:
    """저장본 옆 [↩ 이전 버전] 버튼 (PC·폰 공통)."""
    import streamlit as st
    where = where or st
    prev = previous(store, day, shift)
    if prev is None:
        return
    when = datetime.fromtimestamp(prev.stat().st_mtime)
    if where.button("↩ 이전 버전으로", key=f"revert-{key}", help=f"덮어쓰기 전 근무표({when:%m/%d %H:%M} 저장분)로 되돌립니다. "
                                                                "다시 누르면 지금 것으로 돌아옵니다."):
        try:
            revert(store, day, shift)
        except ValueError as exc:
            st.error(str(exc))
        else:
            st.rerun()
