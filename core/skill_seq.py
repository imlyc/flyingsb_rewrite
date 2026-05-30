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


# ============================================================
# 三藏法师 5 技能 (skill_id 0x14..0x18). exe dispatcher + seq table dump @ sam_seqs.txt.
# ============================================================
# 0x14 南瓜破 (头击): A 类, atlas csam_g5=12, 1 IMPACT. wrapper 加 sound 0xa9/0xbf.
# 0x15 生命之火: B 类回血 (跳过 — 需 heal infrastructure)
# 0x16 不败三击: A 类多段, atlas csam_g2=9, 3 IMPACT. wrapper 加 sound 0xbd.
# 0x17 凤凰掌: B 类投射物, cast atlas csam_g4=11, 1 IMPACT → spawn phoenix (atlas 269-272/dir).
# 0x18 三藏神拳 (最高武学): A 类多段, atlas csam_g2/g1/g3 (9/8/10), 5 IMPACT, 3 段切换.

SKILL_SAM_PUMPKIN_BREAK = [   # 0x14 @0x6729d8
    # UP
    [
        ('fm', 12, 0, 6), ('fm', 12, 1, 12),
        ('move', 0, -12, 0), ('jump', -1000), ('jump', -1001),
        ('fm', 12, 2, 2), ('move', 0, -8, 2),
        ('impact',), ('jump', -105),
        ('fm', 12, 3, 2), ('move', 0, -6, 2),
        ('move', 0, -2, 3), ('move', 0, -2, 3), ('move', 0, -2, 3),
        ('move', 0, 32, 0), ('fm', 12, 0, 0), ('end',),
    ],
    # DN
    [
        ('fm', 12, 4, 6), ('fm', 12, 5, 12),
        ('move', 0, 12, 0), ('jump', -1000), ('jump', -1001),
        ('fm', 12, 6, 2), ('move', 0, 8, 2),
        ('impact',), ('jump', -105),
        ('fm', 12, 7, 2), ('move', 0, 6, 2),
        ('move', 0, 2, 3), ('move', 0, 2, 3), ('move', 0, 2, 3),
        ('move', 0, -32, 0), ('fm', 12, 4, 0), ('end',),
    ],
    # LF
    [
        ('fm', 12, 8, 6), ('fm', 12, 9, 12),
        ('move', -16, 0, 0), ('jump', -1000), ('jump', -1001),
        ('fm', 12, 10, 2), ('move', -12, 0, 2),
        ('impact',), ('jump', -105),
        ('fm', 12, 11, 2), ('move', -8, 0, 2),
        ('move', -4, 0, 3), ('move', -2, 0, 3), ('move', -2, 0, 3),
        ('move', 44, 0, 0), ('fm', 12, 8, 0), ('end',),
    ],
    # RT
    [
        ('fm', 12, 12, 6), ('fm', 12, 13, 12),
        ('move', 16, 0, 0), ('jump', -1000), ('jump', -1001),
        ('fm', 12, 14, 2), ('move', 12, 0, 2),
        ('impact',), ('jump', -105),
        ('fm', 12, 15, 2), ('move', 8, 0, 2),
        ('move', 4, 0, 3), ('move', 2, 0, 3), ('move', 2, 0, 3),
        ('move', -44, 0, 0), ('fm', 12, 12, 0), ('end',),
    ],
]

SKILL_SAM_THREE_HIT = [   # 0x16 @0x67304c, 3 IMPACTs/dir (多段 dedup 只末段结算)
    # UP
    [
        ('move', 0, -8, 0), ('fm', 9, 0, 3), ('fm', 9, 1, 12), ('move', 0, -4, 0),
        ('jump', -1000), ('jump', -1001), ('fm', 9, 2, 3), ('move', 0, -4, 0),
        ('impact',),
        ('fm', 9, 3, 3), ('fm', 9, 1, 5), ('move', 0, -2, 0),
        ('jump', -1000), ('jump', -1001), ('fm', 9, 2, 3), ('move', 0, -2, 0),
        ('impact',),
        ('fm', 9, 3, 3), ('move', 0, -4, 0), ('fm', 9, 4, 5),
        ('jump', -1000), ('jump', -1001), ('fm', 9, 5, 3), ('move', 0, -4, 0),
        ('impact',), ('jump', -105),
        ('fm', 9, 6, 3), ('move', 0, -4, 0), ('fm', 9, 7, 3), ('fm', 9, 8, 5),
        ('move', 0, 32, 0), ('end',),
    ],
    # DN
    [
        ('move', 0, 8, 0), ('fm', 9, 10, 3), ('fm', 9, 11, 12), ('move', 0, 4, 0),
        ('jump', -1000), ('jump', -1001), ('fm', 9, 12, 3), ('move', 0, 4, 0),
        ('impact',),
        ('fm', 9, 13, 3), ('fm', 9, 11, 5), ('move', 0, 2, 0),
        ('jump', -1000), ('jump', -1001), ('fm', 9, 12, 3), ('move', 0, 2, 0),
        ('impact',),
        ('fm', 9, 13, 3), ('move', 0, 4, 0), ('fm', 9, 14, 5),
        ('jump', -1000), ('jump', -1001), ('fm', 9, 15, 3), ('move', 0, 4, 0),
        ('impact',), ('jump', -105),
        ('fm', 9, 16, 3), ('move', 0, 4, 0), ('fm', 9, 17, 3), ('fm', 9, 18, 5),
        ('move', 0, -32, 0), ('end',),
    ],
    # LF
    [
        ('move', -12, 0, 0), ('fm', 9, 20, 3), ('fm', 9, 21, 12), ('move', -6, 0, 0),
        ('jump', -1000), ('jump', -1001), ('fm', 9, 22, 3), ('move', -6, 0, 0),
        ('impact',),
        ('fm', 9, 23, 3), ('fm', 9, 21, 5), ('move', -2, 0, 0),
        ('jump', -1000), ('jump', -1001), ('fm', 9, 22, 3), ('move', -2, 0, 0),
        ('impact',),
        ('fm', 9, 23, 3), ('move', -6, 0, 0), ('fm', 9, 24, 5),
        ('jump', -1000), ('jump', -1001), ('fm', 9, 25, 3), ('move', -6, 0, 0),
        ('impact',), ('jump', -105),
        ('fm', 9, 26, 3), ('move', -6, 0, 0), ('fm', 9, 27, 3), ('fm', 9, 28, 5),
        ('move', 46, 0, 0), ('end',),
    ],
    # RT
    [
        ('move', 12, 0, 0), ('fm', 9, 30, 3), ('fm', 9, 31, 12), ('move', 6, 0, 0),
        ('jump', -1000), ('jump', -1001), ('fm', 9, 32, 3), ('move', 6, 0, 0),
        ('impact',),
        ('fm', 9, 33, 3), ('fm', 9, 31, 5), ('move', 2, 0, 0),
        ('jump', -1000), ('jump', -1001), ('fm', 9, 32, 3), ('move', 2, 0, 0),
        ('impact',),
        ('fm', 9, 33, 3), ('move', 6, 0, 0), ('fm', 9, 34, 5),
        ('jump', -1000), ('jump', -1001), ('fm', 9, 35, 3), ('move', 6, 0, 0),
        ('impact',), ('jump', -105),
        ('fm', 9, 36, 3), ('move', 6, 0, 0), ('fm', 9, 37, 3), ('fm', 9, 38, 5),
        ('move', -46, 0, 0), ('end',),
    ],
]

SKILL_SAM_LIFE_FIRE = [   # 0x15 生命之火 cast @0x672bb8, atlas csam_g0=7. 回血技能 (heal).
    # UP
    [
        ('fm', 7, 0, 6), ('fm', 7, 1, 6), ('fm', 7, 2, 12), ('move', 0, -4, 0),
        ('fm', 7, 3, 3), ('move', 0, -6, 0), ('impact',),
        ('fm', 7, 4, 3), ('move', 0, -4, 0), ('fm', 7, 5, 3), ('move', 0, 14, 0),
        ('fm', 7, 0, 0), ('end',),
    ],
    # DN
    [
        ('fm', 7, 6, 6), ('fm', 7, 7, 6), ('fm', 7, 8, 12), ('move', 0, 4, 0),
        ('fm', 7, 9, 3), ('move', 0, 6, 0), ('impact',),
        ('fm', 7, 10, 3), ('move', 0, 4, 0), ('fm', 7, 11, 3), ('move', 0, -14, 0),
        ('fm', 7, 6, 0), ('end',),
    ],
    # LF
    [
        ('fm', 7, 12, 6), ('fm', 7, 13, 6), ('fm', 7, 14, 12), ('move', -6, 0, 0),
        ('fm', 7, 15, 3), ('move', -8, 0, 0), ('impact',),
        ('fm', 7, 16, 3), ('move', -6, 0, 0), ('fm', 7, 17, 3), ('move', 20, 0, 0),
        ('fm', 7, 12, 0), ('end',),
    ],
    # RT
    [
        ('fm', 7, 18, 6), ('fm', 7, 19, 6), ('fm', 7, 20, 12), ('move', 6, 0, 0),
        ('fm', 7, 21, 3), ('move', 8, 0, 0), ('impact',),
        ('fm', 7, 22, 3), ('move', 6, 0, 0), ('fm', 7, 23, 3), ('move', -20, 0, 0),
        ('fm', 7, 18, 0), ('end',),
    ],
]

SKILL_SAM_PHOENIX_CAST = [   # 0x17 caster cast anim @0x6733ac, atlas csam_g4=11
    # UP
    [
        ('fm', 11, 0, 6), ('move', 0, 6, 0),
        ('fm', 11, 1, 6), ('move', 0, 6, 0),
        ('fm', 11, 2, 6), ('fm', 11, 3, 12),
        ('move', 0, -8, 0),
        ('impact',),
        ('fm', 11, 4, 3), ('move', 0, -10, 0),
        ('fm', 11, 5, 3), ('exit',),
    ],
    # DN
    [
        ('fm', 11, 6, 6), ('move', 0, -6, 0),
        ('fm', 11, 7, 6), ('move', 0, -6, 0),
        ('fm', 11, 8, 6), ('fm', 11, 9, 12),
        ('move', 0, 8, 0),
        ('impact',),
        ('fm', 11, 10, 3), ('move', 0, 10, 0),
        ('fm', 11, 11, 3), ('exit',),
    ],
    # LF
    [
        ('fm', 11, 12, 6), ('move', 6, 0, 0),
        ('fm', 11, 13, 6), ('move', 6, 0, 0),
        ('fm', 11, 14, 6), ('fm', 11, 15, 12),
        ('move', -8, 0, 0),
        ('fm', 11, 16, 3),
        ('impact',),
        ('move', -10, 0, 0),
        ('fm', 11, 17, 3), ('exit',),
    ],
    # RT
    [
        ('fm', 11, 18, 6), ('move', -6, 0, 0),
        ('fm', 11, 19, 6), ('move', -6, 0, 0),
        ('fm', 11, 20, 6), ('fm', 11, 21, 12),
        ('move', 8, 0, 0),
        ('impact',),
        ('fm', 11, 22, 3), ('move', 10, 0, 0),
        ('fm', 11, 23, 3), ('exit',),
    ],
]

SAM_0x18_GOD_FIST_DATA = [
  # UP (seq @0x6733bc)
  [
    ('jump', -1000),
    ('move', 0, -8, 0),
    ('fm', 9, 0, 3),
    ('fm', 9, 1, 12),
    ('move', 0, -4, 0),
    ('jump', -1001),
    ('fm', 9, 2, 3),
    ('move', 0, -4, 0),
    ('impact',),
    ('fm', 9, 3, 3),
    ('fm', 9, 1, 5),
    ('move', 0, -2, 0),
    ('jump', -1001),
    ('fm', 9, 2, 3),
    ('move', 0, -2, 0),
    ('impact',),
    ('fm', 9, 3, 3),
    ('move', 0, -4, 0),
    ('fm', 9, 4, 5),
    ('jump', -1001),
    ('fm', 9, 5, 3),
    ('move', 0, -4, 0),
    ('impact',),
    ('fm', 9, 6, 3),
    ('move', 0, -4, 0),
    ('fm', 9, 7, 3),
    ('fm', 9, 8, 5),
    ('jump', -1002),
    ('fm', 8, 12, 3),
    ('fm', 8, 13, 8),
    ('jump', -1003),
    ('move', 0, -2, 0),
    ('fm', 8, 14, 3),
    ('move', 0, -2, 0),
    ('fm', 8, 15, 3),
    ('move', 0, -2, 0),
    ('fm', 8, 16, 3),
    ('move', 0, -2, 0),
    ('fm', 8, 17, 3),
    ('move', 0, -2, 0),
    ('impact',),
    ('fm', 8, 18, 3),
    ('move', 0, -1, 0),
    ('fm', 8, 19, 3),
    ('move', 0, -1, 0),
    ('fm', 8, 20, 3),
    ('move', 0, -1, 0),
    ('fm', 8, 21, 3),
    ('move', 0, 0, 3),
    ('move', 0, 0, 3),
    ('fm', 8, 22, 3),
    ('move', 0, 0, 0),
    ('fm', 8, 23, 8),
    ('jump', -1004),
    ('fm', 10, 0, 3),
    ('move', 0, -3, 0),
    ('fm', 10, 1, 12),
    ('move', 0, -3, 0),
    ('jump', -1005),
    ('fm', 10, 2, 3),
    ('move', 0, -2, 0),
    ('impact',),
    ('jump', -105),
    ('fm', 10, 3, 3),
    ('move', 0, -2, 0),
    ('fm', 10, 4, 3),
    ('move', 0, -2, 3),
    ('move', 0, -2, 0),
    ('fm', 10, 5, 3),
    ('move', 0, -1, 3),
    ('move', 0, -1, 3),
    ('move', 0, -1, 0),
    ('fm', 10, 6, 3),
    ('move', 0, -1, 3),
    ('move', 0, -1, 0),
    ('fm', 10, 7, 3),
    ('move', 0, -1, 0),
    ('fm', 10, 8, 3),
    ('move', 0, -1, 3),
    ('move', 0, 66, 0),
    ('end',),
  ],
  # DN (seq @0x673690)
  [
    ('jump', -1000),
    ('move', 0, 8, 0),
    ('fm', 9, 10, 3),
    ('fm', 9, 11, 12),
    ('move', 0, 4, 0),
    ('jump', -1001),
    ('fm', 9, 12, 3),
    ('move', 0, 4, 0),
    ('impact',),
    ('fm', 9, 13, 3),
    ('fm', 9, 11, 5),
    ('move', 0, 2, 0),
    ('jump', -1001),
    ('fm', 9, 12, 3),
    ('move', 0, 2, 0),
    ('impact',),
    ('fm', 9, 13, 3),
    ('move', 0, 4, 0),
    ('fm', 9, 14, 5),
    ('jump', -1001),
    ('fm', 9, 15, 3),
    ('move', 0, 4, 0),
    ('impact',),
    ('fm', 9, 16, 3),
    ('move', 0, 4, 0),
    ('fm', 9, 17, 3),
    ('fm', 9, 18, 5),
    ('jump', -1002),
    ('fm', 8, 0, 3),
    ('fm', 8, 1, 8),
    ('move', 0, 2, 0),
    ('jump', -1003),
    ('fm', 8, 1, 3),
    ('move', 0, 2, 0),
    ('fm', 8, 3, 3),
    ('move', 0, 2, 0),
    ('fm', 8, 4, 3),
    ('move', 0, 2, 0),
    ('fm', 8, 5, 3),
    ('move', 0, 2, 0),
    ('impact',),
    ('fm', 8, 6, 3),
    ('move', 0, 1, 0),
    ('fm', 8, 7, 3),
    ('move', 0, 1, 0),
    ('fm', 8, 8, 3),
    ('move', 0, 1, 0),
    ('fm', 8, 9, 3),
    ('move', 0, 0, 3),
    ('move', 0, 0, 3),
    ('fm', 8, 10, 3),
    ('move', 0, 0, 0),
    ('fm', 8, 11, 8),
    ('jump', -1004),
    ('fm', 10, 9, 3),
    ('move', 0, 3, 0),
    ('fm', 10, 10, 12),
    ('move', 0, 3, 0),
    ('jump', -1005),
    ('fm', 10, 11, 3),
    ('move', 0, 2, 0),
    ('impact',),
    ('jump', -105),
    ('fm', 10, 12, 3),
    ('move', 0, 2, 0),
    ('fm', 10, 13, 3),
    ('move', 0, 2, 3),
    ('move', 0, 2, 0),
    ('fm', 10, 14, 3),
    ('move', 0, 1, 3),
    ('move', 0, 1, 3),
    ('move', 0, 1, 0),
    ('fm', 10, 15, 3),
    ('move', 0, 1, 3),
    ('move', 0, 1, 0),
    ('fm', 10, 16, 3),
    ('move', 0, 1, 0),
    ('fm', 10, 17, 3),
    ('move', 0, 1, 3),
    ('move', 0, -66, 0),
    ('end',),
  ],
  # LF (seq @0x673964)
  [
    ('jump', -1000),
    ('move', -12, 0, 0),
    ('fm', 9, 20, 3),
    ('fm', 9, 21, 12),
    ('move', -6, 0, 0),
    ('jump', -1001),
    ('fm', 9, 22, 3),
    ('move', -6, 0, 0),
    ('impact',),
    ('fm', 9, 23, 3),
    ('fm', 9, 21, 5),
    ('move', -2, 0, 0),
    ('jump', -1001),
    ('fm', 9, 22, 3),
    ('move', -2, 0, 0),
    ('impact',),
    ('fm', 9, 23, 3),
    ('move', -6, 0, 0),
    ('fm', 9, 24, 5),
    ('jump', -1001),
    ('fm', 9, 25, 3),
    ('move', -6, 0, 0),
    ('impact',),
    ('fm', 9, 26, 3),
    ('move', -6, 0, 0),
    ('fm', 9, 27, 3),
    ('fm', 9, 28, 5),
    ('jump', -1002),
    ('fm', 8, 36, 3),
    ('fm', 8, 37, 8),
    ('jump', -1003),
    ('move', -2, 0, 0),
    ('fm', 8, 38, 3),
    ('move', -2, 0, 0),
    ('fm', 8, 39, 3),
    ('move', -2, 0, 0),
    ('fm', 8, 40, 3),
    ('move', -2, 0, 0),
    ('fm', 8, 41, 3),
    ('move', -2, 0, 0),
    ('impact',),
    ('fm', 8, 42, 3),
    ('move', -2, 0, 0),
    ('fm', 8, 43, 3),
    ('move', -2, 0, 0),
    ('fm', 8, 44, 3),
    ('move', -2, 0, 0),
    ('fm', 8, 45, 3),
    ('move', 0, 0, 3),
    ('move', 0, 0, 3),
    ('fm', 8, 46, 3),
    ('move', 0, 0, 0),
    ('fm', 8, 47, 8),
    ('jump', -1004),
    ('fm', 10, 18, 3),
    ('move', -4, 0, 0),
    ('fm', 10, 19, 12),
    ('move', -4, 0, 0),
    ('jump', -1005),
    ('fm', 10, 20, 3),
    ('move', -2, 0, 0),
    ('impact',),
    ('jump', -105),
    ('fm', 10, 21, 3),
    ('move', -2, 0, 0),
    ('fm', 10, 22, 3),
    ('move', -2, 0, 3),
    ('move', -2, 0, 0),
    ('fm', 10, 23, 3),
    ('move', -2, 0, 3),
    ('move', -2, 0, 3),
    ('move', -2, 0, 0),
    ('fm', 10, 24, 3),
    ('move', -2, 0, 3),
    ('move', -2, 0, 0),
    ('fm', 10, 25, 3),
    ('move', -2, 0, 0),
    ('fm', 10, 26, 3),
    ('move', -2, 0, 3),
    ('move', 90, 0, 0),
    ('end',),
  ],
  # RT (seq @0x673c38)
  [
    ('jump', -1000),
    ('move', 12, 0, 0),
    ('fm', 9, 30, 3),
    ('fm', 9, 31, 12),
    ('move', 6, 0, 0),
    ('jump', -1001),
    ('fm', 9, 32, 3),
    ('move', 6, 0, 0),
    ('impact',),
    ('fm', 9, 33, 3),
    ('fm', 9, 31, 5),
    ('move', 2, 0, 0),
    ('jump', -1001),
    ('fm', 9, 32, 3),
    ('move', 2, 0, 0),
    ('impact',),
    ('fm', 9, 33, 3),
    ('move', 6, 0, 0),
    ('fm', 9, 34, 5),
    ('jump', -1001),
    ('fm', 9, 35, 3),
    ('move', 6, 0, 0),
    ('impact',),
    ('fm', 9, 36, 3),
    ('move', 6, 0, 0),
    ('fm', 9, 37, 3),
    ('fm', 9, 38, 5),
    ('jump', -1002),
    ('fm', 8, 24, 3),
    ('fm', 8, 25, 8),
    ('move', 2, 0, 0),
    ('jump', -1003),
    ('fm', 8, 26, 3),
    ('move', 2, 0, 0),
    ('fm', 8, 27, 3),
    ('move', 2, 0, 0),
    ('fm', 8, 28, 3),
    ('move', 2, 0, 0),
    ('fm', 8, 29, 3),
    ('move', 2, 0, 0),
    ('impact',),
    ('fm', 8, 30, 3),
    ('move', 2, 0, 0),
    ('fm', 8, 31, 3),
    ('move', 2, 0, 0),
    ('fm', 8, 32, 3),
    ('move', 2, 0, 0),
    ('fm', 8, 33, 3),
    ('move', 0, 0, 3),
    ('move', 0, 0, 3),
    ('fm', 8, 34, 3),
    ('move', 0, 0, 0),
    ('fm', 8, 35, 8),
    ('jump', -1004),
    ('fm', 10, 27, 3),
    ('move', 4, 0, 0),
    ('fm', 10, 28, 12),
    ('move', 4, 0, 0),
    ('jump', -1005),
    ('fm', 10, 29, 3),
    ('move', 2, 0, 0),
    ('impact',),
    ('jump', -105),
    ('fm', 10, 30, 3),
    ('move', 2, 0, 0),
    ('fm', 10, 31, 3),
    ('move', 2, 0, 3),
    ('move', 2, 0, 0),
    ('fm', 10, 32, 3),
    ('move', 2, 0, 3),
    ('move', 2, 0, 3),
    ('move', 2, 0, 0),
    ('fm', 10, 33, 3),
    ('move', 2, 0, 3),
    ('move', 2, 0, 0),
    ('fm', 10, 34, 3),
    ('move', 2, 0, 0),
    ('fm', 10, 35, 3),
    ('move', 2, 0, 3),
    ('move', -90, 0, 0),
    ('end',),
  ],
]


# 0x18 三藏神拳 @0x673f0c — 3 段切换 (csam_g2 → csam_g1 → csam_g3), 5 IMPACTs/dir.
# 这是 三藏 最高武学, 38 fm ops/dir. 4 方向逐字 paste 自 sam_seqs.txt.
SKILL_SAM_GOD_FIST: list[list[tuple]] = SAM_0x18_GOD_FIST_DATA  # noqa: 见下方


# ============================================================
# 孙悟空 10 技能 (skill_id 0x00..0x09). 全 self-cast AOE: caster 念咒 → IMPACT 对
# tmpl 范围内所有敌人结算伤害 + 普攻同款命中特效 (ef010 方向爆 + et00 刺, 见 hit_effect_seq).
# exe dispatcher 见 son_dispatch.txt. 大部分共享念咒 cast seq @0x670dc4 (idle op slot5,
# 8 帧念咒, 方向无关). 少数有专属 summon (分身 0x671b0c / 超亂舞 0x671db0 / 朱雀凤凰火焰).
#
# ⚠ caster 念咒 atlas: 原版 cast seq 用 `idle 5` (slot 5 = 孙悟空 primary-attack atlas 槽,
#   per-character remap, memory 标注静态死路). 我们用全局 atlas 2 (cson_e0, 44帧施法/特效图)
#   frames 0-7 近似念咒姿态. 走 is_global 渲染路径 (2 not in {0,1,5}). 待游戏内视觉校准.
# ============================================================
_SON_CAST_DAJINGANG = [   # 0x670dc4 念咒, cson_e0 frames 0-7 (方向无关)
    ('fm', 2, 0, 2), ('fm', 2, 1, 2), ('fm', 2, 2, 2), ('fm', 2, 3, 2),
    ('fm', 2, 4, 2), ('fm', 2, 5, 2), ('fm', 2, 6, 2), ('fm', 2, 7, 3),
    ('impact',),                      # 念咒完 → AOE 伤害 + 范围每敌人命中特效
    ('fm', 2, 0, 0), ('end',),
]
# idle op 方向无关 → 4 方向共用同一 cast seq.
SKILL_SON_DAJINGANG: list[list[tuple]] = [_SON_CAST_DAJINGANG] * 4


# skill_id → 4-direction seq table
SKILL_SEQS: dict[int, list[list[tuple]]] = {
    0x00: SKILL_SON_DAJINGANG,        # 孙悟空 大金刚 (self-cast AOE 菱r2)
    0x14: SKILL_SAM_PUMPKIN_BREAK,    # 三藏 南瓜破 (A 类)
    0x15: SKILL_SAM_LIFE_FIRE,        # 三藏 生命之火 (heal, 回血技能)
    0x16: SKILL_SAM_THREE_HIT,        # 三藏 不败三击 (A 类 3 IMPACT)
    0x17: SKILL_SAM_PHOENIX_CAST,     # 三藏 凤凰掌 (B 类, cast + spawn phoenix)
    0x18: SKILL_SAM_GOD_FIST,         # 三藏 三藏神拳 (A 类 5 IMPACT, 3 段切换)
    0x20: SKILL_VERTICAL_SLASH,       # 蒙面人 垂直斬
    0x21: SKILL_CAST_CDIT1_M1,        # 赤雲波 (B 类, IMPACT 时 spawn projectile, 不直接掉血)
    0x22: SKILL_CAST_CDIT1_M1,        # 火龍斬 (B 类, 共享 cast seq, IMPACT 时 spawn effect)
    0x23: SKILL_CAST_CDIT1_M1,        # 破天舞 (B 类, 共享 cast seq, IMPACT 时 spawn 多 effect)
    0x24: SKILL_INFINITE_BLADE,       # 無限刀 (5 IMPACT, 切 atlas 终结)
}

# skill_id → MP/SG cost (从 PTR_FUN_0068b4b4[i].field[6] dump).
# 0x20 垂直斬 cost=175 — 但实测 175 似乎不合理 (角色 max_mp 通常较低); 实际可能是 SG/SP.
# 暂用 dump 值, 后续 in-game 调试时再校准 (= 是不是 SP 而非 MP 等).
SKILL_COSTS: dict[int, int] = {
    0x00: 33,     # 大金刚
    0x01: 55,     # 猛将神君青龙
    0x02: 100,    # 甲兵神君白虎
    0x03: 160,    # 酷酷猫
    0x04: 280,    # 分身术
    0x05: 430,    # 凌光神君朱雀
    0x06: 660,    # 集明神君玄武
    0x07: 960,    # 美丽月兔
    0x08: 2000,   # 超级乱舞
    0x09: 60,     # M.凤凰
    0x14: 120,    # 南瓜破
    0x15: 330,    # 生命之火 (未实现, 但 cost 记下)
    0x16: 440,    # 不败三击
    0x17: 990,    # 凤凰掌
    0x18: 110,    # 三藏神拳
    0x20: 175,    # 垂直斬
    0x21: 200,    # 赤雲波
    0x22: 220,    # 火龍斬
    0x23: 900,    # 破天舞
    0x24: 100,    # 無限刀
}


# ---- 辅助/回血技能 (target 友军, IMPACT 时回血而非伤害) ----
# 0x15 生命之火: 蓝火回 HP. exe dispatcher 0x4fe111 走 victim 循环 + esum1 burst (atlas 299).
# heal 量公式 exe 未精确提取, 暂用 caster.attack * 3 (典型 三藏 ~60). TODO 校准.
SKILL_HEAL_SKILLS: set[int] = {0x15}


def is_heal_skill(skill_id: int | None) -> bool:
    return skill_id is not None and skill_id in SKILL_HEAL_SKILLS


def heal_amount(attacker, skill_id: int) -> int:
    """生命之火回血量. 暂用 caster.attack * 3 (placeholder, 待 exe 校准)."""
    return max(1, attacker.attack * 3)


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


def _spawn_huolong(battle, attacker, target_tile):
    from core.projectile import spawn_huolong_effect
    return spawn_huolong_effect(battle, attacker, target_tile)


def _spawn_potian(battle, attacker, target_tile):
    from core.projectile import spawn_potian_effects
    return spawn_potian_effects(battle, attacker, target_tile)


def _spawn_phoenix(battle, attacker, target_tile):
    from core.projectile import spawn_phoenix_effect
    return spawn_phoenix_effect(battle, attacker, target_tile)


SKILL_IMPACT_SPAWN: dict[int, "callable"] = {
    0x17: _spawn_phoenix,    # 三藏 凤凰掌
    0x21: _spawn_cloudwave,
    0x22: _spawn_huolong,
    0x23: _spawn_potian,
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
