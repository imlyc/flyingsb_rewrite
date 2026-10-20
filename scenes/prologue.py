"""序章演出: 跑原版事件脚本 (core.event_script) 的"舞台".

导演 = 原版字节码 (事件 0..9, assets/script/events.json), 这里只实现 EventHost 的演出回调:
  · 真实地图 (core.real_map) + 2.5D 逐行遮挡 (与世界地图同一套画法)
  · 演员 = FC 对象: 角色图集 (ps_*.png, 6×4 帧, 行=朝向) 或 fm 帧 (fm_*.png, 逐帧 bbox/anchor),
    像素级位置 (原版 +8/+0xc 16.16 像素), 偏移 (+0x20 组: 漂浮/下落), 跳/飞的补间
  · 镜头 (格中心 + 帧数补间 / 跟随), 视口黑边 (90.06/07), 调色板渐变 (黑/白叠层),
  · 气泡对白 (core.dialog_engine, 挂在角色头上, 小键盘方位偏好), BGM / 音效
按键: Enter/空格 翻页 (事件里气泡会自动翻), ESC 跳过整个序章.
"""
from __future__ import annotations

import json
import math
from pathlib import Path

import pygame

from core import bgm_table, real_map as realm
from core.dialog_engine import DialogTask, code_str, fast_forward, set_fast
from core.event_script import EventHost, EventRunner, ScriptBundle
from core.fm_frames import FM_FRAMES
from core.sprites.base import TILE_H, TILE_W, load_image
from scenes.base import Scene
from scenes.menu import load_chinese_font

ROOT = Path(__file__).resolve().parent.parent
SPRITES = ROOT / "assets" / "sprites"
FC_TABLES = ROOT / "assets" / "fc_tables.json"
TICK_MS = 25                      # 1 原版 tick: 主循环受渲染限制, Wine 实测 24.5ms (见 project_frame_timing)
FIRST_EVENT = 0
LAST_EVENT = 9                    # 序章链 ev0..ev9 (之后玩家接管)

DIR_ROWS = (0, 1, 2, 3, 3, 2, 2, 3)          # 0x65302C: 朝向 → 图集行 (0 背 1 正 2 左 3 右), 走路动画用
STAND_FRAME = (0, 6, 12, 18, 5, 11, 17, 23)  # FUN_00498ed1: 朝向 → 站立帧 (斜向 4..7 = 各行第 5 格)
# 8 向 (0 上 1 下 2 左 3 右 4 右上 5 左下 6 左上 7 右下, 与坡道朝向码/站立帧表一致) → 格位移
DIR_DELTA = {0: (0, -1), 1: (0, 1), 2: (-1, 0), 3: (1, 0), 4: (1, -1), 5: (-1, 1), 6: (-1, -1), 7: (1, 1)}


def available() -> bool:
    return (ROOT / "assets" / "script" / "events.json").exists() and FC_TABLES.exists() \
        and realm.is_available("TCL0___P")


# ---------------------------------------------------------------- 演员
class Actor:
    """一个 FC 对象 (原版 0x1ac 的对象槽的演出子集)."""

    def __init__(self, fc: int, base_sheet: int) -> None:
        self.fc = fc
        self.base_sheet = base_sheet      # FC 定义表 +0x38 / 58.00 的图集基号
        self.visible = False
        self.px = 0.0                     # 像素位置 (脚点), 原版 +8/+0xc
        self.py = 0.0
        self.z = 0                        # 层 (+0x1c)
        self.dir = 1                      # +0x110
        self.dir_target = 1               # +0x114
        self.off = [0.0, 0.0, 0.0]        # +0x20 组: 绘制偏移 (像素)
        self.off_from = [0.0, 0.0, 0.0]
        self.off_to = [0.0, 0.0, 0.0]
        self.off_ticks = 0
        self.off_total = 0
        self.mode = 2                     # 0 fm 组 / 1 绝对图集 / 2 基号+变体
        self.sheet = 0                    # mode 0: fm 组号; 1: 图集号; 2: 变体
        self.frame = 6                    # 帧号 (图集内 row*cols+col / fm 组内序号)
        self.motion = None                # 跳/飞补间: dict(kind, t, n, ...)
        self.spawned = False
        self.reserved: tuple[int, int] | None = None   # 正在走的那一步的目标格 (原版起步时就占格, 别人不能再进)

    @property
    def tx(self) -> int:
        return int(self.px // TILE_W)

    @property
    def ty(self) -> int:
        return int(self.py // TILE_H)

    def place(self, x: int, y: int, z: int, d: int) -> None:
        self.px = x * TILE_W + TILE_W / 2
        self.py = y * TILE_H + TILE_H / 2
        self.motion = None
        self.off_ticks = 0
        self.reserved = None
        if 0 <= z <= 1:
            self.z = z
        if 0 <= d <= 7:
            self.set_dir(d)

    def set_dir(self, d: int) -> None:
        self.dir = d & 7
        self.dir_target = self.dir
        if self.mode == 2 and self.sheet == 0:
            self.frame = STAND_FRAME[self.dir]

    def tick(self) -> None:
        if fast_forward():                 # Shift: 位移/跳跃补间直接到位 (FUN_0049a818 置 0x754e)
            if self.off_ticks > 0:
                self.off_ticks = 1
            if self.motion is not None:
                self.motion["t"] = max(self.motion["t"], self.motion["n"] - 1)
        if self.off_ticks > 0:
            self.off_ticks -= 1
            k = 1.0 - self.off_ticks / max(1, self.off_total)
            self.off = [a + (b - a) * k for a, b in zip(self.off_from, self.off_to)]
        m = self.motion
        if m is not None:
            m["t"] += 1
            k = min(1.0, m["t"] / max(1, m["n"]))
            self.px = m["x0"] + (m["x1"] - m["x0"]) * k
            self.py = m["y0"] + (m["y1"] - m["y0"]) * k
            if m["kind"] == "jump":
                self.off[2] = -m["h"] * math.sin(math.pi * k)
            if k >= 1.0:
                if m["kind"] == "jump":
                    self.off[2] = 0.0
                self.motion = None


# ---------------------------------------------------------------- 场景
class PrologueScene(Scene, EventHost):
    """序章导演. 用法: scene.next_scene = PrologueScene(surface, return_scene=world_map, audio=..., on_close=...)"""

    def __init__(self, surface: pygame.Surface, return_scene: Scene | None = None,
                 audio=None, on_close=None, start_event: int = FIRST_EVENT) -> None:
        Scene.__init__(self, surface)
        EventHost.__init__(self)
        self.return_scene = return_scene
        self.audio = audio
        self.on_close = on_close
        self.done = False
        self.font = load_chinese_font(20)
        self.small = load_chinese_font(16)
        tbl = json.loads(FC_TABLES.read_text(encoding="utf-8")) if FC_TABLES.exists() else {}
        self.sheets = {int(k): v for k, v in tbl.get("sheets", {}).items()}
        self.fm_groups = {int(k): v for k, v in tbl.get("fm_groups", {}).items()}
        self.fc_defs = {int(k): v for k, v in tbl.get("fc_defs", {}).items()}
        self.maps_by_id = {row["id"]: row for row in realm.map_table().values()}
        # 舞台状态
        self.map: realm.RealMap | None = None
        self.map_row: dict | None = None
        self.actors: dict[int, Actor] = {}
        self._next_obj = 0x10000
        self.cam = [0.0, 0.0]             # 镜头中心 (像素)
        self.cam_from = [0.0, 0.0]
        self.cam_to = [0.0, 0.0]
        self.cam_ticks = 0
        self.cam_total = 0
        self.cam_follow = -1
        self.view = None                  # (w, h) 视口 (None = 全屏)
        self.fade_rgb = (0, 0, 0)
        self.fade_alpha = 0.0             # 0 = 看得见场景, 255 = 全遮
        self.fade_from = 0.0
        self.fade_to = 0.0
        self.fade_ticks = 0
        self.fade_total = 0
        self.fade_step = 0
        # 硬件调色板的"非渐变"状态 (ed.04 黑板 / ed.05 白板 / 1f.00 送工作板): 盖在地图和精灵上, 气泡仍可见
        self.pal_rgb = (0, 0, 0)
        self.pal_alpha = 0.0
        self.pal_work = (1.0, 0)          # ed.08 的 (a/100, b): 工作板 = 场景板×a + b
        self.caption_text: str | None = None
        # ef 转场: kind 0 缩放 / 4 圆形光圈; closing=True 从全屏收到点, False 从点放开; 进度 t/n (tick)
        self.trans: dict | None = None
        self.bubbles: list[DialogTask] = []
        self._img_cache: dict[str, pygame.Surface | None] = {}
        self._tasks: dict[int, Actor] = {}
        self._task_n = 0x30000
        self._in_runner = False
        self._acc = 0.0
        self._frame = 0                   # 画面帧计数 (分层自动卷动用, FUN_004b439e 的 t)
        self._skip_hint = 0
        self.log_lines: list[str] = []
        # 导演
        bundle = ScriptBundle.load()
        self.runner = EventRunner(bundle, self) if bundle is not None else None
        if self.runner is not None:
            self.runner.start(start_event)

    # ---- 场景生命周期 ----
    def on_enter(self) -> None:
        if self.runner is None:
            self._finish()

    def _finish(self) -> None:
        if self.done:
            return
        self.done = True
        set_fast(False)
        if self.audio is not None:
            try:
                self.audio.stop_bgm()
                pygame.mixer.music.set_volume(self._base_volume())   # 还原给地图曲
            except Exception:
                pass
        self.next_scene = self.return_scene
        if self.on_close is not None:
            self.on_close()

    def handle_event(self, event: pygame.event.Event) -> bool:
        if event.type == pygame.QUIT:
            return False
        if event.type == pygame.KEYDOWN:
            if event.key == pygame.K_ESCAPE:
                self._finish()
            elif event.key in (pygame.K_RETURN, pygame.K_SPACE, pygame.K_z, pygame.K_x):
                if self.runner is not None:
                    self.runner.press_key()
        return True

    def update(self, dt_ms: int) -> None:
        if self.done or self.runner is None:
            return
        # 原版: 按住 Shift = 跳过所有停顿/补间 (键盘钩子 DAT_00742350), 见 core.dialog_engine.set_fast
        try:
            set_fast(bool(pygame.key.get_mods() & pygame.KMOD_SHIFT))
        except Exception:
            set_fast(False)
        self._acc += min(dt_ms, 250)
        while self._acc >= TICK_MS:
            self._acc -= TICK_MS
            self.step()
            self._frame += 1

    def step(self) -> None:
        """跑一个原版 tick: 脚本 → 演员补间 → 镜头/渐变."""
        r = self.runner
        ended = r.tick(TICK_MS)
        for a in self.actors.values():
            a.tick()
        self._tick_camera()
        self._tick_fade()
        if self.trans is not None:
            if self.trans["t"] < self.trans["n"]:
                self.trans["t"] += 1
            elif not self.trans["closing"]:
                self.trans = None                 # 放开到全屏后就没事了; 收完的保持遮黑直到下一个转场/切图
        self.bubbles = [d for d in r.dialogs if d.visible() or d.alive]
        if ended or (r.main is not None and r.main.done and r.history and r.history[-1] >= LAST_EVENT
                     and not r.scheduler.any_dialog()):
            self._finish()

    # ---- 日志 ----
    def log(self, msg: str) -> None:
        self.log_lines.append(msg)
        if len(self.log_lines) > 200:
            del self.log_lines[:100]

    # ================= EventHost: 舞台 =================
    def switch_map(self, map_id: int, reload: bool = False) -> None:
        row = self.maps_by_id.get(map_id)
        if row is None:
            self.log(f"[舞台] 没有地图 {map_id}")
            return
        if reload and self.map_row is row:
            return
        if not realm.is_available(row["map"]):
            self.log(f"[舞台] 缺地图文件 {row['map']}")
            self.map = None
        else:
            self.map = realm.load(row["map"])
        self.map_row = row
        self.trans = None
        self.actors = {fc: a for fc, a in self.actors.items() if fc < 0x10000}
        for a in self.actors.values():
            a.visible = False
        self.cam_follow = -1

    def viewport(self, w: int, h: int) -> None:
        self.view = (w, h) if w > 0 and h > 0 else None

    def camera(self, x, y, frames: int, relative: bool, follow: int = -1) -> None:
        if follow != -1:
            self.cam_follow = follow
            a = self._actor(follow, create=False)
            if a is not None and frames <= 0:
                self.cam = [a.px, a.py]
            return
        self.cam_follow = -1
        tx = (self.cam[0] / TILE_W - 0.5 + x) if relative else x
        ty = (self.cam[1] / TILE_H - 0.5 + y) if relative else y
        target = [(tx + 0.5) * TILE_W, (ty + 0.5) * TILE_H]
        if fast_forward():                 # Shift: 镜头直接到位 (FUN_0049a66c 不起补间任务)
            frames = 0
        if frames <= 0:
            self.cam = target
            self.cam_ticks = 0
        else:
            self.cam_from = list(self.cam)
            self.cam_to = target
            self.cam_ticks = self.cam_total = frames

    def camera_busy(self) -> bool:
        return self.cam_ticks > 0

    def _tick_camera(self) -> None:
        if self.cam_follow != -1:
            a = self.actors.get(self.cam_follow)
            if a is not None:
                self.cam = [a.px, a.py]
            return
        if self.cam_ticks > 0:
            if fast_forward():
                self.cam_ticks = 0
            else:
                self.cam_ticks -= 1
            k = 1.0 - self.cam_ticks / max(1, self.cam_total)
            self.cam = [f + (t - f) * k for f, t in zip(self.cam_from, self.cam_to)]

    def fade(self, target: str, frames: int, step: int = 0) -> None:
        # 硬件板当前若是 ed/1f 送上去的黑/白/暗板, 渐变从它开始 (ev0 开头 ed.04 黑 → ee.10 淡入)
        if self.pal_alpha > self.fade_alpha:
            self.fade_alpha, self.fade_rgb = self.pal_alpha, self.pal_rgb
        self.pal_alpha = 0.0
        if target == "scene":
            to, rgb = 0.0, self.fade_rgb
        else:
            to, rgb = 255.0, (255, 255, 255) if target == "white" else (0, 0, 0)
        if self.fade_alpha <= 0 or target != "scene":
            self.fade_rgb = rgb
        self.fade_from = self.fade_alpha
        self.fade_to = to
        self.fade_step = step
        if step > 0:
            self.fade_ticks = self.fade_total = max(1, int(math.ceil(abs(to - self.fade_alpha) / step)))
        else:
            self.fade_ticks = self.fade_total = max(1, frames)

    def _tick_fade(self) -> None:
        if self.fade_ticks > 0:
            self.fade_ticks = 0 if fast_forward() else self.fade_ticks - 1
            k = 1.0 - self.fade_ticks / max(1, self.fade_total)
            self.fade_alpha = self.fade_from + (self.fade_to - self.fade_from) * k

    def wait_fade(self) -> bool:
        return self.fade_ticks > 0 or (self.trans is not None and self.trans["t"] < self.trans["n"])

    def transition(self, kind: int, closing: bool, ms: int, fc: int) -> None:
        a = self.actors.get(fc)
        n = max(1, int(ms / TICK_MS))
        self.trans = {"kind": kind, "closing": closing, "t": 0, "n": n, "fc": fc if a is not None else -1}
        if a is None:
            self.trans["cx"], self.trans["cy"] = self.surface.get_width() / 2, self.surface.get_height() / 2

    def _set_pal(self, rgb: tuple[int, int, int], alpha: float) -> None:
        self.pal_rgb, self.pal_alpha = rgb, alpha
        self.fade_alpha, self.fade_ticks = 0.0, 0          # 送板 = 硬件板立刻换掉, 渐变作废

    def palette(self, kind: str, *args: int) -> None:
        if kind == "apply":                      # ed.00 场景板送硬件 → 画面正常
            self._set_pal((0, 0, 0), 0.0)
        elif kind == "black":                    # ed.04 黑板
            self._set_pal((0, 0, 0), 255.0)
        elif kind == "white":                    # ed.05 白板
            self._set_pal((255, 255, 255), 255.0)
        elif kind == "store":                    # ed.01 工作板 ← 场景板
            self.pal_work = (1.0, 0)
        elif kind == "blend" and len(args) >= 2:  # ed.08 [a, b]: 工作板 = 场景板 × a/100 + b (每通道)
            self.pal_work = (args[0] / 100.0, args[1])

    def native(self, fn: int, args: list[int]) -> None:
        if fn == 0x40A342 and len(args) >= 3:   # 送一段调色板到硬件 [板, 起, 数] (ev2 梦境: 工作暗板 / 黑板)
            buf = args[0]
            if 0x743B58 <= buf < 0x743F58:         # 工作板: 原版送的是板内偏 16 项 (0x743b98) 到 112..255,
                self._set_pal((0, 0, 0), 255.0)     # 地图色全黑 (Wine 实测 ev2 梦境对白时画面纯黑, 只剩气泡)
            elif 0x53C290 <= buf < 0x53C690:       # 黑板
                self._set_pal((0, 0, 0), 255.0)
            elif 0x5403D4 <= buf < 0x5407D4:       # 白板
                self._set_pal((255, 255, 255), 255.0)
        elif fn == 0x40B0C5:                       # 渐变到自定义调色板 (序章结尾压暗): 近似为半黑
            self.fade_rgb = (0, 0, 0)
            self.fade_from, self.fade_to = self.fade_alpha, 170.0
            spd = args[3] if len(args) > 3 else 0
            self.fade_ticks = self.fade_total = max(1, (spd * 3 // 50) + 1 if spd >= 0 else -spd)
            self.fade_step = 0

    def caption(self, text: str | None) -> None:
        self.caption_text = text

    def door(self, door_id: int, state: int) -> None:
        """e2.00: 门表里的门在当前图上就换成开/关的那组瓦片 (原版 FUN_004b82f4 直接改地图)."""
        d = realm.door_table().get(door_id)
        if d is None or self.map is None or self.map_row is None or d["map"] != self.map_row["id"]:
            return
        self.map.patch_cells(d["x"], d["y"], d["w"], d["h"], d["open"] if state else d["closed"])

    # ================= EventHost: 演员 =================
    def _actor(self, fc: int, create: bool = True) -> Actor | None:
        a = self.actors.get(fc)
        if a is None and create:
            d = self.fc_defs.get(fc, {})
            a = Actor(fc, d.get("sheet", 8))
            self.actors[fc] = a
        return a

    def fc_place(self, fc: int, x: int, y: int, z: int, d: int) -> None:
        self._actor(fc).place(x, y, z, d)

    def fc_show(self, fc: int, visible: bool) -> None:
        self._actor(fc).visible = visible

    def fc_dir(self, fc: int, d: int) -> None:
        self._actor(fc).set_dir(d)

    def fc_frame(self, fc: int, frame: int) -> None:
        self._actor(fc).frame = frame

    def fc_anim(self, fc: int, mode: int, frame: int, ticks: int) -> None:
        a = self._actor(fc)
        a.mode = (mode >> 16) & 3
        a.sheet = mode & 0xFFFF
        a.frame = frame

    def fc_move(self, fc: int, dx: float, dy: float, ticks: int, teleport: bool) -> None:
        a = self._actor(fc)
        if teleport:
            a.px += dx
            a.py += dy
        else:
            a.off_from = list(a.off)
            a.off_to = [a.off_to[0] + dx, a.off_to[1] + dy, a.off_to[2]] if a.off_ticks else [a.off[0] + dx, a.off[1] + dy, a.off[2]]
            a.off_ticks = a.off_total = max(1, ticks)

    def fc_offset(self, fc: int, group: int, x, y, z) -> None:
        a = self._actor(fc)
        if group == 0x100:
            if x is not None:
                a.px = x
            if y is not None:
                a.py = y
        else:
            for i, v in enumerate((x, y, z)):
                if v is not None:
                    a.off[i] = v
                    a.off_to[i] = v
            a.off_ticks = 0

    def fc_get(self, fc: int, field: int) -> int:
        a = self.actors.get(fc)
        if a is None:
            return 0
        if field == 0x110:
            return a.dir
        if field == 0x114:
            return a.dir_target
        if field == 0x128:
            return a.tx
        if field == 0x12C:
            return a.ty
        if field == 0x130:
            return a.base_sheet
        if field in (0x20, 0x24, 0x28):
            return int(a.off[(field - 0x20) // 4] * 65536) & 0xFFFFFFFF
        if field == 0x8:
            return int(a.px * 65536) & 0xFFFFFFFF
        if field == 0xC:
            return int(a.py * 65536) & 0xFFFFFFFF
        if field == 0x1C:
            return a.z
        if field in (0x120, 0x124):
            sx, sy = self._screen_pos(a)
            return int(sx if field == 0x120 else sy)
        return 0

    def fc_set(self, fc: int, field: int, v: int) -> None:
        a = self._actor(fc)
        if v & 0x80000000:
            v -= 1 << 32
        if field == 0x110:
            a.set_dir(v)
        elif field == 0x114:
            a.dir_target = v & 7
        elif field == 0x130:                  # 图集基号 (4a.09 / 20.05)
            a.base_sheet = v
        elif field in (0x20, 0x24, 0x28):
            i = (field - 0x20) // 4
            a.off[i] = v / 65536.0
            a.off_to[i] = a.off[i]
        elif field == 0x8:
            a.px = v / 65536.0
        elif field == 0xC:
            a.py = v / 65536.0
        elif field == 0x1C:
            a.z = v

    def _can_step(self, cx: int, cy: int, cz: int, d: int) -> tuple[bool, int, int, int]:
        """一步可行性 (演员可以站在图外, 从边上走进来: 图外格一律可走, 进图按原版规则)."""
        dx, dy = DIR_DELTA.get(d & 7, (0, 0))
        m = self.map
        if m is None:
            return True, cz, cx + dx, cy + dy
        if m.in_bounds(cx, cy):
            ok, z, nx, ny = m.move(cx, cy, dx, dy, cz)
            return ok, z, nx, ny
        nx, ny = cx + dx, cy + dy
        if -3 <= nx < m.w + 3 and -3 <= ny < m.h + 3:
            return True, cz, nx, ny
        return False, cz, cx, cy

    def fc_step(self, fc: int, d: int) -> int:
        a = self._actor(fc)
        ok, z, nx, ny = self._can_step(a.tx, a.ty, a.z, d)
        if not ok:
            return 0
        # 原版 40.00 → FUN_004b4f56: 目标格在占格表 DAT_00810118 里标了 0x10000 (任何可见对象站着/正要走进去) 就挡,
        # 挡住的那步原地踏步. ev4 里迪特被美娜挡在 (6,6), 美娜的 <WALK6> 也进不了迪特那格.
        for h, o in self.actors.items():
            if h != fc and o.visible and o.z == z and (nx, ny) in ((o.tx, o.ty), o.reserved):
                return 0
        a.reserved = (nx, ny)
        code = (d << 8) | 1
        if z > a.z:
            code |= 4
        elif z < a.z:
            code |= 8
        return code

    def fc_layer(self, fc: int, dz: int) -> None:
        a = self._actor(fc)
        a.z = max(0, min(1, a.z + dz))

    def fc_spawn(self, kind: int, x: int, y: int, z: int, d: int, base: int = -1) -> int:
        self._next_obj += 1
        hd = self._next_obj
        # 58.00 的"图集基号"和 58.02 的"kind"都直接是图集表下标 (FUN_004b9d45: obj+0x130 = kind)
        sheet = base if base >= 0 else kind
        a = Actor(hd, sheet)
        a.spawned = True
        a.place(x, y, z, d if d >= 0 else 1)
        a.visible = True
        self.actors[hd] = a
        return hd

    def fc_clone(self, src: int) -> int:
        s = self._actor(src)
        self._next_obj += 1
        hd = self._next_obj
        a = Actor(hd, s.base_sheet)
        a.spawned = True
        a.px, a.py, a.z, a.dir, a.mode, a.sheet, a.frame = s.px, s.py, s.z, s.dir, s.mode, s.sheet, s.frame
        a.visible = False
        self.actors[hd] = a
        return hd

    def fc_blank(self) -> int:
        self._next_obj += 1
        a = Actor(self._next_obj, 8)
        a.spawned = True
        self.actors[self._next_obj] = a
        return self._next_obj

    def fc_destroy(self, handle: int) -> None:
        self.actors.pop(handle, None)

    def fc_path(self, fc: int, x: int, y: int, d: int) -> list[int]:
        """原版寻路 (FUN_0049d659 → FUN_0049d80a 从**起点**泛洪距离场; FUN_0049d1bd 从**终点**回溯到起点,
        每格按 上/下/左/右 的固定顺序取第一个距离 -1 的邻格, 最后把步子反过来). 四向.
        泛洪时队伍角色/NPC 占的格算障碍 (flags 0x10/0x20), 58.xx 生成的对象不算.
        (Wine 3fps 核对过: ev2 迪特从 (9,13) 先左一格再沿第 8 列上去, 就是这个"终点回溯"的结果.) 末尾按 d 转向."""
        a = self._actor(fc)
        face = d                          # 到达后朝向 (下面的循环变量会覆盖 d, 别直接用)
        if self.map is None:
            return []
        sx, sy, sz = a.tx, a.ty, a.z
        goal = (x, y)
        if (sx, sy) == goal:
            return [face | 0x100] if 0 <= face <= 7 else []
        blocked = set()
        for h, o in self.actors.items():
            if h != fc and h < 0x10000 and o.visible and o.z == sz:
                for t in ((o.tx, o.ty), o.reserved):
                    if t is not None and t != goal:
                        blocked.add(t)
        from collections import deque
        dist: dict[tuple[int, int], int] = {(sx, sy): 0}
        q = deque([(sx, sy)])
        while q and goal not in dist:
            cx, cy = q.popleft()
            dc = dist[(cx, cy)]
            for dd in (0, 1, 2, 3):                      # 泛洪顺序 上/下/左/右
                nx, ny = cx + DIR_DELTA[dd][0], cy + DIR_DELTA[dd][1]
                if (nx, ny) in dist or (nx, ny) in blocked:
                    continue
                ok, _nz, ax, ay = self._can_step(cx, cy, sz, dd)
                if not ok or (ax, ay) != (nx, ny):
                    continue
                dist[(nx, ny)] = dc + 1
                q.append((nx, ny))
            if len(dist) > 4000:
                break
        if goal not in dist:
            return []
        back = {0: 1, 1: 0, 2: 3, 3: 2}
        rev: list[int] = []
        cx, cy = goal
        while (cx, cy) != (sx, sy):
            cur = dist[(cx, cy)]
            for dd in (0, 1, 2, 3):                      # 回溯顺序 上/下/左/右, 取第一个距离 -1 的邻格
                nx, ny = cx + DIR_DELTA[dd][0], cy + DIR_DELTA[dd][1]
                if dist.get((nx, ny)) == cur - 1:
                    ok, _nz, ax, ay = self._can_step(nx, ny, sz, back[dd])   # 真正走的方向: 邻格 → 这格
                    if ok and (ax, ay) == (cx, cy):
                        rev.append(back[dd] | 0x8000)
                        cx, cy = nx, ny
                        break
            else:
                return []
        steps = rev[::-1]
        if 0 <= face <= 7:
            steps.append(face | 0x100)
        return steps

    def _motion(self, a: Actor, kind: str, x1: float, y1: float, ticks: int, h: float = 0.0) -> int:
        a.motion = {"kind": kind, "t": 0, "n": 1 if fast_forward() else max(1, ticks),
                    "x0": a.px, "y0": a.py, "x1": x1, "y1": y1, "h": h}
        self._task_n += 1
        self._tasks[self._task_n] = a
        return self._task_n

    def fc_jump(self, fc: int, dx: int, dy: int, ticks: int, a1: int, b1: int, flag: int) -> int:
        a = self._actor(fc)
        n = max(1, int(ticks * (1000 / 60) / TICK_MS)) if ticks > 0 else 1
        return self._motion(a, "jump", a.px + dx * TILE_W, a.py + dy * TILE_H, n, h=TILE_H * (1.0 if a1 == 0 else abs(a1) / 48.0))

    def fc_fly(self, fc: int, px: int, py: int, ticks: int) -> int:
        a = self._actor(fc)
        if ticks <= 0:
            a.px, a.py = px, py
            return 0
        return self._motion(a, "fly", px, py, ticks)

    # 气泡里的 <DIRn> / <WALKd,n> → 原版转向/走路脚本 (由 runner 起子任务)
    def fc_turn(self, fc: int, d: int, x: int) -> int:
        if self.runner is None or self._in_runner:
            return 0
        self._in_runner = True
        try:
            return self.runner.turn(fc, d, x)
        finally:
            self._in_runner = False

    def fc_walk(self, fc: int, d: int, n: int, mode: int, x: int) -> int:
        if self.runner is None or self._in_runner:
            return 0
        self._in_runner = True
        try:
            return self.runner.walk(fc, d, n, mode, x)
        finally:
            self._in_runner = False

    def fc_on_screen(self, fc: int) -> bool:
        """9c.00: 演员脚点是否在当前镜头画面内 (原版屏外角色走路不放动画, 直接瞬移一格)."""
        a = self._actor(fc, create=False)
        if a is None:
            return False
        cx, cy = self._cam_origin()
        sw, sh = self.surface.get_size()
        return -TILE_W <= a.px - cx <= sw + TILE_W and -TILE_H * 2 <= a.py - cy <= sh + TILE_H

    def task_alive(self, hd: int) -> bool:
        if self.runner is not None and hd and (hd & 0xF0000) in (0x20000, 0x40000):
            return self.runner.alive(hd)
        a = self._tasks.get(hd)
        if a is None:
            return False
        if a.motion is None:
            self._tasks.pop(hd, None)
            return False
        return True

    # ================= EventHost: 声音 / 对白 =================
    def sound(self, sid: int) -> None:
        if self.audio is not None:
            try:
                self.audio.play_sfx_id(sid)
            except Exception:
                pass

    def sound_stop(self, sid: int) -> None:
        if self.audio is not None:
            try:
                self.audio.stop_sfx_id(sid)
            except Exception:
                pass

    def _base_volume(self) -> float:
        return float(getattr(self.audio, "_volume", 1.0) or 1.0)

    def bgm(self, n, fade_frames: int = 0) -> None:
        """换曲. 之前的 bgm_volume 淡出会把 mixer 音量压到 0, 新曲开始前必须把音量还原,
        否则后面整段序章 (以及回到地图后的地图曲) 都是哑的."""
        if self.audio is None:
            return
        try:
            if n is None:
                self.audio.stop_bgm()
                return
            if n == 999 and self.map_row is not None:
                n = self.map_row.get("bgm")
            f = bgm_table.bgm_file(n) if n is not None and n >= 0 else None
            if f:
                pygame.mixer.music.set_volume(self._base_volume())
                self.audio.stop_bgm()          # 同名曲也要从头播 (脚本语义), play_bgm 对同曲会跳过
                self.audio.play_bgm(f)
        except Exception:
            pass

    def bgm_volume(self, vol: int, frames: int) -> None:
        """脚本的音量指令: vol=0 + frames = 淡出 (用 mixer 的 fadeout, 淡完即停); 其它 = 按比例设."""
        if self.audio is None:
            return
        try:
            if vol <= 0:
                if frames > 0:
                    pygame.mixer.music.fadeout(int(frames * 25))
                else:
                    self.audio.stop_bgm()
            else:
                pygame.mixer.music.set_volume(self._base_volume() * max(0.0, min(1.0, vol / 100.0)))
        except Exception:
            pass

    def speak(self, dlg: DialogTask) -> None:
        self.log(f"[气泡] {code_str(dlg.code)} fc{dlg.fc}")

    def dialog_event(self, dlg: DialogTask, what: str) -> None: ...

    def key_pressed(self) -> bool:
        return False

    def unknown(self, cmd) -> None:
        self.log(f"[ev] ?? {cmd}")

    # ================= 渲染 =================
    def _image(self, name: str) -> pygame.Surface | None:
        if name in self._img_cache:
            return self._img_cache[name]
        surf = None
        for ext in (".png", ".pcx"):
            p = SPRITES / f"{name}{ext}"
            if p.exists():
                try:
                    surf = load_image(p)
                except Exception:
                    surf = None
                break
        self._img_cache[name] = surf
        return surf

    def _actor_sprite(self, a: Actor) -> tuple[pygame.Surface, int, int] | None:
        """→ (子图, 锚点 x, 锚点 y) (锚点 = 脚点在子图内坐标)."""
        if a.mode == 0:
            pcx = self.fm_groups.get(a.sheet)
            if not pcx:
                return None
            frames = FM_FRAMES.get(pcx.lower())
            img = self._image(f"fm_{pcx}")
            if not frames or img is None or not (0 <= a.frame < len(frames)):
                return None
            x, y, w, h, ax, ay = frames[a.frame]
            if w <= 0 or h <= 0 or x + w > img.get_width() or y + h > img.get_height():
                return None
            return img.subsurface(pygame.Rect(x, y, w, h)), ax, ay
        sheet_id = a.sheet if a.mode == 1 else a.base_sheet + a.sheet
        row = self.sheets.get(sheet_id)
        if row is None:
            return None
        name, cols, rows, ax, ay = row
        img = self._image(f"ps_{name}")
        if img is None or cols <= 0 or rows <= 0:
            return None
        fw, fh = img.get_width() // cols, img.get_height() // rows
        f = a.frame % (cols * rows)
        r = pygame.Rect((f % cols) * fw, (f // cols) * fh, fw, fh)
        return img.subsurface(r), ax, ay

    def _cam_center(self) -> tuple[float, float]:
        """镜头中心 (像素), 按原版 FUN_004b19d5 夹到地图内: 视口 (非整个窗口) 不得越过第 0 层最外一圈瓦片;
        视口比地图 (去掉一圈) 还宽就定在地图正中."""
        sw, sh = self.surface.get_size()
        vw, vh = (min(self.view[0], sw), min(self.view[1], sh)) if self.view else (sw, sh)
        cx, cy = self.cam
        m = self.map
        if m is not None:
            W, H = m.w * TILE_W, m.h * TILE_H
            if vw < W - 2 * TILE_W:
                ox = cx - vw // 2
                shift = 0
                if ox < TILE_W:
                    shift += TILE_W - ox
                if ox + vw >= W - TILE_W:
                    shift -= (ox + vw) - (W - TILE_W) + 1
                cx += shift
            else:
                cx = W / 2
            if vh < H - 2 * TILE_H:
                oy = cy - vh // 2
                shift = 0
                if oy < TILE_H:
                    shift += TILE_H - oy
                if oy + vh >= H - TILE_H:
                    shift -= (oy + vh) - (H - TILE_H) + 1
                cy += shift
            else:
                cy = H / 2
        return cx, cy

    def _cam_origin(self) -> tuple[int, int]:
        sw, sh = self.surface.get_size()
        cx, cy = self._cam_center()
        return int(cx - sw / 2), int(cy - sh / 2)

    def _screen_pos(self, a: Actor) -> tuple[float, float]:
        cx, cy = self._cam_origin()
        return a.px + a.off[0] - cx, a.py + a.off[1] + a.off[2] - cy

    def draw(self) -> None:
        surf = self.surface
        surf.fill((0, 0, 0))
        cx, cy = self._cam_origin()
        sh = surf.get_height()
        m = self.map
        visible = [a for a in self.actors.values() if a.visible]
        by_row: dict[int, list[Actor]] = {}
        for a in visible:
            by_row.setdefault(int((a.py + a.off[1]) // TILE_H), []).append(a)
        if m is not None and m.parallax:
            # 分层卷动 (序章云图): 非活动层按各自视差原点整张画在底下, 活动层按行与精灵交错
            sw = surf.get_width()
            ccx, ccy = self._cam_center()
            act = m.active_layer
            for L in (0, 1):
                if L != act:
                    ox, oy = m.layer_center(L, ccx, ccy, self._frame)
                    m.draw_layer(surf, L, int(ox - sw / 2), int(oy - sh / 2))
            y0 = max(0, cy // TILE_H)
            y1 = min(m.h, (cy + sh) // TILE_H + 1)
            lead_z = act
            for y in range(y0, y1):
                m.draw_layer(surf, act, cx, cy, rows=(y, y + 1))
                for a in sorted(by_row.get(y, ()), key=lambda t: t.py):
                    self._draw_actor(a, cx, cy)
                    lead_z = a.z
                m.draw_tall(surf, cx, cy, y, lead_z)
        elif m is not None:
            y0 = max(0, cy // TILE_H)
            y1 = min(m.h, (cy + sh) // TILE_H + 1)
            lead_z = 0
            for y in range(y0, y1):
                m.draw_terrain(surf, cx, cy, rows=(y, y + 1))
                for a in sorted(by_row.get(y, ()), key=lambda t: t.py):
                    self._draw_actor(a, cx, cy)
                    lead_z = a.z
                m.draw_tall(surf, cx, cy, y, lead_z)
        else:
            for a in sorted(visible, key=lambda t: t.py):
                self._draw_actor(a, cx, cy)
        # 硬件板是黑/白/暗板 (ed.04/05, 1f.00): 盖住地图精灵, 气泡在上面照常显示
        if self.pal_alpha > 0:
            ov = pygame.Surface(surf.get_size())
            ov.fill(self.pal_rgb)
            ov.set_alpha(int(max(0, min(255, self.pal_alpha))))
            surf.blit(ov, (0, 0))
        self._draw_bubbles()
        # 调色板渐变叠层
        if self.fade_alpha > 0:
            ov = pygame.Surface(surf.get_size())
            ov.fill(self.fade_rgb)
            ov.set_alpha(int(max(0, min(255, self.fade_alpha))))
            surf.blit(ov, (0, 0))
        # 视口黑边
        if self.view is not None:
            sw = surf.get_width()
            vw, vh = min(self.view[0], sw), min(self.view[1], sh)
            bx, by = (sw - vw) // 2, (sh - vh) // 2
            if by > 0:
                pygame.draw.rect(surf, (0, 0, 0), (0, 0, sw, by))
                pygame.draw.rect(surf, (0, 0, 0), (0, sh - by, sw, by))
            if bx > 0:
                pygame.draw.rect(surf, (0, 0, 0), (0, 0, bx, sh))
                pygame.draw.rect(surf, (0, 0, 0), (sw - bx, 0, bx, sh))
        self._draw_transition()
        if self.caption_text:
            t = self.font.render(self.caption_text, True, (240, 230, 200))
            surf.blit(t, ((surf.get_width() - t.get_width()) // 2, 40))

    def _draw_transition(self) -> None:
        tr = self.trans
        if tr is None:
            return
        surf = self.surface
        sw, sh = surf.get_size()
        k = tr["t"] / tr["n"]                              # 0 → 1
        a = self.actors.get(tr["fc"])
        if a is not None:
            cx, cy = self._screen_pos(a)
            cy -= TILE_H                                     # 对象的"屏幕位置"是脚点上方一格 (FUN_00499095 的 -0x26)
        else:
            cx, cy = tr.get("cx", sw / 2), tr.get("cy", sh / 2)
        cx = max(0.0, min(float(sw), cx)); cy = max(0.0, min(float(sh), cy))
        shrink = k if tr["closing"] else 1.0 - k            # 0 = 全开, 1 = 全收
        if tr["kind"] == 4:                                  # 圆形光圈 (FUN_00403b89): 半径从角距离收到 0
            rmax = math.hypot(max(cx, sw - cx), max(cy, sh - cy))
            r = rmax * (1.0 - shrink)
            if r <= 0:
                surf.fill((0, 0, 0))
                return
            mask = pygame.Surface((sw, sh))
            mask.fill((0, 0, 0))
            pygame.draw.circle(mask, (255, 0, 255), (int(cx), int(cy)), int(r))
            mask.set_colorkey((255, 0, 255))
            surf.blit(mask, (0, 0))
        else:                                                # 缩放 (FUN_004031c2 ZoomBlt): 全屏矩形 → 对象处的小矩形
            zoom = 1.0 + shrink * 7.0
            w, h = sw / zoom, sh / zoom
            x0 = max(0.0, min(sw - w, cx - w / 2)); y0 = max(0.0, min(sh - h, cy - h / 2))
            sub = surf.subsurface(pygame.Rect(int(x0), int(y0), max(1, int(w)), max(1, int(h)))).copy()
            surf.blit(pygame.transform.scale(sub, (sw, sh)), (0, 0))

    def _draw_actor(self, a: Actor, cx: int, cy: int) -> None:
        sp = self._actor_sprite(a)
        sx = a.px + a.off[0] - cx
        sy = a.py + a.off[1] + a.off[2] - cy
        if sp is None:
            pygame.draw.circle(self.surface, (200, 60, 60), (int(sx), int(sy)), 6)
            return
        img, ax, ay = sp
        self.surface.blit(img, (int(sx - ax), int(sy - ay)))

    # ---- 气泡 ----
    BUBBLE_PAD = 10
    LINE_H = 24

    def _bubble_rect(self, d: DialogTask, placed: list[pygame.Rect]) -> pygame.Rect:
        font = self.font
        lines = d.cur_page().lines or [""]
        w = max([font.size(ln)[0] for ln in lines] + [16 * max(2, d.box_cols)]) + self.BUBBLE_PAD * 2
        h = max(1, max(len(lines), d.box_rows)) * self.LINE_H + self.BUBBLE_PAD * 2
        sw, sh = self.surface.get_size()
        vx0, vy0, vx1, vy1 = self._view_rect()
        a = self.actors.get(d.fc)
        if a is not None:
            ax, ay = self._screen_pos(a)
            ax += d.anchor_dx
            ay += d.anchor_dy
            top = ay - 80
        else:
            ax, ay, top = sw / 2, sh / 2, sh / 2
        prefs = [int(c) for c in str(d.possub)] or [8]
        cand: list[pygame.Rect] = []
        for p in prefs:
            if p in (7, 8, 9):
                x, y = ax - w / 2 + (p - 8) * w / 2, top - h - 6
            elif p in (1, 2, 3):
                x, y = ax - w / 2 + (p - 2) * w / 2, ay + 8
            elif p == 4:
                x, y = ax - 40 - w, top + 10
            elif p == 6:
                x, y = ax + 40, top + 10
            else:
                x, y = ax - w / 2, top - h / 2
            r = pygame.Rect(int(x), int(y), int(w), int(h))
            r.x = int(max(vx0 + 4, min(r.x, vx1 - w - 4)))
            r.y = int(max(vy0 + 4, min(r.y, vy1 - h - 4)))
            cand.append(r)
        for r in cand:
            if not any(r.colliderect(o) for o in placed):
                return r
        return cand[0] if cand else pygame.Rect(0, 0, w, h)

    def _view_rect(self) -> tuple[int, int, int, int]:
        sw, sh = self.surface.get_size()
        if self.view is None:
            return 0, 0, sw, sh
        vw, vh = min(self.view[0], sw), min(self.view[1], sh)
        bx, by = (sw - vw) // 2, (sh - vh) // 2
        return bx, by, sw - bx, sh - by

    def _draw_bubbles(self) -> None:
        placed: list[pygame.Rect] = []
        for d in self.bubbles:
            if not d.visible():
                continue
            r = self._bubble_rect(d, placed)
            placed.append(r)
            k = d.box_t if d.box_state in ("opening", "closing") else 1.0
            if k < 1.0:
                rr = pygame.Rect(0, 0, max(8, int(r.w * k)), max(8, int(r.h * k)))
                rr.center = r.center
                self._draw_box(rr, d.style)
                continue
            self._draw_box(r, d.style)
            pg = d.cur_page()
            y = r.y + self.BUBBLE_PAD
            for i, line in enumerate(pg.lines):
                runs = pg.runs[i] if i < len(pg.runs) else [(c, False) for c in line]
                x = r.x + self.BUBBLE_PAD
                for ch, hl in runs:
                    col = (255, 220, 90) if hl else (250, 250, 250)
                    t = self.font.render(ch, True, col)
                    self.surface.blit(t, (x, y))
                    x += t.get_width()
                y += self.LINE_H
            if d.wait_kind == "key":
                tx, ty = r.right - 16, r.bottom - 10
                pygame.draw.polygon(self.surface, (255, 220, 90), [(tx - 5, ty - 6), (tx + 5, ty - 6), (tx, ty)])
            if d.excl:
                t = self.font.render("!", True, (255, 80, 80))
                self.surface.blit(t, (r.right - 6, r.y - 18))
            if d.arrow:
                t = self.font.render("?", True, (120, 200, 255))
                self.surface.blit(t, (r.right - 6, r.y - 18))

    def _draw_box(self, r: pygame.Rect, style: int) -> None:
        ov = pygame.Surface(r.size, pygame.SRCALPHA)
        if style == 0:                                     # TRANS: 半透明黑
            ov.fill((10, 10, 20, 150))
        elif style == 2:                                   # SOLID
            ov.fill((245, 240, 220, 255))
        else:
            ov.fill((20, 18, 40, 225))
        pygame.draw.rect(ov, (210, 200, 160, 255), ov.get_rect(), 2, border_radius=8)
        self.surface.blit(ov, r.topleft)
