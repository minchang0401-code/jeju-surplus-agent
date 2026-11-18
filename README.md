# 제주 잉여전력 도우미 (AI Agent) — 2차 버전

제주 재생에너지가 남아 전력시장 가격(SMP)이 0원 이하로 떨어지는 **'잉여전력 시간'을 며칠 앞서 예보**하고,
도민에게 **언제·어디서 전기를 쓰면 좋은지** 쉬운 말로 안내하는 에이전트입니다.

## 구성
| 파일 | 역할 |
|---|---|
| `app.py` | 화면 (5일 예보 달력, 빠른 질문 3개, 대화창, 근거 보기, 데이터 상태) |
| `agent.py` | 에이전트: LLM이 도구를 골라 부르고 결과로만 답함. LLM이 없거나 끊기면 규칙 기반(비상 모드) |
| `tools.py` | 도구 7개 (아래 표) |
| `facts.py` | 답변에 쓰는 확인된 사실·출처 (요금제, 제주도 정책 등) |
| `train.py` / `predict.py` / `features.py` | 예측 모델 학습·평가 / 예보 / 변수 |
| `collect_smp.py` | EPSIS 제주 시간별 SMP (정답, 키 불필요) |
| `collect_hub.py` | **제주데이터허브** 579·1226·1225·862 (프로젝트키) |
| `collect_weather.py` | 기상청 ASOS 과거 관측(API허브 키) / 단기예보(공공데이터포털 키) |
| `run_scenarios.py` | 시험 시나리오 5개 + 비상 모드 질문 20개 → `reports/scenario_results.md` |

### 도구 7개와 데이터
| 도구 | 하는 일 | 데이터 |
|---|---|---|
| ① forecast_surplus | 5일 잉여 예보 (시간별 확률) | EPSIS(정답), 기상청 예보, **허브 579**(학습) |
| ② recommend_actions | 가전·충전 시간 추천 | ①, 요금 사실(facts.py) |
| ③ find_chargers | 동네 충전소·급속·관광객 비중 | **허브 862, 1225** |
| ④ ev_charging_habits | 도민 충전 시각 vs 잉여 시간 | **허브 1226**, EPSIS |
| ⑤ explain_surplus | 언제·왜 생기나 (통계) | EPSIS, **허브 877·123·472** |
| ⑥ check_past_forecast | 지난 예보 검증 | 예보 기록 / 백테스트, EPSIS |
| ⑦ data_status | 데이터·연결 상태 | 전체 |

## 문서
- `docs/manual.md` 실행 매뉴얼 (센터 PC용)
- `docs/data_spec.md` 데이터 활용 명세서 초안
- `reports/figures/` 기획서용 그림 4장 (`python experiments/make_figures.py`)

## 실행 순서
```bash
pip install -r requirements.txt
cp .env.example .env          # 키 입력 (키가 없는 항목은 비워 두면 건너뜀)

python collect_smp.py                          # 1) 정답 SMP (키 불필요)
python collect_hub.py --debug                  # 2) 허브 579·1226·1225·862 (프로젝트키)
python collect_weather.py history              # 3) 과거 날씨 (기상청 API허브 키)
python train.py                                # 4) 학습·평가 → reports/report.md
python collect_weather.py forecast             # 5) 최신 단기예보 (공공데이터포털 키) — 매일 실행
python run_scenarios.py                        # 6) 시험 시나리오 → reports/scenario_results.md
python -m streamlit run app.py                 # 7) 화면 (가상환경의 streamlit 으로 실행)
```
파일·링크형 허브 데이터는 직접 내려받아 넣습니다.
- 877 일간 기후 → `data/hub/877_daily_climate/` (4지점 CSV) → `python prepare_files.py` 로 정리
- 123 태양광 사업체 → `data/hub/123_solar_business/`
- 472 풍력발전현황 → `data/hub/472_wind_power/`

## 현재 성능 (2026년 시험 기간)
- 날씨 없이: 날짜 단위 PR-AUC 0.39(1차 모델) vs 0.32(과거 비율) vs 0.25(단순 규칙) — `reports/report.md`
- **날씨 효과 미리 보기 실험**(공개 재분석 자료): 날씨를 붙이면 날짜 PR-AUC 0.39 → 0.68, 예보에 있는 변수만 써도 0.62 — `reports/weather_experiment.md`, `experiments/`
- 날씨·허브 579를 붙인 모델은 키를 받은 뒤 `train.py`가 자동으로 함께 학습·비교합니다.

## 동작 방식
- 단기예보가 있는 날짜(보통 3일)는 **날씨 모델**, 그 뒤 날짜는 **1차 모델**로 예보하고, 어느 모델을 썼는지 표시합니다.
- 예보는 `data/forecast_log.csv`에 쌓이고, ⑥이 나중에 실제 SMP와 비교합니다.
- 실시간 예보가 없으면 저장된 데이터로 안내하는 **저장 데이터 모드**로 표시합니다.
- LLM 키가 없거나 연결이 끊기면 **규칙 기반 답변(비상 모드)**으로 바뀝니다. 이때도 허브·공공데이터 도구는 그대로 씁니다.

## 첫 실행 때 확인할 것 (추정으로 작성한 부분)
- 허브 API 페이지 나눔(`limit`·`number`)과 응답 구조 → `collect_hub.py --debug`
- 허브 1226 응답의 충전 횟수 열 이름 → `tools.ev_charging_habits` 가 자동 탐색, 안 맞으면 수정
- 기상청 ASOS 응답 열 순서 → `collect_weather.py history --debug` 후 `ASOS_COLUMNS` 확인
- 단기예보 격자(제주시 53,38 / 서귀포시 52,33) → `config.KMA_FCST_GRIDS`
- LLM 모델 이름(`.env`의 LLM_MODEL)
- `facts.py`의 계시별 요금 현재 단가

## 주의
- API 키는 `.env`에만 넣고 제출물에 포함하지 마세요.
- 이 서비스는 '지금 잉여 시간에 쓰면 요금이 자동으로 싸진다'고 말하지 않습니다. 제주형 요금제는 추진 단계입니다(facts.py).
