"""竞技场控制台: '/' → 设置当前角色 HP (数字输入 / 方向键微调 / 夹紧 1..max)."""
import os

import pytest

os.environ.setdefault("SDL_VIDEODRIVER", "dummy")
os.environ.setdefault("SDL_AUDIODRIVER", "dummy")
import pygame  # noqa: E402


@pytest.fixture
def sc():
    pygame.init()
    surf = pygame.display.set_mode((800, 600))
    from core.audio_manager import AudioManager
    from scenes.arena.battle_scene import ArenaBattleScene
    import scenes.arena.roster as R
    s = ArenaBattleScene(surf, AudioManager(), player_names=["孙悟空"],
                         enemy_names=[R.ENEMY_ROSTER[0]], return_scene=None)
    if hasattr(s, "on_enter"):
        s.on_enter()
    return s


def _key(s, k):
    s.handle_event(pygame.event.Event(pygame.KEYDOWN, key=k, mod=0, unicode="", scancode=0))
    s.draw()


def _open_hp(s):
    _key(s, pygame.K_SLASH)
    _key(s, pygame.K_DOWN)          # 第 2 项 = 设置当前角色 HP
    _key(s, pygame.K_RETURN)
    assert s._console_level == 2


def test_type_digits_sets_hp(sc):
    u = sc.battle.current
    _open_hp(sc)
    for _ in range(6):
        _key(sc, pygame.K_BACKSPACE)
    for k in (pygame.K_1, pygame.K_7):
        _key(sc, k)
    _key(sc, pygame.K_RETURN)
    assert u.hp == 17 and u.display_hp == 17
    assert not sc._console_open


def test_arrows_and_clamp(sc):
    u = sc.battle.current
    _open_hp(sc)
    _key(sc, pygame.K_UP)           # 满血 +10 → 夹紧到上限
    assert sc._hp_value() == u.max_hp
    for _ in range(6):
        _key(sc, pygame.K_BACKSPACE)
    _key(sc, pygame.K_0)
    _key(sc, pygame.K_RETURN)       # 0 → 夹到 1 (行动中角色不能死在自己回合)
    assert u.hp == 1 and u.alive


def test_esc_returns_to_top(sc):
    hp0 = sc.battle.current.hp
    _open_hp(sc)
    _key(sc, pygame.K_ESCAPE)
    assert sc._console_open and sc._console_level == 0
    assert sc.battle.current.hp == hp0
