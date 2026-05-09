"""10 个可玩角色 → ase_ps atlas 资源名映射 + 16 char_id 战斗模板表.

资源命名规律 (从原版 ps_*.pcx 反推):
  有形态的角色:  ps_<ROOT><F><AA>   F=形态 id,  AA=atlas 序号
  无形态的角色:  ps_<ROOT><AA>      AA=atlas 序号

例:
  ps_CSON000 = 孙悟空 形态0 atlas0 (无头盔, 剧情早期)
  ps_CSON100 = 孙悟空 形态1 atlas0 (戴头盔拳头, 默认战斗态)
  ps_CSON200 = 孙悟空 形态2 atlas0 (戴头盔双节棒)
  ps_CMIRO00 = 美娜 atlas0 (无形态变化)

每形态通常 5~7 个 atlas (atlas0 是 6×4 走路 atlas, 64×96 单帧).

== 16 char_id 战斗模板 (从 FlyingSB.exe 反推) ==
exe 玩家攻击模板表 PTR_FUN_0068aba4 有 16 槽, BTLdoPlayer 用 char_id 索引.
10 个角色 + 6 个形态变体 = 16 个 char_id, 见 CHARACTER_FORMS 定义.
对应 fm 资源 + ATK_A/B/C 风格也固化在 char data record (0x005b01a9, 416B/记录).
"""
from __future__ import annotations

from dataclasses import dataclass


# ---------- 基础角色 sprite 信息 ----------
@dataclass(frozen=True)
class SpriteInfo:
    root: str
    forms: tuple[int, ...] = ()        # 空 = 无形态变化, 后缀只 2 位
    default_form: int | None = None    # 多数剧情时段使用的常态


CHARACTER_SPRITES: dict[str, SpriteInfo] = {
    "孙悟空":   SpriteInfo("CSON",  forms=(0, 1, 2),     default_form=1),  # 1=戴头盔拳头, 2=戴头盔双节棒
    "美娜":     SpriteInfo("CMIRO"),
    "三藏法师": SpriteInfo("CSAM"),
    "猪八戒":   SpriteInfo("CJUPA"),
    "沙悟净":   SpriteInfo("CSAO"),
    "蒙面人":   SpriteInfo("CDIT",  forms=(0, 1),        default_form=1),  # 1=斗篷态(战斗常态), 0=真容(剧情)
    "乐神杰特": SpriteInfo("CSONA"),
    "破无":     SpriteInfo("CPAO"),
    "捕山":     SpriteInfo("CPUSA"),
    "紫河":     SpriteInfo("CJAH",  forms=(0, 1, 2, 3),  default_form=0),  # 0=人, 1=半人半兽, 2=兽, 3=隐藏第四态
}


def sprite_resource(name: str, *, form: int | None = None, atlas: int = 0) -> str:
    """返回完整资源名 (不含扩展名). 喂给 core.sprites.get_character_sprite()."""
    info = CHARACTER_SPRITES[name]
    if not info.forms:
        return f"ps_{info.root}{atlas:02d}"
    if form is None:
        form = info.default_form if info.default_form is not None else info.forms[0]
    return f"ps_{info.root}{form}{atlas:02d}"


# ---------- 16 char_id 战斗模板 (exe 反推) ----------
@dataclass(frozen=True)
class FormInfo:
    """exe 玩家攻击模板表 (PTR_FUN_0068aba4) 的一槽."""
    char_id: int | None          # 0-15, BTLdoPlayer param_2 索引; None = 敌方/不在玩家表
    name: str                    # 我们用的中文角色名 (= CHARACTER_SPRITES key)
    form: int | None             # 形态序号 (None = 无形态变化的角色)
    ps_prefix: str               # ps atlas 名前缀, e.g. "CSON1" → ps_CSON100/101/...
    fm_atlas: str | None         # 攻击 fm atlas 资源名, None = 该形态无战斗 atlas
    style: str                   # ATK_A / ATK_B / ATK_C (对应 raw_attack_seqs.ATK_*)
    label: str                   # 形态标签 (中文, 给人看)
    note: str = ""
    # 一次攻击播放的 atlas 总帧数覆盖. None=用默认 (cols // n * n).
    # 仅当 atlas cols 不是 n 的整数倍时需要 — 原版可能用更精细的帧分布.
    # 例: 蒙面人 cdit1_g1 cols=16, ATK_C n=6, 默认=12, 实测原版 11.
    attack_total_frames: int | None = None


CHARACTER_FORMS: list[FormInfo] = [
    # --- ATK_A 风格 (atlas 0=cson1_g0 在 seq 里是 atlas_slot=0; 4 帧/dir) ---
    FormInfo(0,  "孙悟空",   0, "CSON0", None,           "A", "无头盔",       "剧情早期, 没 fm atlas, 不进战斗"),
    FormInfo(1,  "孙悟空",   1, "CSON1", "fm_CSON1_G0",  "A", "戴头盔拳头",   "默认战斗态"),
    FormInfo(2,  "孙悟空",   2, "CSON2", "fm_CSON1_G1",  "A", "戴头盔双节棒", "fm 复用 form 1 的 G1 atlas"),

    # --- ATK_B 风格 (atlas_slot=1 局部映射到角色自己的 fm; 6 帧/dir) ---
    FormInfo(3,  "美娜",     None, "CMIRO", "fm_CMIRO_G0", "B", "美娜",       ""),
    FormInfo(4,  "三藏法师", None, "CSAM",  "fm_CSAM_G0",  "B", "三藏法师",   "另有 G1..G6 = 7 个 fm 用于多技能"),
    FormInfo(5,  "猪八戒",   None, "CJUPA", "fm_CJUPA_G0", "B", "猪八戒",     ""),
    FormInfo(6,  "沙悟净",   None, "CSAO",  "fm_CSAO_G0",  "B", "沙悟净",     "wrapper dword5=0x42 (特殊标记)"),
    FormInfo(7,  "蒙面人",   0, "CDIT0", None,            "B", "真容",       "无攻击 atlas (只 E0 特效), 剧情专用"),

    # --- ATK_C 风格 (atlas_slot=5 在 seq 里; 6 帧/dir, 含 jump -1001) ---
    FormInfo(8,  "蒙面人",   1, "CDIT1", "fm_CDIT1_G1",   "C", "斗篷态",     "默认战斗态, 满配 G0..G2/M1/E0",
             attack_total_frames=11),  # cdit1_g1 cols=16, n=6, 视觉实测 11 帧 (原版 remap 公式未追到字节级)
    FormInfo(9,  "乐神杰特", None, "CSONA", "fm_CSONA_G0", "C", "乐神杰特",   ""),
    FormInfo(10, "破无",     None, "CPAO",  "fm_CPAO_G0",  "C", "破无",       "远程弓箭手. atlas 11 cols/dir; total=11 (用满, 末帧独占 1 phase 长停)",
             attack_total_frames=11),
    FormInfo(11, "捕山",     None, "CPUSA", "fm_CPUSA_G0", "C", "捕山",       ""),
    FormInfo(12, "紫河",     0, "CJAH0", "fm_CJAH0_G0",   "C", "人形",       "默认战斗态"),
    FormInfo(13, "紫河",     1, "CJAH1", "fm_CJAH1_G0",   "C", "半人半兽",   ""),
    FormInfo(14, "紫河",     2, "CJAH2", "fm_CJAH2_G0",   "C", "兽形",       "wrapper dword5=0x44"),
    FormInfo(15, "紫河",     3, "CJAH3", "fm_CJAH3_G0",   "C", "第四战斗态", "wrapper dword4=4 (其它紫河都=3). 战斗中由特定伤害类型或道具触发变身, 非剧情专用"),
]


# ---------- 敌方战斗模板 (粗略, 等敌方 seq 全部接通后会重写) ----------
# 这些不在 PTR_FUN_0068aba4 (玩家表), 走 PTR_FUN_00692f6c (敌方表) 的 wrapper.
# char_id=None 表示"非玩家槽". 现阶段先给它们配玩家 ATK_B/B_MULTI 凑合.
ENEMY_FORMS: list[FormInfo] = [
    FormInfo(None, "骷髅",   None, "CSKEL", "fm_CSKEL_G0", "B",       "骷髅",   ""),
    FormInfo(None, "黄色怪", None, "CGHOU", "fm_CGHOU_G0", "B",       "黄色怪", ""),
    FormInfo(None, "乌鸦怪", None, "CCROW", "fm_CCROW_G0", "B_MULTI", "乌鸦怪", "原版 2-impact, 我们用合成 B_MULTI 凑合"),
]


def _form_index(name: str, form: int | None = None) -> FormInfo:
    """按 (角色名, 形态) 找 FormInfo. form=None 时取默认形态. 玩家 + 敌方都查."""
    if form is None and name in CHARACTER_SPRITES:
        info = CHARACTER_SPRITES[name]
        form = info.default_form if info.forms else None
    for fi in CHARACTER_FORMS:
        if fi.name == name and fi.form == form:
            return fi
    for fi in ENEMY_FORMS:
        if fi.name == name:
            return fi
    raise KeyError(f"no FormInfo for {name!r} form={form}")


# ---------- 对外 API (兼容旧调用) ----------
def attack_style(name: str, form: int | None = None) -> str:
    """角色当前形态对应的 ATK_A/B/C 风格."""
    try:
        return _form_index(name, form).style
    except KeyError:
        return "B"


def attack_fm_atlas(name: str, form: int | None = None) -> str | None:
    """该形态战斗时使用的 fm atlas 资源名 (无攻击形态返回 None)."""
    try:
        return _form_index(name, form).fm_atlas
    except KeyError:
        return None


def char_id_for(name: str, form: int | None = None) -> int | None:
    """角色形态在 exe 玩家模板表 PTR_FUN_0068aba4 的槽号 (0-15)."""
    try:
        return _form_index(name, form).char_id
    except KeyError:
        return None


def attack_total_frames(name: str, form: int | None = None) -> int | None:
    """一次普攻播放的 atlas 总帧数覆盖. None = 用默认 cols // n * n."""
    try:
        return _form_index(name, form).attack_total_frames
    except KeyError:
        return None
