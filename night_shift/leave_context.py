"""통제A 반차·준호 승계·긴급 반차/이탈 — '누가 언제 빠지고 누가 이어받는지'를 한곳에서 판정 (2026-10-18).

Solver·Validator·서비스가 이 판정을 같이 쓴다. 여기서는 입력 해석(분류)만 하고, 규칙(제약)은 Solver와
Validator가 각자 따로 구현한다 — '같은 제약 함수를 양쪽에서 쓰지 않는다'(AGENTS.md §2)와 충돌하지 않는다.
종전에는 세 곳이 따로 계산해서 판단이 어긋나는 버그가 여러 번 났다(휴게 2시간 요구 대상, 남은 칸 0인 이탈자 분류 등).

자리 형태(엔진 형태) 기준: 관리자 자리(A)가 밤새 이어지고, 준호(6) 줄은 자기 일반근무 시간만 가용이다.
"""
from __future__ import annotations

from dataclasses import dataclass

HANDOVER_PROXY = "6"     # 관리자 대행 준호 (service.HANDOVER_PROXY_ID와 같음)


@dataclass(frozen=True)
class LeaveContext:
    proxy_handover: bool               # 준호가 관리자를 이어받는 날 (미리 정한 반차 + 긴급 이탈 승계)
    planned: bool                      # 미리 정한 통제A 반차 (긴급 재편성 아님)
    early_half: bool                   # 미리 정한 전반부 반차 (18~00시 준호 대행)
    late_half: bool                    # 미리 정한 후반부 반차 (01시부터 준호 대행)
    proxy_own_slots: tuple[int, ...]   # 준호 자기 줄(일반근무) 시간
    half_day_ids: frozenset[str]       # H-09-1 반차자 처리 대상 (미리 정한 반차자 + 남은 칸 있는 긴급 이탈자)
    leaver_ids: frozenset[str]         # 남은 칸이 있는 긴급 반차·이탈 일반근무자
    emergency_out_ids: frozenset[str]  # 12-6 대기 횟수 비교에서 빼는 긴급 반차·이탈자 (남은 칸 없음 포함)
    manager_leaver_slots: frozenset[int]   # 통제A 긴급 반차·이탈의 빠지기 전 남은 칸

    @property
    def manager_leaves(self) -> bool:
        return bool(self.manager_leaver_slots)


def build_leave_context(*, manager_id, general_ids, partial_general_ids, half_day_ids, emergency: bool,
                        emergency_leaver_cells=(), manager_a_start_slot: int = 0, manager_a_end_slot: int = 14,
                        rules_v220: bool = True) -> LeaveContext:
    """emergency = 긴급 재편성(LOCK 있음). half_day_ids = 서비스가 넘긴 반차자(None이면 계획 생성의 부분 출근자 전원)."""
    partial = set(partial_general_ids)
    proxy_handover = bool(rules_v220 and manager_id == "A" and HANDOVER_PROXY in partial
                          and (manager_a_start_slot > 0 or manager_a_end_slot < 14))
    planned = proxy_handover and not emergency
    leaver_ids = frozenset(p for p, _ in emergency_leaver_cells if p in set(general_ids))
    if rules_v220:
        base = partial if half_day_ids is None and not emergency else set(half_day_ids or ()) & partial
        half_day = frozenset(base | (leaver_ids & partial))
    else:
        half_day = frozenset()
    emergency_out = (frozenset(leaver_ids | (partial - half_day - ({HANDOVER_PROXY} if proxy_handover else set())))
                     if emergency else frozenset())
    own = (tuple(range(manager_a_start_slot, 14)) if manager_a_start_slot else tuple(range(manager_a_end_slot))
           ) if proxy_handover else ()
    return LeaveContext(
        proxy_handover=proxy_handover, planned=planned,
        early_half=planned and manager_a_start_slot > 0,
        late_half=planned and manager_a_start_slot == 0 and manager_a_end_slot < 14,
        proxy_own_slots=own, half_day_ids=half_day, leaver_ids=leaver_ids, emergency_out_ids=emergency_out,
        manager_leaver_slots=frozenset(t for p, t in emergency_leaver_cells if p == manager_id))


def reoptimization_half_day_ids(attendance, exclude=()) -> tuple[str, ...]:
    """긴급 재편성·재검증에 넘길 반차자 목록: 부분 출근 일반근무자 중 exclude(관리자 대행 준호, 남은 칸 없이
    바로 빠진 이탈자)를 뺀 사람. attendance는 이탈을 반영한 뒤의 출근 정보."""
    skip = set(exclude)
    return tuple(a.employee_id for a in attendance if a.present and a.is_general_worker
                 and a.employee_id not in skip and not all(a.is_available(t) for t in range(14)))
