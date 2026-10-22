"""연차일정(텍스트) → 날짜를 고르면 근무자 상태 기본값 (2026-10-04 사용자 요청).

- 연차일정 파일(예: '연차일정(2026).txt')을 날짜별 줄로 읽는다. 다른 조 줄도 섞여 있으므로 이름으로만 맞춘다
  (이성호 → 성호처럼 이름 뒤 두 글자가 명단 이름과 같으면 그 사람). 통제A는 박인철·백원석 조장.
- 상태: 연차 / 반차(야간 전반부·후반부, 주간 오전·오후) / 기타(교육·예비군·휴가 등, 그날 근무에서 빠짐 + 비고).
  입사·퇴사·편입·지원·대근 같은 인사 줄은 상태를 바꾸지 않는다. 전·후반을 알 수 없는 '반차'는 바꾸지 않고 안내만 한다.
- 사용자가 화면에서 고른 '기타' 비고는 status_notes.json에 날짜별로 따로 저장한다 (근무표 계산에는 넣지 않음).
"""
from __future__ import annotations

import json
import re
from datetime import date, timedelta, datetime
from uuid import uuid4
from pathlib import Path

MANAGER_NAMES = ("박인철", "백원석")          # 통제A (박인철 조장 퇴사 후 백원석 조장)
NIGHT_FIRST, NIGHT_LATE = "전반부 반차 (01시 출근)", "후반부 반차 (01시 퇴근)"
OTHER = "기타"

_DATE = re.compile(r"^\s*0?(\d{1,2})\s*월\s*0?(\d{1,2})\s*일?")
_LINE = re.compile(r"^\s*(?:([A-D])\s*조\s*)?(?:(?:보안|관제|안내|주차|신입|신규)\s*)?"
                   r"([가-힣]{2,4})\s*(?:\(([^)]*)\))?\s*(?:(?:사원|선임|조장|팀장|부팀장|부탐장|파트장|이사|실장|차장|대리)님?)?"
                   r"\s*-\s*(.*?)\s*$")
_PERSONNEL = ("입사", "퇴사", "편입", "지원", "대근", "전입", "전출", "명단 제외", "명단제외")
LEAVE_FILE, NOTES_FILE = "leave_schedule.txt", "status_notes.json"


def parse(text: str, year: int = 2026) -> dict[date, list[dict]]:
    """{날짜: [{"team", "name", "kind"}]} — 날짜 줄 아래 '조 이름 직급 - 내용' 줄."""
    out: dict[date, list[dict]] = {}
    current = None
    for raw in text.splitlines():
        line = raw.strip()
        if not line:
            continue
        m = _DATE.match(line)
        if m and "-" not in line:
            try:
                current = date(year, int(m[1]), int(m[2]))
            except ValueError:
                current = None
            continue
        m = _LINE.match(line)
        if current is None or not m or not m[4].strip():
            continue
        kind = m[4].strip()
        if m[3]:                                   # '이성호(오전) 사원 - 교육' → 교육(오전)
            kind = f"{kind}({m[3]})"
        out.setdefault(current, []).append({"team": m[1] or "", "name": m[2], "kind": kind})
    return out


def classify(kind: str, shift: str) -> tuple[str | None, str]:
    """(상태 또는 None, 비고). shift = 'night' | 'day'. None = 상태를 바꾸지 않음."""
    k = kind.replace(" ", "")
    if "반차" in k:
        if shift == "night":
            if "오전" in k or "오후" in k:              # 주간 표현 — 야간 전·후반과 같다고 단정하지 않음
                return None, f"반차(야간 전·후반 확인 필요): {kind}"
            if any(w in k for w in ("전반부", "전반야", "전야", "전반")):
                return NIGHT_FIRST, ""
            if any(w in k for w in ("후반부", "후반야", "후반")):
                return NIGHT_LATE, ""
        else:
            if "오전" in k or "전반" in k:
                return "오전반차", ""
            if "오후" in k or "후반" in k:
                return "오후반차", ""
        return None, f"반차(전·후반 확인 필요): {kind}"
    if "연차" in k:
        return "연차", ""
    if any(w in k for w in _PERSONNEL):
        return None, ""
    return OTHER, kind


def short_name(full: str, names) -> str | None:
    """'이성호' → '성호' (명단에 있는 이름일 때만). 통제A 이름은 'A'."""
    if full in MANAGER_NAMES:
        return "A"
    for name in names:
        if full == name or (len(full) >= 3 and full[-len(name):] == name):
            return name
    return None


def night_unavailable_slots(status: str) -> set[int]:
    """야간 상태 → 근무불가 슬롯 (0=18시 … 13=07시). 룰북 21-7: 후반부 반차 01시~, 전반부 반차 ~00시."""
    if status == NIGHT_LATE:
        return set(range(7, 14))
    if status == NIGHT_FIRST:
        return set(range(0, 7))
    if status in ("연차", OTHER):
        return set(range(14))
    return set()


def defaults_for(entries: dict, day: date, shift: str, names) -> tuple[dict, list[str]]:
    """{명단 이름 또는 'A': (상태, 비고)}, 안내 문장들."""
    statuses, notices = {}, []
    for e in entries.get(day, []):
        who = short_name(e["name"], names)
        if who is None:
            continue
        status, note = classify(e["kind"], shift)
        if e.get("manual"):
            presence = e.get("presence", "자동")
            if presence == "미출근":
                status, note = ("연차", "") if e["kind"] == "연차" else (OTHER, e["kind"])
            elif presence == "출근" and status in ("연차", OTHER):
                status, note = "출근", ""
            elif e["kind"] == "출근":
                status, note = "출근", ""
            elif e["kind"] in ("야간지원", "주간지원"):
                target = "night" if e["kind"] == "야간지원" else "day"
                status, note = ("출근", "") if shift == target else (OTHER, e["kind"])
        if status is None:
            if note:
                notices.append(f"{e['name']}: {note}")
            continue
        statuses[who] = (status, note)
    return statuses, notices


# ---------------------------------------------------------------- 저장 (history 폴더)
def save_text(store: Path, text: str) -> Path:
    Path(store).mkdir(parents=True, exist_ok=True)
    path = Path(store) / LEAVE_FILE
    path.write_text(text, encoding="utf-8")
    return path


def replace_uploaded_text(store: Path, text: str) -> Path:
    """업로드 원본을 최종 일정으로: 기존 직접 등록·출근 정정은 백업 후 초기화."""
    if not parse(text):
        raise ValueError('연차일정에서 날짜별 항목을 읽지 못했습니다. 기존 일정은 유지합니다.')
    store = Path(store)
    store.mkdir(parents=True, exist_ok=True)
    trash = store / '.trash'
    stamp = datetime.now().strftime('%Y%m%d_%H%M%S_%f')
    import shutil
    for filename in (LEAVE_FILE, 'manual_leave.json', 'attendance_fix.json'):
        path = store / filename
        if path.exists():
            trash.mkdir(exist_ok=True)
            shutil.copy2(path, trash / f'upload_replace_{stamp}_{filename}')
    path = save_text(store, text)
    (store / 'manual_leave.json').write_text('[]', encoding='utf-8')
    (store / 'attendance_fix.json').write_text('{}', encoding='utf-8')
    # 현재 폴더 원본이 첫 동기화에서 방금 업로드한 내용을 되돌리지 않게 한다.
    from .order_source import SOURCE_DIR
    import os
    folder = Path(os.environ.get('NIGHT_SHIFT_SOURCE_DIR') or SOURCE_DIR)
    files = [p for p in folder.glob('*연차*.txt') if not p.name.startswith('~$')]
    if files:
        source = max(files, key=lambda p: (p.stat().st_mtime_ns, p.name))
        marker = {'path': str(source), 'size': source.stat().st_size, 'mtime': source.stat().st_mtime_ns}
        (store / 'folder_leave_source.json').write_text(json.dumps(marker, ensure_ascii=False), encoding='utf-8')
    from .source_attachment import stash
    stash(store,text.encode('utf-8'),LEAVE_FILE)
    for previous in trash.glob('upload_replace_*_leave_schedule.txt'):
        if previous.resolve().parent==trash.resolve():previous.unlink()
    return path


def load(store: Path, year: int = 2026) -> dict[date, list[dict]]:
    path = Path(store) / LEAVE_FILE
    try:
        entries = parse(path.read_text(encoding="utf-8"), year)
    except OSError:
        entries = {}
    # 이전 날짜별 출근 정정도 달력/편성/일보의 같은 일정 입력으로 읽는다.
    from .daily_report import load_attendance_fixes
    for iso, fixes in load_attendance_fixes(store).items():
        current = date.fromisoformat(iso)
        if current.year != year:
            continue
        entries[current] = [e for e in entries.get(current, []) if e["name"] not in fixes]
        entries[current] += [{"name": name, "team": f.get("team", ""), "kind": f["kind"]}
                             for name, f in fixes.items() if f["kind"] != "출근"]
    for item in load_manual(store):
        start, end = date.fromisoformat(item["start"]), date.fromisoformat(item["end"])
        current = max(start, date(year, 1, 1))
        end = min(end, date(year, 12, 31))
        while current <= end:
            entries[current] = [e for e in entries.get(current, []) if e["name"] != item["name"]]
            if item.get("kind") != HIDE_KIND:              # 원본 숨김(10/23): 그날 그 사람 일정을 지우기만 한다
                entries[current].append({**item, "manual": True})
            current += timedelta(days=1)
    return entries


MANUAL_FILE = "manual_leave.json"
# 연차일정 달력에서 원본(파일) 일정을 지울 때 남기는 직접 등록 종류 (2026-10-23 사용자 확정): 원본 파일은 고치지 않고
# 그 사람·그 날짜 일정을 숨긴다. 새 연차일정 파일을 올리면 다른 직접 등록처럼 초기화된다.
HIDE_KIND = "원본 숨김"


def hide_original(store: Path, name: str, team: str, day: date) -> str:
    """원본 일정 하루 숨김 = 그날만 '원본 숨김' 직접 등록 (기간 일정이면 나머지 날은 그대로)."""
    return save_manual(store, name, team, day, day, HIDE_KIND, note="달력에서 삭제")


def refresh_manual_inputs(state, store: Path, day: date, mode: str) -> bool:
    """직접 일정이 바뀌면 그 날짜의 편성 입력만 초기화(저장 근무표는 보존)."""
    signature = json.dumps(load(store, day.year).get(day, []),
                           ensure_ascii=False, sort_keys=True)
    key = f"manual_input_signature_{mode}_{day}"
    previous = state.get(key, "[]")
    state[key] = signature
    if previous == signature:
        return False
    keys = {"night": ["night_status_date", f"night_roster_{day}", "night_roster", "night_roster_nonce"],
            "day": [f"day_statuses_{day}", f"day_roster_{day}", f"day_control_{day}", f"day_roster_picker_{day}", "day_roster_nonce"],
            "weekend": [f"wd_statuses_{day}", f"wd_roster_{day}", f"wd_roster_picker_{day}", "wd_roster_nonce"]}
    for name in keys[mode]:
        state.pop(name, None)
    return True


def load_manual(store: Path) -> list[dict]:
    try:
        return json.loads((Path(store) / MANUAL_FILE).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return []


def _write_manual(store: Path, items: list[dict]) -> None:
    store = Path(store)
    store.mkdir(parents=True, exist_ok=True)
    path = store / MANUAL_FILE
    if path.exists():
        backup = store / ".trash" / f"manual_leave_{datetime.now():%Y%m%d_%H%M%S_%f}.json"
        backup.parent.mkdir(parents=True, exist_ok=True)
        backup.write_bytes(path.read_bytes())
    temporary = path.with_suffix(".tmp")
    temporary.write_text(json.dumps(items, ensure_ascii=False, indent=2), encoding="utf-8")
    temporary.replace(path)


def save_manual(store: Path, name: str, team: str, start: date, end: date, kind: str,
                note: str = "", presence: str = "자동", item_id: str | None = None) -> str:
    if not name.strip() or not kind.strip() or end < start:
        raise ValueError("인원·일정 종류를 입력하고 종료일을 시작일 이후로 지정하세요.")
    if presence not in ("자동", "출근", "미출근"):
        raise ValueError("출근 여부가 올바르지 않습니다.")
    items = load_manual(store)
    for item in items:
        if item["id"] != item_id and item["name"] == name and start <= date.fromisoformat(item["end"]) and end >= date.fromisoformat(item["start"]):
            raise ValueError("같은 사람의 직접 등록 일정과 기간이 겹칩니다. 기존 일정을 수정하세요.")
    item_id = item_id or uuid4().hex
    updated = {"id": item_id, "name": name, "team": team, "start": start.isoformat(),
               "end": end.isoformat(), "kind": kind.strip(), "note": note.strip(), "presence": presence}
    items = [item for item in items if item["id"] != item_id] + [updated]
    _write_manual(store, items)
    return item_id


def delete_manual(store: Path, item_id: str) -> None:
    items = load_manual(store)
    remaining = [item for item in items if item["id"] != item_id]
    if remaining != items:
        _write_manual(store, remaining)


def load_notes(store: Path) -> dict:
    try:
        return json.loads((Path(store) / NOTES_FILE).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def save_notes(store: Path, day: date, shift: str, notes: dict[str, str]) -> None:
    """화면에서 고른 '기타' 비고 {이름: 비고}. 바뀐 경우만 쓴다."""
    data = load_notes(store)
    current = data.get(day.isoformat(), {}).get(shift, {})
    if current == notes:
        return
    data.setdefault(day.isoformat(), {})[shift] = notes
    Path(store).mkdir(parents=True, exist_ok=True)
    (Path(store) / NOTES_FILE).write_text(json.dumps(data, ensure_ascii=False, indent=1), encoding="utf-8")


def other_labels(store: Path, day: date, shift: str, names) -> dict[str, str]:
    """그날 '기타'로 빠진 사람 {이름: 비고}: 화면에서 저장한 비고가 먼저, 없으면 연차일정."""
    saved = load_notes(store).get(day.isoformat(), {}).get(shift)
    if saved:
        return dict(saved)
    statuses, _ = defaults_for(load(store, day.year), day, shift, names)
    return {name: note for name, (status, note) in statuses.items() if status == OTHER}
