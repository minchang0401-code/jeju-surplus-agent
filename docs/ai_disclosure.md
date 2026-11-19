# AI 사용·외부 API·외부 데이터·오픈소스 고지

대회 규칙("최종 제출 시 사용 AI 모델, AI 활용 범위, 외부 API·서비스, 외부 데이터, 오픈소스 및 외부 코드 등을 명시")에 따라 정리했습니다.

## 1. 서비스 안에서 쓰는 AI 모델
| 구분 | 모델 | 역할 | 위치 |
|---|---|---|---|
| 대화·도구 선택 (LLM) | **Google Gemini 3.5 Flash-Lite** (`gemini-3.5-flash-lite`) | 질문 이해, 도구 선택(function calling), 도구 결과로 답변 작성 | `agent.py`, `config.py` 의 `DEFAULT_LLM` |
| 잉여 시간 예측 | **HistGradientBoostingClassifier** (scikit-learn), 팀이 직접 학습 | 시간별 잉여 확률 계산 | `train.py`, `predict.py`, `models/surplus_model.joblib` |
| 비상 모드 | 규칙 기반 (AI 아님) | LLM이 없거나 끊길 때 낱말 규칙으로 도구 선택 | `agent.py` 의 `_route()` |

- LLM은 OpenAI 호환 주소(`https://generativelanguage.googleapis.com/v1beta/openai`)로 부릅니다. `.env`의 `LLM_PROVIDER`로 OpenAI·Upstage·Anthropic으로 바꿀 수도 있지만, 제출 버전에서 시험한 것은 Gemini입니다.
- LLM이 답에 쓰는 숫자는 **도구 결과에 있는 값만** 쓰도록 지침으로 제한했습니다. 예측 자체는 LLM이 아니라 학습한 모델이 합니다.

### 프롬프트(지침)와 도구 설명 위치
| 내용 | 위치 |
|---|---|
| 시스템 지침 (규칙, 날짜 맥락, 예보 범위, 답변 형식) | `agent.py` → `_system_prompt()` |
| 도구 11개의 이름·설명·입력 형식 (function calling 명세) | `tools.py` → `TOOL_SPECS` |
| 답변에 쓰는 확인된 사실과 주의 규칙 | `facts.py` → `FACTS`, `SAFETY_RULES` |

## 2. 개발 과정에서 쓴 AI 도구 (AI 활용 범위)
| 도구 | 쓴 범위 | 사람이 한 일 |
|---|---|---|
| **Claude (Anthropic, Claude Opus 5.5)** | 코드 작성·수정·디버깅, 데이터 수집 스크립트, 전처리, 모델 학습·평가 코드, 문서 초안(매뉴얼·명세서·결과 설명자료) | 주제·기획 결정, 데이터 신청·키 발급, 실행·결과 확인, 테스트, 수정 방향 결정, 최종 검토 |
| (팀원이 쓴 다른 AI 도구가 있으면 여기에 추가) | | |

## 3. 외부 API·서비스
| 이름 | 쓰는 곳 | 필요한 키 | 비용 |
|---|---|---|---|
| 제주데이터허브 OpenAPI | 허브 579·1225·1226·862 수집 (`collect_hub.py`) | 허브 프로젝트키 | 무료 (데이터별 하루 1,000회) |
| 기상청 API허브 (지상관측 ASOS 시간자료) | 과거 날씨, 학습용 (`collect_weather.py history`) | API허브 인증키 | 무료 |
| 공공데이터포털 기상청 단기예보 (15084084) | 앞으로 3일 날씨, 예보용 (`collect_weather.py forecast`, 앱 자동 갱신) | 일반 인증키 | 무료 |
| 전력거래소 EPSIS (제주 시간별 SMP) | 정답(라벨) 수집 (`collect_smp.py`) | 필요 없음 | 무료 |
| Google Gemini API | 대화·도구 선택 | Gemini API 키 (Google AI Studio) | 무료 등급 사용 (하루 500회 한도). 무료 등급 요청은 Google 제품 개선에 쓰일 수 있음 |
| Streamlit Community Cloud | 팀 내부 시연용 웹 주소 (선택, 제출물 실행에는 필요 없음) | GitHub 계정 | 무료 |

- 실제 API 키는 제출물에 넣지 않았습니다. 발급·설정 방법은 `docs/manual.md`에 있습니다.
- 평가용 LLM 키를 따로 제출하는 경우, 사용 한도를 설정하고 평가가 끝나면 삭제합니다.

## 4. 외부 데이터 (필수 데이터 외)
| 데이터 | 제공처 | 쓰는 곳 |
|---|---|---|
| 제주 시간별 SMP | 전력거래소 EPSIS (공공데이터포털 15150712와 같은 내용) | 정답(라벨), 통계 |
| 지상관측 ASOS 시간자료 | 기상청 | 학습 변수, 허브 579가 끝난 2025-03-31 이후 일별 기상 대체 |
| 단기예보 | 기상청 (공공데이터포털) | 예보 변수 |
| 제주 출력제어·전력수요·연계선(HVDC)·플러스 DR 기록 | 한국전력거래소 (공공데이터포털 15132422·15065239·15100403·15109039, 공공누리 이용조건에 따름) | `grid.py` → 도구⑪, 그림 6. 파일은 팀원 B가 받아 `data/grid_raw/`에 둠 |
| 날씨 효과 사전 실험용 재분석 자료 | Open-Meteo | `experiments/`의 사전 실험과 그림 3·4만 해당. **제출 모델에는 쓰지 않음** |
| 기기 1회 전력량·사용 시간 (기기 사전) | 한국에너지공단 효율등급 자료(제조사 인용), 삼성전자·LG전자 제품 표시값, 한국소비자원 비교시험(건조기·식기세척기·의류관리기), 현대자동차·기아 배터리 용량 공개 자료, 한국냉난방공조신문(제주 히트펌프 보급사업), 서울신문 2026-03-12(제주 도시가스 보급률) | `appliances.py` (값마다 `source`·`basis` 표기, 믿을 만한 대표값이 없는 기기는 숫자 대신 '제품 라벨 확인' 안내) |
| 요금제·정책 사실 | 에너지경제연구원 이슈페이퍼 23-10(2023), 뉴시스 2026-09-16, 파이낸셜뉴스 2026-10-09, 기후에너지환경부·한국전력 보도참고자료 2026-03-13 | `facts.py` (답변의 근거 문장) |

필수 데이터(제주데이터허브 579·862·1225·1226·877·123·472)의 상세 내용과 전처리는 `docs/data_spec.md`를 보세요.

## 5. 오픈소스 라이브러리
| 라이브러리 | 용도 | 라이선스 |
|---|---|---|
| pandas | 데이터 처리 | BSD-3-Clause |
| NumPy | 수치 계산 | BSD-3-Clause |
| scikit-learn | 예측 모델 학습·평가 | BSD-3-Clause |
| joblib | 모델 저장·불러오기 | BSD-3-Clause |
| requests | API 호출 | Apache-2.0 |
| Streamlit | 웹 화면 | Apache-2.0 |
| matplotlib | 그림 그리기 (`experiments/`, 선택) | Matplotlib License (PSF 기반) |
| pytest | 자동 시험 (`tests/`, 선택) | MIT |
| 지도 배경 (Streamlit `st.map`) | 화면 지도 | 배경 지도 © OpenStreetMap contributors, © CARTO (화면에 표시됨) |
| 카카오맵 링크 | 충전소 위치 열기·현재 위치에서 길찾기 (링크만 만듦, API 호출 없음) | 카카오맵 이용약관에 따름 |
| Leaflet 1.9.4 (unpkg CDN) | 내 주변 충전소 지도 (사용자 브라우저에서 불러옴) | BSD-2-Clause |
| 배경 지도 타일 (내 주변 지도) | OpenStreetMap 타일, 못 받으면 Esri World Street Map으로 자동 전환 | © OpenStreetMap contributors (ODbL), Tiles © Esri — 화면에 표시 |
| 브라우저 위치(Geolocation) | 내 주변 충전소 (사용자가 허용할 때만, 브라우저 안에서만 계산·저장 안 함) | 웹 표준 API |
| 구글 캘린더 링크·iCalendar(.ics) | 추천 시간대를 사용자 캘린더에 저장 (링크·파일만 만듦, API 호출·키 없음) | iCalendar는 공개 표준(RFC 5545) |

- 정확한 버전 범위는 `requirements.txt`, 실제 시험한 버전은 `requirements-tested.txt`에 있습니다.
- 위 라이브러리 외에 외부 코드를 그대로 가져와 쓰지 않았습니다. 팀원 에이전트에서 가져온 자료와 방식은 6장에 적었습니다.

## 6. 팀원 코드·자료 활용
같은 팀원이 만든 에이전트 두 개의 장점을 합쳤습니다 (팀원 동의함).
| 가져온 것 | 원래 위치 | 이 프로젝트에서 |
|---|---|---|
| 한국전력거래소 공개 파일(출력제어·수요·연계선·플러스 DR), 풍력발전소 대략 좌표 | 팀원 B `JEJU_SURPLUS_FORECAST/data/raw`, `data/reference/wind_farms.csv` | `data/grid_raw/`, `grid.py`, 화면 지도 |
| 지도 표시 아이디어 | 팀원 B `dashboard/index.html` | `app.py` '지도로 보기' (Streamlit `st.map`, 코드는 새로 작성) |
| 시간 제약 안에서 계획하기 | 팀원 C `TIMEFLOW_JEJU_MVP/timeflow/optimizer.py` | `tools.plan_appliance_use`의 출근·외출 일정 반영 (코드는 새로 작성) |
| 평가기준 대응표 형식 | 팀원 C `docs/EVALUATION_MAPPING.md` | `docs/evaluation_mapping.md` |
| pytest 자동 시험 방식 | 팀원 C `tests/`, `pytest.ini` | `tests/` (시험 내용은 새로 작성) |
