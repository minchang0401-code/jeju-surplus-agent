"""이용 안내의 닫기·표시 설정·브라우저 응답 순서 검증."""
from types import SimpleNamespace

import pytest
import onboarding


class State(dict):
    __getattr__ = dict.__getitem__
    __setattr__ = dict.__setitem__


@pytest.fixture
def state(monkeypatch):
    state = State()
    monkeypatch.setattr(onboarding.st, 'session_state', state)
    return state


def test_dismiss_does_not_hide_future_visits(state):
    state.onboarding_open = True
    onboarding._dismiss_onboarding()
    assert state.onboarding_done and not state.onboarding_open
    assert not state.get('onboarding_hidden', False)


def test_hidden_preference_can_be_set_and_cleared(state):
    onboarding._set_hidden(True)
    first = state.onboarding_preference_write
    assert state.onboarding_hidden and first['hidden']
    onboarding._set_hidden(False)
    assert not state.onboarding_hidden
    assert state.onboarding_preference_write['revision'] != first['revision']


@pytest.mark.parametrize('ready,hidden,manual,expected',[
    (False,False,False,False),
    (True,False,False,True),
    (True,True,False,False),
    (True,True,True,True),
])
def test_open_respects_loaded_preference_except_manual_replay(state,monkeypatch,ready,hidden,manual,expected):
    state.update(onboarding_preferences_ready=ready,onboarding_hidden=hidden,onboarding_open=manual)
    calls=[]
    monkeypatch.setattr(onboarding,'_onboarding_dialog',lambda places:calls.append(places))
    onboarding.render_onboarding(['애월'])
    assert bool(calls)==expected


def test_stale_browser_ack_does_not_undo_recent_checkbox_change(state,monkeypatch):
    onboarding._set_hidden(True)
    monkeypatch.setattr(onboarding,'_preference_store',lambda **kw:{'ready':True,'hidden':False,'available':True,'revision':'old'})
    onboarding.sync_onboarding_preference()
    assert state.onboarding_hidden
    rev=state.onboarding_preference_write['revision']
    monkeypatch.setattr(onboarding,'_preference_store',lambda **kw:{'ready':True,'hidden':True,'available':True,'revision':rev})
    onboarding.sync_onboarding_preference()
    assert state.onboarding_preferences_ready and state.onboarding_hidden


def test_storage_failure_is_exposed_without_blocking_use(state,monkeypatch):
    monkeypatch.setattr(onboarding,'_preference_store',lambda **kw:{'ready':True,'hidden':False,'available':False,'revision':''})
    onboarding.sync_onboarding_preference()
    assert state.onboarding_preferences_ready and not state.onboarding_storage_available


def test_navigation_changes_only_step_and_keeps_dialog_open(state,monkeypatch):
    state.update(onboarding_step=0,onboarding_open=True,onboarding_done=False)
    # 다음·이전은 전체 앱 재실행 없이 팝업 내부의 상태만 바꾼다.
    monkeypatch.setattr(onboarding.st,'rerun',lambda **kw:pytest.fail('navigation triggered a full rerun'))
    onboarding._next_step()
    assert state.onboarding_step==1 and state.onboarding_open and not state.onboarding_done
    onboarding._previous_step()
    assert state.onboarding_step==0 and state.onboarding_open


def test_next_validates_and_saves_profile_before_advancing(state):
    import user_profile as up
    state.update(onboarding_step=1,profile=up.empty(),intro_area='애월',intro_car='없음 / 모름',
                 intro_away=True,intro_start=18,intro_end=9)
    onboarding._next_step()
    assert state.onboarding_step==1 and state.onboarding_validation_error
    state.intro_start=9;state.intro_end=18
    onboarding._next_step()
    assert state.onboarding_step==2 and state.profile['area']=='애월'
    assert state.profile['work_start']==9 and 'onboarding_validation_error' not in state
    onboarding._next_step()
    assert state.onboarding_done and not state.onboarding_open


def test_previous_keeps_unsaved_settings_as_draft(state):
    state.update(onboarding_step=1, intro_area='애월', intro_car='없음 / 모름',
                 intro_away=True, intro_start=10, intro_end=19)
    onboarding._previous_step()
    for key in ('intro_area', 'intro_car', 'intro_away', 'intro_start', 'intro_end'):
        state.pop(key)
    assert state.onboarding_draft['intro_area']=='애월'
    assert state.onboarding_draft['intro_start']==10
    assert state.onboarding_step==0


def test_hide_toggle_keeps_dialog_open_without_full_rerun(state,monkeypatch):
    state.update(intro_dont_show=True,onboarding_open=True,onboarding_step=1)
    monkeypatch.setattr(onboarding.st,'rerun',lambda **kw:pytest.fail('full rerun'))
    onboarding._toggle_hidden()
    assert state.onboarding_hidden and state.onboarding_open and state.onboarding_step==1
