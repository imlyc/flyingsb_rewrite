"""五行山剧情角色作为"按剧情 flag 显隐"的地图 NPC。

**原版事实 (用户校正)**: 云妮 / 仙杜莉 这两个精灵**只在过场剧情动画与对白里出现**,
没有独立的 NPC 模型, 因此**不作为地图 NPC 摆放** —— 她们由 c3_sprites 节点的过场动画 +
对白演出。这里只摆放有独立模型的常驻角色 (被压的孙悟空 / 蒙面人)。

与 `assets/map_npcs.json` (由 tools/extract_map_npcs 生成) 分开存放,
避免重新提取时覆盖这些手工编排的剧情角色。

每个事件 NPC 字段:
  name      角色名 (用于取角色精灵; 无精灵则画占位小人)
  x, y      地图坐标 (需可通行且不与传送门重叠)
  requires  出现的必要 flag (None 表示总是出现)
  hide_when 满足该 flag 时消失 (用于"被压悟空"→"自由悟空"的切换)
  line      撞上去说的单条对白
"""
from __future__ import annotations

from typing import Iterable

EVENT_NPCS: dict[str, list[dict]] = {
    "TOH0_00P": [
        dict(name="蒙面人", x=14, y=5, requires="MASKED_DONE",
             line="（蒙面人静立一旁，斗篷在风中轻扬，目光警惕地扫视四周。）"),
        dict(name="孙悟空", x=20, y=10, requires="MASKED_DONE", hide_when="WUKONG_JOINED",
             line="（孙悟空被压在青石之下：「可恶！是哪个混蛋把俺老孙压在这儿的！快把俺放出来！」）"),
        # 注意: 云妮/仙杜莉 无独立 NPC 模型, 属过场动画角色, 不在此摆放
        # (见模块 docstring; 由 c3_sprites 的过场动画 + 对白演出)
    ],
}


def events_for(base: str, flags: Iterable[str]) -> list[dict]:
    """返回该地图当前应显示的事件 NPC (按 requires / hide_when 过滤)."""
    out = []
    flagset = set(flags)
    for e in EVENT_NPCS.get(base, []):
        if e.get("requires") and e["requires"] not in flagset:
            continue
        if e.get("hide_when") and e["hide_when"] in flagset:
            continue
        out.append(dict(e))
    return out
