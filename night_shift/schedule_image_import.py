"""Read images by their own title, clock rows and table geometry; never fill OCR gaps."""
from dataclasses import dataclass, asdict, field
from datetime import date, datetime
from pathlib import Path
from io import BytesIO
import hashlib, json, os, re, shutil, tempfile
from html import escape
import numpy as np
from PIL import Image, ImageOps
from .history_import import image_ocr, detected_date, fingerprint
from .calendar_info import is_off_day

UNKNOWN = '확인 필요'
DAY_COLUMNS = ['G1','G2','G3','4C','L1','L2','C1','C2','CP','1C','셔틀','순찰','대기','휴게']
NIGHT_COLUMNS = ['G1','L3','I1','G3','G2','G2(1)','G2(2)','CP','셔틀','순찰','보안실','휴게']
ALIASES = {'61':'G1','GI':'G1','62':'G2','63':'G3','LI':'L1','CI':'C1','CPI':'CP',
           '후계':'휴게','후게':'휴게','보안실대기':'대기'}

@dataclass
class ImageDraft:
    day: date | None
    kind: str
    team: str
    mapping: dict
    controls: list
    rows: list
    warnings: list
    source_hash: str
    evidence: str
    extra_names: dict = field(default_factory=dict)

def kind_for(day, shift):
    return 'night' if shift == 'night' else 'weekend_day' if day and is_off_day(day) else 'day'

def _clock(text):
    s=re.sub(r'\s','',text)
    m=re.fullmatch(r'(\d{1,2})[:시.;•·]?(00)',s)
    return int(m[1]) % 24 if m and int(m[1]) <= 24 else None

def classify(text, hours):
    title=re.sub(r'\s','',text)
    day_hours=sum(8 <= h <= 17 for h in hours)
    night_hours=sum(h >= 18 or h <= 7 for h in hours)
    title_shift='night' if '야간' in title else 'day' if '주간' in title else None
    clock_shift='day' if day_hours >= 3 and not night_hours else 'night' if night_hours >= 3 and not day_hours else None
    if title_shift and clock_shift and title_shift != clock_shift:
        raise ValueError('제목과 시간대가 서로 다릅니다. 주간·야간 표가 함께 찍혔다면 한 표씩 잘라 올려주세요.')
    shift=clock_shift or title_shift
    if shift is None:
        raise ValueError('근무표 종류를 확인하지 못했습니다. 제목과 시간 열이 포함된 표인지 확인하세요. 글자 인식이 거의 없는 사진은 더 큰 원본이 필요합니다.')
    day=detected_date(text)
    return day,kind_for(day,shift)

def _centers(indices):
    groups=[]
    for n in indices:
        if not groups or n > groups[-1][-1]+2:groups.append([int(n)])
        else:groups[-1].append(int(n))
    return [sum(g)/len(g) for g in groups]

def _text(words, box):
    x0,y0,x1,y1=box
    found=[w for w in words if x0 < w['x']+w['w']/2 < x1 and y0 < w['y']+w['h']/2 < y1]
    return ' '.join(w['text'] for w in sorted(found,key=lambda w:(round(w['y']/15),w['x'])))

def _ink(image, box):
    x0,y0,x1,y1=map(round,box)
    gray=np.asarray(ImageOps.grayscale(image.crop((x0+6,y0+6,x1-6,y1-6))))
    if not gray.size:return False
    background=float(np.percentile(gray,85))
    return int((gray < max(20,background*.5)).sum()) > max(6,gray.size*.002)

def _reread(image, box):
    x0,y0,x1,y1=map(round,box)
    crop=image.crop((x0+5,y0+5,x1-5,y1-5))
    gray=np.asarray(ImageOps.grayscale(crop))
    bg=float(np.percentile(gray,85))
    clean=Image.fromarray(np.where(gray < max(20,bg*.5),0,255).astype('uint8')).convert('RGB')
    # Repeat the *same* observed glyphs, so single-character OCR has context without inventing tokens.
    canvas=Image.new('RGB',(clean.width*3+80,clean.height+40),'white')
    for n in range(3):canvas.paste(clean,(20+n*(clean.width+20),20))
    b=BytesIO();canvas.save(b,'PNG')
    _,result=image_ocr(b.getvalue(),clean=False)
    # Only accept identical readings from all three copies.
    centers=[20+n*(clean.width+20) for n in range(3)]
    factor=min(3,3000/canvas.width)
    texts=[_text(result['words'],(x*factor,0,(x+clean.width)*factor,canvas.height*factor)).strip() for x in centers]
    return texts[0] if texts[0] and len(set(texts))==1 else ''

def roster_repair(draft, store):
    """Check header names against the daily-report roster (조별 명단); fix one-letter OCR slips.

    Only a unique roster name differing by one syllable replaces the OCR text (절룡 → 철룡).
    Duplicated names and names not on the roster stay as read and are reported for review.
    """
    from . import daily_report
    roster=daily_report.load_roster(Path(store))
    if draft.day:roster=daily_report.active(roster,draft.day)
    shorts=sorted({r['이름'][-2:] for r in roster}|{r['이름'] for r in roster})
    notes=[]
    for table in (draft.mapping,draft.extra_names):
        for key,name in list(table.items()):
            if not name or name in shorts:continue
            near=[s for s in shorts if len(s)==len(name) and sum(a!=b for a,b in zip(s,name))==1]
            if len(near)==1:
                table[key]=near[0];notes.append(f'{key} {name}→{near[0]}')
            else:draft.warnings.append(f'{key}번 이름 {name!r}이 조별 명단에 없습니다. 원본을 확인하세요.')
    if notes:draft.warnings.append('조별 명단과 대조해 이름을 고쳤습니다: '+', '.join(notes))
    seen={}
    for key,name in draft.mapping.items():
        if name:seen.setdefault(name,[]).append(key)
    for name,keys in seen.items():
        if len(keys)>1:draft.warnings.append(f'{"·".join(keys)}번 이름이 모두 “{name}”입니다. 원본 명단을 확인하세요.')
    return draft


def _ocr_cell(image, box):
    """OCR one cell alone on a white margin, enlarged (header names the full-page pass missed)."""
    x0,y0,x1,y1=map(round,box)
    crop=image.crop((x0+3,y0+3,x1-3,y1-3))
    for scale in (2,1):   # 3x enlargement distorts Hangul (원종 → 원羹); a wide white margin is what matters
        c=crop.resize((crop.width*scale,crop.height*scale),Image.LANCZOS)
        canvas=Image.new('RGB',(c.width+400,c.height+200),'white');canvas.paste(c,(200,100))
        b=BytesIO();canvas.save(b,'PNG')
        _,result=image_ocr(b.getvalue(),clean=False)
        text=''.join(w['text'] for w in sorted(result['words'],key=lambda w:w['x']))
        if re.fullmatch(r'(\d{1,2}|CP[123I]|통제)[가-힣A-E]{1,4}',normalize_cell(text)):return text
    return ''


AUX_COLUMNS ={'CP','셔틀','4C','1C'}   # auxiliary posts: the same person may also appear in a main column


def _read_single_glyphs(image, rows, pending, boxes, warnings):
    """Second, independent reading for one-glyph cells OCR dropped: glyph shape + per-hour headcount.

    Accept only a clear shape match whose label is a person on this table and, in a main column,
    not already counted elsewhere in that hour. Otherwise the cell stays '확인 필요'.
    """
    from . import glyph_read
    local={}
    for (t,col),box in boxes.items():
        text=normalize_cell(rows[t].get(col,''))
        if text in glyph_read.LABELS:
            shape=glyph_read.glyph(image,box)
            if shape is not None:local.setdefault(text,[]).append(shape)
    tokens=set()
    for row in rows:
        for col,text in row.items():
            if col=='시간' or text==UNKNOWN:continue
            try:tokens.update(persons(text))
            except ValueError:pass
    filled=[]
    for t,col,box in pending:
        shape=glyph_read.glyph(image,box)
        if shape is None:continue
        label,score,second=glyph_read.classify(shape,local)
        if not glyph_read.confident(label,score,second) or label not in tokens:continue
        if col not in AUX_COLUMNS:
            hour=set()
            for other,text in rows[t].items():
                if other in ('시간',col) or other in AUX_COLUMNS or text==UNKNOWN:continue
                try:hour.update(persons(text))
                except ValueError:pass
            if label in hour:continue
        rows[t][col]=label;filled.append(f'{rows[t]["시간"]} {col}={label}')
    if filled:warnings.append('한 글자 칸을 글자 모양·시간별 인원으로 읽었습니다: '+', '.join(filled))
    return filled


def normalize_cell(text):
    s=text.strip().upper().replace('•','.').replace('·','.').replace(',','.')
    s=re.sub(r'CP[IL](?![A-Z])','CP1',s)
    s=re.sub(r'(?<![A-Z])[IL](?![A-Z])','1',s)
    return s.replace(' ', '')

def persons(text):
    """Strict display tokens; remove CP/education/shuttle annotations, reject remaining garbage."""
    if text == UNKNOWN:raise ValueError('아직 확인하지 않은 칸이 있습니다.')
    s=normalize_cell(text)
    s=re.sub(r'^교육[:：]?','',s)
    s=re.sub(r'CP[123]','',s)
    s=re.sub(r'\((?:설치|해지|해자)\)','',s)
    parts=[v for v in re.split(r'[./;:]+',s) if v]
    if any(not re.fullmatch(r'[A-E]|[1-9]|1[0-9]|20',v) for v in parts):
        raise ValueError(f'배정 {text!r}을 읽을 수 없습니다. 번호를 점(.)으로 구분해 수정하세요.')
    return parts

def parse_image(data):
    image,result=image_ocr(data,clean=False)
    words=result['words'];width,height=image.size
    clocks=[(w,_clock(w['text'])) for w in words if w['x'] < width*.13 and _clock(w['text']) is not None]
    day,kind=classify(result['text'],[h for _,h in clocks])
    shift='night' if kind=='night' else 'day'
    expected=list(range(18,24))+list(range(8)) if shift=='night' else list(range(8,18))
    clocks=[(w,h) for w,h in clocks if h in expected]
    if len(clocks)<3:raise ValueError('시간 열을 충분히 읽지 못했습니다. 시간 열이 잘렸거나 글자가 흐립니다. 표 전체 원본을 올려주세요.')
    clocks.sort(key=lambda v:v[0]['y'])
    rgb=np.asarray(image)
    # Resized screenshots antialias one-pixel rules into gray; retain these grid lines.
    black=rgb.max(axis=2)<160
    horizontal=_centers(np.flatnonzero(black.mean(axis=1)>.65))
    first_y=clocks[0][0]['y']+clocks[0][0]['h']/2
    above=[y for y in horizontal if y<first_y]
    if len(above)<2:raise ValueError('표 구조를 지원하지 않습니다. 머리글과 가로 테두리가 포함된 평면 표를 올려주세요.')
    top=max(above);header_top=above[-2]
    vertical=_centers(np.flatnonzero(black[round(header_top)+3:round(top)-3].mean(axis=0)>.8))
    if vertical and vertical[0]>width*.025:vertical.insert(0,0)
    if vertical and vertical[-1]<width*.98:vertical.append(width-1)
    if len(vertical)<7:raise ValueError('표의 열을 구분하지 못했습니다. 테두리가 잘렸거나 기울어진 사진은 표 전체가 수평으로 보이게 올려주세요.')
    headers=[]
    for a,b in zip(vertical,vertical[1:]):
        s=normalize_cell(_text(words,(a,header_top,b,top)))
        headers.append(ALIASES.get(s,s))
    known=sum(h in DAY_COLUMNS+NIGHT_COLUMNS for h in headers)
    template=DAY_COLUMNS if shift=='day' and len(headers)==15 else NIGHT_COLUMNS if shift=='night' and len(headers)==13 else None
    if template and known>=5:
        # Positional repair is restricted to a recognized supplied layout; unknown labels are shown as a warning.
        recognized=[h for h in headers[1:] if h in template]
        if any(h!=template[i] for i,h in enumerate(headers[1:]) if h in template):
            raise ValueError('열 순서가 지원 양식과 다릅니다. 머리글을 읽을 수 있는 원본으로 올려주세요.')
        columns=template
    else:
        columns=headers[1:]
        if not {'G1','순찰'}.issubset(columns) or known<4:
            raise ValueError('지원하지 않는 표 구조입니다. 근무 포스트 머리글과 시간 열이 포함된 표가 필요합니다.')
    warnings=[]
    if template and headers[1:]!=template:warnings.append('일부 머리글은 기준 양식의 열 위치로 연결했습니다. 원본의 열 순서를 확인하세요.')
    # Extract roster by visible header cells, rather than a hard-coded current team.
    mapping={};controls=set();extra_names={}
    name_lines=[y for y in horizontal if y<header_top]
    name_start=name_lines[-3] if len(name_lines)>=3 else 0
    name_words=[w for w in words if name_start < w['y'] < header_top]
    texts=[w['text'] for w in name_words]
    # Name cells with ink but no OCR word (e.g. '4원종' on 10/8): read that cell alone, enlarged.
    bands=[y for y in horizontal if name_start<=y<=header_top]
    for y0,y1 in zip(bands,bands[1:]):
        for x0,x1 in zip(vertical[1:],vertical[2:]):
            box=(x0,y0,x1,y1)
            if y1-y0>8 and not _text(words,box).strip() and _ink(image,box):texts.append(_ocr_cell(image,box))
    for text in texts:
        s=normalize_cell(text)
        m=re.fullmatch(r'(\d{1,2})([가-힣]{2,4})',s)
        if m:mapping[m[1]]=m[2]
        m=re.fullmatch(r'(CP[123])([가-힣]{2,4})',s.replace('CPI','CP1'))
        if m:extra_names[m[1]]=m[2]
        m=re.fullmatch(r'통제([A-E0])',s)
        if m and m[1]=='0':controls.add('D');continue   # OCR reads the D of 통제D as 0
        if m:controls.add(m[1])
    header_text=_text(words,(0,0,width,header_top))
    team_match=re.search(r'([A-D])\s*조',header_text.upper())
    team=team_match[1] if team_match else ''
    body=[y for y in horizontal if y>=top]
    if len(body)<len(expected)+1:raise ValueError('시간표의 가로 테두리가 부족합니다. 표 하단까지 포함한 원본이 필요합니다.')
    body=body[:len(expected)+1]
    hour_by_row={}
    for w,h in clocks:
        cy=w['y']+w['h']/2
        for t,(a,b) in enumerate(zip(body,body[1:])):
            if a<cy<b:hour_by_row[t]=h
    if any(h!=expected[t] for t,h in hour_by_row.items()):
        raise ValueError('시간 행 순서가 표준 주간·야간 시간대와 다릅니다. 시간 열을 확인하세요.')
    rows=[];retry=[]
    for t,h in enumerate(expected):
        row={'시간':f'{h:02d}:00'}
        if t not in hour_by_row:row['시간']=UNKNOWN;warnings.append(f'{h:02d}시 시간 글자를 못 읽었습니다. 해당 행의 시간을 확인하세요.')
        for col,(x0,x1) in zip(columns,zip(vertical[1:],vertical[2:])):
            box=(x0,body[t],x1,body[t+1])
            text=_text(words,box).strip()
            if not text and _ink(image,box):retry.append((t,col,box));text=UNKNOWN
            row[col]=text
        rows.append(row)
    # Retry observed ink only; genuine empty cells remain empty.
    from concurrent.futures import ThreadPoolExecutor
    with ThreadPoolExecutor(max_workers=4) as pool:
        for (t,col,_),text in zip(retry,pool.map(lambda item:_reread(image,item[2]),retry)):
            if text:rows[t][col]=text
    _read_single_glyphs(image,rows,[(t,col,box) for t,col,box in retry if rows[t][col]==UNKNOWN],
                        {(t,col):(x0,body[t],x1,body[t+1]) for t in range(len(expected))
                         for col,(x0,x1) in zip(columns,zip(vertical[1:],vertical[2:]))},warnings)
    # 교육 rows span the standby/rest columns in the supplied weekday sheet.
    for row in rows:
        if re.fullmatch(r'교육[:：]?',normalize_cell(row.get('대기',''))) and row.get('휴게'):
            row['휴게']='교육: '+row['휴게'];row['대기']=''
    seen=set(mapping)
    for row in rows:
        for col,text in list(row.items()):
            if col=='시간':continue
            if text==UNKNOWN:continue
            try:
                found=persons(text)
                seen.update(p for p in found if p.isdigit())
            except ValueError:
                row[col]=UNKNOWN;warnings.append(f'{row["시간"]} {col}: 문자 {text!r}을 확실히 해석하지 못했습니다.')
    mapping={p:mapping.get(p,'') for p in sorted(seen,key=int)}
    if not mapping:raise ValueError('번호별 명단과 시간별 배정을 읽지 못했습니다. 글자 인식이 부족하므로 더 큰 원본이 필요합니다.')
    if any(not n for n in mapping.values()):warnings.append('이름을 못 읽은 번호는 직접 입력해야 저장할 수 있습니다.')
    if not day:warnings.append('날짜 미확인: 원본 날짜를 직접 입력하세요.')
    if not team:warnings.append('근무조 미확인: 원본의 근무조를 직접 선택하세요.')
    warnings += [f'{r["시간"]} {c}: 확인 필요' for r in rows for c,v in r.items() if v==UNKNOWN]
    return ImageDraft(day,kind,team,mapping,sorted(controls),rows,warnings,hashlib.sha256(data).hexdigest(),
                      f'제목·시간대: {shift} / 날짜: {day or "미확인"} / 시간 행 {len(hour_by_row)}/{len(expected)}',extra_names)

def build_day(day, rows, mapping, kind='day', statuses=None, newcomers=(), shapes=None, fill_gaps=None):
    """shapes = {번호: {'leave_from'|'join_from': 슬롯}} (일찍 퇴근·늦게 출근), fill_gaps = 목록을 주면 근무 가능
    시간의 빈칸을 휴게로 채우고 그 내용을 목록에 적는다(엑셀 일괄 가져오기용, 2026-10-11). 이미지 업로드는 그대로 엄격."""
    from .day_shift import DayPerson,DaySchedule,POSTS
    if not mapping or any(not re.fullmatch(r'[가-힣A-Za-z ]{2,20}',n.strip()) for n in mapping.values()):
        raise ValueError('번호별 이름을 모두 확인하고 입력하세요.')
    if len(set(mapping.values()))!=len(mapping):raise ValueError('같은 이름이 두 번호에 연결돼 있습니다. 번호별 직원을 확인하세요.')
    expected=list(range(8,18))
    if len(rows)!=10 or [_clock(r['시간']) for r in rows]!=expected:raise ValueError('08~17시 10개 시간 행을 확인하세요.')
    grid={p:[None]*10 for p in mapping};shuttle={};fill={};patrol=None;patrols=[];controls=[];ancillary=set();ancillary_at=set()
    core=set(POSTS)|{'I1','L3','순찰','대기','휴게','보안실'}
    for t,row in enumerate(rows):
        assigned={}
        for post,text in row.items():
            if post=='시간':continue
            tokens=persons(text)
            for p in tokens:
                if p.isdigit() and p not in mapping:raise ValueError(f'{row["시간"]} {post}: {p}번 이름을 확인하세요.')
                if post=='셔틀':
                    if p in grid:shuttle[t]=mapping[p]
                    continue
                if post in ('4C','1C','CP'):
                    ancillary.add(p);ancillary_at.add((p,t))
                    continue # Original ancillary assignments are kept in source_review, never treated as rest.
                if post not in core:raise ValueError(f'지원하지 않는 포스트 {post!r}입니다. 원본 머리글을 확인하세요.')
                label='교육' if normalize_cell(text).startswith('교육') else '대기' if post=='보안실' else post
                if p in 'ABCDE':
                    controls.append(p)
                    if post=='순찰' and p=='A':
                        patrol=t;patrols.append(t)
                    elif post in POSTS:fill.setdefault(t,{})[post]=p
                    continue
                if p in assigned:
                    if post=='휴게':continue # User rule: every day/night work or patrol beats rest.
                    if assigned[p]!='휴게':raise ValueError(f'{row["시간"]} {mapping[p]}: {assigned[p]}·{post} 중복 배정입니다. 실제 수행한 칸을 확인하세요.')
                assigned[p]=post;grid[p][t]=label
    active={p for p,row in grid.items() if any(v is not None for v in row)}
    active={p for p in active if p not in ancillary or any(v in (*POSTS,'순찰','대기') for v in grid[p])}
    statuses=statuses or {p:'출근' for p in active}
    from .day_shift import slots_of
    people=[];name_grid={}
    for p in sorted(active,key=int):
        status=statuses.get(p,'출근');person=DayPerson(mapping[p],mapping[p],status,int(p),**(shapes or {}).get(p,{}))
        for t in range(10):
            if t not in slots_of(person):
                if grid[p][t] is not None:raise ValueError(f'{mapping[p]}: {t+8}시 배정과 출근 상태가 서로 다릅니다.')
            elif grid[p][t] is None:
                if fill_gaps is None:raise ValueError(f'{t+8:02d}시 {mapping[p]} 배정을 읽지 못했습니다. 휴게·근무불가 여부를 직접 확인하세요.')
                if (p,t) in ancillary_at:      # 4C 'A.9' = A와 9번이 같이 4C 근무. 주간 집계엔 4C 칸이 없어 교육(동행)으로 셈
                    grid[p][t]='교육';fill_gaps.append(f'{t+8:02d}시 {mapping[p]}: A와 같이 4C 근무(원본 칸 그대로, 집계는 교육 동행)')
                else:
                    grid[p][t]='휴게';fill_gaps.append(f'{t+8:02d}시 {mapping[p]}: 표에 없어 휴게로 둠')
        people.append(person);name_grid[mapping[p]]=grid[p]
    if kind=='weekend_day':
        from .weekend_day import WeekendSchedule,LABELS
        if 'A' not in controls:raise ValueError('휴일 주간 통제A의 시간별 배정을 확인하세요.')
        manager=[]
        for row in rows:
            hits=[p for p,v in row.items() if p in core and 'A' in persons(v)]
            if len(hits)>1 and '휴게' in hits:hits.remove('휴게')
            if not hits and fill_gaps is not None:   # 엑셀 일괄: 어느 칸에도 없으면 휴게 (포스트 먼저, 2026-10-11)
                hits=['휴게'];fill_gaps.append(f'{row["시간"][:2]}시 통제A: 표에 없어 휴게로 둠')
            if len(hits)!=1:raise ValueError(f'{row["시간"]} 통제A 배정을 확인하세요.')
            manager.append('휴게' if hits[0] in ('대기','보안실') else hits[0])
        weekend_grid={p:['휴게' if x in ('대기','교육') else '×' if x is None else x for x in grid[p]] for p in active}
        weekend_grid['A']=manager
        if any(x not in (*LABELS,'×') for r in weekend_grid.values() for x in r):raise ValueError('휴일 주간 포스트가 현재 저장 양식과 다릅니다. G1·G2·I1·L1·순찰·휴게 표를 확인하세요.')
        return WeekendSchedule(str(day),{'A':'통제A',**{p:mapping[p] for p in active}},weekend_grid,
                               half_days={p:s for p,s in statuses.items() if '반차' in s},rule_exempt_names=tuple(mapping[p] for p in newcomers))
    return DaySchedule(day,tuple(people),name_grid,shuttle,'image', 'A' in controls,patrol,fill=fill,control_patrol_slots=tuple(patrols),rule_exempt_names=tuple(mapping[p] for p in newcomers),source_layout={"mapping":dict(mapping),"rows":apply_rest_priority(rows)})

def save_day_image(store, schedule, draft, rows, mapping, data, filename, expected=None, team='', statuses=None):
    """Atomic final save, original backup and stale-review protection; source rows are lossless."""
    from .day_shift import to_json
    kind=draft.kind
    day=schedule.day if isinstance(schedule.day,date) else date.fromisoformat(schedule.day)
    store=Path(store);store.mkdir(parents=True,exist_ok=True)
    if fingerprint(store,day)!=expected:raise ValueError('확인 중 기존 저장본이 바뀌었습니다. 파일을 다시 분석하세요.')
    payload=asdict(schedule) if kind=='weekend_day' else to_json(schedule)
    if kind=='day':payload['source_layout']={'mapping':dict(mapping),'rows':apply_rest_priority(rows),'extra_names':draft.extra_names}
    payload.update(source='image-import',source_file=filename,source_hash=hashlib.sha256(data).hexdigest(),
                   final_save_method='upload',confirmed_at=datetime.now().isoformat(timespec='seconds'),
                   note='이미지 원본 대조 확인 후 저장. 자동 추정 없음.',
                   source_review={'kind':kind,'team':team,'mapping':mapping,'rows':rows,'controls':draft.controls,
                                  'extra_names':draft.extra_names})
    payload['source_review']['applied_rows']=apply_rest_priority(rows)
    payload['source_review']['statuses']=statuses or {}
    payload['source_review']['newcomers']=list(getattr(schedule,'rule_exempt_names',()))
    if kind=='weekend_day':
        from .weekend_day import validate
        payload['import_rule_warnings']=validate(schedule)
    else:
        from .day_shift import validate_day
        payload['import_rule_warnings']=validate_day(schedule)
    payload['source_review']['rest_priority_notes']=rest_priority_notes(rows,mapping)
    path=store/f'{day}.json'
    from .import_compare import identical,mark_overwrite
    if identical(path,payload):return path
    mark_overwrite(path,payload)
    from .source_attachment import stash
    payload["source_attachment"]=stash(store,data,filename)
    # Preserve exact control/ancillary/CP cells separately from the scheduler's core posts.
    payload['source_image']=payload['source_attachment']
    path=store/f'{day}.json';fd,tmp=tempfile.mkstemp(prefix='.image-',suffix='.tmp',dir=store)
    try:
        with os.fdopen(fd,'w',encoding='utf-8') as f:json.dump(payload,f,ensure_ascii=False,indent=1)
        if fingerprint(store,day)!=expected:raise ValueError('저장 직전 기존 기록이 변경됐습니다. 파일을 다시 분석하세요.')
        if path.exists():
            trash=store/'.trash';trash.mkdir(exist_ok=True)
            shutil.copy2(path,trash/f'{day}__deleted-image-{datetime.now():%Y%m%d-%H%M%S%f}.json')
        os.replace(tmp,path)
    finally:Path(tmp).unlink(missing_ok=True)
    return path

def build_night(day,rows,mapping,mode,off=(),newcomers=()):
    """Review raw cells before converting to the existing night store schema."""
    from . import history_import as imp
    from .models import BARRIER_SINGLE_FROM, BARRIER_V2_FROM, Mode
    expected=[f'{h:02d}:00' for h in list(range(18,24))+list(range(8))]
    if [r['시간'] for r in rows]!=expected:raise ValueError('18~07시의 14개 시간 행을 확인하세요.')
    names={'A':'통제A',**mapping}
    if any(not v.strip() for v in names.values()):raise ValueError('번호별 이름을 모두 입력하세요.')
    if len(set(names.values()))!=len(names):raise ValueError('번호별 이름이 중복됩니다.')
    if newcomers:
        rows=[{col:(value if col in ('시간','CP') else '.'.join(p for p in re.findall(r'CP[123]|[A-E]|[0-9]+',normalize_cell(value)) if p not in newcomers)) for col,value in row.items()} for row in rows]
        mapping={p:n for p,n in mapping.items() if p not in newcomers}
        names={p:n for p,n in names.items() if p not in newcomers}
        off=[p for p in off if p not in newcomers]
    # Stable existing identities are resolved from confirmed names only.
    stable={v:k for k,v in imp.ROSTER.items()}
    if any(v not in stable for v in names.values()):raise ValueError('이름이 현재 야간 직원 명단과 다릅니다. 번호별 실제 이름을 확인하세요.')
    grids={p:[] for p in names}
    for t,row in enumerate(rows):
        assignments={}
        for post,value in row.items():
            if post in ('시간','CP','셔틀'):continue
            found=persons(value)
            for p in found:
                if p not in names:raise ValueError(f'{row["시간"]} {post}: {p}번 이름을 확인하세요.')
                label=imp.PATROLS.get(t,UNKNOWN) if post=='순찰' else '보안실 대기' if post in ('보안실','대기') else post
                if p in assignments:
                    if post=='휴게':continue
                    if assignments[p]!='휴게':raise ValueError(f'{row["시간"]} {p}: 중복 근무 배정을 수정하세요.')
                assignments[p]=label
        for p in names:
            if p in off:
                if p in assignments:raise ValueError(f'{row["시간"]} {names[p]}: 근무불가 상태와 표 배정이 다릅니다.')
                grids[p].append('근무불가')
            elif p not in assignments:raise ValueError(f'{row["시간"]} {names[p]} 배정이 비어 있습니다. 휴게 또는 근무불가를 직접 확인하세요.')
            else:grids[p].append(assignments[p])
    standby=lambda t:[p for p,g in grids.items() if g[t]=='보안실 대기']
    post=lambda t,label:[p for p,g in grids.items() if g[t]==label]
    if day>=BARRIER_SINGLE_FROM:
        installers=post(2,'G2') or post(2,'I1');removers=post(10,'I1')
    elif day>=BARRIER_V2_FROM:
        installers=(post(2,'G2') or post(2,'I1'))+standby(2);removers=post(10,'I1')
    elif mode==Mode.FLEXIBLE:
        installers=(post(2,'G2') or post(2,'I1'))+standby(2);removers=post(10,'I1')
    else:installers=standby(2);removers=standby(10)
    return imp.build_import_record(day,mode,grids,{p:stable[n] for p,n in names.items()},imp.ROSTER,
                                   [(p,2) for p in installers],[(p,10) for p in removers])

def rest_priority_notes(rows,mapping):
    notes=[]
    for row in rows:
        try:rest=set(persons(row.get('휴게','')))|set(re.findall(r'CP[123]',normalize_cell(row.get('휴게',''))))
        except ValueError:continue
        for post,text in row.items():
            if post in ('시간','휴게','CP','셔틀'):continue
            try:overlap=rest.intersection(set(persons(text))|set(re.findall(r'CP[123]',normalize_cell(text))))
            except ValueError:continue
            for p in sorted(overlap):
                notes.append(f'{row["시간"]} {mapping.get(p,p)}: {post}·휴게 중복 → {post} 우선 적용')
    return notes

def apply_rest_priority(rows):
    """Interpreted table, including CP/ancillary posts. Original rows are never mutated."""
    result=[]
    for row in rows:
        row=dict(row);raw=row.get('휴게','')
        if raw and raw!=UNKNOWN:
            try:persons(raw)
            except ValueError:
                result.append(row);continue
            working=set()
            for post,value in row.items():
                if post in ('시간','휴게','셔틀') or value==UNKNOWN:continue
                try:working.update(persons(value))
                except ValueError:continue
                working.update(re.findall(r'CP[123]',normalize_cell(value)))
            s=normalize_cell(raw)
            tokens=re.findall(r'CP[123]|[A-E]|\d+',re.sub(r'^교육[:：]?','',s))
            keep=[p for p in tokens if p not in working]
            row['휴게']=('교육: ' if s.startswith('교육') else '')+'.'.join(keep)
        result.append(row)
    return result

def review_html(rows,mapping):
    columns=list(rows[0]);applied=apply_rest_priority(rows)
    parts=['<style>.dsheet{border-collapse:collapse;min-width:960px;width:100%;background:white;color:#111827;text-align:center;font-size:12px}.dsheet td,.dsheet th{border:1px solid #94a3b8;height:35px}.dsheet span{display:inline-block;padding:7px;background:#e0f2fe;border-radius:4px}</style><div style="overflow-x:auto"><table class="dsheet"><tr>']
    parts += [f'<th>{escape(c)}</th>' for c in columns];parts.append('</tr>')
    for t,row in enumerate(applied):
        parts.append('<tr>')
        for col in columns:
            value=row[col];parts.append('<td>')
            if col in ('G1','G2','G3','L1','L2','L3','I1','C1','C2','순찰','보안실','대기','휴게') and value!=UNKNOWN:
                try:tokens=persons(value)
                except ValueError:tokens=[]
                if tokens:
                    for p in tokens:parts.append(f'<span data-who="{escape(p)}" data-t="{t}" title="{escape(mapping.get(p,p))}">{escape(p)}</span> ')
                    cp='.'.join(re.findall(r'CP[123]',normalize_cell(value)))
                    if cp:parts.append(escape(cp))
                else:parts.append(escape(value))
            else:parts.append(escape(value))
            parts.append('</td>')
        parts.append('</tr>')
    parts.append('</table></div>');return ''.join(parts)

def swap_review(rows,a,b):
    p,t=str(a[0]),int(a[1]);q,u=str(b[0]),int(b[1])
    if t!=u or not 0<=t<len(rows):raise ValueError('같은 시간의 근무자끼리만 교환할 수 있습니다.')
    if p==q:return rows
    applied=apply_rest_priority(rows)
    core={'G1','G2','G3','L1','L2','L3','I1','C1','C2','순찰','보안실','대기','휴게'}
    for person in (p,q):
        found=[]
        for col,value in applied[t].items():
            if col not in core or value==UNKNOWN:continue
            try:
                if person in persons(value):found.append(col)
            except ValueError:continue
        if len(found)!=1:raise ValueError('읽지 못했거나 두 근무에 중복된 번호는 직접 입력으로 먼저 확인하세요.')
    output=[dict(r) for r in rows]
    for col,value in output[t].items():
        if col=='시간' or value==UNKNOWN:continue
        output[t][col]=re.sub(r'CP[123]|[A-E]|\d+',lambda m:q if m[0]==p else p if m[0]==q else m[0],value)
    return output
