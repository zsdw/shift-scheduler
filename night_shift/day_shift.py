"""평일 주간근무표 (docs/평일_주간근무_룰북_v1.0.txt).

Time: 08:00~17:00, 10 hourly slots (index 0 = 08시).

Facts taken from the 2026-07~09 Excel sheets and the 통합 근무표 고정틀 (8~11인):
- 순찰 (하층부) exists at 08, 09, 10, 11, 14, 15, 16, 17 (not 12, 13).
- 셔틀 해지/설치 at 08 해지, 11 설치, 13 해지, 16 설치 (17시는 CP 담당이라 제외).
- 근근휴 사이클 HARD (8~10인 고정틀 그대로), 11인 이상·7인 이하는 §3-2 완화.
- C2는 C1이 매시간 열려 있을 때만 (축소는 C2 전부 → C1 순서).
- 대기 = 휴게 (표기상 1명), 순찰 부족 시 통제A 1회 → 선임 2회.
- 선임(준호/태환)은 첫 타임을 휴게·대기·순찰로 시작 (가급적 순찰).
- v0.7: 반차자가 없고 8~11인이면 통합 근무표 고정틀 그대로, 반차자가 있을 때만 룰북 편성.
- v0.7: 통제A는 마지막(17시) 순찰 금지. 08시 줄은 번호 1→G1, 2→G2 … 순서 HARD.
- v1.0 §27: G1·G2·G3·L1·L2는 어느 시간도 비울 수 없다 (긴급 재편성 포함 무조건 HARD).
  긴급 재편성에서 일반근무자로 못 채우는 자리는 통제A(비번 시간) → 통제E 순으로 채우고, 그래도 안 되면 해 없음.

The solver (CP-SAT) and the validator below are written separately; the
validator re-derives every hard rule from the finished grid.
"""
from __future__ import annotations

import json
import random
from dataclasses import dataclass, field, replace
from datetime import date, datetime
from pathlib import Path

HOURS = tuple(f"{h:02d}시" for h in range(8, 18))
SLOTS = range(10)
CORE = ("G1", "G2", "G3", "L1", "L2")
C_POSTS = ("C1", "C2")
POSTS = CORE + C_POSTS
PATROL, STANDBY, REST, EDU = "순찰", "대기", "휴게", "교육"
STATES = POSTS + (PATROL, STANDBY, REST)          # solver states; 교육 = 휴게 at EDU_SLOTS
EDU_SLOTS = frozenset({2, 6})                      # 10시·14시: 그 시간 휴게자 전원 교육, 대기 없음
CONTROL_SLOTS = frozenset({0, 2, 4, 6, 8})         # 통제A 퐁당퐁당 (08·10·12·14·16시)
LAST_SLOT = 9                                      # 17시
FIRST_ROW_ORDER = ("G1", "G2", "G3", "L1", "L2", "C1", "C2")   # §6 v0.7: 08시 번호 1..k 순서
NUMBER_COLORS = {1: "70AD47", 2: "00B0F0", 3: "92D050", 4: "EDEDED", 5: "DEEBF7", 6: "8FAADC",
                 7: "7C7C7C", 8: "FFFF00", 9: "FF0000", 10: "FFFFCC", 11: "CC9900", 12: "006699",
                 13: "CC00FF"}                     # 엑셀 편성표 조건부 서식과 같은 색
PATROL_SLOTS = frozenset({0, 1, 2, 3, 6, 7, 8, 9})
CONTROL_PATROL_SLOTS = PATROL_SLOTS - CONTROL_SLOTS - {LAST_SLOT}   # §7 v0.7: 통제A 순찰은 09·11·15시만 (17시 금지)
SHUTTLE = {0: "해지", 3: "설치", 5: "해지", 8: "설치"}
STATUSES = ("출근", "연차", "오전반차", "오후반차")
SENIOR_NAMES = ("태환", "준호")                   # 선임: 예전 태환, 이후 준호. 둘 다 있으면 태환 (9/1 실제표)
DEFAULT_ROSTER = ("원종", "도운", "준형", "만년", "용주", "제욱", "광희", "준호", "성욱", "성호")
ROTATION = {"G1": "G2", "G2": "G3", "G3": "L1", "L1": "L2", "L2": "G1"}


def available_slots(status: str) -> tuple[int, ...]:
    # 오후반차 = 오전 근무(08~12시) 후 13시 퇴근, 오전반차 = 13시 출근(13~17시).
    return {"출근": tuple(SLOTS), "오후반차": tuple(range(0, 5)), "오전반차": tuple(range(5, 10))}.get(status, ())


@dataclass(frozen=True)
class DayPerson:
    pid: str          # stable id (the name)
    name: str
    status: str       # 출근 / 연차 / 오전반차 / 오후반차
    number: int | None = None
    leave_from: int | None = None   # 긴급 반차·이탈: 이 슬롯부터 근무 불가 (§25)


def slots_of(person: DayPerson) -> tuple[int, ...]:
    """근무 가능 슬롯: 상태(연차·반차) + 긴급 반차·이탈 시각까지."""
    slots = available_slots(person.status)
    if person.leave_from is not None:
        slots = tuple(t for t in slots if t < person.leave_from)
    return slots


# §25 v0.9 긴급 재편성 묶음: (G1) (G2·G3) (L1·L2) (C1·C2)
POST_GROUP = {"G1": "G1", "G2": "G23", "G3": "G23", "L1": "L", "L2": "L", "C1": "C", "C2": "C"}
FATIGUE = {**{post: 2 for post in CORE}, **{post: 1 for post in C_POSTS}, PATROL: 1}   # §25 피로도


def fatigue_of(row) -> int:
    """피로도: G1·G2·G3·L1·L2 = 2, C1·C2·순찰 = 1, 휴게·대기·교육 = 0."""
    return sum(FATIGUE.get(label, 0) for label in row)


@dataclass
class DaySchedule:
    day: date
    people: tuple[DayPerson, ...]
    grid: dict            # pid -> list of 10 labels (None = 근무 불가)
    shuttle: dict = field(default_factory=dict)   # slot -> pid
    status: str = ""
    control: bool = True                            # 통제A 출근 여부 (퐁당퐁당 표시)
    control_patrol: int | None = None               # 통제A가 순찰을 맡은 시간 (없으면 None)
    strict: bool = True                             # 근근휴 사이클 HARD 적용 여부 (§3-2)
    fixed_template: int | None = None               # 고정틀(8~11인)로 만든 표면 그 인원 수 (§23)
    locked_through: int | None = None               # 긴급 재편성: 이 슬롯까지 LOCK (§25)
    emergency: dict | None = None                   # {"pid", "from", "kind", "start"}
    fill: dict = field(default_factory=dict)        # §27 긴급 빈자리 메움: slot -> {post: "A" | "E"}

    def label(self, pid, t):
        return self.grid[pid][t]


# ---------------------------------------------------------------- solver
MAX_POSTS = len(CORE) + len(C_POSTS)               # 7: G1·G2·G3·L1·L2 + C1·C2


def senior_of(people) -> DayPerson | None:
    """선임 (A조 준호, 예전 태환): 출근(가용)한 사람 중 SENIOR_NAMES 순서로 첫 번째."""
    present = {p.name: p for p in people if slots_of(p)}
    return next((present[n] for n in SENIOR_NAMES if n in present), None)


def _phase_works(window, k):
    """Strict 근근휴 cycle inside one person's window. k=0 근근휴, 1 근휴근근, 2 휴근근."""
    return {t: (i + k) % 3 != 2 for i, t in enumerate(window)}


def strict_cycle_possible(people, control: bool = True) -> bool:
    """§3 (v0.5): can every present person follow the strict 근근휴 cycle?

    Every hour needs 5~7 workers (core 5 + C1 + C2), a patrol slot needs one
    person off (통제A may cover one patrol in its off hour), and if any hour
    needs C2 (7 workers) then C1 must be open every hour (≥6 workers).
    The 선임 must start off (phase 휴근근).
    """
    present = [p for p in people if slots_of(p)]
    senior = senior_of(present)
    full = [p for p in present if p.status == "출근" and p is not senior]
    others = [p for p in present if p.status != "출근" or p is senior]
    windows = {p.pid: tuple(slots_of(p)) for p in present}
    from itertools import product
    other_choices = [[2] if p is senior else [0, 1, 2] for p in others]
    n = len(full)
    for a in range(n + 1):
        for b in range(n + 1 - a):
            c = n - a - b
            base = [0] * 10
            for k, count in enumerate((a, b, c)):
                for t, w in _phase_works(tuple(SLOTS), k).items():
                    base[t] += w * count
            for combo in product(*other_choices):
                workers = list(base)
                for p, k in zip(others, combo):
                    for t, w in _phase_works(windows[p.pid], k).items():
                        workers[t] += w
                if min(workers) < len(CORE) or max(workers) > MAX_POSTS:
                    continue
                if max(workers) == MAX_POSTS and min(workers) < MAX_POSTS - 1:
                    continue
                present_at = [sum(t in windows[p.pid] for p in present) for t in SLOTS]
                short = [t for t in PATROL_SLOTS if present_at[t] - workers[t] < 1]
                if not short or (control and len(short) == 1 and short[0] in CONTROL_PATROL_SLOTS):
                    return True
    return False


# ---------------------------------------------------------------- 통합 근무표 고정틀 (§23 v0.7)
# 통합 근무표.xlsx '평일 주간 (8인)~(11인)' 그대로 (자리 번호 1..n). 대기는 아래에서 다시 표기.
# - 8인: 엑셀은 08시 L2=6·C1=5라 §6 v0.7(08시 1→G1 … 순서)에 맞게 5·6번 자리 번호만 맞바꿈.
# - 8인: 엑셀 16시에 3번이 순찰과 휴게란에 겹쳐 적혀 있어 순찰로 본다 (순찰칸이 실제 배정).
# - 9인: 엑셀 표기 누락 칸(3번 13시, 8번 11시)은 휴게 (§22).
# - 11시 순찰 'A'(8·9인)와 14시 순찰 'E'(8인, 통제E는 편성 밖)는 TEMPLATE_OUTSIDE_PATROL로 따로 채움.
FIXED_TEMPLATES = {
    8: (("G1", "G2", "교육", "G3", "L1", "휴게", "L2", "G3", "휴게", "G1"),
        ("G2", "휴게", "G3", "L1", "휴게", "L2", "C1", "순찰", "G1", "G2"),
        ("G3", "L2", "교육", "L2", "G1", "휴게", "G1", "G2", "순찰", "G3"),
        ("L1", "휴게", "L2", "C1", "휴게", "G1", "G2", "휴게", "G3", "L1"),
        ("L2", "순찰", "G1", "G2", "휴게", "G3", "L1", "휴게", "L2", "C1"),
        ("C1", "L1", "순찰", "G1", "G2", "휴게", "G3", "L1", "휴게", "L2"),
        ("순찰", "G1", "G2", "휴게", "G3", "L1", "교육", "L2", "L1", "휴게"),
        ("휴게", "G3", "L1", "휴게", "L2", "G2", "교육", "G1", "G2", "순찰")),
    9: (("G1", "G2", "교육", "G3", "L1", "휴게", "L2", "C1", "순찰", "G1"),
        ("G2", "휴게", "G3", "L1", "휴게", "L2", "C1", "순찰", "G1", "G2"),
        ("G3", "L1", "교육", "L2", "C1", "휴게", "G1", "G2", "휴게", "G3"),
        ("L1", "휴게", "L2", "C1", "휴게", "G1", "G2", "휴게", "G3", "L1"),
        ("L2", "C1", "순찰", "G1", "G2", "휴게", "G3", "L1", "휴게", "L2"),
        ("C1", "순찰", "G1", "G2", "휴게", "G3", "L1", "휴게", "L2", "C1"),
        ("순찰", "G1", "G2", "휴게", "G3", "L1", "교육", "L2", "C1", "휴게"),
        ("휴게", "G3", "L1", "휴게", "L2", "C1", "순찰", "G1", "G2", "휴게"),
        ("휴게", "L2", "C1", "휴게", "G1", "G2", "교육", "G3", "L1", "순찰")),
    10: (("G1", "G2", "교육", "G3", "L1", "휴게", "L2", "C1", "순찰", "C2"),
         ("G2", "휴게", "G3", "L1", "휴게", "L2", "C1", "순찰", "G1", "G2"),
         ("G3", "L1", "교육", "L2", "C1", "휴게", "G1", "G2", "휴게", "G3"),
         ("L1", "휴게", "L2", "C1", "휴게", "C2", "교육", "G1", "G2", "순찰"),
         ("L2", "C1", "교육", "C2", "휴게", "G1", "G2", "휴게", "G3", "L1"),
         ("C1", "C2", "순찰", "G1", "G2", "휴게", "G3", "L1", "휴게", "L2"),
         ("C2", "순찰", "G1", "G2", "휴게", "G3", "L1", "휴게", "L2", "C1"),
         ("순찰", "G1", "G2", "휴게", "G3", "L1", "교육", "L2", "C1", "휴게"),
         ("휴게", "G3", "L1", "휴게", "L2", "C1", "순찰", "C2", "휴게", "G1"),
         ("휴게", "L2", "C1", "순찰", "G1", "G2", "교육", "G3", "L1", "휴게")),
    11: (("G1", "G2", "교육", "G3", "휴게", "L1", "L2", "휴게", "C1", "C2"),
         ("G2", "휴게", "G3", "휴게", "L1", "L2", "교육", "C1", "C2", "순찰"),
         ("G3", "순찰", "L1", "L2", "휴게", "C1", "C2", "휴게", "G1", "G2"),
         ("L1", "L2", "교육", "C1", "C2", "휴게", "G1", "G2", "휴게", "G3"),
         ("L2", "휴게", "C1", "C2", "휴게", "G1", "G2", "순찰", "G3", "휴게"),
         ("C1", "C2", "교육", "G1", "G2", "휴게", "G3", "휴게", "L1", "L2"),
         ("C2", "휴게", "G1", "G2", "휴게", "G3", "순찰", "L1", "L2", "휴게"),
         ("휴게", "G1", "G2", "휴게", "G3", "휴게", "L1", "L2", "순찰", "C1"),
         ("휴게", "G3", "순찰", "L1", "L2", "휴게", "C1", "C2", "휴게", "G1"),
         ("순찰", "L1", "L2", "휴게", "C1", "C2", "교육", "G1", "G2", "휴게"),
         ("휴게", "C1", "C2", "순찰", "G1", "G2", "교육", "G3", "휴게", "L1")),
}
TEMPLATE_SHUTTLE = {8: {0: 6, 3: 4, 5: 2, 8: 5}, 9: {0: 6, 3: 4, 5: 8, 8: 7},
                    10: {0: 7, 3: 5, 5: 4, 8: 8}, 11: {0: 7, 3: 5, 5: 10, 8: 2}}
TEMPLATE_SENIOR_SEAT = {8: 7, 9: 7, 10: 8, 11: 10}   # 08시 순찰로 시작해 17시 휴게로 끝나는 휴근근 자리
# 고정틀에서 A조 직원이 아닌 사람이 맡던 순찰: 8·9인 11시 통제A, 8인 14시 통제E(편성 밖)
TEMPLATE_OUTSIDE_PATROL = {8: {3: "A", 6: "E"}, 9: {3: "A"}}


def fixed_template_size(people) -> int | None:
    """§23 v0.7: 반차자가 없고 출근 인원이 8~11명이면 그 인원의 고정틀을 쓴다 (연차로 줄어든 인원도 포함)."""
    present = [p for p in people if slots_of(p)]
    if any(p.status != "출근" for p in present):
        return None
    return len(present) if len(present) in FIXED_TEMPLATES else None


def fill_outside_patrol(grid: dict, size: int, control: bool, senior_pid=None) -> int | None:
    """고정틀에서 통제A·통제E가 맡던 순찰을 채운다. 통제A 칸은 통제A가 출근했으면 그대로 통제A.

    나머지는 §7 v0.5 순서대로 그 시간 휴게·교육자 중 ① 선임(순찰 2회 미만) → ② 순찰 적은 사람.
    Returns the slot 통제A patrols (or None).
    """
    a_slot = None
    for t, who in sorted(TEMPLATE_OUTSIDE_PATROL.get(size, {}).items()):
        if who == "A" and t in CONTROL_PATROL_SLOTS:       # 통제A 자리: 결근이면 빈칸으로 둠 (일반근무자와 섞지 않음)
            a_slot = t
            continue
        off = [pid for pid, row in grid.items() if row[t] in (REST, STANDBY, EDU)]
        if not off:
            continue
        def rank(pid):
            patrols = grid[pid].count(PATROL)
            return (not (pid == senior_pid and patrols < 2), patrols, sum(c in POSTS for c in grid[pid]), str(pid))
        grid[min(off, key=rank)][t] = PATROL
    return a_slot


def first_row_numbers(grid: dict, people) -> dict:
    """§6 v0.7 HARD: 08시 포스트 줄을 G1→G2→G3→L1→L2→C1→C2 순서로 1..k번,
    08시 비포스트(순찰 → 대기 → 휴게) 다음 08시 이후 출근자 순서로 나머지 번호."""
    present = [p for p in people if any(grid.get(p.pid) or [])]
    def key(p):
        row = grid[p.pid]
        first = row[0]
        if first in FIRST_ROW_ORDER:
            return (0, FIRST_ROW_ORDER.index(first), "")
        if first is not None:
            return (1, (PATROL, STANDBY, REST, EDU).index(first), p.name)
        start = next(t for t, label in enumerate(row) if label is not None)
        return (2, start, p.name)
    return {p.pid: n for n, p in enumerate(sorted(present, key=key), start=1)}


def mark_standby(grid: dict) -> None:
    """§8: 교육 시간이 아닌 시간마다 휴게자 중 1명을 대기로 표기 (골고루, 교육자 → 순찰자 순으로 뒤)."""
    for pid, row in grid.items():
        for t, label in enumerate(row):
            if label == STANDBY:
                row[t] = REST
    count = {pid: 0 for pid in grid}
    edu = {pid: EDU in row for pid, row in grid.items()}
    patrol = {pid: PATROL in row for pid, row in grid.items()}
    for t in SLOTS:
        if t in EDU_SLOTS:
            continue
        resting = [pid for pid, row in grid.items() if row[t] == REST]
        if resting:
            pick = min(resting, key=lambda pid: (count[pid], edu[pid], patrol[pid], str(pid)))
            grid[pick][t] = STANDBY
            count[pick] += 1


def _template_schedule(day, people, size, control, exclude, seed):
    present = [p for p in people if slots_of(p)]
    rng = random.Random(seed)
    senior = senior_of(present)
    for attempt in range(50):
        numbers = {p.pid: p.number for p in present}
        if attempt or any(n is None for n in numbers.values()) or sorted(numbers.values()) != list(range(1, size + 1)):
            shuffled = list(range(1, size + 1))
            rng.shuffle(shuffled)
            numbers = {p.pid: n for p, n in zip(present, shuffled)}
        if senior is not None:                    # §21: 선임은 휴근근 자리(08 순찰)로
            seat = TEMPLATE_SENIOR_SEAT[size]
            holder = next(pid for pid, n in numbers.items() if n == seat)
            numbers[holder], numbers[senior.pid] = numbers[senior.pid], seat
        grid = {p.pid: [None] * 10 for p in people}
        for pid, n in numbers.items():
            grid[pid] = list(FIXED_TEMPLATES[size][n - 1])
        a_slot = fill_outside_patrol(grid, size, control, senior.pid if senior else None)
        mark_standby(grid)
        if all(sum(a != b for pid in grid if pid in prev for a, b in zip(grid[pid], prev[pid])) >= 12
               for prev in exclude):
            break
    else:
        return None, "INFEASIBLE"
    by_number = {n: pid for pid, n in numbers.items()}
    numbered = tuple(DayPerson(p.pid, p.name, p.status, numbers.get(p.pid)) for p in people)
    schedule = DaySchedule(day, numbered, grid, {t: by_number[n] for t, n in TEMPLATE_SHUTTLE[size].items()},
                           f"고정틀 {size}인", control, control_patrol=a_slot, strict=False, fixed_template=size)
    return schedule, schedule.status


def solve_day(day: date, people: list[DayPerson], seconds: int = 20, exclude=(), seed: int = 0,
              control: bool = True):
    """Return (DaySchedule | None, solver status text).

    v0.5: the strict 근근휴 cycle is HARD whenever head count allows it
    (``strict_cycle_possible``); otherwise (예: 11인 이상, 7인 이하) the
    rulebook §3-2 fallback keeps it as a strong soft rule.
    """
    present = [p for p in people if slots_of(p)]
    avail = {p.pid: set(slots_of(p)) for p in present}
    for t in SLOTS:
        need = len(CORE) + (1 if t in PATROL_SLOTS else 0)
        if sum(t in avail[p.pid] for p in present) < need:
            return None, (f"{HOURS[t]} 근무 가능 인원이 {sum(t in avail[p.pid] for p in present)}명이라 "
                          f"핵심 포스트 5곳{'과 순찰' if t in PATROL_SLOTS else ''}을 채울 수 없습니다.")
    size = fixed_template_size(present)
    if size is not None:                                # §23 v0.7: 반차자 없는 8~11인은 고정틀 그대로
        return _template_schedule(day, people, size, control, exclude, seed)
    from ortools.sat.python import cp_model
    strict = strict_cycle_possible(present, True)     # 통제A 출근 여부는 일반근무자 편성에 영향 없음 (v0.9)

    m = cp_model.CpModel()
    x = {}
    for p in present:
        for t in avail[p.pid]:
            for s in STATES:
                x[p.pid, t, s] = m.new_bool_var(f"x_{p.pid}_{t}_{s}")
            m.add_exactly_one(x[p.pid, t, s] for s in STATES)

    def cell(pid, t, s):
        return x.get((pid, t, s), 0)

    def work(pid, t):
        return sum(cell(pid, t, s) for s in POSTS) if t in avail[pid] else 0

    ids = [p.pid for p in present]
    # 통제A 순찰 (§7 v0.5): 순찰이 모자랄 때 통제A가 비번 시간에 1회까지
    a_patrol = {t: m.new_bool_var(f"a_patrol_{t}") for t in sorted(CONTROL_PATROL_SLOTS)}   # 결근이면 그 칸은 빈칸
    if a_patrol:
        m.add(sum(a_patrol.values()) <= 1)
    c1_open, c2_open = {}, {}
    for t in SLOTS:
        for s in CORE:
            m.add(sum(cell(pid, t, s) for pid in ids) == 1)
        c1_open[t] = sum(cell(pid, t, "C1") for pid in ids)
        c2_open[t] = sum(cell(pid, t, "C2") for pid in ids)
        m.add(c1_open[t] <= 1)
        m.add(c2_open[t] <= 1)
        patrol = sum(cell(pid, t, PATROL) for pid in ids) + a_patrol.get(t, 0)
        m.add(patrol == (1 if t in PATROL_SLOTS else 0))
        standby = sum(cell(pid, t, STANDBY) for pid in ids)
        if t in EDU_SLOTS:                              # §20: 교육 시간에는 대기 없음
            m.add(standby == 0)
        else:                                           # §8 v0.5: 휴게자가 있으면 그중 정확히 1명 대기
            m.add(standby <= 1)
            for pid in ids:
                m.add(cell(pid, t, REST) <= standby)
    for t in SLOTS:                                     # §11 v0.5 HARD: C2는 C1이 매시간 열려 있을 때만
        for u in SLOTS:
            m.add(c2_open[t] <= c1_open[u])
    for pid in ids:
        for t in SLOTS:
            if t in avail[pid] and t + 1 in avail[pid]:
                for s in POSTS:             # §4 hard: no same post twice in a row
                    m.add(x[pid, t, s] + x[pid, t + 1, s] <= 1)
        m.add(sum(cell(pid, t, s) for t in SLOTS for s in C_POSTS) <= 2)   # §10 hard

    senior = senior_of(present)
    phases = {}
    if strict:   # §3 HARD: 근근휴 반복, 시작은 근근휴 / 근휴근근 / 휴근근 (대기·순찰·교육·휴게 = 휴)
        for pid in ids:
            window = sorted(avail[pid])
            phase = [m.new_bool_var("") for _ in range(3)]
            m.add_exactly_one(phase)
            phases[pid] = phase
            for i, t in enumerate(window):
                m.add(work(pid, t) == sum(phase[k] for k in range(3) if (i + k) % 3 != 2))

    penalties = []

    def penal(weight, expr_bool):
        penalties.append(weight * expr_bool)

    if senior is not None:          # §21 HARD: 선임은 첫 타임을 휴게·대기·순찰로 시작 (가급적 순찰)
        first = min(avail[senior.pid])
        m.add(work(senior.pid, first) == 0)
        if first in PATROL_SLOTS:
            penal(40, 1 - x[senior.pid, first, PATROL])

    full = [p.pid for p in present if p.status == "출근"]
    for pid in ids:
        slots = sorted(avail[pid])
        w = {t: work(pid, t) for t in slots}
        for t in slots:
            if not strict:                               # §3-2 fallback: 근근휴를 강한 소프트로
                if t + 2 in avail[pid] and t + 1 in avail[pid]:
                    tri = m.new_bool_var("")
                    m.add(tri >= w[t] + w[t + 1] + w[t + 2] - 2)
                    penal(1000, tri)
                if t + 1 in avail[pid]:
                    double_off = m.new_bool_var("")
                    m.add(double_off >= 1 - w[t] - w[t + 1])
                    penal(200, double_off)
                if t - 1 in avail[pid] and t + 1 in avail[pid]:
                    lone = m.new_bool_var("")
                    m.add(lone >= w[t] - w[t - 1] - w[t + 1])
                    penal(100, lone)
            if t >= 2 and t - 1 in avail[pid] and t - 2 in avail[pid] and t in PATROL_SLOTS:
                late = m.new_bool_var("")                # §7: patrol after two posts
                m.add(late >= x[pid, t, PATROL] - w[t - 1])
                m.add(late >= x[pid, t, PATROL] - w[t - 2])
                penal(8, late)
            for s, nxt in ROTATION.items():              # §5 soft: G1 → G2 → G3 → L1 → L2
                if t + 1 in avail[pid]:
                    follow = m.new_bool_var("")
                    m.add(follow <= x[pid, t, s])
                    m.add(follow <= x[pid, t + 1, nxt])
                    penal(-3, follow)
        person = next(p for p in present if p.pid == pid)
        target = {"오후반차": ({0, 1, 3, 4}, 2), "오전반차": ({5, 6, 8, 9}, 7)}.get(person.status)
        if target and person is not senior:              # §13/§14 정배 (근근휴근근)
            works, off = target
            for t in works:
                penal(300, 1 - w[t])
            penal(300, w[off])
        if target:
            for t in avail[pid] & PATROL_SLOTS:          # §13/§14: 반차자의 비포스트 턴은 가능한 한 순찰
                penal(150, 1 - w[t] - x[pid, t, PATROL])
        c_count = sum(cell(pid, t, s) for t in SLOTS for s in C_POSTS)
        if 0 in avail[pid] and person.status == "출근":  # §10: 08 off-starter gets C at most once
            c_twice = m.new_bool_var("")
            m.add(c_count >= 2).only_enforce_if(c_twice)
            m.add(c_count <= 1).only_enforce_if(c_twice.Not())
            two_c = m.new_bool_var("")
            m.add(two_c >= c_twice - w[0])
            penal(80, two_c)

    def spread(values, name, weight):
        if len(values) < 2:
            return
        hi, lo = m.new_int_var(0, 20, f"{name}_hi"), m.new_int_var(0, 20, f"{name}_lo")
        for v in values:
            m.add(hi >= v)
            m.add(lo <= v)
        penal(weight, hi - lo)

    patrols = {pid: sum(cell(pid, t, PATROL) for t in SLOTS) for pid in ids}
    standbys = {pid: sum(cell(pid, t, STANDBY) for t in SLOTS) for pid in ids}
    edus = {pid: sum(cell(pid, t, REST) for t in EDU_SLOTS) for pid in ids}
    spread([sum(work(pid, t) for t in SLOTS) for pid in full], "work", 400)      # §12
    spread([sum(cell(pid, t, s) for t in SLOTS for s in C_POSTS) for pid in full], "c", 60)
    spread([sum(work(pid, t) for t in SLOTS) + patrols[pid] + edus[pid] for pid in full], "load", 100)
    # §7 v0.5: 순찰은 1인 1회. 불가피하면 ① 통제A 1회 → ② 선임 2회 → ③ 그 밖의 사람 2회
    for pid in ids:
        extra = m.new_int_var(0, 10, "")
        m.add(extra >= patrols[pid] - 1)
        penal(150 if senior is not None and pid == senior.pid else 500, extra)
    for var in a_patrol.values():
        penal(60, var)
    # §8 v0.5: 대기는 표기상 1명 (= 휴게). 골고루, 교육한 사람 → 순찰한 사람 순으로 뒤로
    spread([standbys[pid] for pid in full], "standby", 50)
    for pid in ids:
        had_edu, had_patrol = m.new_bool_var(""), m.new_bool_var("")
        m.add(edus[pid] >= 1).only_enforce_if(had_edu)
        m.add(edus[pid] == 0).only_enforce_if(had_edu.Not())
        m.add(patrols[pid] >= 1).only_enforce_if(had_patrol)
        m.add(patrols[pid] == 0).only_enforce_if(had_patrol.Not())
        for flag, weight in ((had_edu, 20), (had_patrol, 10)):
            late = m.new_int_var(0, 10, "")
            m.add(late >= standbys[pid] - 10 * (1 - flag))
            penal(weight, late)
        if pid not in full:
            penal(5, standbys[pid])

    # §6 v0.7: 08시 줄 번호 순서(1→G1, 2→G2 …)는 풀이 뒤 first_row_numbers로 번호를 다시 매겨 HARD로 맞춘다.

    for previous in exclude:                               # regeneration: at least 12 cells differ
        same = [x[pid, t, REST if previous[pid][t] == EDU else previous[pid][t]]
                for pid in ids if pid in previous
                for t in avail[pid] if previous[pid][t] in STATES + (EDU,)]
        if same:
            m.add(sum(same) <= len(same) - 12)

    m.minimize(sum(penalties))
    solver = cp_model.CpSolver()
    solver.parameters.max_time_in_seconds = seconds
    solver.parameters.num_search_workers = 8
    solver.parameters.random_seed = seed
    status = solver.solve(m)
    if status not in (cp_model.OPTIMAL, cp_model.FEASIBLE):
        return None, solver.status_name(status)
    grid = {}
    for p in people:
        row = []
        for t in SLOTS:
            if p.pid in avail and t in avail[p.pid]:
                label = next(s for s in STATES if solver.value(x[p.pid, t, s]))
                row.append(EDU if label == REST and t in EDU_SLOTS else label)
            else:
                row.append(None)
        grid[p.pid] = row
    a_slot = next((t for t, var in a_patrol.items() if solver.value(var)), None)
    numbers = first_row_numbers(grid, people)
    people = [DayPerson(p.pid, p.name, p.status, numbers.get(p.pid)) for p in people]
    schedule = DaySchedule(day, tuple(people), grid, {}, solver.status_name(status), control,
                           control_patrol=a_slot, strict=strict)
    schedule.shuttle = assign_shuttle(schedule)
    return schedule, solver.status_name(status)


def assign_shuttle(schedule: DaySchedule) -> dict:
    """§9: C1/C2 worker first, otherwise the L1/L2 worker with fewer shuttle duties."""
    counts, out = {}, {}
    for t in sorted(SHUTTLE):
        holders = {schedule.grid[pid][t]: pid for pid in schedule.grid if schedule.grid[pid][t]}
        pid = holders.get("C1") or holders.get("C2")
        if pid is None:
            candidates = [holders[s] for s in ("L1", "L2") if s in holders]
            pid = min(candidates, key=lambda c: counts.get(c, 0)) if candidates else None
        if pid:
            out[t] = pid
            counts[pid] = counts.get(pid, 0) + 1
    return out


EMERGENCY_KINDS = ("오후반차 (13시 퇴근)", "긴급 이탈 (선택 시간부터)")
HALF_DAY_LEAVE = 5                                  # 13시


def emergency_candidates(base: DaySchedule, start: int) -> list[DayPerson]:
    """start 슬롯에 아직 근무 가능한 사람 (긴급 반차·이탈자로 고를 수 있는 사람)."""
    return [p for p in sorted(base.people, key=lambda p: (p.number is None, p.number or 0))
            if start in slots_of(p)]


def reoptimize_day(base: DaySchedule, start: int, pid: str, leave_from: int, kind: str = EMERGENCY_KINDS[1],
                   seconds: int = 20, exclude=(), seed: int = 0):
    """§25 긴급 반차·이탈 재편성. Return (DaySchedule | None, 상태 문장).

    - start 이전 슬롯(08시 ~ start-1)은 기존 배정 그대로 LOCK.
    - pid는 leave_from 슬롯부터 근무 불가.
    - start 이후: 근근휴 패턴(휴 2칸 연속·근 3칸 연속·휴-근-휴 금지, LOCK 경계 포함)만 HARD,
      나머지 기존 하드룰은 큰 벌점의 '강력 권장'으로 지향한다.
    - §27 v1.0: G1~L2는 무조건 채운다. 일반근무자로 안 되면 통제A → 통제E, 그래도 안 되면 INFEASIBLE(해 없음).
    """
    if not 1 <= start <= 9:
        return None, "재편성 시작 시간은 09시~17시 중에서 골라야 합니다."
    if leave_from < start:
        return None, "반차·이탈 시각이 재편성 시작 시간보다 빠를 수 없습니다."
    person = next((p for p in base.people if p.pid == pid), None)
    if person is None or start not in slots_of(person):
        return None, "선택한 사람은 재편성 시작 시간에 이미 근무 가능 인원이 아닙니다."
    from ortools.sat.python import cp_model

    people = tuple(replace(p, leave_from=leave_from) if p.pid == pid else p for p in base.people)
    avail = {p.pid: set(slots_of(p)) for p in people if slots_of(p)}
    ids = list(avail)
    future_states = POSTS + (PATROL, REST)            # 대기는 풀이 뒤 표기 (§8: 대기 = 휴게)
    locked = {}
    for q in ids:
        for t in avail[q]:
            if t < start:
                label = base.grid[q][t]
                locked[q, t] = REST if label in (EDU, STANDBY) else label

    m = cp_model.CpModel()
    x = {}
    for q in ids:
        for t in avail[q]:
            if t >= start:
                for st in future_states:
                    x[q, t, st] = m.new_bool_var("")
                m.add_exactly_one(x[q, t, st] for st in future_states)

    def cell(q, t, st):
        if (q, t) in locked:
            return int(locked[q, t] == st or (st == REST and locked[q, t] == STANDBY))
        return x.get((q, t, st), 0)

    def work(q, t):
        return sum(cell(q, t, st) for st in POSTS) if t in avail[q] else 0

    penalties = []

    def penal(weight, expr):
        penalties.append(weight * expr)

    # 통제A 순찰: 한 표에 1회만 표시할 수 있으므로 LOCK 구간에 이미 있으면 새로 두지 않음. 17시 제외.
    a_locked = base.control_patrol if base.control_patrol is not None and base.control_patrol < start else None
    a_patrol = ({t: m.new_bool_var("") for t in sorted(CONTROL_PATROL_SLOTS) if t >= start}
                if a_locked is None else {})
    if a_patrol:
        m.add(sum(a_patrol.values()) <= 1)
    # §27 v1.0: 일반근무자로 못 채우는 핵심 포스트는 통제A(출근, 통제 근무가 아닌 시간, 순찰 중이 아님) 1명 →
    # 통제E 1명(통제A를 쓸 수 없을 때만) 순으로 채운다. 그래도 비면 해 없음.
    fill_a, fill_e = {}, {}
    for t in range(start, 10):
        a_free = base.control and t not in CONTROL_SLOTS
        for st in CORE:
            if a_free:
                fill_a[t, st] = m.new_bool_var("")
                penal(1_000_000, fill_a[t, st])
            fill_e[t, st] = m.new_bool_var("")
            penal(3_000_000, fill_e[t, st])
        a_busy = sum(fill_a.get((t, st), 0) for st in CORE) + a_patrol.get(t, 0)
        if a_free:
            m.add(a_busy <= 1)
            m.add(sum(fill_e[t, st] for st in CORE) <= a_busy)          # 통제A가 비어 있으면 E를 쓰지 않음
        else:
            m.add(sum(fill_e[t, st] for st in CORE) <= 1)
    c1_open, c2_open = {}, {}
    for t in SLOTS:
        c1_open[t] = sum(cell(q, t, "C1") for q in ids)
        c2_open[t] = sum(cell(q, t, "C2") for q in ids)
        if t < start:
            continue
        for st in POSTS:                                 # 한 포스트에 2명은 표가 성립하지 않음 (HARD)
            m.add(sum(cell(q, t, st) for q in ids) <= 1)
        patrol = sum(cell(q, t, PATROL) for q in ids) + a_patrol.get(t, 0)
        m.add(patrol <= 1)
        for st in CORE:                                  # §27 HARD: 핵심 포스트는 한 타임도 비우지 않음
            m.add(sum(cell(q, t, st) for q in ids) + fill_a.get((t, st), 0) + fill_e[t, st] == 1)
        if t in PATROL_SLOTS:                            # 강력 권장: 순찰 충족
            penal(30000, 1 - patrol)
        else:
            m.add(patrol == 0)
    any_c2 = m.new_bool_var("")                          # 강력 권장: C2는 C1이 매시간 열릴 때만
    for t in SLOTS:
        m.add(any_c2 >= c2_open[t])
    for t in SLOTS:
        if isinstance(c1_open[t], int) and c1_open[t] == 1:
            continue
        gap = m.new_bool_var("")
        m.add(gap >= any_c2 - c1_open[t])
        penal(5000, gap)

    for q in ids:                                        # §25 HARD: 근근휴 패턴 (LOCK 경계 포함)
        for t in SLOTS:
            if t + 1 >= start and t in avail[q] and t + 1 in avail[q]:
                m.add(work(q, t) + work(q, t + 1) >= 1)              # 휴 2칸 연속 금지
            if t + 2 >= start and all(u in avail[q] for u in (t, t + 1, t + 2)):
                m.add(work(q, t) + work(q, t + 1) + work(q, t + 2) <= 2)   # 근 3칸 연속 금지
                m.add(work(q, t) - work(q, t + 1) + work(q, t + 2) >= 0)   # 휴-근-휴 금지

    senior = senior_of(people)
    patrols = {q: sum(cell(q, t, PATROL) for t in SLOTS if t in avail[q]) for q in ids}
    for q in ids:
        for t in SLOTS:
            if t + 1 >= start and t in avail[q] and t + 1 in avail[q]:
                for st in POSTS:                         # 강력 권장: 같은 포스트 연속 금지
                    same = m.new_bool_var("")
                    m.add(same >= cell(q, t, st) + cell(q, t + 1, st) - 1)
                    penal(20000, same)
            if t >= start and t >= 2 and t in PATROL_SLOTS and t - 1 in avail[q] and t - 2 in avail[q] \
                    and t in avail[q]:
                late = m.new_bool_var("")                # §7: 근근 다음 순찰
                m.add(late >= x[q, t, PATROL] - work(q, t - 1))
                m.add(late >= x[q, t, PATROL] - work(q, t - 2))
                penal(8, late)
            # §25 v0.9 강력 권장: 묶음 순서 G1 → G2 → G3 → L1 → L2 → G1 (휴 1칸 건너서도 이어짐)
            for gap in (1, 2):
                u = t + gap
                if u >= start and t in avail[q] and u in avail[q]:
                    for st, nxt in ROTATION.items():
                        follow = m.new_bool_var("")
                        m.add(follow <= cell(q, t, st))
                        m.add(follow <= x[q, u, nxt])
                        if gap == 2:
                            m.add(follow <= 1 - work(q, t + 1))
                        penal(-300, follow)
        c_count = sum(cell(q, t, st) for t in SLOTS if t in avail[q] for st in C_POSTS)
        over_c = m.new_int_var(0, 10, "")                # 강력 권장: C1+C2 2회까지
        m.add(over_c >= c_count - 2)
        penal(20000, over_c)
        extra = m.new_int_var(0, 10, "")                 # §7: 순찰 1인 1회, 불가피하면 통제A → 선임
        m.add(extra >= patrols[q] - 1)
        penal(300 if senior is not None and q == senior.pid else 1000, extra)
    for var in a_patrol.values():
        penal(200, var)

    def spread(values, weight):
        if len(values) < 2:
            return
        hi, lo = m.new_int_var(0, 40, ""), m.new_int_var(0, 40, "")
        for v in values:
            m.add(hi >= v)
            m.add(lo <= v)
        penal(weight, hi - lo)

    full = [q for q in ids if len(avail[q]) == 10]
    spread([sum(work(q, t) for t in SLOTS if t in avail[q]) for q in full], 400)
    # §25 v0.9 강력 권장: 묶음 (G1)(G2·G3)(L1·L2) 근무가 사람마다 고르게 (C는 위의 기존 규칙이 더 강함)
    for group in ("G1", "G23", "L"):
        posts = [st for st, g in POST_GROUP.items() if g == group]
        spread([sum(cell(q, t, st) for t in SLOTS if t in avail[q] for st in posts) for q in full], 300)
    spread([sum(FATIGUE[st] * cell(q, t, st) for t in SLOTS if t in avail[q] for st in FATIGUE) for q in full], 150)
    spread([sum(cell(q, t, st) for t in SLOTS if t in avail[q] for st in C_POSTS) for q in full], 60)

    future = [(q, t) for q in ids for t in avail[q] if t >= start]
    for previous in exclude:                             # 재생성: LOCK 이후 칸이 충분히 달라야 함
        same = [x[q, t, REST if previous[q][t] in (EDU, STANDBY) else previous[q][t]]
                for q, t in future if q in previous and previous[q][t] in future_states + (EDU, STANDBY)]
        if same:
            m.add(sum(same) <= len(same) - min(6, max(1, len(same) // 4)))

    m.minimize(sum(penalties))
    solver = cp_model.CpSolver()
    solver.parameters.max_time_in_seconds = seconds
    solver.parameters.num_search_workers = 8
    solver.parameters.random_seed = seed
    status = solver.solve(m)
    if status == cp_model.INFEASIBLE:
        return None, "INFEASIBLE"
    if status not in (cp_model.OPTIMAL, cp_model.FEASIBLE):
        return None, solver.status_name(status)
    grid = {}
    for p in people:
        row = []
        for t in SLOTS:
            if p.pid not in avail or t not in avail[p.pid]:
                row.append(None)
            elif t < start:
                row.append(base.grid[p.pid][t])
            else:
                label = next(st for st in future_states if solver.value(x[p.pid, t, st]))
                row.append(EDU if label == REST and t in EDU_SLOTS else label)
        grid[p.pid] = row
    _mark_standby_from(grid, start)
    a_slot = a_locked if a_locked is not None else next((t for t, v in a_patrol.items() if solver.value(v)), None)
    fill = {t: dict(posts) for t, posts in base.fill.items() if t < start}
    for who, chosen in (("A", fill_a), ("E", fill_e)):
        for (t, st), var in chosen.items():
            if solver.value(var):
                fill.setdefault(t, {})[st] = who
    info = {"pid": pid, "from": leave_from, "kind": kind, "start": start}
    info["history"] = [{k: v for k, v in e.items() if k != "history"} for e in emergency_events(base)] + [dict(info)]
    schedule = DaySchedule(base.day, people, grid, {}, f"긴급 재편성 ({solver.status_name(status)})", base.control,
                           control_patrol=a_slot, strict=True, fixed_template=None,
                           locked_through=start - 1, emergency=info, fill=fill)
    shuttle = assign_shuttle(schedule)
    schedule.shuttle = {t: (base.shuttle[t] if t < start else shuttle[t])
                        for t in SHUTTLE if (t < start and t in base.shuttle) or (t >= start and t in shuttle)}
    return schedule, schedule.status


def emergency_events(schedule: DaySchedule) -> list[dict]:
    """이 표까지 쌓인 긴급 반차·이탈 전부 (연쇄 재편성 포함, 오래된 순). 예전 저장본은 마지막 1건만."""
    info = schedule.emergency
    if not info:
        return []
    return list(info.get("history") or [info])


def _mark_standby_from(grid: dict, start: int) -> None:
    """§8 대기 표기를 start 슬롯부터만 다시 적는다 (LOCK 구간 표기는 그대로)."""
    count = {pid: row[:start].count(STANDBY) for pid, row in grid.items()}
    edu = {pid: EDU in row for pid, row in grid.items()}
    patrol = {pid: PATROL in row for pid, row in grid.items()}
    for t in range(start, 10):
        if t in EDU_SLOTS:
            continue
        resting = [pid for pid, row in grid.items() if row[t] == REST]
        if resting:
            pick = min(resting, key=lambda pid: (count[pid], edu[pid], patrol[pid], str(pid)))
            grid[pick][t] = STANDBY
            count[pick] += 1


def number_people(people: list[DayPerson], rng: random.Random | None = None) -> list[DayPerson]:
    """Random display numbers 1..n for present people (absent people get none)."""
    rng = rng or random.Random()
    present = [p for p in people if slots_of(p)]
    numbers = list(range(1, len(present) + 1))
    rng.shuffle(numbers)
    given = {p.pid: n for p, n in zip(present, numbers)}
    return [DayPerson(p.pid, p.name, p.status, given.get(p.pid)) for p in people]


# ---------------------------------------------------------------- independent validator
_CYCLE_TEXT = ("WWO" * 5, "WOW" * 5, "OWW" * 5)    # 근근휴 / 근휴근근 / 휴근근 시작


def _validator_cycle_possible(schedule: DaySchedule) -> bool:
    """Validator's own check (written apart from the solver) of whether the strict cycle fits."""
    rows = {pid: [t for t, label in enumerate(row) if label is not None] for pid, row in schedule.grid.items()}
    rows = {pid: w for pid, w in rows.items() if w}
    names = {p.pid: p.name for p in schedule.people}
    senior = next((pid for n in SENIOR_NAMES for pid in rows if names[pid] == n), None)
    kinds = {}
    for pid, window in rows.items():
        key = (tuple(window), pid == senior)
        kinds[key] = kinds.get(key, 0) + 1

    def options(window, is_senior, count):
        texts = [_CYCLE_TEXT[2]] if is_senior else list(_CYCLE_TEXT)
        if count == 1:
            return [[text] for text in texts]
        out = []
        for i in range(count + 1):
            for j in range(count + 1 - i):
                out.append([texts[0]] * i + [texts[1 % len(texts)]] * j + [texts[-1]] * (count - i - j))
        return out

    groups = list(kinds.items())

    def search(g, load):
        if g == len(groups):
            if min(load) < 5 or max(load) > 7 or (max(load) == 7 and min(load) < 6):
                return False
            heads = [sum(t in w for (w, _), c in groups for _ in range(c)) for t in range(10)]
            short = [t for t in range(10) if t in PATROL_SLOTS and heads[t] - load[t] < 1]
            return not short or (len(short) == 1
                                 and short[0] in PATROL_SLOTS - CONTROL_SLOTS - {9})
        (window, is_senior), count = groups[g]
        for choice in options(window, is_senior, count):
            new = list(load)
            for text in choice:
                for i, t in enumerate(window):
                    new[t] += text[i] == "W"
            if max(new) <= 7 and search(g + 1, new):
                return True
        return False

    return search(0, [0] * 10)


# §25 긴급 재편성: 근근휴 패턴(주간-3)과 표 자체가 성립하는 조건(근무가능시간·중복 배정)만 HARD,
# 나머지 기존 하드룰은 '강력 권장'으로 따로 보여 준다.
# §27 v1.0: 핵심 포스트 빈칸 금지(주간-2-1)와 통제A·E 메움 규칙(주간-27)은 긴급 재편성에서도 무조건 HARD.
EMERGENCY_HARD_RULES = frozenset({"주간-1", "주간-2", "주간-2-1", "주간-3", "주간-27"})


def validate_day(schedule: DaySchedule) -> list[dict]:
    """HARD 위반 목록 (0건이어야 확정 가능). 긴급 재편성표는 §25 HARD만."""
    issues = _check_day(schedule)
    if schedule.emergency is None:
        return issues
    return [e for e in issues if e["rule"] in EMERGENCY_HARD_RULES]


def emergency_advisories(schedule: DaySchedule) -> list[dict]:
    """긴급 재편성표에서 지키지 못한 '강력 권장' 항목 (기존 하드룰)."""
    if schedule.emergency is None:
        return []
    return [e for e in _check_day(schedule) if e["rule"] not in EMERGENCY_HARD_RULES]


def _check_day(schedule: DaySchedule) -> list[dict]:
    errors = []

    def add(rule, detail):
        errors.append({"rule": rule, "detail": detail})

    people = {p.pid: p for p in schedule.people}
    full_house = [p for p in schedule.people if any(schedule.grid[p.pid])]
    emergency = schedule.emergency
    template_ok = (len(full_house) in (8, 9, 10, 11) and all(p.status == "출근" for p in full_house)
                   and emergency is None and all(p.leave_from is None for p in full_house))
    if schedule.fixed_template is not None:      # §23 v0.7: 고정틀 — 번호 자리와 칸이 고정틀과 같은지
        if not template_ok or schedule.fixed_template != len(full_house):
            add("주간-23", "반차자 없는 8~11인이 아닌데 고정틀로 표시됨")
        else:
            rows = FIXED_TEMPLATES[schedule.fixed_template]
            outside = TEMPLATE_OUTSIDE_PATROL.get(schedule.fixed_template, {})
            for p in full_house:
                expect = rows[p.number - 1] if p.number and p.number <= len(rows) else None
                got = [REST if label == STANDBY else label for label in schedule.grid[p.pid]]
                if expect is None:
                    add("주간-23", f"{p.name} 번호 {p.number}가 고정틀 자리에 없음")
                    continue
                for t, (a, b) in enumerate(zip(got, expect)):
                    # 통제A·E가 맡던 순찰을 그 시간 휴게·교육자가 대신 맡은 칸만 허용
                    if a != b and not (t in outside and a == PATROL and b in (REST, EDU)):
                        add("주간-23", f"{p.name} 줄이 고정틀 {p.number}번 자리와 다름 ({HOURS[t]} {a} ≠ {b})")
                        break
    cycle_required = (schedule.fixed_template is None and emergency is None
                      and _validator_cycle_possible(schedule))
    if cycle_required and not schedule.strict:
        add("주간-3", "근근휴 사이클을 지킬 수 있는 인원인데 완화 편성으로 표시됨")
    if template_ok and schedule.fixed_template is None:
        add("주간-23", f"반차자 없는 {len(full_house)}인인데 고정틀을 쓰지 않음")
    by_number = sorted(full_house, key=lambda p: (p.number is None, p.number or 0))
    numbers = [p.number for p in by_number]
    if numbers != list(range(1, len(by_number) + 1)):
        add("주간-6", f"번호가 1~{len(by_number)} 순서가 아님 ({numbers})")
    else:                                         # §6 v0.7 HARD: 08시 1→G1, 2→G2 … (포스트가 번호 앞쪽에 순서대로)
        firsts = [schedule.grid[p.pid][0] for p in by_number]
        k = sum(f in POSTS for f in firsts)
        if firsts[:k] != list(FIRST_ROW_ORDER[:k]):
            add("주간-6", "08시 줄이 번호 1→G1, 2→G2 … 순서가 아님 ("
                + ", ".join(f"{p.number}:{f}" for p, f in zip(by_number, firsts)) + ")")
    for pid, row in schedule.grid.items():
        allowed = set(slots_of(people[pid]))
        for t, label in enumerate(row):
            if (label is not None) != (t in allowed):
                add("주간-1", f"{people[pid].name} {HOURS[t]} 근무가능시간과 다름")
            if label is not None and label not in STATES + (EDU,):
                add("주간-2", f"{people[pid].name} {HOURS[t]} 알 수 없는 배정 {label}")
        for t in range(9):
            if row[t] in POSTS and row[t] == row[t + 1]:
                add("주간-4", f"{people[pid].name} {HOURS[t]}~{HOURS[t + 1]} {row[t]} 연속")
        if sum(label in C_POSTS for label in row) > 2:
            add("주간-10", f"{people[pid].name} C1+C2 {sum(label in C_POSTS for label in row)}회")
        text = "".join("W" if label in POSTS else "O" for label in row if label is not None)
        if cycle_required and text and not any(text == c[:len(text)] for c in _CYCLE_TEXT):
            add("주간-3", f"{people[pid].name} 근근휴 사이클 아님 ({text.replace('W', '근').replace('O', '휴')})")
        if emergency is not None:                 # §25: LOCK 이후 칸이 하나라도 걸린 구간은 근근휴 패턴 HARD
            start = emergency["start"]
            on = ["W" if label in POSTS else "O" if label is not None else None for label in row]
            for t in range(10):
                if t + 1 < 10 and t + 1 >= start and on[t] == on[t + 1] == "O":
                    add("주간-3", f"{people[pid].name} {HOURS[t]}~{HOURS[t + 1]} 휴게 2칸 연속")
                if t + 2 < 10 and t + 2 >= start and None not in on[t:t + 3]:
                    trio = "".join(on[t:t + 3])
                    if trio == "WWW":
                        add("주간-3", f"{people[pid].name} {HOURS[t]}부터 근무 3칸 연속")
                    elif trio == "OWO":
                        add("주간-3", f"{people[pid].name} {HOURS[t + 1]} 휴-근-휴 (외톨이 근무)")
    c1_hours = sum("C1" in [row[t] for row in schedule.grid.values()] for t in range(10))
    for t, posts in schedule.fill.items():       # §27: 통제A·통제E 메움은 긴급 재편성의 핵심 포스트에만
        if emergency is None:
            add("주간-27", f"{HOURS[t]} 긴급 재편성이 아닌데 통제A·E가 포스트를 맡음")
        whos = list(posts.values())
        for post, who in posts.items():
            if post not in CORE or who not in ("A", "E"):
                add("주간-27", f"{HOURS[t]} {post} '{who}' 메움은 G1~L2에 A·E만 가능")
        if whos.count("A") > 1 or whos.count("E") > 1:
            add("주간-27", f"{HOURS[t]} 통제A·E는 한 시간에 각 1자리만 맡을 수 있음")
        a_free = schedule.control and t not in CONTROL_SLOTS and schedule.control_patrol != t
        if "A" in whos and not a_free:
            add("주간-27", f"{HOURS[t]} 통제A가 결근·통제 근무·순찰 중인데 포스트를 맡음")
        if "E" in whos and a_free and "A" not in whos:
            add("주간-27", f"{HOURS[t]} 통제A가 비어 있는데 통제E로 채움 (A 먼저)")
    for t in range(10):
        column = [row[t] for row in schedule.grid.values()]
        filled = schedule.fill.get(t, {})
        for post in CORE:
            count = column.count(post) + (post in filled)
            if count > 1:
                add("주간-2", f"{HOURS[t]} {post} {count}명 (중복 배정)")
            elif count == 0:
                add("주간-2-1", f"{HOURS[t]} {post} 빈 포스트")
        if column.count("C1") > 1 or column.count("C2") > 1:
            add("주간-2", f"{HOURS[t]} C1 {column.count('C1')}명 / C2 {column.count('C2')}명")
        expected = 1 if t in PATROL_SLOTS else 0
        by_a = 1 if schedule.control_patrol == t else 0
        if column.count(PATROL) + by_a > 1:
            add("주간-2", f"{HOURS[t]} 순찰 {column.count(PATROL) + by_a}명 (중복 배정)")
        elif column.count(PATROL) + by_a != expected:
            add("주간-7", f"{HOURS[t]} 순찰 {column.count(PATROL) + by_a}명 (필요 {expected}명)")
        if column.count(STANDBY) > 1:
            add("주간-8", f"{HOURS[t]} 대기 {column.count(STANDBY)}명")
        if t not in EDU_SLOTS and REST in column and STANDBY not in column:
            add("주간-8", f"{HOURS[t]} 휴게자가 있는데 대기 표기 없음")
        if t in EDU_SLOTS and (STANDBY in column or REST in column):
            add("주간-8-1", f"{HOURS[t]} 교육 시간인데 대기·휴게자가 있음")
        if t not in EDU_SLOTS and EDU in column:
            add("주간-8-1", f"{HOURS[t]} 교육 시간이 아닌데 교육 표기")
    c2_hours = [HOURS[t] for t in range(10) if "C2" in [row[t] for row in schedule.grid.values()]]
    if c2_hours and c1_hours < 10:
        add("주간-11", f"C2 운영({', '.join(c2_hours)}) 중인데 C1이 {c1_hours}시간만 열림 (C2는 C1 매시간일 때만)")
    if schedule.control_patrol is not None and (
            schedule.control_patrol in CONTROL_SLOTS
            or schedule.control_patrol not in PATROL_SLOTS):
        add("주간-7", f"통제A {HOURS[schedule.control_patrol]} 순찰 불가 시간")
    if schedule.control_patrol == 9:              # v0.7 HARD: 통제A는 마지막 순찰 금지 (독립 검증)
        add("주간-7", "통제A가 마지막 17시 순찰을 맡음 (금지)")
    for t, kind in SHUTTLE.items():
        pid = schedule.shuttle.get(t)
        column = {row[t] for row in schedule.grid.values()}
        label = schedule.grid.get(pid, [None] * 10)[t] if pid else None
        c_open = bool(column & set(C_POSTS))
        if label is None or label not in (C_POSTS if c_open else ("L1", "L2")):
            add("주간-9", f"{HOURS[t]} 셔틀 {kind} 담당이 규칙과 다름")
    present_names = {p.name: p for p in schedule.people if any(schedule.grid[p.pid])}
    senior = next((present_names[n] for n in SENIOR_NAMES if n in present_names), None)
    if senior is not None:
        row = schedule.grid[senior.pid]
        first = next(label for label in row if label is not None)
        if first in POSTS:
            add("주간-21", f"선임 {senior.name} 첫 타임이 {first} (휴게·대기·순찰로 시작해야 함)")
    return errors


def day_stats(schedule: DaySchedule) -> list[dict]:
    rows = []
    for p in sorted(schedule.people, key=lambda p: (p.number is None, p.number or 0)):
        row = schedule.grid[p.pid]
        if not any(row):
            continue
        status = p.status
        if p.leave_from is not None:
            status = f"{p.status} → {HOURS[p.leave_from]} 퇴근"
        rows.append({
            "직원": f"{p.number} {p.name}" if p.number else p.name, "상태": status,
            "포스트": sum(label in POSTS for label in row),
            "G·L": sum(label in CORE for label in row), "C": sum(label in C_POSTS for label in row),
            "순찰": row.count(PATROL), "대기": row.count(STANDBY), "교육": row.count(EDU),
            "휴게": row.count(REST),
            "셔틀": sum(1 for pid in schedule.shuttle.values() if pid == p.pid),
            "피로도": fatigue_of(row),
        })
    return rows


def fill_warnings(schedule: DaySchedule) -> list[str]:
    """§27: 일반근무자로 채울 수 없어 통제A·통제E가 맡은 자리 (이 자리를 누군가 채우지 않으면 해가 없음)."""
    out = []
    for t in sorted(schedule.fill):
        for post, who in sorted(schedule.fill[t].items(), key=lambda kv: CORE.index(kv[0])):
            name = "통제A" if who == "A" else "통제E(편성 밖)"
            out.append(f"{HOURS[t]} {post}: 남은 일반근무자로는 채울 수 없어 {name}로 채움 — "
                       "이 자리를 누군가 채우지 않으면 해가 없습니다.")
    return out


def day_findings(schedule: DaySchedule) -> list[str]:
    """Soft-rule notes (특이사항) in plain Korean."""
    notes = []
    people = {p.pid: p for p in schedule.people}
    if schedule.emergency:
        info = schedule.emergency
        notes.append(f"긴급 재편성: {HOURS[info['start'] - 1]}까지 기존 배정 LOCK, {HOURS[info['start']]}부터 다시 편성.")
        for e in emergency_events(schedule):
            who = people[e["pid"]]
            notes.append(f"{who.number}번 {who.name} {e['kind']} → {HOURS[e['from']]}부터 근무 불가.")
        notes.append("긴급 재편성표에서 꼭 지킨 규칙은 근근휴 패턴과 G1~L2 채우기이고, "
                     "나머지 규칙은 가능한 한 지켰습니다(§25·§27).")
        notes.extend(fill_warnings(schedule))
        for e in emergency_advisories(schedule):
            notes.append(f"가능하면 지킬 규칙을 못 지킴: {e['detail']}.")
    absent = [p.name for p in schedule.people if p.status == "연차"]
    half = [f"{p.name}({p.status})" for p in schedule.people if p.status in ("오전반차", "오후반차")]
    if absent:
        notes.append("연차: " + ", ".join(absent) + ".")
    if half:
        notes.append("반차: " + ", ".join(half) + ".")
    for pid, row in schedule.grid.items():
        works = [label in POSTS if label else None for label in row]
        for t in range(8):
            if works[t] and works[t + 1] and works[t + 2] and not schedule.strict:
                notes.append(f"{people[pid].name}: {HOURS[t]}부터 3시간 연속 포스트 (인원상 불가피).")
                break
    full = [p.pid for p in schedule.people if p.status == "출근" and p.leave_from is None]
    counts = {pid: sum(label in POSTS for label in schedule.grid[pid]) for pid in full}
    if counts and max(counts.values()) - min(counts.values()) > 1:
        notes.append(f"전일근무자 포스트 횟수 차이 {max(counts.values()) - min(counts.values())}회 (목표 1회 이내).")
    c_counts = {pid: sum(label in C_POSTS for label in schedule.grid[pid]) for pid in full}
    if c_counts and min(c_counts.values()) == 0 and max(c_counts.values()) == 2:
        notes.append("C계열 0회인 사람이 있는데 2회 받은 사람이 있습니다.")
    missing = [HOURS[t] for t in range(10)
               if t not in EDU_SLOTS and STANDBY not in [row[t] for row in schedule.grid.values()]]
    if missing:
        notes.append("대기자 없는 시간: " + ", ".join(missing) + " (비포스트 인원이 순찰·휴게에 모두 쓰임).")
    if schedule.fixed_template:
        notes.append(f"반차자 없는 {schedule.fixed_template}인: 통합 근무표 고정틀을 그대로 사용했습니다(§23).")
        for t, who in sorted(TEMPLATE_OUTSIDE_PATROL.get(schedule.fixed_template, {}).items()):
            if schedule.control_patrol == t:
                continue
            taker = next((people[pid] for pid, row in schedule.grid.items() if row[t] == PATROL), None)
            if taker:
                base = "통제E(편성 밖)" if who == "E" else "통제A(결근)"
                notes.append(f"고정틀의 {HOURS[t]} 순찰은 {base} 몫이라 {taker.number}번 {taker.name}이(가) 맡았습니다.")
    elif not schedule.strict:
        notes.append("인원상 모든 사람이 근근휴 사이클을 지킬 수 없어(포스트 5~7곳에 맞지 않음) "
                     "일부는 휴게가 이어지거나 근무가 3시간 이어질 수 있습니다(§3-2).")
    if schedule.control_patrol is not None:
        notes.append(f"순찰 인원이 모자라 통제A가 {HOURS[schedule.control_patrol]} 순찰 1회를 맡았습니다(§7)."
                     if schedule.control else
                     f"통제A 결근: {HOURS[schedule.control_patrol]} 순찰(통제A 자리)은 빈칸으로 둡니다.")
    twice = [people[pid].name for pid, row in schedule.grid.items() if row.count(PATROL) >= 2]
    if twice:
        notes.append("순찰 2회: " + ", ".join(twice) + " (통제A 1회를 쓰고도 순찰이 남아 선임 우선으로 배정, "
                     "통제A는 17시 순찰 불가).")
    no_standby = [people[pid].name for pid in full if STANDBY not in schedule.grid[pid]]
    if no_standby:
        notes.append("대기 표기 0회: " + ", ".join(no_standby) + " (대기는 휴게와 같음, 교육·순찰자는 뒤 순위).")
    if not schedule.control:
        notes.append("통제A 결근: 통제A 자리만 비우고 일반근무자 편성은 그대로입니다.")
    c_hours = sum(1 for t in range(10) if "C1" in [row[t] for row in schedule.grid.values()])
    c2_hours = sum(1 for t in range(10) if "C2" in [row[t] for row in schedule.grid.values()])
    notes.append(f"C1 {c_hours}시간, C2 {c2_hours}시간 운영 (인원에 맞춰 자동 결정).")
    return notes


# ---------------------------------------------------------------- storage
def to_json(schedule: DaySchedule) -> dict:
    return {"version": 1, "kind": "day", "date": schedule.day.isoformat(),
            "people": [{"pid": p.pid, "name": p.name, "status": p.status, "number": p.number,
                        "leave_from": p.leave_from} for p in schedule.people],
            "grid": schedule.grid, "shuttle": {str(t): pid for t, pid in schedule.shuttle.items()},
            "control": schedule.control, "control_patrol": schedule.control_patrol, "strict": schedule.strict,
            "fixed_template": schedule.fixed_template, "locked_through": schedule.locked_through,
            "emergency": schedule.emergency,
            "fill": {str(t): posts for t, posts in schedule.fill.items()}}


def from_json(data: dict) -> DaySchedule:
    people = tuple(DayPerson(p["pid"], p["name"], p["status"], p.get("number"), p.get("leave_from"))
                   for p in data["people"])
    return DaySchedule(date.fromisoformat(data["date"]), people, {k: list(v) for k, v in data["grid"].items()},
                       {int(t): pid for t, pid in data.get("shuttle", {}).items()}, "saved",
                       data.get("control", True), data.get("control_patrol"), data.get("strict", True),
                       data.get("fixed_template"), data.get("locked_through"), data.get("emergency"),
                       {int(t): dict(posts) for t, posts in (data.get("fill") or {}).items()})


def save_day(store: Path, schedule: DaySchedule, note: str = "") -> Path:
    store = Path(store)
    store.mkdir(parents=True, exist_ok=True)
    payload = {**to_json(schedule), "confirmed_at": datetime.now().isoformat(timespec="seconds"), "note": note}
    path = store / f"{schedule.day.isoformat()}.json"
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=1), encoding="utf-8")
    return path


def load_day(store: Path, day: date) -> dict:
    data = json.loads((Path(store) / f"{day.isoformat()}.json").read_text(encoding="utf-8"))
    data["schedule"] = from_json(data)
    return data


def load_roster(path: Path) -> list[str]:
    try:
        names = json.loads(Path(path).read_text(encoding="utf-8"))
        return [str(n) for n in names if str(n).strip()]
    except (OSError, ValueError):
        return list(DEFAULT_ROSTER)


def save_roster(path: Path, names: list[str]) -> None:
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    Path(path).write_text(json.dumps(names, ensure_ascii=False), encoding="utf-8")
