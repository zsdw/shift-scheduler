"""터치 드래그의 실제 화면 이벤트를 주간·야간 컴포넌트에서 검증한다."""
import os
from pathlib import Path
import subprocess
import unittest


class TouchDragTests(unittest.TestCase):
    def test_mobile_component_swaps(self):
        node = Path(os.environ['USERPROFILE']) / '.cache/codex-runtimes/codex-primary-runtime/dependencies/node/bin/node.exe'
        if not node.exists():
            self.skipTest('화면 자동 검사에 필요한 Node 실행 환경 없음')
        result = subprocess.run([str(node), str(Path(__file__).with_name('touch_drag_browser.cjs'))],
                                capture_output=True, text=True, encoding='utf-8', timeout=60)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)


if __name__ == '__main__':
    unittest.main()
