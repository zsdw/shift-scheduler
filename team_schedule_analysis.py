"""모든 조의 원문 배정을 룰북 회계로만 환산한다. 편성·검증·저장은 하지 않는다."""
from datetime import date,timedelta
import re
from night_shift.calendar_info import is_off_day

POSTS=('G1','G2','G3','G2(1)','G2(2)','L1','L2','L3','I1','C1','C2','4C','통제')
RESTS=('휴게','휴 게','보안실','보안실/대기','대기')


def normalize_source(source):
    def label(p):
        p=re.sub(r'\s+','',p)
        if p.startswith('I1('):return 'I1'
        if p=='보안실/대기':return '보안실'
        return p
    return {**source,'cells':{h:{label(p):v for p,v in row.items()} for h,row in source['cells'].items()}}


def tokens(value):
    return set(re.findall(r'CP\d+|[A-Z]|\d+',str(value or '').upper()))


def hours(source):
    return list(range(18,24))+list(range(8)) if source['shift']=='night' else list(range(8,18))


def people(source):
    found={str(k):v for k,v in source['names'].items()}
    for c in source.get('controls',[]):
        if any(c in tokens(v) for row in source['cells'].values() for v in row.values()):found[c]='통제'+c
    return found


def barrier_people(source):
    day=date.fromisoformat(source['day'])
    if source['shift']!='night':return set(),set()
    rows=source['cells']
    at=lambda h,p:tokens(rows.get(str(h),{}).get(p)) & people(source).keys()
    standby=lambda h:set().union(*(at(h,p) for p in RESTS[2:]))-set(source.get('controls',[]))
    from night_shift.models import BARRIER_SINGLE_FROM,BARRIER_V2_FROM
    if day>=BARRIER_SINGLE_FROM:
        return at(20,'G2') or at(20,'I1'),at(4,'I1')
    if day>=BARRIER_V2_FROM:
        return (at(20,'G2') or at(20,'I1'))|standby(20),at(4,'I1')
    return standby(20),standby(4)


def details(source,mode='FM'):
    source=normalize_source(source)
    day=date.fromisoformat(source['day']);night=source['shift']=='night';holiday=is_off_day(day)
    installs,removes=barrier_people(source)
    out=[]
    for token,name in people(source).items():
        for h in hours(source):
            cells=source['cells'].get(str(h),{})
            posts=[p for p in POSTS if token in tokens(cells.get(p))]
            patrol=token in tokens(cells.get('순찰'))
            floor=({21:'상층',22:'중층',23:'하층',1:'상층',2:'중층',3:'하층'} if night
                   else {9:'상층',10:'중층',11:'하층',14:'상층',15:'중층',16:'하층'}).get(h)
            if patrol and not night and not holiday:floor='하층'
            fatigue=standing=seated=patrol_score=work=0;explain=[];rest=False
            for p in posts:
                score=0;kind='입식'
                if night:
                    if p=='L3' and h==18 and token in source.get('controls',[]) and not holiday:kind='대기'
                    elif p=='I1':
                        kind='좌식'
                        if (h==18 and not holiday) or (h==7 and not is_off_day(day+timedelta(days=1))):kind='입식'
                        elif mode=='유도리' and h in (22,23,0,1,2,3):kind='휴게성'
                    elif p=='G1' and 0<=h<=4:kind='좌식'
                elif holiday:
                    if p=='I1':kind='좌식'
                    elif p in ('G2','G3') and mode=='유도리':kind='휴게성'
                    elif p not in ('G1','G2','G3','L1'):kind='집계외'
                else:
                    if p in ('C1','C2'):kind='좌식'
                    elif p not in ('G1','G2','G3','L1','L2'):kind='집계외'
                if kind=='입식':score=2;standing+=2;work=1
                elif kind=='좌식':score=1;seated+=1;work=1
                elif kind in ('대기','휴게성'):rest=True
                fatigue+=score;explain.append(f'{p} {kind} {score}점')
            if patrol:
                patrol_score=1 if floor=='하층' or (not night and not holiday) else 2
                fatigue+=patrol_score;work=1;explain.append(f'{floor or "순찰"} 순찰 {patrol_score}점')
            if not posts and not patrol:rest=any(token in tokens(cells.get(p)) for p in RESTS)
            barrier=(h==20 and token in installs) or (h==4 and token in removes)
            if barrier and not work:
                fatigue+=1;rest=False;explain.append('차단봉 단독 1점')
            rest=bool(rest and not work)
            standby=rest and (any(token in tokens(cells.get(p)) and not str(cells.get(p,'')).strip().startswith('교육') for p in RESTS[2:]) or
                (night and h==18 and 'L3' in posts and token in source.get('controls',[]) and not holiday))
            out.append({'번호':token,'근무자':name,'시간':f'{h:02}:00','시':h,
                        '표시': ' · '.join(posts+(['순찰'] if patrol else [])) or ('대기' if standby else '휴게' if rest else '—'),
                        '피로도':fatigue,'입식점수':standing,'좌식점수':seated,'순찰점수':patrol_score,
                        '실근무':work,'휴게':int(rest),'대기':int(standby),'순찰':int(patrol),
                        '층':floor if patrol else None,'설치':int(h==20 and token in installs),
                        '철수':int(h==4 and token in removes),
                        '계산': ' + '.join(explain) if explain else ('휴게·대기 0점' if rest else '미표기·집계외')})
    return out


def metrics(source,mode='FM'):
    all_rows=details(source,mode);out=[]
    for token,name in people(source).items():
        rows=[r for r in all_rows if r['번호']==token]
        row={'근무자':name,'근무횟수':1,**{k:sum(r[k] for r in rows) for k in ('피로도','실근무','휴게','대기','순찰')},
             '막휴게':int(bool(rows and rows[-1]['휴게'])),'대폭휴게':0,
             **{f:sum(r['층']==f for r in rows) for f in ('상층','중층','하층')},
             '차단봉 설치':sum(r['설치'] for r in rows) if source['shift']=='night' else None,
             '차단봉 철수':sum(r['철수'] for r in rows) if source['shift']=='night' else None}
        run=0
        for r in rows:
            run=run+1 if source['shift']=='night' and r['시'] in (23,0,1,2,3,4,5,6) and r['휴게'] else 0
            if run>=3:row['대폭휴게']=1
        out.append(row)
    return out


def totals(records,mode='FM'):
    found={}
    for source in records:
        for row in metrics(source,mode):
            name=row['근무자'];total=found.setdefault(name,{k:(name if k=='근무자' else None) for k in row})
            for k,v in row.items():
                if k!='근무자' and v is not None:total[k]=(total[k] or 0)+v
    return list(found.values())
