@echo off
chcp 65001 >nul
rem 제주 잉여전력 도우미 — 윈도우에서 더블클릭으로 실행
cd /d "%~dp0"

rem 압축을 풀지 않고 zip 안에서 바로 실행한 경우
if not exist "app.py" goto notunzipped

rem Python 찾기: python → py 순서 (Microsoft Store 가짜 python 은 버전 확인에서 걸러짐)
set "PY="
python -c "import sys; sys.exit(sys.version_info < (3, 11))" >nul 2>nul
if not errorlevel 1 set "PY=python"
if not defined PY (
  py -3 -c "import sys; sys.exit(sys.version_info < (3, 11))" >nul 2>nul
  if not errorlevel 1 set "PY=py -3"
)
if not defined PY goto nopython

if exist ".venv\Scripts\python.exe" goto run
echo 처음 실행이라 필요한 프로그램을 설치합니다. 몇 분 걸릴 수 있어요...
%PY% -m venv .venv
if errorlevel 1 goto fail
".venv\Scripts\python.exe" -m pip install -q -r requirements.txt
if errorlevel 1 goto fail

:run
echo ==================================================
echo   제주 잉여전력 도우미가 켜지는 중이에요.
echo   잠시 뒤 브라우저가 자동으로 열려요.
echo.
echo   ※ 이 창은 도우미가 켜져 있다는 표시예요.
echo      쓰는 동안에는 닫지 말고, 최소화해 두세요.
echo      다 쓰고 나서 이 창을 닫으면 도우미가 꺼져요.
echo ==================================================
".venv\Scripts\python.exe" -m streamlit run app.py --browser.gatherUsageStats false
pause
exit /b 0

:notunzipped
echo 압축을 먼저 풀어 주세요.
echo zip 파일을 오른쪽 클릭 → "압축 풀기"(모두 추출)를 한 뒤, 풀린 폴더 안의 실행하기.bat 을 더블클릭해 주세요.
pause
exit /b 1

:nopython
echo Python 3.11 이상이 필요해요. https://www.python.org/downloads/ 에서 설치해 주세요.
echo 설치할 때 "Add python.exe to PATH" 칸을 꼭 체크해 주세요.
pause
exit /b 1

:fail
echo 설치 중 문제가 생겼어요. 이 창의 내용을 캡처해서 보내 주세요.
rmdir /s /q .venv
pause
exit /b 1
