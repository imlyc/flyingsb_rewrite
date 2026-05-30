"""Parse skill0.txt + static_pat.txt → rewrite/core/skill_patterns_data.py.

数据来源 (Ghidra dump 输出, ~/Work/flyingsb/reverse_engineering/):
- skill0.txt: 66 技能 [0]=action_template_idx (skill table @ 0x68b4b0)
- static_pat.txt: action template @ 0x644590 (24B/entry) + pattern set1 @ 0x644f48 + set2 @ 0x645d00

调用方式: python rewrite/tools/parse_patterns.py
重新 dump exe 后跑一次即可.
"""

from __future__ import annotations

import re
from pathlib import Path

# 本脚本在 rewrite/tools/, 数据源 ~/Work/flyingsb/reverse_engineering/, 输出 ../core/.
HERE = Path(__file__).parent                                      # rewrite/tools
REPO = HERE.parent.parent                                          # ~/Work/flyingsb
RE_DIR = REPO / "reverse_engineering"
SKILL0 = RE_DIR / "skill0.txt"
STATIC_PAT = RE_DIR / "static_pat.txt"
OUT = HERE.parent / "core" / "skill_patterns_data.py"

SKILL_RE = re.compile(r"^skill 0x([0-9a-f]+): tmpl_idx=(-?\d+)\s+fn=0x([0-9a-f]+)")
TMPL_RE = re.compile(
    r"^\s*(\d+)\s+\(0x[0-9a-f]+\)\s+\|\s+p1=\s*(\d+)\s+p2=\s*(\d+)"
    r"\s+ax=\s*(-?\d+)\s+ay=\s*(-?\d+)"
)
PAT_HEADER_RE = re.compile(r"^--- set([12]) pattern (\d+)")


def parse_skill_template() -> dict[int, int]:
    out: dict[int, int] = {}
    for line in SKILL0.read_text().splitlines():
        m = SKILL_RE.match(line)
        if m:
            out[int(m.group(1), 16)] = int(m.group(2))
    return out


def parse_action_templates() -> list[tuple[int, int, int, int]]:
    out: list[tuple[int, int, int, int]] = []
    for line in STATIC_PAT.read_text().splitlines():
        if line.startswith("# Pattern set"):
            break
        m = TMPL_RE.match(line)
        if m:
            idx, p1, p2, ax, ay = (int(x) for x in m.groups())
            assert idx == len(out), f"action template idx gap at {idx}"
            out.append((p1, p2, ax, ay))
    return out


def parse_pattern_grids() -> tuple[list[tuple[tuple[int, ...], ...]], list[tuple[tuple[int, ...], ...]]]:
    """Return (set1, set2). Each = list of 11×11 grids (row-major).

    set1 cell: 2 = walkable (else 0)
    set2 cell: int value; downstream uses `val & 4` for damage bit
    """
    set1: list[tuple[tuple[int, ...], ...]] = []
    set2: list[tuple[tuple[int, ...], ...]] = []

    cur_set = None
    cur_idx = None
    cur_rows: list[tuple[int, ...]] = []
    unique_vals: dict[int, list[int]] = {}  # idx → vals for set2
    junked = {1: False, 2: False}   # 一旦碰到 junk pattern 就停止收该 set

    def flush():
        nonlocal cur_rows
        if cur_set is None:
            return
        if len(cur_rows) != 11 or junked[cur_set]:
            cur_rows = []
            return
        target = set1 if cur_set == 1 else set2
        if cur_idx != len(target):
            # 跳过已 junk 区, 不再追加
            cur_rows = []
            return
        target.append(tuple(cur_rows))
        cur_rows = []

    for line in STATIC_PAT.read_text().splitlines():
        m = PAT_HEADER_RE.match(line)
        if m:
            flush()
            cur_set = int(m.group(1))
            cur_idx = int(m.group(2))
            continue
        if cur_set is None:
            continue
        if line.startswith("  unique vals:"):
            # parse for set2 — we need the actual values to map glyphs
            vals_str = line.split(":", 1)[1].strip()
            vals = [int(v) for v in vals_str.strip("[]").split(",") if v.strip()]
            if cur_set == 2:
                unique_vals[cur_idx] = vals
            # junk 检测: 真 pattern 只有 1-6 unique vals (= flag-like 字节);
            # > 10 = 读到 pattern 表后的随机数据, 该 set 到此为止.
            if len(vals) > 10:
                junked[cur_set] = True
                cur_rows = []
            continue
        # data row?  "  . . . . . X . . . . ."  → 11 tokens
        stripped = line.strip()
        if not stripped or stripped.startswith("#") or stripped.startswith("INFO"):
            continue
        tokens = stripped.split()
        if len(tokens) != 11:
            continue
        # Each token is either '.', a digit/hex, 'X', or '@'.
        # set1: X/@ = center (col 5 row len(cur_rows)==5). X means center has val 2.
        # set2: X = center (may have damage bit). Other cells are decimal vals like '4', '68', '140'.
        # The dump only prints the LOW value-token; for set2 some cells are printed as composite values, but
        # from the dumps we see '.' or '4' or 'X'. set1 sees '.' or '2' or '@' or 'X'.
        row: list[int] = []
        for col, tok in enumerate(tokens):
            if tok == ".":
                row.append(0)
            elif tok == "@":
                row.append(0)  # center, but val != 2
            elif tok == "X":
                # Center cell. For set1, X means val==2 (walkable).
                # For set2, X means the center; check unique_vals to know if it has damage bit.
                if cur_set == 1:
                    row.append(2)
                else:
                    # set2 center: dump glyph 'X' marks the cursor anchor, but the cell's actual exe
                    # value still has bit 2 set in every observed pattern (unique_vals always shows
                    # damage-bit values like 0x44/0x84/0x8c). So treat center as damage.
                    row.append(4)
            else:
                try:
                    row.append(int(tok))
                except ValueError:
                    row.append(0)
        # Post-fix: for set2, if center is 'X' but the rest of the row + grid is FULL of '4',
        # treat center as also damaged (= full-screen patterns hit cursor cell too).
        cur_rows.append(tuple(row))

    flush()

    # set1 物理结束于 set2 base: (0x645d00 - 0x644f48) / 0x79 = 29.02 → 真 29 项 (idx 0..28).
    # idx 29+ 读到 set2 区域的 bytes, 误识别成 set1. unique_vals heuristic 抓不到 (它们是 valid set2 数据).
    # 硬截断.
    if len(set1) > 29:
        del set1[29:]

    return set1, set2


def fmt_grid(grid: tuple[tuple[int, ...], ...], indent: str = "        ") -> str:
    rows = []
    for r in grid:
        rows.append(indent + "(" + ", ".join(str(v) for v in r) + "),")
    return "\n".join(rows)


def main() -> None:
    skill_tmpl = parse_skill_template()
    tmpls = parse_action_templates()
    set1, set2 = parse_pattern_grids()

    print(f"skills: {len(skill_tmpl)}  templates: {len(tmpls)}  set1: {len(set1)}  set2: {len(set2)}")

    lines = [
        '"""AUTO-GENERATED by rewrite/tools/parse_patterns.py — do not edit by hand."""',
        "",
        "from __future__ import annotations",
        "",
        "# skill_id → action_template_idx  (skill table @ exe 0x68b4b0 field [0])",
        "SKILL_TEMPLATE: dict[int, int] = {",
    ]
    for sid in sorted(skill_tmpl):
        lines.append(f"    0x{sid:02x}: {skill_tmpl[sid]},")
    lines.append("}")
    lines.append("")
    lines.append("# action_template[idx] = (p1_idx, p2_idx, anchor_x, anchor_y)  (DAT_00644590 24B/entry)")
    lines.append("# p1 → cursor-walkable grid in PATTERN_SET1, p2 → AOE damage grid in PATTERN_SET2.")
    lines.append("# anchor (ax, ay) likely projectile spawn offset; not used for AOE math.")
    lines.append("ACTION_TEMPLATES: tuple[tuple[int, int, int, int], ...] = (")
    for t in tmpls:
        lines.append(f"    {t},")
    lines.append(")")
    lines.append("")
    lines.append("# 11×11 grids, row-major (grid[row][col]). Center = (row=5, col=5) = unit position.")
    lines.append("# Cell == 2 means tile is cursor-walkable (relative to unit, default facing = up (0,-1)).")
    lines.append("PATTERN_SET1: tuple[tuple[tuple[int, ...], ...], ...] = (")
    for i, g in enumerate(set1):
        lines.append(f"    (  # set1 pattern {i}")
        lines.append(fmt_grid(g))
        lines.append("    ),")
    lines.append(")")
    lines.append("")
    lines.append("# Same shape; center = cursor position. Damage tile iff (cell & 4) != 0.")
    lines.append("PATTERN_SET2: tuple[tuple[tuple[int, ...], ...], ...] = (")
    for i, g in enumerate(set2):
        lines.append(f"    (  # set2 pattern {i}")
        lines.append(fmt_grid(g))
        lines.append("    ),")
    lines.append(")")
    lines.append("")

    OUT.write_text("\n".join(lines))
    print(f"wrote {OUT}")


if __name__ == "__main__":
    main()
