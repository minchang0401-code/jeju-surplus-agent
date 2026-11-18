# 시험 시나리오 결과 (2026-11-18 23:43)

통과 5/5


## 1. 일반 가정 — 통과

- 질문: 이번 주에 빨래랑 식기세척기 언제 돌리면 좋아?
- 목적: 기기마다 걸리는 시간·전력량을 계산하고 잉여 가능성 높은 연속 시간대를 안내
- 응답 방식: fallback
- 기대 도구: ['plan_appliance_use'] / 실제 도구: ['plan_appliance_use', 'plan_appliance_use']

```
- 세탁기: 한 번에 약 1시간~2시간, 전기 약 0.4~1kWh 써요 (제품·코스마다 달라요).
- 세탁기 돌리기 좋은 때 (2시간 연속):
  · 11월 22일(일) 낮 12시~오후 2시 (가능성 보통 · 날씨 미반영 참고치)
  · 11월 21일(토) 낮 12시~오후 2시 (가능성 낮음)
  · 11월 23일(월) 낮 12시~오후 2시 (가능성 낮음 · 날씨 미반영 참고치)
- 세탁기 '예약' 기능으로 끝나는 시간을 맞춰 두면 편해요.
- 식기세척기: 한 번에 약 1시간 10분~2시간, 전기 약 0.9~1kWh 써요 (제품·코스마다 달라요).
- 식기세척기 돌리기 좋은 때 (2시간 연속):
  · 11월 22일(일) 낮 12시~오후 2시 (가능성 보통 · 날씨 미반영 참고치)
  · 11월 21일(토) 낮 12시~오후 2시 (가능성 낮음)
  · 11월 23일(월) 낮 12시~오후 2시 (가능성 낮음 · 날씨 미반영 참고치)
- 예약(지연 시작) 기능으로 잉여 시간에 돌아가게 하세요.

출처: 12인용 표준코스 1회 0.97kWh(삼성전자)·1.0kWh(LG전자) 제조사 표시값 · 한국소비자원 시험 표준코스 1시간 6분~2시간, EPSIS 제주 시간별 SMP(학습 정답), 기상청 단기예보, 한국에너지공단 효율등급 기준(드럼세탁기 1등급 최저기준 45.8Wh/kg, 제조사 표기) · 세탁건조기 1회 세탁 432.3Wh(한국에너지공단 등록값, 삼성전자 뉴스룸)
```

## 2. 전기차 도민 — 통과

- 질문: 토요일에 노형동 근처에서 급속 충전하려는데?
- 목적: 토요일 예보 + 허브 862·1225 근거 (묻지 않은 내용은 덧붙이지 않음)
- 응답 방식: fallback
- 기대 도구: ['recommend_actions', 'find_chargers'] / 실제 도구: ['recommend_actions', 'find_chargers']

```
- 2026-11-21(토) 낮 12시~오후 1시: 재생에너지가 남을 가능성 보통(22%) (날씨 미반영 참고치) → 전기차 충전을 이 시간에
- 저녁 4~10시는 제주 계시별 요금의 최대부하 시간이라, 계시별 요금 가입 가구는 이 시간을 피하면 요금이 줄어요.
- 참고: 제주도는 재생에너지가 많이 생산되는 시간에 전기를 쓰도록 유도하는 '제주형 전기요금제'를 마련하겠다고 밝혔습니다(추진 단계, 아직 시행 전).
- 노형 중심 반경 2km에서 충전소 87곳을 찾았어요. 가까운 곳(급속 먼저):
  · 수덕공영주차장 (0.1km · 급속 4대)
  · 노형 제5 공영주차장 (0.2km · 급속 4대)
  · 노형동주민센터 (0.2km · 급속 1대)
  · 노형2지구 공영주차장 (0.3km · 급속 4대)
  · 개인택시조합 (0.3km · 급속 2대)

출처: EPSIS 제주 시간별 SMP(학습 정답), 기상청 단기예보, 에너지경제연구원 이슈페이퍼 23-10 (2023), 제주데이터허브 1225 일별 전기자동차 충전 이력, 제주데이터허브 579 일별 기상(학습), 제주데이터허브 862 전기자동차 충전소 정보 (기준일 20250921)
```

## 3. 원인 설명 — 통과

- 질문: 잉여전력이 왜 생기는 거야?
- 목적: EPSIS 통계 + 허브 877·123·472 근거
- 응답 방식: fallback
- 기대 도구: ['explain_surplus'] / 실제 도구: ['explain_surplus']

```
- 2024-06-01 ~ 2026-11-17 동안 900일 중 127일, 모두 347시간에 제주 전기 가격이 0원 이하로 떨어졌어요.
- 잉여가 잦은 달: 3월(48%), 4월(33%), 11월(26%)
- 주로 맑은 날 한낮에 태양광 발전이 몰리고, 냉난방을 덜 쓰는 봄·가을 주말에 많이 생겨요.
- 2000~2021년 제주 기후를 보면 4~5월 햇빛(일사)이 1월의 약 2.2배로 강하고, 하루 해 비치는 시간도 4월 6.7시간으로 장마철 6월(4.8시간)보다 길어요. 여기에 봄은 냉난방을 덜 써서 전기가 남기 쉬워요.
- 도에 등록된 태양광 발전 사업체는 1,998곳, 모두 711MW예요. 2018년 168MW에서 지금 711MW로 늘어 한낮에 남는 전기가 많아졌어요.
- 풍력발전소도 25곳, 419MW가 있어 바람 센 날엔 전기가 더 남기 쉬워요.

출처: EPSIS 제주 시간별 SMP, 제주데이터허브 123 전기사업체(태양광) 등록현황, 제주데이터허브 472 풍력발전현황, 제주데이터허브 877 2000-2021 제주도 일간 기후(4지점, 일사는 고산)
```

## 4. 예보 검증 — 통과

- 질문: 지난주 예보 맞았어?
- 목적: 지난 예보와 실제 SMP 비교
- 응답 방식: fallback
- 기대 도구: ['check_past_forecast'] / 실제 도구: ['check_past_forecast']

```
- 2026-11-11 ~ 2026-11-17 실제 잉여일 0일. 이 기간에는 '가능성 있음' 예보를 내지 않아 0일을 놓쳤어요.
- 기준: 시험 기간 재현 예보(각 달 시작 5일 전까지의 데이터로 학습한 모델이 냈을 예보)

출처: EPSIS 제주 시간별 SMP(실제), 시험 기간 재현 예보(각 달 시작 5일 전까지의 데이터로 학습한 모델이 냈을 예보)
```

## 5. 데이터·연결 상태 — 통과

- 질문: 데이터 상태 알려줘
- 목적: 실시간/저장 데이터 모드 판단
- 응답 방식: fallback
- 기대 도구: ['data_status'] / 실제 도구: ['data_status']

```
- 모드: 실시간 예보 모드 / 준비된 허브 데이터 7종
```


## 비상 모드 질문 이해 시험 (50개)

통과 50/50


| 질문 | 기대 도구 | 고른 도구 | 결과 |
|---|---|---|---|
| 내일 세탁기 돌려도 돼? | plan_appliance_use | plan_appliance_use | 통과 |
| 이번 주말 빨래 언제가 좋아 | plan_appliance_use | plan_appliance_use | 통과 |
| 모레 식기세척기 언제 쓰면 좋아요 | plan_appliance_use | plan_appliance_use | 통과 |
| 다음주 예보 보여줘 | forecast_surplus | forecast_surplus | 통과 |
| 며칠 동안 언제 전기가 남아? | forecast_surplus | forecast_surplus | 통과 |
| 애월 쪽 충전소 알려줘 | find_chargers | find_chargers | 통과 |
| 공항 근처 급속 충전기 있어? | find_chargers | find_chargers | 통과 |
| 서귀포시청 근처에서 전기차 충전하려고 | find_chargers | recommend_actions, find_chargers | 통과 |
| 중문에서 금요일에 충전할 건데 | find_chargers | recommend_actions, find_chargers | 통과 |
| 전기차 언제 충전하는 게 좋아? | recommend_actions | recommend_actions | 통과 |
| EV 충전 시간 추천해줘 | recommend_actions | recommend_actions | 통과 |
| 다른 사람들은 보통 몇 시에 충전해? | ev_charging_habits | ev_charging_habits | 통과 |
| 출력제어가 뭐야? | explain_surplus | explain_surplus | 통과 |
| 왜 봄에 전기가 남아? | explain_surplus | explain_surplus | 통과 |
| SMP 0원이 무슨 뜻이야 | explain_surplus | explain_surplus | 통과 |
| 지난달 예보 정확했어? | check_past_forecast | check_past_forecast | 통과 |
| 저번 주 예보 맞았는지 알려줘 | check_past_forecast | check_past_forecast | 통과 |
| 데이터 출처가 어디야? | data_status | data_status | 통과 |
| 지금 연결 상태 어때? | data_status | data_status | 통과 |
| 에어컨은 언제 트는 게 좋아? | plan_appliance_use | plan_appliance_use | 통과 |
| 그래서 결국 도민들이 얻는 이득이 뭐야? | explain_benefits | explain_benefits | 통과 |
| 이거 쓰면 전기요금이 싸져? | explain_benefits | explain_benefits | 통과 |
| 이번주는 언제 전기가 남아? 언제 전기를 써야 싸게 쓸 수 있을까? | recommend_actions | recommend_actions | 통과 |
| 내일 언제 써야 싸? | recommend_actions | recommend_actions | 통과 |
| 이번주는 언제 전기가 남아? | forecast_surplus | forecast_surplus | 통과 |
| 이번주에 충전을 하면 뭐가 좋아? | explain_benefits | recommend_actions, explain_benefits | 통과 |
| 이번주에 충전을 하면 뭐가 좋아? | recommend_actions | recommend_actions, explain_benefits | 통과 |
| 충전을 하면 돈이 아껴져? | explain_benefits | explain_benefits | 통과 |
| 전기차 충전하면 언제가 좋아? | recommend_actions | recommend_actions | 통과 |
| 하귀리에서 충전하려는데 | find_chargers | recommend_actions, find_chargers | 통과 |
| 잉여전력은 어떻게 생겨? | explain_surplus | explain_surplus | 통과 |
| 빨래를 아끼려면 어떻게 해야 해? | how_to_act | recommend_actions, how_to_act | 통과 |
| 노형동에서 몇 시에 충전하면 좋아? | recommend_actions | recommend_actions, find_chargers | 통과 |
| 오늘 저녁에 세탁기 돌리려고 | plan_appliance_use | plan_appliance_use | 통과 |
| 빨래 언제 돌려? | plan_appliance_use | plan_appliance_use | 통과 |
| 차 배터리 반 남았어 | plan_appliance_use | plan_appliance_use | 통과 |
| 아이오닉5 30% 남았는데 내일 충전하려면? | plan_appliance_use | plan_appliance_use | 통과 |
| 보일러 언제 틀어? | plan_appliance_use | plan_appliance_use | 통과 |
| 토요일 오후에 건조기 돌려도 돼? | plan_appliance_use | plan_appliance_use | 통과 |
| 밤에 식기세척기 돌릴건데 | plan_appliance_use | plan_appliance_use | 통과 |
| 음식물처리기 언제 돌려? | plan_appliance_use | plan_appliance_use | 통과 |
| 히트펌프 축열조 언제 데워? | plan_appliance_use | plan_appliance_use, plan_appliance_use | 통과 |
| 스타일러 언제 돌리면 좋아? | plan_appliance_use | plan_appliance_use | 통과 |
| 온풍기 틀어도 돼? | plan_appliance_use | plan_appliance_use | 통과 |
| 휴대폰 충전 언제 해? | plan_appliance_use | plan_appliance_use | 통과 |
| 냉장고 언제 켜? | plan_appliance_use | plan_appliance_use | 통과 |
| 노형동에서 차 배터리 20% 남았는데 언제 충전해? | find_chargers | plan_appliance_use, find_chargers | 통과 |
| 오늘 점심 뭐 먹지? | (답할 수 없음) | (답할 수 없음) | 통과 |
| 내가 말한 질문에 다른 답을 하는데? | (답할 수 없음) | (답할 수 없음) | 통과 |
| 제주 맛집 추천해줘 | (답할 수 없음) | (답할 수 없음) | 통과 |

## 이어지는 질문 이해 시험 (8개)

통과 8/8


| 앞 질문 | 이어지는 질문 | 기대 도구 | 고른 도구 | 결과 |
|---|---|---|---|---|
| 잉여전력이 생기는 시간에 충전을 하면 어떤 점이 좋아? | 그렇게 하려면 어떻게 해야해? | how_to_act | recommend_actions, how_to_act | 통과 |
| 잉여전력이 생기는 시간에 충전을 하면 어떤 점이 좋아? | 그럼 언제 하면 돼? | recommend_actions | recommend_actions | 통과 |
| 노형동 충전소 알려줘 | 그럼 거기는 몇 시가 좋아? | recommend_actions | recommend_actions, find_chargers | 통과 |
| 내일 빨래 언제 돌려? | 그럼 그거 어떻게 하면 돼? | how_to_act | recommend_actions, how_to_act | 통과 |
| 보일러 언제 틀어? | 기름 보일러야 | plan_appliance_use | plan_appliance_use | 통과 |
| 보일러 언제 틀어? | 기름이야 | plan_appliance_use | plan_appliance_use | 통과 |
| 전기차 언제 충전해? | 30퍼 남았어 | plan_appliance_use | plan_appliance_use | 통과 |
| 잉여전력이 생기는 시간에 충전을 하면 어떤 점이 좋아? | 그럼 맛집은? | (답할 수 없음) | (답할 수 없음) | 통과 |

## 생활 언어 답변 시험 (7개)

통과 7/7


| 질문 | 꼭 있어야 할 말 | 결과 |
|---|---|---|
| 오늘 저녁에 세탁기 돌리려고 | 0.4~1kWh, 거의 없, 예약 | 통과 |
| 아이오닉5 30% 남았는데 내일 충전하려면? | 84, 42kWh, 급속 | 통과 |
| 차 배터리 반 남았어 | 50% → 80%, 2시간 50분 | 통과 |
| 보일러 언제 틀어? | 기름·가스, 전기보일러인가요 | 통과 |
| 크리스마스에 빨래하려고 | 예보할 수 있는 기간, 밖 | 통과 |
| 냉장고 언제 켜? | 옮기기 어려워 | 통과 |
| 전기장판 써도 돼? | 억지로 옮길 필요는 없어요 | 통과 |