"""평일 주간 근무표 → 현장 양식 PNG ('주간 근무 편성표' 엑셀 모양, 2026-10-07 사용자 요청)."""
from io import BytesIO
from pathlib import Path

from .day_shift import (CONTROL_SLOTS, EDU, EDU_SLOTS, HOURS, NUMBER_COLORS, PATROL, REST, SHUTTLE, STANDBY,
                        control_active, control_patrol_at)

COLUMNS = ['근무시간', 'G1', 'G2', 'G3', '4C', 'L1', 'L2', 'C1', 'C2', 'CP', '1C', '셔틀', '순찰', '대기', '휴게']
# 주간 CP 시간표 틀 (보안근무명령서와 같은 원본 패턴): 08~17시
CP_PATTERN = {3: ['CP1.CP2', 'CP2.CP3', 'CP3', 'CP1.CP2', 'CP2.CP3', 'CP1.CP3', 'CP1', 'CP2.CP3', 'CP1.CP3', 'CP1.CP2'],
              2: ['CP1.CP2', 'CP1', 'CP2', 'CP1.CP2', 'CP1', 'CP2', 'CP1', 'CP1', 'CP2', 'CP1']}


CP_COLORS = {1: '70AD47', 2: '00B0F0', 3: '92D050'}   # 원본 편성표 CP 색 (10/7·10/8 원본 20칸 대조)


def cp_color(text: str) -> str | None:
    """CP 칸 색: 혼자면 그 CP 색, 여럿이면 CP2 → CP3 → CP1 순으로 있는 사람 색 (원본 작성 방식)."""
    import re
    found = {int(n) for n in re.findall(r'CP\s*([123])', str(text).upper())}
    return next((CP_COLORS[n] for n in (2, 3, 1) if n in found), None)


def cell_number(text) -> int | None:
    """칸 색을 정할 번호: 번호가 하나면 그 번호, 공동근무(8.11·A.10·7.9)는 뒤(큰) 번호. 번호 없으면 None."""
    import re
    numbers = [int(n) for n in re.split(r'[.\s,]+', str(text)) if n.isdigit()]
    return max(numbers) if numbers else None


def _join(tokens):
    return '.'.join(sorted(tokens, key=lambda v: (v != 'A', v != 'E', int(v) if v.isdigit() else 99, v)))


def render_day_png(schedule, cp=None, team='A', e_slots=()):
    from PIL import Image, ImageDraw, ImageFont
    regular = Path('C:/Windows/Fonts/malgun.ttf'); bold = Path('C:/Windows/Fonts/malgunbd.ttf')
    if not regular.exists():
        raise ValueError('이미지 출력용 한글 글꼴을 찾지 못했습니다.')
    scale = 2
    xs = [0, 80] + [80 + 72 * i for i in range(1, 15)]
    W = xs[-1] + 1; H = 108 + 31 * 3 + 33 * 10 + 160
    im = Image.new('RGB', (W * scale, H * scale), 'white'); d = ImageDraw.Draw(im)

    def box(a, b, c, e, fill='white'):
        d.rectangle(tuple(round(v * scale) for v in (a, b, c, e)), fill=fill, outline='black', width=scale)

    def text(a, b, c, e, value, size=14, strong=False):
        f = ImageFont.truetype(str(bold if strong else regular), size * scale)
        bb = d.textbbox((0, 0), value, font=f)
        while bb[2] - bb[0] > (c - a - 4) * scale and size > 8:      # 긴 칸은 글자를 줄여 넣는다
            size -= 1; f = ImageFont.truetype(str(bold if strong else regular), size * scale); bb = d.textbbox((0, 0), value, font=f)
        d.text(((a + c) * scale / 2 - (bb[2] - bb[0]) / 2, (b + e) * scale / 2 - (bb[3] - bb[1]) / 2 - bb[1]),
               value, font=f, fill='black')

    day = schedule.day
    sign = W - 1 - 230                                   # 오른쪽 위 결재 칸 (원본 양식)
    box(0, 0, sign, 57); text(0, 0, sign, 57, '주간 근무 편성표', 28, True)
    box(0, 57, sign, 108)
    text(0, 57, sign, 108, f'{day:%Y년 %m월 %d일} {"월화수목금토일"[day.weekday()]}요일 근무조 : {team}조', 23, True)
    box(sign, 0, sign + 46, 108, '#c0c0c0'); text(sign, 0, sign + 46, 54, '결', 15); text(sign, 54, sign + 46, 108, '재', 15)
    for a, b, label in [(sign + 46, sign + 138, '담 당'), (sign + 138, W - 1, '팀 장')]:
        box(a, 0, b, 32, '#c0c0c0'); text(a, 0, b, 32, label, 15, True); box(a, 32, b, 108)
    number = {p.pid: p.number for p in schedule.people}
    present = sorted((p for p in schedule.people if p.number), key=lambda p: p.number)
    from .cp_schedule import short
    layout = schedule.source_layout or {}
    raw_rows = layout.get('applied_rows') or layout.get('rows')
    raw = raw_rows if raw_rows and len(raw_rows) == 10 else None      # 업로드 원본 칸(4C 공동근무·전체 번호) 그대로
    mapping = {int(k): v for k, v in (layout.get('mapping') or {}).items() if str(k).isdigit() and v} if raw else {}
    if mapping and not cp:
        cp = {k[2:]: v for k, v in (layout.get('extra_names') or {}).items() if k.startswith('CP') and v} or cp
    tags = [f'{n}{mapping[n]}' for n in sorted(mapping)] if mapping else [f'{p.number}{p.name}' for p in present]
    lines = [(['통제A'] if schedule.control else []) + tags[:5],          # 원본 양식: 위 줄 통제A·1~5번
             tags[5:] + ([f'CP{k}{short(cp[k])}' for k in sorted(cp)] if cp else [])]
    box(0, 108, 80, 170, '#c0c0c0'); text(0, 108, 80, 170, '근무자명', 13)
    for r, names in enumerate(lines):
        for i in range(14):
            box(xs[i + 1], 108 + 31 * r, xs[i + 2], 139 + 31 * r, '#c0c0c0')
            if i < len(names):
                text(xs[i + 1], 108 + 31 * r, xs[i + 2], 139 + 31 * r, names[i], 12)
    for j, label in enumerate(COLUMNS):
        box(xs[j], 170, xs[j + 1], 201, '#c0c0c0'); text(xs[j], 170, xs[j + 1], 201, label, 14)
    col = {c: i for i, c in enumerate(COLUMNS)}
    for t, hour in enumerate(HOURS):
        cells = [[] for _ in COLUMNS]
        edu = []
        for pid, row in schedule.grid.items():
            label = row[t]
            who = str(number.get(pid) or pid)
            if label in col:
                cells[col[label]].append(who)
            elif label == '통제':
                cells[col['4C']].append(who)
            elif label == PATROL:
                cells[col['순찰']].append(who)
            elif label == STANDBY:
                cells[col['대기']].append(who)
            elif label == EDU:
                edu.append(who)
            elif label == REST:
                cells[col['휴게']].append(who)
        for post, filler in schedule.fill.get(t, {}).items():
            if post in col:
                cells[col[post]].append(filler)
        if control_active(schedule, t):
            if t in CONTROL_SLOTS:
                cells[col['4C']].append('A')
            elif control_patrol_at(schedule, t):
                cells[col['순찰']].append('A')
            elif 'A' not in schedule.fill.get(t, {}).values():
                cells[col['휴게']].append('A')
        if t in e_slots:
            cells[col['휴게']].append('E')
        if cp and len(cp) in CP_PATTERN:
            cells[col['CP']] = [CP_PATTERN[len(cp)][t]]
            if t == 9:
                cells[col['셔틀']].append(f'CP{len(cp)}')
        shuttle = schedule.shuttle.get(t)
        shuttle_number = number.get(shuttle) if shuttle else None
        if shuttle:
            cells[col['셔틀']].insert(0, f'{number[shuttle]}({SHUTTLE[t]})')
        if raw:                       # 업로드 저장본: 원본 칸 글자를 그대로 (앱 프로그램 근무표와 같음)
            import re
            from .schedule_image_import import normalize_cell
            source = raw[t]
            cells = [[] for _ in COLUMNS]
            edu = []
            for name in COLUMNS[1:]:
                value = str(source.get(name, '') or '').strip()
                if name == '휴게' and value.startswith('교육'):
                    edu = [re.sub(r'^교육[:：]?\s*', '', value)]
                    continue
                if value:
                    cells[col[name]] = [value if name == '셔틀' or '(' in value else normalize_cell(value)]   # cpl, cp2 → CP1.CP2
            m = re.match(r'\s*(\d{1,2})\s*\(', cells[col['셔틀']][0]) if cells[col['셔틀']] else None
            shuttle_number = int(m[1]) if m else None
        y = 201 + t * 33
        box(xs[0], y, xs[1], y + 33); text(xs[0], y, xs[1], y + 33, hour[:5] if ':' in hour else f'{8 + t:02d}:00')
        merged = t in EDU_SLOTS and edu
        for j in range(1, len(COLUMNS)):
            if merged and COLUMNS[j] in ('대기', '휴게'):
                continue
            tokens = cells[j]
            value = tokens[0] if j in (col['CP'], col['셔틀']) and len(tokens) == 1 else _join(tokens)
            if j == col['셔틀'] and len(tokens) > 1:
                value = '.'.join(tokens)
            fill = 'white'
            if COLUMNS[j] in ('G1', 'G2', 'G3', '4C', 'L1', 'L2', 'C1', 'C2', '1C', '순찰'):
                n = cell_number(value)             # 공동근무 '7.9'·'A.10'은 뒤 번호 색, 'A' 혼자는 흰색 (원본)
                if n:
                    fill = '#' + NUMBER_COLORS.get(n, 'FFFFFF')
            if j == col['셔틀'] and shuttle_number:                   # 셔틀도 번호 색 (2026-10-08 사용자 요청)
                fill = '#' + NUMBER_COLORS.get(int(shuttle_number), 'FFFFFF')
            elif j in (col['CP'], col['셔틀']) and cp_color(value):   # CP 칸·17시 셔틀 CP3도 원본 CP 색
                fill = '#' + cp_color(value)
            box(xs[j], y, xs[j + 1], y + 33, fill); text(xs[j], y, xs[j + 1], y + 33, value, 14)
        if merged:   # 10·14시 교육: 대기·휴게 두 칸을 합쳐 '교육: 1.3 / 휴게 9'
            a, b = xs[col['대기']], xs[col['휴게'] + 1]
            rest = _join(cells[col['대기']] + cells[col['휴게']])
            box(a, y, b, y + 33); text(a, y, b, y + 33, f'교육: {_join(edu)}' + (f' / 휴게 {rest}' if rest else ''), 13)
    # 특이사항 칸: 원본 주간 편성표의 고정 문구 (2026-10-07 사용자 요청)
    y = 201 + 33 * 10; mid = xs[9] + 40
    box(0, y, 80, H - 1); text(0, y, 80, H - 1, '특이사항', 13)
    box(80, y, mid, H - 1); box(mid, y, W - 1, H - 1)

    def line(a, top, value, size=15):
        f = ImageFont.truetype(str(bold), size * scale)
        d.text(((a + 8) * scale, (top) * scale), value, font=f, fill='black')
    for k, value in enumerate(['*4F비상계단 오픈시간*          (시간준수)', '출근:07:15~08:10', '점심:11:20~13:40', '퇴근:16:50~18:00']):
        line(80, y + 10 + k * 36, value)
    for k, value in enumerate(['순찰자 : 1F~B4F A,B,C,D코어 비상E/V홀 및', '           비상계단 시건 확인', '', '순찰 후 무전 및 보고 실시']):
        line(mid, y + 10 + k * 36, value, 14)
    buffer = BytesIO(); im.save(buffer, format='PNG'); return buffer.getvalue()
