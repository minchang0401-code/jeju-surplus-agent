# 제주 잉여전력 도우미

제주에서 전기가 남을 가능성이 있는 시간을 예측하고, 도민의 일정에 맞는 가전 사용·전기차 충전 시간과 주변 충전소를 안내하는 AI Agent입니다. 날짜·지도·그래프로 예측을 탐색하고, 생활 언어로 계획을 요청한 뒤 근거를 확인하고 캘린더에 저장할 수 있습니다.

예측 대상은 제주 시간별 전력시장 가격(SMP)이 0원 이하가 될 가능성입니다. 실제 잉여 전력량, 출력제어 발생 또는 사용자 전기요금 할인을 보장하지 않습니다. 실제 전력 배분·가전 제어·충전소 예약 기능은 없습니다.

문서 갱신 기준: 2026-11-19.

## 빠른 실행

프로젝트 전체를 내려받아 압축을 풀고 해당 폴더에서 실행합니다. `app.py`만 받으면 데이터·모델·화면 구성 파일이 빠집니다. Python 3.11 이상이 필요하며 최종 회귀검사 환경은 macOS / Python 3.14.4입니다.

macOS / Linux:

```bash
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -r requirements.txt
python -m streamlit run app.py --browser.gatherUsageStats false
```

Windows PowerShell — 활성화 스크립트 없이 실행:

```powershell
py -3 -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
.\.venv\Scripts\python.exe -m streamlit run app.py --browser.gatherUsageStats false
```

주소는 기본 `http://localhost:8501`입니다. 종료는 서버 터미널에서 `Ctrl+C`를 누릅니다. 포트가 사용 중이면 `--server.port 8502`를 붙입니다.

Windows의 `실행하기.bat`, macOS의 `실행하기.command`로도 실행할 수 있습니다. 최초 실행 시 `.venv`와 패키지를 설치하므로 Python과 인터넷이 필요합니다. 기존 `.venv`가 있으면 실행기가 패키지를 다시 설치하지 않으므로 업데이트 후 위 설치 명령을 다시 실행하세요.

## API 없이 체험하기

저장된 `data/`와 `models/`가 있으면 데이터 API와 LLM 키 없이 기본 분석과 규칙 기반 답변을 이용할 수 있습니다. 지도 배경·외부 길찾기·Google Calendar는 인터넷이 필요합니다. 저장된 예보가 미래 날짜를 덮지 못하면 달력·최근 경향 모델의 참고치로 예측합니다.

LLM 호출을 명시적으로 끄려면 아래처럼 실행합니다. 로컬에 별도로 받은 `eval.env`가 있을 때도 적용됩니다.

```bash
# macOS / Linux — 현재 실행에만 적용
LLM_PROVIDER=none python -m streamlit run app.py
```

```powershell
# Windows PowerShell
$env:LLM_PROVIDER = "none"
.\.venv\Scripts\python.exe -m streamlit run app.py
```

`eval.env`는 Git 저장소에 포함되지 않습니다. 파일이 없는데 평가용 키가 자동 제공된다고 가정하지 마세요.

## 환경변수 설정

필요한 기능만 연결합니다. 예시는 비밀값이 없는 [.env.example](.env.example)에 있습니다.

```bash
# macOS / Linux
cp .env.example .env
```

```powershell
# Windows PowerShell
Copy-Item .env.example .env
```

예시 기본값은 `LLM_PROVIDER=none`입니다. LLM을 사용하려면 `.env`의 공급자·키·모델 설정을 함께 확인하세요. 파일 로딩 우선순위는 프로세스 환경변수 → `.env` → 별도로 제공된 `eval.env`이며, 빈 값도 뒤 파일의 같은 항목을 막습니다. 변경 후 서버를 종료하고 다시 실행합니다.

사이드바의 ‘데이터 및 연결 상태’에 표시되는 ‘설정됨’은 인증 정보 등록 여부입니다. 실제 API 연결 성공은 해당 기능 실행과 답변의 ‘근거 보기’에서 확인합니다. 상세 변수와 클라우드 Secrets 설정은 [실행 매뉴얼](docs/manual.md#3-환경변수와-api-설정)을 참고하세요.

## 사용자 흐름

1. 별도 로그인 화면 없이 게스트로 진입합니다.
2. 환영 팝업에서 이용 안내·생활 설정·준비 완료 단계를 확인합니다. X나 ‘바로 둘러보기’로 닫을 수 있습니다.
3. 날짜를 골라 해당 날짜의 추천 구간을 보고, 그래프를 눌러 지도 시각을 바꿉니다. 범위는 오늘부터 5일 뒤까지 6개 날짜입니다.
4. ‘내 생활 설정’의 ‘설정 변경’에서 동네·차종·평일 외출시간·요금제를 조정합니다.
5. ‘생활 계획’에서 빠른 질문이나 직접 질문으로 계획을 요청합니다. 질문에 명시한 조건이 저장된 기본값보다 우선합니다.
6. ‘근거 보기’에서 사용한 도구·자료·계산 결과를 확인하고 유효한 추천 시간을 캘린더에 저장합니다.

‘다시 보지 않기’만 해당 브라우저 저장소에 유지됩니다. 생활 설정과 대화는 게스트 세션에만 남으며 재접속·서버 재시작 시 사라질 수 있습니다. 소셜 로그인과 계정 보관은 준비 중입니다. 자세한 조작법은 [사용자 매뉴얼](docs/manual.md#4-사용자-매뉴얼)에 있습니다.

## Agent와 데이터

| 구성 | 역할 |
|---|---|
| `agent.py` | LLM 질문 해석·도구 선택·설명, 실패 시 규칙 기반 응답 |
| `tools.py` / `planning.py` / `appliances.py` | 11개 도구, 외출 제약과 기기별 사용시간·충전량 계산 |
| `features.py` / `train.py` / `predict.py` | 변수 생성, CPU 기반 모델 학습·평가, 시간별 예측 |
| `time_utils.py` | 서버 시간대와 무관한 한국 시간 날짜·시각 처리 |
| `app.py` / `dashboard_view.py` / `main.css` | 날짜·예측 요약·그래프·반응형 화면 |
| `onboarding.py` / `onboarding.css` / `components/` | 닫을 수 있는 단계별 안내와 브라우저 숨김 설정 |
| `guest_session.py` / `user_profile.py` | 게스트 상태·생활 설정·질문 기본값 |
| `nearby_map.py` / `calendar_link.py` | 지도와 위치 기반 탐색, Google Calendar 링크·ICS 생성 |
| `status_view.py` | 연결 설정·예측 자료·제주데이터허브 자료 상태 표시 |
| `grid.py` / `facts.py` | 계통 기록 계산, 설명에 사용하는 사실과 출처 |

제주데이터허브 579·862·1225·1226·877·123·472를 기상 학습, 충전소 탐색, 이용 이력 분석, 설비 규모·기후 설명에 사용합니다. 외부 자료는 EPSIS 제주 SMP, 기상청 관측·단기·중기예보, 전력거래소 계통 기록입니다. 자료별 제공 기간과 출처는 [데이터 명세](docs/data_spec.md)에 있습니다.

LLM은 질문 해석과 설명을 맡고, 확률은 scikit-learn의 HistGradientBoostingClassifier가 계산합니다. `config.py`는 Gemini·OpenAI·Upstage·Anthropic 설정을 지원하지만 공급자별 실연결은 별도 확인해야 합니다. 대형언어모델을 로컬 GPU에 올리지 않습니다.

## 의존성

| 파일 | 용도 |
|---|---|
| [requirements.txt](requirements.txt) | 앱·수집·학습 실행 범위: pandas, NumPy, scikit-learn, joblib, requests, Streamlit, Altair, pydeck |
| [requirements-dev.txt](requirements-dev.txt) | 실행 의존성 + pytest |
| [requirements-tested.txt](requirements-tested.txt) | 최종 회귀검사에서 확인한 실행 패키지 버전 고정값 |

그림 재생성 등 일부 `experiments/` 스크립트는 별도로 matplotlib와 한글 글꼴이 필요합니다. 앱 실행에는 matplotlib가 필요하지 않습니다. 지도는 카카오맵 또는 Leaflet·외부 지도 타일을 브라우저에서 불러옵니다.

## 검증과 성능 기록

```bash
python -m pip install -r requirements-dev.txt
python -m pytest
python run_scenarios.py
```

2026-11-19 최종 수정본에서 자동 검사 178개, 규칙 기반 질문 이해 58/58, 후속 질문 8/8, 생활 언어 답변 10/10, 시나리오 5/5를 확인했습니다. pytest는 LLM을 대체하고 시나리오 실행도 LLM을 끄므로 API 응답 품질 시험과 다릅니다. 시나리오 실행은 `reports/scenario_results.md`를 갱신합니다.

실제 LLM 시험은 키 설정 후 `python run_llm_eval.py`로 따로 실행합니다. 외부 요청과 비용·한도가 발생할 수 있고 결과 파일을 갱신합니다. 저장된 Gemini 27/27 기록은 이전 시험이며 최종 로직 수정 후의 전체 재시험 결과는 아닙니다.

저장된 모델 보고서의 날짜 PR-AUC 0.651, 시간 PR-AUC 0.568은 관측 날씨를 사용한 과거 월별 재학습 평가입니다. 65.1% 정확도나 실제 예보 운영 성능을 뜻하지 않습니다. 최신 결측 처리 변경 이후의 재학습·재평가와 운영 예보 누적 검증이 필요합니다.

## 문서와 제약사항

- [설치·실행 및 사용자 매뉴얼](docs/manual.md)
- [오류 해결과 제약사항](docs/troubleshooting.md)
- [심사위원 빠른 확인](docs/judge_quickstart.md)
- [데이터 명세](docs/data_spec.md)
- [결과 설명자료](docs/result_report.md)
- [AI·외부 서비스 사용 고지](docs/ai_disclosure.md)
- [저장된 모델 평가](reports/report.md) / [날씨 오차 실험](reports/forecast_error_test.md) / [이전 LLM 시험](reports/llm_eval.md)

충전소 정보·과거 이용 이력은 실시간 빈자리·고장·대기시간이 아닙니다. 지도 색은 제주 전체 예측이고 원 크기는 지역 설비 규모입니다. 도민 참여에 따른 실제 전력 이동·출력제어 감소·요금 절감은 아직 측정하지 않았습니다. 전체 제한은 오류·제약사항 문서를 확인하세요.
