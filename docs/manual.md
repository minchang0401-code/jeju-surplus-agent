# 실행 매뉴얼 (심사·재현용)

이 문서만 보고 처음 받은 PC에서 에이전트를 실행할 수 있도록 적었습니다.
GPU는 쓰지 않습니다. 학습·예측 모두 CPU로 하고, 1분 안에 끝납니다.

## 1. 준비물
| 항목 | 내용 |
|---|---|
| 운영체제 | Windows 10/11, macOS, Linux 모두 가능 |
| Python | 3.11 이상, **3.13 또는 3.14 권장** (시험한 버전: 3.13·3.14). 라이브러리 버전 범위는 `requirements.txt`, 실제 시험한 버전은 `requirements-tested.txt` |
| 주요 패키지 | pandas, numpy, scikit-learn, joblib, requests, streamlit (`requirements.txt`) |
| 인터넷 | 처음 설치, 예보 갱신, AI(LLM) 대화에 필요. 없으면 저장된 데이터와 규칙 기반 답변으로 동작 |
| GPU | 필요 없음 |
| 센터 PC 최소사양 | i7-8700 / RAM 32GB면 충분 (예측·도구 실행 시 메모리 약 0.2GB 측정, GPU 미사용) |

## 2. 가장 쉬운 실행: 더블클릭
1. 압축을 풉니다.
2. 실행 파일을 더블클릭합니다.
   - **윈도우:** `실행하기.bat`
   - **맥:** `실행하기.command`
3. 처음 한 번은 필요한 프로그램을 자동으로 설치하므로 몇 분 걸립니다. 그다음 브라우저가 열립니다.
4. 먼저 뜨는 검은 창은 도우미(서버)가 켜져 있다는 표시입니다. **닫으면 꺼지니 최소화**해 두세요.

| 처음 실행할 때 경고가 뜨면 | 해결 |
|---|---|
| 윈도우: "Windows의 PC 보호" (SmartScreen) | **추가 정보 → 실행** |
| 맥: "확인되지 않은 개발자" | 파일을 오른쪽 클릭 → **열기 → 열기** (처음 한 번만) |
| "Python 3.11 이상이 필요해요" | https://www.python.org/downloads/ 에서 설치. 윈도우는 설치 첫 화면에서 **"Add python.exe to PATH"** 체크 |

> 키를 넣지 않아도 들어 있는 데이터와 학습된 모델로 화면과 대화(규칙 기반 '비상 모드')가 동작합니다.
> AI 대화와 최신 예보를 쓰려면 아래 3번처럼 키를 넣으세요.

## 3. 키 넣기 (`.env`)
`.env.example`을 복사해 이름을 `.env`로 바꾸고, 받은 키를 넣습니다. **실제 데이터 API 키는 제출물에 들어 있지 않습니다.**
```
JEJU_DATAHUB_PROJECT_KEY=   # 제주데이터허브 프로젝트키 (허브 579·1226·1225·862 수집용)
KMA_APIHUB_KEY=             # 기상청 API허브 인증키 (과거 관측, 학습용)
DATA_GO_KR_KEY=             # 공공데이터포털 일반 인증키 (단기예보, 화면에서 자동 갱신)
LLM_PROVIDER=gemini         # gemini / openai / upstage / anthropic / none
LLM_API_KEY=                # Gemini API 키
LLM_MODEL=                  # 비우면 gemini-3.5-flash-lite
```
- 맥에서 `.env`는 숨김 파일입니다. Finder에서 **⌘ + Shift + .** 을 누르면 보입니다.
- 비어 있는 키는 건너뛰고, 그 기능 없이 동작합니다.
- 키를 넣거나 바꾼 뒤에는 검은 창을 닫고 다시 실행해야 반영됩니다.

### 3-1. 키 발급 방법
| 키 | 발급 방법 | 걸리는 시간 |
|---|---|---|
| **Gemini API 키** (`LLM_API_KEY`) | https://aistudio.google.com 에 구글 계정으로 로그인 → 왼쪽 아래 열쇠 아이콘(API keys) → **API 키 만들기** → 복사. 결제 등록 없이 무료 등급(하루 500회) | 1분 |
| 공공데이터포털 일반 인증키 (`DATA_GO_KR_KEY`) | https://www.data.go.kr 회원가입 → 「기상청_단기예보 조회서비스」(15084084) **활용신청** → 마이페이지 → 개인 API 인증키에서 **인증키 복사(Decoding)** | 승인 즉시~1시간 |
| 기상청 API허브 인증키 (`KMA_APIHUB_KEY`) | https://apihub.kma.go.kr 회원가입 → 지상관측 **ASOS 시간자료** 활용신청 → 마이페이지에서 인증키 복사 | 승인 즉시 |
| 제주데이터허브 프로젝트키 (`JEJU_DATAHUB_PROJECT_KEY`) | https://jejudatahub.net 회원가입 → 프로젝트 만들기 → 데이터 579·862·1225·1226을 프로젝트에 추가 → 프로젝트키 복사 | 즉시 |

- 키는 다른 사람에게 보여 주거나 캡처·업로드하지 마세요. 노출되면 발급처에서 새로 만들고 예전 키는 지웁니다.

### 3-2. AI 연결 확인
화면 왼쪽 사이드바 맨 아래에 연결 상태가 나옵니다.
- 🟢 `AI(LLM) 연결: gemini · gemini-3.5-flash-lite` → 정상
- ⚪ `AI(LLM) 꺼짐 — …` → 뒤에 적힌 이유를 확인 (키 없음, 지원하지 않는 이름 등)
- 답마다 **근거 보기 → 응답 방식**에서 `AI(LLM)`인지 `규칙 기반(비상 모드)`인지 볼 수 있습니다.

## 4. 명령어로 실행하기 (데이터를 새로 받거나 다시 학습할 때)
```bash
# 압축을 푼 폴더에서
python -m venv .venv
# Windows: .venv\Scripts\activate    macOS/Linux: source .venv/bin/activate
pip install -r requirements.txt
```
| 순서 | 명령 | 결과 | 걸리는 시간(대략) |
|---|---|---|---|
| 1 | `python collect_smp.py` | `data/smp_jeju_hourly.csv` (정답: 제주 시간별 SMP, 키 불필요) | 1분 |
| 2 | `python collect_hub.py` | `data/hub/*.csv` (허브 579·1226·1225·862) | 수 분~수십 분 (허브 하루 호출 한도 1,000회) |
| 3 | `python prepare_files.py` | 허브 877·123·472 파일 정리본 (`*_clean.csv`) | 수 초 |
| 4 | `python collect_weather.py history` | `data/weather_jeju_hourly.csv` (과거 관측) | 수 분 |
| 5 | `python train.py` | `models/`, `reports/report.md`, `reports/metrics.json` | 1분 이내 |
| 6 | `python collect_weather.py forecast` | `data/forecast_jeju_hourly.csv` (최신 단기예보) | 수 초 |
| 7 | `python run_scenarios.py` | `reports/scenario_results.md` (시나리오 5개 + 질문 58개 + 이어지는 질문 8개 + 생활 언어 답변 10개) | 수 초 |
| 7-1 | `pip install -r requirements-dev.txt` 후 `python -m pytest` | 자동 시험 118개 통과 여부 (키·인터넷 필요 없음) | 수 초 |
| 8 | `python -m streamlit run app.py` | 브라우저에 화면 (http://localhost:8501) | — |

- 1~5는 이미 결과가 들어 있으니 건너뛰어도 됩니다.
- 6은 화면을 열 때 **자동으로** 실행됩니다. 예보가 4시간보다 오래됐고 `DATA_GO_KR_KEY`가 있을 때만 실행돼요.
- `streamlit` 대신 꼭 `python -m streamlit`으로 실행하세요. 다른 Python에 깔린 streamlit이 잡히는 일을 막습니다.

## 5. 결과 확인
- **👤 내 정보 (사이드바):** 동네·전기차·평일 출퇴근 시각·계시별 요금제를 넣고 '저장'을 누르면 이후 질문에 기본값으로 쓰입니다. 저장 뒤 **페이지 주소를 즐겨찾기**하면 다음에도 불러와집니다(새로고침만 하면 그대로, 새 탭에서 빈 주소로 열면 초기화).
- **📅 캘린더에 넣기:** 시간 추천 답 아래 버튼으로 구글 캘린더(안드로이드·PC) 또는 .ics 파일(아이폰·아웃룩)에 저장 → 10분 전 알림
- **화면:** 5일 예보 카드(높음·보통·낮음), '🗺️ 지도로 보기'(충전소·풍력발전소, '급속 충전소만 보기' 스위치), 빠른 질문 3개, 대화창, '근거 보기'(어떤 도구·데이터를 썼는지, 표·그래프·지도)
- **사이드바:** 데이터 준비 상태, AI 연결 상태, 기상청 예보 발표 시각
- **성능:** `reports/report.md` (시험 기간 2026-01-01 이후, 학습에 쓰지 않은 기간)
- **결과 설명:** `docs/result_report.md`
- **그림:** `reports/figures/` — 결과 설명자료 그림은 `report_1`~`report_6` (실제 데이터·결과, `python experiments/make_report_figures.py`로 다시 그림). `fig1`~`fig4`는 사전 실험 그림(3·4는 Open-Meteo 데이터)

## 6. 오류·제약사항
| 증상 | 원인·해결 |
|---|---|
| 답에 "응답 방식: 규칙 기반(비상 모드)" | LLM 키가 없거나, 하루 한도(500회)를 넘었거나, 인터넷이 끊김. 사이드바의 AI 상태 확인. 한도는 한국 시간 오후 4~5시쯤 초기화 |
| 근거 보기에 `llm_error` … `429` | Gemini 한도 초과. 잠시 뒤 다시 하거나 다음 날 사용 (그동안 규칙 기반으로 자동 답변) |
| 근거 보기에 `llm_error` … `400`/`404` | 모델 이름이 바뀌었을 수 있음. `.env`의 `LLM_MODEL`을 AI Studio의 '비율 제한' 화면에 보이는 Flash-Lite 모델 이름으로 지정 |
| "최신 기상청 예보를 받지 못해…" 노란 안내 | `DATA_GO_KR_KEY` 확인, 인터넷 확인. 저장된 예보로 계속 동작 |
| 단기예보 `SERVICE_KEY_IS_NOT_REGISTERED` | 공공데이터포털 승인 직후에는 1~2시간 걸릴 수 있음. Encoding 키를 넣었다면 **Decoding 키**로 바꾸기 |
| 허브 수집이 비어 있음 | 프로젝트키, 허브에서 해당 데이터를 프로젝트에 추가했는지 확인. `python collect_hub.py --debug`로 응답 확인 |
| 기상청 응답 오류 | API허브에서 'ASOS 시간자료' 활용신청 여부, 키 복사 시 공백 |
| 코드를 고쳤는데 그대로임 | 검은 창을 닫고 다시 실행 (새로고침만으로는 안 됨) |
| 한글이 깨짐 (그림) | 한글 글꼴(맑은 고딕·나눔고딕) 설치 |

**제약사항**
- 예보는 **오늘부터 5일 뒤까지**만 합니다. 날씨가 반영된 예보는 기상청 단기예보가 있는 2~3일이고, 나머지는 과거 패턴으로 본 참고치입니다.
- 성능 수치는 관측 날씨 기준이라, 예보 날씨를 쓰는 실제 서비스에서는 낮을 수 있습니다(`docs/result_report.md` 8장).
- 충전소의 실시간 빈자리·고장 여부는 알 수 없습니다(허브 862는 위치·설비 정보).
- 일반(누진제) 가정은 쓰는 시간을 옮겨도 지금 당장 요금이 달라지지 않습니다.
- 기기 전력량·사용 시간은 **대표값의 범위**입니다(제품·코스·용량마다 다름). 전기차는 차종을 모르면 중형(64.8kWh), 공용 완속 7kW·급속 50kW로 가정해 계산합니다. 정확한 값은 제품 라벨을 보세요.

## 7. (참고) 팀 시연용 웹 주소
- 팀 내부 시연을 위해 Streamlit Community Cloud에 같은 코드를 올려 두었습니다. 제출물 실행에는 필요 없습니다.
- 클라우드에서는 키를 `.env` 대신 앱 설정 **Settings → Secrets**에 `이름 = "값"` 형식으로 넣습니다.
- GitHub에 코드를 여러 개 올린 뒤에는 **Manage app → ⋮ → Reboot app**을 눌러 주세요. 바꿔 끼우는 도중의 일시 오류(`KeyError: 'config'` 등)를 막습니다.
