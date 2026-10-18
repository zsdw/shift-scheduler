"""Shift pattern (주주야야휴휴) and Korean public holidays for the date picker.

- Pattern: 6-day cycle 주, 주, 야, 야, 휴, 휴 starting 2026-09-01 (주간 첫째 날).
- Night type (N1~N4) of a night starting on day d:
  시작일이 평일/휴일 × 다음날이 평일/휴일 (휴일 = 토·일·공휴일).
- Holidays: 2026 and 2027 official lists (substitute holidays included).
  Add later years here when they are announced.
"""
from __future__ import annotations

from calendar import Calendar
from datetime import date, timedelta

PATTERN_START = date(2026, 9, 1)
PATTERN = ("주", "주", "야", "야", "휴", "휴")
PATTERN_LABELS = {"주": "주간", "야": "야간", "휴": "휴무"}

HOLIDAYS: dict[date, str] = {
    # 2026
    date(2026, 1, 1): "신정",
    date(2026, 2, 16): "설날 연휴", date(2026, 2, 17): "설날", date(2026, 2, 18): "설날 연휴",
    date(2026, 3, 1): "삼일절", date(2026, 3, 2): "대체공휴일(삼일절)",
    date(2026, 5, 5): "어린이날",
    date(2026, 5, 24): "부처님오신날", date(2026, 5, 25): "대체공휴일(부처님오신날)",
    date(2026, 6, 3): "전국동시지방선거",
    date(2026, 6, 6): "현충일",
    date(2026, 7, 17): "제헌절",
    date(2026, 8, 15): "광복절", date(2026, 8, 17): "대체공휴일(광복절)",
    date(2026, 9, 24): "추석 연휴", date(2026, 9, 25): "추석", date(2026, 9, 26): "추석 연휴",
    date(2026, 10, 3): "개천절", date(2026, 10, 5): "대체공휴일(개천절)",
    date(2026, 10, 9): "한글날",
    date(2026, 12, 25): "성탄절",
    # 2027
    date(2027, 1, 1): "신정",
    date(2027, 2, 6): "설날 연휴", date(2027, 2, 7): "설날", date(2027, 2, 8): "설날 연휴",
    date(2027, 2, 9): "대체공휴일(설날)",
    date(2027, 3, 1): "삼일절",
    date(2027, 5, 1): "노동절", date(2027, 5, 3): "대체공휴일(노동절)",
    date(2027, 5, 5): "어린이날",
    date(2027, 5, 13): "부처님오신날",
    date(2027, 6, 6): "현충일",
    date(2027, 7, 17): "제헌절", date(2027, 7, 19): "대체공휴일(제헌절)",
    date(2027, 8, 15): "광복절", date(2027, 8, 16): "대체공휴일(광복절)",
    date(2027, 9, 14): "추석 연휴", date(2027, 9, 15): "추석", date(2027, 9, 16): "추석 연휴",
    date(2027, 10, 3): "개천절", date(2027, 10, 4): "대체공휴일(개천절)",
    date(2027, 10, 9): "한글날", date(2027, 10, 11): "대체공휴일(한글날)",
    date(2027, 12, 25): "성탄절", date(2027, 12, 27): "대체공휴일(성탄절)",
}


def shift_kind(day: date) -> str:
    """'주', '야' or '휴' for the day (the cycle also runs backwards)."""
    return PATTERN[(day - PATTERN_START).days % len(PATTERN)]


def document_day(day: date) -> bool:
    """A조 야2·휴1 문서 날짜: 전날 A조가 야간 근무한 날."""
    return (day - PATTERN_START).days % len(PATTERN) in (3, 4)


def holiday_name(day: date) -> str | None:
    return HOLIDAYS.get(day)


def is_off_day(day: date) -> bool:
    """Weekend or public holiday (빨간날)."""
    return day.weekday() >= 5 or day in HOLIDAYS


def night_type_for(day: date) -> str:
    start_off, next_off = is_off_day(day), is_off_day(day + timedelta(days=1))
    return {(False, False): "N1", (False, True): "N2", (True, False): "N3", (True, True): "N4"}[(start_off, next_off)]


def next_night(day: date) -> date:
    """The first night-shift day on or after ``day``."""
    for offset in range(len(PATTERN)):
        candidate = day + timedelta(days=offset)
        if shift_kind(candidate) == "야":
            return candidate
    return day


def month_calendar_html(selected: date, saved: set[date] = frozenset()) -> str:
    """Small month grid: 주/야/휴 per day, 빨간날 red, selected day outlined, saved nights dotted."""
    colors = {"주": "#FEF3C7", "야": "#DBEAFE", "휴": "#F1F5F9"}
    head = "".join(f"<th style='padding:2px;color:{'#DC2626' if i in (0, 6) else '#475569'};font-weight:600'>{d}</th>"
                   for i, d in enumerate("일월화수목금토"))
    rows = []
    for week in Calendar(firstweekday=6).monthdatescalendar(selected.year, selected.month):
        cells = []
        for day in week:
            if day.month != selected.month:
                cells.append("<td></td>")
                continue
            kind = shift_kind(day)
            red = is_off_day(day)
            outline = "box-shadow:inset 0 0 0 2px #7C3AED;" if day == selected else ""
            dot = "<span style='color:#16A34A'>●</span>" if day in saved else ""
            title = holiday_name(day) or ""
            cells.append(
                f"<td title='{title}' style='background:{colors[kind]};{outline}border-radius:5px;padding:2px 0;"
                f"text-align:center;line-height:1.15'>"
                f"<div style='font-weight:600;color:{'#DC2626' if red else '#111827'}'>{day.day}{dot}</div>"
                f"<div style='font-size:.62rem;color:#475569'>{kind}</div></td>")
        rows.append("<tr>" + "".join(cells) + "</tr>")
    legend = ("<div style='font-size:.68rem;color:#475569;margin-top:4px'>"
              "<span style='background:#FEF3C7;padding:0 4px'>주</span> 주간 · "
              "<span style='background:#DBEAFE;padding:0 4px'>야</span> 야간 · "
              "<span style='background:#F1F5F9;padding:0 4px'>휴</span> 휴무 · "
              "<span style='color:#DC2626'>빨간 숫자</span> 주말·공휴일 · "
              "<span style='color:#16A34A'>●</span> 저장된 근무표</div>")
    return (f"<div style='font-size:.78rem'><div style='font-weight:600;margin-bottom:2px'>"
            f"{selected.year}년 {selected.month}월</div>"
            "<table style='border-collapse:separate;border-spacing:2px;width:100%;table-layout:fixed'>"
            f"<tr>{head}</tr>{''.join(rows)}</table>{legend}</div>")
