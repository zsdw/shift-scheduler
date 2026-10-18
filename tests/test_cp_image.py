import io,os,tempfile,unittest
from pathlib import Path
from datetime import date
from types import SimpleNamespace
from unittest.mock import patch
from PIL import Image,ImageDraw,ImageFont
from night_shift import cp_image,cp_schedule

def image_bytes():
    image=Image.new('RGB',(2400,340),'white');draw=ImageDraw.Draw(image)
    font=ImageFont.truetype(r'C:\Windows\Fonts\malgun.ttf',25)
    title=ImageFont.truetype(r'C:\Windows\Fonts\malgun.ttf',34)
    draw.text((250,10),'CP 10월 근무표',font=title,fill='black')
    for y in (80,130,190,250,310):draw.line((10,y,2380,y),fill='black',width=2)
    for x in [10,210]+[210+70*n for n in range(1,32)]:draw.line((x,80,x,310),fill='black',width=2)
    for day in range(1,32):draw.text((210+(day-1)*70+15,90),str(day),font=font,fill='black')
    for n,name in enumerate(('권혁준','이덕영','안철룡')):
        y=145+n*60;draw.text((50,y),name,font=font,fill='black')
        for day in range(1,32):draw.text((210+(day-1)*70+8,y),'야'+str(n+1),font=font,fill='black')
    out=io.BytesIO();image.save(out,'PNG');return out.getvalue()

class CpImageTests(unittest.TestCase):
    @unittest.skipUnless(os.name=='nt','Windows OCR integration')
    def test_real_monthly_image_ocr(self):
        draft=cp_image.parse_image(image_bytes())
        self.assertEqual(draft['month'],10)
        self.assertEqual(len(draft['rows']),3)
        self.assertEqual([r['이름'] for r in draft['rows'][:2]],['권혁준','이덕영'])
        if draft['rows'][2]['이름']!='안철룡':
            self.assertTrue(any('이름 확인' in warning for warning in draft['warnings']))
            draft['rows'][2]['이름']='안철룡'  # 확인표에서 원본과 대조해 이름 수정
        entries=cp_image.entries_from_rows(2026,10,draft['rows'])
        self.assertEqual(len(entries),31)
        self.assertEqual(entries['2026-10-31']['night'],{'1':'권혁준','2':'이덕영','3':'안철룡'})

    def test_geometry_and_bad_cells_require_confirmation(self):
        image=Image.new('RGB',(2400,340),'white')
        words=[{'text':str(d),'x':210+(d-1)*70+15,'y':90,'w':30,'h':25} for d in range(1,32)]
        words += [{'text':'권혁준','x':50,'y':145,'w':85,'h':25},{'text':'야1','x':218,'y':145,'w':45,'h':25},{'text':'야8','x':288,'y':145,'w':45,'h':25}]
        with patch.object(cp_image,'image_ocr',return_value=(image,{'words':words,'text':'CP 10월 근무표'})):
            draft=cp_image.parse_image(b'fake')
        self.assertEqual(draft['month'],10);self.assertEqual(draft['rows'][0]['1'],'야1')
        self.assertEqual(draft['rows'][0]['2'],'확인 필요')
        with self.assertRaises(ValueError):cp_image.entries_from_rows(2026,10,draft['rows'])
        draft['rows'][0]['2']='연차'
        self.assertEqual(cp_image.entries_from_rows(2026,10,draft['rows'])['2026-10-01']['night'],{'1':'권혁준'})

    def test_leave_image_upload_save_pc_mobile(self):
        from streamlit.testing.v1 import AppTest
        raw=image_bytes();draft={'month':10,'days':list(range(1,32)),'warnings':[],
            'rows':[{'이름':'권혁준',**{str(d):('야1' if d==10 else '') for d in range(1,32)}}]}
        for mobile in (False,True):
            with self.subTest(mobile=mobile),tempfile.TemporaryDirectory() as folder,patch.dict(os.environ,{'NIGHT_SHIFT_HISTORY_DIR':folder}),patch('mobile_ui.is_mobile',return_value=mobile),patch('streamlit.file_uploader',return_value=SimpleNamespace(name='cp.png',getvalue=lambda:raw)),patch.object(cp_image,'parse_image',return_value=draft):
                at=AppTest.from_string('from leave_view_ui import upload_box\nfrom history_ui import store_dir\nupload_box(store_dir(),"cp_photo")',default_timeout=30).run()
                self.assertFalse(at.exception,[e.value for e in at.exception])
                self.assertTrue(next(b for b in at.button if b.label=='CP 이미지 확인본 저장').disabled)
                at.checkbox[0].check().run()
                next(b for b in at.button if b.label=='CP 이미지 확인본 저장').click().run()
                self.assertFalse(at.exception,[e.value for e in at.exception])
                self.assertEqual(cp_schedule.for_day(Path(folder),date(2026,10,10),'night'),{'1':'권혁준'})

if __name__=='__main__':unittest.main()
