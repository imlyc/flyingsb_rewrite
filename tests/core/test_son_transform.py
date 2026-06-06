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
        # 抑制期不变绝不允许 hp=0 的敌人启动死亡动画
        for d in (d1, d2):
            if d.settle_pending:
                assert d.death_anim_time_ms < 0
        if b._pending_turn_end:
            break

    assert saw_suppressed, "致死敌人应在 eson 砸完前被抑制 (依次造成伤害)"
    # 结算后: 两者同时释放, 同步开始死亡动画
    assert d1.hp == 0 and d2.hp == 0
    assert not d1.settle_pending and not d2.settle_pending
    assert d1.death_anim_time_ms >= 0 and d2.death_anim_time_ms >= 0


def test_dajingang_is_son_transform_skill():
    from core.son_transform import is_son_transform_skill
    assert is_son_transform_skill(0x00) is True
    assert is_son_transform_skill(0x14) is False   # 三藏南瓜破
    assert is_son_transform_skill(None) is False
