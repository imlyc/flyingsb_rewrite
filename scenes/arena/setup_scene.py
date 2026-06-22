"""竞技场设置阶段: KOF 式选人界面 (纯键盘).

左侧选我方, 右侧选敌方. 每侧上半 = 可选池 (向下行走动画), 下半 = 已选出战 (战斗待机动画).
回车把光标角色在 池 ↔ 出战 间挪动. Tab / Shift+方向键 换区域. 空格开战, ESC 返回标题.
"""

from __future__ import annotations

import pygame

from core.anim_state import AnimationState
from core.audio_manager import AudioManager
from core.battle.setup import ENEMY_TEMPLATES
from core.character_sprites import sprite_resource
from core.sprites.atlas_classes import idle_key_from_walk_key, is_flying_sprite
from core.sprites.loaders import get_character_sprite, get_idle_sprite
from scenes.base import Scene
from scenes.menu import load_chinese_font
from scenes.unit_render import pick_locomotion_frame
from scenes.arena.roster import ENEMY_ROSTER, PLAYER_ROSTER

# 区域标识
LEFT, RIGHT = 0, 1
POOL, CHOSEN = 0, 1
COLS = 4  # 每个区域每行格数


def _enemy_sprite_key(name: str) -> str | None:
    spr = ENEMY_TEMPLATES[name].get("sprite")
    return f"ps_{spr}" if spr else None


class ArenaSetupScene(Scene):
    BG = (18, 20, 32)
    PANEL = (30, 34, 52)
    DIVIDER = (90, 96, 130)
    LABEL = (210, 210, 230)
    NAME = (230, 230, 240)
    FOCUS = (255, 230, 110)
    SIDE_TITLE_L = (130, 200, 240)
    SIDE_TITLE_R = (240, 130, 130)
    HINT = (170, 170, 190)

    # 布局常量
    TITLE_Y = 24
    SIDE_HEADER_Y = 52
    POOL_LABEL_Y = 74
    POOL_GRID_Y = 92
    CHOSEN_LABEL_Y = 346
    CHOSEN_GRID_Y = 366
    CELL_W = 94
    CELL_H = 82
    SIDE_PAD = 12
    SPRITE_H = 60  # sprite 缩放后高度

    def __init__(self, surface: pygame.Surface, audio: AudioManager) -> None:
        super().__init__(surface)
        self.audio = audio
        self.title_font = load_chinese_font(30)
        self.label_font = load_chinese_font(20)
        self.name_font = load_chinese_font(14)
        self.hint_font = load_chinese_font(15)

        # 四个名单 (存名字, 战斗时再造 BattleUnit)
        self.p_pool: list[str] = list(PLAYER_ROSTER)
        self.p_chosen: list[str] = []
        self.e_pool: list[str] = list(ENEMY_ROSTER)
        self.e_chosen: list[str] = []

        # 光标: (side, region, idx)
        self.side = LEFT
        self.region = POOL
        self.idx = 0

        # 动画状态: 可选池一直"走", 出战一直"待机" (复用 battle 的 locomotion picker)
        self._walk_anim = AnimationState()
        self._idle_anim = AnimationState()

    # ------- 生命周期 -------
    def on_enter(self) -> None:
        try:
            self.audio.play_bgm("INTRO_.WAV")
        except FileNotFoundError:
            pass

    # ------- 名单存取 -------
    def _list(self, side: int, region: int) -> list[str]:
        if side == LEFT:
            return self.p_pool if region == POOL else self.p_chosen
        return self.e_pool if region == POOL else self.e_chosen

    def _cur_list(self) -> list[str]:
        return self._list(self.side, self.region)

    def _clamp_idx(self) -> None:
        n = len(self._cur_list())
        self.idx = 0 if n == 0 else max(0, min(self.idx, n - 1))

    # ------- 输入 -------
    def handle_event(self, event: pygame.event.Event) -> bool:
        if event.type == pygame.QUIT:
            return False
        if event.type != pygame.KEYDOWN:
            return True
        mods = pygame.key.get_mods()
        shift = bool(mods & pygame.KMOD_SHIFT)
        k = event.key

        if k == pygame.K_ESCAPE:
            from scenes.menu import TitleScene
            self.next_scene = TitleScene(self.surface, self.audio)
            return True
        if k == pygame.K_SPACE:
            self._start_battle()
            return True
        if k == pygame.K_TAB:
            # 四区轮换 (跳过空区域): 我方待选 → 敌方待选 → 我方出战 → 敌方出战 → 循环
            order = [(LEFT, POOL), (RIGHT, POOL), (LEFT, CHOSEN), (RIGHT, CHOSEN)]
            cur = order.index((self.side, self.region))
            for step in range(1, len(order) + 1):
                side, region = order[(cur + step) % len(order)]
                if self._list(side, region):
                    self.side, self.region = side, region
                    break
            self._clamp_idx()
            return True
        if k in (pygame.K_RETURN, pygame.K_KP_ENTER):
            self._move_focused()
            return True

        arrow = {pygame.K_UP: (0, -1), pygame.K_DOWN: (0, 1),
                 pygame.K_LEFT: (-1, 0), pygame.K_RIGHT: (1, 0)}.get(k)
        if arrow is None:
            return True
        dx, dy = arrow
        if shift:
            # 换区域: 上下切池/出战, 左右切侧. 目标区域为空则停在当前区域.
            side, region = self.side, self.region
            if dy < 0:
                region = POOL
            elif dy > 0:
                region = CHOSEN
            elif dx < 0:
                side = LEFT
            elif dx > 0:
                side = RIGHT
            if self._list(side, region):
                self.side, self.region = side, region
                self._clamp_idx()
        else:
            self._move_cursor(dx, dy)
        return True

    def _move_cursor(self, dx: int, dy: int) -> None:
        n = len(self._cur_list())
        if n == 0:
            return
        if dy != 0:
            ni = self.idx + dy * COLS
            if 0 <= ni < n:
                self.idx = ni
        if dx != 0:
            ni = self.idx + dx
            # 不跨行环绕: 同行内移动
            if 0 <= ni < n and (self.idx // COLS == ni // COLS):
                self.idx = ni

    def _move_focused(self) -> None:
        src = self._cur_list()
        if not src:
            return
        name = src.pop(self.idx)
        dst_region = CHOSEN if self.region == POOL else POOL
        dst = self._list(self.side, dst_region)
        dst.append(name)
        # 当前区域被挪空 → 焦点跟随刚挪过去的角色 (目标区域末位)
        if not src:
            self.region = dst_region
            self.idx = len(dst) - 1
        else:
            self._clamp_idx()

    def _start_battle(self) -> None:
        if not self.p_chosen or not self.e_chosen:
            return
        from scenes.arena.battle_scene import ArenaBattleScene
        self.next_scene = ArenaBattleScene(
            self.surface, self.audio,
            player_names=list(self.p_chosen),
            enemy_names=list(self.e_chosen),
            return_scene=self,
        )

    # ------- 更新 -------
    def update(self, dt_ms: int) -> None:
        self._walk_anim.tick(dt_ms, moving=True)
        self._idle_anim.tick(dt_ms, moving=False)

    # ------- 渲染 -------
    def _frame_for(self, name: str, is_player: bool, region: int) -> pygame.Surface | None:
        """复用 battle 的 locomotion picker: 可选池=向下走, 出战=向下待机.
        flying 单位 (乌鸦怪) 由 picker 自动用走路帧扇翅膀, 不会出现空 idle."""
        key = sprite_resource(name) if is_player else _enemy_sprite_key(name)
        if key is None:
            return None
        try:
            cs = get_character_sprite(key)
        except FileNotFoundError:
            return None
        try:
            idle_sprite = get_idle_sprite(idle_key_from_walk_key(key))
        except FileNotFoundError:
            idle_sprite = None
        anim = self._walk_anim if region == POOL else self._idle_anim
        frame, _ = pick_locomotion_frame(
            cs, idle_sprite, (0, 1), anim,
            walk_period_ms=120, idle_period_ms=350,
            flying=is_flying_sprite(key),
        )
        return frame

    def _cell_rect(self, side: int, region: int, idx: int) -> pygame.Rect:
        col = idx % COLS
        row = idx // COLS
        base_x = 0 if side == LEFT else 400
        x = base_x + self.SIDE_PAD + col * self.CELL_W
        gy = self.POOL_GRID_Y if region == POOL else self.CHOSEN_GRID_Y
        y = gy + row * self.CELL_H
        return pygame.Rect(x, y, self.CELL_W, self.CELL_H)

    def _draw_grid(self, side: int, region: int) -> None:
        names = self._list(side, region)
        is_player = (side == LEFT)
        for i, name in enumerate(names):
            rect = self._cell_rect(side, region, i)
            focused = (side == self.side and region == self.region and i == self.idx)
            if focused:
                pygame.draw.rect(self.surface, self.FOCUS, rect.inflate(-4, -2), 2,
                                 border_radius=4)
            frame = self._frame_for(name, is_player, region)
            sprite_bottom = rect.bottom - 16
            if frame is not None:
                fw, fh = frame.get_size()
                scale = self.SPRITE_H / fh
                sw, sh = int(fw * scale), int(fh * scale)
                scaled = pygame.transform.scale(frame, (sw, sh))
                self.surface.blit(scaled, (rect.centerx - sw // 2, sprite_bottom - sh))
            else:
                ph = pygame.Rect(0, 0, 36, 48)
                ph.midbottom = (rect.centerx, sprite_bottom)
                pygame.draw.rect(self.surface, (140, 90, 90), ph, border_radius=4)
            label = self.name_font.render(name, True,
                                          self.FOCUS if focused else self.NAME)
            self.surface.blit(label, label.get_rect(center=(rect.centerx, rect.bottom - 8)))

    def draw(self) -> None:
        self.surface.fill(self.BG)
        w, h = self.surface.get_size()

        # 标题
        title = self.title_font.render("竞技场 — 选择出战角色", True, (255, 215, 90))
        self.surface.blit(title, title.get_rect(center=(w // 2, self.TITLE_Y)))

        # 中央分隔线
        pygame.draw.line(self.surface, self.DIVIDER, (w // 2, 44), (w // 2, h - 38), 2)
        # 池/出战 水平分隔
        for base in (0, w // 2):
            pygame.draw.line(self.surface, self.DIVIDER,
                             (base + 8, self.CHOSEN_LABEL_Y - 8),
                             (base + w // 2 - 8, self.CHOSEN_LABEL_Y - 8), 1)

        # 侧标题
        lt = self.label_font.render("我方", True, self.SIDE_TITLE_L)
        self.surface.blit(lt, lt.get_rect(center=(w // 4, self.SIDE_HEADER_Y)))
        rt = self.label_font.render("敌方", True, self.SIDE_TITLE_R)
        self.surface.blit(rt, rt.get_rect(center=(w * 3 // 4, self.SIDE_HEADER_Y)))

        # 区域标签
        for base in (0, w // 2):
            pl = self.name_font.render("可选", True, self.LABEL)
            self.surface.blit(pl, (base + self.SIDE_PAD, self.POOL_LABEL_Y))
            cl = self.name_font.render("出战", True, self.LABEL)
            self.surface.blit(cl, (base + self.SIDE_PAD, self.CHOSEN_LABEL_Y))

        # 四个网格
        for side in (LEFT, RIGHT):
            for region in (POOL, CHOSEN):
                self._draw_grid(side, region)

        # 底部提示
        ready = bool(self.p_chosen and self.e_chosen)
        hint = ("方向键移动光标   回车: 选/取消出战   Tab/Shift+方向: 换区域   "
                + ("空格: 开始战斗" if ready else "(双方各需≥1人)")
                + "   ESC: 返回")
        ht = self.hint_font.render(hint, True, self.FOCUS if ready else self.HINT)
        self.surface.blit(ht, ht.get_rect(center=(w // 2, h - 18)))
