"""攻击者动画序列数据 (从 FlyingSB.exe 逆向得到).

来源:
  PTR_DAT_00670cf0 (ATK_A: 打击式, 4 方向 × 180 字节)  — 玩家槽位 0/1/2 用
  PTR_DAT_0067122c (ATK_B: 劈砍式, 4 方向 × 140 字节)  — 玩家槽位 3-7 用
  PTR_DAT_0067206c (ATK_C: 第三种, 待解码)              — 玩家槽位 8-15 用

opcode 解码 (基于 reaction_seq.py 已解码 + DOIT_melee 状态机分析):
  0x0a0b 10B  MOVE       (dx, dy, _, ticks)  攻击者位移 (插值)
  0x0a04 10B  FM_OVERLAY (atlas, frame, _, ticks)  fm_*_g* 武器残影帧
  0x0a06 10B  IDLE       (atlas=6, frame, ...)
  0x040e  4B  JUMP_STATE (state)
              特殊状态: -100 = 攻击命中(触发受击/闪避), -110 = 序列结束
              其它状态 (-1000=spawn projectile, -105=update flags) 我们忽略

序列索引 [0..3] = 攻击者面朝方向 (0=UP, 1=DOWN, 2=LEFT, 3=RIGHT).

每步 (Python 表达):
  ('move', dx_px, dy_px, ticks)
  ('fm',   atlas_slot, frame, ticks)
  ('idle', atlas_idx, frame, ticks)
  ('impact',)        ← 命中瞬间, 触发受击/闪避动画 + 实际扣血
  ('end',)           ← 序列结束, 攻击者回合可以结束
  ('jump', state)    ← 其它状态跳转, 当前实现忽略
"""
from __future__ import annotations

ATTACK_TICK_MS = 40   # 与 REACTION_TICK_MS 一致


ATK_A: list[list[tuple]] = [
    # UP
    [('move', 0, -12, 1),
     ('fm', 0, 0, 3),
     ('move', 0, 1, 0),  ('fm', 0, 0, 3),
     ('move', 0, 1, 0),  ('fm', 0, 0, 3),
     ('move', 0, 1, 0),  ('fm', 0, 0, 3),
     ('move', 0, 1, 0),  ('fm', 0, 0, 3),
     ('move', 0, 1, 0),  ('fm', 0, 0, 3),
     ('move', 0, -12, 0),
     ('jump', -1000),
     ('impact',),
     ('jump', -105),
     ('fm', 0, 1, 3),
     ('fm', 0, 2, 3),
     ('fm', 0, 3, 5),
     ('move', 0, 24, 0),
     ('fm', 0, 0, 0),
     ('end',)],
    # DOWN
    [('move', 0, 12, 1),
     ('fm', 0, 4, 3),
     ('move', 0, -1, 0), ('fm', 0, 4, 3),
     ('move', 0, -1, 0), ('fm', 0, 4, 3),
     ('move', 0, -1, 0), ('fm', 0, 4, 3),
     ('move', 0, -1, 0), ('fm', 0, 4, 3),
     ('move', 0, -1, 0), ('fm', 0, 4, 3),
     ('move', 0, 12, 0),
     ('jump', -1000), ('impact',), ('jump', -105),
     ('fm', 0, 5, 3), ('fm', 0, 6, 3), ('fm', 0, 7, 5),
     ('move', 0, -24, 0),
     ('fm', 0, 4, 0),
     ('end',)],
    # LEFT
    [('move', -12, 0, 1),
     ('fm', 0, 8, 3),
     ('move', 1, 0, 0), ('fm', 0, 8, 3),
     ('move', 1, 0, 0), ('fm', 0, 8, 3),
     ('move', 1, 0, 0), ('fm', 0, 8, 3),
     ('move', 1, 0, 0), ('fm', 0, 8, 3),
     ('move', 1, 0, 0), ('fm', 0, 8, 3),
     ('move', -12, 0, 0),
     ('jump', -1000), ('impact',), ('jump', -105),
     ('fm', 0, 9, 3), ('fm', 0, 10, 3), ('fm', 0, 11, 5),
     ('move', 24, 0, 0),
     ('fm', 0, 8, 0),
     ('end',)],
    # RIGHT
    [('move', 12, 0, 1),
     ('fm', 0, 12, 3),
     ('move', -1, 0, 0), ('fm', 0, 12, 3),
     ('move', -1, 0, 0), ('fm', 0, 12, 3),
     ('move', -1, 0, 0), ('fm', 0, 12, 3),
     ('move', -1, 0, 0), ('fm', 0, 12, 3),
     ('move', -1, 0, 0), ('fm', 0, 12, 3),
     ('move', 12, 0, 0),
     ('jump', -1000), ('impact',), ('jump', -105),
     ('fm', 0, 13, 3), ('fm', 0, 14, 3), ('fm', 0, 15, 5),
     ('move', -24, 0, 0),
     ('fm', 0, 12, 0),
     ('end',)],
]


ATK_B: list[list[tuple]] = [
    # UP
    [('move', 0, -12, 0),
     ('fm', 1, 0, 3),
     ('fm', 1, 1, 12),
     ('move', 0, -6, 0),
     ('fm', 1, 2, 3),
     ('move', 0, -6, 0),
     ('jump', -1000), ('impact',), ('jump', -105),
     ('fm', 1, 3, 3),
     ('move', 0, -6, 0),
     ('fm', 1, 4, 3),
     ('fm', 1, 5, 8),
     ('move', 0, 30, 0),
     ('fm', 1, 0, 0),
     ('end',)],
    # DOWN
    [('move', 0, 12, 0),
     ('fm', 1, 6, 3),
     ('fm', 1, 7, 12),
     ('move', 0, 6, 0),
     ('fm', 1, 8, 3),
     ('move', 0, 6, 0),
     ('jump', -1000), ('impact',), ('jump', -105),
     ('fm', 1, 9, 3),
     ('move', 0, 6, 0),
     ('fm', 1, 10, 3),
     ('fm', 1, 11, 8),
     ('move', 0, -30, 0),
     ('fm', 1, 6, 0),
     ('end',)],
    # LEFT
    [('move', -16, 0, 0),
     ('fm', 1, 12, 3),
     ('fm', 1, 13, 12),
     ('move', -8, 0, 0),
     ('fm', 1, 14, 3),
     ('move', -8, 0, 0),
     ('jump', -1000), ('impact',), ('jump', -105),
     ('fm', 1, 15, 3),
     ('move', -8, 0, 0),
     ('fm', 1, 16, 3),
     ('fm', 1, 17, 8),
     ('move', 40, 0, 0),
     ('fm', 1, 12, 0),
     ('end',)],
    # RIGHT
    [('move', 16, 0, 0),
     ('fm', 1, 18, 3),
     ('fm', 1, 19, 12),
     ('move', 8, 0, 0),
     ('fm', 1, 20, 3),
     ('move', 8, 0, 0),
     ('jump', -1000), ('impact',), ('jump', -105),
     ('fm', 1, 21, 3),
     ('move', 8, 0, 0),
     ('fm', 1, 22, 3),
     ('fm', 1, 23, 8),
     ('move', -40, 0, 0),
     ('fm', 1, 18, 0),
     ('end',)],
]


def facing_to_atk_index(facing: tuple[int, int]) -> int:
    dx, dy = facing
    if dy < 0: return 0   # UP
    if dy > 0: return 1   # DOWN
    if dx < 0: return 2   # LEFT
    return 3              # RIGHT


# 按角色名选风格 (character_sprites.ATTACK_PROFILES 配置)
def attack_seq_for(char_name: str, facing: tuple[int, int]) -> list[tuple]:
    from core.character_sprites import attack_style
    style = attack_style(char_name)
    table = ATK_A if style == "A" else ATK_B    # 'C' 待解, 暂用 B
    return table[facing_to_atk_index(facing)]


def frames_per_dir(char_name: str) -> int:
    """fm atlas 每方向用前 N 列 (ATK_A=4, ATK_B=6)."""
    from core.character_sprites import attack_style
    return 4 if attack_style(char_name) == "A" else 6
