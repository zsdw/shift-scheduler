@echo off
rem Runs the full unittest suite and saves the output to test_result.txt
cd /d "%~dp0"
set PYTHONIOENCODING=utf-8
echo Running tests... this can take several minutes.
"%~dp0.venv\Scripts\python.exe" -m unittest discover -s tests -v > test_result.txt 2>&1
>> test_result.txt echo EXIT_CODE=%errorlevel%
echo Done. Result saved to test_result.txt
pause
