"""孙悟空变身演出 coordinator: 翻跟头隐现 + AOE 伤害 + 收尾."""

import random

from core.anim_engine.engine import Engine
from core.battle.data import BattleMap, BattleUnit
from core.battle.queries import BattleQueries


class _B:
    def __init__(self):
        self.rng = random.Random(0)
        self.damage_events: list = []
        self.messages: list = []
        self.players: list = []
        self.enemies: list = []
        self.map = BattleMap(15, 10)
        self.q = BattleQueries(self.map, self.players, self.enemies)
        self.engine = Engine()
        self._pending_damage_range = None
        self._pending_turn_end = False
        self.all_units: list = []

    def _log(self, m): self.messages.append(m)

    def post_attack_anim(self, caster):
        from core.battle import combat
        combat.clear_pending_attack(caster)
        self._pending_damage_range = None
        self._pending_turn_end = True


def _fixture():
    b = _B()
    caster = BattleUnit(name="孙悟空", level=1, max_hp=30, hp=30, max_mp=99, mp=99, sg=0,
                        attack=20, defence=5, agile=100, move=3, is_player=True)
    caster.x, caster.y = 7, 5
    # 菱r2 范围内放 2 个敌人
    d1 = BattleUnit(name="d1", level=1, max_hp=50, hp=50, max_mp=0, mp=0, sg=0,
                    attack=10, defence=0, agile=0, move=3, is_player=False)
    d1.x, d1.y = 8, 5      # forward 1
    d2 = BattleUnit(name="d2", level=1, max_hp=50, hp=50, max_mp=0, mp=0, sg=0,
                    attack=10, defence=0, agile=0, move=3, is_player=False)
    d2.x, d2.y = 7, 6      # 下 1
    b.players.append(caster); b.enemies.extend([d1, d2])
    b.all_units = [caster, d1, d2]
    return b, caster, d1, d2


def test_dajingang_transform_choreography():
    """大金刚 0x00: 翻跟头消失(cast_flip 0→7) → 隐身+AOE伤害 → 翻跟头出现 → 收尾."""
    from core.son_transform import start_son_transform, _FLIP_OUT

    b, caster, d1, d2 = _fixture()
    caster.pending_attack_target = d1
    caster.pending_attack_cursor = (7, 5)
    caster.pending_skill_id = 0x00
    caster.pending_impact_count = 0
    caster.pending_impact_total = 1
    b._pending_damage_range = {(8, 5), (7, 6)}   # 菱r2 内 2 敌人

    coord = start_son_transform(b, caster, (7, 5), 0x00)
    assert caster.cast_flip_frame == 0           # 起手翻跟头第 0 帧
    assert coord.state_code == _FLIP_OUT
    assert caster.pending_caster_coord is coord
    # 起手只有翻跟头, 烟雾在翻跟头落地后才撒 (exe state 0x14)
    assert not [e for e in b.engine.entities if e.user_data.get('kind') == 'hit_effect']

    hp1_0, hp2_0 = d1.hp, d2.hp
    smoke_seen = False
    hidden_seen = False
    for _ in range(300):
        b.engine.tick()
        if caster.cast_hidden:
            hidden_seen = True
            if [e for e in b.engine.entities if e.user_data.get('kind') == 'hit_effect']:
                smoke_seen = True
        if b._pending_turn_end:
            break

    assert hidden_seen, "神兽阶段 caster 应隐身过"
    assert smoke_seen, "翻跟头落地隐身后应撒烟雾"
    assert d1.hp < hp1_0 and d2.hp < hp2_0, "AOE 应伤到菱r2 内两个敌人"
    # 收尾: caster 状态复位
    assert caster.cast_flip_frame is None
    assert caster.cast_hidden is False
    assert b._pending_turn_end is True


def test_dajingang_aoe_deferred_simultaneous_settle():
    """两阶段: 造成伤害依次 (逐个扣血+settle_pending 抑制), 伤害结算同时 (统一释放).
    敌人被砸致死后, 在 eson 还在砸其他敌人期间应保持 settle_pending (不进死亡动画);
    全部砸完后两者同时释放, death_anim 在同一 tick 启动."""
    from core.son_transform import start_son_transform

    b, caster, d1, d2 = _fixture()
    d1.max_hp = d1.hp = 10        # 一砸即死
    d2.max_hp = d2.hp = 10
    caster.pending_attack_target = d1
    caster.pending_attack_cursor = (7, 5)
    caster.pending_skill_id = 0x00
    caster.pending_impact_total = 1
    b._pending_damage_range = {(8, 5), (7, 6)}

    start_son_transform(b, caster, (7, 5), 0x00)

    saw_suppressed = False        # 有一刻: 某敌已死但被抑制 (settle_pending, death 未启动)
    for _ in range(400):
        b.engine.tick()
        for d in (d1, d2):
            if d.hp == 0 and d.settle_pending and d.death_anim_time_ms < 0:
                saw_suppressed = True
        # 抑制期: 不允许 hp=0 的敌人启动死亡动画; 显示 hp 仍是旧值 (HUD 滞后)
        for d in (d1, d2):
            if d.settle_pending:
                assert d.death_anim_time_ms < 0
                assert d.display_hp == 10      # 逻辑 hp 已 0, 但显示滞后到结算
        if b._pending_turn_end:
            break

    assert saw_suppressed, "致死敌人应在 eson 砸完前被抑制 (依次造成伤害)"
    # 结算后: 两者同时释放, 同步开始死亡动画
    assert d1.hp == 0 and d2.hp == 0
    # 致死敌人保持受击前 HP 显示 (原版死亡闪烁不显 0)
    assert d1.display_hp == 10 and d2.display_hp == 10
    assert not d1.settle_pending and not d2.settle_pending
    assert not d1.settle_batch and not d2.settle_batch
    assert d1.death_anim_time_ms >= 0 and d2.death_anim_time_ms >= 0


def test_all_10_son_skills_are_transform_skills():
    from core.son_transform import is_son_transform_skill, SON_BEAST_CONFIG
    for sid in range(0x00, 0x0a):
        assert is_son_transform_skill(sid) is True
    assert is_son_transform_skill(0x14) is False   # 三藏南瓜破
    assert is_son_transform_skill(None) is False
    assert set(SON_BEAST_CONFIG) == set(range(0x00, 0x0a))


def _run_son_skill(sid):
    """跑一个孙悟空技能到回合结束, 返回 (b, caster, d1, d2, beast_atlas_seen)."""
    from core.son_transform import start_son_transform
    b, caster, d1, d2 = _fixture()
    caster.attack = 30
    caster.pending_attack_cursor = (7, 5)
    caster.pending_skill_id = sid
    caster.pending_impact_total = 1
    b._pending_damage_range = {(8, 5), (7, 6)}
    start_son_transform(b, caster, (7, 5), sid)
    seen = set()
    for _ in range(400):
        b.engine.tick()
        for e in b.engine.entities:
            if e.atlas_slot in (255, 256, 262, 263, 264, 267):
                seen.add(e.atlas_slot)
        if b._pending_turn_end:
            break
    return b, caster, d1, d2, seen


def test_son_sweep_beasts_spawn_and_damage():
    """青龙/白虎/朱雀/玄武/月兔/凤凰: 召唤对应神兽 atlas, 范围伤害, 收尾."""
    for sid, atlas in [(0x01, 255), (0x02, 256), (0x05, 262),
                       (0x06, 263), (0x07, 264), (0x09, 267)]:
        b, caster, d1, d2, seen = _run_son_skill(sid)
        assert atlas in seen, f"skill 0x{sid:02x} 应召唤 atlas {atlas}, 实际 {seen}"
        assert d1.hp < 50 and d2.hp < 50, f"skill 0x{sid:02x} 应伤到两敌"
        assert caster.cast_flip_frame is None and not caster.cast_hidden
        assert b._pending_turn_end is True


def test_qinglong_ice_cone_shatter_sequence():
    """青龙冰锥序列 (用户确认): 小冰锥(0-3)/大冰锥(28/31/34) 下落 → 落地碎裂为小冰块(12-23)."""
    from core.son_transform import EICE_CONE_SMALL, EICE_CONE_BIG, EICE_SHATTER
    b, caster, d1, d2 = _fixture()
    caster.attack = 30
    caster.pending_attack_cursor = (7, 5)
    caster.pending_skill_id = 0x01
    caster.pending_impact_total = 1
    b._pending_damage_range = {(8, 5), (7, 6)}
    from core.son_transform import start_son_transform
    from core.fm_frames import FM_FRAMES
    from core.raw_attack_seqs import atlas_resource
    start_son_transform(b, caster, (7, 5), 0x01)

    def render_frame(e):
        # 复刻 hit_effect.draw 的渲染条件 (回归 "spawned 但 projectile 没设导致不渲染" bug)
        if e.user_data.get('kind') != 'hit_effect' or not (e.flags & 0x40):
            return None
        if not e.is_playing() and not e.user_data.get('projectile'):
            return None
        fr = FM_FRAMES.get(atlas_resource(e.atlas_slot & 0xffff))
        if e.atlas_slot != 300 or fr is None or not (0 <= e.frame_idx < len(fr)):
            return None
        return e.frame_idx

    saw_cone = saw_big = saw_shatter = 0
    d1_react_ticks = 0
    for _ in range(600):
        b.engine.tick()
        if d1.reaction_seq is not None:      # 雨期受击反应 (用户问题1)
            d1_react_ticks += 1
        for e in b.engine.entities:
            f = render_frame(e)
            if f in EICE_CONE_SMALL:
                saw_cone += 1
            elif f in EICE_CONE_BIG:
                saw_big += 1
            elif f in EICE_SHATTER:
                saw_shatter += 1
        if b._pending_turn_end:
            break
    assert saw_cone > 0, "应有小冰锥下落 (frames 0-3)"
    assert saw_big > 0, "应有大冰锥收尾 (frames 28/31/34)"
    assert saw_shatter > 0, "冰锥落地应碎裂为小冰块 (frames 12-23)"
    assert d1_react_ticks > 30, f"冰锥雨期敌人应持续受击动画, 实际 {d1_react_ticks} tick"


def test_son_aoe_placeholder_skills_damage():
    """酷酷猫/分身术/超亂舞 (占位 AOE): 范围伤害 + 收尾 (暂无神兽视觉)."""
    for sid in (0x03, 0x04, 0x08):
        b, caster, d1, d2, seen = _run_son_skill(sid)
        assert d1.hp < 50 and d2.hp < 50
        assert b._pending_turn_end is True
