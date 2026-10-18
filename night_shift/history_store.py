"""Confirmed night-shift history on disk (§20).

Each confirmed night is one JSON file ``history/<YYYY-MM-DD>.json``::

    {"version": 1, "rules_version": "2.20", "confirmed_at": "...",
     "plan": <ShiftRecord kind=plan>, "edits": [...], "note": ""}

The *actual* record is never stored separately: it is always rebuilt from the
confirmed plan plus the edit log (see ``actual_edit.apply_edits``), so every
correction stays visible and reversible. Balance for later nights uses only
actual records.
"""
from __future__ import annotations

import json
import re
from dataclasses import asdict, replace
from datetime import date, datetime
from pathlib import Path

from .models import (
    Assignment, AssignmentKind, AssignmentRecord, Attendance, Employee, Mode, NightType,
    Posture, RecordKind, ShiftContext, ShiftRecord, Slot,
)

STORE_VERSION = 1
CYCLE_WEIGHTS_FULL = (0.25, 0.25, 0.25, 0.25)   # 최근 4근무 똑같이(5:5) — 2026-10-13 사용자 확정, 종전 6:4


# ---------------------------------------------------------------- serialization
def _enum(value):
    return value.value if hasattr(value, "value") else value


def record_to_json(record: ShiftRecord) -> dict:
    c = record.context
    return {
        "record_id": record.record_id, "kind": record.kind.value,
        "source_plan_id": record.source_plan_id,
        "confirmed_at": record.confirmed_at.isoformat() if record.confirmed_at else None,
        "context": {
            "shift_start_date": c.shift_start_date.isoformat(), "night_type": c.night_type.value,
            "requested_mode": c.requested_mode.value, "effective_mode": c.effective_mode.value,
            "employees": [asdict(e) for e in c.employees],
            "attendance": [{**asdict(a), "available_slot_indices": (list(a.available_slot_indices)
                                                                     if a.available_slot_indices is not None else None)}
                           for a in c.attendance],
            "mode_change_reason": c.mode_change_reason, "day_instructions": list(c.day_instructions),
            "partial_vacancy_profile": c.partial_vacancy_profile,
            "flexible_from_slot": c.flexible_from_slot,
            "manager_handover": list(c.manager_handover) if c.manager_handover else None,
            "post_operations": [list(op) for op in c.post_operations] if c.post_operations is not None else None,
            "extra_south_slots": list(c.extra_south_slots),
            "manager_handover_reverse": c.manager_handover_reverse,
        },
        "assignments": [{
            "employee_id": r.employee_id, "slot": r.slot.index,
            "displayed": [r.displayed_assignment.kind.value, r.displayed_assignment.label],
            "actual": [r.actual_post_or_work_type.kind.value, r.actual_post_or_work_type.label],
            "fatigue": r.fatigue_value, "work": r.actual_work_time_value, "rest": r.actual_rest_time_value,
            "posture": _enum(r.posture_or_mode), "same": r.counts_for_same_post_consecutive,
            "continuous": r.counts_for_continuous_work_restriction, "meal": r.counts_as_meal_opportunity,
            "patrol_rest": r.counts_as_post_patrol_rest, "install": r.barrier_install_flag,
            "remove": r.barrier_remove_flag, "mode": r.mode.value, "refs": list(r.rule_refs),
        } for r in record.assignments],
    }


def record_from_json(data: dict) -> ShiftRecord:
    c = data["context"]
    context = ShiftContext(
        date.fromisoformat(c["shift_start_date"]), NightType(c["night_type"]), Mode(c["requested_mode"]),
        Mode(c["effective_mode"]), tuple(Employee(**e) for e in c["employees"]),
        tuple(Attendance(a["employee_id"], a["present"], a["is_general_worker"], a["display_number"],
                         a["acts_as_manager"],
                         tuple(a["available_slot_indices"]) if a["available_slot_indices"] is not None else None)
              for a in c["attendance"]),
        c.get("mode_change_reason"), tuple(c.get("day_instructions", ())),
        c.get("partial_vacancy_profile", False), c.get("flexible_from_slot"),
        tuple(c["manager_handover"]) if c.get("manager_handover") else None,
        tuple(tuple(op) for op in c["post_operations"]) if c.get("post_operations") is not None else None,
        tuple(c.get("extra_south_slots", ())),
        c.get("manager_handover_reverse", False),
    )
    # 2026-10-04 사용자 확정: 실근무는 포스트·순찰만. 예전 저장본의 '차단봉만 한 칸' 실근무 1을 읽을 때 0으로
    # 다시 계산한다 (파일은 그대로). 피로도 1·실휴게 0은 그대로.
    rows = tuple(AssignmentRecord(
        r["employee_id"], Slot(r["slot"]), Assignment(AssignmentKind(r["displayed"][0]), r["displayed"][1]),
        Assignment(AssignmentKind(r["actual"][0]), r["actual"][1]), r["fatigue"],
        0 if r["actual"][0] == AssignmentKind.BARRIER_ONLY.value else r["work"], r["rest"],
        Posture(r["posture"]) if r["posture"] is not None else None, r["same"], r["continuous"],
        r["meal"], r["patrol_rest"], r["install"], r["remove"], Mode(r["mode"]), tuple(r["refs"]),
    ) for r in data["assignments"])
    confirmed = datetime.fromisoformat(data["confirmed_at"]) if data.get("confirmed_at") else None
    return ShiftRecord(data["record_id"], RecordKind(data["kind"]), context, rows,
                       data.get("source_plan_id"), confirmed)


# ---------------------------------------------------------------- store
def _path(store: Path, shift_date: date) -> Path:
    return Path(store) / f"{shift_date.isoformat()}.json"


def list_dates(store: Path) -> list[date]:
    store = Path(store)
    if not store.exists():
        return []
    out = []
    for f in store.glob("*.json"):
        try:
            out.append(date.fromisoformat(f.stem))
        except ValueError:
            continue
    return sorted(out)


def exists(store: Path, shift_date: date) -> bool:
    return _path(store, shift_date).exists()


def save_confirmed(store: Path, plan: ShiftRecord, rules_version: str,
                   now: datetime | None = None, rebalance=None) -> Path:
    """Confirm a generated plan for its date. The actual starts equal to the plan."""
    store = Path(store)
    store.mkdir(parents=True, exist_ok=True)
    now = now or datetime.now()
    plan = replace(plan, kind=RecordKind.PLAN, confirmed_at=None)
    payload = {"version": STORE_VERSION, "rules_version": rules_version,
               "confirmed_at": now.isoformat(timespec="seconds"),
               "plan": record_to_json(plan), "edits": [], "note": ""}
    if rebalance is not None:  # emergency re-optimization: remember the LOCKed hours
        payload["rebalance"] = {
            "locked_through": rebalance.locked_through_index,
            "start": rebalance.reoptimization_start_index,
            "employee": rebalance.unavailable_employee_id,
            "from": rebalance.unavailable_from_index,
            "reason": rebalance.reason,
        }
    path = _path(store, plan.context.shift_start_date)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=1), encoding="utf-8")
    return path


def load(store: Path, shift_date: date) -> dict:
    data = json.loads(_path(store, shift_date).read_text(encoding="utf-8"))
    data["plan_record"] = record_from_json(data["plan"])
    return data


def locked_through(data: dict) -> int:
    """Last LOCKed slot of a saved emergency re-optimization, or -1.

    Older files have no ``rebalance`` block; their plan id ends in
    ``-rebalance-<start>``, which is enough to recover the LOCK range.
    """
    info = data.get("rebalance")
    if info and info.get("locked_through") is not None:
        return int(info["locked_through"])
    match = re.search(r"-rebalance-(\d+)$", data.get("plan", {}).get("record_id", ""))
    return int(match.group(1)) - 1 if match else -1


def save_edits(store: Path, shift_date: date, edits: list[dict], note: str | None = None) -> None:
    """Store the latest revision. A new save overwrites the previous revision;
    the first confirmed plan is never touched. note=None keeps the saved note
    (예: 이미지 가져오기 출처 메모를 지우지 않는다)."""
    from .actual_edit import apply_edits
    path = _path(store, shift_date)
    data = json.loads(path.read_text(encoding="utf-8"))
    plan = record_from_json(data["plan"])
    data["edits"] = list(edits)
    if note is not None:
        data["note"] = note
    data["edited_at"] = datetime.now().isoformat(timespec="seconds")
    # Materialized latest revision, for reading without the edit engine.
    data["latest"] = record_to_json(apply_edits(plan, edits)) if edits else None
    path.write_text(json.dumps(data, ensure_ascii=False, indent=1), encoding="utf-8")


# ---------------------------------------------------------------- trash
def _trash(store: Path) -> Path:
    return Path(store) / ".trash"


def delete_to_trash(store: Path, shift_date: date) -> Path:
    """Hide a confirmed night (and its revision) without destroying the data."""
    trash = _trash(store)
    trash.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    target = trash / f"{shift_date.isoformat()}__deleted-{stamp}.json"
    serial = 1
    while target.exists():  # two deletions within the same second must never overwrite
        serial += 1
        target = trash / f"{shift_date.isoformat()}__deleted-{stamp}-{serial}.json"
    _path(store, shift_date).replace(target)
    return target


def list_trash(store: Path) -> list[dict]:
    trash = _trash(store)
    if not trash.exists():
        return []
    items = []
    for f in sorted(trash.glob("*.json"), reverse=True):
        day, _, stamp = f.stem.partition("__deleted-")
        try:
            items.append({"name": f.name, "date": date.fromisoformat(day), "deleted": stamp})
        except ValueError:
            continue
    return items


def restore_from_trash(store: Path, name: str) -> date:
    source = _trash(store) / name
    day = date.fromisoformat(source.stem.partition("__deleted-")[0])
    if exists(store, day):
        raise ValueError(f"{day} 근무표가 이미 저장되어 있어 복구할 수 없습니다. 기존 것을 먼저 삭제하세요.")
    source.replace(_path(store, day))
    return day


def empty_trash(store: Path) -> int:
    """Permanently remove everything in the trash (user-confirmed in the UI)."""
    count = 0
    for item in list_trash(store):
        (_trash(store) / item["name"]).unlink(missing_ok=True)
        count += 1
    return count


def actual_record(store: Path, shift_date: date) -> ShiftRecord:
    from .actual_edit import apply_edits
    data = load(store, shift_date)
    actual = apply_edits(data["plan_record"], data["edits"])
    return replace(actual, kind=RecordKind.ACTUAL,
                   record_id=f"{data['plan_record'].record_id}-actual",
                   source_plan_id=data["plan_record"].record_id,
                   confirmed_at=datetime.fromisoformat(data["confirmed_at"]))


# ---------------------------------------------------------------- balance input
def cycle_weights(count: int) -> tuple[float, ...]:
    """Newest first. Equal weights over the last 4 nights (5:5); fewer: equal."""
    if count <= 0:
        return ()
    if count >= 4:
        return CYCLE_WEIGHTS_FULL
    return tuple(1 / count for _ in range(count))


def recent_actuals(store: Path, before: date, limit: int = 4) -> list[ShiftRecord]:
    """Up to ``limit`` confirmed actual nights before ``before``, newest first."""
    dates = [d for d in list_dates(store) if d < before]
    return [actual_record(store, d) for d in sorted(dates, reverse=True)[:limit]]


def history_selection(store: Path, before: date):
    """HistorySelection from stored actual nights (last two cycles, equal 5:5)."""
    from .service import HistorySelection
    from .soft_history import patrol_rotation_due, update_soft_debt
    from .patrol_history import load_events
    events = load_events(store, before)
    actuals = recent_actuals(store, before)
    if not actuals:
        return HistorySelection(patrol_events=events)
    debt: dict = {}
    for record in sorted(actuals, key=lambda r: r.context.shift_start_date):
        debt = update_soft_debt(record, debt, patrol_rotation_due(
            [r for r in actuals if r.context.shift_start_date < record.context.shift_start_date], debt))
    return HistorySelection(last_rest_records=tuple(recent_actuals(store,before,limit=len(list_dates(store)))),
                            patrol_events=events, actual_records=tuple(actuals), actual_weights=cycle_weights(len(actuals)),
                            soft_debt=debt or None,
                            duty_records=tuple(recent_actuals(store, before, limit=6)))
