"""玩家普攻 (core.normal_attack): 武器 → 普攻表项, 贴身切近战, 紫河变身, 武器附带异常."""
import random

from core.battle.data import BattleMap, BattleUnit
from core.battle.tactics import TacticsBattle, Phase
from core import normal_attack as NA


def _u(name, x, y, *, is_player=True, agile=50, hp=600, weapon=None, acc=()):
    u = BattleUnit(name=name, level=10, max_hp=600, hp=hp, max_mp=300, mp=300, sg=0,
                   attack=100, defence=10, agile=agile, move=3, is_player=is_player)
    u.x, u.y = x, y
    if is_player:
        u.attack_normal, u.attack_melee = NA.attack_ids(name, weapon, acc)
        NA.zihe_setup(u, acc)
    return u


def _battle(players, enemies, seed=1):
    return TacticsBattle(players=players, enemies=enemies, battle_map=BattleMap(32, 64), rng=random.Random(seed),
                         player_positions=[(u.x, u.y) for u in players],
                         enemy_positions=[(u.x, u.y) for u in enemies])


def test_weapon_to_attack():
    assert NA.attack_ids('孙悟空', None) == (0, 0)
    assert NA.attack_ids('孙悟空', 128) == (7, 7)                 # 如意雙截棍
    assert NA.attack_ids('猪八戒', 145) == (24, 91)               # 火箭砲: 远程, 贴身用 91
    assert NA.attack_ids('破无', 176) == (64, 92)
    assert NA.attack_ids('捕山', 184) == (72, 93)
    assert NA.attack_ids('美娜', 200) == (94, 94)                 # 光劍特例
    assert NA.attack_ids('蒙面人', 162, (0xd5,)) == (0x36, 0x36)  # 莫亞刀 + 饰品 0xd5
    assert NA.attack_ids('蒙面人', 162) == (49, 49)


def test_nunchaku_uses_its_own_seq_table():
    assert NA.entry(0).seq_table == 0x670cf0 and NA.entry(7).seq_table == 0x67122c
    seq = NA.seq_for(7, (0, -1))
    assert any(t[0] == 'fm' and t[1] == 1 for t in seq)          # cson1_g1 (全局槽 1)
    assert NA.entry(7).template == 66


def test_melee_switch_when_adjacent():
    p = _u('破无', 15, 53, agile=99, weapon=176)
    p.facing = (0, 1)
    near = _u('e1', 15, 54, is_player=False, agile=1)
    far = _u('e2', 15, 56, is_player=False, agile=1)
    b = _battle([p], [near, far])
    assert b.enter_attack_aim()
    assert p.attack_cur == 92
    assert b.aim_attack_range == {(15, 54)}                      # 只有面前 1 格, 远处选不到
    b.cancel_attack_aim()
    near.x, near.y = 20, 60                                       # 挪走贴身的
    assert b.enter_attack_aim()
    assert p.attack_cur == 64 and (15, 56) in b.aim_attack_range


def test_preview_uses_ranged_entry():
    p = _u('破无', 15, 53, agile=99, weapon=176)
    p.facing = (0, 1)
    b = _battle([p], [_u('e1', 15, 54, is_player=False, agile=1)])
    assert b.phase == Phase.PLAYER_MOVE
    assert (15, 56) in b.attack_range(p)                          # 移动阶段预览仍是远程范围


def test_zihe_thermos_transforms_at_start():
    z = _u('紫河', 15, 53, agile=99, acc=(0x12a, 0x144))
    z.sprite_key = 'ps_CJAH000'
    b = _battle([z], [_u('e', 18, 53, is_player=False, agile=1)])
    assert z.zihe['transformed'] and z.zihe['form'] == 2
    assert z.mp == 0 and z.max_mp == 0 and z.attack_normal == 90
    assert z.max_hp == 600 * 5 // 2 and z.sprite_key == 'ps_CJAH300'
    assert z.flicker is not None


def test_zihe_hit_trigger_and_revert():
    z = _u('紫河', 15, 53, agile=99, acc=(0x129,))
    z.sprite_key = 'ps_CJAH000'
    e = _u('e', 15, 54, is_player=False, agile=1)
    e.type_flags = 0x2000000
    b = _battle([z], [e])
    from core.battle import combat
    combat.apply_damage(b, e, z, 10, "")
    assert z.zihe['pending']
    b.end_unit_turn()                                              # 当前单位行动完 → 处理点变身
    assert z.zihe['transformed'] and z.attack_normal == 89 and z.mp == 0
    beast_hp = z.hp
    b.end_unit_turn()                                              # 敌人行动完: 不是紫河 → 保持兽形
    assert z.zihe['transformed']
    assert b._turn_order[b._turn_idx] is z                         # 新回合轮到紫河, 以兽形行动
    assert z.zihe['transformed'] and z.attack_normal == 89
    b.end_unit_turn()                                              # 紫河兽形行动完 → 变回人形
    assert not z.zihe['transformed'] and z.hp == 590 and z.mp == 300
    assert beast_hp == 600 * 4 // 2


def test_weapon_status_roll():
    hits = 0
    for seed in range(200):
        p = _u('三藏法师', 15, 53, agile=99, weapon=142)            # 紫青手: 普攻 21, 毒
        e = _u('e', 15, 54, is_player=False, agile=1)
        b = _battle([p], [e], seed)
        p.attack_cur = p.attack_normal
        if NA.roll_status(b, p, e) == 0x100:
            hits += 1
    assert 25 < hits < 70                                          # 23%


def test_status_immunity():
    p = _u('三藏法师', 15, 53, agile=99, weapon=142)
    e = _u('e', 15, 54, is_player=False, agile=1)
    e.type_flags = 0x100
    b = _battle([p], [e])
    p.attack_cur = p.attack_normal
    assert all(NA.roll_status(b, p, e) is None for _ in range(100))


# ---------------- 远程普攻 (core.ranged_attack) ----------------
import pytest
from types import SimpleNamespace


def _run_attack(b, n=3000):
    from scenes.battle.update import _tick_reactions
    from core.attack_seq import ATTACK_TICK_MS
    stub = SimpleNamespace(battle=b)
    for _ in range(n):
        b.engine.tick()
        _tick_reactions(stub, ATTACK_TICK_MS)
        if b._pending_turn_end:
            return True
    return False


@pytest.mark.parametrize('name,weapon,idx,dist', [
    ('猪八戒', 145, 24, 3), ('猪八戒', 146, 25, 3), ('猪八戒', 148, 27, 3), ('猪八戒', 149, 28, 3), ('猪八戒', 150, 29, 3),
    ('猪八戒', 151, 30, 3), ('猪八戒', 152, 31, 3),
    ('破无', 176, 64, 3), ('破无', 179, 67, 3), ('破无', 183, 70, 3),
    ('捕山', 184, 72, 3), ('捕山', 186, 74, 2), ('捕山', 187, 75, 3), ('捕山', 189, 77, 2), ('捕山', 190, 78, 3),
])
def test_ranged_attack_finishes_and_damages(name, weapon, idx, dist):
    p = _u(name, 15, 53, agile=99, weapon=weapon)
    p.facing = (0, 1)
    e = _u('e', 15, 53 + dist, is_player=False, agile=1)
    b = _battle([p], [e])
    assert b.enter_attack_aim()
    assert p.attack_cur == idx
    b.aim_cursor = (15, 53 + dist)
    if not b.confirm_attack_aim():
        b.aim_cursor = next(c for c in b.aim_attack_range if e.x == c[0])
        assert b.confirm_attack_aim()
    assert _run_attack(b), f'{idx} 没收尾'
    assert e.hp < 600 or e.hp == 600 and any(ev.miss for ev in b.damage_events)


def test_ranged_char_melee_when_adjacent():
    p = _u('猪八戒', 15, 53, agile=99, weapon=145)
    p.facing = (0, 1)
    e = _u('e', 15, 54, is_player=False, agile=1)
    b = _battle([p], [e])
    assert b.enter_attack_aim() and p.attack_cur == 91
    b.aim_cursor = (15, 54)
    assert b.confirm_attack_aim()
    assert _run_attack(b)


def test_zihe_form3_leap():
    z = _u('紫河', 15, 53, agile=99, acc=(0x12a, 0x144))
    z.sprite_key = 'ps_CJAH000'
    z.facing = (0, 1)
    e = _u('e', 15, 54, is_player=False, agile=1)
    b = _battle([z], [e])
    assert z.attack_normal == 90
    assert b.enter_attack_aim()
    b.aim_cursor = (15, 54)
    assert b.confirm_attack_aim()
    assert _run_attack(b)


def test_zihe_flicker_blocks_next_unit():
    """exe FUN_004a4f94 0xd/0xe: 闪烁 31t 内状态机不前进 → 下一个单位 (玩家输入 / 敌人 AI) 等闪完."""
    import os
    os.environ.setdefault("SDL_VIDEODRIVER", "dummy")
    from types import SimpleNamespace
    from scenes.battle import update as U
    z = _u('紫河', 15, 53, agile=99, acc=(0x129,))
    z.sprite_key = 'ps_CJAH000'
    e = _u('e', 15, 54, is_player=False, agile=1)
    e.type_flags = 0x2000000
    b = _battle([z], [e])
    from core.battle import combat
    combat.apply_damage(b, e, z, 10, "")
    b.end_unit_turn()                                              # 处理点变身 → 闪烁开始, 轮到敌人
    for u in b.all_units:
        u.reaction_seq = None
        u.settle_pending = False
        u.render_x, u.render_y = u.x, u.y
    b.float_events = []
    sc = SimpleNamespace(battle=b, ANIM_EPSILON=0.01, ENEMY_DEATH_TOTAL_MS=0, DEATH_FALL_TOTAL_MS=0,
                         _enemy_pre_move_started_at=None, _enemy_turn_started_at=None, ENEMY_PRE_MOVE_PAUSE_MS=0,
                         ENEMY_TURN_DELAY_MS=0, _battle_over_signaled=False)
    assert b.phase == Phase.ENEMY_TURN and b._enemy_ai_pending and z.flicker
    assert U.units_animating(sc)
    U._tick_phase_transitions(sc, 10**6)
    assert b._enemy_ai_pending                                     # 闪烁中: 敌人不开始
    for _ in range(NA.FLICKER_TICKS):
        U._tick_flicker(b)
    assert z.flicker is None
    U._tick_phase_transitions(sc, 10**6)
    U._tick_phase_transitions(sc, 10**6)
    assert not b._enemy_ai_pending                                 # 闪完 → 敌人开始行动
