"""근무자 선호 (룰북 17-1, 2026-10-02 사용자 확정). 모두 소프트 — 하드룰을 바꾸지 않는다.

1) 공통 선호 보너스: 근무자들이 공통으로 좋아하는 것
   - 00~05시 안에 2시간 이상 연속 실휴게
   - 07시 휴게는 16장의 최근 수혜일 순서로 별도 결정(피로도 가중 제외)
   모두에게 기본 가중치를 주고, 최근 3싸이클(6근무) 실제 기록에서 밤당 피로도가 팀 평균보다 높았던
   (상대적으로 손해 본) 사람일수록 가중치를 더 준다. 하드룰·당일 밸런스·이력 밸런스를 다 맞춘 뒤 적용.
2) 개인 회피 (강한 소프트): 당일 밸런스 목표 다음, 이력 밸런스·선호 보너스보다 먼저 피한다.
"""
from __future__ import annotations

from .models import NightType

# 00~05시 = 슬롯 6~11, 07시 = 슬롯 13
NIGHT_REST_SLOTS = range(6, 12)
LAST_SLOT = 13
BASE_WEIGHT = 2          # 모두에게 주는 기본 가중치
MAX_EXTRA = 6            # 손해 본 사람 추가 가중치 상한 (밤당 피로도 0.5점 초과마다 +1)

# (이름, 표시 포스트, 슬롯, 적용 야간 유형) — 다음날이 평일인 야간 = N1(평일→평일)·N3(공휴일→평일)
PERSONAL_AVOID = (
    ("만년", "I1", 12, (NightType.N1, NightType.N3)),    # 06시 I1 매우 싫어함 (2026-10-02)
)


def preference_weights(records, general_ids) -> dict[str, int] | None:
    """최근 실제 기록에서 사람별 선호 가중치. 기록이 없으면 모두 기본 가중치."""
    if not general_ids:
        return None
    totals = {p: 0 for p in general_ids}
    nights = {p: 0 for p in general_ids}
    for record in records or ():
        present = {a.employee_id for a in record.context.attendance if a.present}
        for p in general_ids:
            if p in present:
                nights[p] += 1
                totals[p] += sum(r.fatigue_value for r in record.assignments if r.employee_id == p)
    rates = {p: totals[p] / nights[p] for p in general_ids if nights[p]}
    if len(rates) < 2:
        return {p: BASE_WEIGHT for p in general_ids}
    team = sum(rates.values()) / len(rates)
    return {p: BASE_WEIGHT + max(0, min(MAX_EXTRA, round((rates.get(p, team) - team) * 2)))
            for p in general_ids}


def avoid_cells(context) -> tuple[tuple[str, int, str], ...]:
    """이번 근무에 해당하는 개인 회피 칸: ((employee_id, slot, label), ...)."""
    names = {e.employee_id: e.name for e in context.employees}
    present = {a.employee_id for a in context.attendance if a.present}
    out = []
    for name, label, slot, nights in PERSONAL_AVOID:
        if context.night_type not in nights:
            continue
        for employee_id, employee_name in names.items():
            if employee_name == name and employee_id in present:
                out.append((employee_id, slot, label))
    # 사용자 확정 2026-10-03: 실제 통제 A만, 관리자대행에게 전이하지 않는다.
    if "A" in names and "A" in present:
        out.append(("A", 10, "보안실 대기"))  # 04시, 모든 야간 유형·모드의 강한 소프트
    return tuple(out)
