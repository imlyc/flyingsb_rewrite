"""技能音效接线: 表与 exe 静态绑定 (core.battle.exe_sounds) 一致 + 孙悟空四神兽/超亂舞播放点."""
import pytest

from core.battle.exe_sounds import SKILL_SOUNDS
from core.skill_seq import (SKILL_SIGNAL_SOUNDS, SKILL_SIGNAL_HIT_SOUNDS, SKILL_START_SOUNDS,
                            SKILL_IMPACT2_SOUNDS, skill_signal_sounds)


def _exe_ids(skill_id, kind):
    return {sid for sid, k, _tick, _addr in SKILL_SOUNDS[skill_id] if k == kind}


def test_signal_tables_match_exe_bindings():
    """我们手工按 dispatcher case 列的 (信号→音) 每一项都在 exe 静态解析表里 (同 skill, 同 kind)."""
    for sid, m in SKILL_SIGNAL_SOUNDS.items():
        assert set(m.values()) <= _exe_ids(sid, 'play'), hex(sid)
    for sid, m in SKILL_SIGNAL_HIT_SOUNDS.items():
        assert set(m.values()) <= _exe_ids(sid, 'hit'), hex(sid)
    for sid, snd in SKILL_START_SOUNDS.items():
        assert snd in _exe_ids(sid, 'play'), hex(sid)
    for sid, snd in SKILL_IMPACT2_SOUNDS.items():
        assert snd in _exe_ids(sid, 'play'), hex(sid)


def test_signal_pairs_follow_exe_pattern():
    """-1000/-1002/-1004 登记命中音, -1001/-1003/-1005 播挥击音 (exe 三藏神拳/無限刀/垂直斬)."""
    assert skill_signal_sounds(0x18, -1001) == (185, -1)
    assert skill_signal_sounds(0x18, -1000) == (-1, 189)
    assert skill_signal_sounds(0x24, -1003) == (217, -1)
    assert skill_signal_sounds(0x24, -1004) == (-1, 261)
    assert skill_signal_sounds(0x20, -1001) == (281, -1)
    assert skill_signal_sounds(0x20, -1000) == (-1, 282)
    assert skill_signal_sounds(None, -1001) == (-1, -1)
    assert skill_signal_sounds(0x20, -100) == (-1, -1)


def test_potian_dash_seq_carries_signal_for_sound():
    from core.projectile import CDIT1_G0_TABLE
    for seq in CDIT1_G0_TABLE:
        assert ('jump', -1001) in seq


def test_huolong_effect_seq_sound_ops_match_exe():
    from core.projectile import HUOLONG_EFFECT_SEQ
    snds = [t[1] for t in HUOLONG_EFFECT_SEQ if t[0] == 'sound']
    assert snds == [327, 221]
    assert {327, 221} <= _exe_ids(0x22, 'seq')


# ---- 孙悟空 变身技能 (走 son_transform coordinator, headless 跑完整流程) ----
def _son_battle():
    from tests.core.test_son_transform import _fixture
    b, caster, d1, d2 = _fixture()
    caster.pending_attack_target = d1
    caster.pending_attack_cursor = (7, 5)
    caster.pending_impact_count = 0
    caster.pending_impact_total = 1
    b._pending_damage_range = {(8, 5), (7, 6)}
    return b, caster


def _run_son_skill(skill_id):
    from core.son_transform import start_son_transform
    b, caster = _son_battle()
    caster.pending_skill_id = skill_id
    played, solo, stopped = [], [], []
    b.engine.on('sound_play', lambda ent, sid: played.append(sid))
    b.engine.on('sound_play_solo', lambda ent, sid: solo.append(sid))
    b.engine.on('sound_stop', lambda ent, sid: stopped.append(sid))
    start_son_transform(b, caster, (7, 5), skill_id)
    for _ in range(900):
        b.engine.tick()
        if b._pending_turn_end:
            break
    assert b._pending_turn_end
    return played, solo, stopped


def test_zhuque_sounds():
    from core.son_transform import SFX_ZQ_BEAST, SFX_ZQ_FIRE, SFX_SMOKE
    played, solo, stopped = _run_son_skill(0x05)
    assert played.count(SFX_ZQ_BEAST) == 1
    assert played.index(SFX_ZQ_BEAST) > played.index(SFX_SMOKE)
    assert played.count(SFX_ZQ_FIRE) >= 8, "火雨每颗一次 0xd7"
    assert SFX_ZQ_BEAST not in stopped
    assert {SFX_ZQ_BEAST, SFX_ZQ_FIRE} <= _exe_ids(0x05, 'play')


def test_xuanwu_sounds():
    from core.son_transform import SFX_XW_COIL, SFX_XW_QUAKE, SFX_XW_ROCK
    played, solo, stopped = _run_son_skill(0x06)
    assert played.count(SFX_XW_QUAKE) == 1 and stopped.count(SFX_XW_QUAKE) == 1
    assert played.count(SFX_XW_ROCK) == 2, "2 敌各一块落石落地"
    assert played.count(SFX_XW_COIL) >= 4, "盘踞 128 tick 内 seq 循环 (31 tick) 多次 tick0 音"
    # 时序: 隆隆先于第一个 coil 音/落石, 落石在停震之前
    assert played.index(SFX_XW_QUAKE) <= played.index(SFX_XW_COIL)
    assert SFX_XW_COIL in _exe_ids(0x06, 'seq')
    assert {SFX_XW_QUAKE, SFX_XW_ROCK} <= _exe_ids(0x06, 'play')


def test_yuetu_sounds():
    from core.son_transform import SFX_YT_BEAST, SFX_YT_BARRAGE
    SFX_YT_COIL = ((24, 0x12a), (27, 0xa9))          # 盘踞 seq 0x671c8c 内的 sound op (现由 attach_seq 播)
    played, solo, stopped = _run_son_skill(0x07)
    assert played.count(SFX_YT_BEAST) == 1 and stopped == [SFX_YT_BEAST]
    # 弹幕期 end-0x1e <= t <= end 共 31 tick, 每 tick 一次 (exe 两个 if 同 tick 都跑, 末 tick 也播)
    assert solo.count(SFX_YT_BARRAGE) == 31                   # 实录 tick 183..213 每 tick 一次 (含结束 tick)
    for _t, sid in SFX_YT_COIL:
        assert played.count(sid) >= 2
        assert sid in _exe_ids(0x07, 'seq')
    assert SFX_YT_BEAST in _exe_ids(0x07, 'play')


def test_mfeng_sounds():
    from core.son_transform import SFX_MF_LAND, SFX_MF_FEATHER, SFX_SMOKE
    played, solo, stopped = _run_son_skill(0x09)
    assert played.count(SFX_MF_LAND) == 1
    assert played.index(SFX_MF_LAND) > played.index(SFX_SMOKE)
    assert solo.count(SFX_MF_FEATHER) == 31, "羽毛期 end-0x1e..end 共 31 tick 每 tick 一次"
    assert {SFX_MF_LAND, SFX_MF_FEATHER} == _exe_ids(0x09, 'play')


def test_luanwu_sounds():
    from core.son_transform import SFX_LUANWU_START, SFX_LUANWU_HIT, LUANWU_DURATION, LUANWU_REACT_INTERVAL
    played, solo, stopped = _run_son_skill(0x08)
    assert played.count(SFX_LUANWU_START) == 1
    assert played.count(SFX_LUANWU_HIT) == LUANWU_DURATION // LUANWU_REACT_INTERVAL
    assert played.index(SFX_LUANWU_START) < played.index(SFX_LUANWU_HIT)
    assert {SFX_LUANWU_START, SFX_LUANWU_HIT} == _exe_ids(0x08, 'play')


# ---- 蒙面人技能: 走完整 TacticsBattle 信号路由 (起手音 / seq 信号挥击音 / 登记命中音 / 落地音) ----
def _dit_battle(skill_id, enemy_pos):
    import random
    from core.battle.data import BattleMap, BattleUnit
    from core.battle.tactics import TacticsBattle
    p = BattleUnit(name="蒙面人", level=1, max_hp=30, hp=30, max_mp=999, mp=999, sg=0,
                   attack=20, defence=5, agile=20, move=0, is_player=True)
    p.x, p.y = 10, 10
    e = BattleUnit(name="e", level=1, max_hp=500, hp=500, max_mp=0, mp=0, sg=0,
                   attack=10, defence=0, agile=5, move=0, is_player=False)
    e.x, e.y = enemy_pos
    b = TacticsBattle(players=[p], enemies=[e], battle_map=BattleMap(20, 20), rng=random.Random(0),
                      player_positions=[(p.x, p.y)], enemy_positions=[(e.x, e.y)])
    p.facing = (0, -1)
    played = []
    b.engine.on('sound_play', lambda ent, sid: played.append(sid))
    assert b.enter_attack_aim(skill_id=skill_id)
    assert b.confirm_attack_aim()
    for _ in range(600):
        b.engine.tick()
        if b._pending_turn_end:
            break
    assert b._pending_turn_end
    return played


def _sam_battle(skill_id, enemy_pos):
    import random
    from core.battle.data import BattleMap, BattleUnit
    from core.battle.tactics import TacticsBattle
    p = BattleUnit(name="三藏法师", level=1, max_hp=30, hp=30, max_mp=999, mp=999, sg=0,
                   attack=20, defence=5, agile=20, move=0, is_player=True)
    p.x, p.y = 10, 10
    e = BattleUnit(name="e", level=1, max_hp=500, hp=500, max_mp=0, mp=0, sg=0,
                   attack=10, defence=0, agile=5, move=0, is_player=False)
    e.x, e.y = enemy_pos
    b = TacticsBattle(players=[p], enemies=[e], battle_map=BattleMap(20, 20), rng=random.Random(0),
                      player_positions=[(p.x, p.y)], enemy_positions=[(e.x, e.y)])
    p.facing = (0, -1)
    played = []
    b.engine.on('sound_play', lambda ent, sid: played.append(sid))
    assert b.enter_attack_aim(skill_id=skill_id)
    assert b.confirm_attack_aim()
    for _ in range(600):
        b.engine.tick()
        if b._pending_turn_end:
            break
    assert b._pending_turn_end
    return played


def test_pumpkin_break_sounds():
    """南瓜破 0x14: -1001 播 169, -1000 登记 191 → IMPACT 播."""
    played = _sam_battle(0x14, (10, 9))
    assert played.count(169) == 1 and played.count(191) >= 1
    assert played.index(169) < played.index(191)


def test_three_hit_sounds():
    """不敗三擊 0x16: 三击各 -1001 播 185, 命中各播 189."""
    played = _sam_battle(0x16, (10, 9))
    assert played.count(185) == 3 and played.count(189) == 3
    assert played[0] == 185


def test_vertical_slash_sounds_via_signal_routing():
    """垂直斬 0x20: jump -1001 播 281, jump -1000 登记 282 → IMPACT 播."""
    played = _dit_battle(0x20, (10, 9))
    assert played.count(281) == 1 and played.count(282) == 1
    assert played.index(281) < played.index(282)


def test_huolong_sounds_start_seq_and_impact2():
    """火龍斬 0x22: 起手 261 → effect seq 内 327/221 → 落地结算 189."""
    played = _dit_battle(0x22, (10, 8))
    assert played[:1] == [261]
    assert [s for s in played if s in (327, 221, 189)] == [327, 221, 189]


def test_potian_sounds_start_spawn_dash():
    """破天舞 0x23: 起手 279 → 天字 spawn 280 → 挥刀 -1001 播 261."""
    played = _dit_battle(0x23, (10, 8))
    assert played[:1] == [279]
    assert played.index(279) < played.index(280) < played.index(261)
