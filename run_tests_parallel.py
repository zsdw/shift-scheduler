"""전체 테스트를 파일별로 동시에 돌린다 (2026-10-04, 순서대로 돌리면 25~30분 → 병렬).

사용:  .venv\\Scripts\\python.exe run_tests_parallel.py            (동시 3개)
       .venv\\Scripts\\python.exe run_tests_parallel.py -j 4 test_day_shift.py test_mobile_ui.py

근무표 계산(OR-Tools)이 스레드를 많이 써서 동시에 너무 많이 돌리면 시간 제한 테스트가 흔들린다. 그래서
실패한 파일은 마지막에 혼자 다시 돌려, 다시 통과하면 '혼잡 때문(재실행 통과)'으로, 또 실패하면 진짜 실패로 보고한다.
로그는 logs/tests/<파일>.log 에 남는다.
"""
from __future__ import annotations

import argparse
import re
import subprocess
import sys
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

ROOT = Path(__file__).resolve().parent
LOGS = ROOT / "logs" / "tests"


def _last_seconds(name: str) -> float:
    try:
        m = re.findall(r"^Ran \d+ tests? in ([\d.]+)s", (LOGS / f"{name}.log").read_text(encoding="utf-8"), re.M)
        return float(m[-1]) if m else 0.0
    except OSError:
        return 0.0


def run_file(name: str) -> tuple[str, bool, int, float, str]:
    start = time.time()
    proc = subprocess.run([sys.executable, "-m", "unittest", "discover", "-s", "tests", "-p", name],
                          cwd=ROOT, capture_output=True, text=True, encoding="utf-8", errors="replace")
    out = proc.stdout + proc.stderr
    (LOGS / f"{name}.log").write_text(out, encoding="utf-8")
    m = re.search(r"^Ran (\d+) test", out, re.M)
    return name, proc.returncode == 0, int(m[1]) if m else 0, time.time() - start, out


def main() -> int:
    # Windows 백그라운드 리다이렉션에서도 결과 요약의 한글·구두점을 안전하게 출력한다.
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    parser = argparse.ArgumentParser()
    parser.add_argument("-j", "--jobs", type=int, default=3)
    parser.add_argument("files", nargs="*", help="tests/ 안의 파일 이름 (없으면 전부)")
    args = parser.parse_args()
    LOGS.mkdir(parents=True, exist_ok=True)
    files = args.files or sorted(p.name for p in (ROOT / "tests").glob("test_*.py"))
    files.sort(key=lambda name: -_last_seconds(name))     # 오래 걸리는 파일부터 (지난 로그 기준)
    start = time.time()
    with ThreadPoolExecutor(max_workers=args.jobs) as pool:
        results = list(pool.map(run_file, files))
    failed = [r for r in results if not r[1]]
    retried = {}
    for name, *_ in failed:                                  # 혼자 다시 돌려 혼잡 탓인지 확인
        retried[name] = run_file(name)
    total = sum(r[2] for r in results)
    real = [n for n, r in retried.items() if not r[1]]
    print(f"테스트 {total}개 · 파일 {len(files)}개 · {time.time() - start:.0f}초 (동시 {args.jobs}개)")
    for name in sorted(retried):
        state = "진짜 실패" if name in real else "재실행 통과(혼잡 때문)"
        print(f"  {name}: {state} — 로그 logs/tests/{name}.log")
        if name in real:
            lines = [line for line in retried[name][4].splitlines()
                     if line.startswith(("FAIL:", "ERROR:", "AssertionError", "RuntimeError"))]
            print("\n".join(lines[:20]))
    print("결과: 모두 통과" if not real else f"결과: 실패 {len(real)}개 파일")
    return 1 if real else 0


if __name__ == "__main__":
    sys.exit(main())
