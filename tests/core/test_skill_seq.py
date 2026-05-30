"""技能 seq 数据 + 接通 attack_seq_for / begin_attack 验证."""

from core.attack_seq import attack_seq_for
from core.skill_seq import (
    SKILL_SEQS,
    SKILL_VERTICAL_SLASH,
    has_skill_seq,
    skill_cost,
    skill_seq_for,
)


def test_vertical_slash_4_dirs_each_uses_atlas_19():
    """exe dump: 垂直斬 4 方向都用 atlas 19 (= cdit1_g0); UP 用 frames 0-11 等."""
    assert len(SKILL_VERTICAL_SLASH) == 4
    for dir_idx, seq in enumerate(SKILL_VERTICAL_SLASH):
        fm_ops = [t for t in seq if t[0] == 'fm']
        for op in fm_ops:
            assert op[1] == 19, f"dir {dir_idx} expected atlas 19, got {op[1]}"


def test_vertical_slash_has_init_impact_end_signals():
    """每方向都有 -1000 init + -100 IMPACT + -110 END 信号."""
    for seq in SKILL_VERTICAL_SLASH:
        kinds = [t[0] for t in seq]
        assert 'jump' in kinds        # -1000 init
        assert 'impact' in kinds      # -100
        assert 'end' in kinds         # -110


def test_skill_seqs_lookup():
    """蒙面人 5 技能 (0x20..0x24) 全部已实现."""
    for sid in (0x20, 0x21, 0x22, 0x23, 0x24):
        assert has_skill_seq(sid) is True
    # 未注册的 skill 仍回落
    assert has_skill_seq(0x05) is False


def test_sam_all_5_skills_implemented():
    """三藏 5 技能 (0x14..0x18) 全部已实现."""
    for sid in (0x14, 0x15, 0x16, 0x17, 0x18):
        assert has_skill_seq(sid) is True


def test_life_fire_is_heal_skill():
    from core.skill_seq import is_heal_skill
    assert is_heal_skill(0x15) is True
    assert is_heal_skill(0x14) is False     # 南瓜破 = 攻击
    assert is_heal_skill(0x17) is False     # 凤凰掌 = 攻击
    assert is_heal_skill(None) is False


def test_life_fire_heals_ally():
    """生命之火 IMPACT → 给友军回 HP, 不扣血, 发 heal=True 飘字事件 + esum1 effect."""
    from core.battle.combat import apply_pending_attack
    from core.battle.data import BattleUnit
    b, caster, _enemy = _b_class_battle_fixture((2, 5), (9, 9))
    ally = BattleUnit(name="孙悟空", level=1, max_hp=80, hp=20, max_mp=0, mp=0, sg=0,
                      attack=10, defence=0, agile=0, move=3, is_player=True)
    ally.x, ally.y = 2, 3
    b.players.append(ally); b.all_units.append(ally)

    caster.pending_attack_target = ally
    caster.pending_attack_cursor = (2, 3)
    caster.pending_skill_id = 0x15
    caster.pending_impact_count = 0
    caster.pending_impact_total = 1
    apply_pending_attack(b, caster)

    assert ally.hp == 80, "友军应被回满 (20 + caster.attack*3=60 → clamp 80)"
    assert len(b.damage_events) == 1
    assert b.damage_events[0].heal is True
    assert b.damage_events[0].damage == 60   # 实际回复量
    # esum1 (atlas 299) effect spawn
    fx = [e for e in b.engine.entities if e.user_data.get('kind') == 'hit_effect'
          and e.atlas_slot == 299]
    assert len(fx) == 1


def test_skill_seq_for_facing():
    """facing → seq 列表的方向索引."""
    seq_up = skill_seq_for(0x20, (0, -1))
    seq_rt = skill_seq_for(0x20, (1, 0))
    assert seq_up == SKILL_VERTICAL_SLASH[0]
    assert seq_rt == SKILL_VERTICAL_SLASH[3]


def test_attack_seq_for_routes_to_skill_when_skill_id_given():
    """带 skill_id → 走 skill_seq, 不带 → 走普攻."""
    seq_skill = attack_seq_for("蒙面人", (0, -1), skill_id=0x20)
    seq_atk = attack_seq_for("蒙面人", (0, -1), skill_id=None)
    assert seq_skill == SKILL_VERTICAL_SLASH[0]
    assert seq_skill != seq_atk


def test_unimplemented_skill_falls_back_to_normal_attack():
    """未 dump 的 skill_id 回落到角色普攻 seq (= 不崩, 视觉先 work).
    用 0x0a (美娜小回复, 尚未实现) 验证 fallback."""
    seq_skill = attack_seq_for("蒙面人", (0, -1), skill_id=0x0a)
    seq_atk = attack_seq_for("蒙面人", (0, -1), skill_id=None)
    assert seq_skill == seq_atk


def test_skill_bytecode_compiles():
    """skill seq 能编进 bytecode (= anim_engine 能跑)."""
    from core.anim_engine.bytecode import tuple_to_bytecode
    bc = tuple_to_bytecode(skill_seq_for(0x20, (1, 0)))
    assert len(bc) > 100   # 30+ ops × ≥4B
    # bytecode 末尾应是 SIGNAL -110 (end) = `0e 04 92 ff` (signed -110 = 0xff92)
    assert bc[-4] == 0x0e


def test_skill_cost():
    assert skill_cost(0x20) == 175
    assert skill_cost(0xFF) == 0


def test_infinite_blade_5_impacts_mid_atlas_switch():
    """無限刀 0x24: 4 方向各 5 段 IMPACT, atlas 20 (cdit1_g1) 主体 + 终结切 atlas 19 (cdit1_g0)."""
    from core.skill_seq import SKILL_INFINITE_BLADE
    assert len(SKILL_INFINITE_BLADE) == 4
    for dir_idx, seq in enumerate(SKILL_INFINITE_BLADE):
        impacts = [t for t in seq if t[0] == 'impact']
        assert len(impacts) == 5, f"dir {dir_idx} expected 5 IMPACTs, got {len(impacts)}"
        atlases = {t[1] for t in seq if t[0] == 'fm'}
        assert atlases == {19, 20}, f"dir {dir_idx} expected atlas 19+20, got {atlases}"


def test_cloudwave_projectile_physics_lands_and_damages():
    """赤雲波 (B 类): IMPACT 时 spawn 投射物, 投射物按重力下落, 落地 → SIG_IMPACT_2 → 结算伤害."""
    import random
    from core.anim_engine.engine import Engine
    from core.battle.combat import begin_attack, apply_pending_attack
    from core.battle.data import BattleUnit, DamageEvent
    from core.battle.queries import BattleQueries
    from core.battle.data import BattleMap
    from core.anim_engine.entity import SIG_IMPACT_2

    class _B:
        def __init__(self):
            self.rng = random.Random(0)
            self.damage_events: list = []
            self.messages: list = []
            self.players: list = []
            self.enemies: list = []
            self.map = BattleMap(10, 10)
            self.q = BattleQueries(self.map, self.players, self.enemies)
            self.engine = Engine()
            self._pending_damage_range = None
            self._SIG_IMPACT_2 = SIG_IMPACT_2
            self.all_units = []
        def _log(self, m): self.messages.append(m)

    b = _B()
    caster = BattleUnit(name="蒙面人", level=1, max_hp=30, hp=30,
                        max_mp=15, mp=15, sg=0, attack=20, defence=5, agile=100, move=3, is_player=True)
    caster.x, caster.y = 2, 2
    defender = BattleUnit(name="d", level=1, max_hp=50, hp=50,
                          max_mp=0, mp=0, sg=0, attack=10, defence=0, agile=0, move=3, is_player=False)
    defender.x, defender.y = 5, 2
    b.players.append(caster); b.enemies.append(defender)
    b.all_units = [caster, defender]

    # 模拟"赤雲波 cast seq 跑到 IMPACT": 设 pending, 直接调 apply_pending_attack
    caster.pending_attack_target = defender
    caster.pending_skill_id = 0x21
    caster.pending_impact_count = 0
    caster.pending_impact_total = 1
    # 接 IMPACT_2 路由
    def on_signal(src, sig):
        if sig == SIG_IMPACT_2:
            caster.pending_impact_count = 0     # 强制走最终结算
            saved = caster.pending_skill_id
            caster.pending_skill_id = None
            from core.battle import combat
            combat.apply_pending_attack(b, caster)
            caster.pending_skill_id = saved
    b.engine.on('signal', on_signal)

    apply_pending_attack(b, caster)

    # 投射物 entity 应已 spawn (think_fn=cloudwave_think_fn)
    proj = [e for e in b.engine.entities if e.user_data.get('projectile')]
    assert len(proj) == 1
    p = proj[0]
    assert p.state_code == 0   # FLYING

    # 跑 tick 直到 z 落地 (max 100 tick 防死循环)
    initial_hp = defender.hp
    for _ in range(100):
        b.engine.tick()
        if p.state_code != 0:
            break
    # 落地后 state 切换 + 伤害结算
    assert p.state_code != 0, "投射物没落地"
    assert defender.hp < initial_hp, "落地后没扣血"
    assert len(b.damage_events) == 1


def _b_class_battle_fixture(caster_pos, defender_pos):
    """复用赤雲波 fixture 的简版 battle, 给火龍/破天 用."""
    import random
    from core.anim_engine.engine import Engine
    from core.battle.data import BattleMap, BattleUnit
    from core.battle.queries import BattleQueries
    from core.anim_engine.entity import SIG_IMPACT_2

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
            self.all_units = []
        def _log(self, m): self.messages.append(m)

    b = _B()
    caster = BattleUnit(name="蒙面人", level=1, max_hp=30, hp=30,
                        max_mp=15, mp=15, sg=0, attack=20, defence=5,
                        agile=100, move=3, is_player=True)
    caster.x, caster.y = caster_pos
    defender = BattleUnit(name="d", level=1, max_hp=50, hp=50,
                          max_mp=0, mp=0, sg=0, attack=10, defence=0,
                          agile=0, move=3, is_player=False)
    defender.x, defender.y = defender_pos
    b.players.append(caster); b.enemies.append(defender)
    b.all_units = [caster, defender]

    def on_signal(src, sig):
        if sig == SIG_IMPACT_2:
            caster.pending_impact_count = 0
            saved = caster.pending_skill_id
            caster.pending_skill_id = None
            from core.battle import combat
            combat.apply_pending_attack(b, caster)
            caster.pending_skill_id = saved
    b.engine.on('signal', on_signal)
    return b, caster, defender


def test_huolong_effect_signals_impact_and_damages():
    """火龍斬 (0x22, B 类无物理): spawn effect 在 cursor → 播 16 帧 seq → 信号 IMPACT_2 → 结算伤害."""
    from core.battle.combat import apply_pending_attack
    b, caster, defender = _b_class_battle_fixture((2, 2), (5, 2))
    # cursor 落 defender 上, damage tile 是 3x3 包含 defender
    caster.pending_attack_target = defender
    caster.pending_attack_cursor = (defender.x, defender.y)
    caster.pending_skill_id = 0x22
    caster.pending_impact_count = 0
    caster.pending_impact_total = 1

    apply_pending_attack(b, caster)
    proj = [e for e in b.engine.entities if e.user_data.get('projectile')]
    assert len(proj) == 1
    p = proj[0]
    assert p.atlas_slot == 278   # 火龍 atlas

    initial_hp = defender.hp
    for _ in range(200):
        b.engine.tick()
        if defender.hp < initial_hp:
            break
    assert defender.hp < initial_hp, "火龍 seq 完没扣血"
    assert len(b.damage_events) == 1


def test_potian_full_choreography():
    """破天舞 (0x23) 严格还原: 3 阶段编排.
    Phase SECONDARY: per victim spawn 1 atlas-279 effect (POTIAN_SECONDARY_SEQ 9 帧).
    Phase SCATTER:   per victim spawn 2 atlas-279 scatter (frames 9/10, spring 物理收敛) + 1 atlas-292 trajectory.
    Phase DAMAGE:    coordinator 发 SIG_IMPACT_2 → 走 _pending_damage_range 路径结算.
    """
    from core.battle.combat import apply_pending_attack
    b, caster, defender = _b_class_battle_fixture((2, 2), (5, 2))
    caster.pending_attack_target = defender
    caster.pending_attack_cursor = (defender.x, defender.y)
    caster.pending_skill_id = 0x23
    caster.pending_impact_count = 0
    caster.pending_impact_total = 1

    apply_pending_attack(b, caster)

    # SECONDARY phase: 1 victim → 1 secondary effect + 1 coordinator
    secondaries = [e for e in b.engine.entities
                   if e.user_data.get('projectile') and e.atlas_slot == 279]
    coords = [e for e in b.engine.entities
              if e.user_data.get('kind') == 'potian_coordinator']
    assert len(secondaries) == 1, f"期望 1 个 secondary effect, 实际 {len(secondaries)}"
    assert len(coords) == 1
    assert coords[0].atlas_slot == 0   # coordinator 不渲染

    # 跑到 SCATTER phase: 应 spawn 2 scatter (atlas 279) + 1 trajectory (atlas 292)
    initial_hp = defender.hp
    saw_trajectory = False
    for _ in range(300):
        b.engine.tick()
        traj = [e for e in b.engine.entities
                if e.user_data.get('projectile') and e.atlas_slot == 292]
        if traj:
            saw_trajectory = True
        if defender.hp < initial_hp:
            break

    assert saw_trajectory, "SCATTER 阶段没 spawn trajectory (atlas 292)"
    assert defender.hp < initial_hp, "coordinator 没发 SIG_IMPACT_2 / 没扣血"
    assert len(b.damage_events) == 1


def test_potian_caster_dash_phase_attaches_cdit1_g0():
    """破天舞: caster.entity 存在时, SECONDARY 完应 attach CDIT1_G0_TABLE 到 caster + 标 pending_caster_coord."""
    from core.battle.combat import apply_pending_attack
    from core.projectile import CDIT1_G0_TABLE, _POTIAN_PHASE_CASTER_DASH
    from core.anim_engine.bytecode import tuple_to_bytecode
    b, caster, defender = _b_class_battle_fixture((2, 2), (5, 2))
    # 给 caster 真分配 entity (模拟 begin_attack)
    caster.entity = b.engine.spawn()
    caster.entity.user_data['unit'] = caster
    caster.facing = (1, 0)  # RT
    caster.pending_attack_target = defender
    caster.pending_attack_cursor = (defender.x, defender.y)
    caster.pending_skill_id = 0x23
    caster.pending_impact_count = 0
    caster.pending_impact_total = 1
    apply_pending_attack(b, caster)
    coord = [e for e in b.engine.entities
             if e.user_data.get('kind') == 'potian_coordinator'][0]

    # 跑过 SECONDARY 阶段 (29 ticks)
    for _ in range(30):
        b.engine.tick()
    assert coord.state_code == _POTIAN_PHASE_CASTER_DASH
    assert caster.pending_caster_coord is coord
    # caster.entity 上挂的 seq 应该是 RT 方向的 cdit1_g0 (= 含 atlas 19)
    rt_seq = tuple_to_bytecode(CDIT1_G0_TABLE[3])
    assert caster.entity.seq == rt_seq


def test_potian_per_victim_spawns():
    """破天舞 3x3 范围 N 个 victim → N 个 secondary, scatter 阶段 N×2 scatter + N trajectory."""
    from core.battle.data import BattleUnit
    from core.battle.combat import apply_pending_attack
    b, caster, defender = _b_class_battle_fixture((2, 2), (5, 2))
    # 再加 2 个 enemy 在 3x3 内 (cursor=(5,2), 范围 x∈[4,6] y∈[1,3])
    d2 = BattleUnit(name="d2", level=1, max_hp=50, hp=50, max_mp=0, mp=0, sg=0,
                    attack=10, defence=0, agile=0, move=3, is_player=False)
    d2.x, d2.y = 4, 1
    d3 = BattleUnit(name="d3", level=1, max_hp=50, hp=50, max_mp=0, mp=0, sg=0,
                    attack=10, defence=0, agile=0, move=3, is_player=False)
    d3.x, d3.y = 6, 3
    b.enemies.extend([d2, d3])
    b.all_units.extend([d2, d3])

    caster.pending_attack_target = defender
    caster.pending_attack_cursor = (defender.x, defender.y)
    caster.pending_skill_id = 0x23
    caster.pending_impact_count = 0
    caster.pending_impact_total = 1
    apply_pending_attack(b, caster)

    secondaries = [e for e in b.engine.entities
                   if e.user_data.get('projectile') and e.atlas_slot == 279]
    assert len(secondaries) == 3, f"3 victims → 3 secondaries, 实际 {len(secondaries)}"

    # 跑到 SCATTER 完整 spawn
    for _ in range(40):
        b.engine.tick()
        traj = [e for e in b.engine.entities
                if e.user_data.get('projectile') and e.atlas_slot == 292]
        if len(traj) == 3:
            break
    traj = [e for e in b.engine.entities
            if e.user_data.get('projectile') and e.atlas_slot == 292]
    assert len(traj) == 3, f"3 victims → 3 trajectories, 实际 {len(traj)}"


def test_huolong_potian_impact_spawn_registered():
    """0x21/0x22/0x23 三个 B 类 skill 都注册到 SKILL_IMPACT_SPAWN."""
    from core.skill_seq import has_impact_spawn
    assert has_impact_spawn(0x21) is True
    assert has_impact_spawn(0x22) is True
    assert has_impact_spawn(0x23) is True
    assert has_impact_spawn(0x20) is False   # A 类直接 damage
    assert has_impact_spawn(0x24) is False   # A 类多段
    assert has_impact_spawn(None) is False


def test_skill_impact_extra_vertical_slash():
    """垂直斬 IMPACT 时 dispatcher 额外 spawn 12 帧放电特效 (ds_mag28 + ds_mag13)."""
    from core.skill_seq import (
        SKILL_IMPACT_EXTRA, has_skill_impact_extra, skill_impact_extra_seq,
    )
    assert has_skill_impact_extra(0x20) is True
    assert has_skill_impact_extra(0x21) is False    # 赤雲波 暂未实现
    assert has_skill_impact_extra(None) is False
    seq = skill_impact_extra_seq(0x20)
    fm_ops = [t for t in seq if t[0] == 'fm']
    # 5 帧 atlas 231 + 7 帧 atlas 230 = 12 帧
    assert len(fm_ops) == 12
    atlases = {op[1] for op in fm_ops}
    assert atlases == {230, 231}       # mid-seq atlas 切换
    # 最末 EXIT
    assert seq[-1] == ('exit',)
    # bytecode 编码能跑
    from core.anim_engine.bytecode import tuple_to_bytecode
    bc = tuple_to_bytecode(seq)
    assert len(bc) > 100