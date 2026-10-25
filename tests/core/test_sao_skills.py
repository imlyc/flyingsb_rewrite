"""沙悟净 斗轉星移 0x1e / 返荷杖 0x1f: 结印 cast seq (exe @0x67603c) + 自身状态 + 回合递减 + 伤害结算效果."""
import random

import pytest

from core.battle.data import BattleMap, BattleUnit
from core.battle.status import (apply_status, has_status, round_tick, ST_DOUZHUAN, ST_FANHE)
from core.skill_seq import SKILL_SAO_CAST, SKILL_SEQS, SKILL_STATUS_EFFECTS, skill_signal_sounds


def _unit(name, x, y, *, is_player, attack=20, defence=5, agile=10, hp=200):
    u = BattleUnit(name=name, level=1, max_hp=hp, hp=hp, max_mp=999, mp=999, sg=16,
                   attack=attack, defence=defence, agile=agile, move=0, is_player=is_player)
    u.x, u.y = x, y
    return u


def _battle(skill_id=None, enemy_pos=(10, 9)):
    from core.battle.tactics import TacticsBattle
    p = _unit("沙悟净", 10, 10, is_player=True)
    e = _unit("e", *enemy_pos, is_player=False, agile=1)
    b = TacticsBattle(players=[p], enemies=[e], battle_map=BattleMap(20, 20), rng=random.Random(0),
                      player_positions=[(p.x, p.y)], enemy_positions=[(e.x, e.y)])
    p.facing = (0, -1)
    return b, p, e


def _run(b, n=600):
    for _ in range(n):
        b.engine.tick()
        if b._pending_turn_end:
            return True
    return False


def test_cast_seq_matches_exe_bytecode():
    """exe @0x67603c: idle 槽5 帧 0,1,-1000,2,3,4,5,4,3,-1000,2,3,4,5,4,3,2,1,0 (各 4 tick), 不分方向."""
    frames = [t[2] if t[0] == 'idle' else t[1] for t in SKILL_SAO_CAST if t[0] in ('idle', 'jump')]
    assert frames == [0, 1, -1000, 2, 3, 4, 5, 4, 3, -1000, 2, 3, 4, 5, 4, 3, 2, 1, 0]
    assert all(t[1] == 5 and t[3] == 4 for t in SKILL_SAO_CAST if t[0] == 'idle')
    assert SKILL_SAO_CAST[-2:] == [('impact',), ('end',)]
    assert SKILL_SEQS[0x1e] == SKILL_SEQS[0x1f] and len(SKILL_SEQS[0x1e]) == 4
    assert skill_signal_sounds(0x1e, -1000) == (311, -1)
    assert skill_signal_sounds(0x1f, -1000) == (182, -1)


def test_status_round_tick_follows_exe_countdown():
    """FUN_004a3738: 先清位, nibble>0 → -1 并重新置位. N=2 → 施放回合 + 2 回合有效, 第 3 次递减消失."""
    u = _unit("u", 0, 0, is_player=True)
    apply_status(u, ST_DOUZHUAN, 2)
    assert has_status(u, ST_DOUZHUAN)
    round_tick([u]); assert has_status(u, ST_DOUZHUAN) and u.status_turns[ST_DOUZHUAN] == 1
    round_tick([u]); assert has_status(u, ST_DOUZHUAN) and u.status_turns[ST_DOUZHUAN] == 0
    round_tick([u]); assert not has_status(u, ST_DOUZHUAN)
    dead = _unit("d", 1, 1, is_player=True); dead.hp = 0
    apply_status(dead, ST_FANHE, 2)
    round_tick([dead]); assert dead.status_turns[ST_FANHE] == 2, "死亡单位跳过递减"


@pytest.mark.parametrize("sid,bit,snd", [(0x1e, ST_DOUZHUAN, 311), (0x1f, ST_FANHE, 182)])
def test_cast_applies_self_status_with_sound_and_pose(sid, bit, snd):
    b, p, e = _battle()
    played = []
    b.engine.on('sound_play', lambda ent, s: played.append(s))
    assert b.enter_attack_aim(skill_id=sid)
    assert b.aim_cursor == (10, 10), "自身技能 cursor 锁在自己"
    assert b.confirm_attack_aim(), "范围内只有自己也能确认 (目标为我方)"
    seen_pose = False
    for _ in range(600):
        b.engine.tick()
        ent = p.entity
        if ent is not None and (ent.atlas_slot & 0x20000) and (ent.atlas_slot & 0xffff) == 5:
            seen_pose = True
        if b._pending_turn_end:
            break
    assert b._pending_turn_end
    assert seen_pose, "施法期间走 mode2 idle 槽 5 = ps_CSAO05 结印图"
    assert has_status(p, bit) and p.status_turns[bit] == SKILL_STATUS_EFFECTS[sid][1] == 2
    assert played.count(snd) == 2, "seq 两处 jump -1000 各播一次"
    assert e.hp == e.max_hp, "不伤敌"


def _enemy_hits_player(b, p, e):
    """立即结算 (strike 与 anim IMPACT 共用 _roll_damage_one; 无模板的测试敌人 seq 没 end 信号, 不走动画)."""
    from core.battle import combat
    e.facing = (0, 1)
    combat.strike(b, e, p)


def test_douzhuan_zeroes_incoming_damage():
    b, p, e = _battle()
    apply_status(p, ST_DOUZHUAN, 2)
    hp0 = p.hp
    _enemy_hits_player(b, p, e)
    assert p.hp == hp0
    ev = [d for d in b.damage_events if (d.x, d.y) == (p.x, p.y)]
    assert ev and all(d.damage == 0 and not d.miss for d in ev), "算命中, 飘 0"


def test_fanhe_reflects_attacker_attack_stat():
    b, p, e = _battle()
    apply_status(p, ST_FANHE, 2)
    hp0, ehp0 = p.hp, e.hp
    _enemy_hits_player(b, p, e)
    assert p.hp == hp0, "本人不掉血"
    assert e.hp == ehp0 - e.attack, "攻击者扣自己的攻击力 (exe local_250)"
    assert any((d.x, d.y) == (e.x, e.y) and d.damage == e.attack for d in b.damage_events)


def test_fanhe_forces_hit_even_when_would_miss():
    b, p, e = _battle()
    p.agile = 999                      # 正常必闪避
    apply_status(p, ST_FANHE, 2)
    ehp0 = e.hp
    _enemy_hits_player(b, p, e)
    assert e.hp == ehp0 - e.attack
    assert not any(d.miss for d in b.damage_events)
