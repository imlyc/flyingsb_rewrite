"""把代码里手工转录的动画 seq 和 FlyingSB.exe 里的原字节逐 op 对照, 揪出转录时丢掉/抄错的 op.

背景: 原版技能演出 = exe 代码 (think fn, 只能移植) + .data 里的 seq 字节码 (是数据, 我们按 op
手工转录成 tuple, 见 core/raw_attack_seqs.py / skill_seq.py / son_transform.py ...). 转录会漏
(白虎盘踞 seq 0x671b48 里的 sound 0x139 就漏过), 这里机器对一遍.

做法:
  1. 收集各模块里的 seq (list[tuple]) 和 4 方向表 (list[4 个 seq]);
  2. 把每个 seq 前几个 op 编成"slot 位通配"的字节模式, 在 exe 里搜 (slot 是我们重编号的 atlas
     id, 跟 exe 的 slot 号不同, 其它字段应逐字节一致) → 定位原地址;
  3. 从该地址解码 exe 的 op 流, 与我们的 op 流做归一化 diff (忽略 slot), 列出差异;
     重点标出 exe 有而我们没有的 sound / signal op.

跑法: cd rewrite && venv/bin/python -m tools.verify_seqs [-v] [名字过滤]
"""
from __future__ import annotations

import difflib
import importlib
import os
import re
import struct
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
ORIGIN = Path(os.environ.get("FLYINGSB_ORIGIN", ROOT.parent / "origin" / "flyingsb"))
EXE = Path(os.environ.get("FLYINGSB_EXE", ORIGIN / "FlyingSB.exe"))
IMAGE_BASE = 0x400000

MODULES = ("core.raw_attack_seqs", "core.skill_seq", "core.son_transform", "core.projectile", "core.pig_skills", "core.pao_skills", "core.bosan_skills", "core.jet_skills", "core.mina_skills",
           "core.hit_effect_seq")
SEQ_KINDS = {"fm", "idle", "fm_m1", "move", "sound", "impact", "jump", "end", "exit", "loop", "raw"}
SIG_IMPACT, SIG_END = -100, -110
# 我们为绕开 tactics 普攻 IMPACT 结算而改用的专用信号 = exe 原 -100 (超亂舞 -1008, 猪八戒 -1009)
SIG_ALIASES = {-1008: SIG_IMPACT, -1009: SIG_IMPACT, -1010: SIG_IMPACT, -1011: SIG_IMPACT, -1012: -200, -1013: SIG_IMPACT}   # 破无 -1010, 捕山 -1011/-1012
MAX_OPS = 400


# ---------------- 归一化 op (两边共用) ----------------
# ('F', frame, ticks) / ('M', dx, dy, dz, ticks) / ('S', id, op) / ('G', sig) / ('X',) / ('L',) / ('R', ...)
def norm_ours(seq) -> list[tuple]:
    out = []
    for t in seq:
        k = t[0]
        if k in ("fm", "idle", "fm_m1"):
            out.append(("F", t[2], t[3]))
        elif k == "move":
            dx, dy, dz, ticks = (t[1], t[2], 0, t[3]) if len(t) == 4 else t[1:]
            out.append(("M", dx, dy, abs(dz), ticks))     # dz 取绝对值 (z 轴方向约定相反)
        elif k == "sound":
            out.append(("S", t[1], 0x13 if t[2] == 0x0413 else 0x11))
        elif k == "impact":
            out.append(("G", t[1] if len(t) > 1 else SIG_IMPACT))
        elif k == "jump":
            out.append(("G", SIG_ALIASES.get(t[1], t[1])))
        elif k == "end":
            out.append(("G", SIG_END))
        elif k == "exit":
            out.append(("X",))
        elif k == "loop":
            out.append(("L",))
        elif k == "raw":
            out.append(("R", t[1] & 0xFF, t[2], t[3], t[4], t[5]))
    return out


def decode_exe(data: bytes, off: int) -> list[tuple]:
    """从 off 解码 op 流直到 EXIT/LOOP (含). 返回归一化 op 列表."""
    out = []
    while off + 2 <= len(data) and len(out) < MAX_OPS:
        op, size = data[off], data[off + 1]
        if size < 2 or size > 16:
            break
        body = data[off + 2: off + size]
        if op in (0x04, 0x05, 0x06) and size == 10:
            _slot, frame, ticks = struct.unpack("<HIH", body)
            out.append(("F", frame, ticks))
        elif op in (0x0B, 0x0C) and size == 10:
            dx, dy, dz, ticks = struct.unpack("<hhhH", body)
            out.append(("M", dx, dy, abs(dz), ticks))
        elif op in (0x11, 0x12, 0x13) and size == 4:
            out.append(("S", struct.unpack("<H", body)[0], 0x13 if op == 0x13 else 0x11))
        elif op == 0x0E and size == 4:
            out.append(("G", struct.unpack("<h", body)[0]))
        elif op == 0x00:
            out.append(("X",)); break
        elif op == 0x01:
            out.append(("L",)); break
        else:
            vals = struct.unpack("<%dh" % ((size - 2) // 2), body[: (size - 2) // 2 * 2])
            out.append(("R", op) + tuple(vals))
        off += size
    return out


# ---------------- 在 exe 里定位 ----------------
def _pattern(ops: list[tuple], n: int = 8) -> bytes | None:
    """前 n 个 op 的字节模式 (regex, slot 位通配). 不足 3 个可用 op 返回 None."""
    parts = []
    for o in ops[:n]:
        if o[0] == "F":
            parts.append(rb"[\x04\x05\x06]\x0a.." + re.escape(struct.pack("<IH", o[1], o[2])))
        elif o[0] == "M":
            # 我们的 z 轴朝上为负, exe 相反 → dz 允许正负两种
            dx, dy, dz, ticks = o[1:]
            alts = {struct.pack("<hhhH", dx, dy, dz, ticks), struct.pack("<hhhH", dx, dy, -dz, ticks)}
            parts.append(rb"[\x0b\x0c]\x0a(?:" + b"|".join(re.escape(a) for a in alts) + rb")")
        elif o[0] == "S":
            parts.append(re.escape(bytes([o[2], 4])) + re.escape(struct.pack("<H", o[1])))
        elif o[0] == "G":
            parts.append(rb"\x0e\x04" + re.escape(struct.pack("<h", o[1])))
        elif o[0] == "X":
            parts.append(rb"\x00\x02")
        elif o[0] == "L":
            parts.append(rb"\x01\x02")
        else:
            break
    if len(parts) < 3:
        return None
    return b"".join(parts)


def locate(data: bytes, ops: list[tuple]) -> list[int]:
    """先用长模式 (8 op) 精确找, 找不到再放宽到 5 / 3 op (转录时改过前几个 op 的 seq)."""
    for n in (8, 5, 3):
        pat = _pattern(ops, n)
        if pat is None:
            continue
        hits = [m.start() for m in re.finditer(pat, data, re.S)]
        if hits:
            return hits
    return []


# ---------------- 收集 ----------------
def _is_seq(v) -> bool:
    return (isinstance(v, (list, tuple)) and len(v) > 0
            and all(isinstance(t, tuple) and t and isinstance(t[0], str) and t[0] in SEQ_KINDS
                    for t in v))


def collect() -> list[tuple[str, list]]:
    found = []
    for mn in MODULES:
        mod = importlib.import_module(mn)
        for name, v in vars(mod).items():
            if name.startswith("__") or not isinstance(v, (list, tuple)):
                continue
            if _is_seq(v):
                found.append((f"{mn.split('.')[-1]}.{name}", list(v)))
            elif isinstance(v, list) and len(v) == 4 and all(_is_seq(d) for d in v):
                for i, d in enumerate(v):
                    found.append((f"{mn.split('.')[-1]}.{name}[{('UP', 'DN', 'LF', 'RT')[i]}]", list(d)))
    return found


def fmt(o: tuple) -> str:
    return {"F": "fm f=%d t=%d", "M": "move %d,%d,%d t=%d", "S": "SOUND 0x%x op%02x",
            "G": "signal %d", "X": "exit", "L": "loop"}.get(o[0], "raw " + "%s " * (len(o) - 1)) % o[1:] \
        if o[0] in "FMSGXL" and len(o) > 1 else ("exit" if o[0] == "X" else "loop" if o[0] == "L" else repr(o))


def compare(name: str, ours: list, data: bytes, verbose: bool) -> dict:
    mine = norm_ours(ours)
    hits = locate(data, mine)
    res = {"name": name, "addr": None, "status": "", "missing": [], "diff": []}
    if not hits:
        res["status"] = "NOT FOUND" if _pattern(mine) else "TOO SHORT"
        return res
    a = [fmt(o) for o in mine]
    best = None
    for h in hits[:64]:                      # 多处命中: 取与我们差异最小的那处
        th = decode_exe(data, h)
        b = [fmt(o) for o in th]
        # 我们常把 ('end',) 之后省掉 exe 的 exit; 比较时补上同等结尾
        if a and b and a[-1] != "exit" and b[-1] == "exit" and mine[-1][0] == "G":
            b = b[:-1]
        d = [l for l in difflib.unified_diff(b, a, "exe", "ours", lineterm="", n=0)
             if not l.startswith(("---", "+++", "@@"))]
        if best is None or len(d) < len(best[2]):
            best = (h, th, d)
    hit, theirs, diff = best
    res["addr"] = hit + IMAGE_BASE
    res["diff"] = diff
    ours_set = set(mine)
    res["missing"] = [fmt(o) for o in theirs if o[0] in ("S", "G") and o not in ours_set]
    res["status"] = "OK" if not diff else "DIFF"
    if len(hits) > 1:
        res["status"] += f" (exe 里 {len(hits)} 处相同)"
    return res


def main(argv: list[str]) -> int:
    verbose = "-v" in argv
    filt = [a for a in argv if not a.startswith("-")]
    if not EXE.exists():
        print(f"缺 {EXE}")
        return 2
    data = EXE.read_bytes()
    seqs = [(n, s) for n, s in collect() if not filt or any(f in n for f in filt)]
    bad = 0
    for name, seq in seqs:
        r = compare(name, seq, data, verbose)
        addr = f"@0x{r['addr']:x}" if r["addr"] else ""
        flag = "  ⚠ 漏: " + "; ".join(r["missing"]) if r["missing"] else ""
        print(f"{r['status']:<10} {name:<48} {addr:<10}{flag}")
        if r["missing"] or r["status"].startswith("NOT"):
            bad += 1
        if verbose and r["diff"]:
            for l in r["diff"]:
                print("    " + l)
    print(f"\n{len(seqs)} 条 seq, {bad} 条有问题 (漏 sound/signal 或没定位到)")
    return 1 if bad else 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
