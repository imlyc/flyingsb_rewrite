"""战斗状态栏 (scenes.battle.status_bar, exe FUN_004ce480): HP 颜色档位, SG 槽宽, 滑入/滑出."""
import os
from types import SimpleNamespace

os.environ.setdefault("SDL_VIDEODRIVER", "dummy")
import pygame  # noqa: E402

from core.battle.data import BattleUnit, Phase  # noqa: E402
from scenes.battle import status_bar as SB  # noqa: E402


def _u(name, hp=100, max_hp=100, mp=0, max_mp=0, sg=0):
    return BattleUnit(name=name, level=5, max_hp=max_hp, hp=hp, max_mp=max_mp, mp=mp, sg=sg,
                      attack=1, defence=1, agile=1, move=1, is_player=True)


def test_hp_color_bands():
    assert SB.hp_pair(51, 100) is SB.PAIR_GOOD          # > 1/2
    assert SB.hp_pair(50, 100) is SB.PAIR_MID           # > 1/4
    assert SB.hp_pair(25, 100) is SB.PAIR_LOW
    assert SB.hp_pair(0, 100) is SB.PAIR_DEAD


def test_bar_layout_and_sg_gauge():
    pygame.init()
    pygame.display.set_mode((800, 600))
    bar = SB.render_bar([_u('孙悟空', max_mp=50, mp=20, sg=0xFFFFFFFF), _u('猪八戒', sg=8), _u('沙悟净', sg=6)])
    assert bar.get_size() == (3 * 128, 80)
    purple = lambda c: c.r > 150                                       # noqa: E731  满槽 (紫底/浅色数字) vs 空槽 (暗)
    # 八戒 SG 8 = 3 格满 (48px): 槽从 (128+40, 42) 起, 第 3 格内是满色, 第 4 格不是
    assert purple(bar.get_at((128 + 40 + 40, 50)))
    assert not purple(bar.get_at((128 + 40 + 56, 50)))
    # 沙悟净 SG 6 = 2 格槽的第 1 格 (16px)
    assert purple(bar.get_at((256 + 40 + 8, 50))) and not purple(bar.get_at((256 + 40 + 24, 50)))


def test_slide_in_and_out():
    sc = SimpleNamespace(battle=SimpleNamespace(phase=Phase.PLAYER_MOVE))
    for _ in range(19):
        SB.tick(sc)
    assert sc._status_bar_h == 76
    SB.tick(sc)
    SB.tick(sc)
    assert sc._status_bar_h == 80
    sc.battle.phase = Phase.VICTORY
    SB.tick(sc)
    assert sc._status_bar_h == 76
