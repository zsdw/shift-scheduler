import unittest
from streamlit.testing.v1 import AppTest


class OperationsSidebarTests(unittest.TestCase):
    def test_compact_sidebar_and_mode_switch(self):
        at = AppTest.from_string('''
import streamlit as st
import app
with st.sidebar:
    mode = st.radio("운영 모드", ("FM", "유도리"), horizontal=True)
    value = app.flexible_operations_input(st.sidebar) if mode == "유도리" else None
    st.selectbox("야간 유형", ["N1", "N2"])
st.write(repr(value))
''').run()
        self.assertFalse(at.exception)
        self.assertEqual(len(at.sidebar.expander), 0)
        at.sidebar.radio[0].set_value("유도리").run()
        self.assertFalse(at.exception)
        self.assertEqual(at.sidebar.expander[0].label, "유도리 포스트 운영")
        self.assertEqual(len(at.main.expander), 0)
        self.assertEqual(len(at.sidebar.dataframe), 0)
        self.assertEqual([s.label for s in at.sidebar.selectbox][:4], ["포스트", "시작", "운영", "끝"])
        self.assertTrue(any("룰북 기본" in c.value for c in at.sidebar.caption))
        at.sidebar.selectbox[1].set_value("23시").run()
        self.assertIn("('I1', 5, 9, 'rest')", at.main.markdown[0].value)
        at.sidebar.button[1].click().run()
        self.assertEqual(len(at.sidebar.selectbox), 9)
        at.sidebar.button[1].click().run()
        self.assertEqual(len(at.sidebar.selectbox), 5)
        at.sidebar.radio[0].set_value("FM").run()
        self.assertFalse(at.exception)
        self.assertEqual(len(at.sidebar.expander), 0)
        at.sidebar.radio[0].set_value("유도리").run()
        self.assertEqual(at.sidebar.selectbox[1].value, "23시")


if __name__ == "__main__":
    unittest.main()
