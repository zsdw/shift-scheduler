import unittest
from streamlit.testing.v1 import AppTest

SOURCE="""
import streamlit as st
from types import SimpleNamespace
from unittest.mock import patch
import app
initial=SimpleNamespace(record='initial', annotations=(), dual_spreads={'FM':0})
changed=SimpleNamespace(record='edited', annotations=('memo',), dual_spreads={'FM':1})
st.session_state.setdefault('schedule_results',[changed])
st.session_state.setdefault('generated_initial_results',{0:initial})
st.session_state.setdefault('generated_originals',{0:'initial'})
st.session_state.setdefault('selected_schedule_index',0)
with patch.object(app,'confirm_button',lambda result,key,**kw: st.button('✅ 이 근무표로 확정',key=key)):
    app.confirm_and_regenerate(st.session_state['schedule_results'][0],0,None,None,None)
app.hint_bar(('길게 눌러 근무 교환','이름 선택','규칙 위반이면 취소','빗금=LOCK'))
st.write(st.session_state['schedule_results'][0].record)
"""

class NightResetUITests(unittest.TestCase):
    def test_pc_mobile_restore_initial_and_button_position(self):
        for view in ('pc','mobile'):
            at=AppTest.from_string(SOURCE)
            at.query_params['view']=view
            at.run()
            self.assertFalse(at.exception)
            self.assertEqual([b.label for b in at.button],['✅ 이 근무표로 확정','↩ 초기 생성표로','🔁 근무표 재생성'])
            self.assertFalse(at.button[1].disabled)
            at.button[1].click().run()
            self.assertFalse(at.exception)
            restored=at.session_state['schedule_results'][0]
            self.assertEqual(restored.record,'initial')
            self.assertEqual(restored.annotations,())
            self.assertEqual(restored.dual_spreads,{'FM':0})
            self.assertNotIn(0,at.session_state['generated_originals'])
            self.assertTrue(at.button[1].disabled)
    def test_hint_wrap_and_spacing(self):
        at=AppTest.from_string(SOURCE).run()
        html=next(m.value for m in at.markdown if 'night-hints' in m.value)
        self.assertIn('display:flex',html)
        self.assertIn('flex-wrap:wrap',html)
        self.assertIn('padding-bottom:12px',html)
        self.assertIn('line-height:1.5',html)
