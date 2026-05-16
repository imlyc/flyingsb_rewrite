"""命中特效 (blood spawn) — 从 FlyingSB.exe 静态反编译 DOIT_melee 的 -100 IMPACT case.

== 原版 IMPACT 行为 (FUN_004d0e18 case 0xffffff9c) ==
命中分支 (hit_flags[i] & 1 == 0) **同时 spawn 两个独立 effect entity**:

  1st spawn — 略偏 defender 位置 (随机 ±8px jitter + 基线 +25y/+28z offset):
      seq = param_3   ← wrapper 传入的固定/查表参数
      用法分组:
        - char_id 0-7 (ATK_A/B 拳/剑) + 所有敌人 → 固定 seq @0x655b18
              = fm_ET00 frames 14,15, 4 ticks/帧 (= 320ms 紫色 starburst)
        - char_id 8-15 (ATK_C 高级) → (&PTR_DAT_00655ca0)[direction]
              = fm_EF010 frames 24-29 / 27-29, 2 ticks/帧 (= 240ms 长椭圆刺)

  2nd spawn — 严格 defender 中心 (+25y/+28z offset, 无 jitter):
      seq = PTR_DAT_00655c10[direction]
          = fm_EF010 frames 0-17 (小红刺爆), 2 ticks/帧 (= 240ms)
      所有攻击共用.

== `direction` 编码 ==
存在 action_obj +0x110, 由 wrapper 在 attack 启动时设. 0=UP 1=DN 2=LF 3=RT
(= attacker facing). DAT_006418dc 是 4-元素方向轴交换表 [1,0,3,2] —
attacker dir → defender 反应 dir (反向), 仅给 HIT/DODGE reaction 表用,
跟命中特效无关.

DOIT_melee 中真正访问的只有 PTR_DAT_006557f0/00655960[0..3] 4 项. 我们旧
代码理解的"damage_type 表 8-16 项" 是误读, 后续条目从未被访问.

== dt 4-7 / fm_EF011 长枪 / 三爪 ==
不是普攻 hit-effect. 在 .rdata 区里 (0x655d30 / 0x655dc0 周围) 是其他
调用点 (技能 dispatcher 或敌方特殊 attack) 引用的 seq. 后续接技能时再补.
"""

from __future__ import annotations

# 4 方向 dispatch: 0=UP, 1=DN, 2=LF, 3=RT (= action_obj +0x110 的取值)
_DIRS = ("UP", "DN", "LF", "RT")


def facing_to_dir(facing: tuple[int, int]) -> str:
    """attacker.facing → 方向键. (1,0)=RT 等."""
    fx, fy = facing
    if fx == 1:  return "RT"
    if fx == -1: return "LF"
    if fy == 1:  return "DN"
    return "UP"


# ---------------- 2nd spawn — 全部攻击共用 ----------------
# PTR_DAT_00655c10 @ 0x655c10, 4 ptrs 指向 seq @0x655b90 / b0 / d0 / f0
# 每段: 3 个 FM op (atlas=216=ef010, frame, ticks=2) + EXIT (0x0200)
UNIVERSAL_SPARK_BY_DIR: dict[str, list[int]] = {
    "UP": [12, 13, 14],
    "DN": [15, 16, 17],
    "LF": [ 0,  1,  2],
    "RT": [ 3,  4,  5],
}
UNIVERSAL_SPARK_ATLAS = "ef010"
UNIVERSAL_SPARK_FRAME_TICKS = 2          # 80ms / 帧


# ---------------- ATK_C 1st spawn (char_id 8-15) — 长椭圆 ----------------
# PTR_DAT_00655ca0 @ 0x655ca0, 4 ptrs → seq @0x655c20 / 40 / 60 / 80
# 同结构: 3 FM ops + EXIT, atlas=216=ef010, ticks=2
ATK_C_OVAL_BY_DIR: dict[str, list[int]] = {
    "UP": [27, 28, 29],
    "DN": [24, 25, 26],
    "LF": [27, 28, 29],     # LF 复用 UP frames (exe 数据如此, 不是我抄错)
    "RT": [24, 25, 26],     # RT 复用 DN frames
}
ATK_C_OVAL_ATLAS = "ef010"
ATK_C_OVAL_FRAME_TICKS = 2


# ---------------- 抓痕 (CCROW 等 custom-wrapper 敌人用) ----------------
# PTR_DAT_00655d30 @ 0x655d30, 4 ptrs → seq @0x655cb0 / d0 / f0, 0x655d10
# 27 个 inner fn 引用此表 (含 enemy slot 45 简单 wrapper + 多个 custom enemy wrapper +
# 蒙面人技能 dispatcher). 视觉实测: 乌鸦怪命中用此特效.
CLAW_BY_DIR: dict[str, list[int]] = {
    "UP": [43, 44, 42],
    "DN": [40, 41, 39],
    "LF": [43, 44, 42],     # LF 复用 UP (跟椭圆表同模式)
    "RT": [40, 41, 39],
}
CLAW_ATLAS = "ef010"
CLAW_FRAME_TICKS = 2


# ---------------- ATK_A/B + 敌人 1st spawn (char_id 0-7 / 敌方) ----------------
# DAT_00655b18 — 单段 seq (无方向变化):
#   FM(atlas=215=et00, frame=14, ticks=4), FM(et00, 15, 4), EXIT
# 紫色 starburst, 4 ticks/帧 = 160ms/帧 × 2 帧 = 320ms 总
UNIVERSAL_STARBURST_FRAMES: list[int] = [14, 15]
UNIVERSAL_STARBURST_ATLAS = "et00"
UNIVERSAL_STARBURST_FRAME_TICKS = 4


# ---------- IMPACT 时序常量 ----------
HIT_EFFECT_TICK_MS = 40                  # 跟 attack_seq 同时基

# 1st spawn 位置抖动 (= 原版 FUN_005336c7() & 15 - 8 → ±8px)
HIT_EFFECT_JITTER_PX = 8
# 1st + 2nd spawn 基线 y 偏移 (= 原版 +0x1900000 在 16.16 = +25px); z 偏移 +28 在 2D 不用
HIT_EFFECT_Y_BASELINE_PX = 25


# ---------- atlas → hit-fx 映射 (= 攻击 action 决定 effect, 不是角色) ----------
# 完整 dump 自 FlyingSB.exe: 反编译所有 DOIT_melee callers + .rdata 扫 0x655c?? table 引用,
# 跟每个 caller fn 的 ATTACK seq table 第一个 FM op 的 atlas_slot 配对. atlas idx → fm 名
# 在 raw_attack_seqs.ATLAS_RESOURCE.
#
# 关键观察 (印证用户假设): **一个敌人若有 G0/G1/G2 多 atlas (= 多种攻击 action), 不同 action
# 可以用不同 hit-fx**. 例: 乌鸦 G0 单啄 → OVAL, G1 双啄 → CLAW; 黄色怪 G0/G2 → STARBURST,
# G1 → CLAW.
ATLAS_HIT_FX: dict[str, str] = {
    # ---- OVAL (table 0x655ca0) ----
    "chec_g0":  "OVAL",   # slot 4 简单 wrapper
    "csadi_g0": "OVAL",   # slot 18
    "cskel_g0": "OVAL",   # 骷髅 (用户实测)
    "cskel_g1": "OVAL",   # 骷髅 alt
    "cbri0_g0": "OVAL",
    "cbri0_g1": "OVAL",
    "cbri2_g0": "OVAL",
    "cthi_g1":  "OVAL",
    "ccrow_g0": "OVAL",   # 乌鸦 G0 单啄 (跟 G1 不同!)

    # ---- CLAW (table 0x655d30) ----
    "csung_g1": "CLAW",   # slot 45 简单 wrapper
    "cdrf_g0":  "CLAW",
    "cdrf_g1":  "CLAW",
    "cearw_g1": "CLAW",
    "cearw_g2": "CLAW",
    "cghou_g1": "CLAW",   # 黄色怪 G1 (其他形态走 STARBURST)
    "czom_g0":  "CLAW",
    "chhou_g0": "CLAW",
    "cmdog_g1": "CLAW",
    "cmdog_g2": "CLAW",
    "cpri0_g1": "CLAW",
    "cpri1_g0": "CLAW",
    "cbl_g0":   "CLAW",
    "cyeti_g0": "CLAW",
    "cyeti_g1": "CLAW",
    "ccrow_g1": "CLAW",   # 乌鸦 G1 双啄 (用户实测) — 我们 rewrite 默认就是这个

    # ---- LANCE (table 0x655dc0, fm_EF011) — 暂未实现 LANCE 风格 ----
    # "cthi_g0":  "LANCE",
    # "cbl_g1":   "LANCE",

    # ---- STARBURST (默认; 不必显式列, 但显式覆盖更清楚) ----
    # cwu/csama/cnine/czig/ccomb/cghou_g0/cghou_g2/csdog/cbri1/cmus*/cpri0_g0 等等
}


# atlas_key (= resource 名, 不含 fm_ 前缀, 小写) → 全局 atlas_idx (= FM op mode 0 的 slot 值).
# 用在 build_hit_effect_bytecode: bytecode 里 FM op slot 是 atlas idx, render 端再 lookup
# 回 atlas_key (atlas_resource). 跟原版语义一致.
ATLAS_KEY_TO_IDX: dict[str, int] = {
    "et00":  215,
    "ef010": 216,
    "ef011": 217,
}


class HitEffectSpec:
    """1 个待 spawn 的 effect: atlas + frames + 每帧 ticks + 是否抖动."""
    __slots__ = ("atlas_key", "frames", "frame_ticks", "jittered")
    def __init__(self, atlas_key: str, frames: list[int], frame_ticks: int, jittered: bool):
        self.atlas_key = atlas_key
        self.frames = frames
        self.frame_ticks = frame_ticks
        self.jittered = jittered

    def to_bytecode(self) -> bytes:
        """组 anim_engine 字节码: 一串 FM op + EXIT. 模拟原版 blood_spawn 挂的 seq."""
        from core.anim_engine.bytecode import tuple_to_bytecode
        slot = ATLAS_KEY_TO_IDX[self.atlas_key]
        steps: list = [('fm', slot, fi, self.frame_ticks) for fi in self.frames]
        steps.append(('exit',))
        return tuple_to_bytecode(steps)


_STYLE_PRESETS: dict[str, tuple[str, dict[str, list[int]], int]] = {
    "STARBURST": (UNIVERSAL_STARBURST_ATLAS,
                  {d: list(UNIVERSAL_STARBURST_FRAMES) for d in _DIRS},
                  UNIVERSAL_STARBURST_FRAME_TICKS),
    "OVAL":      (ATK_C_OVAL_ATLAS, ATK_C_OVAL_BY_DIR, ATK_C_OVAL_FRAME_TICKS),
    "CLAW":      (CLAW_ATLAS, CLAW_BY_DIR, CLAW_FRAME_TICKS),
}


def _resolve_first_spawn_style(attacker_name: str | None, attacker_form: int | None) -> str:
    """决定 1st spawn 风格. 优先按 attack atlas (= attack action) 查 ATLAS_HIT_FX (exe 数据);
    若该 atlas 不在表里 (= STARBURST 默认), 回落到 attack_style (玩家 C 也用 OVAL).
    """
    from core.character_sprites import attack_fm_atlas, attack_style
    if attacker_name:
        fm = attack_fm_atlas(attacker_name, attacker_form)
        if fm:
            atlas_key = fm.lower().removeprefix("fm_")
            if atlas_key in ATLAS_HIT_FX:
                return ATLAS_HIT_FX[atlas_key]
        # 玩家 ATK_C wrapper 通过 (&PTR_DAT_00655ca0)[dir] 间接索引, 等同 OVAL
        if attack_style(attacker_name, attacker_form) == "C":
            return "OVAL"
    return "STARBURST"


def pick_hit_effects(attacker_name: str | None,
                     attacker_form: int | None,
                     attacker_facing: tuple[int, int]) -> list[HitEffectSpec]:
    """主入口. 返回 IMPACT 时该 spawn 的 effect 列表 (顺序 = 渲染顺序, 后画的在上).

    分发逻辑:
      1st spawn — 由 attacker 的 attack atlas 决定 (= 攻击 action 级别):
        ATLAS_HIT_FX 表里有匹配: 取其风格 (OVAL / CLAW)
        否则玩家 ATK_C: OVAL
        否则: STARBURST (紫爆)
      2nd spawn — 全部走 UNIVERSAL_SPARK 小红刺爆 (defender 中心, 无 jitter)
    """
    direction = facing_to_dir(attacker_facing)

    style = _resolve_first_spawn_style(attacker_name, attacker_form)
    atlas, by_dir, ticks = _STYLE_PRESETS[style]

    return [
        HitEffectSpec(atlas, list(by_dir[direction]), ticks, jittered=True),
        HitEffectSpec(UNIVERSAL_SPARK_ATLAS, list(UNIVERSAL_SPARK_BY_DIR[direction]),
                      UNIVERSAL_SPARK_FRAME_TICKS, jittered=False),
    ]
