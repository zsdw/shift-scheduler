const fs = require('fs');
const path = require('path');
const {chromium} = require(path.join(process.env.USERPROFILE,'.cache/codex-runtimes/codex-primary-runtime/dependencies/node/node_modules/playwright'));
const assert = require('assert');
(async () => {
  const browser = await chromium.launch({headless:true,channel:'msedge'});
  try {
    for (const kind of ['day_grid','drag_grid']) {
      const page = await browser.newPage({viewport:{width:412,height:850},hasTouch:true,isMobile:true});
      await page.setContent(fs.readFileSync(path.join(__dirname,'../night_shift',kind,'index.html'),'utf8'));
      await page.evaluate(kind => {
        window.values=[];
        window.addEventListener('message',e=>{if(e.data.type==='streamlit:setComponentValue')window.values.push(e.data.value)});
        const data = kind==='day_grid' ? {edit:true,html:`<table class="dsheet"><tr><td class="name" data-who="1">1번</td><td class="name" data-who="2">2번</td></tr><tr><td><span data-who="1" data-t="1">1</span></td><td><span data-who="2" data-t="1">2</span></td><td><span data-who="3" data-t="2">3</span></td></tr></table>`} : {hours:['18시','19시'],tap_swap:true,rows:['1','2','3'].map((id,i)=>({id,label:id,movable:true,cells:[{t:i===2?2:1,label:'G1',color:'FFFFFF',movable:true}]}))};
        window.postMessage({type:'streamlit:render',args:{data}},'*');
      },kind);
      await page.waitForSelector('[draggable="true"][data-t]');
      async function gesture(target,cancel=false) {
        await page.evaluate(async ({target,cancel,kind})=>{
          const els=[...document.querySelectorAll(kind==='day_grid'?'[draggable="true"][data-t]':'td[draggable="true"]')];
          const a=els[0],b=els[target];
          // Dispatch real pointer event handlers; replace capture only because synthetic pointers are not active hardware pointers.
          a.setPointerCapture=()=>{};
          const rect=x=>x.getBoundingClientRect();
          const ar=rect(a),br=rect(b),x=br.x+br.width/2,y=br.y+br.height/2;
          const event=(name,cx,cy)=>new PointerEvent(name,{bubbles:true,cancelable:true,pointerId:7,pointerType:'touch',isPrimary:true,clientX:cx,clientY:cy});
          a.dispatchEvent(event('pointerdown',ar.x+ar.width/2,ar.y+ar.height/2));
          await new Promise(resolve=>setTimeout(resolve,300));
          a.dispatchEvent(event('pointermove',x,y));
          a.dispatchEvent(event(cancel?'pointercancel':'pointerup',x,y));
          a.click(); b.click();
        },{target,cancel,kind});
        await page.waitForTimeout(30);
      }
      await gesture(1);
      let values=await page.evaluate(()=>window.values);
      assert.equal(values.length,1,'one swap, no duplicate click');
      assert.equal(values[0].kind,kind==='day_grid'?'swap':'cell');
      assert.deepEqual(kind==='day_grid'?values[0].a:values[0].source,['1',1]);
      assert.deepEqual(kind==='day_grid'?values[0].b:values[0].target,['2',1]);
      await gesture(2);
      assert.equal((await page.evaluate(()=>window.values)).length,1,'different hour refused');
      await gesture(1,true);
      assert.equal((await page.evaluate(()=>window.values)).length,1,'cancel does not swap');
      // 실제 기기와 같은 브라우저 터치 입력으로 포인터 캡처까지 확인한다.
      await page.waitForTimeout(550);
      const points=await page.evaluate(kind=>[...document.querySelectorAll(kind==='day_grid'?'[draggable="true"][data-t]':'td[draggable="true"]')].slice(0,2).map(el=>{const r=el.getBoundingClientRect();return {x:r.x+r.width/2,y:r.y+r.height/2}}),kind);
      const cdp=await page.context().newCDPSession(page);
      await cdp.send('Input.dispatchTouchEvent',{type:'touchStart',touchPoints:[points[0]]});
      await page.waitForTimeout(300);
      await cdp.send('Input.dispatchTouchEvent',{type:'touchMove',touchPoints:[points[1]]});
      await cdp.send('Input.dispatchTouchEvent',{type:'touchEnd',touchPoints:[]});
      await cdp.detach();
      await page.waitForTimeout(30);
      assert.equal((await page.evaluate(()=>window.values)).length,2,'browser touch input swaps once');
      if (kind==='day_grid') {   // 2026-10-07: 폰 이름 칸끼리 꾹 눌러 끌기 = 번호만 교환(rowswap)
        await page.waitForTimeout(550);
        const names=await page.evaluate(()=>[...document.querySelectorAll('td.name[data-who]')].slice(0,2).map(el=>{const r=el.getBoundingClientRect();return {x:r.x+r.width/2,y:r.y+r.height/2}}));
        const cdpn=await page.context().newCDPSession(page);
        await cdpn.send('Input.dispatchTouchEvent',{type:'touchStart',touchPoints:[names[0]]});
        await page.waitForTimeout(300);
        await cdpn.send('Input.dispatchTouchEvent',{type:'touchMove',touchPoints:[names[1]]});
        await cdpn.send('Input.dispatchTouchEvent',{type:'touchEnd',touchPoints:[]});
        await cdpn.detach();
        await page.waitForTimeout(30);
        const all=await page.evaluate(()=>window.values);
        assert.equal(all.length,3,'name touch drag emits once');
        assert.deepEqual([all[2].kind,all[2].a,all[2].b],['rowswap','1','2']);
        await page.evaluate(()=>window.values.pop());
      }
      // 2026-10-06: 표 안 번호 칸을 짚자마자 밀면 화면이 스크롤되고 교환은 없음 (꾹 누르기 전에는 스크롤)
      assert.equal(await page.evaluate(kind=>getComputedStyle(document.querySelector(kind==='day_grid'?'[draggable="true"][data-t]':'td[draggable="true"]')).touchAction,kind),'pan-x pan-y','draggable cells allow panning');
      await page.evaluate(()=>{document.body.style.paddingBottom='3000px';window.scrollTo(0,0)});
      const cdp2=await page.context().newCDPSession(page);
      const p=points[0];
      await cdp2.send('Input.dispatchTouchEvent',{type:'touchStart',touchPoints:[p]});
      for (let i=1;i<=6;i++) await cdp2.send('Input.dispatchTouchEvent',{type:'touchMove',touchPoints:[{x:p.x,y:p.y-30*i}]});
      await cdp2.send('Input.dispatchTouchEvent',{type:'touchEnd',touchPoints:[]});
      await cdp2.detach();
      await page.waitForTimeout(300);
      assert.ok(await page.evaluate(()=>window.scrollY)>0,'quick swipe on a cell scrolls the page');
      assert.equal((await page.evaluate(()=>window.values)).length,2,'quick swipe does not swap');
      await page.evaluate(()=>{document.querySelector('[draggable="true"][data-t]').removeAttribute('draggable')});
      assert.equal(await page.locator('.dragging,.over').count(),0,'drag feedback cleared');
      console.log(kind+': 같은 시간 교환·다른 시간 거절·취소·중복 클릭 방지 통과');
      if (kind === 'drag_grid') {
        for (const compact of [false, true]) {
          await page.evaluate(compact => {
            const data = {compact, band:[4,10], hours:Array.from({length:14},(_,t)=>String((18+t)%24).padStart(2,'0')+':00'),
              sheet:{operations:{G1:Array(14).fill(null),I1:Array.from({length:14},(_,t)=>t>=4&&t<=9?'rest':null)},title:'야간 근무 편성표',sub:'검사',heads:[['1','1이름']],tokens:{'1':'1'},colors:{'1':'70AD47'},cp:[],shuttle:[]},
              rows:[{id:'1',label:'1이름',movable:true,cells:Array.from({length:14},(_,t)=>({t,label:'G1',color:'70AD47',movable:true}))}]};
            window.postMessage({type:'streamlit:render',args:{data}},'*');
          },compact);
          await page.waitForSelector('table.sheet td.op-start');
          assert.equal(await page.locator('td.op-band').count(),12,'post-specific ranges include empty post cells');
          assert.equal(await page.locator('td.op-start').count(),2,'each post has a top edge');
          assert.equal(await page.locator('td.op-end').count(),2,'each post has a bottom edge');
          assert.equal(await page.locator('td.op-start').first().evaluate(el=>getComputedStyle(el).borderTopWidth),'4px');   // 2026-10-13 자홍색 4px
          assert.ok((await page.locator('.legend').allTextContents()).join(' ').includes('I1 휴게성 22:00~03:00'));
          assert.equal(await page.locator('th.hour.bandh').count(),0,'no time labels marked');
          assert.equal(await page.locator('th.hour.band-start').count(),0,'no time top edge');
          assert.equal(await page.locator('th.hour.band-end').count(),0,'no time bottom edge');
          assert.equal(await page.locator('.pc.band-l,.pc.band-r,.pc.band-t,.pc.band-b').count(),0,'no flexible borders inside duty cells');
          assert.equal(await page.locator('td.op-start').first().evaluate(el=>getComputedStyle(el).borderTopWidth),'4px');   // 2026-10-13 자홍색 4px
          assert.equal(await page.locator('td.op-end').first().evaluate(el=>getComputedStyle(el).borderBottomWidth),'4px');
        }
        console.log('PC·폰: 유도리 시간 열 사각 테두리·근무 칸 내부 표시 제거 통과');
      }
      await page.close();
    }
  } finally {await browser.close()}
})().catch(e=>{console.error(e);process.exit(1)});
