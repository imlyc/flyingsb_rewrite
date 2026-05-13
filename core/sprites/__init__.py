"""Sprite atlas 加载与切帧.

原版 sprite 命名约定:
  ps_*  来自 ase_ps.dll, 黑底色键 (0,0,0) 透明
  fm_*  来自 ase_fm.dll, 绿底色键 (0,255,0) 透明 — 多为特效/重影
  其它  无色键 (UI / 不透明 tileset)

角色 atlas 主流尺寸 384×384, 切 4 行 × 6 列 = 24 帧, 单帧 64×96.
朝向行映射 DEFAULT_DIRECTION_ROWS (UP=0, DOWN=1, LEFT=2, RIGHT=3).

子模块:
  base.py           — 路径常量 / Direction / SpriteSheet / 阴影 / load_image
  atlas_classes.py  — CharacterSprite / IdleSprite / WeakenedSprite + 常量
  loaders.py        — get_* 入口 + 缓存 + SBTLFONT 字体
"""
