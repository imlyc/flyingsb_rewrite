"""原版「事件脚本」(wh/seq.cpp 脚本 VM) 的解码器 + 解释器.

原版剧情演出 (序章、NPC 对白分支等) 不是 anim seq 字节码, 而是另一套通用脚本语言, 由
`FUN_00467cbc` 解释执行, 256 个 op 的处理函数表在 VA 0x632b78. 事件表 `PTR_DAT_0073df8c`
(168 个事件入口), 新游戏序章 = 事件 0 (切到地图 469 樂神封印孙悟空) 起, 事件脚本自己切图.

指令格式 (逆向 2026-10-18, 见 reverse_engineering/EVENT_SCRIPT_SPEC.md):
  [op u8][sub u8][len u16][操作数 ...]      len 含 4 字节头
  操作数 5 字节: [type u8][value u32]
    type 0x00 = 立即数;  0x80 = 立即指针 (字符串/脚本地址);  0x04/0x84 = 立即数 (字段偏移/全局地址)
    type bit6 (0x40) = 变量: 低 6 位 = 字节数 (1/2/4), bit7 = 全局 (value 是绝对地址),
      否则 value 是脚本上下文内偏移 (局部变量, 如 +0x44 返回值槽 / +0xe8 +0xec 临时).
    例: 0xc4 0x73e235 = 全局 dword 变量 (对象句柄表: 0x73e235 起 = FC id 0,1,3,4,5,6,8,9,...).
  op 0x05 (switch 跳) / 0x06 (switch 调, 压返回地址) 例外: 操作数 count, index 之后紧跟 count 个 u32 地址 (@+0xe).

执行模型: 每帧跑到某条指令要求 "等待" 为止 (原版 DAT_007d76ec = 1/2), 下一帧继续.
对外: 解释器只管控制流/变量, 所有世界副作用通过 Host 回调 (见 EventHost) 完成,
场景层 (scenes/prologue.py) 用 anim engine 实体 + 真实地图实现这些回调.
"""
from __future__ import annotations

import os
import math
import struct
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable

ROOT = Path(__file__).resolve().parent.parent
ORIGIN = Path(os.environ.get("FLYINGSB_ORIGIN", ROOT.parent / "origin" / "flyingsb"))
EXE = Path(os.environ.get("FLYINGSB_EXE", ORIGIN / "FlyingSB.exe"))
IMAGE_BASE = 0x400000
EVENT_TABLE_VA = 0x73DF8C
EVENT_COUNT_MAX = 0xA8            # FUN_0045901c: 0 <= ev <= 0xa7
from core.dialog_engine import DialogTask, MessageQueue, code_str, fast_forward  # noqa: E402

TALK_SCRIPT_VA = 0x73C192
EVENT_FLAGS_VA = 0x7D72E8         # DAT_007d72e8[ev]: 事件触发次数 (92.02/03 自增, 91.00 读)
G_EVENT_NOW, G_EVENT_PREV, G_EVENT_NEXT, G_EVENT_DEFER = 0x613060, 0x613064, 0x613068, 0x61306C
G_MAP_NOW = 0x654D98              # DAT_00654d98: 当前地图号         # 4f.09 给 FC 起的子任务跑的标准 "说话" 脚本
FC_VAR_BASE = 0x73E235            # 对象句柄变量表 (dword), 值 = FC id
G_PARTY_MASK = 0x7D8008           # DAT_007d8008: 队伍位掩码 (e8.08 写; bit i → PARTY_SLOT_FC[i])
G_PARTY_LEADER = 0x867E80         # DAT_00867e80 (原版存对象下标, 这里直接存队长 FC id)
# DAT_0063fa28: 队伍槽 i → FC id (e8.08 的掩码按这张表展开)
PARTY_SLOT_FC = (1, 3, 4, 5, 6, 8, 9, 10, 11, 12)

# 操作数类型
T_IMM, T_PTR = "imm", "ptr"


@dataclass
class Operand:
    kind: str           # imm / ptr / var
    value: int          # 立即数 / 地址 / 变量地址(全局) 或 偏移(局部)
    size: int = 4
    is_global: bool = True
    raw_type: int = 0

    def __repr__(self) -> str:
        if self.kind == "imm":
            return str(self.value)
        if self.kind == "ptr":
            return f"ptr:{self.value:#x}"
        return f"{'g' if self.is_global else 'l'}var{self.size}@{self.value:#x}"


@dataclass
class Cmd:
    addr: int
    op: int
    sub: int
    size: int
    operands: list[Operand]
    table: list[int] = field(default_factory=list)   # op 05 的跳转表
    text: str | None = None                          # 4f.09 / 88.00 的对白 (Big5 解码)

    def __repr__(self) -> str:
        t = f" text={self.text[:30]!r}" if self.text else ""
        return f"<{self.addr:#x} {self.op:02x}.{self.sub:02x} {self.operands}{t}>"


class ExeImage:
    """FlyingSB.exe 的只读映像 (VA 寻址)."""

    def __init__(self, path: Path = EXE) -> None:
        self.data = path.read_bytes()

    def u8(self, va: int) -> int:
        return self.data[va - IMAGE_BASE]

    def u16(self, va: int) -> int:
        return struct.unpack_from("<H", self.data, va - IMAGE_BASE)[0]

    def u32(self, va: int) -> int:
        return struct.unpack_from("<I", self.data, va - IMAGE_BASE)[0]

    def in_range(self, va: int) -> bool:
        return 0 <= va - IMAGE_BASE < len(self.data) - 4

    def cstr(self, va: int, limit: int = 4000) -> str:
        o = va - IMAGE_BASE
        e = self.data.find(b"\0", o, o + limit)
        if e < 0:
            e = o + limit
        return self.data[o:e].decode("big5", errors="replace")

    def read_var(self, va: int, size: int) -> int:
        if not self.in_range(va):
            return 0
        if size == 1:
            return self.u8(va)
        if size == 2:
            return self.u16(va)
        return self.u32(va)


def decode_operands(raw: bytes) -> list[Operand]:
    out: list[Operand] = []
    i = 0
    while i + 5 <= len(raw):
        t = raw[i]
        v = struct.unpack_from("<I", raw, i + 1)[0]
        i += 5
        if t & 0x40:
            out.append(Operand("var", v, t & 0x3F or 4, bool(t & 0x80), t))
        elif t == 0:
            out.append(Operand("imm", v if v < 0x80000000 else v - (1 << 32), 4, True, t))
        elif t == 0x80:
            out.append(Operand("ptr", v, 4, True, t))
        else:
            out.append(Operand("imm", v, 4, True, t))     # 0x04 字段偏移 / 0x84 全局地址 等
    return out


# 解释器 256 项处理表 PTR_FUN_00632b78 里有真实处理函数的 op (其余 156 项指向空处理 0x4680b9)
KNOWN_OPS = frozenset([
    0x00, 0x01, 0x02, 0x03, 0x04, 0x05, 0x06, 0x07, 0x08, 0x09, 0x0B, 0x0C, 0x0D, 0x0E, 0x0F, 0x10, 0x11,
    0x12, 0x14, 0x18, 0x19, 0x1F, 0x20, 0x21, 0x25, 0x26, 0x27, 0x28, 0x29, 0x2C, 0x2D, 0x2E, 0x30, 0x31,
    0x38, 0x40, 0x41, 0x42, 0x44, 0x45, 0x46, 0x47, 0x48, 0x4A, 0x4B, 0x4C, 0x4D, 0x4F, 0x50, 0x51, 0x52,
    0x58, 0x5C, 0x5D, 0x60, 0x61, 0x62, 0x64, 0x65, 0x66, 0x67, 0x68, 0x6F, 0x71, 0x78, 0x80, 0x81, 0x88,
    0x89, 0x90, 0x91, 0x92, 0x98, 0x99, 0x9C, 0xA0, 0xA1, 0xA8, 0xB1, 0xC0, 0xC1, 0xC2, 0xC8, 0xD0, 0xD1,
    0xE0, 0xE1, 0xE2, 0xE4, 0xE6, 0xE8, 0xE9, 0xEA, 0xEC, 0xED, 0xEE, 0xEF, 0xF0, 0xF1, 0xF2])


def cmd_valid(img: ExeImage, p: int) -> bool:
    """一条指令的形状是否合法: 已知 op, 长度 = 4 + 5n (switch: 4 + 10 + 4·cnt)."""
    op = img.u8(p)
    size = img.u16(p + 2)
    if op not in KNOWN_OPS or size < 4 or not img.in_range(p + size - 1):
        return False
    if op in (0x05, 0x06):                              # 05 switch-jump / 06 switch-call 同形
        if size < 14 or img.u8(p + 4) != 0:
            return False
        return size == 14 + 4 * img.u32(p + 5) and size <= 14 + 4 * 512
    if size > 4 + 5 * 24:
        return False
    return (size - 4) % 5 == 0


def decode_script(img: ExeImage, va: int, end_va: int | None = None, max_cmds: int = 20000,
                  stop_at: set[int] | None = None) -> list[Cmd]:
    """从 va 线性解码一段脚本, 到 end_va (下一事件入口) / 遇到顶层 op 00 (事件结束) / 碰到非法指令
    (03 跳转后面常紧跟对白字符串) / 到达 stop_at 里已解过的地址 为止."""
    cmds: list[Cmd] = []
    p = va
    depth = 0
    while img.in_range(p) and len(cmds) < max_cmds:
        if end_va is not None and p >= end_va:
            break
        if stop_at is not None and p in stop_at and p != va:
            break
        if not cmd_valid(img, p):
            break
        op, sub = img.u8(p), img.u8(p + 1)
        size = img.u16(p + 2)
        raw = img.data[p + 4 - IMAGE_BASE: p + size - IMAGE_BASE]
        if op in (0x05, 0x06):
            ops = decode_operands(raw[:10])
            cnt = ops[0].value if ops and ops[0].kind == "imm" else 0
            table = [struct.unpack_from("<I", raw, 10 + 4 * k)[0] for k in range(max(0, cnt))
                     if 10 + 4 * k + 4 <= len(raw)]
            cmd = Cmd(p, op, sub, size, ops, table)
        else:
            cmd = Cmd(p, op, sub, size, decode_operands(raw))
        if op in (0x4F, 0x88) and sub in (0x08, 0x09, 0x00) and len(cmd.operands) >= 2:
            for o in cmd.operands:
                if o.kind == "ptr" and img.in_range(o.value):
                    s = img.cstr(o.value, 3000)
                    if any(ord(c) > 0x7F for c in s) or "<" in s or "@" in s:
                        cmd.text = s
                        break
        cmds.append(cmd)
        p += size
        # 嵌套深度粗略跟踪, 只用于 end_va 未知时判断脚本末尾
        if op in (0x0B, 0x0D, 0x10):
            depth += 1
        elif op in (0x0C, 0x0E, 0x12):
            depth = max(0, depth - 1)
        if end_va is None and op == 0x00 and depth == 0 and sub not in (1, 2):
            break
    return cmds


def decode_region(img: ExeImage, va: int, end_va: int | None = None, max_cmds: int = 20000) -> list[Cmd]:
    """顺着控制流解码: 线性扫 + 03 跳转 / 05 switch 表的目标 (原版事件里对白字符串夹在代码中间,
    纯线性扫会在那里断掉, 漏掉后半段; 如 ev2 的第二阶段 0x6a2b6a). 结果按地址排序."""
    seen: dict[int, Cmd] = {}
    queue = [va]
    while queue and len(seen) < max_cmds:
        start = queue.pop()
        if start in seen or not img.in_range(start) or (end_va is not None and start >= end_va):
            continue
        for c in decode_script(img, start, end_va, max_cmds, stop_at=set(seen)):
            if c.addr in seen:
                break
            seen[c.addr] = c
            if c.op == 0x03:
                queue.extend(o.value for o in c.operands if o.kind == "ptr")
            elif c.op in (0x05, 0x06):
                queue.extend(c.table)
    return [seen[a] for a in sorted(seen)]


def event_entries(img: ExeImage) -> list[int]:
    out = []
    for i in range(EVENT_COUNT_MAX):
        v = img.u32(EVENT_TABLE_VA + 4 * i)
        if v == 0:
            break
        out.append(v)
    return out


def decode_event(img: ExeImage, idx: int, entries: list[int] | None = None) -> list[Cmd]:
    entries = entries or event_entries(img)
    va = entries[idx]
    end = entries[idx + 1] if idx + 1 < len(entries) else None
    return decode_region(img, va, end)


# ---------------------------------------------------------------- 序列化 (assets/script/events.json)
GLOBALS_SNAPSHOT = (0x73C000, 0x73F000)     # 脚本全局变量区 (对象句柄表 0x73e235.., 标准子脚本 0x73c192..)
SUBSCRIPT_OPS = {(0x4F, 0x00), (0x4F, 0x04), (0x4F, 0x08)}
# 引擎内置的 FC 行为脚本 (exe 代码里直接引用的入口): 转向 / 走路 / 走路(模式1) / 45.02 / 45.06 / 气泡汗滴
TURN_SCRIPT_VA, WALK_SCRIPT_VA, WALK1_SCRIPT_VA = 0x738DD8, 0x73BE23, 0x73BE7A
HOP_SCRIPT_VA, HOP2_SCRIPT_VA = 0x73963E, 0x73A4E6
WALKER_SCRIPT_VA, WALKER1_SCRIPT_VA = 0x73BED1, 0x73C008      # 46 寻路走: 逐步取 50.00 的步骤码
BUILTIN_SCRIPTS = (TALK_SCRIPT_VA, TURN_SCRIPT_VA, WALK_SCRIPT_VA, WALK1_SCRIPT_VA, HOP_SCRIPT_VA,
                   HOP2_SCRIPT_VA, WALKER_SCRIPT_VA, WALKER1_SCRIPT_VA, 0x73C5BC, 0x73C703)


def cmd_to_json(c: Cmd) -> dict:
    return {"a": c.addr, "op": c.op, "sub": c.sub, "n": c.size,
            "o": [[o.kind, o.value, o.size, int(o.is_global), o.raw_type] for o in c.operands],
            "t": c.table or None, "s": c.text}


def cmd_from_json(j: dict) -> Cmd:
    ops = [Operand(k, v, sz, bool(g), rt) for k, v, sz, g, rt in j["o"]]
    return Cmd(j["a"], j["op"], j["sub"], j["n"], ops, j.get("t") or [], j.get("s"))


def build_bundle(img: ExeImage, events: list[int] | None = None) -> dict:
    """把事件 + 其引用的子脚本 (4f.00/4f.04/44 挂的行为脚本) + 全局变量区快照打成 JSON 可写的 dict.

    子脚本若落在某个事件的地址区间内, 解码到该事件末尾为止 (与主脚本共享字节, 只存一份入口);
    落在事件区外的 (如标准说话脚本 0x73c192) 解到顶层 op 00 为止."""
    entries = event_entries(img)
    want = events if events is not None else list(range(len(entries)))
    bounds = [(entries[i], entries[i + 1] if i + 1 < len(entries) else entries[i] + 0x8000) for i in range(len(entries))]

    def containing_end(va: int) -> int | None:
        for lo, hi in bounds:
            if lo <= va < hi:
                return hi
        return None

    scripts: dict[int, list[Cmd]] = {}
    ev_out: dict[int, int] = {}
    queue: list[int] = []
    for ev in want:
        ev_out[ev] = entries[ev]
        queue.append(entries[ev])
    queue.extend(BUILTIN_SCRIPTS)
    while queue:
        va = queue.pop()
        if va in scripts or not img.in_range(va):
            continue
        cmds = decode_region(img, va, containing_end(va), max_cmds=4000)
        scripts[va] = cmds
        for c in cmds:
            if (c.op, c.sub) in SUBSCRIPT_OPS:
                for o in c.operands:
                    if o.kind == "ptr" and o.value not in scripts and img.in_range(o.value):
                        queue.append(o.value)
            elif c.op == 0x05 and c.sub in (1, 2):
                # 05.01/05.02 的表里是子脚本指针 (说话脚本按姿势号分派 → 4f.15/16 起任务)
                for v in c.table:
                    if v not in scripts and 0x400000 < v < 0x800000 and img.in_range(v) and cmd_valid(img, v):
                        queue.append(v)
    lo, hi = GLOBALS_SNAPSHOT
    return {
        "events": {str(k): v for k, v in ev_out.items()},
        "scripts": {str(va): [cmd_to_json(c) for c in cmds] for va, cmds in scripts.items()},
        "globals": {"base": lo, "hex": img.data[lo - IMAGE_BASE: hi - IMAGE_BASE].hex()},
        "talk_script": TALK_SCRIPT_VA,
    }


class ScriptBundle:
    """运行时用的事件脚本包 (不需要 exe)."""

    def __init__(self, data: dict) -> None:
        self.events = {int(k): v for k, v in data["events"].items()}
        self.scripts = {int(k): [cmd_from_json(j) for j in v] for k, v in data["scripts"].items()}
        g = data.get("globals") or {}
        self.g_base = g.get("base", 0)
        self.g_bytes = bytes.fromhex(g.get("hex", ""))

    @classmethod
    def load(cls, path: Path | None = None) -> "ScriptBundle | None":
        import json
        path = path or (ROOT / "assets" / "script" / "events.json")
        if not path.exists():
            return None
        return cls(json.loads(path.read_text(encoding="utf-8")))

    def read_var(self, va: int, size: int) -> int:
        off = va - self.g_base
        if 0 <= off and off + size <= len(self.g_bytes):
            return int.from_bytes(self.g_bytes[off:off + size], "little")
        return 0

    def cstr(self, va: int) -> str:
        off = va - self.g_base
        if not (0 <= off < len(self.g_bytes)):
            return ""
        e = self.g_bytes.find(b"\0", off)
        return self.g_bytes[off:e if e >= 0 else None].decode("big5", errors="replace")

    def in_range(self, va: int) -> bool:
        return 0 <= va - self.g_base < len(self.g_bytes)

    def u32(self, va: int) -> int:
        return self.read_var(va, 4)


# ---------------------------------------------------------------- 比较/算术 (FUN_00467eca)
def calc(op: int, a: int, b: int) -> int:
    a &= 0xFFFFFFFF
    b &= 0xFFFFFFFF
    sa = a - (1 << 32) if a & 0x80000000 else a
    sb = b - (1 << 32) if b & 0x80000000 else b
    if op == 0:
        return int(a == b)
    if op == 1:
        return int(a != b)
    if op in (2, 4):
        return int(sa < sb)
    if op in (3, 5):
        return int(sa <= sb)
    if op == 6:
        return int(a != 0 and b != 0)
    if op == 7:
        return int(a != 0 or b != 0)
    if op == 8:
        return (a + b) & 0xFFFFFFFF
    if op == 9:
        return (a - b) & 0xFFFFFFFF
    if op == 10:
        return (a * b) & 0xFFFFFFFF
    if op == 11:
        return int(sa / sb) & 0xFFFFFFFF if sb else 0
    if op == 12:
        return (sa - int(sa / sb) * sb) & 0xFFFFFFFF if sb else 0
    if op == 13:
        return a & b
    if op == 14:
        return a & ~b & 0xFFFFFFFF
    if op == 15:
        return a | b
    if op == 16:
        return a ^ b
    if op == 17:
        return (a << (b & 31)) & 0xFFFFFFFF
    if op == 18:
        return (sa >> (b & 31)) & 0xFFFFFFFF
    return int(a == b)


def signed(v: int) -> int:
    v &= 0xFFFFFFFF
    return v - (1 << 32) if v & 0x80000000 else v


# ---------------------------------------------------------------- Host 接口
class EventHost:
    """世界副作用回调. 场景层继承并实现; 默认实现只打印 (用于干跑/测试).

    返回 True 的 "wait_*" 表示还要等 (解释器本帧停在这条指令, 下帧再问)."""

    def log(self, msg: str) -> None:
        print(msg)

    # 地图 / 画面
    def switch_map(self, map_id: int, reload: bool = False) -> None: self.log(f"[ev] switch_map {map_id}")
    def viewport(self, w: int, h: int) -> None: self.log(f"[ev] viewport {w}x{h}")
    def camera_busy(self) -> bool: return False
    def camera(self, x: int | None, y: int | None, frames: int, relative: bool, follow: int = -1) -> None:
        self.log(f"[ev] camera {x},{y} {frames}f rel={relative}" + (f" follow fc{follow}" if follow != -1 else ""))
    def fade(self, target: str, frames: int, step: int = 0) -> None:
        self.log(f"[ev] fade→{target} {frames}f" + (f" step{step}" if step else ""))
    def palette(self, kind: str, *args: int) -> None: self.log(f"[ev] palette {kind} {list(args)}")
    def wait_fade(self) -> bool: return False
    def caption(self, text: str | None) -> None: self.log(f"[ev] caption {text!r}")
    # 角色 (FC)
    # ---- FC 行为 (返回句柄的: 0 = 立刻完成; 否则 task_alive(hd) 查询) ----
    def fc_turn(self, fc: int, d: int, x: int) -> int: self.log(f"[ev] fc{fc} turn {d}"); return 0
    def fc_walk(self, fc: int, d: int, n: int, mode: int, x: int) -> int:
        self.log(f"[ev] fc{fc} walk dir{d} x{n}"); return 0
    def fc_path(self, fc: int, x: int, y: int, d: int) -> list[int]:
        """46 寻路: 从 fc 当前格到 (x,y) 的步骤码列表 (dir|0x8000 走一格 / dir|0x100 只转向, d = 到达后朝向);
        空 = 不可达 (瞬移)."""
        self.log(f"[ev] fc{fc} path→({x},{y}) face {d}"); return []
    def fc_jump(self, fc: int, dx: int, dy: int, ticks: int, a: int, b: int, flag: int) -> int:
        self.log(f"[ev] fc{fc} jump ({dx},{dy}) {ticks}t"); return 0
    def fc_fly(self, fc: int, px: int, py: int, ticks: int) -> int:
        self.log(f"[ev] fc{fc} fly px({px},{py}) {ticks}t"); return 0
    def fc_step(self, fc: int, d: int) -> int: return (d << 8) | 1          # 40.00: 能走 → 通行码
    def fc_layer(self, fc: int, dz: int) -> None: self.log(f"[ev] fc{fc} layer {dz:+d}")
    def fc_get(self, fc: int, field: int) -> int: return 0                  # 20.04 / 26.01 读对象字段
    def fc_set(self, fc: int, field: int, v: int) -> None: self.log(f"[ev] fc{fc}.{field:#x}={v}")
    def fc_offset(self, fc: int, group: int, x: int | None, y: int | None, z: int | None) -> None:
        self.log(f"[ev] fc{fc} {'pos' if group == 0x100 else 'offset'} {x},{y},{z}")
    def fc_clone(self, src: int) -> int: self.log(f"[ev] clone fc{src}"); return 0x10000
    def fc_blank(self) -> int: self.log("[ev] blank obj"); return 0x10000
    def task_alive(self, hd: int) -> bool: return False
    def fc_on_screen(self, fc: int) -> bool: return True                 # 9c.00: 在镜头内
    def dialog_event(self, dlg: "DialogTask", what: str) -> None: ...
    def fc_place(self, fc: int, x: int, y: int, z: int, d: int) -> None:
        self.log(f"[ev] place fc{fc} ({x},{y},z{z}) d{d}")
    def fc_show(self, fc: int, visible: bool) -> None: self.log(f"[ev] fc{fc} show={visible}")
    def fc_dir(self, fc: int, d: int) -> None: self.log(f"[ev] fc{fc} dir {d}")
    def fc_frame(self, fc: int, frame: int) -> None: self.log(f"[ev] fc{fc} frame {frame}")
    def fc_anim(self, fc: int, mode: int, frame: int, ticks: int) -> None:
        self.log(f"[ev] fc{fc} anim mode={mode:#x} frame={frame} {ticks}t")
    def fc_move(self, fc: int, dx: int, dy: int, ticks: int, teleport: bool) -> None:
        self.log(f"[ev] fc{fc} move ({dx},{dy}) {ticks}t tp={teleport}")
    def fc_spawn(self, kind: int, x: int, y: int, z: int, d: int, base: int = -1) -> int:
        self._spawn_n = getattr(self, "_spawn_n", 0) + 1
        self.log(f"[ev] spawn kind{kind} base{base} ({x},{y},z{z}) d{d}"); return 0x10000 + self._spawn_n
    def fc_destroy(self, handle: int) -> None: self.log(f"[ev] destroy {handle:#x}")
    # 对白
    def speak(self, dlg: "DialogTask") -> None:
        self.log(f"[ev] fc{dlg.fc} [{code_str(dlg.code)}] speak {dlg.text[:40]!r}")
    def wait_dialog(self) -> bool: return False
    # 声音
    def sound(self, sid: int) -> None: self.log(f"[ev] sound {sid:#x}")
    def sound_stop(self, sid: int) -> None: self.log(f"[ev] sound_stop {sid:#x}")
    def wait_sound(self, sid: int) -> bool: return False
    def bgm(self, n: int | None, fade_frames: int = 0) -> None: self.log(f"[ev] bgm {n} fade={fade_frames}")
    def bgm_volume(self, vol: int, frames: int) -> None: self.log(f"[ev] bgm_volume {vol} {frames}f")
    # 系统
    def event_begin(self) -> None: self.log("[ev] event_begin")
    def event_end(self) -> None: self.log("[ev] event_end")
    def key_pressed(self) -> bool: return True
    def party(self, action: str, fc: int) -> None: self.log(f"[ev] party {action} fc{fc}")
    def native(self, fn: int, args: list[int]) -> None: self.log(f"[ev] native {fn:#x} {args}")
    def unknown(self, cmd: Cmd) -> None: self.log(f"[ev] ?? {cmd}")


# ---------------------------------------------------------------- 解释器
class Frame:
    """gosub 调用帧 (07/08): 返回地址 + 调用时 blocks 深度 (返回时丢掉子程序里没闭合的块)."""
    __slots__ = ("ret", "nblocks", "count", "sub", "cmd", "saved")

    def __init__(self, ret: int, nblocks: int, count: int = 0, sub: int = 0, cmd: int = -1,
                 saved: list | None = None) -> None:
        self.ret, self.nblocks, self.count, self.sub, self.cmd = ret, nblocks, count, sub, cmd
        self.saved = saved      # 调用时的块栈快照 (原版块栈是定长数组 + 深度, 返回只恢复深度,
                                # 子程序里 05.00 弹掉的 if 块回来后还在 —— 走路脚本 0x739480 就靠这个)


@dataclass
class Block:
    head: int          # 回跳地址 (0 = 非循环块)
    end: int           # 块结束处 (0 = if 块)
    counter: int = 0
    flag: int = 0
    taken: int = 0     # 10/11/12 if-else 链: 已有分支命中


class EventVM:
    """一个事件脚本任务 (对应原版 FUN_00467cbc 的一个 ctx)."""

    # 1f 原生调用里见到的调色板函数 → fade 语义
    NATIVE_FADE = {0x40B0C5: "fade_start", 0x40A200: "palette_fill", 0x40A342: "palette_set"}

    def __init__(self, img, cmds: list[Cmd], host: EventHost, globals_: dict[int, int] | None = None,
                 name: str = "ev", scripts: dict[int, list[Cmd]] | None = None, fc_default: int = -1,
                 scheduler: "TaskScheduler | None" = None, event_id: int = -1, arg: int = -1,
                 entry: int | None = None) -> None:
        self.img = img                      # ExeImage 或 ScriptBundle (read_var / cstr / in_range)
        self.cmds = cmds
        self.host = host
        self.name = name
        self.scripts = scripts or {}
        self.fc_default = fc_default        # ctx+0xfc: 本任务的默认角色 (子任务 = 所属 FC)
        self.scheduler = scheduler
        if fc_default != -1:
            self.locals = {0xF8: fc_default, 0xFC: fc_default}
        self.by_addr = {c.addr: i for i, c in enumerate(cmds)}
        self.pc = self.by_addr.get(entry, 0) if entry is not None else 0   # cmds 按地址排序, 入口不一定是第 0 条
        if fc_default == -1:
            self.locals: dict[int, int] = {}
        self.calls: list[Frame] = []        # 07/08 调用栈
        self.event_id = event_id            # DAT_00613060 (当前事件号), 子任务 = -1
        self.locals[0x44] = arg & 0xFFFFFFFF  # FUN_0045901c(ev, arg) 的 arg 存在 ctx+0x44
        self.globals = globals_ if globals_ is not None else {}
        self.blocks: list[Block] = []
        self.wait = 0                # ctx+0x40
        self.done = False
        self.steps = 0
        self.trace: list[str] = []
        self.rand_seed = 0x12345

    # ---- 变量 ----
    def read(self, o: Operand) -> int:
        if o.kind != "var":
            return o.value
        if o.is_global:
            if o.value in self.globals:
                return self.globals[o.value]
            return self.img.read_var(o.value, o.size)
        return self.locals.get(o.value, 0)

    def write(self, o: Operand, v: int) -> None:
        v &= (1 << (8 * o.size)) - 1 if o.size in (1, 2) else 0xFFFFFFFF
        if o.kind != "var":
            return
        if o.is_global:
            self.globals[o.value] = v
        else:
            self.locals[o.value] = v

    def local(self, off: int) -> int:
        return self.locals.get(off, 0)

    def set_local(self, off: int, v: int) -> None:
        self.locals[off] = v & 0xFFFFFFFF

    # ---- 控制流辅助 ----
    def cur(self) -> Cmd:
        return self.cmds[self.pc]

    def next_pc(self) -> int:
        return self.pc + 1

    def addr_of(self, i: int) -> int:
        return self.cmds[i].addr if i < len(self.cmds) else self.cmds[-1].addr + self.cmds[-1].size

    def index_of(self, addr: int) -> int:
        if addr in self.by_addr:
            return self.by_addr[addr]
        # 跳到块外一条 (end 地址 = 脚本末尾之后)
        return len(self.cmds)

    def match_end(self, start: int, op_open: int, op_close: int) -> int:
        """FUN_00467e54: 从 start 起找配对的 op_close, 返回其下标."""
        depth = 0
        i = start
        while i < len(self.cmds):
            c = self.cmds[i]
            if c.op == op_open:
                depth += 1
            elif c.op == op_close:
                if depth == 0:
                    return i
                depth -= 1
            i += 1
        return len(self.cmds) - 1

    def jump_addr(self, addr: int) -> None:
        self.pc = self.index_of(addr)

    # ---- 主循环 ----
    def tick(self, max_steps: int = 2000) -> bool:
        """跑一帧; 返回 是否已结束."""
        if self.done:
            return True
        steps = 0
        while not self.done and steps < max_steps:
            if self.pc >= len(self.cmds):
                self.done = True
                break
            cmd = self.cur()
            before = self.pc
            yield_ = self.exec(cmd)
            steps += 1
            self.steps += 1
            if yield_:
                return self.done
            if self.pc == before and not yield_:
                # 处理函数没推进 pc 也没要求等 → 死循环保护
                self.pc += 1
        return self.done

    def run_to_end(self, max_ticks: int = 100000) -> None:
        for _ in range(max_ticks):
            if self.tick():
                return

    def fc(self, v: int) -> int:
        """操作数 → FC id: -1 = 本任务默认角色."""
        return self.fc_default if v in (-1, 0xFFFFFFFF) else v

    def _walk_delay(self) -> int:
        return self.scheduler.walk_delay if self.scheduler is not None else 0

    def spawn_child(self, script_va: int, fc: int, locals_: dict[int, int] | None = None) -> int:
        if self.scheduler is None or script_va not in self.scripts:
            self.host.log(f"[ev] (no sub-script {script_va:#x})")
            return 0
        child = EventVM(self.img, self.scripts[script_va], self.host, self.globals,
                        name=f"{self.name}>{script_va:#x}", scripts=self.scripts, fc_default=fc,
                        scheduler=self.scheduler, entry=script_va)
        if locals_:
            child.locals.update(locals_)
        return self.scheduler.add(child)

    @property
    def mq(self) -> MessageQueue:
        if self.scheduler is not None:
            return self.scheduler.mq
        if not hasattr(self, "_mq"):
            self._mq = MessageQueue()
        return self._mq

    def _speak(self, fc: int, text: str, code: int) -> int:
        """起一个对白气泡 (FUN_0049ac7c): 返回句柄 (0x40000+n); 无调度器时只通知 host."""
        sch = self.scheduler
        facing = self.host.fc_get(fc, 0x110) if fc not in (-1, 0xFFFFFFFF) else 1
        if sch is None:
            dlg = DialogTask(text, fc, code, self.mq, self.host, facing=facing)
            self.host.speak(dlg)
            return 0
        dlg = DialogTask(text, fc, code, sch.mq, self.host, facing=facing,
                         auto_delay_ms=sch.auto_dialog * 100, speed_ms=sch.text_speed)
        hd = sch.add_dialog(dlg)
        self.host.speak(dlg)
        return hd

    def _wait_handle(self, hd: int) -> bool:
        """句柄 (子任务 / 对白 / host 任务) 是否还活着."""
        if hd in (0, 0xFFFFFFFF):
            return False
        if self.scheduler is not None and (self.scheduler.alive(hd) or self.scheduler.dialog_alive(hd)):
            return True
        return self.host.task_alive(hd)

    def _ret(self) -> bool:
        """子程序返回 (op 00 在调用栈非空时). 返回 False = 没有可返回的帧."""
        if not self.calls:
            return False
        fr = self.calls.pop()
        if fr.saved is not None:
            self.blocks[:] = fr.saved[:fr.nblocks]
        else:
            del self.blocks[fr.nblocks:]
        self.pc = self.index_of(fr.ret)
        return True

    def _switch_map(self, map_id: int, reload: bool) -> None:
        """e0 / e1: 已在该图上就不重载 (FUN_00494688 的 local_30 != DAT_00654d98 判断; e0 同理)."""
        if self.globals.get(G_MAP_NOW, -1) == map_id:
            return
        if self.scheduler is not None:
            self.scheduler.kill_children()
            self.scheduler.path_state.clear()
        self.globals[G_MAP_NOW] = map_id
        self.host.switch_map(map_id, reload)
        # FUN_004c90c3 末尾的 FUN_004b895c: 当前主角对象 flags |= 0x100c0 → 载图后队长一定可见
        # (前一事件走进门后 4a.00 把她隐藏, 新图靠这里重新显示)
        leader = self.globals.get(G_PARTY_LEADER, -1)
        if leader != -1:
            self.host.fc_show(leader, True)

    def _wait_or_store(self, mode: int, hd: int, o0) -> bool:
        """44/46/47 类 (FUN_0047a959 尾部): 第 0 操作数是**变量**就把任务句柄写进去 (不看它现在的值 ——
        02.03 等完会把它清 0, 下次再用同一变量时值是 0, 不能当成 mode 0);
        是立即数才按 mode: -1 不管; 0 → 0xd0; 1 → 0xcc (下次同类 mode 1 指令先等它)."""
        if o0 is not None and o0.kind == "var":
            self.write(o0, hd)
        elif mode == 0:
            self.set_local(0xD0, hd)
        elif mode == 1:
            self.set_local(0xCC, hd)
        return False

    # ---- 指令 ----
    def exec(self, c: Cmd) -> bool:
        """执行一条; 返回 True 表示本帧到此为止 (下帧再来, pc 由指令自己决定是否推进)."""
        h = self.host
        o = c.operands
        op, sub = c.op, c.sub
        R = self.read
        advance = True
        wait = False

        if op == 0x00:                                   # 块尾 / 子程序返回 / 任务结束
            if sub in (1, 2) and len(o) >= 3 and calc(R(o[1]), R(o[0]), R(o[2])) == 0:
                self.pc += 1
                return False
            if self._ret():
                return False
            if self.blocks:
                while self.blocks:
                    b = self.blocks.pop()
                    if b.head == 0 and b.end:
                        self.jump_addr(b.end)
                        return False
                self.pc += 1
                return False
            self.done = True
            return True
        if op == 0x01:                                   # 让出一帧
            self.pc += 1
            return True
        if op == 0x02:                                   # 等待
            if sub == 0:
                if self.wait == 0:
                    self.wait = R(o[0]) if o else 0
                    if self.wait == 0:
                        self.pc += 1
                        return False
                if fast_forward():                       # Shift: ctx+0x40 = 1 (FUN_00467cbc 分支)
                    self.wait = 1
                self.wait -= 1
                if self.wait == 0:
                    self.pc += 1
                return True
            if sub == 1:                                 # 等到变量 == 0
                if R(o[0]) == 0:
                    self.pc += 1
                return True
            if sub == 2:                                 # 等按键 (Shift 视为已按, FUN_00457173)
                if h.key_pressed() or fast_forward():
                    self.pc += 1
                return True
            if sub in (3, 4):                            # 等句柄对象 (子任务 / 对白框) 消失
                hd = R(o[0]) if o else 0
                if not self._wait_handle(hd):
                    if sub == 3 and o:
                        self.write(o[0], 0)
                    self.pc += 1
                return True
            if sub == 5:                                 # 等 ctx+0xdc 的任务 (4f.15 起的) 结束; 至少让一帧
                if self.wait == 0:
                    self.wait = 1
                    return True
                if not self._wait_handle(self.local(0xDC)):
                    self.set_local(0xDC, 0)
                    self.wait = 0
                    self.pc += 1
                return True
            self.pc += 1
            return True
        if op == 0x03:                                   # 跳转
            if self.blocks and self.blocks[-1].end == 0:
                self.blocks.pop()
            self.jump_addr(R(o[0]))
            return False
        if op == 0x04:                                   # 条件跳转: 04.00 [ptr,a,op,b] 真跳; 04.01 [ptr,var] 零跳
            if sub == 0 and len(o) >= 4:
                go = calc(R(o[2]), R(o[1]), R(o[3])) != 0
            elif sub == 1 and len(o) >= 2:
                go = R(o[1]) == 0
            else:
                go = False
            if go:
                if self.blocks and self.blocks[-1].end == 0:
                    self.blocks.pop()
                self.jump_addr(R(o[0]))
            else:
                self.pc += 1
            return False
        if op == 0x07:                                   # gosub ptr
            self.calls.append(Frame(self.addr_of(self.pc + 1), len(self.blocks), saved=list(self.blocks)))
            self.jump_addr(R(o[0]))
            return False
        if op == 0x08:                                   # 调 ptr 共 n 次 (每次返回到本指令)
            fr = self.calls[-1] if self.calls and self.calls[-1].cmd == c.addr else None
            if fr is None:
                n = R(o[1]) if len(o) > 1 else 0
                if n <= 0:
                    self.pc += 1
                    return False
                fr = Frame(c.addr, len(self.blocks), count=n, cmd=c.addr, saved=list(self.blocks))
                self.calls.append(fr)
            if fr.count <= 0:
                self.calls.pop()
                self.pc += 1
                return False
            fr.count -= 1
            self.calls.append(Frame(c.addr, len(self.blocks)))
            self.jump_addr(R(o[0]))
            return False
        if op == 0x0F:                                   # break (0f.01/02 条件)
            if sub in (1, 2) and len(o) >= 3 and calc(R(o[1]), R(o[0]), R(o[2])) == 0:
                self.pc += 1
                return False
            while self.blocks:
                b = self.blocks.pop()
                if b.end:
                    self.pc = self.index_of(b.end)
                    return False
            self.pc += 1
            return False
        if op == 0x14:                                   # 循环计数读出
            b = next((bb for bb in reversed(self.blocks) if bb.counter), None)
            if o:
                cnt = b.counter if b else 0
                self.write(o[0], cnt if sub == 0 else (R(o[1]) - cnt if len(o) > 1 else 0))
            self.pc += 1
            return False
        if op == 0x05:                                   # switch
            cnt, idx = R(o[0]), signed(R(o[1]))
            tgt = c.table[idx] if 0 <= idx < len(c.table) else None
            if sub == 0:
                if tgt is None:
                    self.pc += 1
                else:
                    if self.blocks and self.blocks[-1].end == 0:
                        self.blocks.pop()
                    self.jump_addr(tgt)
                return False
            if tgt is not None:
                self.set_local(0xE8, tgt)
                if sub == 2 and idx + 1 < len(c.table):
                    self.set_local(0xEC, c.table[idx + 1])
            self.pc += 1
            return False
        if op == 0x06:                                   # switch-call: gosub 表[idx] (FUN_0046a140; 跑/跳脚本按朝向分派)
            cnt, idx = R(o[0]), signed(R(o[1]))
            tgt = c.table[idx] if 0 <= idx < len(c.table) else None
            if tgt is None:
                self.pc += 1
                return False
            self.calls.append(Frame(self.addr_of(self.pc + 1), len(self.blocks), saved=list(self.blocks)))
            self.jump_addr(tgt)
            return False
        if op == 0x0B:                                   # repeat N { ... } (0b..0c)
            n = R(o[0]) if o else 0
            end_i = self.match_end(self.pc + 1, 0x0B, 0x0C)
            if n == 0:
                self.pc = end_i + 1
                return False
            self.blocks.append(Block(head=self.addr_of(self.pc + 1), end=self.addr_of(end_i), counter=n, flag=1))
            self.pc += 1
            return False
        if op == 0x0C:
            if self.blocks:
                b = self.blocks[-1]
                b.counter -= 1
                if b.counter > 0:
                    self.jump_addr(b.head)
                    return True          # 原版每圈让一帧
                self.blocks.pop()
            self.pc += 1
            return False
        if op == 0x0D:                                   # while (cond) { ... } (0d..0e)
            if sub == 0 and len(o) >= 3:
                cond = calc(R(o[1]), R(o[0]), R(o[2]))
            else:
                cond = 1
            in_block = bool(self.blocks) and self.blocks[-1].head == c.addr
            end_i = self.match_end(self.pc + 1, 0x0D, 0x0E)
            if cond == 0:
                if in_block:
                    self.blocks.pop()
                self.pc = end_i + 1
                return False
            if not in_block:
                self.blocks.append(Block(head=c.addr, end=self.addr_of(end_i + 1), flag=1))
            self.pc += 1
            return False
        if op == 0x0E:
            if self.blocks and self.blocks[-1].end == self.addr_of(self.pc + 1):
                self.jump_addr(self.blocks[-1].head)
                return True
            self.pc += 1
            return False
        if op in (0x10, 0x11):                           # if / elif / else (10..11..12)
            if op == 0x11:
                if not self.blocks:
                    self.pc += 1
                    return False
                b = self.blocks[-1]
                if b.taken:
                    self.pc = self.match_end(self.pc + 1, 0x10, 0x12)
                    return False
            else:
                self.blocks.append(Block(head=0, end=0, flag=0))
                b = self.blocks[-1]
            if sub == 0:
                cond = R(o[0]) if o else 0
            elif sub == 1:
                cond = calc(R(o[1]), R(o[0]), R(o[2]))
            elif sub == 2:
                cond = int(calc(R(o[1]), R(o[0]), R(o[2])) == 0)
            else:
                cond = 1
            if cond:
                b.taken = 1
                self.pc += 1
                return False
            # 跳到下一个 11 或 12 (同层)
            i = self.pc + 1
            depth = 0
            while i < len(self.cmds):
                cc = self.cmds[i]
                if cc.op == 0x10:
                    depth += 1
                elif cc.op == 0x12:
                    if depth == 0:
                        break
                    depth -= 1
                elif cc.op == 0x11 and depth == 0:
                    break
                i += 1
            self.pc = i
            return False
        if op == 0x12:
            if self.blocks and self.blocks[-1].end == 0 and self.blocks[-1].head == 0:
                self.blocks.pop()
            self.pc += 1
            return False
        if op == 0x19:                                   # rand
            if sub == 0:
                self.rand_seed = (self.rand_seed * 0x41C64E6D + 0x3039) & 0xFFFFFFFF
                n = R(o[0]) if o else 1
                self.set_local(0x44, self.rand_seed % n if n else 0)
            elif sub == 1 and o:
                self.rand_seed = R(o[0]) or 1
            self.pc += 1
            return False
        if op == 0x1F:                                   # 原生函数调用
            fn = R(o[0]) if o else 0
            h.native(fn, [R(x) for x in o[1:]])
            self.pc += 1
            return False
        if op == 0x2C:                                   # var = value
            if len(o) >= 2:
                self.write(o[0], R(o[1]))
            self.pc += 1
            return False
        if op == 0x28:                                   # 一元
            if o:
                v = R(o[0])
                self.write(o[0], {1: ~v, 2: v + 1, 3: v - 1}.get(sub, -v if sub == 0 else v))
            self.pc += 1
            return False
        if op == 0x29:                                   # var op= value
            if len(o) >= 2:
                a, b = signed(R(o[0])), signed(R(o[1]))
                r = {0: a + b, 1: a - b, 2: a * b, 3: int(a / b) if b else 0, 4: (a % b) if b else 0,
                     8: a << (b & 31), 9: a >> (b & 31)}.get(sub, a)
                self.write(o[0], r)
            self.pc += 1
            return False
        if op == 0x2D:                                   # var = a <op> b
            if sub == 1 and len(o) >= 4:
                self.write(o[0], calc(R(o[2]), R(o[1]), R(o[3])))
            elif sub == 0 and len(o) >= 3:
                self.write(o[0], calc(R(o[1]), R(o[0]), R(o[2])))
            self.pc += 1
            return False
        if op == 0x91:                                   # 事件标志表 DAT_007d72e8
            base = EVENT_FLAGS_VA
            if sub == 0 and o:
                self.set_local(0x44, self.globals.get(base + 4 * R(o[0]), self.img.u32(base + 4 * R(o[0]))))
            elif sub == 1 and len(o) >= 2:
                self.globals[base + 4 * R(o[0])] = R(o[1])
            self.pc += 1
            return False
        if op == 0x4B:                                   # 剧本表 0x54eadc 字段读写
            if sub == 0 and o:
                self.set_local(0x44, self.img.u32(0x54EADC + R(o[0]) * 0x44))
            self.pc += 1
            return False

        # ---------------- 世界副作用 ----------------
        if op == 0xE0 and sub == 0:                      # 换图 (同图不重载): 旧图上的对象任务全部作废
            self._switch_map(R(o[0]), False)
        elif op == 0xE1:
            if sub == 0 and o:
                self.write(o[0], self.globals.get(G_MAP_NOW, 0))
            elif sub in (1, 2) and o:
                self._switch_map(R(o[0]), True)
        elif op == 0x90:                                 # 画面框 (FUN_0048cb40)
            if sub in (6, 7) and len(o) >= 2:                # 6 = 30 帧渐变到 [w,h], 7 = 立刻 (FUN_0049bfd5)
                h.viewport(R(o[0]), R(o[1]))
            elif sub == 5:                                   # FUN_0040e271(800, 0x1c2): 800x450 宽银幕
                h.viewport(800, 450)
            elif sub == 4:                                   # FUN_0049bf9c: 30 帧渐变回 800x450 (DAT_0053ca38)
                h.viewport(800, 450)
            # 0/1/2/3 (FUN_0049bf31/be56: 640x480 的普通地图框, 战斗/切图相关) 先不管
        elif op == 0xB1:                                 # 镜头 [mode, frames, x|fc, y]
            mode = signed(R(o[0])) if o else -1
            if mode == 1 and self.local(0xCC) == 0xCA:        # 上一条 mode 1 的镜头还在跑 → 先等它
                if h.camera_busy():
                    return True
                self.set_local(0xCC, 0)
            frames = signed(R(o[1])) if len(o) > 1 else 0
            if sub == 0:
                h.camera(None, None, frames, False, follow=R(o[2]) if len(o) > 2 else -1)
            else:
                x = signed(R(o[2])) if len(o) > 2 else 0
                y = signed(R(o[3])) if len(o) > 3 else 0
                h.camera(x, y, frames, sub in (2, 6))
            if mode == 1:
                self.set_local(0xCC, 0xCA)
        elif op == 0x42:
            fc = self.fc(R(o[0]))
            h.fc_place(fc, signed(R(o[2])), signed(R(o[3])), signed(R(o[1])), signed(R(o[4])) if len(o) > 4 else 0)
            if sub == 1:
                h.fc_show(fc, True)
        elif op == 0x4A:
            fc = self.fc(R(o[0])) if o else self.fc_default
            if sub == 0:
                h.fc_show(fc, False)
            elif sub == 1:
                h.fc_show(fc, True)
            elif sub == 2:
                h.fc_show(fc, True)
                d = signed(R(o[1])) if len(o) > 1 else -1
                if d != -1:
                    h.fc_dir(fc, d)
            elif sub == 9 and len(o) > 1:                   # obj+0x130 = 图集基号 (序章 4a.09 [SON, 8] = 无头盔 CSON000)
                h.fc_set(fc, 0x130, R(o[1]))
            elif sub == 8:                                   # 0x44 = obj+0x130
                self.set_local(0x44, h.fc_get(fc, 0x130))
            elif sub in (4, 5, 0x14, 0x15):
                pass                                        # 激活/碰撞标志, 演出里无关
            else:
                h.unknown(c)
        elif op == 0x4F:
            if sub in (8, 9):                               # 说话: 子任务 (说话脚本) + 气泡
                fc = self.fc(R(o[0]))
                code = R(o[2]) if len(o) > 2 else 0
                script = TALK_SCRIPT_VA if sub == 9 else R(o[1])
                if self.scheduler is not None:
                    self.scheduler.kill_fc(fc, talk_only=True)
                    self.scheduler.fc_codes[code] = fc
                self.spawn_child(script, fc, {0xF4: code})
                if sub == 9 and c.text:
                    self.set_local(0xD8, self._speak(fc, c.text, code))
            elif sub in (0x15, 0x16) and o:                 # 默认 FC 起行为脚本 (指针在变量里)
                hd = self.spawn_child(R(o[0]), self.fc_default)
                self.set_local(0xDC if sub == 0x15 else 0xD0, hd)
            elif sub in (0, 4) and len(o) >= 3:            # 给 FC 挂一个行为子任务 (脚本在 ptr)
                fc = self.fc(R(o[1]))
                hd = self.spawn_child(R(o[2]), fc)
                flag = R(o[0]) if o[0].kind != "var" else None
                if o[0].kind == "var":
                    self.write(o[0], hd)
                elif flag == 0:
                    self.set_local(0xD0, hd)
                elif flag == 1:
                    self.set_local(0xCC, hd)
            elif sub in (0x0A, 0x0B):                       # 结束 FC 的说话脚本 (0b 连气泡一起)
                if self.scheduler is not None:
                    self.scheduler.kill_fc(self.fc(R(o[0])), talk_only=True, dialogs=(sub == 0x0B))
            elif sub in (0x14, 0x15, 0x16, 0x17):
                pass                                        # 对白窗对象管理, 由 UI 自己处理
            else:
                h.unknown(c)
        elif op == 0x88:
            if sub == 0:
                code = R(o[2]) if len(o) > 2 else 0
                self.set_local(0xD8, self._speak(self.fc(R(o[0])), c.text or "", code))
            elif sub == 4:                                  # 等所有气泡关闭
                if (self.scheduler is not None and self.scheduler.any_dialog()) or h.wait_dialog():
                    return True
        elif op == 0x58:                                 # 对象: 00 [var, 图集基号, z, x, y, 向] / 02 [var, FC 定义号, z, x, y, 向]
            if sub == 0 and len(o) >= 6:
                hd = h.fc_spawn(-1, signed(R(o[3])), signed(R(o[4])), signed(R(o[2])), signed(R(o[5])), base=R(o[1]))
                self.write(o[0], hd)
            elif sub == 1 and o:
                if self.scheduler is not None:
                    self.scheduler.kill_fc(R(o[0]), dialogs=True)
                h.fc_destroy(R(o[0]))
                self.write(o[0], 0)
            elif sub == 2 and len(o) >= 6:
                hd = h.fc_spawn(R(o[1]), signed(R(o[3])), signed(R(o[4])), signed(R(o[2])), signed(R(o[5])))
                self.write(o[0], hd)
        elif op == 0x5C and o:
            if self.scheduler is not None:
                self.scheduler.kill_fc(R(o[0]), dialogs=True)
            h.fc_destroy(R(o[0]))
        elif op == 0x61:                                 # 默认 FC 动作 + 等 N 帧
            if self.wait == 0:
                n = R(o[0]) if o else 0
                mode = {0: 0, 1: 0x10000, 2: 0x20000, 3: 0x30000, 4: 0}.get(sub, 0)
                h.fc_anim(self.fc_default, mode | (R(o[1]) if len(o) > 1 else 0), R(o[2]) if len(o) > 2 else 0, n)
                if n <= 0:
                    self.pc += 1
                    return False
                self.wait = n + self.local(0x108) + self._walk_delay()   # FUN_00484ba5/004871c1
            if fast_forward():
                self.wait = 1
            self.wait -= 1
            if self.wait == 0:
                self.pc += 1
            return True
        elif op == 0x62 and len(o) >= 3:
            mode = {0: 0, 1: 0, 3: 0x20000}.get(sub, 0)   # sub0/1 都是 fm 动画组 (实测 62.01 [樂神, 26])
            h.fc_anim(self.fc(R(o[0])), mode | R(o[1]), R(o[2]), 0)
        elif op == 0x67:                                 # 移动 (像素) + 等 N 帧
            if self.wait == 0:
                n = R(o[0]) if o else 0
                if sub == 0 and len(o) >= 3:                 # 偏移目标 (+0x20) += (dx,dy) px, n 帧内滑到
                    h.fc_move(self.fc_default, signed(R(o[1])), signed(R(o[2])), n, False)
                elif sub == 1 and len(o) >= 3:               # 位置 += (dx,dy) px —— 仅当 40.00 判定能走
                    if (self.local(0x104) & 1) == 0:         # (FUN_004871c1 case 1: 挡住就原地踏步)
                        h.fc_move(self.fc_default, signed(R(o[1])), signed(R(o[2])), 0, True)
                elif sub == 2 and len(o) >= 3:               # 位置 += (dx,dy) 16.16 px
                    h.fc_move(self.fc_default, signed(R(o[1])) / 65536.0, signed(R(o[2])) / 65536.0, 0, True)
                elif sub == 8 and len(o) >= 4:
                    h.fc_move(self.fc(R(o[1])), signed(R(o[2])), signed(R(o[3])), 0, True)
                if n <= 0 or fast_forward():
                    # Shift: FUN_004871c1 直接清等待并推进, **不置让帧标志** → 同帧继续执行下一条
                    # (走路脚本每组 3 个 67 + 1 个 61, 于是一格 24 帧变 8 帧 = 原版按住 Shift 的快走)
                    self.wait = 0
                    self.pc += 1
                    return False
                self.wait = n + self.local(0x108) + self._walk_delay()   # FUN_004871c1
            if fast_forward():
                self.wait = 1
            self.wait -= 1
            if self.wait == 0:
                self.pc += 1
            return True
        elif op == 0xC8:
            if sub == 0:
                h.sound(R(o[0]))
            elif sub == 1:
                h.sound_stop(R(o[0]))
            elif sub == 2:
                if h.wait_sound(R(o[0])):
                    return True
        elif op == 0xC1:
            if sub == 0:
                h.bgm(R(o[0]))
            elif sub in (1, 3):
                h.bgm(None)
            elif sub == 2:
                h.bgm(R(o[0]))
            elif sub == 4:
                h.bgm(R(o[0]), R(o[1]) if len(o) > 1 else 0)
        elif op == 0xC2:
            if sub == 0 and len(o) >= 2:
                h.bgm_volume(R(o[0]), R(o[1]))
            elif sub == 1:
                h.bgm_volume(0, R(o[0]) if o else 0)
            elif sub == 2:
                h.bgm(None)
        elif op == 0xEC:
            if h.wait_fade():
                return True
        elif op == 0xED:                                 # 调色板 (FUN_00497711)
            # 00 把场景调色板 0x868ac0 送硬件 (画面正常) / 01 工作板 0x743b58 ← 场景板 / 02 场景板 ← 工作板 /
            # 03 场景板 ← 硬件 / 04 送黑板 0x53c290 (全黑) / 05 送白板 0x5403d4 / 08 [a, b] 工作板 = 场景板×a% + b
            # (不送硬件; 之后由 1f.00 [FUN_0040a342, 板, 起, 数] 送) / 0a 取硬件部分项
            kind = {0: "apply", 1: "store", 2: "restore", 3: "clear", 4: "black", 5: "white",
                    8: "blend", 10: "tint"}.get(sub, f"ed.{sub:02x}")
            h.palette(kind, *[signed(R(x)) for x in o[:2]])
        elif op == 0xEE:                                 # 调色板渐变 (FUN_0040b0c5/0040b169)
            # 0/3 → 黑 (0x53c290), 1/4 → 白 (0x5403d4), 2/5 → 白(0 号留黑), 0x10/0x11 → 场景调色板.
            # 0/1/2/0x10: 操作数 = 速度 → 线性插值 steps (负数 = 帧数, 正数 ×3/50, 至少 1), 共 steps+1 帧
            # 3/4/5/0x11: 操作数 = 每帧每通道步进量 (level), 到位为止
            if sub in (0x20, 0x21):
                if self.wait == 0:
                    if sub == 0x20:
                        h.fade("white", 0, step=0x28)
                    else:
                        h.fade("scene", 13)
                    self.wait = 1
                if h.wait_fade():
                    return True
                self.wait = 0
            else:
                v = signed(R(o[0])) if o else 0
                target = {0: "black", 3: "black", 1: "white", 4: "white", 2: "white", 5: "white",
                          0x10: "scene", 0x11: "scene"}.get(sub, "scene")
                if sub in (0, 1, 2, 0x10):
                    steps = -v if v < 0 else max(1, v * 3 // 50)
                    h.fade(target, steps + 1)
                else:
                    h.fade(target, 0, step=max(1, v))
        elif op == 0x92:                                 # 事件开始/结束 (wh/seq.cpp 0xad0 附近)
            if sub == 0:
                self.globals[G_EVENT_NOW] = self.event_id & 0xFFFFFFFF
                self.globals[G_EVENT_NEXT] = 0xFFFFFFFF
                self.globals[G_EVENT_DEFER] = 0xFFFFFFFF
                h.event_begin()
            elif sub == 1:                               # 事件结束: 清掉所有气泡/说话脚本/消息环 (DAT_007d7038=1, FUN_004071a6)
                self.globals[G_EVENT_PREV] = self.globals.get(G_EVENT_NOW, 0xFFFFFFFF)
                self.globals[G_EVENT_NOW] = 0xFFFFFFFF
                if self.scheduler is not None:
                    self.scheduler.kill_all_dialogs()
                    self.scheduler.mq.clear()
                    self.scheduler.kill_talk_tasks()
                self.done = True
                h.event_end()
                return True
            elif sub in (2, 3):
                # 2: 本事件结束后立刻重跑自己 (0x613068); 3: 下次触发检查时重跑 (0x61306c);
                # 两者都把事件标志 DAT_007d72e8[ev] +1, 事件开头 91.00 读它再 switch 选阶段
                ev = self.globals.get(G_EVENT_NOW, 0xFFFFFFFF)
                self.globals[G_EVENT_NEXT if sub == 2 else G_EVENT_DEFER] = ev
                if ev != 0xFFFFFFFF:
                    fa = EVENT_FLAGS_VA + 4 * ev
                    self.globals[fa] = (self.globals.get(fa, self.img.u32(fa)) + 1) & 0xFFFFFFFF
            elif sub == 4 and o:
                v = R(o[0])
                h.caption(self.img.cstr(v) if self.img.in_range(v) else str(v))
            elif sub == 5:
                h.caption(None)
        elif op == 0xE8:                                 # 队伍 (FUN_00496912)
            if sub == 0:                                     # FUN_00499395: 保证该 FC 有对象 (入队, 不显示)
                h.party("add", R(o[0]))
            elif sub == 8:                                   # FUN_004998d3(mask, 1): 按位掩码重设队伍
                mask = R(o[0])
                members = [PARTY_SLOT_FC[i] for i in range(10) if mask >> i & 1]
                self.globals[G_PARTY_MASK] = mask
                for fc in members:
                    h.party("add", fc)
                if members:
                    leader = self.globals.get(G_PARTY_LEADER, -1)
                    if leader not in members:                # 原队长被踢 → 第一个成员接任 (FUN_004994d9)
                        leader = members[0]
                    self.globals[G_PARTY_LEADER] = leader
                    h.party("leader", leader)
                    h.fc_show(leader, True)                  # 末尾 FUN_00498daa(leader, 1)
            elif sub == 9:                                   # FUN_004998d3(mask, 0): 只补人不踢人
                mask = R(o[0])
                for fc in [PARTY_SLOT_FC[i] for i in range(10) if mask >> i & 1]:
                    h.party("add", fc)
            elif sub == 1 and o:                             # 当前主角 (队长) 的 FC 号写进变量 (FUN_004b9a41)
                self.write(o[0], self.globals.get(G_PARTY_LEADER, -1) & 0xFFFFFFFF)
            elif sub == 0x10:                                # FUN_00499c8e: 隐藏全部队员 (之后脚本用 42.01 逐个摆出来)
                mask = self.globals.get(G_PARTY_MASK, 0)
                for fc in [PARTY_SLOT_FC[i] for i in range(10) if mask >> i & 1]:
                    h.fc_show(fc, False)
            elif sub == 2:                                   # FUN_004994d9: 换队长 (新队长一定显示)
                fc = R(o[0])
                self.globals[G_PARTY_LEADER] = fc
                h.party("leader", fc)
                h.fc_show(fc, True)
        elif op == 0x81 and o:                           # 销毁句柄 (子任务 / 窗口)
            if self.scheduler is not None:
                self.scheduler.kill(R(o[0]))
            self.write(o[0], 0)
        elif op == 0x20:                                 # 内存/对象字段读写
            if sub == 0 and o:
                self.set_local(0x44, self.img.u32(R(o[0])) if hasattr(self.img, "u32") else 0)
            elif sub == 1 and len(o) >= 2:
                self.globals[R(o[0])] = R(o[1])
            elif sub == 2 and len(o) >= 2:                   # 0x44 = ptr[idx] (表读)
                self.set_local(0x44, self.img.u32(R(o[0]) + 4 * R(o[1])))
            elif sub == 4 and len(o) >= 2:                   # 0x44 = obj.field
                self.set_local(0x44, h.fc_get(self.fc_default if R(o[0]) in (0, 0xFFFFFFFF) or o[0].value == 0xFC
                                              else R(o[0]), R(o[1])))
            elif sub == 5 and len(o) >= 3:                   # obj.field = v
                fc = self.fc_default if o[0].kind == "var" and o[0].value == 0xFC else R(o[0])
                h.fc_set(fc, R(o[1]), R(o[2]))
            elif sub == 0x10 and len(o) >= 3:                # 子任务局部变量写
                if self.scheduler is not None:
                    vm = self.scheduler.tasks.get(R(o[0]))
                    if vm is not None:
                        vm.set_local(R(o[1]), R(o[2]))
        elif op == 0x25 and sub == 0 and len(o) >= 5:    # 对象位置/偏移直接设 (16.16 像素)
            mask = R(o[1])
            vals = [signed(R(o[2])) / 65536.0, signed(R(o[3])) / 65536.0, signed(R(o[4])) / 65536.0]
            h.fc_offset(self.fc(R(o[0])), mask & 0xF00, *(vals[i] if mask & (1 << i) else None for i in range(3)))
        elif op == 0x26 and len(o) >= 2:                 # 对象字段组 ↔ 局部变量组
            mask = R(o[1])
            lbase = {0x10: 0x11C, 0x20: 0x140, 0x40: 0x134, 0x80: 0x128}.get(mask & 0xF0)
            grp = mask & 0xF00
            fc = self.fc(R(o[0]))
            if lbase is not None and grp:
                for i in range(3):
                    if mask & (1 << i):
                        if sub == 1:
                            self.set_local(lbase + 4 * i, h.fc_get(fc, grp + 4 * i))
                        else:
                            h.fc_set(fc, grp + 4 * i, signed(self.local(lbase + 4 * i)))
        elif op == 0x27:                                 # 物理: 27.01 正弦摆, 27.00 弹簧
            mask = R(o[0]) if o else 0
            if sub == 1:
                base = 0x140 if mask & 8 else None
                for i, (ph, amp, fn) in enumerate(((0x14C, 0x158, math.cos), (0x150, 0x15C, math.sin), (0x154, 0x160, math.sin))):
                    if mask & (1 << i):
                        ang = self.local(ph) * 2 * math.pi / 65536.0
                        v = int(fn(ang) * signed(self.local(amp)) * 65536)
                        cur = signed(self.local(base + 4 * i)) if base is not None else signed(self.local(0x11C + 4 * i))
                        self.set_local(0x11C + 4 * i, cur + (-v if i == 1 else v))
            else:
                for i in range(3):
                    if mask & (1 << i):
                        pos, tgt, acc, vel = 0x11C + 4 * i, 0x140 + 4 * i, 0x128 + 4 * i, 0x134 + 4 * i
                        a = signed(self.local(acc))
                        v = signed(self.local(vel)) + (a if signed(self.local(pos)) < signed(self.local(tgt)) else -a)
                        self.set_local(vel, v)
                        self.set_local(pos, signed(self.local(pos)) + v)
        elif op == 0x40:                                 # 40.00/01: 试走一步 → ctx+0x104 = 通行码 ^ 1
            d = R(o[0]) if sub == 1 and o else h.fc_get(self.fc_default, 0x114)
            self.set_local(0x104, h.fc_step(self.fc_default, d) ^ 1)
        elif op == 0x41:                                 # 走完一步: 坡道升降层
            code = self.local(0x104)
            if (code & 1) == 0 and code & 0xC:
                h.fc_layer(self.fc_default, 1 if (code & 0xC) == 4 else -1)
        elif op == 0x44 and len(o) >= 3:                 # 转向 (00 同步 / 01 异步)
            if sub == 0 and self.local(0xCC) and self._wait_handle(self.local(0xCC)):
                return True
            if sub == 0 and self.local(0xCC):
                self.set_local(0xCC, 0)
            else:
                fc = self.fc(R(o[0]))
                hd = self._turn(fc, R(o[1]), R(o[2]))
                if sub == 0:
                    if self._wait_handle(hd):
                        self.set_local(0xCC, hd)
                        return True
                else:
                    self.set_local(0xD0, hd)
        elif op == 0x45 and len(o) >= 3:                 # 走路 (奇数 sub 同步)
            if (sub & 1) and self.local(0xCC):
                if self._wait_handle(self.local(0xCC)):
                    return True
                self.set_local(0xCC, 0)
            else:
                fc = self.fc(R(o[0]))
                d, n = R(o[1]), R(o[2])
                if sub in (0, 1):
                    hd = self._walk(fc, d, n, 0)
                elif sub in (4, 5):
                    hd = self._walk(fc, d, n, 1)
                else:
                    h.fc_dir(fc, d)
                    hd = self.spawn_child(HOP_SCRIPT_VA if sub in (2, 3) else HOP2_SCRIPT_VA, fc, {0xE8: n})
                if sub & 1:
                    if self._wait_handle(hd):
                        self.set_local(0xCC, hd)
                        return True
                else:
                    self.set_local(0xD0, hd)
        elif op == 0x46 and len(o) >= 2:                 # 寻路走到 (x,y)
            mode = signed(R(o[0]))
            if mode == 1 and self.local(0xCC):
                if self._wait_handle(self.local(0xCC)):
                    return True
                self.set_local(0xCC, 0)
            else:
                fc = self.fc(R(o[1]))
                x = signed(R(o[2])) if len(o) > 2 else 0
                y = signed(R(o[3])) if len(o) > 3 else 0
                d = signed(R(o[4])) if len(o) > 4 else -1          # 到达后朝向 (FUN_0049932a 第 5 参)
                if sub in (4, 5, 6, 7, 9):
                    x += h.fc_get(fc, 0x128)
                    y += h.fc_get(fc, 0x12C)
                kind = {0: 0, 4: 0, 1: 1, 5: 1, 2: 0, 6: 0, 3: 1, 7: 1, 8: 0, 9: 0, 10: 0}.get(sub, 0)
                steps = list(h.fc_path(fc, x, y, d))
                if not steps or self.scheduler is None:
                    h.fc_place(fc, x, y, -1, d)                  # 原版: 没路就瞬移过去
                    hd = 0
                else:
                    self.scheduler.path_state[fc] = [steps, 0]
                    hd = self.spawn_child(WALKER1_SCRIPT_VA if kind == 1 else WALKER_SCRIPT_VA, fc,
                                          {0x19C: 1 if sub == 10 else 0})
                self._wait_or_store(mode, hd, o[0])
                if mode == 1 and self._wait_handle(hd):
                    return True
        elif op == 0x47 and len(o) >= 2:                 # 跳 (抛物线) / 飞到像素点
            mode = signed(R(o[0]))
            if mode == 1 and self.local(0xCC):
                if self._wait_handle(self.local(0xCC)):
                    return True
                self.set_local(0xCC, 0)
            else:
                fc = self.fc(R(o[1]))
                a = [signed(R(x)) for x in o[2:]] + [0] * 5
                if sub in (8, 9):
                    px, py = a[0] * 64 + 32, a[1] * 48 + 24
                    if sub == 9:
                        px, py = h.fc_get(fc, 0x128) * 64 + 32 + a[0] * 64, h.fc_get(fc, 0x12C) * 48 + 24 + a[1] * 48
                    hd = h.fc_fly(fc, px, py, a[2])
                else:
                    dx, dy = a[0], a[1]
                    if sub in (0, 4):
                        dx, dy = a[0] - h.fc_get(fc, 0x128), a[1] - h.fc_get(fc, 0x12C)
                    hd = h.fc_jump(fc, dx, dy, a[2], a[3], a[4], 1 if sub in (0, 1, 4, 5) else 0)
                self._wait_or_store(mode, hd, o[0])
                if mode == 1 and self._wait_handle(hd):
                    return True
        elif op == 0x50 and o:                           # 寻路: 取下一步 (0 = 走完)
            st = self.scheduler.path_state.setdefault(self.fc_default, [None, 0]) if self.scheduler else [None, 0]
            if st[0] is None:
                st[0] = []
            if st[1] < len(st[0]):
                self.write(o[0], st[0][st[1]])
            else:
                self.write(o[0], 0)
                st[0], st[1] = None, 0
        elif op == 0x51:
            if self.scheduler is not None:
                st = self.scheduler.path_state.setdefault(self.fc_default, [None, 0])
                st[1] += 1
        elif op == 0x5D:                                 # 对象: 00 空对象 / 04 复制
            if sub == 0 and o:
                self.write(o[0], h.fc_blank())
            elif sub == 4 and len(o) >= 2:
                self.write(o[0], h.fc_clone(self.fc(R(o[1]))))
        elif op == 0x60:
            if sub == 4:
                self.set_local(0x44, 0)
        elif op == 0x65:                                 # 子任务检查点: 00 计数+1 / 01 [hd, n] 等计数 ≥ n
            if sub == 0:
                self.set_local(0x100, self.local(0x100) + 1)
            elif sub == 1 and len(o) >= 2:
                vm = self.scheduler.tasks.get(R(o[0])) if self.scheduler else None
                if vm is not None and not vm.done and signed(vm.local(0x100)) < signed(R(o[1])):
                    return True
        elif op == 0x66:                                 # 朝向: 00 默认 FC 现向+目标向 / 01 目标向 / 02 [fc, d]
            if sub == 0 and o:
                h.fc_dir(self.fc_default, R(o[0]))
            elif sub == 1 and o:
                h.fc_set(self.fc_default, 0x114, R(o[0]))
            elif sub == 2 and len(o) >= 2:
                h.fc_dir(self.fc(R(o[0])), R(o[1]))
        elif op == 0x71:                                 # 文字/消息环
            if sub == 0 and len(o) >= 3:
                if not self.mq.take_match(R(o[0]), R(o[1]), R(o[2])):
                    return True
                self.set_local(0x10C, R(o[0])); self.set_local(0x110, R(o[1])); self.set_local(0x114, R(o[2]))
            elif sub == 1 and len(o) >= 2:                   # 等某气泡走到标签 L
                i = self.mq.find(R(o[0]), R(o[1]))
                if i < 0:
                    return True
                e = self.mq.take(i)
                self.set_local(0x10C, e[0]); self.set_local(0x110, e[1]); self.set_local(0x114, 0)
                self.pc += 1
                return True
            elif sub == 2 and len(o) >= 3:
                self.set_local(0x44, int(self.mq.take_match(R(o[0]), R(o[1]), R(o[2]))))
            elif sub == 3 and o:                             # 说话脚本: 等姿势号
                i = self.mq.find_cmd(R(o[0]))
                if i < 0:
                    return True
                e = self.mq.take(i)
                self.set_local(0x10C, e[0]); self.set_local(0x110, e[1]); self.set_local(0x114, e[2])
                self.set_local(0x118, e[3])
                self.set_local(0x44, e[2] & 0xFFFF7FFF)
            elif sub == 4 and len(o) >= 3:
                self.mq.post(R(o[1]), R(o[0]), R(o[2]), self.handle_id())
            elif sub == 5 and len(o) >= 2:
                self.mq.post(R(o[1]), R(o[0]), 0, self.handle_id())
            elif sub == 7 and len(o) >= 2:
                self.mq.post(R(o[0]), 0xFFFFFFFF, R(o[1]) | 0x8000, self.handle_id())
            elif sub == 8:
                self.mq.post(self.local(0x110), self.local(0x10C), self.local(0x114), self.handle_id())
            elif sub == 0xA:
                self.mq.clear()
        elif op == 0x89:                                 # 气泡参数
            if sub == 0 and len(o) >= 3 and self.scheduler is not None:
                self.scheduler.dialog_offset(self.fc(R(o[0])), signed(R(o[1])), signed(R(o[2])))
            elif sub in (8, 9) and o and self.scheduler is not None:
                if sub == 8:
                    self.scheduler.kill_fc(self.fc(R(o[0])), talk_only=False, dialogs=True, scripts=False)
                else:
                    self.scheduler.kill_dialog(R(o[0]))
                    self.write(o[0], 0)
            elif sub == 0xC and self.scheduler is not None:
                self.mq.clear()
                self.scheduler.kill_all_dialogs()
        elif op == 0xE2:
            if sub == 4 and o and R(o[0]) == 1000 and self.scheduler is not None:
                if self.scheduler.auto_dialog == 0:
                    self.scheduler.auto_dialog = 10      # DAT_007d70d8: 事件里气泡 ';' 自动翻页 (10×100ms)
        elif op == 0x6F and o:                           # 全局走路延时 DAT_007d8080 (00 设 / 01 加)
            if self.scheduler is not None:
                v = signed(R(o[0]))
                self.scheduler.walk_delay = v if sub == 0 else self.scheduler.walk_delay + v
        elif op == 0x68:                                 # 走完: 站立帧按朝向复位 (FUN_00498ed1)
            fc = self.fc(R(o[0])) if (sub == 1 and o) else self.fc_default
            d = h.fc_get(fc, 0x110) & 7
            h.fc_anim(fc, 0x20000, (0, 6, 12, 18, 5, 11, 17, 23)[d], 0)
        elif op in (0x80, 0xE6, 0xEF, 0x9C, 0xF1, 0x52, 0x4C, 0x4D):
            if op == 0x9C:                               # 对象在屏幕内? (走路脚本: 屏外的步子是瞬移)
                self.set_local(0x44, 1 if h.fc_on_screen(self.fc(R(o[0])) if o else self.fc_default) else 0)
        else:
            h.unknown(c)
        if advance:
            self.pc += 1
        return wait


    # ---- 内置行为脚本 (原版 FUN_0049a08f / FUN_0049a0e9 起的任务) ----
    def handle_id(self) -> int:
        return getattr(self, "handle", 0)

    def _turn(self, fc: int, d: int, x: int) -> int:
        """转向任务: 脚本 0x738dd8 逐 45° 转到目标向 (obj+0x114), ctx+0x108 = x."""
        if d < 0 or d > 7:
            return 0
        self.host.fc_set(fc, 0x114, d)
        if self.scheduler is None or TURN_SCRIPT_VA not in self.scripts:
            self.host.fc_dir(fc, d)
            return self.host.fc_turn(fc, d, x)
        return self.spawn_child(TURN_SCRIPT_VA, fc, {0x108: x})

    def _walk(self, fc: int, d: int, n: int, mode: int, x: int = 0) -> int:
        """走路任务: 脚本 0x73be23 (模式 0) / 0x73be7a (模式 1): ctx+0xe4 = 方向, +0x2c = 步数, +0x108 = x."""
        va = WALK1_SCRIPT_VA if mode == 1 else WALK_SCRIPT_VA
        if self.scheduler is None or va not in self.scripts:
            return self.host.fc_walk(fc, d, n, mode, x)
        return self.spawn_child(va, fc, {0xE4: d, 0x2C: n, 0x108: x})


class TaskScheduler:
    """多任务: 主事件 + FC 子任务 (4f.00 起的) + 气泡, 每帧各跑一轮.
    句柄: 子任务 0x20000+n, 气泡 0x40000+n."""

    def __init__(self) -> None:
        self.tasks: dict[int, EventVM] = {}
        self.dialogs: dict[int, DialogTask] = {}
        self.mq = MessageQueue()
        self.fc_codes: dict[int, int] = {}       # 说话代号 → fc
        self.path_state: dict[int, list] = {}    # 46 寻路: fc → [steps, idx]
        self.auto_dialog = 0                     # DAT_007d70d8 (×100ms); 0 = 等按键
        self.walk_delay = 0                      # DAT_007d8080: 每个 61/67 等待额外加的帧数 (op 6f)
        self.text_speed = 25                     # ms/字
        self._n = 0
        self._nd = 0

    # ---- 气泡 ----
    def add_dialog(self, dlg: DialogTask) -> int:
        self._nd += 1
        hd = 0x40000 + self._nd
        dlg.handle = hd
        self.dialogs[hd] = dlg
        return hd

    def dialog_alive(self, hd: int) -> bool:
        d = self.dialogs.get(hd)
        return d is not None and d.alive

    def any_dialog(self) -> bool:
        return any(d.alive for d in self.dialogs.values())

    def kill_dialog(self, hd: int) -> None:
        d = self.dialogs.pop(hd, None)
        if d is not None and d.alive:
            d.kill()

    def kill_all_dialogs(self) -> None:
        for hd in list(self.dialogs):
            self.kill_dialog(hd)

    def kill_talk_tasks(self) -> None:
        for hd, vm in list(self.tasks.items()):
            if 0xF4 in vm.locals and getattr(vm, "is_child", True):
                self.kill(hd)

    def kill_children(self) -> None:
        for hd, vm in list(self.tasks.items()):
            if getattr(vm, "is_child", True):
                self.kill(hd)

    def dialog_offset(self, fc: int, dx: int, dy: int) -> None:
        for d in self.dialogs.values():
            if d.fc == fc and d.alive:
                d.anchor_dx, d.anchor_dy = dx, dy

    def tick_dialogs(self, dt_ms: float) -> None:
        for hd, d in list(self.dialogs.items()):
            if d.alive:
                d.tick(dt_ms)
            if not d.alive:
                self.dialogs.pop(hd, None)

    def press_key(self) -> None:
        for d in self.dialogs.values():
            if d.alive:
                d.press_key()

    def add(self, vm: EventVM) -> int:
        self._n += 1
        hd = 0x20000 + self._n
        vm.handle = hd
        self.tasks[hd] = vm
        return hd

    def alive(self, hd: int) -> bool:
        vm = self.tasks.get(hd)
        return vm is not None and not vm.done

    def kill(self, hd: int) -> None:
        vm = self.tasks.pop(hd, None)
        if vm is not None:
            vm.done = True

    def kill_fc(self, fc: int, talk_only: bool = False, dialogs: bool = False, scripts: bool = True) -> None:
        """结束某 FC 的子任务. talk_only: 只杀说话脚本 (局部 0xf4 有代号的); dialogs: 连气泡一起."""
        if scripts:
            for hd, vm in list(self.tasks.items()):
                if vm.fc_default == fc and getattr(vm, "is_child", True):
                    if talk_only and 0xF4 not in vm.locals:
                        continue
                    self.kill(hd)
        if dialogs:
            for hd, d in list(self.dialogs.items()):
                if d.fc == fc:
                    self.kill_dialog(hd)

    def tick(self) -> None:
        for hd, vm in list(self.tasks.items()):
            if not vm.done:
                vm.tick()
            if vm.done:
                self.tasks.pop(hd, None)

    def busy(self) -> bool:
        return any(not vm.done for vm in self.tasks.values())


# ---------------------------------------------------------------- 便捷入口
def load_image() -> ExeImage | None:
    return ExeImage() if EXE.exists() else None


def fc_table(img: ExeImage, n: int = 16) -> list[int]:
    """对象句柄变量表 0x73e235.. 的初值 (FC id)."""
    return [img.u32(FC_VAR_BASE + 4 * i) for i in range(n)]


class EventRunner:
    """事件链: 跑一个事件到 92.01, 再按 0x613068 (92.02 / 2c 写) 或 0x61306c (92.03) 接下一个.
    对应 FUN_0045901c 起任务 + 92.01 处理 + FUN_0045aef5 的组合."""

    def __init__(self, bundle: "ScriptBundle | ExeImage", host: EventHost,
                 globals_: dict[int, int] | None = None, events: dict[int, int] | None = None,
                 scripts: dict[int, list[Cmd]] | None = None) -> None:
        self.img = bundle
        self.host = host
        self.globals = globals_ if globals_ is not None else {}
        self.events = events if events is not None else getattr(bundle, "events", {})
        self.scripts = scripts if scripts is not None else getattr(bundle, "scripts", {})
        self.scheduler = TaskScheduler()
        self.main: EventVM | None = None
        self.history: list[int] = []
        self.frames = 0

    def start(self, ev: int, arg: int = -1) -> bool:
        va = self.events.get(ev)
        if va is None or va not in self.scripts:
            self.host.log(f"[ev] no event {ev}")
            return False
        self.history.append(ev)
        self.main = EventVM(self.img, self.scripts[va], self.host, self.globals, name=f"ev{ev}",
                            scripts=self.scripts, scheduler=self.scheduler, event_id=ev, arg=arg, entry=va)
        self.main.is_child = False
        return True

    @property
    def running(self) -> bool:
        return self.main is not None and not self.main.done

    def _pending(self) -> int | None:
        for key in (G_EVENT_NEXT, G_EVENT_DEFER):
            v = self.globals.get(key, 0xFFFFFFFF)
            if v != 0xFFFFFFFF:
                self.globals[key] = 0xFFFFFFFF
                return v
        return None

    def press_key(self) -> None:
        self.scheduler.press_key()

    def _any_vm(self) -> "EventVM | None":
        if self.main is not None:
            return self.main
        return next(iter(self.scheduler.tasks.values()), None)

    def turn(self, fc: int, d: int, x: int) -> int:
        """气泡 <DIRn> → 转向脚本任务 (返回句柄)."""
        vm = self._any_vm()
        return vm._turn(fc, d, x) if vm is not None else 0

    def walk(self, fc: int, d: int, n: int, mode: int, x: int) -> int:
        vm = self._any_vm()
        return vm._walk(fc, d, n, mode, x) if vm is not None else 0

    def alive(self, hd: int) -> bool:
        return self.scheduler.alive(hd) or self.scheduler.dialog_alive(hd)

    @property
    def dialogs(self) -> list[DialogTask]:
        return [d for d in self.scheduler.dialogs.values() if d.alive]

    def tick(self, dt_ms: float = 30.0) -> bool:
        """跑一帧. 返回 True = 整条链已结束 (没有主事件、也没有待接的事件)."""
        self.frames += 1
        if self.main is not None and not self.main.done:
            self.main.tick()
        self.scheduler.tick()
        self.scheduler.tick_dialogs(dt_ms)
        if self.main is None or self.main.done:
            nxt = self._pending()
            if nxt is not None:
                self.start(nxt)
                return False
            return not self.scheduler.busy() and not self.scheduler.any_dialog()
        return False

    def run(self, max_frames: int = 200000) -> int:
        for _ in range(max_frames):
            if self.tick():
                break
        return self.frames
