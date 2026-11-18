"""기기 사전 — 도민이 "빨래 돌리려고", "차 배터리 반 남았어"처럼 말해도 에이전트가 시간·전력량을 대신 계산합니다.

값의 근거(basis)
- 공인·제조사: 한국에너지공단 효율등급 자료, 제조사 표시값, 한국소비자원 시험 결과
- 계산값: 물리식으로 계산 (가정을 note 에 적음)
- 제품마다 다름: 믿을 만한 대표값이 없어 숫자를 말하지 않고 "제품 라벨 확인"을 안내
숫자는 모두 '대략'이며 제품·코스·사용량에 따라 달라집니다. 에이전트는 범위로 말하고 출처를 함께 보여 줍니다.
"""
from __future__ import annotations

import math

# shift: 시간 옮기기 쉬운 정도 — 높음(예약·저장 가능) / 보통 / 낮음(효과 작음) / 불가(시간 이동 효과 없음)
# mode : plan(잉여 시간에 맞춰 돌리기) / precondition(미리 냉·난방 해 두기) / store(낮에 데워 저장) / ask(종류 확인) / small(작은 기기)
APPLIANCES: dict[str, dict] = {
    "전기차": {
        "aliases": ["전기차", "전기 차", "ev", "충전", "차 배터리", "배터리", "아이오닉", "코나", "니로", "레이", "ev6", "ev3", "ev9", "테슬라"],
        "kwh": None, "hours": None, "shift": "높음", "mode": "plan",
        "how": "충전 시작 시간을 옮기거나, 차·충전기의 예약 충전 기능을 쓰세요.",
        "basis": "공인·제조사", "source": "현대자동차·기아 배터리 정보 공개 자료(배터리 팩 용량)",
        "note": "필요 전력량 = 배터리 용량 × (채울 비율). 공용 완속 충전기 7kW 기준으로 시간 계산(가정)",
    },
    "세탁기": {
        "reserve": True,   # 예약·타이머로 집에 없어도 돌릴 수 있음
        "aliases": ["세탁기", "빨래", "세탁"],
        "kwh": (0.4, 1.0), "hours": (1.0, 2.0), "shift": "높음", "mode": "plan",
        "how": "세탁기 '예약' 기능으로 끝나는 시간을 맞춰 두면 편해요.",
        "basis": "공인·제조사",
        "source": "한국에너지공단 효율등급 기준(드럼세탁기 1등급 최저기준 45.8Wh/kg, 제조사 표기) · 세탁건조기 1회 세탁 432.3Wh(한국에너지공단 등록값, 삼성전자 뉴스룸)",
        "note": "세탁 용량·코스·온수 사용에 따라 다름",
    },
    "건조기": {
        "reserve": True,   # 예약·타이머로 집에 없어도 돌릴 수 있음
        "aliases": ["건조기", "빨래 말리", "옷 말리"],
        "kwh": (2.0, 3.6), "hours": (1.7, 3.1), "shift": "높음", "mode": "plan",
        "how": "예약 기능이 있으면 잉여 시간에 끝나도록 맞추세요. 세탁기와 이어서 돌리면 시간이 길어지니 함께 계산해요.",
        "basis": "공인·제조사",
        "source": "삼성전자 20kg 건조기 1회 1,989.1Wh(한국에너지공단 자료 인용) · 삼성전자서비스 '1회 건조 약 3.6kWh' · 한국소비자원 시험 1회 건조 1시간 43분~3시간 6분",
        "note": "히트펌프식·용량에 따라 다름",
    },
    "식기세척기": {
        "reserve": True,   # 예약·타이머로 집에 없어도 돌릴 수 있음
        "aliases": ["식기세척기", "식세기", "설거지"],
        "kwh": (0.9, 1.0), "hours": (1.1, 2.0), "shift": "높음", "mode": "plan",
        "how": "예약(지연 시작) 기능으로 잉여 시간에 돌아가게 하세요.",
        "basis": "공인·제조사",
        "source": "12인용 표준코스 1회 0.97kWh(삼성전자)·1.0kWh(LG전자) 제조사 표시값 · 한국소비자원 시험 표준코스 1시간 6분~2시간",
        "note": "자동·고온 코스는 더 쓸 수 있음",
    },
    "히트펌프": {
        "reserve": True,   # 예약·타이머로 집에 없어도 돌릴 수 있음
        "aliases": ["히트펌프", "축열조", "공기열"],
        "kwh": None, "hours": (2.0, 5.0), "shift": "높음", "mode": "store",
        "how": "남는 전기가 많은 낮에 축열조(물탱크)를 데워 두고 저녁·밤에 그 열을 쓰세요. 설치업체 앱·타이머로 운전 시간을 정할 수 있는지 확인하세요.",
        "basis": "공인·제조사",
        "source": "제주 생활 속 히트펌프 보급사업 지원 설비: 20kW 미만 공기열 히트펌프 + 축열조 300~500L + VPP 설비 (한국냉난방공조신문 2026-09)",
        "note": "필요 전력량은 집 크기·날씨·설정 온도에 따라 크게 달라 숫자로 말하지 않음",
    },
    "전기온수기": {
        "reserve": True,   # 예약·타이머로 집에 없어도 돌릴 수 있음
        "aliases": ["전기온수기", "온수기", "온수"],
        "kwh": (2.0, 3.0), "hours": (1.0, 2.0), "shift": "높음", "mode": "store",
        "how": "저장식은 물을 미리 데워 두는 방식이라, 데우는 시간을 낮으로 옮기면 좋아요(타이머가 있는 제품).",
        "basis": "계산값",
        "source": "계산: 물 50L를 약 45℃ 데우는 데 필요한 열 ≈ 2.6kWh (물의 비열 4.186kJ/kg·℃)",
        "note": "50L 저장식, 히터 출력 1.5~3kW 가정. 순간식은 시간 이동 불가",
    },
    "전기보일러": {
        "aliases": ["전기보일러", "축열식 보일러", "심야전기 보일러"],
        "kwh": None, "hours": None, "shift": "보통", "mode": "store",
        "how": "축열식이면 낮에 물·축열재를 데워 두고 저녁에 쓰세요. 축열 기능이 없으면 필요할 때 쓰는 기기라 이동 효과가 작아요.",
        "basis": "제품마다 다름", "source": "제품 사양에 따라 크게 다름 — 제품 라벨·설명서 확인",
        "note": "",
    },
    "음식물처리기": {
        "aliases": ["음식물처리기", "음식물 처리기", "음쓰", "음식물 쓰레기"],
        "kwh": (1.0, 2.0), "hours": (3.0, 4.0), "shift": "높음", "mode": "plan",
        "how": "모아 두었다가 잉여 시간에 '건조' 시작 버튼을 누르세요.",
        "basis": "제품마다 다름",
        "source": "건조식 예: 500W 제품 4시간 ≈ 2kWh(리뷰 계산) · 쾌속모드 3시간 이내 처리(제품 기사)",
        "note": "건조식 기준 대략값. 미생물식은 계속 켜 두는 방식이라 이동 효과 작음",
    },
    "의류관리기": {
        "reserve": True,   # 예약·타이머로 집에 없어도 돌릴 수 있음
        "aliases": ["의류관리기", "스타일러", "에어드레서", "슈드레서"],
        "kwh": None, "hours": (1.1, 1.5), "shift": "보통", "mode": "plan",
        "how": "예약 기능으로 잉여 시간에 돌리세요. 1회 소비전력량은 제품 앞면 라벨에 적혀 있어요(2025년 7월부터 표시 의무).",
        "basis": "공인·제조사",
        "source": "한국소비자원 시험 최대용량 건조 1시간 7분~1시간 30분 · 효율관리기자재 운용규정 개정(의류관리기 1회 소비전력량 표시)",
        "note": "",
    },
    "전기밥솥": {
        "reserve": True,   # 예약·타이머로 집에 없어도 돌릴 수 있음
        "aliases": ["밥솥", "전기밥솥", "취사", "밥 하"],
        "kwh": None, "hours": (0.5, 1.0), "shift": "낮음", "mode": "small",
        "how": "예약 취사로 낮에 밥을 지어 두는 정도예요. 전기를 많이 쓰는 기기는 아니라 효과는 작아요.",
        "basis": "제품마다 다름", "source": "제품 라벨 확인", "note": "",
    },
    "작은 충전기기": {
        "aliases": ["킥보드", "전동킥보드", "전기자전거", "로봇청소기", "보조배터리", "노트북", "휴대폰", "핸드폰"],
        "kwh": None, "hours": None, "shift": "낮음", "mode": "small",
        "how": "하나하나는 전기를 조금 써서 효과는 작지만, '충전은 낮에' 습관을 들이는 데 좋아요.",
        "basis": "제품마다 다름", "source": "제품 라벨 확인", "note": "",
    },
    "에어컨": {
        "aliases": ["에어컨", "냉방", "에어콘"],
        "kwh_per_hour": (0.5, 2.2), "kwh": None, "hours": None, "shift": "보통", "mode": "precondition",
        "how": "필요할 때 쓰는 기기라 통째로 옮기기는 어려워요. 남는 전기가 많은 낮에 조금 더 시원하게 해 두고, 저녁(4~10시)에는 약하게 쓰는 방법이 있어요.",
        "basis": "공인·제조사",
        "source": "정격 냉방 소비전력: 벽걸이 510W·스탠드 2,200W (LG전자 제품 사양) · 스탠드 1.6kW급(캐리어 1등급 모델)",
        "note": "시간당 사용 전력량(정격 기준). 실제는 인버터 운전으로 더 적을 수 있음",
    },
    "전기히터": {
        "aliases": ["전기히터", "히터", "온풍기", "난로", "전기난로", "라디에이터"],
        "kwh": None, "hours": None, "shift": "낮음", "mode": "precondition",
        "how": "필요할 때 쓰는 기기예요. 낮에 미리 방을 데워 두는 정도만 가능하고 효과는 크지 않아요.",
        "basis": "제품마다 다름", "source": "제품 라벨의 소비전력 확인", "note": "",
    },
    "전기장판": {
        "aliases": ["전기장판", "온수매트", "전기매트", "전기요"],
        "kwh": None, "hours": None, "shift": "불가", "mode": "small",
        "how": "잘 때 쓰는 기기라 시간을 옮기기 어렵고, 쓰는 전기도 작아서 억지로 옮길 필요는 없어요.",
        "basis": "제품마다 다름", "source": "제품 라벨 확인", "note": "",
    },
    "보일러": {
        "aliases": ["보일러", "난방"],
        "kwh": None, "hours": None, "shift": "불가", "mode": "ask",
        "how": "전기보일러인지, 기름·가스 보일러인지에 따라 달라요. 기름·가스 보일러는 연료를 태워 난방해서 전기를 거의 쓰지 않으니, 시간을 옮겨도 남는 전기를 쓰는 효과는 없어요.",
        "basis": "공인·제조사",
        "source": "제주 도시가스 보급률 18.5%, 가정·상업 에너지 소비의 약 32%가 석유류 (서울신문 2026-03-12) · 제주 생활 속 히트펌프 보급사업(기름·가스 보일러 → 히트펌프 교체 지원)",
        "note": "기름·가스 보일러 가구에는 제주도 히트펌프 교체 지원 사업을 안내",
    },
    "옮기기 어려운 기기": {
        "aliases": ["냉장고", "김치냉장고", "인덕션", "전자레인지", "에어프라이어", "tv", "티비", "텔레비전", "컴퓨터", "공유기", "정수기", "조명", "전등"],
        "kwh": None, "hours": None, "shift": "불가", "mode": "none",
        "how": "늘 켜 두거나 필요할 때 바로 써야 하는 기기라 시간을 옮기기 어려워요. 억지로 옮기지 않아도 돼요. "
               "대신 세탁기·건조기·식기세척기·전기차 충전처럼 예약할 수 있는 기기를 낮으로 옮기면 효과가 커요.",
        "basis": "제품마다 다름", "source": "기기 특성", "note": "",
    },
}

# 전기차 배터리 용량(kWh) — 현대·기아 공개 자료
EV_MODELS = {
    "레이": 35.2, "레이ev": 35.2,
    "니로": 64.8, "니로ev": 64.8, "코나": 64.8, "코나 일렉트릭": 64.8,
    "아이오닉5": 84.0, "아이오닉 5": 84.0, "ev6": 84.0, "아이오닉6": 84.0,
}
EV_DEFAULT_KWH = 64.8          # 차종을 모르면 중형(니로EV·코나) 기준
SLOW_CHARGER_KW = 7.0          # 공용 완속 충전기 일반 출력(가정)
QUICK_CHARGER_KW = 50.0        # 공용 급속 충전기 일반 출력(가정, 80%까지는 출력 유지로 봄)
EV_SOURCE = "배터리 용량: 레이EV 35.2·니로EV 64.8·아이오닉5/EV6 84.0kWh (현대자동차·기아 공개 자료)"

# 기본 사용 가능 시간대 (사람이 깨어 있는 시간, 시작 시각 기준)
DEFAULT_EARLIEST, DEFAULT_LATEST = 6, 22


def find_appliance(text: str) -> str | None:
    """문장에서 기기 찾기. 긴 별칭부터 맞춰 '전기보일러'를 '보일러'보다 먼저 잡음."""
    q = (text or "").replace(" ", "").lower()
    pairs = sorted(((a.replace(" ", "").lower(), k) for k, v in APPLIANCES.items() for a in v["aliases"] + [k]),
                   key=lambda x: -len(x[0]))
    for alias, key in pairs:
        if alias and alias in q:
            return key
    return None


def find_all(text: str) -> list[str]:
    """문장에 나온 기기를 모두 찾음 ('빨래랑 식기세척기' → ['세탁기', '식기세척기']). 긴 별칭이 짧은 별칭을 덮음."""
    q = (text or "").replace(" ", "").lower()
    pairs = sorted(((a.replace(" ", "").lower(), k) for k, v in APPLIANCES.items() for a in v["aliases"] + [k]),
                   key=lambda x: -len(x[0]))
    found, used = [], [False] * len(q)
    for alias, key in pairs:
        i = q.find(alias)
        while alias and i >= 0:
            if not any(used[i:i + len(alias)]):
                for j in range(i, i + len(alias)):
                    used[j] = True
                if key not in found:
                    found.append((i, key))
            i = q.find(alias, i + 1)
    return [k for _, k in sorted(set(found))]


def ev_energy(battery_percent: float | None, car: str = "", target_percent: float = 80) -> dict:
    """전기차 필요 전력량·완속 충전 시간. battery_percent 가 없으면 '반쯤(50%)'으로 가정하고 알려 줌."""
    cap, cap_note = EV_DEFAULT_KWH, "차종을 몰라 중형(니로EV·코나, 64.8kWh) 기준"
    c = (car or "").replace(" ", "").lower()
    for name, kwh in sorted(EV_MODELS.items(), key=lambda x: -len(x[0])):
        if name.replace(" ", "") in c:
            cap, cap_note = kwh, f"{name} 배터리 {kwh}kWh 기준"
            break
    assumed = battery_percent is None
    now = 50.0 if assumed else max(0.0, min(100.0, float(battery_percent)))
    need = max(0.0, cap * (target_percent - now) / 100)
    hours = need / SLOW_CHARGER_KW
    return {"battery_kwh": cap, "battery_note": cap_note, "now_percent": now, "assumed_percent": assumed,
            "target_percent": target_percent, "kwh": round(need, 1),
            "hours": round(hours, 1), "hours_ceil": max(1, math.ceil(hours)),
            "quick_hours": round(need / QUICK_CHARGER_KW, 2),
            "assumption": f"공용 완속 충전기 {SLOW_CHARGER_KW:g}kW, {int(now)}% → {int(target_percent)}%까지"}
