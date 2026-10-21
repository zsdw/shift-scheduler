"""편성표 엑셀(날짜별 '(주)'·'(야)' 시트) 일괄 가져오기 (2026-10-04 사용자 요청).

- 한 파일에 여러 날짜 시트가 있고, 파일은 미래 날짜가 조금씩 쌓이며 다시 올라온다. 올릴 때마다 A조·시작일 이후
  날짜를 모두 덮어쓰되, 시트 내용 지문(source_hash)이 저장본과 같은 날짜는 건너뛴다. 바뀐 날짜만 다시 만들어
  저장하므로 매번 전체를 검증하지 않는다. 특이사항·밸런스 판정은 화면에서 저장본으로 다시 계산된다.
- 야간: 모두 FM(사용자 확정). 차단봉은 20시·04시 보안실 대기자(통제 제외) 1명을 설치·철수자로 본다(FM 11-2·11-3).
  통제E(지원)가 있으면 E를 통제 자리로 기록하고, 함께 적힌 통제A(동행)는 비고에만 남긴다. 이런 날은 통제 쪽
  밸런스·격차 경고를 비고에서 뺀다(사용자 확정: 일반근무자 특이사항만).
- 주간: 평일 주간 시트만. 주말·공휴일 주간은 앱이 아직 지원하지 않아 건너뛴다.
- 하단 특이사항(폐문·시건 등)은 근무에 반영하지 않고 비고에 참고로만 적는다.
"""
from __future__ import annotations

import hashlib
import io
import json
import re
from dataclasses import dataclass, field
from datetime import date
from pathlib import Path

from . import history_import as imp
from . import history_store
from .day_shift import (DayPerson, DaySchedule, EDU, PATROL, POSTS, REST, STANDBY, load_day, save_day)
from .models import HistoryInput, Mode

SHEET = re.compile(r"(\d{2})년\s*0?(\d{1,2})월\s*0?(\d{1,2})\s*일?\s*\((주|야)\)")
TEAM = re.compile(r"근무조\s*:?\s*([A-D])\s*조")
NIGHT_HEADERS = {"보안실/대기": "보안실", "보안실대기": "보안실"}
ROSTER_IDS = {name: eid for eid, name in imp.ROSTER.items() if eid != "A"}     # 만년 → '1' ...


@dataclass
class Plan:
    day: date
    shift: str                 # 'night' | 'day'
    sheet: str
    digest: str
    status: str = ""           # new | changed | same | skip
    reason: str = ""
    record: object = None      # 야간 ShiftRecord / 주간 DaySchedule
    note: str = ""
    warnings: list = field(default_factory=list)
    source_file: str = ""
    source_review: dict = field(default_factory=dict)
    source_bytes: bytes = field(default=b"",repr=False)


def _digest(rows) -> str:
    return hashlib.sha256(json.dumps(rows, ensure_ascii=False, default=str).encode("utf-8")).hexdigest()


def scan(data: bytes, team: str = "A", start: date = date(2026, 9, 1)) -> list[tuple[date, str, str, list]]:
    """[(날짜, shift, 시트 이름, 값 행들)] — 같은 날짜·근무가 여러 시트면 뒤에 있는 시트(수정본)를 쓴다."""
    from openpyxl import load_workbook
    book = load_workbook(io.BytesIO(data), read_only=True, data_only=True)
    found = {}
    try:
        for ws in book.worksheets:
            m = SHEET.search(ws.title)
            if not m:
                continue
            day = date(2000 + int(m[1]), int(m[2]), int(m[3]))
            if day < start:
                continue
            rows = [list(r[:90]) for r in ws.iter_rows(min_row=1, max_row=40, values_only=True)]
            head = " ".join(str(v) for r in rows[:4] for v in r if v is not None)
            t = TEAM.search(head)
            if not t or t[1] != team:
                continue
            found[day, "night" if m[4] == "야" else "day"] = (ws.title, rows)
    finally:
        book.close()
    return [(d, s, title, rows) for (d, s), (title, rows) in sorted(found.items())]


def _norm(v) -> str:
    return re.sub(r"\s+", "", str(v or ""))


def _names(rows) -> tuple[dict, set]:
    """명단 칸: {'1': '만년', ...}, {'A', 'E', 'D'} (통제 표기)."""
    numbered, controls = {}, set()
    for r in rows[:8]:
        for v in r:
            s = _norm(v)
            m = re.fullmatch(r"(\d{1,2})[.,·\-]?([가-힣]{2,4})", s)   # '8.세명'처럼 점 찍힌 칸도 (2026-10-21)
            if m:
                numbered[m[1]] = m[2]
            m = re.fullmatch(r"통제([A-Z])", s)
            if m:
                controls.add(m[1])
    return numbered, controls


def _header(rows, needed) -> tuple[int, dict]:
    for i, r in enumerate(rows):
        heads = {}
        for j, v in enumerate(r):
            h = _norm(v).upper()
            h = NIGHT_HEADERS.get(h, h)
            if h and h not in heads:
                heads[h] = j
        if needed <= set(heads):
            return i, heads
    raise ValueError("근무시간·포스트 열 제목 줄을 찾지 못했습니다.")


def _tokens(value) -> list[str]:
    return [t for t in re.split(r"[.,·\s/]+", str(value or "").upper().replace("통제", "")) if t]


def _special_text(rows) -> str:
    for r in rows:
        if r and _norm(r[0]) == "특이사항":
            text = next((str(v) for v in r[1:] if v not in (None, "")), "")
            return re.sub(r"\s{2,}", " · ", text.replace("\n", " ")).strip(" ·")
    return ""


# ---------------------------------------------------------------- 야간
def night_record(day: date, rows, file_name: str = "", sheet: str = "", leave=None, newcomers=(), saved=None):
    """(ShiftRecord, 비고, 경고들). 읽을 수 없는 칸이 있으면 ValueError.

    leave = 연차일정 {이름: (상태, 비고)} — 반차·연차 시간의 빈칸은 휴게가 아니라 근무불가(룰북 21-7)."""
    numbered, controls = _names(rows)
    if not controls & {"A", "E"}:
        raise ValueError("통제A·통제E가 명단에 없어 관리자 자리를 알 수 없습니다.")
    use_e = "E" in controls
    from collections import Counter
    dup = sorted(n for n, c in Counter(numbered.values()).items() if c > 1)
    if dup:                                              # 2026-10-11: 이름으로 합치지 않는다 → 그 날짜는 건너뜀
        raise ValueError("명단 오기: " + ", ".join(f"{n}이(가) 두 번호에 적힘" for n in dup) + " → 이 날짜는 건너뜀")
    numbered={p:n for p,n in numbered.items() if p not in newcomers}
    unknown = [n for n in numbered.values() if n not in ROSTER_IDS]
    if unknown or any(int(k) not in range(1, 7) for k in numbered):
        raise ValueError(f"야간 명단에 없는 이름이나 번호: {', '.join(unknown) or numbered}")
    index, heads = _header(rows, {"G1", "L3", "I1"})
    time_col = heads.get("근무시간", 0)
    valid = set(numbered) | {"A"}
    known = valid | set(newcomers)
    cells, notes = [], []
    from .schedule_image_import import persons
    for body in rows[index + 1:]:
        hour = imp.hour_of(body[time_col] if time_col < len(body) else None)
        if hour is None:
            continue
        item = {"hour": hour}
        texts = {post: _cell_text(body[heads[post.upper()]]) if heads.get(post.upper()) is not None
                 and heads[post.upper()] < len(body) else "" for post in imp.POSTS}
        for post, text in texts.items():                 # 점이 빠진 칸('E.CP235')은 옆 칸을 보고 쪼갠다 (2026-10-11)
            if not text:
                continue
            try:
                persons(text)
            except ValueError:
                others = set()
                for p2, t2 in texts.items():
                    if p2 != post and t2:
                        try:
                            others.update(persons(t2))
                        except ValueError:
                            pass
                fixed = _repair(text, known, others)
                if fixed is None:
                    raise ValueError(f"{hour:02d}시 {post} 칸 '{text}'을 읽을 수 없음 → 이 날짜는 건너뜀")
                notes.append(f"{hour:02d}시 {post} '{text}' → '{fixed}'")
                texts[post] = fixed
        for post, text in texts.items():                 # 명단에 없는 번호: 보안실·휴게에만 = 오기(뺌), 포스트·순찰 = 건너뜀
            for p in (t for t in _tokens(text) if t.isdigit() and t not in known):
                if post not in ("보안실", "휴게"):
                    raise ValueError(f"명단 오기: {hour:02d}시 {post}의 {p}번이 명단에 없음 → 이 날짜는 건너뜀")
                notes.append(f"{hour:02d}시 {post}의 {p}번: 명단에 없는 번호라 뺌")
        for post in imp.POSTS:
            tokens = _tokens(texts[post])
            if use_e:                                     # E = 통제 자리, 함께 적힌 A(동행)는 뺀다
                tokens = ["A" if t == "E" else None if t == "A" else t for t in tokens]
            tokens = [t for t in tokens if t and t not in newcomers and not t.startswith("CP") and (t in valid or not t.isdigit())]
            item[post] = ".".join(tokens)
        # 통제가 같은 시간에 포스트와 보안실에 함께 적힌 칸(예: 03시 G1·보안실 E)은 포스트로 본다
        if any("A" in _tokens(item[p]) for p in imp.POSTS if p != "보안실"):
            item["보안실"] = ".".join(t for t in _tokens(item.get("보안실", "")) if t != "A")
        rest_col = heads.get("휴게")
        item["_rest"] = _tokens(_cell_text(body[rest_col])) if rest_col is not None and rest_col < len(body) else []
        cells.append(item)
        if len(cells) == 14:
            break
    work = [p for p in imp.POSTS if p != "휴게"]
    saved_at = {}
    if saved is not None:                               # 저장본의 (번호, 시간칸) → 표시 포스트
        token_of = {a.employee_id: (str(a.display_number) if a.display_number is not None else "A")
                    for a in saved.context.attendance if a.present}
        saved_at = {(token_of[r.employee_id], r.slot.index): r.displayed_assignment.label
                    for r in saved.assignments if r.employee_id in token_of}
    for t, item in enumerate(cells):
        # (휴게 칸은 근무 칸에 없는 사람의 자리라 근무 칸이 우선 — draft_from_cells가 근무 칸에 없는 사람만 휴게로 둔다)
        # 한 번호가 두 근무 칸에 있고 그 시간 빠진 사람이 한 명이면, 저장본과 맞는 쪽으로 읽는다 (옆 칸을 보면 아는 오기)
        where = {}
        for p in work:
            for x in _tokens(item.get(p, "")):
                where.setdefault(x, []).append(p)
        dups = {x: ps for x, ps in where.items() if len(ps) == 2}
        listed = {x for p in imp.POSTS for x in _tokens(item.get(p, ""))} | set(item["_rest"])
        missing = [x for x in numbered if x not in listed]
        if len(dups) == 1 and len(missing) == 1 and saved_at:
            (x, posts), y = next(iter(dups.items())), missing[0]
            same = lambda label, post: label == post or (post == "G3" and label == "G2")  # noqa: E731
            for post_y, post_x in (posts, posts[::-1]):
                if same(saved_at.get((y, t), ""), post_y) and same(saved_at.get((x, t), ""), post_x):
                    item[post_y] = ".".join(y if tok == x else tok for tok in _tokens(item[post_y]))
                    notes.append(f"{item['hour']:02d}시 {post_y} '{x}' → '{y}' ({x}번이 {posts[0]}·{posts[1]} 두 칸, "
                                 f"그 시간 {y}번이 없고 저장본과 일치)")
                    break
    draft = imp.draft_from_cells(cells, day, sheet, {**{k: v for k, v in numbered.items()}, "A": "통제"})
    problems = [w for w in draft.warnings if "G2(2)" not in w]
    if problems:
        raise ValueError("; ".join(problems))
    grid = {token: draft.grid[token] for token in ["A", *numbered]}
    grid, leave_notes = imp.apply_leave(grid, {"A": "A", **numbered}, leave or {})
    identities = {"A": "A", **{token: ROSTER_IDS[name] for token, name in numbered.items()}}
    names = {**{eid: name for eid, name in imp.ROSTER.items()}, "A": "통제E(지원)" if use_e else "통제A"}

    def barrier(t):                                      # FM: 통제 외 보안실 대기자 1명
        standby = [tok for tok in _tokens(cells[t].get("보안실", "")) if tok in numbered]
        return [(standby[0], t)] if len(standby) == 1 else []

    def post(t, name):
        found = [tok for tok in _tokens(cells[t].get(name, "")) if tok in numbered]
        return [(found[0], t)] if len(found) == 1 else []
    from .models import BARRIER_SINGLE_FROM, BARRIER_V2_FROM
    if day >= BARRIER_SINGLE_FROM:
        installs = post(2, "G2") or post(2, "I1")
        removes = post(10, "I1")
    elif day >= BARRIER_V2_FROM:                           # 15-0: 설치 G2+대기(G2 있을 때) 또는 I1+대기, 철수 04시 I1
        installs = (post(2, "G2") or post(2, "I1")) + barrier(2)
        removes = post(10, "I1")
    else:
        installs, removes = barrier(2), barrier(10)
    record = imp.build_import_record(day, Mode.FM, grid, identities, names, installs, removes)
    from .validator import validate_first_trial
    from .schedule_edit import explain_errors
    errors = validate_first_trial(record, HistoryInput((), ()), rules_v220=True)
    if use_e:                                            # 통제 쪽 밸런스·격차는 따지지 않음
        errors = [e for e in errors if not str(e.get("rule", "")).startswith(("8-", "H-15"))]
    who = lambda items: ", ".join(f"{t} {numbered[t]}" for t, _ in items) if items else "확인 안 됨"  # noqa: E731
    rule = ("20시 G2 단독(없으면 I1 단독), 04시 I1 단독, 15-0" if day >= BARRIER_SINGLE_FROM else "20시 G2+대기 또는 I1+대기, 04시 I1, 15-0" if day >= BARRIER_V2_FROM
            else "20·04시 보안실 대기자, 11-2·11-3")
    lines = [f"엑셀 편성표 일괄 가져오기: {file_name} / {sheet}",
             f"모드 FM(사용자 확정) · 차단봉 설치 {who(installs)}, 철수 {who(removes)} ({rule})"]
    if use_e:
        lines.append("통제E(지원)를 통제 자리로 기록" + (" · 통제A(동행)는 표에서 제외" if "A" in controls else "")
                     + " — 통제 쪽 밸런스는 보지 않고 일반근무자 특이사항만 봅니다.")
    if len(numbered) < 6:
        absent = sorted(set(ROSTER_IDS) - set(numbered.values()))
        lines.append(f"일반근무자 {len(numbered)}명 (빠진 사람: {', '.join(absent)})")
    lines.extend(leave_notes)
    if notes:
        lines.append("엑셀 오기 자동 해석: " + " / ".join(notes))
    special = _special_text(rows)
    if special:
        lines.append("현장 특이사항(참고, 근무에 반영 안 함): " + special)
    lines.extend(explain_errors(errors, record.context))
    return record, "\n".join(lines), []


# ---------------------------------------------------------------- 주간
def _day_hour(value) -> int | None:
    """주간 08:00~17:00 (야간용 hour_of는 18~07시만 읽는다)."""
    if hasattr(value, "hour"):
        hour = value.hour
    else:
        m = re.fullmatch(r"\s*(\d{1,2})\s*[:시]\s*(?:00)?\s*", str(value or ""))
        hour = int(m[1]) if m else None
    return hour if hour is not None and 8 <= hour <= 17 else None


DAY_COLUMNS = ("G1", "G2", "G3", "4C", "L1", "L2", "C1", "C2", "CP", "1C", "셔틀", "순찰", "대기", "휴게")


def _cell_text(value) -> str:
    if value is None:
        return ""
    if isinstance(value, float) and value.is_integer():
        value = int(value)
    # 손으로 친 칸의 띄어쓰기 구분('1.3 10', 'E.CP2 3 5')은 점 구분으로 ('교육: 1.3'은 그대로)
    return re.sub(r"(?<=[0-9A-Za-z)])\s+(?=[0-9A-Za-z])", ".", str(value).strip())


def _repair(text: str, valid: set, others: set) -> str | None:
    """점이 빠진 칸('E.CP235', 'E.1.310..CP2')을 명단 번호로 쪼갠다 (2026-10-11 사용자 확정: 옆 칸을 보면 안다).
    쪼개는 방법이 여러 개면 그 시간 다른 칸에 없는 사람으로 이뤄진 쪽. 그래도 하나로 안 정해지면 None."""
    def splits(run):
        if not run:
            return [[]]
        out = []
        for k in range(1, min(2, len(run)) + 1):
            head = run[:k]
            if head in valid and not head.startswith("0"):
                out += [[head, *rest] for rest in splits(run[k:])]
        return out
    s = re.sub(r"\s+", "", text.upper())
    if re.sub(r"^교육[:：]?|CP[123]|[A-E]|\d+|[.,·/;]", "", s):      # 번호·CP·통제 말고 다른 글자가 있으면 추측 안 함
        return None
    prefix = "교육: " if s.startswith("교육") else ""
    parts = []
    for token in re.findall(r"CP[123]|[A-E]|\d+", re.sub(r"^교육[:：]?", "", s)):
        if not token.isdigit() or token in valid:
            parts.append(token)
            continue
        options = splits(token)
        fresh = [o for o in options if not set(o) & others]
        pick = options if len(options) == 1 else fresh
        if len(pick) != 1:
            return None
        parts += pick[0]
    return prefix + ".".join(parts)


def day_schedule(day: date, rows, roster, defaults=None, file_name: str = "", sheet: str = "", fixes=None):
    """(DaySchedule, 비고) — 이미지 업로드와 같은 무손실 경로(schedule_image_import.build_day, 2026-10-11).

    원본 칸(4C·CP·1C·셔틀·공동근무 8.11·교육 동행)을 source_layout에 그대로 보존한다. 명단에 같은 이름이 두
    번호에 있거나 이름 없는 번호가 시간표에 있으면 ValueError → 그 날짜는 건너뛴다(사용자 확정). fixes =
    편성표 번호 이름 고침 {번호: 이름}(order_name_fix.json, 명령서와 공통)."""
    from .schedule_image_import import build_day, persons
    numbered, controls, table, extra, repaired, used, mapping = _read_table(rows, fixes, DAY_COLUMNS)
    return _finish_day(day, rows, roster, defaults, file_name, sheet, fixes, numbered, controls, table, extra,
                       repaired, used, mapping)


def _read_table(rows, fixes, columns):
    """주간 시트(평일·휴일) 칸을 글자 그대로 읽는다. 명단 오기·읽을 수 없는 칸이면 ValueError."""
    from collections import Counter
    from .schedule_image_import import persons
    numbered, controls = _names(rows)
    numbered = {**numbered, **{str(k): v for k, v in (fixes or {}).items()}}
    if not numbered:
        raise ValueError("주간 명단(번호·이름)을 찾지 못했습니다.")
    index, heads = _header(rows, {"G1", "G2", "L1"})
    heads = {("I1" if k.startswith("I1") else "대기" if k == "보안실" else k): v for k, v in heads.items()}
    time_col = heads.get("근무시간", 0)
    extra = {}
    for r in rows[:index]:
        for v in r:
            m = re.fullmatch(r"(CP[123])([가-힣]{2,4})", _norm(v).upper().replace("CPI", "CP1"))
            if m:
                extra[m[1]] = m[2]
    table = []
    for body in rows[index + 1:]:
        hour = _day_hour(body[time_col] if time_col < len(body) else None)
        if hour is None or len(table) == 10:
            continue
        row = {"시간": f"{hour:02d}:00"}
        for col in columns:
            j = heads.get(col)
            row[col] = _cell_text(body[j]) if j is not None and j < len(body) else ""
        if re.fullmatch(r"교육[:：]?", _norm(row["대기"])) and row["휴게"]:     # 대기·휴게 합친 교육 칸
            row["휴게"], row["대기"] = "교육: " + row["휴게"], ""
        elif row["대기"].replace(" ", "").startswith("교육") and not row["휴게"]:
            row["휴게"], row["대기"] = row["대기"], ""
        table.append(row)
    if [r["시간"] for r in table] != [f"{h:02d}:00" for h in range(8, 18)]:
        raise ValueError("08~17시 10개 시간 행을 찾지 못했습니다.")
    dup = sorted(n for n, c in Counter(numbered.values()).items() if c > 1)
    if dup:
        raise ValueError("명단 오기: " + ", ".join(f"{n}이(가) {'·'.join(sorted((p for p, v in numbered.items() if v == n), key=int))}번에 두 번"
                                                 for n in dup) + " 적힘 → 이 날짜는 건너뜀")
    repaired, used = [], set()
    for r in table:
        for col, text in r.items():
            if col == "시간" or not text:
                continue
            try:
                found = persons(text)
            except ValueError:
                others = set()
                for c, v in r.items():
                    if c not in ("시간", col) and v:
                        try:
                            others.update(persons(v))
                        except ValueError:
                            pass
                fixed = _repair(text, set(numbered), others)
                if fixed is None:
                    raise ValueError(f"{r['시간'][:2]}시 {col} 칸 '{text}'을 읽을 수 없음 → 이 날짜는 건너뜀")
                found, r[col] = persons(fixed), fixed
                repaired.append(f"{r['시간'][:2]}시 {col} '{text}' → '{fixed}'")
            used.update(p for p in found if p.isdigit())
    unnamed = sorted(used - set(numbered), key=int)
    idle = ("대기", "휴게")
    ghosts = [p for p in unnamed if not any(col not in idle and text and p in persons(text)
                                            for r in table for col, text in r.items() if col != "시간")]
    for r in table:                                      # 명단에 없는 번호가 대기·휴게 칸에만 = 엑셀 오기, 근무 아님
        for col in idle:
            if r[col] and set(ghosts) & set(persons(r[col])):
                before = r[col]
                prefix = "교육: " if before.replace(" ", "").startswith("교육") else ""
                keep = [t for t in re.findall(r"CP[123]|[A-E]|\d+",
                                              re.sub(r"^교육[:：]?", "", before.replace(" ", "").upper()))
                        if t not in ghosts]
                r[col] = prefix + ".".join(keep)
                repaired.append(f"{r['시간'][:2]}시 {col} '{before}' → '{r[col]}' (명단에 없는 번호, 대기·휴게 칸에만 있음)")
    used -= set(ghosts)
    unnamed = [p for p in unnamed if p not in ghosts]
    if unnamed:
        raise ValueError("명단 오기: " + "·".join(unnamed) + "번 이름이 명단에 없음 → 이 날짜는 건너뜀")
    mapping = {p: numbered[p] for p in sorted(used, key=int)}
    return numbered, controls, table, extra, repaired, used, mapping


def _shapes(table, mapping, columns, repaired):
    """핵심 칸에 나온 시간으로 출근 상태·늦은 출근·이른 퇴근, 4C 동행자."""
    from .schedule_image_import import persons
    # 출근 상태: 핵심 칸(포스트·순찰·대기·휴게)에 나온 시간으로. 13시부터만 = 오전반차, 12시까지만 = 오후반차,
    # 그 밖에 앞·뒤가 3시간 이상 비면 늦게 출근(join_from)·일찍 퇴근(leave_from). 중간 빈칸은 휴게.
    core = {p: set() for p in mapping}
    escorted = set()                                     # 4C·1C에 'A.9'처럼 통제와 함께 적힌 동행 신입
    for t, r in enumerate(table):
        for col in [c for c in columns if c not in ("CP", "셔틀")]:
            found = persons(r[col]) if r.get(col) else []
            for p in found:
                if p in core:
                    core[p].add(t)
                    if col in ("4C", "1C") and any(c in found for c in "ADE"):
                        escorted.add(p)
    statuses, shapes, warnings = {}, {}, [f"엑셀 오기 자동 해석: {x}" for x in repaired]
    for p, slots in core.items():
        if not slots:
            continue
        first, last = min(slots), max(slots)
        status = "오전반차" if first >= 5 else "오후반차" if last <= 4 else "출근"
        statuses[p] = status
        if status == "출근" and first >= 3:
            shapes[p] = {"join_from": first}
            warnings.append(f"{mapping[p]}: {first + 8:02d}시부터 근무")
        elif status == "출근" and 9 - last >= 3:
            shapes[p] = {"leave_from": last + 1}
            warnings.append(f"{mapping[p]}: {last + 8:02d}시까지 근무")
        elif status != "출근":
            warnings.append(f"{mapping[p]}: {status}로 기록")
    return statuses, shapes, warnings, escorted


def _finish_day(day, rows, roster, defaults, file_name, sheet, fixes, numbered, controls, table, extra,
                repaired, used, mapping):
    from .schedule_image_import import build_day
    statuses, shapes, warnings, escorted = _shapes(table, mapping, DAY_COLUMNS, repaired)
    schedule = build_day(day, table, mapping, statuses=statuses, shapes=shapes, fill_gaps=warnings)
    from dataclasses import replace
    layout = {**(schedule.source_layout or {}), "extra_names": extra, "controls": sorted(controls),
              "listed": dict(numbered)}                  # 엑셀 명단 전체(시간표에 없는 기타 인원 포함) — 근무표 명단 칸 표시용
    present = {p.name for p in schedule.people}
    absent = []
    # 엑셀 명단 머리에 이름은 있는데 시간표에 없는 사람 = 출근은 했지만 다른 곳 근무 → 기타 (사용자 확정, 예: 준호)
    for number, name in sorted(numbered.items(), key=lambda kv: int(kv[0])):
        if name not in present and number not in used:
            status, note = (defaults or {}).get(name, ("기타", ""))
            if status not in ("연차", "기타"):
                status, note = "기타", ""
            absent.append(DayPerson(name, name, status, None, note=note or "명단에만 있고 시간표에는 없음(다른 곳 근무)"))
            warnings.append(f"{name}: 명단에만 있고 시간표에는 없음 → {status}")
    listed = present | {p.name for p in absent}
    for name in roster:                                  # 명단에도 없는 인원은 연차일정에 있을 때만 (2026-10-11)
        if name not in listed and (defaults or {}).get(name, ("",))[0] in ("연차", "기타"):
            status, note = defaults[name]
            absent.append(DayPerson(name, name, status, None, note=note))
    grid = {**schedule.grid, **{p.name: [None] * 10 for p in absent}}
    exempt = tuple(mapping[p] for p in sorted(escorted, key=int) if mapping[p] in present)
    if exempt:
        warnings.append("4C 동행(규칙 검사 제외): " + ", ".join(exempt))
    schedule = replace(schedule, people=tuple(schedule.people) + tuple(absent), grid=grid, status="excel",
                       source_layout=layout, rule_exempt_names=exempt)
    lines = [f"엑셀 편성표 일괄 가져오기: {file_name} / {sheet}"]
    if fixes:
        lines.append("편성표 번호 이름 고침 적용: " + ", ".join(f"{k}번 {v}" for k, v in sorted(fixes.items(), key=lambda kv: int(kv[0]))))
    others = sorted(controls - {"A"})
    if others:
        lines.append("통제 표기: " + ", ".join(f"통제{c}" for c in sorted(controls)) + " (통제 쪽 밸런스는 보지 않음)")
    if warnings:
        lines.append("엑셀 확인: " + " / ".join(warnings))
    special = _special_text(rows)
    if special:
        lines.append("현장 특이사항(참고): " + special)
    return schedule, "\n".join(lines)


WEEKEND_COLUMNS = ("G1", "G2", "G3", "I1", "L1", "L2", "CP", "순찰", "대기", "휴게")


def weekend_schedule(day: date, rows, file_name: str = "", sheet: str = "", fixes=None):
    """주말·공휴일 주간 시트 → WeekendSchedule (2026-10-11 사용자 요청). 평일과 같은 무손실 읽기·오기 처리.
    통제A가 없고 통제E가 통제 자리에 서면 E를 통제 자리(A)로 기록한다(야간과 같음). 보안실 대기는 휴게로 센다."""
    from dataclasses import asdict  # noqa: F401
    from .schedule_image_import import build_day
    numbered, controls, table, extra, repaired, used, mapping = _read_table(rows, fixes, WEEKEND_COLUMNS)
    notes = []
    if "A" not in controls and "E" in controls:
        for r in table:
            for col in WEEKEND_COLUMNS:
                if r.get(col):
                    r[col] = re.sub(r"(?<![A-Z])E(?![A-Z0-9])", "A", r[col])
        notes.append("통제E(지원)를 통제 자리로 기록")
    statuses, shapes, warnings, _ = _shapes(table, mapping, WEEKEND_COLUMNS, repaired)
    schedule = build_day(day, table, mapping, kind="weekend_day", statuses=statuses, shapes=shapes,
                         fill_gaps=warnings)
    if notes:                                            # 통제 자리에 선 사람 이름표
        schedule.names["A"] = "통제E(지원)"
    lines = [f"엑셀 편성표 일괄 가져오기: {file_name} / {sheet}", *notes]
    if warnings:
        lines.append("엑셀 확인: " + " / ".join(warnings))
    return schedule, "\n".join(lines), {"mapping": mapping, "rows": table, "extra_names": extra,
                                        "controls": sorted(controls)}


def _save_weekend(store: Path, item) -> None:
    """휴일 주간 저장(이미 저장본이 있으면 이전 것을 .trash에 직전 버전으로)."""
    import shutil
    from dataclasses import asdict
    from datetime import datetime
    from .import_compare import mark_overwrite
    path = Path(store) / f"{item.day.isoformat()}.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = {**asdict(item.record), "note": item.note, "source": "excel-bulk", "source_hash": item.digest,
               "source_sheet": item.sheet, "source_file": item.source_file, "final_save_method": "upload",
               "source_review": item.source_review, "confirmed_at": datetime.now().isoformat(timespec="seconds")}
    if path.exists():
        trash = path.parent / ".trash"
        trash.mkdir(exist_ok=True)
        shutil.copy2(path, trash / f"{item.day.isoformat()}__deleted-import-{datetime.now():%Y%m%d-%H%M%S%f}.json")
        mark_overwrite(path, payload)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=1), encoding="utf-8")


# ---------------------------------------------------------------- 계획·적용
def _saved_digest(path: Path) -> str | None:
    try:
        return json.loads(path.read_text(encoding="utf-8")).get("source_hash")
    except (OSError, ValueError):
        return None


def plan(data: bytes, night_store: Path, day_store: Path, *, file_name: str = "", day_roster=(),
         start: date = date(2026, 9, 1), is_off_day=None, day_defaults=None, force: bool = False) -> list[Plan]:
    """덮어쓸 날짜 목록. 저장본 지문이 같으면 'same'(다시 만들지 않음)."""
    plans = []
    from . import leave_schedule
    entries = leave_schedule.load(Path(night_store))
    for day, shift, sheet, rows in scan(data, start=start):
        digest = _digest(rows)
        if shift == "day" and is_off_day is not None and is_off_day(day):
            shift = "weekend"                            # 주말·공휴일 주간 (2026-10-11): history/weekend_day
        store = night_store if shift == "night" else Path(day_store).parent / "weekend_day" if shift == "weekend" else day_store
        item = Plan(day, shift, sheet, digest, source_file=file_name,source_bytes=data)
        existing = Path(store) / f"{day.isoformat()}.json"
        try:
            if shift == "weekend":
                from .order_source import load_name_fixes
                from dataclasses import asdict
                fixes = load_name_fixes(night_store).get(day.isoformat(), {}).get("day", {})
                item.record, item.note, item.source_review = weekend_schedule(day, rows, file_name, sheet, fixes)
                from .import_compare import identical
                item.status = "same" if identical(existing, asdict(item.record)) else "changed" if existing.exists() else "new"
                plans.append(item)
                continue
            if shift == "night":
                from .newcomers import detect
                numbered,_controls=_names(rows)
                header,heads=_header(rows,{'G1','L3','I1'})
                reviewed=[]
                for body in rows[header+1:]:
                    hour=imp.hour_of(body[heads.get('근무시간',0)] if body else None)
                    if hour is None:continue
                    reviewed.append({'시간':f'{hour:02}:00',**{post:'.'.join(_tokens(body[col])) for post,col in heads.items() if post in (*imp.POSTS,'CP','휴게','셔틀') and col<len(body)}})
                    if len(reviewed)==14:break
                newcomers=detect(night_store,day,reviewed,numbered)
                if newcomers:item.source_review={'kind':'night','mapping':numbered,'rows':reviewed,'newcomers':list(newcomers),'newcomer_evidence':newcomers}
                leave = {}  # 업로드 근무표 원본이 우선
                saved = None
                if existing.exists():                    # 오기 칸을 저장본과 맞춰 읽을 때 사용 (2026-10-11)
                    try:
                        saved = history_store.actual_record(Path(night_store), day)
                    except (OSError, ValueError, KeyError):
                        saved = None
                item.record, item.note, item.warnings = night_record(day, rows, file_name, sheet, leave, newcomers, saved)
            else:
                from .order_source import load_name_fixes      # 편성표 번호 이름 고침(명령서와 공통)
                fixes = load_name_fixes(night_store).get(day.isoformat(), {}).get("day", {})
                from .daily_report import retired          # 퇴사자(마지막 근무일 지남)는 명단에서 뺌 (2026-10-12)
                gone = retired(Path(night_store), day)
                roster_today = [n for n in day_roster if n not in gone]
                leave_status = leave_schedule.defaults_for(entries, day, "day", roster_today)[0]
                item.record, item.note = day_schedule(day, rows, roster_today,
                                                      leave_status, file_name, sheet, fixes)
                from .newcomers import detect
                from dataclasses import replace
                mapping={str(p.number):p.name for p in item.record.people if p.number}
                reverse={p.name:str(p.number) for p in item.record.people if p.number}
                pairs=[{'시간':f'{t+8:02}:00',**{post:'.'.join(reverse[name] for name,g in item.record.grid.items() if name in reverse and g[t]==post) for post in POSTS}} for t in range(10)]
                newcomers=detect(night_store,day,pairs,mapping)
                found=tuple(mapping[p] for p in newcomers)
                item.record=replace(item.record,rule_exempt_names=tuple(dict.fromkeys(item.record.rule_exempt_names+found)))
            from .import_compare import identical
            from .day_shift import to_json
            payload={"plan":history_store.record_to_json(item.record)} if shift=="night" else to_json(item.record)
            if item.source_review:payload["source_review"]=item.source_review
            item.status = "same" if identical(existing,payload) else "changed" if existing.exists() else "new"
        except (ValueError, NotImplementedError) as exc:
            item.status, item.reason = "skip", str(exc)
        plans.append(item)
    return plans


def apply(plans: list[Plan], night_store: Path, day_store: Path) -> int:
    """new·changed만 저장(기존 저장본은 휴지통으로). 저장한 개수."""
    saved = 0
    for item in plans:
        if item.status not in ("new", "changed"):
            continue
        extra = {"source_hash": item.digest, "source_sheet": item.sheet,
                 "source_file": item.source_file, "final_save_method": "upload"}
        if item.source_review:extra["source_review"]=item.source_review
        if item.source_bytes:extra["source_bytes"]=item.source_bytes
        if item.shift == "night":
            imp.save_import(night_store, item.record, "excel-bulk", item.note,
                            imp.fingerprint(night_store, item.day), extra)
        elif item.shift == "weekend":
            _save_weekend(Path(day_store).parent / "weekend_day", item)
        else:
            save_day(Path(day_store), item.record, item.note, {"source": "excel-bulk", **extra})
        # Count replacements only; same-content imports preserve files byte for byte.
        saved += 1
    return saved
