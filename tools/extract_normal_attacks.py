"""从 FlyingSB.exe 提取玩家普攻表 → core/normal_attack_data.py (生成文件).

exe 普攻表 @0x68ab90: 96 项 × 24B = [id, flags, 0, 组号(角色模组), 瞄准模板 idx, 处理函数].
处理函数多数是 DOIT_melee 模板 (FUN_004d0e18(this, seq 表[4 方向], 命中特效)) + 挥击音/命中音登记;
各项的 seq 表 / 特效 / 音效 / 信号从反编译 (reverse_engineering/normal_attack_all.txt) 抽出, 这里写死成表
(见 ENTRY_EXTRA), seq 字节从 exe 解码. 武器 → 普攻: 道具表 stride 0x4c, +0x695510 普攻 id, +0x6954e0 武器类型,
+0x6954ec 可装备角色位 (& 0x430 = 八戒/破无/捕山 远程武器).

跑法: cd rewrite && venv/bin/python -m tools.extract_normal_attacks
"""
from __future__ import annotations

import json
import os
import struct
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
EXE = Path(os.environ.get("FLYINGSB_EXE", ROOT.parent / "origin" / "flyingsb" / "FlyingSB.exe"))
OUT = ROOT / "core" / "normal_attack_data.py"

# 处理函数抽出的: 项 → (seq 表, 命中特效, (挥击音, 信号), (命中音, 登记信号))
# 特效: 'starburst' = DAT_00655b18 (et00 紫星), 'oval' = PTR_00655ca0[施法者朝向] (ef010 长椭圆),
#       'claw' = PTR_00655d30[施法者朝向] (ef010 三爪)
_G2A = ('starburst', (0xb9, -1000))
_G2B = ('starburst', (0xd5, -1000))
ENTRY_EXTRA: dict[int, tuple] = {}
for i, hit in zip(range(0, 3), (0xbd, 0xbf, 0xbf)):
    ENTRY_EXTRA[i] = (0x670cf0, 'starburst', (0xb9, -1000), (hit, 0))
for i in range(3, 8):
    ENTRY_EXTRA[i] = (0x67122c, 'starburst', (0xd5, -1000), (0xbd, 0))
for i in range(8, 16):
    ENTRY_EXTRA[i] = (0x67206c, 'oval', (0xd3, -1001), (0xbd, -1000))
for i, hit in zip(range(16, 23), (0xbd, 0x103, 0xbf, 0xe0, 0xe0, 0xe0, 0xe0)):
    ENTRY_EXTRA[i] = (0x672608, 'starburst', (0xb9, -1001), (hit, -1000))
ENTRY_EXTRA[23] = (0x672788, 'starburst', (0x127, -1001), (0xbd, -1000))
for i in range(32, 40):
    ENTRY_EXTRA[i] = (0x67602c, 'starburst', None, None)          # 沙悟净: 音在 seq 里 (op 0x11/0x13)
for i in range(48, 56):
    ENTRY_EXTRA[i] = (0x676ad4 if i == 54 else 0x6763a0, 'oval', (0x104, -1001), (0x105, -1000))
for i, hit in zip(range(56, 64), (0xbf, 0xbe, 0xbe, 0xbe, 0xb9, 0xb9, 0xb9, 0xb9)):
    ENTRY_EXTRA[i] = (0x677704, 'starburst', (0x11d, -1001), (hit, -1000))
for i in range(80, 88):
    ENTRY_EXTRA[i] = (0x6798c8, 'starburst', (0xaa, -1001), (0xbd, -1000))
ENTRY_EXTRA[88] = (0x679ec4, 'claw', None, None)
ENTRY_EXTRA[89] = (0x67a2f4, 'claw', None, None)
ENTRY_EXTRA[91] = (0x67420c, 'starburst', (0xb9, -1001), (0xbd, 0))
ENTRY_EXTRA[92] = (0x677c4c, 'starburst', (0xb9, -1001), (0xbd, -1000))
ENTRY_EXTRA[93] = (0x67872c, 'starburst', (0xaa, -1001), (0xbd, -1000))
ENTRY_EXTRA[94] = (0x67206c, 'oval', (0xce, -1001), (0x11a, -1000))
ENTRY_EXTRA[95] = (0x6763a0, 'oval', (0xce, -1001), (0x11a, -1000))
# 远程 (八戒 24-31 / 破无 64-71 / 捕山 72-79) 与 紫河第三形态 90: 自定义处理函数, 另做 (core.normal_attack 里标 'custom')


class Exe:
    def __init__(self, path: Path):
        self.d = path.read_bytes()
        pe = struct.unpack_from('<I', self.d, 0x3c)[0]
        nsec = struct.unpack_from('<H', self.d, pe + 6)[0]
        opt = struct.unpack_from('<H', self.d, pe + 20)[0]
        self.secs = []
        for i in range(nsec):
            o = pe + 24 + opt + i * 40
            vs, va, rs, raw = struct.unpack_from('<IIII', self.d, o + 8)
            self.secs.append((0x400000 + va, max(vs, rs), raw))

    def off(self, v: int) -> int:
        for va, size, raw in self.secs:
            if va <= v < va + size:
                return raw + v - va
        raise ValueError(hex(v))

    def u32(self, v: int) -> int:
        return struct.unpack_from('<I', self.d, self.off(v))[0]

    def seq(self, v: int) -> list[tuple]:
        """解码成我们的 tuple seq (core.anim_engine.bytecode.tuple_to_bytecode 格式)."""
        o = self.off(v)
        out: list[tuple] = []
        for _ in range(400):
            op, size = self.d[o], self.d[o + 1]
            body = self.d[o + 2:o + size]
            if op in (4, 5, 6) and size == 10:
                slot, frame, ticks = struct.unpack('<HIH', body)
                out.append(({4: 'fm', 5: 'fm_mode1', 6: 'idle'}[op], slot, frame, ticks))
            elif op in (0x0b, 0x0c) and size == 10:
                dx, dy, dz, ticks = struct.unpack('<hhhH', body)
                out.append(('move', dx, dy, dz, ticks))
            elif op == 0x0e and size == 4:
                out.append(('jump', struct.unpack('<h', body)[0]))
            elif op in (0x11, 0x12, 0x13) and size == 4:
                out.append(('sound', struct.unpack('<H', body)[0], 0x0400 | op))
            elif op == 0:
                out.append(('exit',))
                break
            elif op == 1:
                out.append(('loop',))
                break
            else:
                raise ValueError(f'未知 op {op:#x} size {size} @ {v:#x}')
            o += size
        return out


def main() -> None:
    exe = Exe(EXE)
    entries = []
    for i in range(96):
        b = 0x68ab90 + i * 0x18
        flags, group, tmpl, fn = exe.u32(b + 4), exe.u32(b + 12), exe.u32(b + 16), exe.u32(b + 20)
        ex = ENTRY_EXTRA.get(i)
        kind = 'none' if fn == 0 else ('doit' if ex else 'custom')
        entries.append(dict(idx=i, group=group, flags=flags, template=tmpl, fn=fn, kind=kind,
                            seq_table=ex[0] if ex else None, fx=ex[1] if ex else None,
                            swing=ex[2] if ex else None, hit=ex[3] if ex else None))
    tables = {}
    for e in entries:
        t = e['seq_table']
        if t is not None and t not in tables:
            tables[t] = [exe.seq(exe.u32(t + 4 * d)) for d in range(4)]
    # 远程普攻 / 紫河第三形态 (core.ranged_attack) 用到的 seq: 4 方向表 + 单条
    extra_tables = [0x67439c, 0x6747dc, 0x674f5c, 0x67511c, 0x6780bc, 0x67823c, 0x677c8c, 0x677e3c, 0x677ecc,
                    0x67895c, 0x678b4c, 0x678d1c, 0x678e1c, 0x678ecc, 0x678f0c, 0x67442c, 0x674fec, 0x67a7e4,
                    0x655960]
    for t in extra_tables:
        if t not in tables:
            tables[t] = [exe.seq(exe.u32(t + 4 * d)) for d in range(4)]
    singles = {a: exe.seq(a) for a in (0x674ffc, 0x67512c, 0x656014, 0x655fa4, 0x656084, 0x66a870)}
    items = json.loads((ROOT / 'assets' / 'items_table.json').read_text())
    it = items if isinstance(items, list) else items.get('items', items)
    pairs = it.items() if isinstance(it, dict) else enumerate(it)
    weapons = {}
    for k, v in pairs:
        iid = int(k) if str(k).isdigit() else v.get('id')
        if v.get('cat') != 'WEAPON':
            continue
        weapons[iid] = (exe.u32(0x695510 + iid * 0x4c), exe.u32(0x6954e0 + iid * 0x4c),
                        exe.u32(0x6954ec + iid * 0x4c))
    lines = ['"""生成文件 (tools/extract_normal_attacks.py), 勿手改. 玩家普攻表 @0x68ab90 + seq 表 + 武器→普攻."""',
             'from __future__ import annotations', '',
             '# idx → (组号, flags, 瞄准模板, 处理函数, kind, seq 表地址, 命中特效, (挥击音, 信号)|None, (命中音, 登记信号)|None)',
             'ATTACK_ENTRIES: list[tuple] = [']
    for e in entries:
        lines.append(f"    ({e['group']}, {e['flags']:#06x}, {e['template']}, {e['fn']:#x}, {e['kind']!r}, "
                     f"{hex(e['seq_table']) if e['seq_table'] else None}, {e['fx']!r}, {e['swing']!r}, {e['hit']!r}),   # {e['idx']}")
    lines += [']', '', '# seq 表地址 → [上, 下, 左, 右] 4 方向 seq (exe 原字节解码)', 'SEQ_TABLES: dict[int, list[list[tuple]]] = {']
    for t, dirs in tables.items():
        lines.append(f'    {t:#x}: [')
        for s in dirs:
            lines.append(f'        {s!r},')
        lines.append('    ],')
    lines += ['}', '', '# 单条 seq (地址 → seq)', 'SEQS: dict[int, list[tuple]] = {']
    for a, sq in singles.items():
        lines.append(f'    {a:#x}: {sq!r},')
    lines += ['}', '', '# 武器道具 id → (普攻 idx, 武器类型, 可装备角色位)', 'WEAPON_ATTACK: dict[int, tuple[int, int, int]] = {']
    for iid, (a, t, m) in sorted(weapons.items()):
        lines.append(f'    {iid}: ({a}, {t:#x}, {m:#x}),')
    lines += ['}', '']
    OUT.write_text('\n'.join(lines), encoding='utf-8')
    print('written', OUT, len(entries), 'entries', len(tables), 'seq tables', len(weapons), 'weapons')


if __name__ == '__main__':
    main()
