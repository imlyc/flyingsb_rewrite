"""敌人反击: 第 0 招不是 DOIT (玉皇大帝 37 / 暴走族甲 214) 时走招式演出, 回合能正常收尾 (以前落到无 END 的 ATK_UNKNOWN 卡住)."""
from types import SimpleNamespace

import pytest

from core.attack_seq import ATTACK_TICK_MS
from core.battle.data import BattleMap
from core.battle.setup import make_enemy_by_type
from core.battle.tactics import TacticsBattle
from core.exe_rng import ExeRng
from scenes.battle.update import _tick_reactions
from tools.skill_trace import _unit


@pytest.mark.parametrize('etype', [14, 168])
def test_counter_with_spell_move_finishes(etype):
    e = make_enemy_by_type(etype)
    e.x, e.y = 15, 54
    p = _unit('p', 15, 53, is_player=True, agile=99)
    b = TacticsBattle(players=[p], enemies=[e], battle_map=BattleMap(32, 64), rng=ExeRng(1),
                      player_positions=[(15, 53)], enemy_positions=[(15, 54)])
    b._pending_counter = {'unit': e, 'target': p, 'dmg': 7}
    assert b._start_counter()
    stub = SimpleNamespace(battle=b)
    for _ in range(1500):
        b.engine.tick()
        _tick_reactions(stub, ATTACK_TICK_MS)
        if b._pending_turn_end:
            break
    assert b._pending_turn_end
    assert p.hp == p.max_hp - 7
