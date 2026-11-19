#!/bin/bash
# 제주 잉여전력 도우미 — 맥에서 더블클릭으로 실행
cd "$(dirname "$0")" || exit 1
pause() { read -r -p "Enter 키를 누르면 창이 닫힙니다..." _; }

if ! command -v python3 >/dev/null 2>&1 || ! python3 -c 'import sys; sys.exit(sys.version_info < (3, 11))'; then
  echo "Python 3.11 이상이 필요해요. https://www.python.org/downloads/ 에서 설치한 뒤 다시 실행해 주세요."
  pause; exit 1
fi

if [ ! -x .venv/bin/python ]; then
  echo "처음 실행이라 필요한 프로그램을 설치합니다. 몇 분 걸릴 수 있어요..."
  if ! python3 -m venv .venv || ! .venv/bin/python -m pip install -q -r requirements.txt; then
    echo "설치 중 문제가 생겼어요. 이 창의 내용을 캡처해서 보내 주세요."
    rm -rf .venv; pause; exit 1
  fi
fi

echo "=================================================="
echo "  제주 잉여전력 도우미가 켜지는 중이에요."
echo "  잠시 뒤 브라우저가 자동으로 열려요."
echo ""
echo "  ※ 이 창은 도우미가 켜져 있다는 표시예요."
echo "     쓰는 동안에는 닫지 말고, 최소화해 두세요."
echo "     다 쓰고 나서 이 창을 닫으면 도우미가 꺼져요."
echo "=================================================="
.venv/bin/python -m streamlit run app.py --browser.gatherUsageStats false
pause
