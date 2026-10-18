"""CP 월간 이미지의 날짜 열·이름 행을 OCR 위치로 읽고 확인표로 전달한다."""
import re
from statistics import median
from .history_import import image_ocr

def parse_image(data):
    image,result=image_ocr(data,clean=False)
    words=result['words']
    text=result.get('text','')
    month_match=re.search(r'(?:CP\s*)?(\d{1,2})\s*월',text,re.I)
    month=int(month_match[1]) if month_match and 1<=int(month_match[1])<=12 else None
    numeric=[w for w in words if re.fullmatch(r'\d{1,2}',w['text'].strip()) and 1<=int(w['text'])<=31]
    bands=[]
    for w in sorted(numeric,key=lambda w:w['y']):
        cy=w['y']+w['h']/2
        band=next((b for b in bands if abs(b[0]-cy)<max(w['h'],8)),None)
        if band is None:bands.append([cy,[w]])
        else:band[1].append(w)
    candidates=[]
    for y,group in bands:
        ordered=sorted(group,key=lambda w:w['x'])
        days=[int(w['text']) for w in ordered]
        if len(days)>=20 and days==sorted(set(days)) and days[0]<=10 and days[-1]>=28:
            candidates.append((y,ordered))
    if not candidates:raise ValueError('월간 표의 날짜 1~말일 줄을 읽지 못했습니다. 날짜와 이름이 포함된 표 전체 이미지를 올려주세요.')
    header,dates=max(candidates,key=lambda b:len(b[1]))
    step=median([(b['x']+b['w']/2-a['x']-a['w']/2)/(int(b['text'])-int(a['text'])) for a,b in zip(dates,dates[1:])])
    origin=median([w['x']+w['w']/2-(int(w['text'])-1)*step for w in dates])
    columns={d:origin+(d-1)*step for d in range(1,max(int(w['text']) for w in dates)+1)}
    left=origin-step/2
    name_words=[w for w in words if w['y']>header and w['x']+w['w']/2<left
                and re.fullmatch(r'[가-힣]{2,4}',w['text'].strip()) and not w['text'].strip().endswith('조')
                and w['text'].strip() not in ('성명','이름','근무','주간','야간','연차','휴무','합계')]
    if not name_words:
        # 넓은 표에서 짧은 이름이 통째로 빠지는 Windows OCR: 이름 열을 따로 확대해 다시 읽는다.
        from io import BytesIO
        top=max(0,int(header+median(w['h'] for w in dates)))
        crop=image.crop((0,top,max(1,int(left)),image.height))
        buffer=BytesIO();crop.save(buffer,'PNG')
        enlarged,reread=image_ocr(buffer.getvalue())
        scale=enlarged.width/crop.width
        for w in reread['words']:
            if re.fullmatch(r'[가-힣]{2,4}',w['text'].strip()) and not w['text'].strip().endswith('조'):
                name_words.append({**w,'x':w['x']/scale,'y':top+w['y']/scale,'w':w['w']/scale,'h':w['h']/scale})
    if not name_words:raise ValueError('CP 근무자 이름을 읽지 못했습니다. 이름 열이 포함된 이미지를 올려주세요.')
    name_words.sort(key=lambda w:w['y'])
    height=median([b['y']-a['y'] for a,b in zip(name_words,name_words[1:])]) if len(name_words)>1 else name_words[0]['h']*2
    rows=[];warnings=[]
    from .daily_report import DEFAULT_ROSTER
    known=[p['이름'] for p in DEFAULT_ROSTER if p['직책']=='CP']
    for name in name_words:
        cy=name['y']+name['h']/2;row={'이름':name['text'].strip()}
        if not any(full==row['이름'] or full.endswith(row['이름']) for full in known):
            candidates=[full for full in known if len(full)==len(row['이름']) and sum(a!=b for a,b in zip(full,row['이름']))==1]
            warnings.append('이름 확인: '+row['이름']+(' (명단 후보: '+', '.join(candidates)+')' if candidates else ''))
        for day,x in columns.items():
            found=[w for w in words if abs(w['x']+w['w']/2-x)<step/2 and abs(w['y']+w['h']/2-cy)<height*.4]
            value=''.join(w['text'] for w in sorted(found,key=lambda w:w['x'])).replace(' ','')
            if not value:
                box=(max(0,int(x-step*.35)),max(0,int(cy-height*.28)),min(image.width,int(x+step*.35)),min(image.height,int(cy+height*.28)))
                crop=image.crop(box).convert('L')
                if crop.width and crop.height and sum(crop.histogram()[:110])/(crop.width*crop.height)>.025:
                    value='확인 필요'
            value=value.replace('주I','주1').replace('야I','야1')
            if value and not re.fullmatch(r'(주|야)[123]|연차|휴무|대휴|휴|병가|휴가|비번|[-—]',value):
                warnings.append(f'{row["이름"]} {day}일: {value} → 확인 필요')
                value='확인 필요'
            row[str(day)]=value
        rows.append(row)
    return {'month':month,'rows':rows,'days':list(columns),'warnings':warnings}

def entries_from_rows(year,month,rows):
    from .cp_schedule import parse_rows
    from calendar import monthrange
    people={}
    for row in rows:
        name=str(row.get('이름','')).strip()
        if not name:continue
        if name in people:raise ValueError(f'{name}: 이름이 중복됩니다.')
        if not re.fullmatch(r'[가-힣]{2,4}',name):raise ValueError('근무자 이름을 확인하세요: '+name)
        cells={}
        for key,value in row.items():
            if not str(key).isdigit():continue
            value='' if value is None else str(value).strip().replace(' ','')
            if int(key)>monthrange(year,month)[1]:
                if value:raise ValueError(f'{month}월에는 {key}일이 없습니다.')
                continue
            if value and not re.fullmatch(r'(주|야)[123]|연차|휴무|대휴|휴|병가|휴가|비번|[-—]',value):
                raise ValueError(f'{name} {key}일: 주1~3·야1~3·연차·휴무 또는 빈칸으로 확인하세요.')
            cells[int(key)]=value
        people[name]=cells
    if not people:raise ValueError('근무자가 없습니다.')
    return parse_rows(year,month,people)
