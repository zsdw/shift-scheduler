"""Data contracts from rulebook v2 chapters 2–4, 15, 18–21.

These types do not generate assignments or enforce operational hard rules.
Unresolved operating policies must be settled before the rule engine is built.
"""

from dataclasses import dataclass
from datetime import date, datetime, time, timedelta
from enum import Enum


class Mode(str, Enum):
    FLEXIBLE = "flexible"
    FM = "FM"


class NightType(str, Enum):
    N1 = "N1"
    N2 = "N2"
    N3 = "N3"
    N4 = "N4"


class RecordKind(str, Enum):
    PLAN = "plan"
    ACTUAL = "actual"


class Posture(str, Enum):
    STANDING = "standing"
    SEATED = "seated"
    REST_LIKE = "rest-like"


class AssignmentKind(str, Enum):
    POST = "post"
    PATROL = "patrol"
    SECURITY_STANDBY = "security_standby"
    REST = "rest"
    BARRIER_ONLY = "barrier_only"
    UNAVAILABLE = "unavailable"


@dataclass(frozen=True)
class Employee:
    """Stable identity, independent of a night's displayed 1–6 number (§2)."""

    employee_id: str
    name: str

    def __post_init__(self):
        if not self.employee_id.strip():
            raise ValueError("employee_id must not be blank")


@dataclass(frozen=True)
class Attendance:
    employee_id: str
    present: bool
    is_general_worker: bool
    display_number: int | None
    acts_as_manager: bool
    available_slot_indices: tuple[int, ...] | None = None

    def __post_init__(self):
        if self.display_number is not None and self.display_number not in range(1, 7):
            raise ValueError("Display number must be 1–6 (§2-1)")
        if self.available_slot_indices is not None:
            slots = tuple(self.available_slot_indices)
            if len(slots) != len(set(slots)) or any(index not in range(14) for index in slots):
                raise ValueError("Availability slots must be unique indices 0–13 (§21-7)")
            if not self.present and slots:
                raise ValueError("Absent employees cannot have available slots")

    def is_available(self, slot_index: int) -> bool:
        if not self.present:
            return False
        return self.available_slot_indices is None or slot_index in self.available_slot_indices


@dataclass(frozen=True)
class Slot:
    """Chronological index: 0=18:00, 6=00:00 next day, 13=07:00 (§3)."""

    index: int

    def __post_init__(self):
        if self.index not in range(14):
            raise ValueError("Slot index must be 0–13 (§3)")

    @property
    def hour(self) -> int:
        return (18 + self.index) % 24

    def starts_at(self, shift_start_date: date) -> datetime:
        return datetime.combine(shift_start_date, time(18)) + timedelta(hours=self.index)


SLOTS = tuple(Slot(i) for i in range(14))


@dataclass(frozen=True)
class Assignment:
    """Preserve exact post labels (G2 vs G2(1)) and patrol area (§25)."""

    kind: AssignmentKind
    label: str

    def __post_init__(self):
        if not self.label.strip():
            raise ValueError("An assignment cannot have an empty label (§3)")


@dataclass(frozen=True)
class AssignmentRecord:
    """One person/slot; every accounting flag is explicit, not inferred (§4).

    Actual fields in a PLAN record describe planned operating assumptions;
    they are not confirmed actual history. Posture may be unresolved (None),
    e.g. patrol posture pending interpretation, rather than an invented default.
    """

    employee_id: str
    slot: Slot
    displayed_assignment: Assignment
    actual_post_or_work_type: Assignment
    fatigue_value: float
    actual_work_time_value: float
    actual_rest_time_value: float
    posture_or_mode: Posture | None
    counts_for_same_post_consecutive: bool
    counts_for_continuous_work_restriction: bool
    counts_as_meal_opportunity: bool
    counts_as_post_patrol_rest: bool
    barrier_install_flag: bool
    barrier_remove_flag: bool
    mode: Mode
    rule_refs: tuple[str, ...]


@dataclass(frozen=True)
class ShiftContext:
    """Mode is required; no implicit mode mixing (§0-2).

    The requested/effective distinction records a later engine's FM4 switch.
    This data model does not perform the switch itself.
    """

    shift_start_date: date
    night_type: NightType
    requested_mode: Mode
    effective_mode: Mode
    employees: tuple[Employee, ...]
    attendance: tuple[Attendance, ...]
    mode_change_reason: str | None = None
    day_instructions: tuple[str, ...] = ()
    # v2.18 §0-4-1: planned partial vacancy (some slot has only four available
    # general workers) uses the four-worker vacancy profile for the whole shift.
    partial_vacancy_profile: bool = False
    # v2.20 §0-4-2: emergency re-optimization switched the unlocked remainder
    # (slots >= this index) to flexible mode + vacancy-2 rules.
    flexible_from_slot: int | None = None
    # Emergency: manager A left mid-shift and 준호 took over as manager from
    # (slot, proxy_id). The engine solves a "seat form" (see service.seat_form).
    manager_handover: tuple[int, str] | None = None
    # 유도리 포스트별 운영 (사용자 지정, 2026-10-02 사용자 확정): ((post, from_slot, to_slot, "rest"|"seated"), ...)
    # None = 룰북 기본 유도리(10-1: I1 00~03시 휴게성). 값이 있으면 기본값을 대신한다. 유도리 슬롯에만 적용.
    post_operations: tuple[tuple[str, int, int, str], ...] | None = None
    # 5-7 추가 남문 (2026-10-05 사용자 확정): 원래 남문을 안 여는 시간에 G2 1명을 더 여는 슬롯들.
    # 주말 시작(N3/N4) 18·19·20시, 다음날 주말(N2/N4) 06·07시만. 생성 전 사용자 확인값.
    extra_south_slots: tuple[int, ...] = ()

    def __post_init__(self):
        bad = set(self.extra_south_slots) - set(extra_south_choices(self.night_type))
        if bad or len(set(self.extra_south_slots)) != len(self.extra_south_slots):
            raise ValueError(f"추가 남문은 원래 남문을 안 여는 시간만 고를 수 있습니다: {sorted(bad)}")
        if self.post_operations is not None:
            problems = post_operation_problems(self.post_operations)
            if problems:
                raise ValueError("; ".join(problems))
        ids = [p.employee_id for p in self.employees]
        if len(ids) != len(set(ids)):
            raise ValueError("Employee identities must be unique")
        attendance_ids = [a.employee_id for a in self.attendance]
        if len(attendance_ids) != len(set(attendance_ids)):
            raise ValueError("Duplicate attendance record")
        if not set(attendance_ids).issubset(ids):
            raise ValueError("Attendance references an unknown employee")
        numbers = [a.display_number for a in self.attendance if a.display_number is not None]
        if len(numbers) != len(set(numbers)):
            raise ValueError("Display numbers must be unique within a shift")


@dataclass(frozen=True)
class ShiftRecord:
    """Plan/actual separation and revision linkage (§20); no implicit approval."""

    record_id: str
    kind: RecordKind
    context: ShiftContext
    assignments: tuple[AssignmentRecord, ...]
    source_plan_id: str | None = None
    confirmed_at: datetime | None = None


@dataclass(frozen=True)
class BarrierHistoryEntry:
    """§15-6: identities, not display numbers; date is the 18:00 start date."""

    shift_start_date: date
    install_employee_ids: tuple[str, ...]
    remove_employee_ids: tuple[str, ...]
    mode: Mode
    kind: RecordKind
    source_record_id: str


@dataclass(frozen=True)
class HistoryInput:
    """None=unknown history; empty tuple=explicitly no available history.

    Cycle grouping/aggregation is deferred to stage 7, not inferred from dates.
    """

    actual_nights: tuple[ShiftRecord, ...] | None
    barrier_entries: tuple[BarrierHistoryEntry, ...] | None

    def __post_init__(self):
        if self.actual_nights is not None and any(
            r.kind is not RecordKind.ACTUAL for r in self.actual_nights
        ):
            raise ValueError("Planned shifts are not actual night history (§20)")


def mode_at(context: "ShiftContext", slot_index: int) -> Mode:
    """Operating mode of one slot (v2.20 §0-4-2 allows a mid-shift switch)."""
    if context.flexible_from_slot is not None and slot_index >= context.flexible_from_slot:
        return Mode.FLEXIBLE
    return context.effective_mode


# ---- 유도리 포스트별 운영 (사용자 지정)
SOUTH_POSTS = ("G2", "G3", "G2(1)")
# 사용자 확정: 남문은 좌식 불가, G1·L3는 휴게성 불가. I1은 휴게성(10-1 그대로) 또는 좌식(휴게성 없이 정위치).
POST_OPERATION_CHOICES = {"I1": ("rest", "seated"), "G1": ("seated",), "L3": ("seated",),
                          **{post: ("rest",) for post in SOUTH_POSTS}}
DEFAULT_POST_OPERATIONS = (("I1", 6, 9, "rest"),)          # 룰북 10-1: 00·01·02·03시 I1 휴게성
GENERATION_POST_OPERATIONS = (("I1", 4, 9, "rest"),)       # 새 생성 기본: 22~03시, 과거 None 저장본은 종전 기준 유지


def default_rest_start(post_operations) -> int | None:
    """기본 유도리면 I1 휴게성 시작 칸(None 저장본 6=00시, 새 기본 4=22시), 사용자 지정이면 None.
    기본값을 명시 저장한 새 표도 '사용자 지정'으로 보지 않게 한다 (2026-10-13)."""
    if post_operations is None:
        return 6
    normalized = tuple(tuple(item) for item in post_operations)
    return {DEFAULT_POST_OPERATIONS: 6, GENERATION_POST_OPERATIONS: 4}.get(normalized)
# 차단봉 칸은 룰북대로 둔다: 20시 설치(I1·남문 G2), 04시 I1 철수(10-3·10-5).
BARRIER_CELLS = frozenset({("I1", 2), ("G2", 2), ("I1", 10)})


# 15-0 차단봉 고정 담당 (2026-10-05 사용자 확정, 이 날짜 야간부터): FM·유도리 공통
# 20시 설치 = G2 운영 시 G2 + 보안실 대기 1명, G2 없으면 I1 + 보안실 대기 1명 / 04시 철수 = I1 근무자.
# 피로도: 포스트 겸임은 원래 포스트 회계 그대로, 대기 설치자만 1점(실근무 0). 이전 날짜 기록은 옛 규칙 그대로.
BARRIER_V2_FROM = date(2026, 10, 5)
BARRIER_SINGLE_FROM = date(2026, 10, 9)

def barrier_single(context) -> bool:
    return context.shift_start_date >= BARRIER_SINGLE_FROM

BARRIER_HISTORY_FROM = date(2026, 10, 4)


def barrier_history_counts(context) -> bool:
    """차단봉 담당 집계는 2026-10-04 야간부터 시작한다."""
    return context.shift_start_date >= BARRIER_HISTORY_FROM


def barrier_v2(context) -> bool:
    return context.shift_start_date >= BARRIER_V2_FROM


def extra_south_choices(night_type) -> tuple[int, ...]:
    """5-7: 추가 남문(G2)을 고를 수 있는 슬롯 = 원래 남문을 안 여는 시간 (0=18시, 12=06시, 13=07시)."""
    value = getattr(night_type, "value", night_type)
    evening = (0, 1, 2) if value in ("N3", "N4") else ()
    morning = (12, 13) if value in ("N2", "N4") else ()
    return evening + morning


def post_operation_problems(operations) -> list[str]:
    problems = []
    for item in operations:
        post, lo, hi, state = item
        if post not in POST_OPERATION_CHOICES:
            problems.append(f"{post}: 유도리 운영을 정할 수 없는 포스트")
        elif state not in POST_OPERATION_CHOICES[post]:
            problems.append(f"{post}: '{state}' 운영은 고를 수 없음")
        if not (0 <= int(lo) <= int(hi) <= 13):
            problems.append(f"{post}: 시간 범위가 잘못됨 ({lo}~{hi})")
    return problems


def post_operation(context: "ShiftContext", label: str, slot_index: int) -> str | None:
    """유도리 슬롯에서 이 포스트 칸의 운영 ('rest' 휴게성 / 'seated' 좌식 / None 기본). 뒤에 적은 항목이 우선."""
    if mode_at(context, slot_index) != Mode.FLEXIBLE or (label, slot_index) in BARRIER_CELLS:
        return None
    operations = DEFAULT_POST_OPERATIONS if context.post_operations is None else context.post_operations
    state = None
    for post, lo, hi, value in operations:
        if post == label and lo <= slot_index <= hi:
            state = value
    return state
