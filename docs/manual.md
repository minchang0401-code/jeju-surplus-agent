# 실행 매뉴얼 (심사·재현용)

이 문서만 보고 처음 받은 PC에서 에이전트를 실행할 수 있도록 적었습니다.
GPU는 쓰지 않습니다(학습·예측 모두 CPU, 1분 이내).

## 1. 준비물
| 항목 | 내용 |
|---|---|
| 운영체제 | Windows 10/11, macOS, Linux 모두 가능 |
| Python | 3.10 이상 (개발: 3.13) |
| 주요 패키지 | pandas, numpy, scikit-learn, joblib, requests, streamlit (`requirements.txt`) |
| 인터넷 | 데이터 수집·예보·LLM에 필요. 없으면 '저장 데이터 모드'로 동작 |
| GPU | 필요 없음 |

## 2. 설치
```bash
# 압축을 푼 폴더에서
python -m venv .venv
# Windows: .venv\Scripts\activate    macOS/Linux: source .venv/bin/activate
pip install -r requirements.txt
```

## 3. 키 넣기
`.env.example`을 복사해 `.env`를 만들고 받은 키를 넣습니다. **키는 제출물에 들어 있지 않습니다.**
```
JEJU_DATAHUB_PROJECT_KEY=   # 제주데이터허브 프로젝트키 (허브 579·1226·1225·862)
KMA_APIHUB_KEY=             # 기상청 API허브 authKey (과거 관측 ASOS)
DATA_GO_KR_KEY=             # 공공데이터포털 일반 인증키 (단기예보)
LLM_PROVIDER=none           # openai / upstage / anthropic / none
LLM_API_KEY=
LLM_MODEL=
```
- 키가 비어 있는 항목은 건너뛰고, 그 데이터 없이 동작합니다.
- `LLM_PROVIDER=none`이면 규칙 기반 '비상 모드'로 답합니다(도구와 데이터는 그대로 사용).

## 3-1. 가장 쉬운 실행: 더블클릭
- 윈도우: `실행하기.bat` / 맥: `실행하기.command` 를 더블클릭하면 설치(처음 한 번)와 실행을 자동으로 하고 브라우저를 엽니다.
- 먼저 뜨는 검은 창은 도우미(서버)가 켜져 있다는 표시입니다. 닫으면 꺼집니다.
- 받아 둔 데이터로 바로 동작합니다. 실시간 예보를 갱신하려면 아래 4번의 5단계(키 필요)를 실행하세요.

## 4. 실행 순서 (데이터를 새로 받거나 다시 학습할 때)
| 순서 | 명령 | 결과 | 걸리는 시간(대략) |
|---|---|---|---|
| 1 | `python collect_smp.py` | `data/smp_jeju_hourly.csv` (정답: 제주 시간별 SMP) | 1분 |
| 2 | `python collect_hub.py` | `data/hub/*.csv` (허브 579·1226·1225·862) | 수 분 |
| 3 | `python collect_weather.py history` | `data/weather_jeju_hourly.csv` (과거 관측) | 수 분 |
| 4 | `python train.py` | `models/`, `reports/report.md`, `reports/metrics.json` | 1분 이내 |
| 5 | `python collect_weather.py forecast` | `data/forecast_jeju_hourly.csv` (최신 단기예보) | 수 초 |
| 6 | `python run_scenarios.py` | `reports/scenario_results.md` (시나리오 5개 + 질문 20개) | 수 초 |
| 7 | `python -m streamlit run app.py` | 브라우저에 화면 (http://localhost:8501) | — |

- 매일 쓸 때는 5 → 7만 다시 하면 됩니다.
- 1~4를 건너뛰어도 제출물에 들어 있는 학습된 모델과 정답 요약 파일(`data/smp_jeju_surplus_compact.txt`)로 바로 7을 실행할 수 있습니다.

## 5. 결과 확인
- 화면: 5일 예보 카드(높음·보통·낮음), 빠른 질문 3개, 대화창, '근거 보기'(어떤 도구·데이터를 썼는지)
- 성능: `reports/report.md` (시험 기간 2026-01-01 이후, 학습에 쓰지 않은 기간)
- 그림: `reports/figures/` (기획서용), 다시 그리려면 `python experiments/make_figures.py`

## 6. 문제가 생기면
| 증상 | 확인할 것 |
|---|---|
| 허브 수집이 비어 있음 | 프로젝트키, 허브에서 해당 데이터 '활용 신청' 여부. `python collect_hub.py --debug`로 응답 확인 |
| 기상청 응답 오류 | API허브에서 'ASOS 시간자료' 활용 신청 여부, 키 복사 시 공백 |
| 단기예보 `SERVICE_KEY_IS_NOT_REGISTERED` | 공공데이터포털 승인 직후에는 1~2시간 걸릴 수 있음 |
| 예보 카드에 '저장 데이터 모드' 표시 | 5번 단계(단기예보)를 실행하지 않았거나 인터넷 없음 |
| 답변이 짧고 딱딱함 | LLM 키가 없거나 끊겨 비상 모드. 사이드바에 표시됨 |
| 한글이 깨짐(그림) | 한글 글꼴(맑은 고딕·나눔고딕) 설치 |
