"""技能动画 seq 数据 (从 FlyingSB.exe dump).

跟 `raw_attack_seqs.py` 同 tuple 格式: 4 项 (UP/DN/LF/RT) × seq 列表. 这里只放
已 dump 的技能, 其他 skill_id 暂不在表里 (= 用普攻 fallback 或留 TODO).

== 已实现的技能 ==
- 0x20 垂直斬 (蒙面人, dispatcher 0x504345, seq @0x6767d0, atlas cdit1_g0 = 19)
  单 IMPACT 近战, 6 步前冲 + 蓄力 + 出招 + 收招 + 归位.

== 待 dump ==
- 0x21 赤雲波: dispatcher 0x504582, 共享 seq @0x676d28. B 类 (含 spawn edit01 投射物)
- 0x22 火龍斬: dispatcher 0x504b3a, 共享 seq @0x676d28. B 类 (spawn edit02)
- 0x23 破天舞: dispatcher 0x5052aa, 共享 seq @0x6767d0. B 类 (spawn edit03)
- 0x24 無限刀: dispatcher 0x5056d3, seq @0x677494. A 类 5 连击 (复用 cdit1_g1)
- 其他 9 角色 × N 技能, 未 dump
"""

from __future__ import annotations


SKILL_VERTICAL_SLASH = [
    # UP  (seq @0x6763b0)
    [
        ('jump', -1000),
        ('move', 0, -1, 0), ('fm', 19, 0, 3),
        ('move', 0, -1, 0), ('fm', 19, 1, 3),
        ('move', 0, -1, 0), ('fm', 19, 2, 3),
        ('move', 0, -1, 0), ('fm', 19, 3, 3),
        ('move', 0, -1, 0), ('fm', 19, 4, 3),
        ('move', 0, -1, 0), ('fm', 19, 5, 3),
        ('move', 0, -1, 0), ('fm', 19, 6, 12),
        ('move', 0, -6, 0), ('jump', -1001),
        ('fm', 19, 7, 2), ('move', 0, -6, 0),
        ('fm', 19, 8, 3), ('move', 0, -6, 0),
        ('impact',), ('jump', -105),
        ('fm', 19, 9, 3), ('fm', 19, 10, 3), ('fm', 19, 11, 15),
        ('move', 0, 25, 0), ('fm', 19, 0, 0), ('end',),
    ],
    # DN  (seq @0x6764b8)
    [
        ('jump', -1000),
        ('move', 0, 1, 0), ('fm', 19, 12, 3),
        ('move', 0, 1, 0), ('fm', 19, 13, 3),
        ('move', 0, 1, 0), ('fm', 19, 14, 3),
        ('move', 0, 1, 0), ('fm', 19, 15, 3),
        ('move', 0, 1, 0), ('fm', 19, 16, 3),
        ('move', 0, 1, 0), ('fm', 19, 17, 3),
        ('move', 0, 1, 0), ('fm', 19, 18, 12),
        ('move', 0, 6, 0), ('jump', -1001),
        ('fm', 19, 19, 2), ('move', 0, 6, 0),
        ('fm', 19, 20, 3), ('move', 0, 6, 0),
        ('impact',), ('jump', -105),
        ('fm', 19, 21, 3), ('fm', 19, 22, 3), ('fm', 19, 23, 15),
        ('move', 0, -25, 0), ('fm', 19, 12, 0), ('end',),
    ],
    # LF  (seq @0x6765c0)
    [
        ('jump', -1000),
        ('move', -2, 0, 0), ('fm', 19, 24, 3),
        ('move', -2, 0, 0), ('fm', 19, 25, 3),
        ('move', -2, 0, 0), ('fm', 19, 26, 3),
        ('move', -2, 0, 0), ('fm', 19, 27, 3),
        ('move', -2, 0, 0), ('fm', 19, 28, 3),
        ('move', -2, 0, 0), ('fm', 19, 29, 3),
        ('move', -2, 0, 0), ('fm', 19, 30, 12),
        ('move', -8, 0, 0), ('jump', -1001),
        ('fm', 19, 31, 2), ('move', -8, 0, 0),
        ('fm', 19, 32, 3), ('move', -8, 0, 0),
        ('impact',), ('jump', -105),
        ('fm', 19, 33, 3), ('fm', 19, 34, 3), ('fm', 19, 35, 15),
        ('move', 38, 0, 0), ('fm', 19, 24, 0), ('end',),
    ],
    # RT  (seq @0x6766c8)
    [
        ('jump', -1000),
        ('move', 2, 0, 0), ('fm', 19, 36, 3),
        ('move', 2, 0, 0), ('fm', 19, 37, 3),
        ('move', 2, 0, 0), ('fm', 19, 38, 3),
        ('move', 2, 0, 0), ('fm', 19, 39, 3),
        ('move', 2, 0, 0), ('fm', 19, 40, 3),
        ('move', 2, 0, 0), ('fm', 19, 41, 3),
        ('move', 2, 0, 0), ('fm', 19, 42, 12),
        ('move', 8, 0, 0), ('jump', -1001),
        ('fm', 19, 43, 2), ('move', 8, 0, 0),
        ('fm', 19, 44, 3), ('move', 8, 0, 0),
        ('impact',), ('jump', -105),
        ('fm', 19, 45, 3), ('fm', 19, 46, 3), ('fm', 19, 47, 15),
        ('move', -38, 0, 0), ('fm', 19, 36, 0), ('end',),
    ],
]


# 0x24 無限刀: 5 段连击, atlas cdit1_g1 (20) 主体 + 终结切 cdit1_g0 (19).
# exe @0x677494 (4-ptr table), dispatcher 0x5056d3 无 IMPACT extra fx (走默认 OVAL 2-spawn).
# 每个方向 5 个 IMPACT; 我们 anim_engine + apply_pending_attack 已支持多 IMPACT (每次独立
# roll), atlas 切换由 render 端每帧反查 atlas_slot 自动处理.
SKILL_INFINITE_BLADE = [
    # UP  (seq @0x676e44)
    [
        ('jump', -1000),
        ('move', 0, -12, 0), ('fm', 20, 0, 3),
        ('move', 0, -6, 0), ('fm', 20, 1, 3),
        ('move', 0, -6, 0), ('fm', 20, 5, 3), ('fm', 20, 6, 3),
        ('jump', -1001),
        ('move', 0, -6, 0), ('fm', 20, 8, 3),
        ('impact',),
        ('fm', 20, 9, 3), ('fm', 20, 10, 8),
        ('jump', -1001),
        ('move', 0, 6, 0), ('fm', 20, 6, 3),
        ('move', 0, -6, 0), ('fm', 20, 8, 3),
        ('impact',),
        ('fm', 20, 9, 3), ('fm', 20, 10, 8),
        ('jump', -1001),
        ('move', 0, 6, 0), ('fm', 20, 11, 3),
        ('move', 0, -4, 0),
        ('impact',),
        ('fm', 20, 12, 3), ('fm', 20, 13, 5),
        ('jump', -1002), ('jump', -1003),
        ('fm', 20, 13, 3),
        ('impact',),
        ('fm', 20, 14, 3), ('fm', 20, 15, 12),
        ('jump', -1004), ('jump', -1005),
        ('fm', 19, 6, 3), ('fm', 19, 7, 3), ('fm', 19, 8, 3),
        ('move', 0, -6, 0),
        ('impact',),
        ('jump', -105),
        ('fm', 19, 9, 3), ('fm', 19, 10, 3), ('fm', 19, 11, 8),
        ('move', 0, 34, 0), ('fm', 19, 0, 0), ('end',),
    ],
    # DN  (seq @0x676fd8)
    [
        ('jump', -1000),
        ('move', 0, 12, 0), ('fm', 20, 16, 3),
        ('move', 0, 6, 0), ('fm', 20, 17, 3),
        ('move', 0, 6, 0), ('fm', 20, 21, 3), ('fm', 20, 22, 3),
        ('jump', -1001),
        ('move', 0, 6, 0), ('fm', 20, 24, 3),
        ('impact',),
        ('fm', 20, 25, 3), ('fm', 20, 26, 8),
        ('jump', -1001),
        ('move', 0, -6, 0), ('fm', 20, 22, 3),
        ('move', 0, 6, 0), ('fm', 20, 24, 3),
        ('impact',),
        ('fm', 20, 25, 3), ('fm', 20, 26, 8),
        ('jump', -1001),
        ('move', 0, -6, 0), ('fm', 20, 27, 3),
        ('move', 0, 4, 0),
        ('impact',),
        ('fm', 20, 28, 3), ('fm', 20, 29, 5),
        ('jump', -1002), ('jump', -1003),
        ('fm', 20, 29, 3),
        ('impact',),
        ('fm', 20, 30, 3), ('fm', 20, 31, 12),
        ('jump', -1004), ('jump', -1005),
        ('fm', 19, 18, 3), ('fm', 19, 19, 3), ('fm', 19, 20, 3),
        ('move', 0, 6, 0),
        ('impact',),
        ('jump', -105),
        ('fm', 19, 21, 3), ('fm', 19, 22, 3), ('fm', 19, 23, 8),
        ('move', 0, -34, 0), ('fm', 19, 12, 0), ('end',),
    ],
    # LF  (seq @0x67716c)
    [
        ('jump', -1000),
        ('move', -14, 0, 0), ('fm', 20, 32, 3),
        ('move', -8, 0, 0), ('fm', 20, 33, 3),
        ('move', -8, 0, 0), ('fm', 20, 37, 3), ('fm', 20, 38, 3),
        ('jump', -1001),
        ('move', -8, 0, 0), ('fm', 20, 40, 3),
        ('impact',),
        ('fm', 20, 41, 3), ('fm', 20, 42, 8),
        ('move', 8, 0, 0), ('fm', 20, 38, 3),
        ('jump', -1001),
        ('move', -8, 0, 0), ('fm', 20, 40, 3),
        ('impact',),
        ('fm', 20, 41, 3), ('fm', 20, 42, 8),
        ('jump', -1001),
        ('move', 8, 0, 0), ('fm', 20, 43, 3),
        ('move', -6, 0, 0),
        ('impact',),
        ('fm', 20, 44, 3), ('fm', 20, 45, 5),
        ('jump', -1002), ('jump', -1003),
        ('fm', 20, 45, 3),
        ('impact',),
        ('fm', 20, 46, 3), ('fm', 20, 47, 12),
        ('jump', -1004), ('jump', -1005),
        ('fm', 19, 30, 3), ('fm', 19, 31, 3), ('fm', 19, 32, 3),
        ('move', -8, 0, 0),
        ('impact',),
        ('jump', -105),
        ('fm', 19, 33, 3), ('fm', 19, 34, 3), ('fm', 19, 35, 8),
        ('move', 44, 0, 0), ('fm', 19, 24, 0), ('end',),
    ],
    # RT  (seq @0x677300)
    [
        ('jump', -1000),
        ('move', 14, 0, 0), ('fm', 20, 48, 3),
        ('move', 8, 0, 0), ('fm', 20, 49, 3),
        ('move', 8, 0, 0), ('fm', 20, 53, 3), ('fm', 20, 54, 3),
        ('jump', -1001),
        ('move', 8, 0, 0), ('fm', 20, 56, 3),
        ('impact',),
        ('fm', 20, 57, 3), ('fm', 20, 58, 8),
        ('move', -8, 0, 0), ('fm', 20, 54, 3),
        ('jump', -1001),
        ('move', 8, 0, 0), ('fm', 20, 56, 3),
        ('impact',),
        ('fm', 20, 57, 3), ('fm', 20, 58, 8),
        ('jump', -1001),
        ('move', -8, 0, 0), ('fm', 20, 59, 3),
        ('move', 6, 0, 0),
        ('impact',),
        ('fm', 20, 60, 3), ('fm', 20, 61, 5),
        ('jump', -1002), ('jump', -1003),
        ('fm', 20, 61, 3),
        ('impact',),
        ('fm', 20, 62, 3), ('fm', 20, 63, 12),
        ('jump', -1004), ('jump', -1005),
        ('fm', 19, 42, 3), ('fm', 19, 43, 3), ('fm', 19, 44, 3),
        ('move', 8, 0, 0),
        ('impact',),
        ('jump', -105),
        ('fm', 19, 45, 3), ('fm', 19, 46, 3), ('fm', 19, 47, 8),
        ('move', -44, 0, 0), ('fm', 19, 36, 0), ('end',),
    ],
]


# 0x21 赤雲波 + 0x22 火龍斬 共享 cast seq @0x676d28 — 4 帧施法姿 (cdit1_m1 atlas 22) + IMPACT + EXIT.
# IMPACT 时 dispatcher 不直接结算伤害, 而是 spawn 投射物 (SKILL_IMPACT_SPAWN).
SKILL_CAST_CDIT1_M1 = [
    # UP
    [('fm', 22, 0, 3), ('fm', 22, 1, 3), ('fm', 22, 2, 3), ('fm', 22, 3, 5),
     ('impact',), ('exit',)],
    # DN
    [('fm', 22, 4, 3), ('fm', 22, 5, 3), ('fm', 22, 6, 3), ('fm', 22, 7, 5),
     ('impact',), ('exit',)],
    # LF
    [('fm', 22, 8, 3), ('fm', 22, 9, 3), ('fm', 22, 10, 3), ('fm', 22, 11, 5),
     ('impact',), ('exit',)],
    # RT
    [('fm', 22, 12, 3), ('fm', 22, 13, 3), ('fm', 22, 14, 3), ('fm', 22, 15, 5),
     ('impact',), ('exit',)],
]


# skill_id → 4-direction seq table
SKILL_SEQS: dict[int, list[list[tuple]]] = {
    0x20: SKILL_VERTICAL_SLASH,   # 垂直斬
    0x21: SKILL_CAST_CDIT1_M1,    # 赤雲波 (B 类, IMPACT 时 spawn projectile, 不直接掉血)
    0x24: SKILL_INFINITE_BLADE,   # 無限刀 (5 IMPACT, 切 atlas 终结)
}

# skill_id → MP/SG cost (从 PTR_FUN_0068b4b4[i].field[6] dump).
# 0x20 垂直斬 cost=175 — 但实测 175 似乎不合理 (角色 max_mp 通常较低); 实际可能是 SG/SP.
# 暂用 dump 值, 后续 in-game 调试时再校准 (= 是不是 SP 而非 MP 等).
SKILL_COSTS: dict[int, int] = {
    0x20: 175,    # 垂直斬
    0x21: 200,    # 赤雲波
    0x22: 220,    # 火龍斬
    0x23: 900,    # 破天舞
    0x24: 100,    # 無限刀
}


# 技能 IMPACT 时 dispatcher 额外 spawn 的特效 entity seq.
# 跟标准 2-spawn (starburst/oval + 小红刺爆) 叠加, 这是 *第 3 个* effect.
# spawn 位置: defender 中心 + (+25, +28) 基线偏移 (跟 2nd spawn 同样).
# 注意: seq 含 atlas 切换 (中段从 atlas A 换到 B), render 端不要缓存 atlas_key, 每帧从
# entity.atlas_slot 取最新值.
SKILL_IMPACT_EXTRA: dict[int, list[tuple]] = {
    # 0x20 垂直斬 放电特效 (exe @0x676ae4):
    #   ds_mag28 (231) frames 0-4 = 5 帧小白爆
    #   ds_mag13 (230) frames 5-11 = 7 帧紫色放电扩散
    # 全部 ticks=1 (= 40ms/帧), 总 12 帧 ≈ 480ms.
    0x20: [
        ('fm', 231, 0, 1), ('fm', 231, 1, 1), ('fm', 231, 2, 1),
        ('fm', 231, 3, 1), ('fm', 231, 4, 1),
        ('fm', 230, 5, 1), ('fm', 230, 6, 1), ('fm', 230, 7, 1),
        ('fm', 230, 8, 1), ('fm', 230, 9, 1), ('fm', 230, 10, 1),
        ('fm', 230, 11, 1),
        ('exit',),
    ],
}


# B-class skills: 技能 IMPACT (-100) 不直接结算伤害, 而是 spawn 投射物.
# 投射物 think_fn 落地时发 SIG_IMPACT_2 (-250), battle signal handler 那时才结算伤害.
# 表里的 spawn fn 签名: (battle, attacker, target_tile) -> Entity
# target_tile = AIM 选的 cursor 格 (= 投射物落点 / 伤害中心), 不是 defender.x/y —
# AOE 技能 cursor 可能不在敌人身上 (e.g. 赤雲波 cursor 落空格 → 十字 5 格扫边).
def _spawn_cloudwave(battle, attacker, target_tile):
    from core.projectile import spawn_cloudwave_projectile
    return spawn_cloudwave_projectile(battle, attacker, target_tile)


SKILL_IMPACT_SPAWN: dict[int, "callable"] = {
    0x21: _spawn_cloudwave,
    # 0x22 火龙斩 / 0x23 破天舞 后续接
}


def has_impact_spawn(skill_id: int | None) -> bool:
    return skill_id is not None and skill_id in SKILL_IMPACT_SPAWN


def skill_impact_spawn(skill_id: int):
    return SKILL_IMPACT_SPAWN[skill_id]


def has_skill_seq(skill_id: int) -> bool:
    return skill_id in SKILL_SEQS


def has_skill_impact_extra(skill_id: int | None) -> bool:
    return skill_id is not None and skill_id in SKILL_IMPACT_EXTRA


def skill_impact_extra_seq(skill_id: int) -> list[tuple]:
    return SKILL_IMPACT_EXTRA[skill_id]


def skill_seq_for(skill_id: int, facing: tuple[int, int]) -> list[tuple]:
    """skill_id + facing → seq (tuple list). 调用前要 has_skill_seq 判断."""
    from core.attack_seq import facing_to_atk_index
    return SKILL_SEQS[skill_id][facing_to_atk_index(facing)]


def skill_cost(skill_id: int) -> int:
    return SKILL_COSTS.get(skill_id, 0)
