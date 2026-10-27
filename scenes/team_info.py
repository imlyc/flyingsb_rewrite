"""隊伍情報 (队伍情报) 界面 — 照 exe menu.cpp 逆向 (2026-10-27, reverse_engineering/eqmenu_decomp.java, 原版原生截图核对).

原版是一组"窗口实体" (FUN_0041da1b(n, 开/关), 表 0x54cad0), 每 tick 跑各自状态机; 这里按同样的编号/状态复刻:
   3 FUN_00422234 队伍转盘 (立绘椭圆转盘, ←→ 转到下/上一人, 10 tick 一格, 停后 8 tick 内可连按)
  12 FUN_00433e1a 属性面板 (FUN_00433975 填值; 列表开着时 当前/换上后 两列, 减=红 增=黄)
   6 FUN_0042a9ae 装备栏 (頭部/身體/手部/飾品/飾品; 获焦点时 ↑↓ 选槽, Enter 开列表)
  14 FUN_00434b30 金钱;  1 FUN_00420e32 名字;  2 FUN_004211de 子菜单 道具/特殊能力/裝備
   4 FUN_0042534d 道具列表 (mode 6 = 换装候选, mode 2 = 可用道具);  5 FUN_00429169 特殊能力;  13 FUN_004347a3 说明栏
  光标 FUN_0043854a: 矩形 16.16 定点插值 (步长 = 差/6, 剩余 ≤ 2 步改半步收敛, 期间不收键), 灰阶调色板 0xf8..0xff 轮转描两圈.
窗口: FUN_0041e3ec 纯色底 (菜单色 69,107,88) + 1px 高光/暗边; 弹出缩放 0x1999 → +0x7ef9/t 过冲 → -0x28f/t 回 1.0, 关闭 -0x4f5c/t.
文字: 新細明體 16px (scenes.battle.status_bar.draw_text, y = 垂直中线, 先描边后主色); 界面文字统一简体.
1 tick = TICK_MS (原版主循环下限 16ms).
"""
from __future__ import annotations

from dataclasses import dataclass

import pygame

from core import equipment as EQ
from core import item_icons
from core.character import Character
from core.items import get_item_name, item_desc, item_effect_type, item_table_entry
from scenes.battle.status_bar import _text_width, draw_text

TICK_MS = 17
SCREEN_W, SCREEN_H = 800, 600

# ---- 调色板 (原版菜单调色板实值, 原生截图读出; 菜单色 = FlyingSB.INI menu_color_*) ----
WIN = (69, 107, 88)            # idx 1
SHADE = (34, 53, 44)           # idx 2 = 菜单色 / 2
WHITE, BLACK = (255, 255, 255), (0, 0, 0)
CURSOR_GRAYS = [(v, v, v) for v in (219, 179, 143, 107, 71, 35, 0, 255)]   # 0xf8..0xff
# (主色, 描边色) = exe 0x53c734.. PALETTEINDEX 对
P_NORMAL = ((255, 255, 255), (35, 35, 35))
P_GRAY = ((0, 0, 0), (71, 71, 71))
P_RED = ((255, 2, 2), (151, 54, 51))
P_YELLOW = ((255, 255, 51), (153, 129, 118))

# ---- 键 (exe: Z/ESC/小键盘0 取消, X/Enter/小键盘1 确定, 方向/小键盘 8246, PgUp/PgDn/小键盘 93) ----
K_CANCEL, K_OK, K_UP, K_DOWN, K_LEFT, K_RIGHT, K_PGUP, K_PGDN = range(1, 9)
_KEYMAP = {
    pygame.K_ESCAPE: K_CANCEL, pygame.K_z: K_CANCEL, pygame.K_KP0: K_CANCEL, pygame.K_INSERT: K_CANCEL,
    pygame.K_RETURN: K_OK, pygame.K_KP_ENTER: K_OK, pygame.K_x: K_OK, pygame.K_KP1: K_OK,
    pygame.K_UP: K_UP, pygame.K_KP8: K_UP, pygame.K_DOWN: K_DOWN, pygame.K_KP2: K_DOWN,
    pygame.K_LEFT: K_LEFT, pygame.K_KP4: K_LEFT, pygame.K_RIGHT: K_RIGHT, pygame.K_KP6: K_RIGHT,
    pygame.K_PAGEUP: K_PGUP, pygame.K_KP9: K_PGUP, pygame.K_PAGEDOWN: K_PGDN, pygame.K_KP3: K_PGDN,
}
REPEAT_DELAY_MS, REPEAT_MS = 500, 33          # Windows 键盘自动重复 (exe 方向键收重复, 取消键不收)
_REPEATABLE = (K_UP, K_DOWN, K_LEFT, K_RIGHT, K_PGUP, K_PGDN)

# ---- 音效 (exe sound id) ----
SND_CURSOR, SND_OK, SND_CANCEL, SND_OPEN, SND_BUZZ, SND_HEAL = 0x144, 0x142, 0x143, 0x10E, 0x141, 0xCA

# 窗口号 (exe 0x7b8eb0[n])
W_NAME, W_SUB, W_TEAM, W_LIST, W_SKILL, W_EQUIP, W_STATS, W_DESC, W_MONEY = 1, 2, 3, 4, 5, 6, 12, 13, 14
_FOCUSABLE = {W_SUB, W_LIST, W_SKILL, W_EQUIP}          # 0x54cad4 标志
_OPEN_SOUND = {W_SUB, W_TEAM, W_LIST, W_SKILL}          # 0x54cad8 标志

SLOT_LABELS = ("头部：", "身体：", "手部：", "饰品：", "饰品：")
LIST_TITLES = ("　头部防具", "　身体防具", "　武　　器", "　饰　　品 ", "　饰　　品 ")
SUB_ITEMS = ("道具", "特殊能力", "装备")
SG_STEPS = {6: (6, 16)}                                   # 沙悟淨 SG 技门槛, 其余 (2,5,8,12,16)
SG_STEPS_DEFAULT = (2, 5, 8, 12, 16)
GAUGE_W5 = (0, 8, 16, 22, 27, 32, 38, 43, 48, 52, 56, 60, 64, 68, 72, 76, 80)   # 0x54ca40
GAUGE_W2 = (0, 3, 6, 9, 12, 14, 16, 18, 20, 22, 24, 26, 28, 29, 30, 31, 32)     # 0x54ca84


# ---------------- exe 定点三角 (FUN_00411850 / 00411918; 表 0x544b78 = trunc(sin*65536), 4096 份) ----------------
_SIN_Q = None


def _sin_tab(i: int) -> int:
    global _SIN_Q
    if _SIN_Q is None:
        import math
        _SIN_Q = [int(math.sin(k * 2 * math.pi / 4096) * 65536) for k in range(1025)]
    return _SIN_Q[i]


def fsin(a: int) -> int:
    u = ((a + 8) & 0xFFFFFFFF) >> 4
    q, u = u & 0xC00, u & 0xFFF
    if q == 0:
        return _sin_tab(u)
    if q == 0x400:
        return _sin_tab(0x800 - u)
    if q == 0x800:
        return -_sin_tab(u - 0x800)
    return -_sin_tab(0x1000 - u)


def fcos(a: int) -> int:
    u = ((a + 8) & 0xFFFFFFFF) >> 4
    q, u = u & 0xC00, u & 0xFFF
    if q == 0:
        return _sin_tab(0x400 - u)
    if q == 0x400:
        return -_sin_tab(u - 0x400)
    if q == 0x800:
        return -_sin_tab(0xC00 - u)
    return _sin_tab(u - 0xC00)


def _tdiv(a: int, b: int) -> int:
    """C 整数除法 (向零截断)."""
    q = abs(a) // abs(b)
    return q if (a >= 0) == (b > 0) else -q


def _fx(v: int) -> int:
    """(v + (v>>31 & 0xffff)) >> 16 = 16.16 向零取整."""
    return _tdiv(v, 0x10000)


# ---------------- 数据 ----------------
@dataclass
class Member:
    name: str              # 简体角色名 (core.character.CHARACTER_NAMES)
    ch: Character
    record: int            # 角色记录号 (存档槽位 = exe 角色表下标; 可装备位 0x8000>>record)


# ---------------- 绘制原语 ----------------
def frame_surface(w: int, h: int) -> pygame.Surface:
    """FUN_0041e3ec 窗口底: 纯色 + 上/左 1px 白高光 + 下/右内侧暗边 + 最外侧黑边."""
    s = pygame.Surface((w, h))
    s.fill(WIN)
    s.fill(WHITE, (1, 1, w - 3, 1))
    s.fill(WHITE, (1, 1, 1, h - 3))
    s.fill(SHADE, (1, h - 2, w - 2, 1))
    s.fill(SHADE, (w - 2, 1, 1, h - 2))
    s.fill(BLACK, (0, h - 1, w - 1, 1))
    s.fill(BLACK, (w - 1, 0, 1, h - 1))
    return s


def text_c(surf: pygame.Surface, x0: int, x1: int, cy: int, text: str, pair=P_NORMAL) -> None:
    """FUN_0041dd68: DT_CENTER (x0..x1 水平居中)."""
    draw_text(surf, x0 + _tdiv((x1 - x0) - _text_width(text), 2), cy, text, pair)


def separator(surf: pygame.Surface, x: int, y: int, ln: int) -> None:
    """布局项 type -1: 凹线."""
    l, t = x - 1, y - 1
    surf.fill(BLACK, (l, t, ln, 1))
    surf.fill(BLACK, (l, t, 1, 2))
    surf.fill(WHITE, (l + 1, t + 1, ln - 1, 1))
    surf.fill(WHITE, (l + ln, t, 1, 2))


def _rect(surf, color, l, t, r, b) -> None:
    if r > l and b > t:
        surf.fill(color, (l, t, r - l, b - t))


def scrollbar(surf: pygame.Surface, cx: int, cy: int, length: int, n: int, pos: int) -> None:
    """FUN_0041f239 (竖直): 凹槽 + 凸块, 块高 = max(14, 槽长 / n)."""
    if n == 0 or length <= 15:
        return
    l, t, r, b = cx - 2, cy - length // 2, cx + 2, cy - length // 2 + length
    _rect(surf, WIN, cx - 9, t - 1, cx + 9, b + 1)
    _rect(surf, SHADE, l, t, r, b)
    _rect(surf, BLACK, l - 1, t - 1, r, t)
    _rect(surf, BLACK, l - 1, t - 1, l, b)
    _rect(surf, WHITE, r, t, r + 1, b + 1)
    _rect(surf, WHITE, l, b, r + 1, b + 1)
    th = max(14, _tdiv(b - t, n))
    tl, tr = l - 5, l + 9
    tt = (t + th // 2 + _tdiv((length - th) * pos, n)) - th // 2
    tb = tt + th
    _rect(surf, WIN, tl, tt, tr, tb)
    _rect(surf, WHITE, tl - 1, tt - 1, tr, tt)
    _rect(surf, WHITE, tl - 1, tt - 1, tl, tb)
    _rect(surf, BLACK, tr, tt, tr + 1, tb + 1)
    _rect(surf, BLACK, tl, tb, tr + 1, tb + 1)


_smenu = None


def _smenu_sheet():
    global _smenu
    if _smenu is None:
        from scenes.battle.status_bar import _get_smenu
        _smenu = _get_smenu()
    return _smenu


def sg_gauge(surf: pygame.Surface, x: int, y: int, sg: int, two: bool) -> None:
    """布局项 type -3 (5 格, 宽 80) / -4 (沙悟淨 2 格, 宽 32): SMENU y32 空槽 + y48 满槽."""
    sg = max(0, min(16, sg))
    sh = _smenu_sheet()
    w = 32 if two else 80
    px = (GAUGE_W2 if two else GAUGE_W5)[sg]
    surf.blit(sh, (x, y - 8), pygame.Rect(0, 32, w, 16))
    if px:
        surf.blit(sh, (x, y - 8), pygame.Rect(0, 48, px, 16))


def icon(surf: pygame.Surface, item_id: int, x: int, y: int) -> None:
    """布局项 type -2: SITEM 20×20 格整格不透明贴 (含黑底/蓝框, 原生截图核对), 左上 = (x, y-10)."""
    sheet = item_icons._load()
    if sheet is None or not (0 <= item_id < item_icons.COLS * item_icons.ROWS):
        return
    c = item_icons.CELL
    surf.blit(sheet, (x, y - 10), pygame.Rect((item_id % item_icons.COLS) * c, (item_id // item_icons.COLS) * c, c, c))


# ---------------- 光标 (FUN_0043854a) ----------------
class Cursor:
    STEPS = 6                                   # FlyingSB.INI menu_cursor_move_frame (exe 0x7b88d8)

    def __init__(self) -> None:
        full = [0, 0, SCREEN_W << 16, SCREEN_H << 16]
        self.cur = list(full)
        self.dst = list(full)
        self.step = [0, 0, 0, 0]
        self.state = 10
        self.ready = True                       # exe 0x7b8ef8: 光标停稳 (或进入收尾半步) 才收键
        self.phase = 0

    def move_to(self, l: int, t: int, r: int, b: int) -> None:
        self.dst = [l << 16, t << 16, r << 16, b << 16]
        self.state = 0x14

    def reset_full(self) -> None:
        self.cur = [1 << 16, 1 << 16, (SCREEN_W - 1) << 16, (SCREEN_H - 1) << 16]
        self.dst = list(self.cur)

    def tick(self) -> None:
        if self.state == 10 and self.cur != self.dst:
            self.state = 0x14
        if self.state == 0x14:
            self.step = [_tdiv(d - c, self.STEPS) for c, d in zip(self.cur, self.dst)]
            self.ready = False
            self.state = 0x1E
        if self.state == 0x1E:
            for i in range(4):
                self.cur[i] += self.step[i]
                rem = _fx(self.dst[i] - self.cur[i])
                if abs(rem) <= abs(_fx(self.step[i] * 2)):
                    self.step[i] = _tdiv(rem, 2) << 16
                    self.ready = True
                st = self.step[i]
                if st < 1:
                    if st < 0:
                        if self.cur[i] <= self.dst[i]:
                            self.cur[i] = self.dst[i]
                    else:
                        self.cur[i] = self.dst[i]
                elif self.dst[i] <= self.cur[i]:
                    self.cur[i] = self.dst[i]
            if self.cur == self.dst:
                self.ready = True
                self.state = 10

    def draw(self, surf: pygame.Surface) -> None:
        l, t, r, b = (_fx(v) for v in self.cur)
        for inset in (0, 1):
            col = CURSOR_GRAYS[self.phase & 7]
            self.phase += 1
            L, T, R, B = l + inset, t + inset, r - inset, b - inset
            if R - L < 1 or B - T < 1:
                continue
            surf.fill(col, (L, T, R - L, 1))
            surf.fill(col, (L, B - 1, R - L, 1))
            surf.fill(col, (L, T, 1, B - T))
            surf.fill(col, (R - 1, T, 1, B - T))


# ---------------- 窗口基类 ----------------
class Win:
    W = H = 0

    def __init__(self, sc: "TeamInfoScene", idx: int) -> None:
        self.sc = sc
        self.idx = idx
        self.state = 1
        self.s = 0
        self.cx = self.cy = 0
        self.surf: pygame.Surface | None = None
        self.mode_prev = sc.mode
        self.row = 0
        self.dead = False

    # --- 弹出/收起动画 ---
    def _grow(self) -> bool:
        self.s += 0x7EF9
        if self.s > 0xFFFF:
            self.state = 0xF
            return True
        return False

    def _settle(self) -> bool:
        self.s -= 0x28F
        if self.s < 0x10001:
            self.s = 0x10000
            self.state = 0x14
            return True
        return False

    def _shrink(self) -> bool:
        self.s -= 0x4F5C
        if self.s < 1:
            self.s = 0
            self.state = 0x6E
            return True
        return False

    def left(self) -> int:
        return self.cx - self.W // 2

    def top(self) -> int:
        return self.cy - self.H // 2

    def cursor_to(self, rect) -> None:
        l, t, r, b = rect
        self.sc.cursor.move_to(self.left() + l, self.top() + t, self.left() + r, self.top() + b)

    def focused(self) -> bool:
        return self.sc.focus is self

    def key(self) -> int:
        """本 tick 的按键 (焦点在本窗且光标停稳才收)."""
        return self.sc.key if (self.focused() and self.sc.cursor.ready) else 0

    def tick(self) -> None:
        pass

    def draw(self, dst: pygame.Surface) -> None:
        if self.surf is None or self.dead or self.s <= 0:
            return
        if self.s == 0x10000:
            dst.blit(self.surf, (self.left(), self.top()))
            return
        sw = _fx(self.W * self.s)
        sh = _fx(self.H * self.s)
        if sw < 1 or sh < 1:
            return
        dst.blit(pygame.transform.scale(self.surf, (sw, sh)), (self.cx - sw // 2, self.cy - sh // 2))

    def remove(self) -> None:
        self.dead = True
        self.sc.wins.pop(self.idx, None)


def _std_open(win: Win, on_opened=None) -> bool:
    """state 10 / 0xf 的通用处理; 返回 True 表示本 tick 已处理."""
    if win.state == 10:
        if win._grow() and on_opened:
            on_opened()
        return True
    if win.state == 0xF:
        win._settle()
        return True
    if win.state == 100:
        win._shrink()
        return True
    return False


# ---------------- 3: 队伍转盘 ----------------
class TeamWin(Win):
    CX, CY = (SCREEN_W - 640) // 2 + 0xB0, (SCREEN_H - 480) // 2 + 0x104       # (256, 320)
    RX, RY = 100, 30                                                             # 0x54cc40/44

    def __init__(self, sc, idx) -> None:
        super().__init__(sc, idx)
        self.angle = 0
        self.spin = 0
        self.rx = self.ry = 0
        self.cnt = 0
        self.wait = 0
        self.saved_focus = None
        self.box = (0, 0, 0, 0)

    def _press_spin(self, k: int) -> bool:
        n = len(self.sc.members)
        if n <= 1 or k not in (K_LEFT, K_RIGHT):
            return False
        if k == K_LEFT:
            self.spin = _tdiv(_tdiv(-0x10000, n), 10)
            self.sc.cur = (self.sc.cur + 1) % n
        else:
            self.spin = _tdiv(_tdiv(0x10000, n), 10)
            self.sc.cur = (self.sc.cur - 1 + n) % n
        self.cnt = 10
        return True

    def _spin_step(self) -> bool:
        self.angle = (self.angle + 0x10000 + self.spin) % 0x10000
        self.cnt -= 1
        return self.cnt == 0

    def _refresh_panels(self) -> None:
        sc = self.sc
        for w, st in ((W_STATS, 0x5A), (W_EQUIP, 0x5A), (W_NAME, 0x1E)):
            if w in sc.wins:
                sc.wins[w].state = st

    def tick(self) -> None:
        sc = self.sc
        st = self.state
        if st == 1:
            n = len(sc.members)
            self.angle = (0x10000 - _tdiv(0x10000, n) * sc.cur) % 0x10000
            self.spin = 0xCCC
            self.rx = self.ry = 0
            fx = self.CX + _fx(fsin(0x8000) * self.RX)
            fy = self.CY - _fx(fcos(0x8000) * self.RY)
            self.box = (fx - 0x20, fy - 0x56, fx + 0x20, fy + 8)
            self.cx, self.cy = fx, fy                    # 子菜单相对它定位
            if self.mode_prev == -1:
                sc.cursor.reset_full()
            sc.cursor.move_to(*self.box)
            self.state = 10
        elif st == 10:
            self.rx += self.RX // 10
            self.ry += self.RY // 10
            self.angle = (self.angle + 0x10000 + self.spin) % 0x10000
            if self.rx >= self.RX:
                self.rx, self.ry = self.RX, self.RY
                for w in (W_STATS, W_EQUIP, W_MONEY, W_NAME, W_SUB):
                    sc.open(w)
                sc.focus = sc.wins.get(W_SUB)
                sc.mode = 3
                self.wait = 0
                self.state = 0x14
        elif st == 0x14:
            ready = sc.cursor.ready
            k = sc.key if ready else 0
            if sc.focus is sc.wins.get(W_SUB):
                if self._press_spin(k):
                    self.state = 0x1E
            elif (sc.focus is not None and sc.focus.idx in (W_LIST, W_SKILL, W_EQUIP)
                  and not (sc.focus.idx == W_LIST and sc.focus.mode == 6)):
                old = sc.member.record
                if self._press_spin(k):
                    if sc.focus.idx == W_SKILL:              # exe 0x7b82bc[角色] = 技能光标
                        sc.skill_mem[old] = sc.focus.row
                    self.state = 0x15
                    self.saved_focus = sc.focus
                    sc.focus.state = 0x5E
        elif st in (0x15, 0x1E):
            sc.close(W_SUB)
            sc.cursor.move_to(*self.box)
            self.state = 0x16 if st == 0x15 else 0x28
            sc.sound(SND_CURSOR)
        elif st in (0x16, 0x28):
            if self._spin_step():
                self.wait = 0
                self.state = 0x17 if st == 0x16 else 0x32
        elif st in (0x17, 0x32):
            c = self.wait
            self.wait += 1
            if c < 8:
                if sc.cursor.ready and self._press_spin(sc.key):
                    self.state = 0x15 if st == 0x17 else 0x1E
            else:
                self._refresh_panels()
                if st == 0x17:
                    sc.focus = self.saved_focus
                    if sc.focus is not None:
                        sc.focus.state = 0x5F
                else:
                    sc.open(W_SUB)
                    sc.focus = sc.wins.get(W_SUB)
                    sc.mode = 2
                self.state = 0x14
        elif st == 100:
            self.rx, self.ry = self.RX, self.RY
            self.spin = -0xCCC
            self.state = 0x69
            for w in (W_STATS, W_EQUIP, W_MONEY, W_NAME, W_SUB):
                sc.close(w)
        elif st == 0x69:
            self.rx -= self.RX // 10
            self.ry -= self.RY // 10
            self.angle = (self.angle + 0x10000 + self.spin) % 0x10000
            if self.rx < 1:
                self.state = 0x6E
        elif st == 0x6E:
            self.remove()
            sc.finished = True

    def draw(self, dst: pygame.Surface) -> None:
        """FUN_00421e56: 每人立绘 (网格 8×记录号 帧 6 = 正面站姿) 按深度缩放, 由远到近画."""
        if self.dead:
            return
        sc = self.sc
        n = len(sc.members)
        a = self.angle
        step = _tdiv(0x10000, n)
        items = []
        for m in sc.members:
            x = self.CX + _fx(fsin(a) * self.rx)
            y = self.CY - _fx(fcos(a) * self.ry)
            a = (a + 0x10000 + step) % 0x10000
            frame = sc.stand_frame(m)
            if frame is None or self.ry <= 0:
                continue
            k = (y - (self.CY - self.ry * 7)) / float(self.ry * 7)
            fw, fh = frame.get_size()
            ax, ay = sc.anchor_of(m)
            top = y - int(ay * k)
            bottom = top + int(fh * k)
            left = x - int(ax * k)
            right = left + int(fw * k)
            items.append((k, frame, left, top, right, bottom))
        for i in range(len(items)):            # exe 的交换排序 (按缩放升序 = 远的先画)
            for j in range(i + 1, len(items)):
                if items[j][0] < items[i][0]:
                    items[i], items[j] = items[j], items[i]
        for k, frame, l, t, r, b in items:
            if r > l and b > t:
                dst.blit(pygame.transform.scale(frame, (r - l, b - t)), (l, t))


# ---------------- 2: 子菜单 道具/特殊能力/裝備 ----------------
class SubWin(Win):
    W, H = 80, 80
    ROWS = ((40 - 0x1B, 9, 40 + 0x1B, 0x1F), (40 - 0x23, 0x1D, 40 + 0x23, 0x33), (40 - 0x13, 0x31, 40 + 0x13, 0x47))

    def render(self) -> None:
        s = frame_surface(self.W, self.H)
        for i, t in enumerate(SUB_ITEMS):
            text_c(s, 40 - 60, 40 + 60, 20 + 20 * i, t)
        self.surf = s

    def tick(self) -> None:
        sc = self.sc
        st = self.state
        if st == 1:
            team = sc.wins.get(W_TEAM)
            if team is not None:
                self.cx, self.cy = team.cx + 0x50, team.cy - 0x28
            else:
                self.cx, self.cy = SCREEN_W // 2, SCREEN_H // 2
            self.s = 0x1999
            self.row = 0
            self.render()
            self.state = 10
        elif st == 10:
            if self._grow():
                self.row = sc.sub_row
                self.cursor_to(self.ROWS[self.row])
        elif _std_open(self):
            pass
        elif st == 0x14:
            k = self.key()
            if k == K_CANCEL:
                sc.sub_row = self.row
                if W_TEAM in sc.wins:
                    sc.wins[W_TEAM].state = 100
                sc.sound(SND_CANCEL)
            elif k == K_OK:
                sc.sub_row = self.row
                if self.row == 0:
                    sc.mode = 2
                    sc.open(W_LIST, mode=2)
                    sc.close(W_SUB)
                elif self.row == 1:
                    sc.mode = 2
                    sc.open(W_SKILL, mode=2)
                    sc.close(W_SUB)
                else:
                    if W_EQUIP in sc.wins:
                        sc.wins[W_EQUIP].state = 0x19
                    else:
                        sc.open(W_EQUIP)
                    sc.focus = sc.wins.get(W_EQUIP)
                    sc.close(W_SUB)
                    sc.mode = 2
                sc.sound(SND_OK)
            elif k == K_UP and self.row != 0:
                self.row -= 1
                self.cursor_to(self.ROWS[self.row])
                sc.sound(SND_CURSOR)
            elif k == K_DOWN and self.row != 2:
                self.row += 1
                self.cursor_to(self.ROWS[self.row])
                sc.sound(SND_CURSOR)
        if self.state == 0x6E:
            sc.sub_row = self.row
            self.remove()


# ---------------- 6: 装备栏 ----------------
class EquipWin(Win):
    W, H = 288, 120
    ROWS = tuple((0x90 - 0x8C, 9 + 20 * i, 0x90 + 0x8C, 0x1F + 20 * i) for i in range(5))

    def render(self) -> None:
        s = frame_surface(self.W, self.H)
        ch = self.sc.member.ch
        for i in range(5):
            y = 20 + 20 * i
            draw_text(s, 12, y, SLOT_LABELS[i], P_NORMAL)
            it = EQ.slot_item(ch, i)
            if it is not None:
                icon(s, it, 0x50, y)
                draw_text(s, 0x6C, y, get_item_name(it), P_NORMAL)
        self.surf = s

    def _desc(self) -> None:
        it = EQ.slot_item(self.sc.member.ch, self.row)
        self.sc.desc_pending = item_desc(it) if it is not None else ""

    def tick(self) -> None:
        sc = self.sc
        st = self.state
        if st == 1:
            self.cx, self.cy = SCREEN_W // 2 - 0x120 + self.W // 2, SCREEN_H // 2 + 0x78
            self.s = 0x1999
            self.row = 0
            self.render()
            self.state = 10
        elif st == 10:
            if self._grow():
                self.cursor_to(self.ROWS[self.row])
        elif _std_open(self):
            pass
        elif st == 0x14:
            k = self.key()
            if k == K_CANCEL:
                sc.open(W_SUB)
                sc.focus = sc.wins.get(W_SUB)
                sc.close(W_DESC)
                sc.sound(SND_CANCEL)
            elif k == K_OK:
                sc.slot_sel = self.row
                sc.mode = 6
                sc.open(W_LIST, mode=6)
                sc.sound(SND_OK)
            elif k in (K_UP, K_DOWN):
                self.row = max(0, min(4, self.row + (-1 if k == K_UP else 1)))
                self.cursor_to(self.ROWS[self.row])
                self._desc()
                sc.sound(SND_CURSOR)
        elif st in (0x19, 0x1E):
            if st == 0x19:
                sc.open(W_DESC)
            sel = sc.equip_result
            m = sc.member
            if sel is not None:
                EQ.equip(m.ch, sc.slot_sel, None if sel == EQ.UNEQUIP else sel, sc.inv, m.name)
                sc.changed(m)
            sc.equip_result = None
            EQ.recompute_stats(m.ch)                     # exe 进 裝備 时也重算一次
            if W_STATS in sc.wins:
                sc.wins[W_STATS].state = 0x1E
            else:
                sc.open(W_STATS)
            self.render()
            self.cursor_to(self.ROWS[self.row])
            self._desc()
            self.state = 0x14
        elif st == 0x5A:
            self.render()
            self.state = 0x14
        elif st == 0x5F:
            self.render()
            self.cursor_to(self.ROWS[self.row])
            self._desc()
            self.state = 0x14
        if self.state == 0x6E:
            self.remove()


# ---------------- 12: 属性面板 ----------------
class StatsWin(Win):
    W, H = 288, 150

    def render(self) -> None:
        sc = self.sc
        m = sc.member
        ch = m.ch
        s = frame_surface(self.W, self.H)
        for x, y, t in ((12, 20, "生命："), (12, 40, "魔法："), (12, 60, "ＳＧ"), (0x90, 20, "等级："),
                        (0x90, 40, "经验值："), (0x90, 60, "下一级："), (12, 90, "力量："), (12, 110, "智慧："),
                        (12, 130, "敏捷："), (0x90, 90, "攻击："), (0x90, 110, "防御："), (0x90, 130, "幸运：")):
            draw_text(s, x, y, t, P_NORMAL)
        separator(s, 10, 0x4B, self.W - 20)
        i32 = EQ._i32
        draw_text(s, 0x34, 20, f"{i32(ch.CurrentHP):4d}/{i32(ch.MaxHP):4d}", P_NORMAL)
        draw_text(s, 0x34, 40, f"{i32(ch.CurrentMP):4d}/{i32(ch.MaxMP):4d}", P_NORMAL)
        if i32(ch.MaxMP) < 1:
            sg_gauge(s, 0x34, 60, i32(ch.SG), m.record == 6)
        draw_text(s, 0xD0, 20, f"{i32(ch.Level)}", P_NORMAL)
        draw_text(s, 0xD0, 40, f"{i32(ch.Exp)}", P_NORMAL)
        draw_text(s, 0xD0, 60, f"{i32(ch.nextExp)}", P_NORMAL)
        cur = EQ.current_stats(ch)
        new = sc.compare
        for i, (x, y) in enumerate(((0x38, 90), (0x38, 110), (0x38, 130), (0xC0, 90), (0xC0, 110), (0xC0, 130))):
            if new is None:
                draw_text(s, x, y, f"{cur[i]:4d}", P_NORMAL)
            else:
                pair = P_NORMAL if cur[i] == new[i] else (P_RED if new[i] < cur[i] else P_YELLOW)
                draw_text(s, x, y, f"{cur[i]:4d} {new[i]:4d}", pair)
        sc.compare = None                                # exe 画完即 memset 0x7b7cec
        self.surf = s

    def tick(self) -> None:
        st = self.state
        if st == 1:
            self.cx, self.cy = SCREEN_W // 2 - 0x120 + self.W // 2, SCREEN_H // 2 - 0x9B
            self.s = 0x1999
            self.sc.compare = None
            self.render()
            self.state = 10
        elif _std_open(self):
            pass
        elif st in (0x1E, 0x5A):
            self.render()
            self.state = 0x14
        if self.state == 0x6E:
            self.sc.compare = None
            self.remove()


# ---------------- 1 名字 / 14 金钱 / 13 说明 ----------------
class NameWin(Win):
    W, H = 100, 32

    def render(self) -> None:
        s = frame_surface(self.W, self.H)
        text_c(s, 0, 100, 16, self.sc.member.name)
        self.surf = s

    def tick(self) -> None:
        st = self.state
        if st == 1:
            self.cx, self.cy = SCREEN_W // 2 - self.W // 2, SCREEN_H // 2 - 0x38
            self.s = 0x1999
            self.render()
            self.state = 10
        elif _std_open(self):
            pass
        elif st == 0x1E:
            self.render()
            self.state = 0x14
        if self.state == 0x6E:
            self.remove()


class MoneyWin(Win):
    W, H = 100, 32

    def tick(self) -> None:
        st = self.state
        if st == 1:
            s = frame_surface(self.W, self.H)
            draw_text(s, 10, 16, f"{min(self.sc.money, 99999999):8d}", P_NORMAL)
            draw_text(s, 0x50, 0x10, "G", P_NORMAL)
            self.surf = s
            self.cx, self.cy = SCREEN_W // 2 - 0x120 + self.W // 2, SCREEN_H // 2 + 0x28
            self.s = 0x1999
            self.state = 10
        elif _std_open(self):
            pass
        if self.state == 0x6E:
            self.remove()


class DescWin(Win):
    W, H = 576, 40

    def render(self, text: str) -> None:
        s = frame_surface(self.W, self.H)
        if text:
            draw_text(s, 16, 20, text, P_NORMAL)
        self.surf = s

    def tick(self) -> None:
        st = self.state
        if st == 1:
            self.cx, self.cy = SCREEN_W // 2, SCREEN_H // 2 + 0xD2
            self.s = 0x1999
            self.render("")
            self.state = 10
        elif _std_open(self):
            pass
        elif st == 0x14 and self.sc.desc_pending is not None:
            self.render(self.sc.desc_pending)
            self.sc.desc_pending = None
        if self.state == 0x6E:
            self.remove()


# ---------------- 4: 道具列表 (mode 6 换装 / mode 2 道具) ----------------
class ListWin(Win):
    W, H = 256, 410
    VIS = 15

    def __init__(self, sc, idx, mode: int = 6) -> None:
        super().__init__(sc, idx)
        self.mode = mode
        self.entries: list[tuple[int, bool]] = []
        self.count = 0
        self.cursor = 0
        self.scroll = 0
        self.picked = -1
        self.title = ""

    def row_rect(self, r: int):
        return (self.W // 2 - 0x78, 0x24 + 0x18 * r, self.W // 2 + 100, 0x40 + 0x18 * r)

    def _build(self) -> None:
        sc = self.sc
        if self.mode == 6:
            self.entries = EQ.candidates(sc.member.ch, sc.member.record, sc.slot_sel, sc.inv)
        else:                                            # FUN_00423e2d(5): 分类 0 且 效果类型 & 4 (回复/药丸)
            self.entries = [(i, True) for i in range(EQ.ITEM_COUNT)
                            if sc.inv.count(i) > 0 and item_table_entry(i) is not None
                            and EQ.item_class(i) == 0 and (item_effect_type(i) & 4)]
        self.count = len(self.entries)

    def _item(self) -> int:
        return self.entries[self.cursor][0] if 0 <= self.cursor < self.count else -1

    def _desc(self) -> None:
        it = self._item()
        self.sc.desc_pending = item_desc(it) if 0 <= it < EQ.ITEM_COUNT else ""

    def _preview(self) -> None:
        sc = self.sc
        if self.count <= 0:
            return
        it = self._item()
        sc.compare = EQ.preview_stats(sc.member.ch, sc.slot_sel, None if it == EQ.UNEQUIP else it)
        if W_STATS in sc.wins:
            sc.wins[W_STATS].state = 0x5A

    def render(self) -> None:
        s = frame_surface(self.W, self.H)
        draw_text(s, 10, 20, self.title, P_YELLOW)
        inv = self.sc.inv
        for r in range(self.VIS):
            i = self.scroll + r
            if i >= self.count:
                break
            it, en = self.entries[i]
            y = 0x32 + 0x18 * r
            pair = P_NORMAL if en else P_GRAY
            if it == EQ.UNEQUIP:
                draw_text(s, 0x24, y, "解除装备", pair)
                continue
            icon(s, it, 0xC, y)
            draw_text(s, 0x24, y, get_item_name(it), pair)
            draw_text(s, 0xC4, y, f"{min(inv.count(it), 999):3d}", pair)
        if self.count > self.VIS:
            scrollbar(s, 0xF0, 0xDC, 0x15E, self.count - 1, self.cursor)
        self.surf = s

    def _move(self, k: int) -> bool:
        n = self.count
        c, top = self.cursor, self.scroll
        if n <= 0:
            return False
        if k == K_UP and c != 0:
            c -= 1
            top = min(top, c)
        elif k == K_DOWN and c != n - 1:
            c += 1
            if top + self.VIS <= c:
                top = c - (self.VIS - 1)
        elif k == K_PGUP and c != 0:
            c = min(n - 1, max(0, c - self.VIS))
            top = min(n - 1, max(0, top - self.VIS))
        elif k == K_PGDN and c != n - 1:
            c = min(n - 1, max(0, c + self.VIS))
            top = max(0, min(n - self.VIS, top + self.VIS))
        else:
            return False
        self.cursor, self.scroll = c, top
        self.row = c - top
        self.cursor_to(self.row_rect(self.row))
        self.render()
        self._desc()
        self.sc.sound(SND_CURSOR)
        return True

    def tick(self) -> None:
        sc = self.sc
        st = self.state
        if st == 1:
            self.cx, self.cy = SCREEN_W // 2 + 0xA0, SCREEN_H // 2 - 0xE6 + self.H // 2
            self.s = 0x1999
            self._build()
            if self.mode == 6:
                cls = min(sc.slot_sel, 3)
                self.cursor = max(0, min(self.count - 1, sc.list_mem[cls]))
                self.title = LIST_TITLES[sc.slot_sel]
                sc.equip_result = None
                if self.count == 0:
                    self.count = -1
                else:
                    self._preview()
            else:
                self.cursor = max(0, min(self.count - 1, sc.item_mem))
                self.title = "　道具"
            self.scroll = max(0, self.cursor - self.VIS + 1)
            self.render()
            self.state = 10
        elif st == 10:
            if self._grow():
                if self.mode != 6:
                    sc.open(W_DESC)
                self._desc()
                self.row = self.cursor - self.scroll
                self.cursor_to(self.row_rect(self.row))
        elif st == 0xF:
            if self._settle() and self.count < 0:
                self.picked = -1
                self.state = 100
                sc.sound(SND_CANCEL)
        elif st == 100:
            self._shrink()
        elif st == 0x14:
            k = self.key()
            if k == K_CANCEL:
                self.picked = -1
                self.state = 100
                sc.sound(SND_CANCEL)
            elif k == K_OK:
                if self.count > 0 and self.entries[self.cursor][1]:
                    self.picked = self.cursor
                    if self.mode == 6:
                        self.state = 100
                        sc.sound(SND_OK)
                    else:
                        self._use_item()
            elif k:
                self._move(k)
            if self.mode == 6 and self.focused() and sc.key in (K_UP, K_DOWN, K_PGUP, K_PGDN):
                self._preview()
        elif st == 0x5F:
            self.row = self.cursor - self.scroll
            self.cursor_to(self.row_rect(self.row))
            self.state = 0x14
        if self.state == 0x6E:
            self._closed()

    def _use_item(self) -> None:
        """mode 2: FUN_004246dd 对当前角色使用 (core.items.field_use), 成功才扣数量 + 刷新."""
        sc = self.sc
        from core.items import field_use
        it = self._item()
        res = field_use(sc.member.ch, it, [m.ch for m in sc.members])
        if res is None:
            return
        sc.inv.remove(it, 1)
        sc.changed(sc.member)
        sc.sound(SND_BUZZ)
        sc.sound(SND_HEAL)
        for w in (W_STATS, W_EQUIP):
            if w in sc.wins:
                sc.wins[w].state = 0x5A
        self._build()
        self.cursor = max(0, min(self.count - 1, self.cursor))
        self.scroll = max(0, min(self.scroll, self.cursor - self.VIS + 1 if self.cursor >= self.VIS else self.scroll))
        self.render()
        self.row = self.cursor - self.scroll
        self.cursor_to(self.row_rect(self.row))
        self._desc()

    def _closed(self) -> None:
        sc = self.sc
        if self.mode == 6:
            sc.list_mem[min(sc.slot_sel, 3)] = self.cursor
            sc.equip_result = None if self.picked < 0 else self.entries[self.picked][0]
            if W_EQUIP in sc.wins:
                sc.wins[W_EQUIP].state = 0x1E
            else:
                sc.open(W_EQUIP)
            sc.focus = sc.wins.get(W_EQUIP)
        else:
            sc.item_mem = self.cursor
            sc.open(W_SUB)
            sc.focus = sc.wins.get(W_SUB)
            sc.close(W_DESC)
        sc.mode = self.mode_prev
        self.remove()


# ---------------- 5: 特殊能力 (列表 + 说明; 场外施法未做) ----------------
class SkillWin(Win):
    W, H = 256, 410

    def __init__(self, sc, idx, mode: int = 2) -> None:
        super().__init__(sc, idx)
        self.mode = mode
        self.skills: list[int] = []
        self.enabled: list[bool] = []

    def row_rect(self, r: int):
        return (self.W // 2 - 0x78, 0x24 + 0x18 * r, self.W // 2 + 0x78, 0x40 + 0x18 * r)

    def _build(self) -> None:
        """FUN_0042878a: 角色表 +0x94 的 10 个已学技能; 场外只有 pattern&1 (回复类) 可用; MP/SG 够才亮."""
        from core.skill_table import SKILL_TABLE
        m = self.sc.member
        ch = m.ch
        sk = list(getattr(ch, "skills", []) or [])
        if not sk:
            from core.character_data import learned_skills
            sk = learned_skills(m.name, EQ._i32(ch.Level))
        sk = (sk + [-1] * 10)[:10]
        scale = 0x10000
        eq = EQ.equipped(ch)
        if 0xFA in eq:
            scale = 0x20000
        if 0xFB in eq:
            scale = 0x8000
        self.scale = scale
        steps = SG_STEPS.get(m.record, SG_STEPS_DEFAULT)
        self.skills, self.enabled = [], []
        for i, s in enumerate(sk):
            row = SKILL_TABLE.get(s)
            ok = False
            if s >= 0 and row is not None:
                if self.mode == 2 and not (row[2] & 1):
                    ok = False
                elif EQ._i32(ch.MaxMP) < 1:
                    ok = i < len(steps) and EQ._i32(ch.SG) >= steps[i]
                else:
                    ok = EQ._i32(ch.CurrentMP) >= _fx(row[5] * scale)
            self.skills.append(s)
            self.enabled.append(ok)

    def _desc(self) -> None:
        from core.skills import get_skill_desc
        s = self.skills[self.row] if self.skills else -1
        self.sc.desc_pending = get_skill_desc(s) if s >= 0 else ""

    def render(self) -> None:
        from core.skill_table import SKILL_TABLE
        from core.skills import get_skill_name
        s = frame_surface(self.W, self.H)
        draw_text(s, 10, 20, "特殊能力", P_NORMAL)
        for i, sk in enumerate(self.skills):
            if sk < 0:
                continue
            y = 0x32 + 0x18 * i
            pair = P_NORMAL if self.enabled[i] else P_GRAY
            draw_text(s, 0xC, y, get_skill_name(sk), pair)
            cost = SKILL_TABLE.get(sk, (0,) * 7)[5]
            if cost:
                draw_text(s, 0xD8, y, f"{_fx(cost * self.scale):3d}", pair)
        self.surf = s

    def tick(self) -> None:
        sc = self.sc
        st = self.state
        if st == 1:
            self.cx, self.cy = SCREEN_W // 2 + 0xA0, SCREEN_H // 2 - 0xE6 + self.H // 2
            self.s = 0x1999
            self._build()
            self.row = sc.skill_mem.get(sc.member.record, 0)
            self.render()
            self.state = 10
        elif st == 10:
            if self._grow():
                self.cursor_to(self.row_rect(self.row))
                sc.open(W_DESC)
                self._desc()
        elif _std_open(self):
            pass
        elif st == 0x14:
            k = self.key()
            if k == K_CANCEL:
                self.state = 100
                sc.sound(SND_CANCEL)
            elif k == K_OK:
                sc.sound(SND_BUZZ)                       # TODO 场外施法 (FUN_00428cf4 + 转盘选目标) 未做
            elif k in (K_UP, K_DOWN):
                d = -1 if k == K_UP else 1
                r = self.row + d
                while 0 <= r < 10 and self.skills[r] < 0:
                    r += d
                if 0 <= r < 10 and r != self.row:
                    self.row = r
                    self.cursor_to(self.row_rect(r))
                    self._desc()
                    sc.sound(SND_CURSOR)
        elif st == 0x5F:
            self._build()
            self.row = sc.skill_mem.get(sc.member.record, 0)
            self.render()
            self.cursor_to(self.row_rect(self.row))
            self._desc()
            self.state = 0x14
        if self.state == 0x6E:
            sc.skill_mem[sc.member.record] = self.row
            sc.open(W_SUB)
            sc.focus = sc.wins.get(W_SUB)
            sc.close(W_DESC)
            sc.mode = self.mode_prev
            self.remove()


_WIN_CLASSES = {W_NAME: NameWin, W_SUB: SubWin, W_TEAM: TeamWin, W_LIST: ListWin, W_SKILL: SkillWin,
                W_EQUIP: EquipWin, W_STATS: StatsWin, W_DESC: DescWin, W_MONEY: MoneyWin}


# ---------------- 场景 ----------------
class TeamInfoScene:
    """隊伍情報. members = [Member]; inv = 背包 (count/add/remove); 装备直接改 members[i].ch.
    on_change(member) 在换装/用道具后回调 (竞技场记忆装备用). 关闭后切回 return_scene."""

    # 跨次打开保留的光标记忆 (exe 全局: 0x7b8f0c 子菜单, 0x7b8f28[4] 各槽列表, 0x7b8f24 道具列表)
    _sub_row = 0
    _list_mem = [0, 0, 0, 0]
    _item_mem = 0

    def __init__(self, surface: pygame.Surface, audio, members: list[Member], inv, money: int,
                 return_scene, backdrop: pygame.Surface | None = None, start_index: int = 0,
                 on_change=None) -> None:
        self.surface = surface
        self.audio = audio
        self.members = members
        self.inv = inv
        self.money = int(money)
        self.return_scene = return_scene
        self.on_change = on_change
        self.next_scene = None
        self.cur = max(0, min(len(members) - 1, start_index))
        self.mode = -1                        # exe 0x54ca20
        self.wins: dict[int, Win] = {}
        self.order: list[Win] = []
        self.focus: Win | None = None
        self.cursor = Cursor()
        self.key = 0
        self._keys: list[int] = []
        self._held: dict[int, int] = {}
        self.slot_sel = 0
        self.equip_result = None
        self.compare = None
        self.desc_pending: str | None = None
        self.sub_row = TeamInfoScene._sub_row
        self.list_mem = TeamInfoScene._list_mem
        self.item_mem = TeamInfoScene._item_mem
        self.skill_mem: dict[int, int] = {}
        self.finished = False
        self._acc = 0
        self._frames: dict[int, tuple] = {}
        self.backdrop = self._dim(backdrop)
        if members:
            self.open(W_TEAM)
        else:                                   # 没人可看 → 直接返回
            self.finished = True

    # --- 生命周期 ---
    def on_enter(self) -> None:
        pass

    def on_exit(self) -> None:
        TeamInfoScene._sub_row = self.sub_row
        TeamInfoScene._item_mem = self.item_mem

    @property
    def member(self) -> Member:
        return self.members[self.cur]

    # --- 窗口管理 (FUN_0041da1b) ---
    def open(self, idx: int, **kw) -> None:
        w = self.wins.get(idx)
        if w is None:
            w = _WIN_CLASSES[idx](self, idx, **kw)
            self.wins[idx] = w
            self.order.append(w)
        else:
            w.state = 1
            for k, v in kw.items():
                setattr(w, k, v)
        if idx in _FOCUSABLE:
            self.focus = w
        if idx in _OPEN_SOUND:
            self.sound(SND_OPEN)

    def close(self, idx: int) -> None:
        w = self.wins.get(idx)
        if w is not None:
            w.state = 100

    def sound(self, sid: int) -> None:
        if self.audio is not None:
            try:
                self.audio.play_sfx_id(sid)
            except Exception:
                pass

    def changed(self, m: Member) -> None:
        if self.on_change is not None:
            self.on_change(m)

    # --- 立绘 ---
    def _sprite_res(self, m: Member) -> str | None:
        from core.grid_atlas_table import GRID_ATLAS
        rec = GRID_ATLAS.get(8 * (m.record + 1))          # exe 0x53c764[角色] = 8*(角色+1)
        if rec:
            return rec[0]
        try:
            from core.character_sprites import sprite_resource
            return sprite_resource(m.name)
        except Exception:
            return None

    def _load_frame(self, m: Member):
        if m.record in self._frames:
            return self._frames[m.record]
        out = (None, (32, 82))
        res = self._sprite_res(m)
        if res:
            try:
                from core.grid_atlas_table import GRID_ATLAS
                from core.sprites.loaders import get_character_sprite
                sheet = get_character_sprite(res).sheet
                anchor = next(((v[3], v[4]) for v in GRID_ATLAS.values() if v[0] == res), (32, 82))
                fr = sheet.frame(6 % sheet.cols, 6 // sheet.cols)        # 网格帧 6 = 正面站姿
                out = (fr, anchor)
            except Exception:
                pass
        self._frames[m.record] = out
        return out

    def stand_frame(self, m: Member):
        return self._load_frame(m)[0]

    def anchor_of(self, m: Member):
        return self._load_frame(m)[1]

    # --- 背景 (FUN_0041d429: 截屏后隔点涂黑) ---
    @staticmethod
    def _dim(src: pygame.Surface | None) -> pygame.Surface:
        out = pygame.Surface((SCREEN_W, SCREEN_H))
        out.fill(BLACK)
        if src is None:
            return out
        out.blit(src, (0, 0))
        try:
            arr = pygame.surfarray.pixels3d(out)
            arr[0::2, 0::2] = 0
            arr[1::2, 1::2] = 0
            del arr
        except Exception:
            pass
        return out

    # --- 输入 ---
    def handle_event(self, event: pygame.event.Event) -> bool:
        if event.type == pygame.QUIT:
            return False
        if event.type == pygame.KEYDOWN:
            k = _KEYMAP.get(event.key)
            if k:
                self._keys.append(k)
                if k in _REPEATABLE:
                    self._held[event.key] = pygame.time.get_ticks() + REPEAT_DELAY_MS
        elif event.type == pygame.KEYUP:
            self._held.pop(event.key, None)
        return True

    def _poll_repeat(self) -> None:
        now = pygame.time.get_ticks()
        for key, due in list(self._held.items()):
            if now >= due:
                self._keys.append(_KEYMAP[key])
                self._held[key] = due + REPEAT_MS

    # --- 更新 ---
    def update(self, dt_ms: int) -> None:
        self._poll_repeat()
        self._acc += dt_ms
        n = 0
        while self._acc >= TICK_MS and n < 4:
            self._acc -= TICK_MS
            n += 1
            self.step()
        if self._acc > TICK_MS * 4:
            self._acc = 0

    def step(self) -> None:
        """一个原版 tick: 光标实体先走, 再按创建顺序跑各窗口."""
        self.key = self._keys.pop(0) if self._keys else 0
        self.cursor.tick()
        for w in list(self.order):
            if not w.dead:
                w.tick()
        self.order = [w for w in self.order if not w.dead]
        if self.finished and self.next_scene is None:
            self.next_scene = self.return_scene

    # --- 渲染 ---
    def draw(self) -> None:
        self.surface.blit(self.backdrop, (0, 0))
        for w in self.order:
            w.draw(self.surface)
        self.cursor.draw(self.surface)


# ---------------- 入口: 世界地图 / 竞技场 ----------------
def members_from_save(save) -> list[Member]:
    """存档出场名单 (0xBF8/0xBFC; 重制版存档无名单时按在队角色)."""
    from core.character import CHARACTER_NAMES
    slots: list[int] = []
    try:
        from core.save_manager import party_slots
        slots = party_slots(save)
    except Exception:
        slots = []
    if not slots:
        from core.party import NAME_TO_SLOT, active_party
        slots = [NAME_TO_SLOT[n] for n in active_party(save) if NAME_TO_SLOT.get(n) is not None]
    return [Member(CHARACTER_NAMES.get(s, f"#{s}"), save.characters[s], s)
            for s in slots if s in save.characters]


def open_from_world(world) -> TeamInfoScene:
    save = world.save
    backdrop = None
    try:
        backdrop = world._capture_backdrop()
    except Exception:
        pass
    return TeamInfoScene(world.surface, world.audio, members_from_save(save), save.inventory,
                         getattr(save, "money", 0), world, backdrop=backdrop)
