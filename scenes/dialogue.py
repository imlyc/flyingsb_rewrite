"""剧情对白场景 (E 试水).

播放 tools/extract_script.py 从 FlyingSB.exe 提取的原版对白
(assets/script/messages.json: [{scene, speaker, text, tags, cmds}])。

证明"原版剧本 → 可播放对白"这条链路通了; 后续再把 msg_id 与地图事件绑定,
就是完整的剧情事件引擎。
"""

from __future__ import annotations

import json
from pathlib import Path

import pygame

from scenes.base import Scene
from scenes.menu import load_chinese_font
from scenes.unit_render import AnimationState, blit_unit, pick_locomotion_frame

# ---- 演出节奏 ----
TYPE_CPS = 45          # 逐字揭示速度 (字符/秒)
IDLE_PERIOD_MS = 400   # 说话角色待机呼吸周期 (与行走走 2 帧一致)
SLIDE_MS = 140         # 对话框入场滑入时长

ROOT = Path(__file__).resolve().parent.parent
MESSAGES = ROOT / "assets" / "script" / "messages.json"


def load_dialogue(limit: int | None = None) -> list[dict]:
    """筛出"像对白"的条目 (有说话人 / 含句读 / 够长)."""
    if not MESSAGES.exists():
        return []
    data = json.loads(MESSAGES.read_text(encoding="utf-8"))
    out = []
    for m in data:
        t = (m.get("text") or "").strip()
        if not t:
            continue
        if m.get("speaker") or any(c in t for c in "。？！，…") or len(t) > 6:
            out.append(m)
    return out[:limit] if limit else out


class DialogueScene(Scene):
    """底部对话框, 逐条播放. Enter/Space/→ 下一条, ← 上一条, ESC 返回."""

    BOX_H = 160
    BG = (12, 10, 24)
    BOX = (10, 8, 22, 232)
    EDGE = (150, 120, 220)
    TEXT = (232, 228, 240)
    NAME = (255, 214, 96)
    DIM = (140, 132, 170)

    def __init__(self, surface: pygame.Surface, return_scene: Scene | None = None,
                 messages: list[dict] | None = None, title: str = "剧本预览",
                 on_close: "callable | None" = None, backdrop: pygame.Surface | None = None) -> None:
        super().__init__(surface)
        self.return_scene = return_scene
        self.msgs = load_dialogue() if messages is None else messages
        self.idx = 0
        self.title = title
        self.font = load_chinese_font(22)
        self.name_font = load_chinese_font(24)
        self.small = load_chinese_font(16)
        # 对白全部播放完 / ESC 退出时调用 (剧情战斗中用于衔接战斗)
        self.on_close = on_close
        # 剧情对白: 覆盖在**当前地图画面**上 (原版对话框浮在场景上, 不切黑屏)
        self.backdrop = backdrop
        # ---- 演出状态 ----
        self._anim = AnimationState()      # 说话角色待机动画计时
        self._reveal = 0.0                 # 已揭示字符数 (逐字打字机)
        self._slide = 0.0                  # 对话框入场 (0→1)
        self._unit_cache: dict[str, object] = {}

    # ------- 更新 (演出动画) -------
    def _cur_text(self) -> str:
        if not self.msgs:
            return ""
        return self.msgs[self.idx].get("text") or ""

    def update(self, dt_ms: int) -> None:
        self._anim.tick(dt_ms, moving=False)        # 说话角色待机呼吸计时
        full = self._cur_text()
        if self._reveal < len(full):                # 逐字揭示
            self._reveal = min(len(full), self._reveal + TYPE_CPS * dt_ms / 1000.0)
        if self._slide < 1.0:                       # 对话框入场
            self._slide = min(1.0, self._slide + dt_ms / SLIDE_MS)

    def _draw_portraits(self, frames: list[int], box: pygame.Rect) -> None:
        """画原版立绘: 帧号 → core.npc_sprites 的站立像 (与原版 jmp.c0 同一编号空间).

        多人同框 (如 <$MIRO:3016><$SON:3022>) 时从右往左依次排开。
        """
        try:
            from core import npc_sprites
            if not npc_sprites.available():
                return
        except Exception:
            return
        x = box.right - 24
        for f in frames:
            try:
                surf = npc_sprites.surface_for(f, direction=1)
            except Exception:
                surf = None
            if surf is None:
                continue
            w, h = surf.get_size()
            x -= w
            if x < box.x + 4:
                break
            self.surface.blit(surf, (x, box.y - h + 10))
            x -= 10

    def _speaker_unit(self, name: str | None):
        """说话人的原版角色精灵 (walk + idle); 旁白/无精灵则返回 None."""
        if not name:
            return None
        key = str(name)
        if key in self._unit_cache:
            return self._unit_cache[key]
        res = None
        try:
            from core.character_sprites import sprite_resource
            from core.sprites.atlas_classes import idle_key_from_walk_key
            from core.sprites.loaders import get_character_sprite, get_idle_sprite
            res_name = sprite_resource(key)
            walk = get_character_sprite(res_name)
            try:
                idle = get_idle_sprite(idle_key_from_walk_key(res_name))
            except Exception:
                idle = None
            res = (walk, idle)
        except Exception:
            res = None                              # 非角色名 (旁白/未知) → 不画立绘
        self._unit_cache[key] = res
        return res

    # ------- 输入 -------
    def handle_event(self, event: pygame.event.Event) -> bool:
        if event.type == pygame.KEYDOWN:
            if event.key in (pygame.K_RETURN, pygame.K_SPACE, pygame.K_RIGHT, pygame.K_DOWN):
                # 字还没出完 → 先补全本句; 再按才翻页 (常见 RPG 语义)
                if self._reveal < len(self._cur_text()):
                    self._reveal = float(len(self._cur_text()))
                    return True
                self.idx += 1
                if self.idx >= len(self.msgs):
                    self.idx = len(self.msgs) - 1
                    self._exit()
                else:
                    self._reveal = 0.0
                    self._slide = 0.0
            elif event.key in (pygame.K_LEFT, pygame.K_UP):
                self.idx = max(0, self.idx - 1)
                self._reveal = 0.0
                self._slide = 0.0
            elif event.key in (pygame.K_ESCAPE, pygame.K_x):
                self._exit()
        return True

    def _exit(self) -> None:
        cb = self.on_close
        self.next_scene = self.return_scene if self.return_scene is not None else None
        if self.return_scene is None:
            self.next_scene = None
        if cb is not None:
            cb()

    # ------- 渲染 -------
    def _wrap(self, text: str, font: pygame.font.Font, max_w: int) -> list[str]:
        lines, cur = [], ""
        for ch in text:
            if ch == "\n":
                lines.append(cur)
                cur = ""
                continue
            if font.size(cur + ch)[0] > max_w:
                lines.append(cur)
                cur = ch
            else:
                cur += ch
        if cur:
            lines.append(cur)
        return lines

    def _cmd_labels(self, cmds: list[dict]) -> list[str]:
        """把剧本指令翻译成可读标签 (道具名走 core.items 表)."""
        out = []
        for c in cmds:
            kind = c.get("cmd", "")
            if kind == "note":                 # 剧本演出提示 (地图 NPC 对白用)
                out.append(str(c.get("arg", "")))
            elif kind == "item":
                arg = str(c.get("arg", ""))
                num = "".join(ch for ch in arg if ch.isdigit())
                name = None
                if num:
                    try:
                        from core.items import get_item_name
                        name = get_item_name(int(num))
                    except Exception:
                        name = None
                out.append(f"道具 → {name or arg}")
            elif kind == "voice":
                out.append(f"立绘/语音 → {c.get('name')}#{c.get('n')}")
            else:
                out.append(f"音乐/立绘 → {c.get('name')}")
        return out

    def draw(self) -> None:
        sw, sh = self.surface.get_size()
        if self.backdrop is not None:
            self.surface.blit(self.backdrop, (0, 0))      # 浮在场景上 (原版样式)
        else:
            self.surface.fill(self.BG)                    # 剧本预览: 独立黑底
            self.surface.blit(self.small.render(
                f"{self.title}   {self.idx + 1}/{len(self.msgs)}", True, self.DIM), (16, 12))
        if not self.msgs:
            self.surface.blit(self.font.render(
                "未找到剧本 (先跑 tools.extract_script)", True, self.TEXT),
                (16, sh // 2))
            return

        m = self.msgs[self.idx]
        # 说话人小头像 (框内左侧): 按 <face>(手工NPC的精灵) 或说话人名解析
        from core import portraits
        face = portraits.head_face(m.get("face") or m.get("speaker") or "", 46)
        # 框高自适应内容 (原版剧本一条台词可能 1~6 行, 固定高度会溢出)
        lines = self._wrap(m.get("text") or "", self.font,
                           sw - (136 if face is not None else 96))[:6]
        has_cmd = bool(m.get("cmds") or [])
        need = 48 + 30 * max(1, len(lines)) + (30 if has_cmd else 0) + 26
        box_h = max(120, min(need, max(140, sh // 2)))
        box = pygame.Rect(20, sh - box_h - 20 + int((1.0 - self._slide) * 18),
                          sw - 40, box_h)
        # 原版棕色编织窗口 (九宫格切片, 见 core/ui_window)
        from core import ui_window
        win = ui_window.window("brown")
        if win is not None:
            win.draw(self.surface, box)
            inner = pygame.Surface((box.w - 18, box.h - 18), pygame.SRCALPHA)
            inner.fill((8, 6, 20, 120))        # 暗底内衬 (面板纹理偏亮, 让字跳出来)
            self.surface.blit(inner, (box.x + 9, box.y + 9))
        else:
            overlay = pygame.Surface(box.size, pygame.SRCALPHA)
            overlay.fill(self.BOX)
            self.surface.blit(overlay, box.topleft)
            pygame.draw.rect(self.surface, self.EDGE, box, 2)

        speaker = m.get("speaker")
        scene_id = m.get("scene")
        name = speaker or (f"[{scene_id}]" if scene_id else "旁白")
        if face is not None:
            self.surface.blit(face, (box.x + 12, box.y + 12))
            text_x = box.x + 70
        else:
            text_x = box.x + 18
        # 说话人名牌: 左上角小窗口 (压在框沿上, 原版样式)
        tab_font = self.name_font
        tw = tab_font.size(name)[0] + 28
        tab = pygame.Rect(box.x + (56 if face is not None else 10), box.y - 22, tw, 32)
        if win is not None:
            ui_window.window("brown", margin=8, tile=12).draw(self.surface, tab)
        else:
            pygame.draw.rect(self.surface, self.EDGE, tab)
        self.surface.blit(tab_font.render(name, True, self.NAME), (tab.x + 14, tab.y + 4))
        y = box.y + 16

        # 演出: **原版立绘优先** (帧号来自剧本 <$CODE:帧号>), 没有立绘才用角色精灵待机动画
        portraits = list(m.get("portraits") or [])
        if portraits:
            self._draw_portraits(portraits, box)

        room = max(1, (box.h - 48 - (30 if has_cmd else 0) - 22) // 30)
        rem = int(self._reveal)          # 逐字揭示: 跨行累计
        for line in lines[:room]:
            if rem <= 0:
                break
            self.surface.blit(self.font.render(line[:rem], True, self.TEXT),
                              (text_x, y))
            rem -= len(line)
            y += 30

        cmds = m.get("cmds") or []
        if cmds:
            label = "    ".join(self._cmd_labels(cmds))
            self.surface.blit(self.small.render(label, True, (250, 200, 120)),
                              (box.x + 18, box.bottom - 52))

        # 本句显示完 → 右下角 ▼ 提示可继续 (还没出完时不显示)
        if self._reveal >= len(self._cur_text()) and self.idx < len(self.msgs) - 1:
            tx, ty = box.right - 30, box.bottom - 46
            pygame.draw.polygon(self.surface, self.NAME,
                                [(tx - 7, ty), (tx + 7, ty), (tx, ty + 9)])
        hint = self.small.render("Enter/空格 继续    ← 上一条    ESC 返回",
                                 True, self.DIM)
        self.surface.blit(hint, (box.right - hint.get_width() - 16, box.bottom - 24))
