"""攻击者动画 seq 选择 + 解释器常量.

数据源: `core.raw_attack_seqs` (从 FlyingSB.exe 反推, 不要手改).
对应 exe 反推事实:
  ATK_A `0x00670cf0` — atlas_slot=0 (cson1_g0), 4 帧/dir, 1 impact, 玩家槽 0-2 用
  ATK_B `0x0067122c` — atlas_slot=1 (cson1_g1), 6 帧/dir, 1 impact, 玩家槽 3-7 用
  ATK_C `0x0067206c` — atlas_slot=5 (cmiro_g0), 6 帧/dir, 1 impact, 玩家槽 8-15 用
                       含 op `('jump', -1001)`, 跟 -100 IMPACT 配对出现 (作用未解, 暂忽略)

注意: seq 里的 atlas_slot 是 *per-unit 局部索引*, 不是全局 atlas_idx.
DOIT_melee 解释器内部用 unit 自己的 atlas 表查实际 fm atlas. 所以多个角色
共享同一段 seq, 但显示各自的 atlas — 我们的 `attack_fm_atlas(name)` 设计
碰巧符合此语义, render 端 `(idx//n)*cols + idx%n` 翻译处理 cols 不一致.

ATK_B_MULTI 是我们的合成版 (双 IMPACT, 原版玩家普攻没有), 留给敌人/怪物用,
等敌人 seq 全部接上后再清掉.
"""
from __future__ import annotations

from core.raw_attack_seqs import ATK_A, ATK_B, ATK_C

ATTACK_TICK_MS = 40   # 与 REACTION_TICK_MS 一致


# ATK_B_MULTI: 我们派生的二段攻击 (exe 玩家普攻没有, 来自敌方 seq 启发).
# 在原 ('fm', 1, 4, 3) 之后插入第二个 ('impact',). 视觉: 冲入 → 命中1 → 收招前一刻 → 命中2 → 收招.
# 紫河 / 乌鸦怪 暂用此, 等敌方真实 seq 接上后改为对应 ENEMY_TBL_*.
def _make_atk_b_multi():
    out = []
    for dir_seq in ATK_B:
        new = []
        for step in dir_seq:
            new.append(step)
            if step[0] == 'fm' and step[2] in (4, 10, 16, 22):  # fm4 in 4 directions
                new.append(('impact',))
        out.append(new)
    return out


ATK_B_MULTI: list[list[tuple]] = _make_atk_b_multi()


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
    table = {
        "A":       ATK_A,
        "B":       ATK_B,
        "C":       ATK_C,
        "B_MULTI": ATK_B_MULTI,
    }.get(style, ATK_B)
    return table[facing_to_atk_index(facing)]


def frames_per_dir(char_name: str) -> int:
    """fm atlas 每方向用前 N 列 (ATK_A=4, 其它都是 6)."""
    from core.character_sprites import attack_style
    return 4 if attack_style(char_name) == "A" else 6
