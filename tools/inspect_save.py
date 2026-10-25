"""存档检查 / 对比工具: 打印布局摘要与事件变量, 或对比两个存档的事件变量.

用法:
  python -m tools.inspect_save <save.dat>            # 打印布局摘要 + 非零事件变量
  python -m tools.inspect_save <saveA> <saveB>       # 对比两个存档的事件变量差异

布局见 core.save_manager (= exe 存档函数 FUN_004ca35d 的写入顺序): 头 0x30 / 角色表 0x30 / 地图号 0xBF0 / 金钱 0xBF4 /
队伍 0xBF8 / 道具数量 0xCF8 / 队长坐标 0x1298 / 遇敌组 0x12A8 / 加密的事件状态块 0x1BFC (事件变量 VA 0x80F950 起).
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from core.save_manager import item_counts, load_save, party_slots  # noqa: E402


def describe(path: Path) -> None:
    save = load_save(path)
    nz = save.nonzero_event_vars()
    print(f"=== {path.name} ===")
    print(f"  地点: {save.location}   金钱: {save.money}   队长 Lv{save.leader_level}   游戏时间 {save.play_time}")
    print(f"  队伍槽位: {party_slots(save)}")
    print(f"  道具: {sorted(item_counts(save.raw).items())[:40]}")
    print(f"  事件变量: {len(save.event_vars)} 个, 非零 {len(nz)}")
    print("  " + "  ".join(f"{va:#x}={v}" for va, v in list(nz.items())[:60]) + (" ..." if len(nz) > 60 else ""))


def diff(pa: Path, pb: Path) -> None:
    a, b = load_save(pa), load_save(pb)
    va, vb = a.nonzero_event_vars(), b.nonzero_event_vars()
    print(f"=== diff {pa.name} -> {pb.name} ===")
    keys = sorted(set(va) | set(vb))
    changed = [(k, va.get(k, 0), vb.get(k, 0)) for k in keys if va.get(k, 0) != vb.get(k, 0)]
    print(f"  事件变量变化 ({len(changed)}):")
    for k, x, y in changed[:120]:
        print(f"    {k:#x}: {x} -> {y}")


def main() -> int:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    args = sys.argv[1:]
    if not args:
        d = Path(os.environ.get("FLYINGSB_ORIGIN", ROOT.parent / "origin" / "flyingsb")) / "Data"
        print(f"用法: python -m tools.inspect_save <save> [<save2>]   (默认目录 {d})")
        return 1
    if len(args) == 1:
        describe(Path(args[0]))
    else:
        describe(Path(args[0]))
        print()
        describe(Path(args[1]))
        print()
        diff(Path(args[0]), Path(args[1]))
    return 0


if __name__ == "__main__":
    sys.exit(main())
