"""单体飞行道具类 custom 敌招 (各自完整 dispatcher, 结构相同), reverse_engineering/enemy_spells_decomp.txt, 2026-10-26.

招式 / dispatcher / 弹生成函数 / 弹 think:
  138 投出手銬   FUN_004e013c / FUN_004e0011 / FUN_004dffb9     203 放箭     FUN_004e30e4 / FUN_004e2fb9 / FUN_004e2f61
  142 飛針       FUN_004e0d02 / FUN_004e0be1 / FUN_004e0b93     204 雙放箭   FUN_004e34e0 / (同 203 的弹)
  153 射箭       FUN_004e1454 / FUN_004e1333 / FUN_004e12e5     207 丟銀斧頭 FUN_004e425f / FUN_004e413e / FUN_004e40f0
  159 發射栗子   FUN_004e2096 / FUN_004e1f59 / FUN_004e1f0b     208 丟金斧頭 FUN_004e4841 / FUN_004e46b3 / FUN_004e4665
  188 番茄醬放射 FUN_004e2973 / FUN_004e2831 / FUN_004e27e3     210 射飛刀   FUN_004e4dfe / FUN_004e4cc7 / FUN_004e4c6f
dispatcher (共同骨架):
  case 0   **无渐暗**: 施法者清 0x10000, 挂施法 seq 表[施法者朝向] (各招自己的表, 不在 SEQ_TABLES) → 10.
  -100     对 **第一个目标** (DAT_00869c48) 发一个弹 (+0x78 ++) → 0x14. 153/204 的施法 seq 有两个 -100 = 两发.
  弹       生在施法者 (x, y [+1], z + Z), 目标 = 目标 (x, y [+1], z + Z); mode 0x31 FUN_004cdbc2 匀速:
           朝向上/下 只给 vy = ∓V上下, 左/右 只给 vx = ∓V左右 (另一轴速度 0 → 首步即钳到目标), 两轴都到 → (到达音)
           以弹自身为源发 -200, 自毁. 弹 seq = 表[施法者朝向] 或静态帧 (159 栗子 图 0x149 帧 0 / 188 番茄醬 图 0xee 帧=朝向).
  -200     第一个目标 FUN_004c4f20 + 受击 seq 6557f0[目标朝向] + 两个特效 FUN_004d0c90 (目标 x, y+400, z+448, 各轴
           + (rand&15)-8 抖动, rand 顺序 z→y→x): 655c10[施法者朝向] ef010 方向刺爆 + 655b18 et00 星爆 (188 为 666d30 番茄汁);
           飘字 FUN_004d05d8 (153/204: 第 2 发才飘字, +0x7c 计数到 2 才收尾) + 命中音.
  0x14     弹/飘字计数归零 → 自毁 (**不走渐亮**).
各招参数 (速度 px/t 上下/左右, Z px, 音效 生成/到达/-200) 见 Shot 子类.
结算时机 = exe -200 (受击+特效+飘字同 tick).
实录校准 (wine/captures/en138_t96 / en142_t99 / en153_t109 / en159_t115 / en188_t142 / en203_t159 / en204_t160 / en207_t163 / en208_t164 / en210_t166, 及 139 en139_t97):
  弹出生当 tick 不 think (首帧在出生点), 弹寿命/-200/特效/飘字出生 tick 均吻合; 收尾 = 末位飘字 -20 后第 2 tick 施法者回待机, 吻合
  (原版多为 MISS 4 字形, 与我们位数不同 → 收尾差 2 t/位). 153 第 2 箭的目标点含目标受击后退 (b_common.cur_pos), 改后第 2 箭寿命 13 t 吻合.
"""
from __future__ import annotations

from core.enemy_spells.b_common import cur_pos
from core.enemy_spells.base import Spell, fx, FP, _pos, _rand, _sfx, _cdbc2, _motion, _dir, _unit_z

# ---------------- 公共特效 ----------------
SPARK = [  # @0x655c10
    [('fm', 216, 12, 2), ('fm', 216, 13, 2), ('fm', 216, 14, 2), ('exit',)],
    [('fm', 216, 15, 2), ('fm', 216, 16, 2), ('fm', 216, 17, 2), ('exit',)],
    [('fm', 216, 0, 2), ('fm', 216, 1, 2), ('fm', 216, 2, 2), ('exit',)],
    [('fm', 216, 3, 2), ('fm', 216, 4, 2), ('fm', 216, 5, 2), ('exit',)],
]
STAR = [('fm', 215, 14, 4), ('fm', 215, 15, 4), ('exit',)]  # @0x655b18
OPP = (1, 0, 3, 2)              # 表 6418dc: 反方向


def impact_fx(battle, victim, d: int, second=STAR, jitter: bool = True) -> None:
    """-200/-250 的两个 FUN_004d0c90 特效: 655c10[d] 方向刺爆 + second (默认 655b18 星爆; None = 只刺爆), 在目标 (x, y+400, z+448).
    jitter: 各轴 (rand&15)-8 px (rand 顺序 z→y→x). 位置取受击 seq 首个后退位移之后 (core.pao_skills.hit_pos)."""
    from core.pao_skills import hit_pos
    x, y = hit_pos(victim)
    for seq in (SPARK[d], second):
        if seq is None:
            continue
        jx = jy = jz = 0
        if jitter:
            jz = ((_rand(battle) & 15) - 8) * FP
            jy = ((_rand(battle) & 15) - 8) * FP
            jx = ((_rand(battle) & 15) - 8) * FP
        fx(battle, None, x + jx, y + 400 * FP + jy, 448 * FP + jz, seq)


def reset_hit(victim, battle=None) -> None:
    """FUN_004c4f20 + 受击 seq 6557f0[目标朝向] (不转向)."""
    from core.battle import combat
    if victim.alive:
        combat.set_reaction(victim, "hit", None)
        if battle is not None:
            victim._b_hit_tick = battle.engine._tick_id     # 受击 seq 起点 (b_common.cur_pos 用)


def n_casts(seq) -> int:
    return sum(1 for t in seq if t[0] == 'jump' and t[1] == -100)


# ---------------- 弹 ----------------
def _shot_think(e, eng) -> None:
    """FUN_004dffb9 类: FUN_004cdbc2, x/y 两轴到 → (到达音) -200 自毁."""
    ud = e.user_data
    if 'shot' not in ud:
        return
    _cdbc2(e)
    if ud['m'] & 0x30:
        return
    sp: Shot = ud['spell']
    if sp.SFX_ARRIVE is not None:
        _sfx(sp.battle, sp.SFX_ARRIVE)
    sp.on_arrive(ud['victim'])
    eng.destroy(e)


class Shot(Spell):
    """单体弹 dispatcher. 子类填参数."""
    DIM = False
    FADE_IN = False
    CAST: list = []                 # 施法 seq 表 [上, 下, 左, 右]
    PROJ: list | None = None        # 弹 seq 表; None → STATIC
    STATIC: tuple | None = None     # (图集, 帧 | None=朝向)
    SPEED = (24, 32)                # (上下, 左右) px/t
    Z = 32                          # 弹 z 偏移 px
    Y = 0                           # 弹 y 偏移 px (生成/目标同加)
    SFX_SPAWN: int | None = None    # 弹生成时 (生成函数里)
    SFX_ARRIVE: int | None = None   # 弹到达 (弹 think 里)
    SFX_HIT: int | None = None      # dispatcher -200
    SECOND = STAR                   # -200 第二个特效
    HITS = 1                        # 第几个 -200 才飘字 (+0x7c)

    def __init__(self, battle, caster, mid):
        super().__init__(battle, caster, mid)
        self.total = n_casts(self.CAST[_dir(caster)])
        self.shots = 0
        self.arrived = 0

    def cast_seq(self, d: int):
        return self.CAST[d]

    def on_cast_impact(self) -> None:
        self.shots += 1
        if not self.targets:
            self.arrived += 1
            self._check_end()
            return
        self.spawn(self.targets[0])

    def spawn(self, v) -> None:
        b, c = self.battle, self.caster
        d = _dir(c)
        x, y = _pos(c)
        tx, ty = cur_pos(b, v)          # exe 目标 +8/+0xc 含受击 seq 后退 (实录 en153_t109: 第 2 箭晚 1 t 到)
        vud, vlr = self.SPEED
        vx, vy = ((0, -vud), (0, vud), (-vlr, 0), (vlr, 0))[d]
        yo, zo = self.Y * FP, self.Z * FP
        mot = _motion(m=0x31, vx=vx * FP, vy=vy * FP, tx=tx, ty=ty + yo, tz=_unit_z(v) + zo)
        if self.PROJ is not None:
            fx(b, _shot_think, x, y + yo, _unit_z(c) + zo, self.PROJ[d], shot=True, spell=self, victim=v, **mot)
        else:
            atlas, frame = self.STATIC
            fx(b, _shot_think, x, y + yo, _unit_z(c) + zo, None, atlas=atlas, frame=d if frame is None else frame,
               shot=True, spell=self, victim=v, **mot)
        self.live += 1
        if self.SFX_SPAWN is not None:
            _sfx(b, self.SFX_SPAWN)

    def on_arrive(self, v) -> None:
        """-200."""
        self.live -= 1
        self.arrived += 1
        reset_hit(v, self.battle)
        impact_fx(self.battle, v, _dir(self.caster), self.SECOND)
        if self.arrived == self.HITS:
            self.settle(v)
        if self.SFX_HIT is not None:
            _sfx(self.battle, self.SFX_HIT)
        self._check_end()

    def _check_end(self) -> None:
        if self.arrived >= self.total and not self._finishing:
            self.finish()


CAST_138 = [  # @0x660fb4
    [('fm', 124, 0, 3), ('fm', 124, 1, 3), ('move', 0, -6, 0, 0), ('fm', 124, 2, 3), ('move', 0, -4, 0, 0), ('jump', -100), ('fm', 124, 3, 3), ('move', 0, -2, 0, 0), ('fm', 124, 4, 12), ('move', 0, 12, 0, 0), ('fm', 124, 0, 0), ('exit',)],
    [('fm', 124, 5, 3), ('fm', 124, 6, 3), ('move', 0, 6, 0, 0), ('fm', 124, 7, 3), ('move', 0, 4, 0, 0), ('jump', -100), ('fm', 124, 8, 3), ('move', 0, 2, 0, 0), ('fm', 124, 9, 12), ('move', 0, -12, 0, 0), ('fm', 124, 5, 0), ('exit',)],
    [('fm', 124, 10, 3), ('fm', 124, 11, 3), ('move', -8, 0, 0, 0), ('fm', 124, 12, 3), ('move', -4, 0, 0, 0), ('jump', -100), ('fm', 124, 13, 3), ('move', -2, 0, 0, 0), ('fm', 124, 14, 12), ('move', 14, 0, 0, 0), ('fm', 124, 10, 0), ('exit',)],
    [('fm', 124, 15, 3), ('fm', 124, 16, 3), ('move', 8, 0, 0, 0), ('fm', 124, 17, 3), ('move', 4, 0, 0, 0), ('jump', -100), ('fm', 124, 18, 3), ('move', 2, 0, 0, 0), ('fm', 124, 19, 12), ('move', -14, 0, 0, 0), ('fm', 124, 15, 0), ('exit',)],
]
PROJ_138 = [  # @0x661074
    [('fm', 324, 4, 1), ('fm', 324, 5, 1), ('fm', 324, 6, 1), ('fm', 324, 7, 1), ('loop',)],
    [('fm', 324, 12, 1), ('fm', 324, 13, 1), ('fm', 324, 14, 1), ('fm', 324, 15, 1), ('loop',)],
    [('fm', 324, 0, 1), ('fm', 324, 3, 1), ('fm', 324, 2, 1), ('fm', 324, 1, 1), ('loop',)],
    [('fm', 324, 8, 1), ('fm', 324, 9, 1), ('fm', 324, 10, 1), ('fm', 324, 11, 1), ('loop',)],
]
CAST_142 = [  # @0x6614c4
    [('fm', 126, 0, 3), ('fm', 126, 1, 12), ('move', 0, -6, 0, 0), ('sound', 209, 1041), ('fm', 126, 2, 3), ('move', 0, -4, 0, 0), ('jump', -100), ('fm_mode1', 926, 4, 3), ('move', 0, -2, 0, 8), ('move', 0, 12, 0, 0), ('fm', 126, 0, 0), ('exit',)],
    [('fm', 126, 4, 3), ('fm', 126, 5, 12), ('move', 0, 6, 0, 0), ('sound', 209, 1041), ('fm', 126, 6, 3), ('move', 0, 4, 0, 0), ('jump', -100), ('fm_mode1', 926, 5, 3), ('move', 0, 2, 0, 8), ('move', 0, -12, 0, 0), ('fm', 126, 4, 0), ('exit',)],
    [('fm', 126, 8, 3), ('fm', 126, 9, 12), ('move', -8, 0, 0, 0), ('sound', 209, 1041), ('fm', 126, 10, 3), ('move', -4, 0, 0, 0), ('jump', -100), ('fm_mode1', 926, 6, 3), ('move', -2, 0, 0, 8), ('move', 14, 0, 0, 0), ('fm', 126, 8, 0), ('exit',)],
    [('fm', 126, 12, 3), ('fm', 126, 13, 12), ('move', 8, 0, 0, 0), ('sound', 209, 1041), ('fm', 126, 14, 3), ('move', 4, 0, 0, 0), ('jump', -100), ('fm_mode1', 926, 7, 3), ('move', 2, 0, 0, 8), ('move', -12, 0, 0, 0), ('fm', 126, 12, 0), ('exit',)],
]
PROJ_142 = [  # @0x661504
    [('fm', 326, 0, 0), ('exit',)],
    [('fm', 326, 1, 0), ('exit',)],
    [('fm', 326, 2, 0), ('exit',)],
    [('fm', 326, 3, 0), ('exit',)],
]
CAST_153 = [  # @0x6627f4
    [('fm', 134, 0, 3), ('fm', 134, 1, 3), ('sound', 200, 1041), ('fm', 134, 2, 3), ('jump', -100), ('fm', 134, 3, 12), ('fm', 134, 4, 3), ('sound', 200, 1041), ('fm', 134, 5, 3), ('jump', -100), ('fm', 134, 6, 12), ('fm', 134, 0, 0), ('exit',)],
    [('fm', 134, 7, 3), ('fm', 134, 8, 3), ('sound', 200, 1041), ('fm', 134, 9, 3), ('jump', -100), ('fm', 134, 10, 12), ('fm', 134, 11, 3), ('sound', 200, 1041), ('fm', 134, 12, 3), ('jump', -100), ('fm', 134, 13, 12), ('fm', 134, 7, 0), ('exit',)],
    [('fm', 134, 14, 3), ('fm', 134, 15, 3), ('sound', 200, 1041), ('fm', 134, 16, 3), ('jump', -100), ('fm', 134, 17, 12), ('fm', 134, 18, 3), ('sound', 200, 1041), ('fm', 134, 19, 3), ('jump', -100), ('fm', 134, 20, 12), ('fm', 134, 14, 0), ('exit',)],
    [('fm', 134, 21, 3), ('fm', 134, 22, 3), ('sound', 200, 1041), ('fm', 134, 23, 3), ('jump', -100), ('fm', 134, 24, 12), ('fm', 134, 25, 3), ('sound', 200, 1041), ('fm', 134, 26, 3), ('jump', -100), ('fm', 134, 27, 12), ('fm', 134, 21, 0), ('exit',)],
]
PROJ_153 = [  # @0x662834
    [('fm', 327, 1, 0), ('exit',)],
    [('fm', 327, 0, 0), ('exit',)],
    [('fm', 327, 3, 0), ('exit',)],
    [('fm', 327, 2, 0), ('exit',)],
]
CAST_159 = [  # @0x6630a0
    [('fm', 138, 0, 3), ('fm', 138, 1, 5), ('fm', 138, 2, 3), ('move', 0, -6, 0, 0), ('sound', 222, 1041), ('fm', 138, 3, 3), ('move', 0, -3, 0, 0), ('jump', -100), ('fm', 138, 4, 3), ('move', 0, -3, 0, 0), ('fm', 138, 5, 12), ('move', 0, 12, 0, 0), ('fm', 138, 0, 0), ('exit',)],
    [('fm', 138, 6, 3), ('fm', 138, 7, 5), ('fm', 138, 8, 3), ('move', 0, 6, 0, 0), ('sound', 222, 1041), ('fm', 138, 9, 3), ('move', 0, 3, 0, 0), ('jump', -100), ('fm', 138, 10, 3), ('move', 0, 3, 0, 0), ('fm', 138, 11, 12), ('move', 0, -12, 0, 0), ('fm', 138, 6, 0), ('exit',)],
    [('fm', 138, 12, 3), ('fm', 138, 13, 5), ('fm', 138, 14, 3), ('move', -8, 0, 0, 0), ('sound', 222, 1041), ('fm', 138, 15, 3), ('move', -4, 0, 0, 0), ('jump', -100), ('fm', 138, 16, 3), ('move', -4, 0, 0, 0), ('fm', 138, 17, 12), ('move', 16, 0, 0, 0), ('fm', 138, 12, 0), ('exit',)],
    [('fm', 138, 18, 3), ('fm', 138, 19, 5), ('fm', 138, 20, 3), ('move', 8, 0, 0, 0), ('sound', 222, 1041), ('fm', 138, 21, 3), ('move', 4, 0, 0, 0), ('jump', -100), ('fm', 138, 22, 3), ('move', 4, 0, 0, 0), ('fm', 138, 23, 12), ('move', -16, 0, 0, 0), ('fm', 138, 18, 0), ('exit',)],
]
CAST_188 = [  # @0x666d20
    [('fm', 158, 0, 5), ('fm', 158, 1, 12), ('move', 0, -6, 0, 0), ('jump', -100), ('fm', 158, 2, 3), ('move', 0, -3, 0, 0), ('fm', 158, 3, 3), ('move', 0, -3, 0, 0), ('fm', 158, 4, 3), ('move', 0, 12, 0, 0), ('fm', 158, 5, 3), ('exit',)],
    [('fm', 158, 6, 5), ('fm', 158, 7, 12), ('move', 0, 6, 0, 0), ('jump', -100), ('fm', 158, 8, 3), ('move', 0, 3, 0, 0), ('fm', 158, 9, 3), ('move', 0, 3, 0, 0), ('fm', 158, 10, 3), ('move', 0, -12, 0, 0), ('fm', 158, 11, 3), ('exit',)],
    [('fm', 158, 12, 5), ('fm', 158, 13, 12), ('move', -8, 0, 0, 0), ('jump', -100), ('fm', 158, 14, 3), ('move', -8, 0, 0, 0), ('fm', 158, 15, 3), ('move', -4, 0, 0, 0), ('fm', 158, 16, 3), ('move', 20, 0, 0, 0), ('fm', 158, 17, 0), ('exit',)],
    [('fm', 158, 18, 5), ('fm', 158, 19, 12), ('move', 8, 0, 0, 0), ('jump', -100), ('fm', 158, 20, 3), ('move', 8, 0, 0, 0), ('fm', 158, 21, 3), ('move', 4, 0, 0, 0), ('fm', 158, 22, 3), ('move', -20, 0, 0, 0), ('fm', 158, 23, 3), ('exit',)],
]
FX_188 = [('fm', 238, 4, 2), ('fm', 238, 5, 2), ('fm', 238, 6, 2), ('fm', 238, 7, 2), ('exit',)]  # @0x666d30
CAST_207 = [  # @0x6694ec
    [('fm', 172, 0, 3), ('fm', 172, 1, 12), ('sound', 243, 1041), ('fm', 172, 2, 3), ('jump', -100), ('fm', 172, 3, 3), ('fm', 172, 4, 12), ('exit',)],
    [('fm', 172, 5, 3), ('fm', 172, 6, 12), ('sound', 243, 1041), ('fm', 172, 7, 3), ('jump', -100), ('fm', 172, 8, 3), ('fm', 172, 9, 12), ('exit',)],
    [('fm', 172, 10, 3), ('fm', 172, 11, 12), ('sound', 243, 1041), ('fm', 172, 12, 3), ('jump', -100), ('fm', 172, 13, 3), ('fm', 172, 14, 12), ('exit',)],
    [('fm', 172, 15, 3), ('fm', 172, 16, 12), ('sound', 243, 1041), ('fm', 172, 17, 3), ('jump', -100), ('fm', 172, 18, 3), ('fm', 172, 19, 12), ('exit',)],
]
PROJ_207 = [  # @0x66957c
    [('fm', 330, 25, 1), ('fm', 330, 24, 1), ('fm', 330, 23, 1), ('fm', 330, 22, 1), ('fm', 330, 21, 1), ('fm', 330, 20, 1), ('exit',)],
    [('fm', 330, 26, 1), ('fm', 330, 27, 1), ('fm', 330, 28, 1), ('fm', 330, 29, 1), ('fm', 330, 30, 1), ('fm', 330, 31, 1), ('exit',)],
    [('fm', 330, 25, 1), ('fm', 330, 24, 1), ('fm', 330, 23, 1), ('fm', 330, 22, 1), ('fm', 330, 21, 1), ('fm', 330, 20, 1), ('exit',)],
    [('fm', 330, 26, 1), ('fm', 330, 27, 1), ('fm', 330, 28, 1), ('fm', 330, 29, 1), ('fm', 330, 30, 1), ('fm', 330, 31, 1), ('exit',)],
]
CAST_208 = [  # @0x66970c
    [('fm', 171, 0, 0), ('move', 0, 4, 0, 0), ('fm', 171, 1, 12), ('move', 0, -4, 0, 0), ('fm', 171, 2, 3), ('move', 0, -4, 0, 0), ('jump', -100), ('fm', 171, 3, 3), ('move', 0, -4, 0, 0), ('fm', 171, 4, 3), ('exit',)],
    [('fm', 171, 5, 0), ('move', 0, -4, 0, 0), ('fm', 171, 6, 12), ('move', 0, 4, 0, 0), ('fm', 171, 7, 3), ('move', 0, 4, 0, 0), ('jump', -100), ('fm', 171, 8, 3), ('move', 0, 4, 0, 0), ('fm', 171, 9, 3), ('exit',)],
    [('fm', 171, 10, 3), ('move', 4, 0, 0, 0), ('fm', 171, 11, 12), ('move', -4, 0, 0, 0), ('fm', 171, 12, 3), ('move', -4, 0, 0, 0), ('jump', -100), ('fm', 171, 13, 3), ('move', -4, 0, 0, 0), ('fm', 171, 14, 3), ('exit',)],
    [('fm', 171, 15, 3), ('move', -4, 0, 0, 0), ('fm', 171, 16, 12), ('move', 4, 0, 0, 0), ('fm', 171, 17, 3), ('move', 4, 0, 0, 0), ('jump', -100), ('fm', 171, 18, 3), ('move', 4, 0, 0, 0), ('fm', 171, 19, 3), ('exit',)],
]
PROJ_208 = [  # @0x6697a0
    [('fm', 331, 11, 2), ('fm', 331, 12, 2), ('fm', 331, 13, 2), ('fm', 331, 14, 2), ('loop',)],
    [('fm', 331, 11, 2), ('fm', 331, 12, 2), ('fm', 331, 13, 2), ('fm', 331, 14, 2), ('loop',)],
    [('fm', 331, 0, 2), ('fm', 331, 1, 2), ('fm', 331, 2, 2), ('fm', 331, 3, 2), ('loop',)],
    [('fm', 331, 6, 2), ('fm', 331, 7, 2), ('fm', 331, 8, 2), ('fm', 331, 9, 2), ('loop',)],
]
CAST_210 = [  # @0x669ab0
    [('fm', 175, 0, 8), ('fm', 175, 1, 12), ('fm', 175, 2, 3), ('jump', -100), ('fm', 175, 3, 3), ('fm', 175, 4, 12), ('exit',)],
    [('fm', 175, 5, 8), ('fm', 175, 6, 12), ('fm', 175, 7, 3), ('jump', -100), ('fm', 175, 8, 3), ('fm', 175, 9, 12), ('exit',)],
    [('fm', 175, 10, 8), ('fm', 175, 11, 12), ('fm', 175, 12, 3), ('jump', -100), ('fm', 175, 13, 3), ('fm', 175, 14, 12), ('exit',)],
    [('fm', 175, 15, 8), ('fm', 175, 16, 12), ('fm', 175, 17, 3), ('jump', -100), ('fm', 175, 18, 3), ('fm', 175, 19, 12), ('exit',)],
]
PROJ_210 = [  # @0x669af0
    [('fm', 330, 15, 0), ('exit',)],
    [('fm', 330, 14, 0), ('exit',)],
    [('fm', 330, 12, 0), ('exit',)],
    [('fm', 330, 13, 0), ('exit',)],
]
CAST_203 = [  # @0x668f0c
    [('fm', 170, 0, 3), ('fm', 170, 1, 5), ('fm', 170, 2, 8), ('fm', 170, 3, 15), ('move', 0, 0, 0, 0), ('jump', -100), ('fm', 170, 4, 3), ('exit',)],
    [('fm', 170, 5, 3), ('fm', 170, 6, 5), ('fm', 170, 7, 8), ('fm', 170, 8, 15), ('move', 0, 0, 0, 0), ('jump', -100), ('fm', 170, 9, 3), ('exit',)],
    [('fm', 170, 10, 3), ('fm', 170, 11, 5), ('fm', 170, 12, 8), ('fm', 170, 13, 15), ('move', 0, 0, 0, 0), ('jump', -100), ('fm', 170, 14, 3), ('exit',)],
    [('fm', 170, 15, 3), ('fm', 170, 16, 5), ('fm', 170, 17, 8), ('fm', 170, 18, 15), ('move', 0, 0, 0, 0), ('jump', -100), ('fm', 170, 19, 3), ('exit',)],
]
ARROW_203 = [  # @0x668f4c
    [('fm', 330, 17, 0), ('exit',)],
    [('fm', 330, 16, 0), ('exit',)],
    [('fm', 330, 19, 0), ('exit',)],
    [('fm', 330, 18, 0), ('exit',)],
]
CAST_204 = [  # @0x66913c
    [('fm', 170, 0, 3), ('fm', 170, 1, 5), ('fm', 170, 2, 8), ('fm', 170, 3, 15), ('move', 0, 0, 0, 0), ('jump', -100), ('fm', 170, 4, 15), ('fm', 170, 1, 5), ('fm', 170, 2, 8), ('fm', 170, 3, 15), ('move', 0, 0, 0, 0), ('jump', -100), ('fm', 170, 4, 15), ('exit',)],
    [('fm', 170, 5, 3), ('fm', 170, 6, 5), ('fm', 170, 7, 8), ('fm', 170, 8, 15), ('move', 0, 0, 0, 0), ('jump', -100), ('fm', 170, 9, 15), ('fm', 170, 6, 5), ('fm', 170, 7, 8), ('fm', 170, 8, 15), ('move', 0, 0, 0, 0), ('jump', -100), ('fm', 170, 9, 15), ('exit',)],
    [('fm', 170, 10, 3), ('fm', 170, 11, 5), ('fm', 170, 12, 8), ('fm', 170, 13, 15), ('move', 0, 0, 0, 0), ('jump', -100), ('fm', 170, 14, 15), ('fm', 170, 11, 5), ('fm', 170, 12, 8), ('fm', 170, 13, 15), ('move', 0, 0, 0, 0), ('jump', -100), ('fm', 170, 14, 15), ('exit',)],
    [('fm', 170, 15, 3), ('fm', 170, 16, 5), ('fm', 170, 17, 8), ('fm', 170, 18, 15), ('move', 0, 0, 0, 0), ('jump', -100), ('fm', 170, 19, 15), ('fm', 170, 16, 5), ('fm', 170, 17, 8), ('fm', 170, 18, 15), ('move', 0, 0, 0, 0), ('jump', -100), ('fm', 170, 19, 15), ('exit',)],
]


class Handcuff(Shot):
    """138 投出手銬: 弹 z+48, 9/12 px/t, 生成音 0xf1, 到达音 0xbd."""
    CAST, PROJ, SPEED, Z, SFX_SPAWN, SFX_ARRIVE = CAST_138, PROJ_138, (9, 12), 48, 0xf1, 0xbd


class Needle(Shot):
    """142 飛針: 12/16 px/t, -200 音 0xbd."""
    CAST, PROJ, SPEED, SFX_HIT = CAST_142, PROJ_142, (12, 16), 0xbd


class TwinArrow(Shot):
    """153 射箭: 施法 seq 两个 -100 (各带 seq 内 200 音) 两箭; 12/16 px/t; -200 音 0xbd, 第 2 箭才飘字."""
    CAST, PROJ, SPEED, SFX_HIT, HITS = CAST_153, PROJ_153, (12, 16), 0xbd, 2


class Chestnut(Shot):
    """159 發射栗子: 静态图 0x149 帧 0, 9/12 px/t, -200 音 0xbd."""
    CAST, STATIC, SPEED, SFX_HIT = CAST_159, (0x149, 0), (9, 12), 0xbd


class Ketchup(Shot):
    """188 番茄醬放射: 静态图 0xee 帧=朝向, 9/12 px/t; -100 播 0xaf; -200 第二特效 = 666d30 (番茄汁), 音 0xbd."""
    CAST, STATIC, SPEED, SFX_SPAWN, SFX_HIT, SECOND = CAST_188, (0xee, None), (9, 12), 0xaf, 0xbd, FX_188


class Arrow(Shot):
    """203 放箭: 24/32 px/t, 生成音 200, 到达音 0xbf."""
    CAST, PROJ, SFX_SPAWN, SFX_ARRIVE = CAST_203, ARROW_203, 200, 0xbf


class DoubleArrow(Arrow):
    """204 雙放箭: 同 203 的箭, 施法 seq 两个 -100, 第 2 箭才飘字."""
    CAST, HITS = CAST_204, 2


class SilverAxe(Shot):
    """207 丟銀斧頭: 24/32 px/t, -200 音 0xbd."""
    CAST, PROJ, SFX_HIT = CAST_207, PROJ_207, 0xbd


class GoldAxe(Shot):
    """208 丟金斧頭: 弹 y+1 z+0, 6/8 px/t, 生成音 0xe6, -200 音 0xc4."""
    CAST, PROJ, SPEED, Y, Z, SFX_SPAWN, SFX_HIT = CAST_208, PROJ_208, (6, 8), 1, 0, 0xe6, 0xc4


class Knife(Shot):
    """210 射飛刀: 弹 y+1, 24/32 px/t, 生成音 0xd2, 到达音 0xbd."""
    CAST, PROJ, Y, SFX_SPAWN, SFX_ARRIVE = CAST_210, PROJ_210, 1, 0xd2, 0xbd


MOVES = {138: Handcuff, 142: Needle, 153: TwinArrow, 159: Chestnut, 188: Ketchup, 203: Arrow, 204: DoubleArrow,
         207: SilverAxe, 208: GoldAxe, 210: Knife}
