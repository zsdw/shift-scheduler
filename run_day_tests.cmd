@echo off
cd /d "%~dp0"
echo Running day-shift tests...
"%~dp0.venv\Scripts\python.exe" -m unittest tests.test_day_shift -v > day_test_result.txt 2>&1
>> day_test_result.txt echo EXIT_CODE=%errorlevel%
echo Done. Result saved to day_test_result.txt
