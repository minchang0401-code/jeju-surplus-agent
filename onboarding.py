"""닫을 수 있는 이용 안내 모달과 브라우저별 다시 보지 않기 설정."""
from html import escape
from pathlib import Path
from uuid import uuid4

import streamlit as st
import streamlit.components.v1 as components
import user_profile as up


_preference_store = components.declare_component(
    'onboarding_preferences', path=str(Path(__file__).parent / 'components' / 'onboarding_preferences'))


def sync_onboarding_preference(key="onboarding_preferences"):
    """브라우저 저장소와 연결. 계정·생활정보는 저장하지 않고 안내 숨김 여부만 저장."""
    pending = st.session_state.get('onboarding_preference_write', {})
    result = _preference_store(hidden=pending.get('hidden'), revision=pending.get('revision', ''),
                               key=key, default=None)
    if isinstance(result, dict) and result.get('ready'):
        if not pending or result.get('revision') == pending.get('revision'):
            st.session_state.onboarding_preferences_ready = True
            st.session_state.onboarding_hidden = bool(result.get('hidden', False))
            st.session_state.onboarding_storage_available = bool(result.get('available', False))


def _set_hidden(hidden):
    st.session_state.onboarding_hidden = bool(hidden)
    st.session_state.onboarding_preference_write = {'hidden': bool(hidden), 'revision': uuid4().hex}


def _dismiss_onboarding():
    st.session_state.onboarding_done = True
    st.session_state.onboarding_open = False


def _remember_settings():
    draft = dict(st.session_state.get('onboarding_draft', {}))
    for key in ('intro_area', 'intro_car', 'intro_away', 'intro_start', 'intro_end'):
        if key in st.session_state:
            draft[key] = st.session_state[key]
    st.session_state.onboarding_draft = draft


def _toggle_hidden():
    _set_hidden(st.session_state.intro_dont_show)


def _previous_step():
    if st.session_state.get('onboarding_step') == 1:
        _remember_settings()
    st.session_state.onboarding_step = max(0, st.session_state.get('onboarding_step', 0) - 1)
    st.session_state.pop('onboarding_validation_error', None)
    if st.session_state.onboarding_step == 1:
        st.session_state.onboarding_restore_draft = True


def _next_step():
    """버튼 콜백에서 상태를 먼저 변경하면 팝업 본문만 한 번 다시 그려진다."""
    step = st.session_state.get('onboarding_step', 0)
    st.session_state.pop('onboarding_validation_error', None)
    if step == 1:
        _remember_settings()
        if st.session_state.intro_away and st.session_state.intro_end <= st.session_state.intro_start:
            st.session_state.onboarding_validation_error = '돌아오는 시각을 나가는 시각보다 늦게 골라주세요.'
            return
        profile = dict(st.session_state.profile)
        profile['area'] = '' if st.session_state.intro_area == '선택 안 함' else st.session_state.intro_area
        profile['car'] = up.CARS[st.session_state.intro_car]
        profile['work_start'] = st.session_state.intro_start if st.session_state.intro_away else None
        profile['work_end'] = st.session_state.intro_end if st.session_state.intro_away else None
        st.session_state.profile = profile
    if step == 2:
        _dismiss_onboarding()
    else:
        st.session_state.onboarding_step = step + 1
        if step == 0:
            st.session_state.onboarding_restore_draft = True


def _step_indicator(step):
    labels = ['무엇을 할 수 있나요?', '내 생활 설정', '체험 준비 완료']
    items = []
    for i, label in enumerate(labels):
        state = 'current' if i == step else ('complete' if i < step else '')
        mark = '✓' if i < step else str(i + 1)
        current = ' aria-current="step"' if i == step else ''
        items.append(f'<li class="{state}"{current}><span class="intro-step-number">{mark}</span><span>{label}</span></li>')
    st.markdown('<nav class="intro-steps" aria-label="이용 안내 단계"><ol>' + ''.join(items) + '</ol></nav>', unsafe_allow_html=True)


def _intro_overview():
    st.markdown('<div class="intro-eyebrow">제주의 에너지를 내 생활에</div>'
                '<h3 class="intro-heading">전기 쓰기 좋은 시간,<br>쉽게 찾아보세요.</h3>'
                '<p class="intro-description">제주의 재생에너지 예측을 바탕으로<br>내 일정에 맞는 전기 사용 시간을 함께 찾아드려요.</p>', unsafe_allow_html=True)
    st.markdown('''<div class="intro-features">
      <div class="intro-feature"><span class="intro-feature-icon" aria-hidden="true">◷</span><strong>언제 쓸까요?</strong><p>빨래·충전하기 좋은<br>시간을 확인해요.</p></div>
      <div class="intro-feature"><span class="intro-feature-icon" aria-hidden="true">⌖</span><strong>어디서 충전할까요?</strong><p>지도에서 내 동네<br>충전소를 찾아요.</p></div>
      <div class="intro-feature"><span class="intro-feature-icon" aria-hidden="true">✦</span><strong>내 일정에는요?</strong><p>AI에게 물어보고<br>사용 계획을 세워요.</p></div>
    </div>''', unsafe_allow_html=True)
    st.caption('로그인 없이 체험할 수 있어요. 원하면 설정 없이 바로 둘러보세요.')


def _intro_settings(places):
    st.markdown('<h3 class="intro-heading">내 생활에 맞춰 추천받으세요.</h3>'
                '<p class="intro-description">모두 선택 사항이에요. 나중에 ‘내 생활 설정’에서 바꿀 수 있어요.</p>', unsafe_allow_html=True)
    profile = st.session_state.profile
    areas = ['선택 안 함'] + [p for p in places if p not in ('공항', '시청', '터미널', '도청')]
    cars = list(up.CARS)
    car = next((k for k, v in up.CARS.items() if v == profile['car']), cars[0])
    defaults = {'intro_area': profile['area'] if profile['area'] in areas else '선택 안 함',
                'intro_car': car, 'intro_away': profile['work_start'] is not None,
                'intro_start': profile['work_start'] if profile['work_start'] is not None else 9,
                'intro_end': profile['work_end'] if profile['work_end'] is not None else 18}
    draft = st.session_state.get('onboarding_draft', {})
    restore = st.session_state.pop('onboarding_restore_draft', False)
    for key, value in defaults.items():
        if restore or key not in st.session_state:
            st.session_state[key] = draft.get(key, value)
    left, right = st.columns(2)
    left.selectbox('주로 생활하는 동네', areas, key='intro_area', on_change=_remember_settings, help='가까운 충전소를 찾을 때 기준으로 사용해요.')
    right.selectbox('이용하는 전기차', cars, key='intro_car', on_change=_remember_settings,
                    help='전기차가 있으면 차종에 맞춰 필요한 충전시간을 계산해요.')
    st.checkbox('평일에 정해진 외출시간이 있어요', key='intro_away', on_change=_remember_settings)
    if st.session_state.intro_away:
        left, right = st.columns(2)
        left.selectbox('집에서 나가는 시간', list(range(24)), format_func=lambda h: f'{h}시', key='intro_start', on_change=_remember_settings)
        right.selectbox('집에 돌아오는 시간', list(range(1, 25)), format_func=lambda h: f'{h}시', key='intro_end', on_change=_remember_settings)
        st.caption('집에 없는 시간을 반영해 가전 사용과 충전 시간을 추천해요.')
    else:
        st.caption('외출시간이 일정하지 않으면 선택하지 않아도 괜찮아요.')
    st.markdown('<div class="intro-note">선택한 정보는 현재 게스트 세션에만 유지돼요.</div>', unsafe_allow_html=True)


def _intro_ready():
    profile = st.session_state.profile
    area = escape(profile.get('area') or '제주 전체')
    car = escape(profile.get('car') or '전기차 설정 안 함')
    away = f"평일 {profile['work_start']}~{profile['work_end']}시 외출" if profile.get('work_start') is not None else '외출시간 설정 안 함'
    st.markdown('<div class="intro-eyebrow">준비가 끝났어요</div>'
                '<h3 class="intro-heading">첫 추천부터 확인해볼까요?</h3>'
                f'<div class="intro-summary"><span>⌖ {area}</span><span>{car}</span><span>{away}</span></div>', unsafe_allow_html=True)
    st.markdown('''<div class="intro-start-card"><span class="intro-small-label">시작은 이렇게</span>
      <strong>‘이번 주 언제가 좋아?’를 눌러보세요.</strong>
      <p>메인 화면의 ‘생활 계획’에서<br>빨래와 식기세척기를 돌릴 추천 시간을 확인할 수 있어요.</p>
    </div>''', unsafe_allow_html=True)
    with st.expander('예측과 지도는 이렇게 읽어주세요'):
        st.markdown('- **예측은 참고 정보예요.** SMP가 0원 이하일 가능성이며, 실제 잉여 전력량이나 요금 할인을 뜻하지 않아요.\n'
                    '- **지도 색은 제주 전체 예측이에요.** 원 크기는 지역별 재생에너지 설비 규모예요.\n'
                    '- **답변의 근거도 확인하세요.** AI 답변 아래에서 사용한 데이터와 계산 근거를 볼 수 있어요.')


@st.dialog('제주 잉여전력 도우미에 오신 걸 환영해요!', width='medium', dismissible=True, on_dismiss=_dismiss_onboarding)
def _onboarding_dialog(places):
    if st.session_state.get('onboarding_done', False):
        st.rerun()
    st.markdown((Path(__file__).parent / 'onboarding.css').read_text(), unsafe_allow_html=True)
    step = st.session_state.get('onboarding_step', 0)
    _step_indicator(step)
    with st.container(key='onboarding_stage'):
        if step == 0:
            _intro_overview()
        elif step == 1:
            _intro_settings(places)
        else:
            _intro_ready()
        if st.session_state.get('onboarding_validation_error'):
            st.error(st.session_state.onboarding_validation_error)
    st.divider()
    sync_onboarding_preference(key='onboarding_preferences_dialog')
    st.checkbox('다시 보지 않기', value=st.session_state.get('onboarding_hidden', False), key='intro_dont_show', on_change=_toggle_hidden,
                help='이 브라우저에 저장돼요. 사이드바의 ‘처음 이용 안내 다시 보기’로 언제든 다시 열 수 있어요.')
    if st.session_state.get('onboarding_storage_available') is False:
        st.caption('브라우저 저장소를 사용할 수 없어 이번 접속 동안만 설정이 유지돼요.')
    with st.container(key='onboarding_footer'):
        back, skip, next_ = st.columns([1, 1.3, 2])
        back.button('이전', disabled=step == 0, key='intro_back', width='stretch', on_click=_previous_step)
        skip.button('바로 둘러보기', key='intro_skip', width='stretch', on_click=_dismiss_onboarding)
        labels = ['내 생활 설정하기 →', '설정 확인하기 →', '체험 시작하기 →']
        next_.button(labels[step], type='primary', key='intro_next', width='stretch', on_click=_next_step)

def render_onboarding(places):
    if st.session_state.get('onboarding_done', False):
        return
    if not st.session_state.get('onboarding_open', False):
        if not st.session_state.get('onboarding_preferences_ready', False):
            return  # 저장된 설정을 읽기 전에는 잠깐 팝업이 나타나는 현상도 방지
        if st.session_state.get('onboarding_hidden', False):
            return
        st.session_state.onboarding_open = True
    _onboarding_dialog(places)
