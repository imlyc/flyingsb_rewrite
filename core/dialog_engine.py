"""原版对白气泡引擎 (wh/dlgbox.cpp 逆向移植, 纯逻辑, 不画).

原版一句台词 = 一个挂在角色身上的**气泡任务** (FUN_0045b173 → think FUN_004516a7), 文本本身是
小脚本: 标签 (FUN_0044fa05 解析) 控制分页/等待/同步/动作. 和事件主脚本之间用一个 32 项的
**消息环** (0x7af598, FUN_004071b5 post / 4072b0 find / 407451 take) 对表:

  文本 `<$010>`      → post(key='010', sub=我的代号, flags=0)    主脚本 71.01 ['010', ..] 等它
  文本 `<$=DIT>`+`<$>` → 对手 = DIT; `<$>` = post(key=DIT, sub=我) "该你说了"; 对方文本里的 `/` 收到后继续
  文本 `/` / `<#L>`  → 等一条 key=我的代号 (sub=L 或任意) 的消息  主脚本 71.05 [L, 代号] 发它
  文本 `<$X->`       → post(key=X, .., flags=1)  → X 的气泡收到后关窗 (`!`/`?`/`^` 是图标/汗)
  文本 `<$X:n>`      → post(key=X, .., n|0x8000) → X 的"说话"子脚本 (71.03) 取走 → 换姿势
  主脚本 71.07 [X,n] → 同上 (sub=-1); 71.04 [L, X, f] → post(X, L, f)

标签语义 (token 号 = 原版 FUN_0044fa05 的返回值):
  `@@` 新气泡 (按到下一个 @@ 为止的文字量测框)   `;` 翻页 (等按键 / 事件里自动延时)   `|` 换行
  `<->` 关窗  `<+>` 开窗  `<Dn>` 停 n×100ms  `<W=n>`/`<W±n>` 打字速度 (ms/字)  `*..*` 高亮
  `<possub_U/D/L/R>` 气泡位置偏好 (小键盘数字序列 8642 等)  `<WIDTHxx>` 宽度档  `<CSn>` 脸
  `<DIRn[:x]>` 转向  `<WALKd,n[:x]>` 走  `<W?>` 等动作完  `<SEn>` 音效  `<BGMn>` 换曲
  `<WA>` 等动作完  `<TRANS>/<SOLID>` 窗样式  `<FnT/B>` 字号  `<B>/<T>` 粗体  `<PUSH>/<POP>` 存/取样式
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Callable

# ---------------------------------------------------------------- 消息环 (0x7af598)
# ---------------------------------------------------------------- 快进 (原版按住 Shift)
# exe 的键盘钩子 FUN_0040f025 把 Shift 状态写到 DAT_00742350, 脚本/气泡各处直接读它:
#   等待 op (ctx+0x40) 一律改成 1 帧; 等按键 (FUN_00457173) 视为已按; 镜头/位移补间
#   (FUN_0049a66c/0049aa5b/0049a818) 直接到位. 不是"倍速", 是把所有停顿和补间跳掉.
_FAST = [False]


def set_fast(on: bool) -> None:
    _FAST[0] = bool(on)


def fast_forward() -> bool:
    return _FAST[0]


class MessageQueue:
    """[key, sub, flags, sender] 列表; 原版是 32 项环, 这里不限长 (语义一致)."""

    def __init__(self) -> None:
        self.entries: list[list[int]] = []

    def post(self, key: int, sub: int, flags: int, sender: int = 0) -> None:
        self.entries.append([key & 0xFFFFFFFF, sub & 0xFFFFFFFF, flags & 0xFFFFFFFF, sender])

    def find(self, key: int, sub: int = 0, start: int = 0) -> int:
        """FUN_004072b0: key 相同 (sub 非 0 时也要相同), 且不是 0x8000 命令消息."""
        key &= 0xFFFFFFFF
        sub &= 0xFFFFFFFF
        for i in range(start, len(self.entries)):
            e = self.entries[i]
            if e[0] == key and (sub == 0 or e[1] == sub) and not (e[2] & 0x8000):
                return i
        return -1

    def find_cmd(self, key: int) -> int:
        """FUN_00407367: key 相同且带 0x8000 的命令消息 (姿势号)."""
        key &= 0xFFFFFFFF
        for i, e in enumerate(self.entries):
            if e[0] == key and (e[2] & 0x8000):
                return i
        return -1

    def take(self, i: int) -> list[int]:
        return self.entries.pop(i)

    def take_match(self, key: int, sub: int, flags: int) -> bool:
        """FUN_00407550: 找 (key, sub) 且 flags 相等的消息, 取走; 没有 → False."""
        i = 0
        while True:
            i = self.find(key, sub, i)
            if i < 0:
                return False
            if self.entries[i][2] == flags & 0xFFFFFFFF:
                self.take(i)
                return True
            i += 1

    def clear(self) -> None:
        self.entries.clear()


def code_of(s: str) -> int:
    """'MIRO' → 0x4D49524F (原版多字符常量, 高位在前; FUN_00451629 同样左移拼)."""
    v = 0
    for ch in s[:4]:
        v = (v << 8) | (ord(ch) & 0xFF)
    return v


def code_str(v: int) -> str:
    out = ""
    while v:
        out = chr(v & 0xFF) + out
        v >>= 8
    return out


# ---------------------------------------------------------------- 标签解析 (FUN_0044fa05)
# possub 代号: 十进制各位 = 小键盘方位偏好序 (8 上 2 下 4 左 6 右 5 正中, 7/9/1/3 斜角)
POSSUB = {"U": 8642, "D": 2468, "L": 4826, "R": 6284, "UL": 825, "DL": 258, "UR": 582, "DR": 285,
          "LU": 852, "RU": 528, "LD": 50, "RD": 5}
POSSUB_BY_DIR = {0: 462, 1: 864, 2: 628, 3: 842}          # FUN_0045b0be: 按角色朝向的默认偏好
WIDTH_CLASS = {"S": 0, "M": 1, "L": 2, "XL": 3, "HUGE": 4, "MAX": 5}
WIDTH_COLS = {0: 10, 1: 14, 2: 18, 3: 22, 4: 26, 5: 30}      # 每档最多全角字数 (近似原版表 0x6126a0)
DIR_DIGIT = {1: 5, 2: 1, 3: 7, 4: 2, 6: 3, 7: 6, 8: 0, 9: 4}  # FUN_0049bb05: 小键盘数字 → 朝向码

_NUM = re.compile(r"\d+")


@dataclass
class Tok:
    kind: str
    a: int | str = 0
    b: int = 0


def _code_at(s: str, i: int) -> tuple[int, int]:
    """FUN_00451629: 最多 4 个 [A-Za-z0-9_] → 多字符常量; 返回 (值, 长度)."""
    j = i
    v = 0
    while j < len(s) and j - i < 4 and (s[j].isalnum() or s[j] == "_"):
        v = (v << 8) | (ord(s[j]) & 0xFF)
        j += 1
    return v, j - i


def tokenize(text: str) -> list[Tok]:
    """原文 (已从 Big5 解码的 str) → token 列表. 未识别标签整体丢弃."""
    out: list[Tok] = []
    i, n = 0, len(text)
    while i < n:
        c = text[i]
        if c == "<":
            j = text.find(">", i)
            if j < 0:
                i += 1
                continue
            body = text[i + 1:j]
            tok = _parse_tag(body)
            if tok is not None:
                out.append(tok)
            i = j + 1
            continue
        if c == "@":
            if i + 1 < n and text[i + 1] == "@":
                out.append(Tok("box"))
                i += 2
            else:
                out.append(Tok("cr"))
                i += 1
            continue
        if c == ";":
            out.append(Tok("page"))
        elif c == "|":
            out.append(Tok("nl"))
        elif c == "/":
            out.append(Tok("wait_msg", 0))
        elif c == "*":
            out.append(Tok("hl"))
        elif c == "^":
            out.append(Tok("emph"))
        elif c == "~":
            out.append(Tok("char", "　" if ord(c) < 0x80 and False else " "))  # 原版 '~' = 半角空位
        else:
            out.append(Tok("char", c))
        i += 1
    out.append(Tok("end"))
    return out


def _parse_tag(body: str) -> Tok | None:
    u = body.upper()
    if not u:
        return None
    if u == "-":
        return Tok("close")
    if u == "+":
        return Tok("open")
    if u == "!":
        return Tok("excl", 1)
    if u == "!-":
        return Tok("excl", 0)
    if u == "?":
        return Tok("arrow", 1)
    if u == "?-":
        return Tok("arrow", 0)
    if u.startswith("#"):
        rest = body[1:]
        if rest == "?":
            return Tok("wait_msg", 0)
        v, ln = _code_at(rest, 0)
        return Tok("wait_msg", v if v else -1)
    if u.startswith("$"):
        rest = body[1:]
        if rest.startswith("="):
            v, _ = _code_at(rest, 1)
            return Tok("setname", v)
        v, ln = _code_at(rest, 0)
        tail = rest[ln:]
        if tail == "":
            return Tok("post", v, 0)
        if tail == "-":
            return Tok("post", v, 1)
        if tail == "!":
            return Tok("post", v, 0x10)
        if tail == "!-":
            return Tok("post", v, 0x20)
        if tail == "?":
            return Tok("post", v, 0x40)
        if tail == "?-":
            return Tok("post", v, 0x80)
        if tail == "^":
            return Tok("post", v, 2)
        if tail.startswith(":"):
            m = _NUM.match(tail, 1)
            if m:
                return Tok("post", v, int(m.group()) | 0x8000)
        return None
    if u.startswith("POSSUB_"):
        return Tok("possub", POSSUB.get(u[7:], 8642))
    if u.startswith("POS"):
        m = _NUM.match(u, 3)
        if m:
            return Tok("pos", int(m.group()), int(u.endswith("H")))
        return None
    if u.startswith("WIDTH"):
        return Tok("width", WIDTH_CLASS.get(u[5:], 1))
    if u.startswith("WALK"):
        m = re.match(r"WALK(\d),(\d+)(?::(\d+))?$", u)
        if m:
            return Tok("walk", (DIR_DIGIT.get(int(m.group(1)), 1) << 16) | int(m.group(2)),
                       int(m.group(3) or 0))
        return None
    if u.startswith("DIR"):
        m = re.match(r"DIR(\d)(?::(\d+))?$", u)
        if m:
            return Tok("dir", DIR_DIGIT.get(int(m.group(1)), 1), int(m.group(2) or 0))
        return None
    if u == "W?":
        return Tok("wait_task")
    if u.startswith("W=") or u.startswith("W+") or u.startswith("W-"):
        m = _NUM.match(u, 2)
        if m:
            v = int(m.group())
            return Tok("speed", v if u[1] == "=" else (v if u[1] == "+" else -v), int(u[1] != "="))
        return None
    if u == "WA":                       # 等上一个动作 (<DIRn>/<WALK>) 做完: 全库 1237 处, 758 处紧跟 <DIR>
        return Tok("wait_task")
    if u == "TRANS":
        return Tok("style", 0)
    if u == "SOLID":
        return Tok("style", 2)
    if u == "PAPER":
        return Tok("style", 4)
    if u.startswith("D") and u[1:].isdigit():
        return Tok("delay", int(u[1:]) * 100)
    if u.startswith("CS") and u[2:].isdigit():
        return Tok("face", int(u[2:]))
    if u.startswith("SE") and u[2:].isdigit():
        return Tok("sound", int(u[2:]))
    if u.startswith("BGM") and u[3:].isdigit():
        return Tok("bgm", int(u[3:]))
    if u == "B":
        return Tok("bold", 1)
    if u == "T":
        return Tok("bold", 0)
    if u == "FAST":
        return Tok("fast", 1)
    if u == "FAST-":
        return Tok("fast", 0)
    if re.match(r"F\d[TB]?$", u):
        return Tok("font", int(u[1]), {"T": 1, "B": 2}.get(u[2:], 0))
    if u == "PUSH":
        return Tok("push")
    if u == "POP":
        return Tok("pop")
    if u == "SWEAT":
        return Tok("sweat")
    if u == "TAIL":
        return Tok("tail", 1)
    if u == "TAILX":
        return Tok("tail", 0)
    if u.startswith("INDENT") and u[6:].isdigit():
        return Tok("indent", int(u[6:]))
    if u.startswith("HMAX") and u[4:].isdigit():
        return Tok("hmax", int(u[4:]))
    if u.startswith("MSG_ID"):
        v, _ = _code_at(body, 7)
        return Tok("msgid", v)
    if u.startswith("EVENTTITLE"):
        return Tok("title", body[10:].strip())
    return None


# ---------------------------------------------------------------- 气泡任务
class DialogHost:
    """气泡要做的演出回调; 事件 Host 可直接复用 (方法名一致)."""

    def fc_turn(self, fc: int, d: int, x: int) -> int: return 0
    def fc_walk(self, fc: int, d: int, n: int, mode: int, x: int) -> int: return 0
    def task_alive(self, hd: int) -> bool: return False
    def sound(self, sid: int) -> None: ...
    def bgm(self, n: int | None, fade_frames: int = 0) -> None: ...
    def dialog_event(self, dlg: "DialogTask", what: str) -> None: ...   # open/close/page/char/end


@dataclass
class Page:
    lines: list[str] = field(default_factory=list)
    runs: list[list[tuple[str, bool]]] = field(default_factory=list)   # 与 lines 对应: [(字, 高亮)]


class DialogTask:
    """一个气泡. 每帧 tick(dt_ms); 状态供场景渲染."""

    TICK_MS = 25
    OPEN_MS = 160
    CLOSE_MS = 120
    PUNCT_EXTRA = {" ": 2.0, "!": 13.0, ",": 7.0, ".": 1.0, "?": 17.0, "，": 8.0, "。": 19.0, "…": 4.0}

    def __init__(self, text: str, fc: int, code: int, mq: MessageQueue, host: DialogHost,
                 handle: int = 0, facing: int = 1, auto_delay_ms: int = 0, speed_ms: int = 25) -> None:
        self.text = text
        self.toks = tokenize(text)
        self.fc = fc
        self.code = code & 0xFFFFFFFF
        self.mq = mq
        self.host = host
        self.handle = handle
        self.pos = 0
        self.alive = True
        self.finished = False
        # 显示状态
        self.box_state = "closed"           # closed / opening / open / closing
        self.box_t = 0.0                    # 开/关进度 0..1
        self.pages: list[Page] = [Page()]
        self.possub = POSSUB_BY_DIR.get(facing, 852)
        self.width_class = 1
        self.style = 1
        self.face = -1
        self.bold = 0
        self.font = 2
        self.hl = False
        self.emph = False
        self.partner = 0                    # dlg+0x164: `<$=X>` 设的对手代号; `<$>` 发给它, `<#>` 等它
        self.arrow = 0
        self.excl = 0
        self.sweat = 0
        self.indent = 0
        self.anchor_dx = 0                  # 89.00: 气泡锚点偏移 (像素)
        self.anchor_dy = 0
        self.box_cols = 0
        self.box_rows = 0
        self.speed_ms = speed_ms
        self.auto_delay_ms = auto_delay_ms   # ';' 自动翻页延时 (DAT_007d70d8*100); 0 = 等按键
        self.fast = False
        self.flag_stack: list[tuple] = []
        # 等待
        self.wait_kind: str | None = None   # key / msg / task / delay / box
        self.wait_sub = 0
        self.wait_ms = 0.0
        self.wait_task = 0
        self.char_ms = 0.0                  # 下一个字前还要等的毫秒
        self.key_latch = False
        self.page_pending = False           # ';' 翻页后先留着旧页, 下一个字到了才换新页 (等对手时不显示空框)
        self.last_task = 0
        self.after_close: str | None = None  # 关窗后动作: 'reopen' / 'end' / None
        self.transcript: list[str] = []     # 每个气泡段落 (@@ 换框 / 关窗 时归档) 的全文, 调试/测试用
        self.log: list[str] = []

    # ---- 对外 ----
    def press_key(self) -> None:
        self.key_latch = True

    def visible(self) -> bool:
        return self.box_state != "closed"

    def cur_page(self) -> Page:
        return self.pages[-1]

    def kill(self) -> None:
        self._archive()
        self.alive = False
        self.finished = True
        self.box_state = "closed"
        self.host.dialog_event(self, "end")

    # ---- 量测 (FUN_0044f386/0044f517): 到下一个 @@ 为止的文字, 最宽行 × 最多行 ----
    def _measure(self) -> None:
        cols = 0
        rows = 1
        maxcols = WIDTH_COLS.get(self.width_class, 14)
        cur = 0
        i = self.pos
        page_rows = 1
        while i < len(self.toks):
            t = self.toks[i]
            if t.kind in ("box", "end"):
                break
            if t.kind == "char":
                cur += 1 if ord(t.a) > 0x7F else 0.5
                if cur > maxcols:
                    cur = 1
                    page_rows += 1
                cols = max(cols, cur)
            elif t.kind == "nl":
                cur = 0
                page_rows += 1
            elif t.kind == "page":
                rows = max(rows, page_rows)
                page_rows = 1
                cur = 0
            i += 1
        rows = max(rows, page_rows)
        self.box_cols = max(2, int(cols + 0.999))
        self.box_rows = max(1, rows)

    # ---- 帧步进 ----
    def tick(self, dt_ms: float) -> None:
        if not self.alive or self.finished:
            return
        # 开/关动画
        if self.box_state == "opening":
            self.box_t = min(1.0, self.box_t + dt_ms / self.OPEN_MS)
            if self.box_t >= 1.0:
                self.box_state = "open"
            return
        if self.box_state == "closing":
            self.box_t = max(0.0, self.box_t - dt_ms / self.CLOSE_MS)
            if self.box_t <= 0.0:
                self.box_state = "closed"
                act, self.after_close = self.after_close, None
                if act == "end":
                    self.kill()
                    return
                if act == "reopen":
                    self._open_box()
            return
        # 等待类
        if self.wait_kind == "delay":
            self.wait_ms -= dt_ms
            if self.wait_ms > 0 and not fast_forward():
                return
            self.wait_kind = None
        elif self.wait_kind == "key":
            if self.auto_delay_ms > 0:
                self.wait_ms -= dt_ms
            if self.key_latch or fast_forward() or (self.auto_delay_ms > 0 and self.wait_ms <= 0):
                self.key_latch = False
                self.wait_kind = None
                self._next_page()
            else:
                return
        elif self.wait_kind == "msg":
            if not self._poll_msg():
                return
        elif self.wait_kind == "task":
            if self.host.task_alive(self.wait_task):
                return
            self.wait_kind = None
        self.key_latch = False
        # 打字节奏
        if self.char_ms > 0:
            self.char_ms -= dt_ms
            if self.char_ms > 0:
                return
        budget = 64 if (self.fast or fast_forward()) else 1
        while budget > 0 and self.wait_kind is None and self.box_state in ("open", "closed") \
                and self.alive and not self.finished:
            if self._step():
                budget -= 1

    def _poll_msg(self) -> bool:
        i = self.mq.find(self.code, 0)
        while i >= 0:
            e = self.mq.entries[i]
            if (e[2] & 0xFF) == 0:
                if self.wait_sub == 0 or e[1] == self.wait_sub & 0xFFFFFFFF:
                    self.mq.take(i)
                    self.wait_kind = None
                    return True
                i = self.mq.find(self.code, 0, i + 1)
                continue
            f = e[2]
            self.mq.take(i)
            if f & 1:
                self._close_box(None)
            if f & 2:
                self.sweat = 1
            if f & 0x10:
                self.excl = 1
            if f & 0x20:
                self.excl = 0
            if f & 0x40:
                self.arrow = 1
            if f & 0x80:
                self.arrow = 0
            i = self.mq.find(self.code, 0)
        return False

    def _archive(self) -> None:
        txt = self.text_so_far()
        if txt:
            self.transcript.append(txt)

    def _open_box(self) -> None:
        self._archive()
        self._measure()
        self.pages = [Page()]
        self.page_pending = False
        self.box_state = "opening"
        self.box_t = 0.0
        self.host.dialog_event(self, "open")

    def _close_box(self, after: str | None) -> None:
        if self.box_state == "closed":
            if after == "end":
                self.kill()
            elif after == "reopen":
                self._open_box()
            return
        self.box_state = "closing"
        self.after_close = after
        self.host.dialog_event(self, "close")

    def _next_page(self) -> None:
        self.page_pending = True
        self.host.dialog_event(self, "page")

    def _fresh_page(self) -> None:
        if self.page_pending:
            self.page_pending = False
            self.pages.append(Page())

    def _put_char(self, ch: str) -> None:
        self._fresh_page()
        pg = self.cur_page()
        if not pg.lines:
            pg.lines.append("")
        maxcols = WIDTH_COLS.get(self.width_class, 14)
        width = sum(1 if ord(c) > 0x7F else 0.5 for c in pg.lines[-1])
        if width + (1 if ord(ch) > 0x7F else 0.5) > maxcols:
            pg.lines.append("")
        while len(pg.runs) < len(pg.lines):
            pg.runs.append([])
        pg.lines[-1] += ch
        pg.runs[-1].append((ch, self.hl))
        base = self.speed_ms * (1.0 if ord(ch) > 0x7F else 0.5)
        self.char_ms = base * (1.0 + self.PUNCT_EXTRA.get(ch, 0.0))
        if ch == "." or ch == "．":
            self.char_ms = base * 2.0
        self.host.dialog_event(self, "char")

    def _step(self) -> bool:
        """执行一个 token; 返回 True 表示是"显示了一个字"(计打字预算)."""
        if self.pos >= len(self.toks):
            self._close_box("end")
            return False
        t = self.toks[self.pos]
        self.pos += 1
        k = t.kind
        if k == "char":
            if self.box_state == "closed":
                self.pos -= 1
                self._open_box()
                return False
            self._put_char(t.a)
            return True
        if k == "end":
            self.pos -= 1
            self._close_box("end")
            return False
        if k == "box":
            if self.box_state == "closed":
                self._open_box()
            else:
                self._close_box("reopen")
            return False
        if k == "page":
            self.wait_kind = "key"
            self.wait_ms = float(self.auto_delay_ms)
            self.key_latch = False
            return False
        if k == "nl":
            self._fresh_page()
            pg = self.cur_page()
            if not pg.lines:
                pg.lines.append("")
            pg.lines.append("")
            return False
        if k == "cr":
            pg = self.cur_page()
            if pg.lines and pg.lines[-1] == "":
                pass
            return False
        if k == "close":
            self._close_box(None)
            return False
        if k == "open":
            if self.box_state == "closed":
                self._open_box()
            return False
        if k == "wait_msg":                 # '/' 等任意; <#L> 等 sub=L; <#> 等 sub=对手
            self.wait_kind = "msg"
            self.wait_sub = 0 if t.a == 0 else (self.partner if t.a == -1 else int(t.a))
            self._poll_msg()
            return False
        if k == "post":                     # <$L..> 发给 L; <$> 发给对手 (FUN_00457264: 0 → dlg+0x164)
            key = int(t.a) if t.a else (self.partner or self.code)
            self.mq.post(key, self.code, int(t.b), self.handle)
            return False
        if k == "setname":
            self.partner = int(t.a)
            return False
        if k == "delay":
            self.wait_kind = "delay"
            self.wait_ms = float(t.a) if not (self.fast or fast_forward()) else 0.0
            return False
        if k == "speed":
            self.speed_ms = max(0, self.speed_ms + int(t.a)) if t.b else int(t.a)
            return False
        if k == "possub":
            self.possub = int(t.a)
            return False
        if k == "width":
            self.width_class = int(t.a)
            return False
        if k == "style":
            self.style = int(t.a)
            return False
        if k == "face":
            self.face = int(t.a)
            return False
        if k == "bold":
            self.bold = int(t.a)
            return False
        if k == "font":
            self.font = int(t.a)
            return False
        if k == "hl":
            self.hl = not self.hl
            return False
        if k == "emph":
            self.emph = not self.emph
            return False
        if k == "fast":
            self.fast = bool(t.a)
            return False
        if k == "push":
            self.flag_stack.append((self.bold, self.font, self.hl, self.style))
            return False
        if k == "pop":
            if self.flag_stack:
                self.bold, self.font, self.hl, self.style = self.flag_stack.pop()
            return False
        if k == "dir":
            self.last_task = self.host.fc_turn(self.fc, int(t.a), int(t.b))
            return False
        if k == "walk":
            d, n = int(t.a) >> 16, int(t.a) & 0xFFFF
            self.last_task = self.host.fc_walk(self.fc, d, n, 0, int(t.b))
            return False
        if k == "wait_task":
            if self.last_task and self.host.task_alive(self.last_task):
                self.wait_kind = "task"
                self.wait_task = self.last_task
            return False
        if k == "sound":
            self.host.sound(int(t.a))
            return False
        if k == "bgm":
            self.host.bgm(int(t.a))
            return False
        if k == "sweat":
            self.sweat = 1
            return False
        if k == "arrow":
            self.arrow = int(t.a)
            return False
        if k == "excl":
            self.excl = int(t.a)
            return False
        if k == "msgid":
            self.code = int(t.a) & 0xFFFFFFFF
            return False
        return False

    # ---- 调试 ----
    def text_so_far(self) -> str:
        return " / ".join("|".join(p.lines) for p in self.pages if p.lines)
