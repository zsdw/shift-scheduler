"""날짜별 문서 대조 (2026-10-07 사용자 요청): 연차일정 → 근태일보 → 근무표 → 근무명령서.

달력에서 날짜를 고르면 어느 탭에서든 결과를 페이지 맨 위에 보여 준다.
신뢰 순서(사용자 확정): 저장된 프로그램 근무표 > 근태일보 저장본 > 연차일정 > 편성표 엑셀.
- 아래 순위 자료(편성표 엑셀)가 다른 것은 자동 판단(엑셀 오기)으로 회색 표시, 필요하면 바꿀 수 있다.
- 근무표와 일보처럼 위 순위끼리 다르면 빨간 경고 + 처리 선택(일보 고치기 / 확인함).
- 일보 고치기는 날짜별 출근 상태 고침(attendance_fix.json)을 연차일정 위에 덧씌우고 일보를 다시 저장한다
  (이전 저장본은 휴지통). 연차일정 원본은 바꾸지 않는다.
"""
from __future__ import annotations

import hashlib
import json
from datetime import date, datetime, timedelta
from pathlib import Path

from . import daily_report as dr

DAY_DIR, WEEKEND_DIR = "day", "weekend_day"
RESOLUTION_FILE = "check_resolutions.json"
# 2026-10-08 일보 저장 절차 제거: 일보는 연차일정(원본+직접 등록+출근 고침)으로 항상 자동 계산
TRUST_ORDER = ("저장된 프로그램 근무표", "연차일정(일보 자동 계산)", "편성표 엑셀")
FIX_STATUSES = ("결근", "휴무", "연차", "오전반차", "오후반차", "교육", "주간지원", "야간지원", "대근", "출근")


def _match(short: str, full_names) -> str | None:
    found = [f for f in full_names if f == short or f.endswith(short)]
    return found[0] if len(found) == 1 else None


def _report(store: Path, day: date):
    roster = dr.load_roster(store)
    report = dr.build(day, dr.entries_for(store, day), roster, dr.entries_for(store, day - timedelta(days=1)))
    saved = dr.load_saved(store, day)
    rows, changed = report["rows"], []
    return report, rows, changed, saved, dr.active(roster, day)


def _expected(rows, roster, teams, shift: str, off: bool) -> dict[str, str]:
    """그 근무에 번호를 받고 나와야 하는 대원 {이름: 소속} — 일보(저장본 우선) 기준."""
    from .security_order import person_kinds, present
    out = {}
    team = (teams["주간조"] if shift == "day" else teams["야간조"])
    for p in roster:
        if p["직책"] != "대원":
            continue
        kinds = [k.replace(" ", "") for k in person_kinds(p["이름"], rows)]
        if p["소속"] == team:
            ok = present(p["이름"], rows, shift, False) if shift == "day" else not any(
                any(w == "absent" for w, _ in dr.classify(k)) for k in kinds) and not any("주간지원" in k for k in kinds)
        elif p["소속"] == "주간고정":
            ok = (present(p["이름"], rows, "day", off) if shift == "day"
                  else any("야간지원" in k for k in kinds))
        else:
            ok = any(("주간지원" if shift == "day" else "야간지원") in k or "대근" in k for k in kinds)
        if ok:
            out[p["이름"]] = p["소속"]
    return out


def _absent_kind(name, rows):
    from .security_order import person_kinds
    return next((k for k in person_kinds(name, rows) if any(w == "absent" for w, _ in dr.classify(k))), None)


def _issue(level, where, message, kind, person=None, sources=(), fix=None, default=None, ack_label="확인함 (그대로 둠)"):
    key = hashlib.sha1(f"{kind}|{where}|{person}|{message}".encode("utf-8")).hexdigest()[:16]
    choices = []
    if fix:
        choices.append({"id": "fix", "label": f"근무표가 맞음 → {person} 일정·일보 고치기", "status": fix})
    if kind == "leave_changed":
        choices.append({"id": "resave", "label": "새 계산으로 일보 다시 저장"})
    if level != "info":
        choices.append({"id": "ack", "label": ack_label})
    return {"key": key, "level": level, "where": where, "message": message, "kind": kind, "person": person,
            "sources": list(sources), "choices": choices,
            "default": default or (choices[0]["id"] if choices else None)}


def _support_status(group: str, shift: str) -> str:
    return "야간지원" if shift == "night" else "주간지원" if group != "주간고정" else "출근"


def _compare(label, names, expected, rows, roster, issues, where, shift, program: bool, trainees=()):
    """program=True: 저장된 프로그램 근무표(일보보다 위) / False: 편성표 엑셀(일보보다 아래, 자동 판단)."""
    from .security_order import person_kinds
    roster_names = [p["이름"] for p in roster]
    group = {p["이름"]: p["소속"] for p in roster}
    level = "error"
    src = "근무표" if program else "편성표 엑셀"
    auto_ack = "연차일정이 맞음 → 근무표를 고칠게요"
    listed = {}
    for short in names:
        full = _match(short, roster_names)
        if full is None:
            if short not in trainees:
                issues.append(_issue(level, where, f"{label}의 '{short}'을(를) 명단에서 찾지 못했습니다.", "unknown",
                                     short, [(src, short), ("근태일보 명단", "없음")]))
            continue
        if full in listed:
            issues.append(_issue(level, where, f"{label}에 {full}이(가) 두 번 적혀 있습니다.", "dup", full))
        listed[full] = short
    for full in listed:
        kind = _absent_kind(full, rows)
        if kind:
            issues.append(_issue(level, where, f"{label}에 {full}이(가) 있는데 근태일보상 {kind}입니다.", "absent_listed",
                                 full, [(src, "근무"), ("근태일보", kind)], fix="출근",
                                 default=None if program else "ack", ack_label=auto_ack))
        elif full not in expected:
            issues.append(_issue("warn", where,
                                 f"{label}에 {full}이(가) 있는데 근태일보에는 이 근무 출근으로 잡혀 있지 않습니다.",
                                 "not_expected", full, [(src, "근무"), ("근태일보", f"{group.get(full, '')} 근무 아님")],
                                 fix=_support_status(group.get(full, ""), shift),
                                 default="ack", ack_label=auto_ack))
    for short in trainees:          # 교육 동행·신입: 일보에 교육·입사 비고가 있어야 한다
        full = _match(short, roster_names)
        if full and full not in expected and not any(w in k for k in person_kinds(full, rows) for w in ("교육", "입사")):
            issues.append(_issue("warn", where, f"{label}에 교육 동행 {full}이(가) 있는데 근태일보에 교육·입사 비고가 없습니다.",
                                 "trainee", full, [("근무표", "교육 동행"), ("근태일보", "비고 없음")], fix="교육",
                                 ack_label=auto_ack))
    for full, grp in expected.items():
        if full not in listed and not any(full.endswith(t) for t in trainees):
            issues.append(_issue(level, where, f"근태일보상 출근({grp})인 {full}이(가) {label}에 없습니다.", "missing",
                                 full, [("근태일보", "출근"), (src, "없음")], fix="결근",
                                 default="ack", ack_label=auto_ack))


def review(store: Path, day: date, order_sources: dict | None = None) -> list[dict]:
    """건별 대조 결과(처리 선택지 포함). 처리함(확인함)으로 기록된 건은 resolved=True."""
    from .order_source import document_available     # 명령서를 띄우는 날은 모두 대조 (2026-10-11)
    if not document_available(store, day):
        return []
    store = Path(store)
    issues: list[dict] = []
    report, rows, changed, saved, roster = _report(store, day)
    teams = {k: (v if str(v).endswith("조") else f"{v}조") for k, v in report["teams"].items()}
    off = dr.is_off_day(day)
    roster_names = [p["이름"] for p in roster]
    if changed:
        issues.append(_issue("error", "근태일보", "일보 저장 뒤 연차일정(또는 출근 상태 고침)이 바뀌어 계산이 달라졌습니다: "
                             + ", ".join(changed), "leave_changed", None,
                             [("근태일보 저장본", "저장 당시 값"), ("연차일정", "새 계산값")], ack_label="저장본 유지 (확인함)"))
    expected_day = _expected(rows, roster, teams, "day", off)
    day_path = store / DAY_DIR / f"{day.isoformat()}.json"
    weekend_path = store / WEEKEND_DIR / f"{day.isoformat()}.json"
    if day_path.exists():
        data = json.loads(day_path.read_text(encoding="utf-8"))
        trainees = tuple(data.get("trainees") or {}) + tuple(data.get("rule_exempt_names") or ())
        names = [p["pid"] for p in data["people"] if p.get("number") and p["pid"] not in trainees]
        layout = data.get("source_layout") or data.get("source_review") or {}
        names += [n for k, n in (layout.get("mapping") or {}).items()     # 원본 보조칸(4C 공동근무 등)에만 있는 사람
                  if str(k).isdigit() and n and n not in names and n not in trainees]
        for p in data["people"]:
            full = _match(p["pid"], roster_names)
            if p["status"] == "연차" and full and not _absent_kind(full, rows):
                issues.append(_issue("error", "근무표(주간)", f"주간 근무표에서 {full}이(가) 연차인데 근태일보상 출근입니다.",
                                     "schedule_leave", full, [("근무표", "연차"), ("근태일보", "출근")], fix="연차",
                                     ack_label="근무표를 고칠게요 (일보가 맞음)"))
        _compare("주간 근무표", names, expected_day, rows, roster, issues, "근무표(주간)", "day", True, trainees)
    elif weekend_path.exists():
        data = json.loads(weekend_path.read_text(encoding="utf-8"))
        names = [n for k, n in data.get("names", {}).items() if k != "A"]
        _compare("주말 주간 근무표", names, expected_day, rows, roster, issues, "근무표(주간)", "day", True,
                 tuple(data.get("rule_exempt_names") or ()))
    night_path = store / f"{day.isoformat()}.json"
    expected_night = _expected(rows, roster, teams, "night", off)
    if night_path.exists():
        data = json.loads(night_path.read_text(encoding="utf-8"))
        context = data["plan"]["context"]
        present = {a["employee_id"] for a in context["attendance"] if a.get("present") and a.get("is_general_worker")}
        names = [e["name"] for e in context["employees"] if e["employee_id"] in present and e["name"] != "통제"]
        _compare("야간 근무표", names, expected_night, rows, roster, issues, "근무표(야간)", "night", True)
    for shift, source in (order_sources or {}).items():
        if source.get("program"):      # 저장된 프로그램 근무표가 명령서 기준: 위 '근무표(주간)' 대조와 같은 자료
            continue
        label = f"폴더 편성표 엑셀({'주간' if shift == 'day' else '야간'})"
        expected = expected_day if shift == "day" else expected_night
        shorts = list(source.get("names", {}).values())
        for s in sorted({s for s in shorts if shorts.count(s) > 1}):
            numbers = [n for n, v in source["names"].items() if v == s]
            issues.append(_issue("error", "근무명령서", f"{label} {'·'.join(numbers)}번 이름이 모두 '{s}'입니다 — "
                                 "명령서 탭 '편성표 번호 이름 고치기'로 바로잡으세요.", "dup", s,
                                 ack_label="확인함 (명령서에서 고침)"))
        unique = [s for i, s in enumerate(shorts) if s not in shorts[:i]]
        _compare(label, unique, expected, rows, roster, issues, "근무명령서", shift, False)
        for control in source.get("controls", []):
            match = [p for p in roster if p["직책"] == f"통제{control}"]
            if len(match) == 1 and shift == "day" and _absent_kind(match[0]["이름"], rows):
                issues.append(_issue("info", "근무명령서", f"{label}의 통제{control}({match[0]['이름']})은 근태일보상 "
                                     f"{_absent_kind(match[0]['이름'], rows)}이라 명령서 성명에서 뺐습니다.", "control"))
    done = load_resolutions(store).get(day.isoformat(), {})
    for issue in issues:
        issue["resolved"] = done.get(issue["key"])
    return issues


def check(store: Path, day: date, order_sources: dict | None = None) -> list[tuple[str, str, str]]:
    """[(수준 error|warn|auto|info, 확인할 곳, 내용)] — 확인함으로 처리한 건은 뺀다."""
    return [(i["level"], i["where"], i["message"]) for i in review(store, day, order_sources) if not i["resolved"]]


# ---------------------------------------------------------------- 처리 (확인함 / 일보 고치기 / 다시 저장)
def load_resolutions(store) -> dict:
    path = Path(store) / RESOLUTION_FILE
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def _record(store, day, key, value):
    data = load_resolutions(store)
    data.setdefault(day.isoformat(), {})[key] = {**value, "at": datetime.now().isoformat(timespec="seconds")}
    (Path(store) / RESOLUTION_FILE).write_text(json.dumps(data, ensure_ascii=False, indent=1), encoding="utf-8")


def unresolve(store, day, key):
    data = load_resolutions(store)
    data.get(day.isoformat(), {}).pop(key, None)
    (Path(store) / RESOLUTION_FILE).write_text(json.dumps(data, ensure_ascii=False, indent=1), encoding="utf-8")


def resave_report(store, day, focus_person: str | None = None, keep_edits: bool = True) -> bool:
    """일보 저장본을 새 계산값으로 다시 저장(이전 저장본은 휴지통). 손으로 고친 줄은 유지(그 사람 소속 줄 제외)."""
    store = Path(store)
    saved = dr.load_saved(store, day)
    if not saved:
        return False
    roster = dr.load_roster(store)
    report = dr.build(day, dr.entries_for(store, day), roster, dr.entries_for(store, day - timedelta(days=1)))
    group = next((p["소속"] for p in roster if p["이름"] == focus_person), None)
    rows = []
    for r in report["rows"]:
        s = saved.get("rows", {}).get(str(int(r["행"])))
        focus = group is not None and (r["구분"] == group or r.get("조") == group)
        edited = (s and s.get("계산사고") is not None
                  and (s["사고"] != s["계산사고"] or (s.get("비고") or "") != (s.get("계산비고") or "")))
        rows.append({**r, "사고": s["사고"], "비고": s["비고"]} if keep_edits and edited and not focus else dict(r))
    dr.save_report(store, day, rows, saved.get("writer", ""), report["rows"])
    return True


def apply(store, day, issue: dict, choice: str, status: str | None = None) -> str:
    """선택한 처리를 적용하고 화면에 보여 줄 한 줄 결과를 돌려준다."""
    store = Path(store)
    if choice == "ack":
        _record(store, day, issue["key"], {"choice": "ack", "message": issue["message"]})
        return "확인함으로 표시했습니다."
    if choice == "resave":
        resave_report(store, day, keep_edits=False)
        _record(store, day, issue["key"], {"choice": "resave", "message": issue["message"]})
        return "근태일보를 새 계산으로 다시 저장했습니다 (이전 저장본은 휴지통)."
    if choice == "fix":
        person = issue["person"]
        status = status or next(c["status"] for c in issue["choices"] if c["id"] == "fix")
        dr.save_attendance_fix(store, day, person, status)
        _record(store, day, issue["key"], {"choice": "fix", "status": status, "message": issue["message"]})
        return f"{person}: 근태일보 상태를 '{status}'(으)로 고쳤습니다. 일정과 일보에 자동 반영됩니다."
    raise ValueError(choice)
