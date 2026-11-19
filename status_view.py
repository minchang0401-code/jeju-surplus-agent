"""데이터 보유·갱신 상태와 연결 설정을 구분해 일관된 형식으로 표시한다."""
from html import escape

import streamlit as st


HUB_LABELS = {
    579: '일별 기상', 862: '전기차 충전소', 1225: '일별 충전 이력',
    1226: '월별 충전 이력', 877: '일간 기후', 123: '태양광 등록 현황', 472: '풍력발전 현황',
}


def _row(label, state, detail, tone='neutral'):
    return dict(label=label, state=state, detail=detail, tone=tone)


def _forecast_row(label, result, available, issued=None):
    suffix = f'발표 시각 {issued}' if issued else '발표 시각 확인 필요'
    if result in ('fresh', 'updated') and available:
        return _row(label, '최신', suffix, 'ready')
    if result == 'failed':
        detail = f'갱신 실패 · 저장 자료 사용 · {suffix}' if available else '갱신 실패 · 사용할 저장 자료 없음'
        return _row(label, '갱신 실패', detail, 'attention')
    if available:
        return _row(label, '저장 자료', suffix)
    return _row(label, '자료 없음', '수집된 예보가 없습니다.')


def build_status_groups(status, fresh, llm, *, weather_configured=False, mid_available=False, mid_issued=None):
    available = status.get('available', {})
    llm_on = bool(llm.get('on'))
    needs_config = not llm_on and any(word in llm.get('text', '') for word in ('지원하지 않는', '없어요'))
    connections = [
        _row('AI 응답', '설정됨' if llm_on else ('설정 확인' if needs_config else '미설정'),
             'AI 모델을 사용하도록 설정했습니다.' if llm_on else '기본 추천 방식으로 응답합니다.',
             'ready' if llm_on else ('attention' if needs_config else 'neutral')),
        _row('기상예보 API', '설정됨' if weather_configured else '미설정',
             '인증 정보가 등록되어 있습니다.' if weather_configured else '저장된 예보 자료를 사용합니다.',
             'ready' if weather_configured else 'neutral'),
    ]
    last_date = status.get('label_last_date')
    if not last_date:
        price = _row('전력가격 기록', '자료 없음', '확인된 전력가격 자료가 없습니다.')
    elif status.get('labels_stale'):
        price = _row('전력가격 기록', '갱신 필요', f'전력거래소 EPSIS · 기준일 {last_date}', 'attention')
    else:
        price = _row('전력가격 기록', '보유', f'전력거래소 EPSIS · 기준일 {last_date}', 'ready')
    forecasts = [price,
        _row('예측 모델', '보유' if available.get('학습된 모델') else '자료 없음', '잉여전력 가능성 예측에 사용',
             'ready' if available.get('학습된 모델') else 'neutral'),
        _row('기상 관측', '보유' if available.get('기상청 관측(학습)') else '자료 없음', '기상청 · 모델 학습에 사용',
             'ready' if available.get('기상청 관측(학습)') else 'neutral'),
        _forecast_row('단기 기상예보', fresh.get('status'), bool(available.get('기상청 단기예보(예측)')), fresh.get('issued_at')),
        _forecast_row('중기 기상예보', fresh.get('mid'), mid_available, mid_issued),
    ]
    hubs = []
    for no, label in HUB_LABELS.items():
        has_data = any(value for key, value in available.items() if key.startswith(f'허브 {no} '))
        hubs.append(_row(label, '보유' if has_data else '자료 없음', f'제주데이터허브 · 데이터 {no}',
                         'ready' if has_data else 'neutral'))
    return [('연결 설정', connections), ('예측 자료', forecasts), ('제주데이터허브 자료', hubs)]


def render_status_panel(status, fresh, llm):
    from config import FORECAST_MID_CSV, get_key
    mid_issued = None
    if FORECAST_MID_CSV.exists():
        import pandas as pd
        try:
            base = pd.read_csv(FORECAST_MID_CSV, usecols=['base'], dtype=str)['base'].iloc[0]
            mid_issued = pd.to_datetime(base[:12], format='%Y%m%d%H%M').strftime('%Y-%m-%d %H:%M')
        except (ValueError, KeyError, IndexError, OSError):
            pass
    groups = build_status_groups(status, fresh, llm,
                                 weather_configured=bool(get_key('DATA_GO_KR_KEY')),
                                 mid_available=FORECAST_MID_CSV.exists(), mid_issued=mid_issued)
    for title, rows in groups:
        items = ''.join(
            '<li><div class="status-line">'
            f'<span>{escape(row["label"])}</span><span class="status-value {row["tone"]}">{escape(row["state"])}</span>'
            f'</div><p>{escape(row["detail"])}</p></li>' for row in rows)
        st.html(f'<section class="status-group"><h4>{escape(title)}</h4><ul>{items}</ul></section>')
    st.caption('‘설정됨’은 인증 정보 등록 상태입니다. 실제 API 호출 성공 여부와는 구분됩니다.')
