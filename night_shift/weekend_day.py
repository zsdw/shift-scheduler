"""주말·공휴일 주간 기본 편성. 야간/평일 엔진 및 확정 이력과 분리.

긴급 반차·이탈(2026-10-05 사용자 확정): LOCK한 시간까지 기존 배정 그대로, 빠지는 사람은 그 시간부터 근무불가(×).
오후반차 13시 퇴근. 남은 일반근무자가 4명이 되는 시간부터 결원 2명 규칙(G2 미운영·연속 실근무 최대 3).
밸런스(n빵)는 끝까지 근무하는 일반근무자끼리. 빠진 사람 순찰은 순찰 안 한 일반근무자 우선, 없으면 통제A.
Solver(generate)와 Validator(validate)는 같은 규칙을 각자 따로 계산한다.
"""
from __future__ import annotations
from dataclasses import dataclass, asdict, field, replace
from pathlib import Path
import json
from ortools.sat.python import cp_model

LABELS = ('G1', 'G2', 'I1', 'L1', '순찰', '휴게')
OFF = '×'                                   # 긴급 반차·이탈 뒤 근무불가 (근무 0·휴게 0으로 센다)
# 보안실 대기 (2026-10-18 사용자 확정): 실휴게·피로도 0 (휴게와 같은 회계), 매시간 정확히 1명.
# standby=True로 만든 표에만 대기 규칙을 적용한다 (그 전 저장본·업로드 표는 대기 없이 휴게로 기록).
STANDBY = '대기'
A_G1_WINDOW = range(3, 8)                   # 통제A G1 최소 1번은 11~15시 안 (2026-10-18 사용자 확정)
PATROL = {1: ('상층', 2), 2: ('중층', 2), 3: ('하층', 1),
          6: ('상층', 2), 7: ('중층', 2), 8: ('하층', 1)}
FIRST_PATROL = min(PATROL)                  # 첫 순찰 칸(09시) — 통제A 고정 (2026-10-12)
EARLY_LOCK = 2                              # 긴급 재편성 LOCK이 10시(2번째 칸)까지면 격차 1, 그 뒤는 2 허용


def emergency_gap(locked_through):
    """긴급 재편성 일반근무자 실근무·피로도 허용 격차 (2026-10-12 사용자 확정)."""
    return 1 if locked_through is None or locked_through <= EARLY_LOCK else 2
HALF_DAY_LEAVE = 5                          # 오후반차: 13시(5번째 칸)부터 근무불가
KINDS = {'half': '오후반차', 'leave': '긴급 이탈'}


@dataclass
class WeekendSchedule:
    day: str
    names: dict[str, str]
    grid: dict[str, list[str]]
    mode: str = 'FM'
    g2_cap: int = 2
    balance: bool = True
    standing_limit: bool = True
    manager_priority: bool = True      # 2026-10-05 사용자 확정: 통제A 실근무 ≤ 일반근무자 (야간과 동일)
    locked_through: int | None = None  # 긴급 재편성: 이 칸까지 기존 배정 LOCK
    leavers: dict = field(default_factory=dict)   # {번호: {'from': 칸, 'kind': 'half'|'leave', 'lock': 칸}}
    half_days: dict = field(default_factory=dict) # 미리 정한 반차 {번호: '오전반차'|'오후반차'} (2026-10-05)
    rule_exempt_names: tuple = ()  # Confirmed newcomer names are exempt, actual paired cells retained.
    relaxed: bool = False              # 반차일 평소 하드룰 해가 없어 연속 실근무·격차 1을 가능하면 지킬 규칙으로 낮춤
    # 실제 근무 칸 주석 (2026-10-13, 야간 저장본과 같은 '피로도·사유 기록'): [{'pid','t','fatigue','reason'}]
    annotations: list = field(default_factory=list)
    patrol_events: tuple = ()
    standby: bool = False              # 보안실 대기 규칙으로 만든 표 (2026-10-18~)
    # 막타임(17시) 휴게 이력 — 야간 07시와 이어서 (2026-10-18): {번호: {'prev': 직전 출근에 받음, 'last': 마지막 받은 날 ordinal|-1}}
    last_rest: dict = field(default_factory=dict)
    # 통제A 미리 정한 반차 (2026-10-18 사용자 확정): '오전반차'(13시 출근)|'오후반차'(13시 퇴근)|None, proxy = 대행 준호 번호
    a_half: str | None = None
    proxy: str | None = None


# 2026-10-05 사용자 확정(평일과 같음): 오후반차 = 08~12시 근무 후 13시 퇴근, 오전반차 = 13시 출근(13~17시)
PLANNED_OFF = {'오후반차': range(5, 10), '오전반차': range(0, 5)}


def off_slots(schedule, pid):
    """근무불가 칸 (미리 정한 반차 + 긴급 반차·이탈, 통제A 반차 포함)."""
    out = set(PLANNED_OFF.get(schedule.half_days.get(pid), ()))
    if pid == 'A' and getattr(schedule, 'a_half', None):
        out |= set(PLANNED_OFF[schedule.a_half])
    if pid in schedule.leavers:
        out |= set(range(schedule.leavers[pid]['from'], 10))
    return out


def partial_people(schedule):
    """하루 전체를 근무하지 않는 일반근무자 (n빵·포스트 최소 1번 제외 대상)."""
    return set(schedule.leavers) | set(schedule.half_days)


def half_rest_hours(schedule, pid, mode):
    """반차자가 나온 시간 중 휴게 시간 (유도리는 G2 휴게성 포함). 목표 1시간."""
    off = off_slots(schedule, pid)
    return sum(v in ('휴게', STANDBY) or (mode == '유도리' and v == 'G2')
               for t, v in enumerate(schedule.grid[pid]) if t not in off)


def leave_text(schedule, pid):
    info = schedule.leavers.get(pid)
    if info:
        return f"{8 + info['from']}시~ {KINDS[info['kind']]}"
    a_half = getattr(schedule, 'a_half', None)
    if pid == 'A' and a_half:
        return a_half
    if a_half and pid == getattr(schedule, 'proxy', None):
        return f"통제A 대행 {'08~12시' if a_half == '오전반차' else '16·17시 휴게'}"
    return schedule.half_days.get(pid, '')


def stats(schedule, mode):
    out = []
    for pid, row in schedule.grid.items():
        standing = sum(v in ('G1', 'L1') or (v == 'G2' and mode == 'FM') for v in row)
        seated = row.count('I1')
        patrol = sum(PATROL.get(t, ('', 0))[1] for t, v in enumerate(row) if v == '순찰')
        work = standing + seated + row.count('순찰')
        rest = 10 - work - row.count(OFF)
        name = f'{pid} · {schedule.names[pid]}' + (f' ({leave_text(schedule, pid)})' if leave_text(schedule, pid) else '')
        extra = sum(int(a.get('fatigue', 0)) for a in getattr(schedule, 'annotations', ()) if a.get('pid') == pid)
        out.append({'직원': name, '실근무': work, '실휴게': rest,
                    '피로도': standing*2+seated+patrol+extra, '입식': standing, '좌식': seated,
                    '순찰 피로도': patrol, '기타 피로도': extra})
    return out


HISTORY_COUNT = 4


def history_debt(store, day, count=HISTORY_COUNT):
    """최근 주말 주간 저장본 count회에서 사람(이름)별 '손해' 피로도 (2026-10-12 사용자 확정).

    각 기록에서 하루 전체 근무한 일반근무자의 피로도 - 그날 일반근무자 평균을 더한다(그날 모드 기준).
    양수 = 남보다 많이 함(손해) → 완벽 n빵이 안 되는 날 피로도를 덜 받는다. 평일·야간 기록은 섞지 않는다.
    반환 ({이름: 손해 점수}, [참조한 날짜])."""
    folder = Path(store)
    target = str(day)
    days = sorted((p.stem for p in folder.glob('????-??-??.json') if p.stem < target), reverse=True)[:count]
    debt = {}
    for iso in days:
        try:
            s = rule_schedule(load(folder, iso))
        except (OSError, ValueError, TypeError, KeyError):
            continue
        full = [p for p in s.grid if p != 'A' and p not in partial_people(s)]
        if len(full) < 2:
            continue
        values = {row['직원'].split(' · ')[0]: row['피로도'] for row in stats(s, 'FM' if s.mode == 'FM' else '유도리')}
        avg = sum(values[p] for p in full) / len(full)
        for p in full:
            debt[s.names[p]] = debt.get(s.names[p], 0) + values[p] - avg
    return debt, days


def rule_schedule(schedule):
    if not schedule.rule_exempt_names:return schedule
    excluded={p for p,n in schedule.names.items() if n in schedule.rule_exempt_names}
    return replace(schedule,names={p:n for p,n in schedule.names.items() if p not in excluded},
                   grid={p:r for p,r in schedule.grid.items() if p not in excluded},
                   half_days={p:s for p,s in schedule.half_days.items() if p not in excluded},rule_exempt_names=())


def validate(schedule, base=None):
    """독립 검증(꼭 지킬 규칙 위반). base(원래 표)를 주면 LOCK 칸이 그대로인지도 본다."""
    errors = _check(rule_schedule(schedule), rule_schedule(base) if base else None)[0]
    for pid,name in schedule.names.items():
        if pid=='A' or not any(v not in (None,OFF) for v in schedule.grid.get(pid,[])):continue
        prior=sorted((e for e in schedule.patrol_events if e['name']==name[-2:]),key=lambda e:(e['date'],e['shift']))
        if any(e['excluded'] for e in prior[-2:]) and '순찰' not in schedule.grid[pid]:
            errors.append(f'{name}: 순찰 제외 후 다음 출근 2회 순찰 필수')
    return errors


def advisories(schedule):
    """긴급 재편성에서 '가능하면 지킬 규칙'으로 낮춘 것(연속 실근무 상한·일반근무자 격차 1) 중 못 지킨 것."""
    return _check(rule_schedule(schedule), None)[1]


def repeats_of(schedule):
    """같은 포스트 2연속 (강한 비권장, 2026-10-05): ['3번 11~13시 G1', …]."""
    out = []
    for pid, row in schedule.grid.items():
        for t in range(9):
            if row[t] in LABELS[:4] and row[t] == row[t + 1]:
                out.append(f"{'통제A' if pid == 'A' else pid + '번'} {8+t}~{10+t}시 {row[t]}")
    return out


def _check(schedule, base):
    errors, soft = [], []
    # 2026-10-05 사용자 확정: 긴급(또는 해 없는 반차일)은 연속 실근무·격차 1을 가능하면 지킬 규칙으로
    emergency = bool(schedule.leavers) or schedule.relaxed
    soft_or_hard = soft if emergency else errors
    grid = schedule.grid
    if 'A' not in grid or not 5 <= len(grid) <= 7 or set(grid) != set(schedule.names):
        return ['통제A와 일반근무자 4~6명이 필요합니다.'], []
    if any(len(row) != 10 or any(v not in LABELS + (OFF, STANDBY) for v in row) for row in grid.values()):
        return ['근무표는 유효한 업무 10칸이어야 합니다.'], []
    offs = {}
    for pid, row in grid.items():                 # 근무불가 칸은 반차·이탈 시간에만 (따로 계산)
        off = set()
        if schedule.half_days.get(pid) == '오후반차':
            off |= set(range(5, 10))
        elif schedule.half_days.get(pid) == '오전반차':
            off |= set(range(5))
        elif pid in schedule.half_days:
            errors.append(f'{pid} 반차 종류 오류')
        info = schedule.leavers.get(pid)
        if info:
            off |= set(range(info['from'], 10))
        if pid == 'A' and (info or pid in schedule.half_days):
            errors.append('통제A 긴급 반차·이탈은 지원하지 않습니다')
        if pid == 'A' and schedule.a_half:            # 통제A 미리 정한 반차 (2026-10-18)
            off |= set(PLANNED_OFF.get(schedule.a_half, ()))
        if any((v == OFF) != (t in off) for t, v in enumerate(row)):
            errors.append(f'{pid} 근무불가 칸 오류')
        offs[pid] = off
    if base is not None and schedule.locked_through is not None:
        for pid, row in grid.items():
            if row[:schedule.locked_through + 1] != base.grid[pid][:schedule.locked_through + 1]:
                errors.append(f'{pid} LOCK 칸 변경')
    generals = [p for p in grid if p != 'A']
    full = [p for p in generals if p not in schedule.leavers and p not in schedule.half_days]
    # 그 시간 결원 수 (통제A가 반차로 빠진 시간은 1명 더, 10/18)
    absent_at = [6 - sum(t not in offs[p] for p in generals) + int(t in offs.get('A', ())) for t in range(10)]
    if max(absent_at) > 2:
        errors.append('일반근무자가 4명 미만인 시간이 있습니다 (지원 범위 밖)')
    for t in range(10):
        cells = [row[t] for row in grid.values()]
        for post in LABELS[:4]:
            required = 0 if post == 'G2' and absent_at[t] >= 2 else 1
            if cells.count(post) != required:
                errors.append(f'{8+t}시 {post} 인원 오류')
        if cells.count('순찰') != int(t in PATROL):
            errors.append(f'{8+t}시 순찰 인원 오류')
    # 통제A 반차 날 (2026-10-18 사용자 확정): 오후반차면 마지막 2시간 규칙을 대행 준호가, 오전반차면 08·09시를 대행 준호가
    a_half, proxy = schedule.a_half, schedule.proxy
    if a_half and proxy not in grid:
        errors.append('통제A 반차 대행자(준호) 없음')
        a_half = None
    last_two = proxy if a_half == '오후반차' else 'A'
    morning = proxy if a_half == '오전반차' else 'A'
    who = lambda p: '통제A' if p == 'A' else f'대행 {p}'
    if grid[last_two][9] != '휴게':                  # 2026-10-05 사용자 확정: 통제A 마지막 시간(17시) 휴게
        errors.append(f'{who(last_two)} 17시 휴게 아님')
    if schedule.locked_through is None and grid[morning][0] not in ('휴게', 'G2'):   # 2026-10-16 사용자 확정(하드)
        errors.append(f'{who(morning)} 08시 휴게·G2 아님')
    # 2026-10-16 사용자 확정: 통제A 16시 휴게는 강한 권장(검증 대상 아님, 종전 'G2만' 하드 폐지).
    # 결원 2명(G2 미운영) 시간의 G1 금지만 하드 (LOCK으로 지난 칸 보존)
    if not (schedule.locked_through is not None and schedule.locked_through >= 8):
        if absent_at[8] >= 2 and grid[last_two][8] == 'G1':
            errors.append(f'{who(last_two)} 16시 G1')
    g2_all_day = max(absent_at) < 2
    # 2026-10-12 사용자 확정: 첫 순찰(09시)은 통제A (LOCK으로 지난 칸 보존), 통제A도 운영 포스트 하루 최소 1번
    if not (schedule.locked_through is not None and schedule.locked_through >= FIRST_PATROL):
        if a_half == '오전반차':                       # 대행 준호는 09시 G1만 빼고 (첫 순찰 규칙 없음)
            if grid[proxy][FIRST_PATROL] == 'G1':
                errors.append(f'대행 {proxy} {8 + FIRST_PATROL}시 G1')
        elif grid['A'][FIRST_PATROL] != '순찰':
            errors.append(f'통제A {8 + FIRST_PATROL}시 첫 순찰 아님')
    a_missing = [v for v in LABELS[:4] if v not in grid['A'] and (v != 'G2' or g2_all_day)]
    if a_missing and not a_half:                      # 반차 날은 반나절이라 포스트 1번씩 적용 안 함
        soft_or_hard.append(f'통제A 포스트 미배정: {",".join(a_missing)}')
    # 2026-10-18 사용자 확정(하드): 통제A G1 최소 1번은 11~15시 안 (반차 날은 출근한 시간만, 그 밖 G1은 권장)
    a_window = [t for t in A_G1_WINDOW if grid['A'][t] != OFF]
    if a_window and 'G1' not in [grid['A'][t] for t in a_window] and not (
            schedule.locked_through is not None and schedule.locked_through >= max(a_window)):
        soft_or_hard.append('통제A 11~15시 G1 없음')
    if schedule.standby:
        # 2026-10-18 사용자 확정: 대기 매시간 정확히 1명 · 순찰 직후 1시간은 휴게 표기 · 일반근무자 대기 횟수 차이 ≤1
        # (LOCK으로 지난 칸 보존: 대기 없이 만든 원래 표를 긴급 재편성한 경우 LOCK 시간은 세지 않음)
        old = schedule.locked_through if base is not None and not base.standby else -1
        for t in range(old + 1, 10):
            if [row[t] for row in grid.values()].count(STANDBY) != 1:
                errors.append(f'{8+t}시 대기 인원 오류')
        for pid, row in grid.items():
            if any(row[t] == '순찰' and row[t+1] == STANDBY for t in range(9)):
                errors.append(f'{pid} 순찰 직후 대기')
        counts = [row.count(STANDBY) for pid, row in grid.items() if pid != 'A']
        if counts and max(counts) - min(counts) > 1:
            errors.append(f'일반근무자 대기 횟수 차이 초과 ({max(counts) - min(counts)})')
    # 2026-10-18 사용자 확정: 직전 출근(야간 07시·빨간날 주간 17시)에 막타임을 받은 사람은 17시 실휴게 금지 (LOCK 보존)
    if schedule.last_rest and not (schedule.locked_through is not None and schedule.locked_through >= 9):
        for pid, info in schedule.last_rest.items():
            row = grid.get(pid)
            if pid == last_two:                       # 오후반차 대행 준호 17시 휴게는 통제A 규칙(우선)
                continue
            if row and info.get('prev') and (row[9] in ('휴게', STANDBY) or (schedule.mode == '유도리' and row[9] == 'G2')):
                errors.append(f'{pid} 직전 출근에 이어 막타임 휴게')
    base_absent = 7 - len(grid)
    for pid, row in grid.items():
        if pid in full:                              # 일반근무자 운영 포스트 하루 최소 1번 (빠진 사람 제외)
            missing = [v for v in LABELS[:4] if v not in row and (v != 'G2' or g2_all_day)]
            if missing:
                errors.append(f'{pid} 포스트 미배정: {",".join(missing)}')
        if row.count('G2') > schedule.g2_cap:
            errors.append(f'{pid} G2 횟수 초과')
        if pid == 'A':
            need = max(1, base_absent)
            partial = schedule.leavers or schedule.half_days    # 반차·이탈일: 일반 우선, 모자라면 통제A 추가
            if (row.count('순찰') != need) if not partial else (row.count('순찰') < need):
                errors.append('A 순찰 횟수 오류')
        elif row.count('순찰') > 1:
            errors.append(f'{pid} 순찰 횟수 오류')
    for mode in ('FM', '유도리') if schedule.mode == 'FM' else ('유도리',):
        for pid, row in grid.items():
            run = stand = rest = pure = 0
            run_flagged = False
            for t, label in enumerate(row):
                resting = label in ('휴게', STANDBY) or (mode == '유도리' and label == 'G2')
                working = not resting and label != OFF
                rest = rest+1 if resting else 0
                pure = pure+1 if label in ('휴게', STANDBY) else 0
                # 2026-10-18 사용자 확정: 휴게·대기만 3연속 금지(유도리 G2 휴게성이 끼면 3연속 허용), 4연속 휴게는 금지
                if pure > 2:
                    errors.append(f'{mode} {pid} 3연속 휴게'); break
                if rest > 3:
                    errors.append(f'{mode} {pid} 4연속 휴게'); break
                run = run+1 if working else 0
                # 2026-10-18 사용자 확정: 4연속 실근무가 불가피하면 그 4칸에 G2·I1 각각 최소 1번
                if run == 4 and not ('G2' in row[t-3:t+1] and 'I1' in row[t-3:t+1]):
                    soft_or_hard.append(f'{mode} {pid} 4연속 실근무에 G2·I1 없음 ({8+t-3}~{8+t+1}시)')
                stand = stand+1 if label in ('G1', 'L1', '순찰') or (mode == 'FM' and label == 'G2') else 0
                # 연속 실근무: 결원 1명 시간만 4칸, 그 밖은 3칸 (긴급 전환 시간별)
                limit = 4 if all(absent_at[k] == 1 for k in range(t - run + 1, t + 1)) else 3
                if run > limit and not run_flagged:
                    soft_or_hard.append(f'{mode} {pid} 연속 실근무 초과 ({8+t-run+1}~{8+t+1}시 {run}시간, 상한 {limit})')
                    run_flagged = True
                    if not emergency: break
                if schedule.standing_limit and stand > 2:
                    errors.append(f'{mode} {pid} 3연속 입식'); break
        values = dict(zip(grid, stats(schedule, mode)))
        if schedule.balance and full:
            # 긴급 재편성은 LOCK 10시까지 1, 그 뒤 2까지 허용 (2026-10-12 사용자 확정)
            allowed = emergency_gap(schedule.locked_through) if schedule.leavers else 1
            for key in ('실근무', '피로도'):
                gap = max(values[p][key] for p in full)-min(values[p][key] for p in full)
                if gap > allowed:
                    soft_or_hard.append(f'{mode} 일반근무자 {key} 격차 초과 ({gap}, 허용 {allowed})')
        if schedule.manager_priority and any(values['A']['실근무'] > values[p]['실근무'] for p in full):
            errors.append(f'{mode} 통제A 실근무 우대 위반')
        # 2026-10-18 사용자 확정: 통제A 피로도 (표의 운영 기준만, 반차·긴급일 제외)
        # 결원 1·2명: 끝까지 근무하는 일반근무자 각각보다 최소 1점 적게(하드). 결원 0명: 가장 적은 사람보다 많지 않게(하드).
        main = 'FM' if schedule.mode == 'FM' else '유도리'
        if (mode == main and schedule.manager_priority and full and not emergency
                and not schedule.half_days and not schedule.a_half and schedule.standby):
            need = 1 if len(grid) < 7 else 0
            low = min(values[p]['피로도'] for p in full)
            if low - values['A']['피로도'] < need:
                errors.append(f'{mode} 통제A 피로도 {values["A"]["피로도"]}점 — 일반근무자 최저 {low}점보다 '
                              + ('1점 이상 적어야 함' if need else '많음'))
    return errors, soft


def generate(day, names, mode='FM', *, seconds=30, seed=0, exclude=None,
             g2_cap=2, balance=True, standing_limit=True, manager_priority=True,
             base=None, locked_through=None, leavers=None, half_days=None, relaxed=False, history=None, patrol_events=(),
             last_rest=None, a_half=None, proxy=None):
    """base·locked_through·leavers: 긴급 재편성 (LOCK 칸은 base 그대로, 빠진 사람은 그 칸부터 ×).
    half_days: 미리 정한 반차 {번호: '오전반차'|'오후반차'}. 평소 하드룰로 해가 없으면 relaxed로 한 번 더 푼다.
    history: {이름: 최근 손해 피로도} (history_debt). 완벽 n빵이 안 되면 n빵 차이·2연속 다음 순위로
    손해 본 사람에게 피로도를 덜 준다 (2026-10-12 사용자 확정)."""
    if 'A' not in names or not 5 <= len(names) <= 7:
        raise ValueError('통제A 출근·일반 결원 0~2명만 지원합니다.')
    leavers = dict(leavers or {})
    half_days = dict(half_days or {})
    if 'A' in half_days or any(v not in PLANNED_OFF for v in half_days.values()):
        raise ValueError('반차는 일반근무자의 오전반차·오후반차만 지원합니다.')
    if base is not None and a_half is None:            # 긴급 재편성: 원래 표의 통제A 반차·대행 그대로
        a_half, proxy = getattr(base, 'a_half', None), getattr(base, 'proxy', None)
    if a_half is not None:
        # 통제A 미리 정한 반차 (2026-10-18 사용자 확정): 대행 준호가 하루 전체 출근해야 함
        if a_half not in PLANNED_OFF:
            raise ValueError('통제A 반차는 오전반차·오후반차만 지원합니다.')
        if proxy not in names or proxy == 'A' or proxy in half_days or proxy in (leavers or {}):
            return None, 'UNSUPPORTED'
    if (half_days or a_half) and not leavers and relaxed is False:       # 먼저 평소 하드룰로
        result, label = generate(day, names, mode, seconds=seconds, seed=seed, exclude=exclude, g2_cap=g2_cap,
                                 balance=balance, standing_limit=standing_limit, manager_priority=manager_priority,
                                 base=base, locked_through=locked_through, half_days=half_days, relaxed='hard',
                                 history=history, patrol_events=patrol_events, last_rest=last_rest,
                                 a_half=a_half, proxy=proxy)
        # 2026-10-05 사용자 확정: 반차일 해 없으면 긴급처럼 낮춤. 통제A 반차일도 같은 반차일(10/18) — 빡빡해서
        # 시간 안에 못 찾는 경우(UNKNOWN)도 많아 해를 못 찾으면 낮춘다.
        if label != 'INFEASIBLE' and not (a_half and result is None and label != 'UNSUPPORTED'):
            return result, label
        relaxed = True
    m = cp_model.CpModel()
    ids = list(names)
    generals = [p for p in ids if p != 'A']
    full = [p for p in generals if p not in leavers and p not in half_days]
    base_absent = 7 - len(ids)
    offs = {p: set(PLANNED_OFF.get(half_days.get(p), ())) | (set(range(leavers[p]['from'], 10)) if p in leavers else set())
            for p in ids}
    if a_half:
        offs['A'] |= set(PLANNED_OFF[a_half])
    # 통제A 반차 날 '마지막 2시간 휴게'(16시 권장·17시 하드)를 서는 사람: 오후반차면 대행 준호, 아니면 통제A
    last_two = proxy if a_half == '오후반차' else 'A'
    morning = proxy if a_half == '오전반차' else 'A'    # 08시 휴게·G2 / 09시 규칙을 서는 사람
    # 그 시간 결원 수. 통제A가 반차로 빠진 시간은 인원이 1명 적어 결원 1명 더로 센다 → 평소 결원 규칙(G2 미운영·4연속 허용 등) 그대로 (10/18)
    absent = [6 - sum(t not in offs[p] for p in generals) + int(t in offs['A']) for t in range(10)]
    if max(absent) > 2:
        return None, 'UNSUPPORTED'
    labels = LABELS + (OFF, STANDBY)
    x = {(p,t,v): m.NewBoolVar(f'{p}_{t}_{v}') for p in ids for t in range(10) for v in labels}
    for p in ids:
        for t in range(10):
            m.AddExactlyOne(x[p,t,v] for v in labels)
            m.Add(x[p,t,OFF] == int(t in offs[p]))
        m.Add(sum(x[p,t,'G2'] for t in range(10)) <= g2_cap)
        if p in full:       # 2026-10-05 사용자 확정(하드): 일반근무자는 운영 포스트마다 하루 최소 1번
            for v in LABELS[:4]:
                if v != 'G2' or max(absent) < 2:
                    m.Add(sum(x[p,t,v] for t in range(10)) >= 1)
        count = sum(x[p,t,'순찰'] for t in range(10))
        if p == 'A':
            if leavers or half_days: m.Add(count >= max(1, base_absent))  # 빠진 사람 순찰: 일반 우선, 없으면 통제A
            else: m.Add(count == max(1, base_absent))
        else: m.Add(count <= 1)
    exclusion_terms=[]
    exclusion_bound=0
    for p in generals:
        events=[e for e in patrol_events if e['name']==names[p][-2:]]
        patrol_count=sum(x[p,t,'순찰'] for t in range(10))
        if any(e['excluded'] for e in events[-2:]):m.Add(patrol_count>=1)
        previous=sum(e['excluded'] for e in events)
        exclusion_bound+=previous
        exclusion_terms.append(previous*(1-patrol_count))
    rotation_cost=sum(exclusion_terms)
    rotation_scale=exclusion_bound+1
    m.Add(x[last_two, 9, '휴게'] == 1)               # 통제A(오후반차면 대행 준호) 마지막 시간 휴게 (하드)
    # 2026-10-16 사용자 확정: 통제A 16시는 휴게가 강한 권장(하드 아님), 휴게가 안 되면 G2 우선.
    # (종전 10/13 '16시 G2만' 하드 폐지) 결원 2명(G2 미운영) 시간은 G1 금지 하드 유지. 오후반차면 대행 준호가 계승.
    a16 = 0
    if locked_through is None or locked_through < 8:
        if absent[8] >= 2:
            m.Add(x[last_two, 8, 'G1'] == 0)
            a16 = 1 - x[last_two, 8, '휴게']
        else:
            a16 = 2 - 2 * x[last_two, 8, '휴게'] - x[last_two, 8, 'G2']     # 휴게 0 · G2 1 · 그 밖 2
    if locked_through is None:                        # 2026-10-16 사용자 확정(하드): 통제A(오전반차면 대행) 08시는 휴게·G2만
        m.Add(x[morning, 0, '휴게'] + x[morning, 0, 'G2'] == 1)
    if locked_through is None or locked_through < FIRST_PATROL:   # 2026-10-12 사용자 확정: 첫 순찰(09시)은 통제A
        if a_half == '오전반차':                       # 2026-10-18: 통제A 오전반차면 대행 준호는 09시 G1만 빼고 (첫 순찰 규칙 없음)
            m.Add(x[proxy, FIRST_PATROL, 'G1'] == 0)
        else:
            m.Add(x['A', FIRST_PATROL, '순찰'] == 1)
    if base is not None and locked_through is not None:
        for p in ids:
            for t in range(locked_through + 1):
                m.Add(x[p,t,base.grid[p][t]] == 1)
    for t in range(10):
        for v in LABELS[:5]:
            count = int(t in PATROL) if v == '순찰' else int(not (v == 'G2' and absent[t] >= 2))
            m.Add(sum(x[p,t,v] for p in ids) == count)
    # 보안실 대기 (2026-10-18 사용자 확정): 매시간 정확히 1명, 순찰 직후 1시간은 휴게 표기,
    # 일반근무자끼리 대기 횟수 차이 ≤1, 통제A 대기는 비권장(아래 목적식 — 일반근무자 밸런스가 깨질 때만).
    # 대기 없이 만든 원래 표를 긴급 재편성하면 LOCK 시간은 원래 그대로(대기 0명).
    old_lock = locked_through if base is not None and locked_through is not None and not base.standby else -1
    for t in range(old_lock + 1, 10):
        m.Add(sum(x[p,t,STANDBY] for p in ids) == 1)
    for p in ids:
        for t in range(9):
            m.Add(x[p,t,'순찰'] + x[p,t+1,STANDBY] <= 1)
    sb_count = {p: sum(x[p,t,STANDBY] for t in range(10)) for p in generals}
    for a in generals:
        for b in generals:
            if a != b:
                m.Add(sb_count[a] - sb_count[b] <= 1)
    a_standby = sum(x['A',t,STANDBY] for t in range(10))
    # 막타임 휴게 (2026-10-18 사용자 확정, 야간 16장과 같은 기준을 야간 07시 이력과 이어서): 직전 실제 출근(야간·빨간날 주간)에
    # 막타임을 받은 일반근무자는 17시 실휴게(휴게·대기, 유도리 표는 G2 휴게성 포함) 금지(하드), 나머지는 마지막 수혜가
    # 오래된 사람부터(아래 우선 단계). LOCK된 17시는 보존.
    last_rest = dict(last_rest if last_rest is not None else (base.last_rest if base is not None else {}))
    rest17 = {p: x[p,9,'휴게'] + x[p,9,STANDBY] + (x[p,9,'G2'] if mode == '유도리' else 0) for p in generals}
    last_rank = g2_rank = 0
    if last_rest and (locked_through is None or locked_through < 9):
        waits = sorted({info.get('last', -1) for p, info in last_rest.items()
                        if p in rest17 and not info.get('prev') and 9 not in offs[p] and p != last_two})
        for p in generals:
            info = last_rest.get(p)
            if not info or 9 in offs[p] or p == last_two:   # 오후반차 대행 준호는 17시 휴게가 통제A 규칙(우선)
                continue
            if info.get('prev'):
                m.Add(rest17[p] == 0)
            else:                                     # 오래 기다린 순서 0,1,2… (한 번도 안 받음 = -1 = 맨 앞)
                last_rank += waits.index(info.get('last', -1)) * rest17[p]
                if mode == 'FM' and absent[9] < 2:    # FM 표 17시 G2(유도리면 휴게성)도 같은 순번 — 실제 휴게보다 뒤 순위
                    g2_rank += waits.index(info.get('last', -1)) * x[p,9,'G2']
    # 2026-10-18 사용자 확정(아주 강한 권장): FM 표의 17시 G2(유도리로 운영하면 휴게성 막타임)에도 직전 출근 수혜자는
    # 넣지 않는다. 지키기 어려울 때만 허용 (아래 우선 단계, 16시 휴게 다음).
    g2_17 = 0
    if last_rest and mode == 'FM' and absent[9] < 2 and (locked_through is None or locked_through < 9):
        g2_17 = sum(x[p,9,'G2'] for p in generals if last_rest.get(p, {}).get('prev') and 9 not in offs[p]
                    and p != last_two)
    # 통제A G1: 최소 1번은 11~15시 안(하드, 2026-10-18), 그 밖 G1은 비권장. 피로도 2점 업무를 더 줄 땐 L1 우선(권장):
    # L1이 아닌 2점 업무(G1·FM G2·상/중층 순찰) 횟수를 최소화.
    a_g1_out = sum(x['A',t,'G1'] for t in range(10) if t not in A_G1_WINDOW)
    a_extra = (sum(x['A',t,'G1'] for t in range(10)) + (sum(x['A',t,'G2'] for t in range(10)) if mode == 'FM' else 0)
               + sum(x['A',t,'순찰'] for t in PATROL if PATROL[t][1] == 2))
    spreads, violations, half_rest = [], [], []
    # 2026-10-05 사용자 확정: 긴급(또는 해 없는 반차일)은 연속 실근무 상한·격차 1을 가능하면 지킬 규칙으로
    emergency = bool(leavers) or relaxed is True
    partial = bool(leavers or half_days)          # 반차·이탈일: 통제A 추가 순찰 최소·반차자 휴게 1시간 목표

    def cap(expr, limit):
        """하드(평소) 또는 어기면 벌점(긴급)."""
        if emergency:
            slack = m.NewBoolVar('')
            m.Add(expr <= limit + slack)
            violations.append(slack)
        else:
            m.Add(expr <= limit)
    # 2026-10-12 사용자 확정: 통제A도 운영 포스트(결원 2명 시간이 있으면 G2 제외) 하루 최소 1번.
    # 평소 하드, 긴급(또는 해 없는 반차일)은 가능하면 지킬 규칙.
    if not a_half:                                    # 통제A 반차 날은 반나절이라 포스트 4개 1번씩 불가 → 적용 안 함 (10/18)
        for v in LABELS[:4]:
            if v != 'G2' or max(absent) < 2:
                cap(-sum(x['A', t, v] for t in range(10)), -1)
    a_g1_slots = [t for t in A_G1_WINDOW if t not in offs['A']]    # 통제A G1 11~15시 (반차 날은 출근한 시간만)
    if a_g1_slots and (locked_through is None or locked_through < max(a_g1_slots)):
        cap(-sum(x['A', t, 'G1'] for t in a_g1_slots), -1)
    fatigue_of = {}                                   # 이력 어드밴티지용 피로도 (FM이면 FM 기준)
    long_runs = []                                    # 결원 1명 시간 4연속 실근무 사용 여부
    end3, end_rest2 = [], []
    views = ('FM', '유도리') if mode == 'FM' else ('유도리',)
    for view in views:
        totals = {}
        worklabels = [v for v in LABELS if v != '휴게' and not (view == '유도리' and v == 'G2')]
        restlabels = ['휴게', STANDBY] + (['G2'] if view == '유도리' else [])
        standlabels = ['G1','L1','순찰'] + (['G2'] if view == 'FM' else [])
        for p in ids:
            works = [sum(x[p,t,v] for v in worklabels) for t in range(10)]
            rests = [sum(x[p,t,v] for v in restlabels) for t in range(10)]
            pure = [x[p,t,'휴게'] + x[p,t,STANDBY] for t in range(10)]
            stands = [sum(x[p,t,v] for v in standlabels) for t in range(10)]
            fatigue = [sum(x[p,t,v]*(PATROL.get(t,('',0))[1] if v == '순찰' else 1 if v == 'I1' else 2)
                           for v in worklabels) for t in range(10)]
            for t in range(7):                       # 4칸 연속 실근무: 네 칸 모두 결원 1명 시간일 때만 허용
                if not all(absent[k] == 1 for k in range(t, t+4)):
                    cap(sum(works[t:t+4]), 3)
                else:                                # 2026-10-12 사용자 확정: 4연속 없이 해가 없을 때만 (아래 최소화)
                    used = m.NewBoolVar('')
                    m.Add(sum(works[t:t+4]) <= 3 + used)
                    long_runs.append(used)
                    # 2026-10-18 사용자 확정: 4연속이면 그 4칸에 G2·I1 각각 최소 1번 (유도리 기준은 G2가 휴게성이라 4연속 불가)
                    m.Add(sum(x[p,k,'G2'] for k in range(t, t+4)) >= sum(works[t:t+4]) - 3)
                    m.Add(sum(x[p,k,'I1'] for k in range(t, t+4)) >= sum(works[t:t+4]) - 3)
            for t in range(6): cap(sum(works[t:t+5]), 4)
            if standing_limit:
                for t in range(8): m.Add(sum(stands[t:t+3]) <= 2)
            # 2026-10-18 사용자 확정: 휴게·대기만 3연속 금지(유도리 G2 휴게성이 끼면 3연속 허용), 4연속 휴게 금지
            for t in range(8): m.Add(sum(pure[t:t+3]) <= 2)
            for t in range(7): m.Add(sum(rests[t:t+4]) <= 3)
            totals[p] = (sum(works), sum(fatigue))
            fatigue_of.setdefault(p, sum(fatigue))
            if view == views[0]:                      # 마지막 시간 끝 3연속 근무·2연속 휴게 (아래 end_clash)
                end3.append(sum(works[7:10]) - 2)
                if p not in ('A', last_two):          # 통제A(오후반차면 대행 준호) 16·17시 휴게는 별도 규칙
                    end_rest2.append(sum(rests[8:10]) - 1)
            if leavers.get(p, {}).get('kind') == 'half' or p in half_days:
                # 2026-10-05 사용자 확정: 긴급·미리 정한 반차자는 나오는 5시간 중 휴게 1시간만 (다른 근무자 밸런스 다음)
                gap = m.NewIntVar(0, 10, '')
                m.AddAbsEquality(gap, sum(rests[t] for t in range(10) if t not in offs[p]) - 1)
                half_rest.append(gap)
        if balance and full:
            if not emergency:                        # 긴급은 차이를 줄이는 목표만 (아래 spreads)
                for a in full:
                    for b in full:
                        for k in (0,1): m.Add(totals[a][k]-totals[b][k] <= 1)
            # 2026-10-05 사용자 확정: 완벽한 n빵(차이 0)을 먼저 찾고, 안 되면 1 차이 표
            for k in (0,1):
                hi, lo = m.NewIntVar(0, 40, ''), m.NewIntVar(0, 40, '')
                m.AddMaxEquality(hi, [totals[p][k] for p in full])
                m.AddMinEquality(lo, [totals[p][k] for p in full])
                spreads.append(hi-lo)
        if manager_priority:
            for p in full: m.Add(totals['A'][0] <= totals[p][0])
    # 통제A 피로도 (표의 운영 기준 = FM 표면 FM, 2026-10-18 사용자 확정): 끝까지 근무하는 일반근무자 각각보다
    # 결원 1·2명은 최소 1점 적게(하드), 결원 0명은 최소 1점 적게가 권장이되 가장 적은 사람보다 많지는 않게(하드).
    # 반차·긴급일은 기존 확정 순위대로 권장만. 상한 없음(10/18 '최소 1~2점 적게').
    a_gap = []
    for p in full:
        short = m.NewIntVar(0, 40, '')
        m.Add(fatigue_of[p] - fatigue_of['A'] + short >= 1)
        a_gap.append(short)
        if manager_priority and not partial and not emergency and not a_half:   # 통제A 반차 날은 반나절이라 제외
            m.Add(fatigue_of[p] - fatigue_of['A'] >= (1 if base_absent >= 1 else 0))
    a_off = sum(a_gap)
    # 2026-10-18 사용자 요청(강한 권장): 누군가 15·16·17시 3연속 근무로 끝나면, 일반근무자 16·17시 2연속 휴게(대기 포함)는
    # 나오지 않게. 둘이 같이 나오면 1 (표의 운영 기준). 통제A 16·17시 휴게는 별도 확정 규칙이라 2연속 휴게 쪽에서 제외.
    any3, any2, end_clash = m.NewBoolVar(''), m.NewBoolVar(''), m.NewBoolVar('')
    for e in end3: m.Add(e <= any3)
    for e in end_rest2: m.Add(e <= any2)
    m.Add(end_clash >= any3 + any2 - 1)
    # exclude: 피할 표 하나(dict) 또는 여러 개(list) — 재생성 후보가 이전 후보들과 모두 다르게 (2026-10-18)
    for ex in (exclude if isinstance(exclude, (list, tuple)) else [exclude] if exclude else []):
        if set(ex) == set(ids):
            m.Add(sum(x[p,t,ex[p][t]] for p in ids for t in range(10)) < len(ids)*10)
    a_patrol = sum(x['A',t,'순찰'] for t in range(10))   # 긴급: 통제A 추가 순찰은 최소 (일반 우선)
    # 2026-10-05 사용자 확정(강한 비권장): 같은 포스트 2연속(예: 11·12시 연속 G1). 밸런스(n빵) 다음 순위
    repeats = []
    for p in ids:
        for t in range(9):
            for v in LABELS[:4]:
                both = m.NewBoolVar('')
                m.AddBoolAnd([x[p,t,v], x[p,t+1,v]]).OnlyEnforceIf(both)
                m.AddBoolOr([x[p,t,v].Not(), x[p,t+1,v].Not()]).OnlyEnforceIf(both.Not())
                repeats.append(both)
    repeat = sum(repeats)
    # 2026-10-12 사용자 확정: 완벽 n빵이 안 될 때 남는 피로도 차이는 최근 이력에서 손해 본 사람에게 유리하게.
    # 순위: n빵 차이 → 같은 포스트 2연속 → 이력 어드밴티지. 오늘 일반근무자끼리 평균을 뺀 손해 점수 × 피로도 최소.
    debts = {p: (history or {}).get(names[p], 0.0) for p in full}
    mean = sum(debts.values()) / len(debts) if debts else 0.0
    weights = {p: round((debts[p] - mean) * 10) for p in full}
    advantage = sum(w * fatigue_of[p] for p, w in weights.items() if w)
    scale = sum(abs(w) for w in weights.values()) * 40 * 2 + 1     # 이력 항이 2연속 1개보다 작게

    scale *= rotation_scale

    def solve(model, limit=seconds):
        solver = cp_model.CpSolver()
        solver.parameters.max_time_in_seconds = limit
        solver.parameters.num_search_workers = 4
        solver.parameters.random_seed = seed
        return solver, solver.Solve(model)

    # 0단계 (2026-10-12 사용자 확정): 결원 1명 시간 4연속은 4연속 없이 해가 없을 때만, 그때도 최소 횟수.
    # 완벽 n빵보다 우선. 긴급(또는 해 없는 반차일)은 다른 '가능하면 지킬 규칙'과 같은 순위로 최소화.
    # 통제A 16시 휴게(강한 권장, 2026-10-16): 평소엔 다른 목표보다 먼저 가장 좋은 값(휴게 > G2 > 그 밖)을 고정.
    # 긴급(또는 해 없는 반차일)은 '가능하면 지킬 규칙' 바로 다음 순위로 최소화.
    if not isinstance(a16, int) and not emergency:
        best16 = m.Clone()
        best16.Minimize(a16)
        probe_solver, probe_status = solve(best16, min(seconds, 10))
        if probe_status in (cp_model.FEASIBLE, cp_model.OPTIMAL):
            m.Add(a16 <= int(probe_solver.ObjectiveValue()))
    # 막타임 분배 순위 (2026-10-18 사용자 확정): ① 실제 휴게·대기는 직전 수혜자 금지(하드)
    # ② 17시 G2도 직전 수혜자 피하기(아주 강한 권장) ③ 실제 휴게·대기는 오래된 사람부터 ④ 17시 G2도 오래된 사람부터
    # (③보다 뒤). 지키기 어려우면 그 단계만 가능한 만큼 — 다른 규칙이 우선.
    if not isinstance(g2_17, int) and not emergency:
        g2_probe = m.Clone()
        g2_probe.Minimize(g2_17)
        probe_solver, probe_status = solve(g2_probe, min(seconds, 10))
        if probe_status in (cp_model.FEASIBLE, cp_model.OPTIMAL):
            m.Add(g2_17 <= int(probe_solver.ObjectiveValue()))
    if not isinstance(last_rank, int) or not isinstance(g2_rank, int):
        rank = 100 * last_rank + g2_rank                # ③ 먼저, 같으면 ④
        rank_probe = m.Clone()
        rank_probe.Minimize(rank)
        probe_solver, probe_status = solve(rank_probe, min(seconds, 10))
        if probe_status in (cp_model.FEASIBLE, cp_model.OPTIMAL):
            m.Add(rank <= int(probe_solver.ObjectiveValue()))
    # 그다음: 통제A 1~2점 덜 (n빵 판정보다 먼저). 반차·긴급일은 기존 확정 순위(반차자 휴게 1시간) 다음 — 아래 목적식
    if a_gap and not partial:
        gap_probe = m.Clone()
        gap_probe.Minimize(a_off)
        probe_solver, probe_status = solve(gap_probe, min(seconds, 10))
        if probe_status in (cp_model.FEASIBLE, cp_model.OPTIMAL):
            m.Add(a_off <= int(probe_solver.ObjectiveValue()))
    if not emergency:                                # 그다음: 마지막 시간 3연속 근무 vs 2연속 휴게 (강한 권장)
        clash_probe = m.Clone()
        clash_probe.Minimize(end_clash)
        probe_solver, probe_status = solve(clash_probe, min(seconds, 10))
        if probe_status in (cp_model.FEASIBLE, cp_model.OPTIMAL):
            m.Add(end_clash <= int(probe_solver.ObjectiveValue()))
    if long_runs and emergency:
        violations.extend(long_runs)
    elif long_runs:
        fewest = m.Clone()
        fewest.Minimize(sum(long_runs))
        probe_solver, probe_status = solve(fewest, min(seconds, 10))
        if probe_status in (cp_model.FEASIBLE, cp_model.OPTIMAL):
            m.Add(sum(long_runs) <= int(probe_solver.ObjectiveValue()))
    # 1단계: 완벽한 n빵(일반근무자 실근무·피로도 차이 0) / 2단계: 불가능하면 차이 1 이내에서 최소
    # 평소 뒷순위 (10/18): 통제A 대기 비권장 → 같은 포스트 2연속 → 통제A 11~15시 밖 G1 → 2점 업무는 L1 우선
    tail = 100*a_standby + 10*repeat + 3*a_g1_out + a_extra
    no_perfect = gap_over = False
    if partial or emergency:
        # 반차·긴급: ① 가능하면 지킬 규칙 위반 최소 ② 통제A 추가 순찰 최소(일반 우선) ③ 일반근무자 차이 최소(완벽 n빵 우선)
        # ④ 반차자 휴게 1시간에 가깝게 ⑤ 같은 포스트 2연속 최소
        # (10/18) ⑥ 통제A 대기 비권장 ⑦ 통제A 1점 덜 ⑧ 2연속 ⑨ 통제A 11~15시 밖 G1 · L1 우선
        m.Minimize(scale*(10*(1000000*sum(violations) + 100000*a16 + 90000*g2_17 + 50000*end_clash + 10000*a_patrol + 1000*sum(spreads)
                              + 50*sum(half_rest) + 20*a_standby + 2*a_off + repeat) + 3*a_g1_out + a_extra)
                   + advantage*rotation_scale + rotation_cost)
        # 긴급: 전체 계산 시간은 그대로(seconds) — 2/3은 규칙 위반 최소, 1/3은 허용 차이 맞추기
        first = max(1, seconds * 2 // 3) if leavers and spreads else (seconds if emergency else min(seconds, 15))
        solver, status = solve(m, first)
        if leavers and spreads and status in (cp_model.FEASIBLE, cp_model.OPTIMAL):
            # 2026-10-12 사용자 확정: 긴급 재편성 일반근무자 격차 — LOCK 10시까지 1, 그 뒤 2까지 허용.
            # 연속 실근무 상한·통제A 포스트(가능하면 지킬 규칙)를 더 어기지 않는 범위에서만 맞춘다.
            limit = emergency_gap(locked_through)
            if max(solver.Value(spread) for spread in spreads) > limit:
                probe = m.Clone()
                for spread in spreads:
                    probe.Add(spread <= limit)
                probe.Add(sum(violations) <= int(solver.Value(sum(violations))))
                better, better_status = solve(probe, max(1, seconds - first))
                if better_status in (cp_model.FEASIBLE, cp_model.OPTIMAL):
                    solver, status = better, better_status
                else:
                    gap_over = True            # 허용 차이 안의 표가 없어 차이 최소 표 (화면 안내)
    elif spreads:
        probe = m.Clone()
        probe.Add(sum(spreads) == 0)
        probe.Minimize(tail*rotation_scale + rotation_cost)
        # 완벽 n빵 가능/불가능 판정: 10/12~13 통제A 규칙 추가 뒤 10초로는 불가능 증명이 자주 안 끝남 → 최대 20초 (2026-10-13)
        solver, status = solve(probe, min(seconds, 20))
        if status in (cp_model.FEASIBLE, cp_model.OPTIMAL):
            status = cp_model.OPTIMAL                # 완벽한 n빵 (2연속 최소화는 10초 안 최선)
        else:
            no_perfect = status == cp_model.INFEASIBLE
            m.Minimize(scale*(1000*sum(spreads) + tail) + advantage*rotation_scale + rotation_cost)
            # 2026-10-05 사용자 확정: 완벽 n빵 불가능이 확인되면 1 차이 표 다듬기는 최대 10초
            solver, status = solve(m, min(seconds, 10) if no_perfect else seconds)
    else:
        m.Minimize(tail*rotation_scale + rotation_cost)
        solver, status = solve(m)
    label = solver.StatusName(status)
    if status not in (cp_model.FEASIBLE, cp_model.OPTIMAL): return None, label
    if no_perfect and label == 'FEASIBLE':
        label = 'NO_PERFECT'          # 완벽 n빵 불가능은 확인, 1 차이 안에서 최선 확인은 시간 부족
    if gap_over:
        label = 'GAP_OVER'            # 긴급 격차 기준(1 또는 2) 안의 표를 찾지 못해 차이 최소 표
    grid = {p: [next(v for v in labels if solver.Value(x[p,t,v])) for t in range(10)] for p in ids}
    # relaxed는 이름으로 넘긴다: 순서로 넘기면 rule_exempt_names 칸에 들어가 완화 표 검증이 멈췄음 (2026-10-18 수정)
    result = WeekendSchedule(str(day), dict(names), grid, mode, g2_cap, balance, standing_limit, manager_priority,
                             locked_through, leavers, half_days, relaxed=relaxed is True, standby=True,
                             last_rest=last_rest, a_half=a_half, proxy=proxy if a_half else None)
    result.patrol_events = tuple(patrol_events)
    errors = validate(result, base)
    if errors: raise RuntimeError('; '.join(errors))
    return result, label


def diagnose(day, names, mode='FM', *, half_days=None, history=None, patrol_events=(), seconds=8, last_rest=None,
             a_half=None, proxy=None):
    """해 없음 진단 (2026-10-18 사용자 요청, 야간 21-8 최소완화 진단과 같은 뜻): 규칙 묶음을 하나씩 빼고 다시
    계산해 표가 나오는 묶음을 돌려준다. 진단용이며 결과를 자동 적용하지 않는다(규칙 자동 완화 금지)."""
    trials = [('일반근무자 실근무·피로도 차이 1 이내(n빵)', {'balance': False}),
              ('3연속 입식 금지', {'standing_limit': False}),
              ('통제A 실근무 ≤ 일반근무자', {'manager_priority': False}),
              ('G2 1인 하루 최대 2회', {'g2_cap': 3}),
              ('연속 실근무 상한·통제A 포스트 1번씩 (가능하면 지킬 규칙으로 낮춤)', {'relaxed': True})]
    if mode == 'FM':
        trials.append(('FM·유도리 동시 검증 (유도리로 생성하면)', {'mode': '유도리'}))
    def works(change):
        opts = {'mode': mode, **change}
        try:
            result, _ = generate(day, names, opts.pop('mode'), seconds=seconds, half_days=half_days,
                                 history=history, patrol_events=patrol_events, last_rest=last_rest,
                                 a_half=a_half, proxy=proxy, **opts)
        except (RuntimeError, ValueError):
            result = None
        return result is not None
    from concurrent.futures import ThreadPoolExecutor   # 화면 대기 시간을 줄이려고 3개씩 동시에 (CP-SAT는 GIL 밖에서 계산)
    with ThreadPoolExecutor(max_workers=3) as pool:
        ok = list(pool.map(works, [change for _, change in trials]))
    return [label for (label, _), good in zip(trials, ok) if good]


def emergency_candidates(schedule, start):
    """start 칸부터 빠질 수 있는 일반근무자 (아직 빠지지 않은 사람, 그 시간에 근무 중인 사람).
    오후반차자는 13시 전 긴급 이탈만, 오전반차자는 13시 이후 긴급 이탈만 의미가 있다."""
    return [p for p in schedule.grid if p != 'A' and p not in schedule.leavers
            and any(t not in off_slots(schedule, p) for t in range(start, 10))]


def reoptimize(base, lock, pid, kind, *, seconds=30, seed=0, exclude=None, history=None, patrol_events=None):
    """긴급 반차·이탈: lock 칸까지 기존 배정 그대로, pid는 오후반차(13시)·긴급 이탈(lock+1)부터 ×."""
    start = lock + 1
    if pid == 'A' or pid not in base.grid or pid in base.leavers:
        raise ValueError('빠질 수 있는 일반근무자를 고르세요.')
    if base.locked_through is not None and lock < base.locked_through:
        raise ValueError('이미 LOCK한 시간보다 앞은 고를 수 없습니다.')
    if not 0 <= lock <= 8:
        raise ValueError('LOCK 시간은 08~16시 중에서 고르세요.')
    if kind == 'half' and start > HALF_DAY_LEAVE:
        raise ValueError('오후반차(13시 퇴근)는 13시 전까지만 고를 수 있습니다.')
    if kind == 'half' and pid in base.half_days:
        raise ValueError('이미 반차인 사람은 긴급 이탈만 고를 수 있습니다.')
    leave_from = HALF_DAY_LEAVE if kind == 'half' else start
    leavers = dict(base.leavers)
    leavers[pid] = {'from': leave_from, 'kind': kind, 'lock': lock}
    return generate(base.day, base.names, base.mode, seconds=seconds, seed=seed, exclude=exclude,
                    g2_cap=base.g2_cap, balance=base.balance, standing_limit=base.standing_limit,
                    manager_priority=base.manager_priority, base=base, locked_through=lock, leavers=leavers,
                    half_days=base.half_days, history=history,
                    patrol_events=base.patrol_events if patrol_events is None else patrol_events)


def save(store, schedule, overwrite=False):
    errors = validate(schedule)
    if errors: raise ValueError('; '.join(errors))
    path = Path(store)/f'{schedule.day}.json'
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists() and not overwrite: raise FileExistsError('이 날짜에 저장된 표가 있습니다.')
    temporary = path.with_suffix('.tmp')
    temporary.write_text(json.dumps(asdict(schedule), ensure_ascii=False, indent=2), encoding='utf-8')
    temporary.replace(path)
    return path


def save_actual(store, schedule, changed_cells=0):
    """화면에서 고친 실제 근무를 최종본으로 저장 (2026-10-13, 야간·평일 '💾 실제 근무 저장'과 같음).
    실제 근무 기록이라 생성 규칙 검사로 막지 않는다. 출처(엑셀 원본 등)·메모는 유지하고 이전 저장본은 .trash에."""
    import shutil
    from datetime import datetime
    path = Path(store)/f'{schedule.day}.json'
    old = json.loads(path.read_text(encoding='utf-8')) if path.exists() else {}
    if path.exists():
        trash = path.parent/'.trash'; trash.mkdir(exist_ok=True)
        shutil.copy2(path, trash/f"{schedule.day}__before-edit-{datetime.now():%Y%m%d-%H%M%S}.json")
    keep = {k: v for k, v in old.items() if k in ('source', 'source_hash', 'source_sheet', 'source_file',
                                                   'source_review', 'source_attachment', 'note')}
    note = keep.get('note', '')
    if changed_cells:
        note = (note + '\n' if note else '') + f'실제 근무 수정 {changed_cells}칸 ({datetime.now():%m/%d %H:%M})'
    payload = {**asdict(schedule), **keep, 'note': note, 'final_save_method': 'screen-edit',
               'confirmed_at': old.get('confirmed_at') or datetime.now().isoformat(timespec='seconds'),
               'edited_at': datetime.now().isoformat(timespec='seconds')}
    temporary = path.with_suffix('.tmp')
    temporary.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding='utf-8')
    temporary.replace(path)
    return path


def load(store, day):
    from dataclasses import fields
    data=json.loads((Path(store)/f'{day}.json').read_text(encoding='utf-8'))
    # JSON은 목록이 list로만 돌아온다 → 기본값이 tuple인 칸(patrol_events·rule_exempt_names)은 생성 때와 같은 tuple로 (2026-10-18)
    for f in fields(WeekendSchedule):
        if isinstance(f.default, tuple) and isinstance(data.get(f.name), list):
            data[f.name]=tuple(data[f.name])
    return WeekendSchedule(**{f.name:data[f.name] for f in fields(WeekendSchedule) if f.name in data})
