"""敌方招式 (248 项, exe 招式表 0x692F54 stride 0x20) → core/enemy_move_data.py (生成文件).

记录: +0 名称 +4 威力 +8 flags (0x800000 物理 / 0x4000 计方位 / 0x8000 计属性 / 0x10 可反击 / &3 目标类型 0 打我方
1 对己方 2 打我方(另一种站位) / 0xf000000 结算类别 0 伤害 1 加异常 2 回复 3 召唤 4 固定伤害 / 0x1f00 附带异常)
+0xc 扣敌 MP +0x10 ? +0x14 动作模板 (范围, ACTION_TEMPLATES) +0x18 处理函数.
处理函数按反编译 (reverse_engineering/enemy_moves_decomp*.txt) 分类:
  doit   : FUN_004d0e18(this, seq 表[4 方向], 命中特效) — 同玩家普攻 DOIT_melee; 特效 starburst 655b18 /
           claw 655d30[dir] / oval 655ca0[dir] / dir4 655dc0[dir] / spark2 655b60
  tmpl   : 调一个通用演出模板 FUN_xxx(this, 参数表) (另做)
  custom : 自写状态机 (另做)
  带 '+hook' = 在某些信号上另有处理 (音效/转身/挂 seq), 其余交给 doit/模板.
跑法: cd rewrite && venv/bin/python -m tools.extract_enemy_moves
"""
from __future__ import annotations

import json
import re
from pathlib import Path

from tools.extract_normal_attacks import EXE, Exe

ROOT = Path(__file__).resolve().parent.parent
RE_DIR = ROOT.parent / "reverse_engineering"
OUT = ROOT / "core" / "enemy_move_data.py"
FX = {'&DAT_00655b18': 'starburst', '&DAT_00655b60': 'spark2', '(&PTR_DAT_00655d30)': 'claw',
      '(&PTR_DAT_00655ca0)': 'oval', '(&PTR_DAT_00655dc0)': 'dir4'}


def _funcs() -> dict[str, str]:
    out = {}
    for f in ("enemy_moves_decomp.txt", "enemy_moves_decomp_missing.txt"):
        txt = (RE_DIR / f).read_text(encoding="utf-8")
        parts = re.split(r"^=== (FUN_[0-9a-f]+) ===", txt, flags=re.M)
        for i in range(1, len(parts), 2):
            out[parts[i].lower()] = parts[i + 1]
    return out


def classify(body: str):
    doit = re.search(r"FUN_004d0e18\(param_1,&?PTR_DAT_([0-9a-f]+),(.*?)\);", body)
    calls = re.findall(r"(FUN_[0-9a-f]+)\(param_1,&?(PTR_PTR|PTR_DAT|DAT)_([0-9a-f]+)\);", body)
    hook = "param_1 + 0x14c) == -" in body or "== -0x" in body
    lines = [ln for ln in body.split("\n") if ln.strip() and not ln.strip().startswith(("void", "{", "}", "return"))]
    if doit:
        fxs = doit.group(2)
        fx = next((v for k, v in FX.items() if fxs.startswith(k)), "?")
        return ("doit+hook" if (hook or len(lines) > 2) else "doit"), "FUN_004d0e18", int(doit.group(1), 16), fx
    if len(calls) == 1 and calls[0][0] != "FUN_004c4a6f":
        fn, _, arg = calls[0]
        return ("tmpl+hook" if (hook or len(lines) > 2) else "tmpl"), fn, int(arg, 16), None
    return "custom", None, None, None


def main() -> None:
    e = Exe(EXE)
    acts = json.loads((ROOT / "assets" / "enemy_actions.json").read_text(encoding="utf-8"))["actions"]
    funcs = _funcs()
    rows, tables, bad = [], {}, []
    for i in range(248):
        a = acts[str(i)]
        fva = int(a["func"])
        body = funcs.get(f"fun_{fva:08x}", "")
        kind, fn, arg, fx = classify(body) if body else ("custom", None, None, None)
        if kind.startswith("doit") and arg not in tables:
            try:
                tables[arg] = [e.seq(e.u32(arg + 4 * d)) for d in range(4)]
            except ValueError as ex:
                bad.append((i, str(ex)))
                kind = "custom"
        rows.append((i, a["name"], int(a["param_a"]), int(a["flags"]), int(a["p3"]), int(a["p4"]), int(a["p5"]),
                     fva, kind, fn, arg, fx))
    lines = ['"""生成文件 (tools/extract_enemy_moves.py), 勿手改. 敌方招式表 0x692F54 + 处理函数分类 + DOIT seq 表."""',
             "from __future__ import annotations", "",
             "# id → (名称, 威力, flags, 扣MP, +0x10, 动作模板, 处理函数, 类别, 调用模板/DOIT, 参数(seq 表/模板参数), 命中特效)",
             "MOVES: list[tuple] = ["]
    for r in rows:
        lines.append(f"    ({r[1]!r}, {r[2]}, {r[3]:#x}, {r[4]}, {r[5]}, {r[6]}, {r[7]:#x}, {r[8]!r}, {r[9]!r}, "
                     f"{hex(r[10]) if r[10] is not None else None}, {r[11]!r}),   # {r[0]}")
    lines += ["]", "", "# DOIT seq 表地址 → [上, 下, 左, 右] (exe 原字节解码)", "SEQ_TABLES: dict[int, list[list[tuple]]] = {"]
    for t, dirs in tables.items():
        lines.append(f"    {t:#x}: [")
        lines += [f"        {s!r}," for s in dirs]
        lines.append("    ],")
    lines += ["}", ""]
    OUT.write_text("\n".join(lines), encoding="utf-8")
    from collections import Counter
    print("written", OUT, Counter(r[8] for r in rows), "decode errors", bad[:5], len(bad))


if __name__ == "__main__":
    main()
