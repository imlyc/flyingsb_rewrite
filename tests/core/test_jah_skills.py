"""紫河 9 技能 (0x39..0x41): 施法 seq + coordinator 演出跑完 → 结算 (HP / MP / 状态) + 音效 (exe 逆向, core.jah_skills)."""
import random

import pytest

from core.battle.data import BattleMap, BattleUnit
from core.fm_frames import FM_FRAMES
import core.jah_skills as J


def _unit(name, x, y, *, is_player, attack=30, defence=5, agile=10, hp=400, mp=100):
    u = BattleUnit(name=name, level=1, max_hp=hp, hp=hp, max_mp=mp, mp=mp, sg=0,
                   attack=attack, defence=defence, agile=agile, move=0, is_player=is_player)
    u.x, u.y = x, y
    return u


def _cursor_for(sid):
    """用假单位算 AIM 初始 cursor (facing 上), 把敌人放在那."""
    from core.skill_patterns import compute_skill_pattern
    u = _unit("紫河", 10, 10, is_player=True)
    u.facing = (0, -1)
    rng = compute_skill_pattern(u, BattleMap(20, 20), sid)
    if (10, 10) in rng:
        return (10, 10)
    for d in range(1, 12):
        if (10, 10 - d) in rng:
            return (10, 10 - d)
    return sorted(rng)[0]


def _battle(sid):
    from core.battle.tactics import TacticsBattle
    p = _unit("紫河", 10, 10, is_player=True, mp=50)
    p.mp = 10
    cur = _cursor_for(sid)
    enemies = []
    if cur != (10, 10):
        enemies.append(_unit("e1", *cur, is_player=False, agile=1))
    b = TacticsBattle(players=[p], enemies=enemies or [_unit("far", 0, 0, is_player=False, agile=1)],
                      battle_map=BattleMap(20, 20), rng=random.Random(1),
                      player_positions=[(p.x, p.y)], enemy_positions=[(e.x, e.y) for e in (enemies or [_unit("far", 0, 0, is_player=False)])])
    p.facing = (0, -1)
    played = []
    b.engine.on('sound_play', lambda ent, s: played.append(s))
    b.engine.on('sound_play_solo', lambda ent, s: played.append(s))
    assert b.enter_attack_aim(skill_id=sid), hex(sid)
    assert b.aim_cursor == cur
    assert b.confirm_attack_aim(), hex(sid)
    return b, p, (enemies[0] if enemies else None), played


def _run(b, n=900):
    for i in range(n):
        b.engine.tick()
        if b._pending_turn_end:
            return i
    return -1


def test_cast_seq_matches_exe():
    assert J.SKILL_JAH_CAST[0] == [('fm_mode1', 106, 2, 5), ('fm_mode1', 106, 3, 12), ('impact',), ('exit',)]
    from core.grid_atlas_table import grid_atlas_key, GRID_ATLAS
    assert grid_atlas_key(106) == "ps_CJAH002" and GRID_ATLAS[106][1:3] == (4, 4)
    from core.anim_engine.bytecode import tuple_to_bytecode
    bc = tuple_to_bytecode(J.SKILL_JAH_CAST[0])
    assert bc[0] == 0x05 and bc[10] == 0x05
    assert [s[0][2] for s in J.SKILL_JAH_CAST] == [2, 6, 10, 14]
    from core.skill_seq import SKILL_SEQS, SKILL_IMPACT_SPAWN
    for sid in range(0x39, 0x42):
        assert SKILL_SEQS[sid] is J.SKILL_JAH_CAST and sid in SKILL_IMPACT_SPAWN


def test_effect_frames_within_atlases():
    for seq in (J.DRILL_SEQ_UD, J.DRILL_SEQ_LR, J.PILLAR_UP_SEQ, J.PILLAR_TRAP_SEQ, J.HUAQI_SEQ,
                J.XIULUO_LAND_SEQ, J.DRAGON_SEQ, J.SKILL_JAH_CAST[3]):
        for t in seq:
            if t[0] == 'fm':
                name = {232: 'ds_ice', 284: 'ejaha01', 285: 'ejaha02', 286: 'ejaha05',
                        287: 'ejaha07', 288: 'ejaha08', 247: 'e00'}[t[1]]
                assert t[2] < len(FM_FRAMES[name]), (name, t)


@pytest.mark.parametrize("sid,cast_snd", [
    (0x39, J.SFX_ICE_DRILL), (0x3a, J.SFX_PILLAR_CAST), (0x3c, 173), (0x3f, J.SFX_PILLAR_CAST),
    (0x40, J.SFX_XIULUO_SPAWN), (0x41, 257),
])
def test_attack_skills_damage_enemy_and_play_cast_sound(sid, cast_snd):
    b, p, e, played = _battle(sid)
    assert e is not None
    hp0 = e.hp
    end = _run(b)
    assert end >= 0, f"{hex(sid)} 回合没结束"
    assert e.hp < hp0, hex(sid)
    assert cast_snd in played, (hex(sid), played[:10])
    assert J.SFX_HIT in played or sid in (0x3c, 0x3f, 0x40, 0x41)   # 冰河/冰身/修羅/冰龍 的受击 exe 无音


def test_ice_drill_schedule_and_hits():
    b, p, e, played = _battle(0x39)
    _run(b)
    assert played.count(J.SFX_ICE_DRILL) == J.DRILL_COUNT
    assert played.count(J.SFX_HIT) == J.DRILL_COUNT


def test_pillar_up_timeline():
    b, p, e, played = _battle(0x3a)
    end = _run(b)
    assert played.count(J.SFX_HIT) == 5           # t=0,20,40,60,80 (exe tick%20==0 与 t=80 结算同 tick)
    assert J.SFX_ICE_BIG in played
    assert end >= 17 + J.PILLAR_UP_END


def test_huajing_zeroes_enemy_mp():
    b, p, e, played = _battle(0x3b)
    e.mp = e.max_mp = 100
    hp0 = e.hp
    assert _run(b) >= 0
    assert e.mp < 100 and e.hp == hp0, "化精大法只动 MP"
    assert J.SFX_HUAJING_CAST in played and J.SFX_HUAJING_HIT in played
    assert any(d.mp and (d.x, d.y) == (e.x, e.y) for d in b.damage_events)


def test_xijing_absorbs_mp():
    b, p, e, played = _battle(0x3d)
    e.mp = e.max_mp = 100
    p.mp = 10
    hp0 = e.hp
    assert _run(b) >= 0
    assert e.mp < 100 and e.hp == hp0
    assert p.mp > 10 and p.mp <= p.max_mp
    assert J.SFX_XIJING_CAST in played and J.SFX_XIJING_DEPART in played and J.SFX_XIJING_HIT in played


def test_huaqi_sets_absorb_status_then_next_hit_becomes_mp():
    from core.battle.status import has_status, ST_HUAJING
    from core.battle import combat
    b, p, e, played = _battle(0x3e)
    assert _run(b) >= 0
    assert has_status(p, ST_HUAJING)
    assert J.SFX_HUAQI in played
    atk = _unit("atk", 10, 9, is_player=False, attack=50)
    b.enemies.append(atk); b.all_units.append(atk)
    hp0, mp0 = p.hp, p.mp
    combat.strike(b, atk, p)
    assert p.hp == hp0 and p.mp > mp0
    assert not has_status(p, ST_HUAJING), "一次性"


def test_xiuluo_land_sound_and_dragon_cones():
    b, p, e, played = _battle(0x40)
    _run(b)
    assert played.index(J.SFX_XIULUO_SPAWN) < played.index(J.SFX_XIULUO_LAND)
    b, p, e, played = _battle(0x41)
    _run(b)
    assert played.index(257) < played.index(J.SFX_ICE_BIG)


def test_drill_axis_follows_caster_facing():
    """exe FUN_004d788d: 施法者朝上/下 → vy=∓24 定速; 朝左/右 → vx=∓32 定速 (与目标相对位置无关)."""
    b, p, e, played = _battle(0x39)
    drills = []
    for _ in range(40):
        b.engine.tick()
        drills += [x for x in b.engine.entities if x.user_data.get('drill') and x not in drills]
        if drills:
            break
    assert drills
    d = drills[0]
    assert abs(d.vy) == J.DRILL_SPEED_V * J.FP, "朝上: 竖向 24px/tick 定速"


def test_xijing_particles_rise_then_fly_with_exe_frames():
    b, p, e, played = _battle(0x3d)
    seen = set(); rose = False
    for _ in range(120):
        b.engine.tick()
        for x in b.engine.entities:
            if x.user_data.get('particle') and (x.flags & 0x800):
                seen.add(x.user_data['frames'])
                if x.user_data['rise'] and x.state_code == 0 and x.z < 0:
                    rose = True
    assert seen and seen <= set(J.PARTICLE_FRAME_SETS)
    assert rose


def test_xijing_particles_oscillate_around_orb_before_diving():
    """exe FUN_004c3211 弹簧: 漂浮期光粒 x 会多次越过光球 x (来回摆), 之后才直线飞入."""
    b, p, e, played = _battle(0x3d)
    crossings = {}
    last_side = {}
    for _ in range(80):
        b.engine.tick()
        for x in b.engine.entities:
            if x.user_data.get('particle') and (x.flags & 0x800) and x.state_code == 0:
                tx = x.user_data['target'][0]
                side = x.x >= tx
                if x.id in last_side and side != last_side[x.id]:
                    crossings[x.id] = crossings.get(x.id, 0) + 1
                last_side[x.id] = side
    assert crossings and max(crossings.values()) >= 2, crossings
