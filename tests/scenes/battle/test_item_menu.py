"""战斗行动菜单 → 道具: 竞技场 (world_map 是 terrain, 没有 save) 打开道具菜单不能崩 (回归: ESC→道具 AttributeError)."""
import os

import pytest

os.environ.setdefault("SDL_VIDEODRIVER", "dummy")
os.environ.setdefault("SDL_AUDIODRIVER", "dummy")
import pygame  # noqa: E402


@pytest.fixture
def arena_scene():
    pygame.init()
    surf = pygame.display.set_mode((800, 600))
    from core.audio_manager import AudioManager
    from scenes.arena.battle_scene import ArenaBattleScene
    import scenes.arena.roster as R
    sc = ArenaBattleScene(surf, AudioManager(), player_names=["孙悟空"],
                          enemy_names=[R.ENEMY_ROSTER[0]], return_scene=None)
    if hasattr(sc, "on_enter"):
        sc.on_enter()
    return sc


def _step(sc, n=40):
    for _ in range(n):
        sc.update(33)
        sc.draw()


def _until_player_turn(sc, limit=3000):
    """敌人初始行动值随机 (exe 摆阵 rand%20), 可能先手: 推进到玩家回合."""
    from core.battle.data import Phase
    for _ in range(limit):
        if sc.battle.current.is_player and sc.battle.phase == Phase.PLAYER_MOVE:
            break
        sc.update(33)
        sc.draw()
    _step(sc)


def _key(sc, k):
    sc.handle_event(pygame.event.Event(pygame.KEYDOWN, key=k, mod=0, unicode="", scancode=0))
    sc.handle_event(pygame.event.Event(pygame.KEYUP, key=k, mod=0, unicode="", scancode=0))
    _step(sc)


def test_arena_item_menu_opens_and_uses_sandbox_item(arena_scene):
    sc = arena_scene
    _until_player_turn(sc)
    assert sc.battle.current.is_player
    _key(sc, pygame.K_ESCAPE)
    assert sc._menu_open
    _key(sc, pygame.K_LEFT)                 # 道具
    assert sc._item_submenu                 # 菜单开着, draw 没崩
    items = sc.inventory.consumables()
    assert items
    u = sc.battle.current
    u.hp = 1
    _key(sc, pygame.K_RETURN)               # 用第一个消耗品
    assert u.hp > 1
    assert not sc._item_submenu
    assert sum(c for _, c in sc.inventory.consumables()) == sum(c for _, c in items) - 1


def test_item_menu_without_inventory_shows_empty(arena_scene):
    sc = arena_scene
    sc.inventory = None                     # 模拟没有道具栏的宿主
    _until_player_turn(sc)
    _key(sc, pygame.K_ESCAPE)
    _key(sc, pygame.K_LEFT)
    assert sc._item_submenu
    _key(sc, pygame.K_RETURN)               # 无物可用, 不崩
    _key(sc, pygame.K_ESCAPE)               # 回一级
    assert sc._menu_open and not sc._item_submenu
