"""10 个可玩角色 → ase_ps atlas 资源名映射.

资源命名规律 (从原版 ps_*.pcx 反推):
  有形态的角色:  ps_<ROOT><F><AA>   F=形态 id,  AA=atlas 序号
  无形态的角色:  ps_<ROOT><AA>      AA=atlas 序号

例:
  ps_CSON000 = 孙悟空 形态0 atlas0 (真实样貌)
  ps_CSON100 = 孙悟空 形态1 atlas0 (白头盔常态)
  ps_CMIRO00 = 美娜 atlas0 (无形态变化)

每形态通常 5~7 个 atlas (atlas0 是 6×4 走路 atlas, 64×96 单帧).
"""
from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(frozen=True)
class SpriteInfo:
    root: str
    forms: tuple[int, ...] = ()        # 空 = 无形态变化, 后缀只 2 位
    default_form: int | None = None    # 多数剧情时段使用的常态


CHARACTER_SPRITES: dict[str, SpriteInfo] = {
    "孙悟空":   SpriteInfo("CSON",  forms=(0, 1, 2),     default_form=1),  # 1=白头盔
    "美娜":     SpriteInfo("CMIRO"),
    "三藏法师": SpriteInfo("CSAM"),                                        # 另有 CSAMA 变身待考
    "猪八戒":   SpriteInfo("CJUPA"),
    "沙悟净":   SpriteInfo("CSAO"),
    "蒙面人":   SpriteInfo("CDIT",  forms=(0, 1),        default_form=1),  # 1=斗篷
    "乐神杰特": SpriteInfo("CSONA"),
    "破无":     SpriteInfo("CPAO"),
    "捕山":     SpriteInfo("CPUSA"),
    "紫河":     SpriteInfo("CJAH",  forms=(0, 1, 2, 3),  default_form=0),  # 4 形态待标注
}


def sprite_resource(name: str, *, form: int | None = None, atlas: int = 0) -> str:
    """返回完整资源名 (不含扩展名). 喂给 core.sprites.get_character_sprite()."""
    info = CHARACTER_SPRITES[name]
    if not info.forms:
        return f"ps_{info.root}{atlas:02d}"
    if form is None:
        form = info.default_form if info.default_form is not None else info.forms[0]
    return f"ps_{info.root}{form}{atlas:02d}"
