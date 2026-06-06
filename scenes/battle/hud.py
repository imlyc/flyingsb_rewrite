"""战斗场景 HUD/菜单/banner/日志 渲染.

自由函数, 第一参数 scene. 不持有状态, 每次从 scene 读字体/颜色/数据.
"""

from __future__ import annotations

import math
from typing import TYPE_CHECKING

import pygame

from core.battle.data import BattleUnit, LevelUpReport, Phase
from core.character import UNSET
from core.sprites.base import TILE_W, TILE_H

if TYPE_CHECKING:
    from scenes.battle.scene import BattleScene


# HUD 布局常量 (顶部双卡片)
HUD_X = 12
HUD_Y = 12
HUD_W_CUR = 280
HUD_W_NEXT = 220
LOG_H = 100

# 技能二级菜单尺寸 (跨 _draw_skill_submenu + 过渡动画白框落点 + desc 栏共享)
SKILL_PANEL_W = 312
SKILL_PANEL_TOP = 20
SKILL_ROW_H = 28                       # 每行高度 (= desc 栏高度, 字体 16pt + 边距)
# 描述长条: 横跨屏幕底部, 左右等距留白 32px, 高度 = 字体 + 小边距.
SKILL_DESC_BAR_H = 28
SKILL_DESC_BAR_SIDE_MARGIN = 32        # 距屏幕左/右的留白
SKILL_DESC_BAR_MARGIN = 8              # 距屏幕底的留白
# 技能 panel 底部预留: 等于 desc 栏总占用 + panel 顶 + panel/desc 之间的 8px 间距,
# 保证 panel.bottom + 8 = desc_bar.top (rect h = sh - bottom_margin, panel.bottom = top + h).
SKILL_PANEL_BOTTOM_MARGIN = SKILL_PANEL_TOP + 8 + SKILL_DESC_BAR_H + SKILL_DESC_BAR_MARGIN

# Win95 风格立体凸起面板配色 (原版战斗菜单 UI):
# - 填充: 暗橄榄绿 (用户实测原版 skill_menu.png 采样 (93,90,55))
# - 上+左边缘: 白色 (光源在左上方的高光)
# - 下+右边缘: 黑色 (右下方的阴影)
PANEL_FILL = (93, 90, 55)
PANEL_LIGHT = (255, 255, 255)
PANEL_SHADOW = (0, 0, 0)


def draw_beveled_panel(surface: pygame.Surface, rect: pygame.Rect,
                       fill: tuple[int, int, int] = PANEL_FILL,
                       light: tuple[int, int, int] = PANEL_LIGHT,
                       shadow: tuple[int, int, int] = PANEL_SHADOW,
                       border_w: int = 1) -> None:
    """Win95 风格立体凸起面板: 纯色填充 + 左/上白边 + 右/下黑边.
    原版战斗菜单 UI 都是这套样式; 颜色可以替换 (玩家可改色, 默认暗橄榄绿)."""
    surface.fill(fill, rect)
    x, y, w, h = rect
    # 左 + 上 = 高光
    pygame.draw.line(surface, light, (x, y), (x + w - 1, y), border_w)
    pygame.draw.line(surface, light, (x, y), (x, y + h - 1), border_w)
    # 右 + 下 = 阴影
    pygame.draw.line(surface, shadow, (x, y + h - 1), (x + w - 1, y + h - 1), border_w)
    pygame.draw.line(surface, shadow, (x + w - 1, y), (x + w - 1, y + h - 1), border_w)


def draw_floats(scene: "BattleScene", cam_x: int, cam_y: int) -> None:
    now = pygame.time.get_ticks()
    for f in scene._floats:
        f.draw(scene.surface, scene._float_big, scene._float_small, cam_x, cam_y, now)


def draw_action_menu(scene: "BattleScene", cam_x: int, cam_y: int) -> None:
    """十字 4 选项 + 二级菜单 + 全部过渡动画.
    状态机:
      _menu_anim_t != None       → 一级打开动画
      _menu_transition_t != None → 一级→二级 过渡动画 (3 phase)
      _menu_open + _submenu=None → 静态一级
      _submenu='skill'           → 静态二级
    """
    if (not scene._menu_open and scene._submenu is None
            and scene._menu_close_t is None
            and scene._menu_dismiss_t is None):
        return
    from core.sprites.loaders import (
        SMENU_END, SMENU_ITEM, SMENU_SETTINGS, SMENU_SKILL, load_smenu_icon,
    )

    u = scene.battle.current
    ucx = u.x * TILE_W - cam_x + TILE_W // 2
    # ucy 落在当前 tile 顶边 (= 上一 tile 底边), 让九宫格跨这条边居中.
    ucy = u.y * TILE_H - cam_y
    offset = 32
    # icon 最终位置 + 极角. 极角约定: 0=右, π/2=下, π=左, -π/2=上.
    placements = [
        (SMENU_SKILL,    ucx,          ucy - offset, -math.pi / 2),
        (SMENU_ITEM,     ucx - offset, ucy,           math.pi),
        (SMENU_SETTINGS, ucx + offset, ucy,           0.0),
        (SMENU_END,      ucx,          ucy + offset,  math.pi / 2),
    ]

    # 1. 反向关闭 (二级 → 一级): 二级 panel 缩小消失, 白框已无
    if scene._menu_close_t is not None:
        progress = scene._menu_close_t / scene.MENU_CLOSE_MS
        _draw_skill_submenu(scene, scale=max(0.0, 1.0 - progress),
                            draw_highlight_row=False)
        return

    # 2. 一级打开动画
    if scene._menu_anim_t is not None:
        _draw_menu_open_anim(scene, ucx, ucy, placements, offset)
        return

    # 3. 一级 → 二级 过渡动画
    if scene._menu_transition_t is not None:
        _draw_menu_transition(scene, ucx, ucy, placements, offset)
        return

    # 4. 一级关闭动画 (回战斗): icons 旋转淡出 + 可选白框移到选中 icon 位置
    if scene._menu_dismiss_t is not None:
        _draw_menu_dismiss(scene, ucx, ucy, placements, offset)
        return

    # 3. 静态一级
    if scene._menu_open:
        for icon_idx, x, y, _ in placements:
            icon = load_smenu_icon(icon_idx)
            scene.surface.blit(icon, icon.get_rect(center=(x, y)))
        scene.surface.fill((255, 255, 255), pygame.Rect(ucx - 1, ucy - 1, 2, 2))

    # 4. 静态二级 (transition 完成后也走这里)
    if scene._submenu == 'skill':
        _draw_skill_submenu(scene, draw_highlight_row=True)


_SURROUND_SIZE = 36   # 白框包住一个 icon 的边长 (略大于 32 给视觉间隙)


def _draw_icons_rotate_out(scene: "BattleScene", ucx: int, ucy: int,
                           placements, offset: int, progress: float,
                           target_icon: int | None) -> None:
    """复用动画原语: 4 个 icon 顺时针再转 90° + 淡出, 同时白点扩成白框移到 target icon.
    progress 0→1. target_icon=None 时白框不画 (ESC 路径).
    用于 L1→战斗 的 dismiss 和 L1→L2 过渡 phase A.
    """
    from core.sprites.loaders import load_smenu_icon

    # 4 icons 旋转 + 淡出
    for icon_idx, fx, fy, final_angle in placements:
        angle = final_angle + progress * (math.pi / 2)
        x = ucx + int(offset * math.cos(angle))
        y = ucy + int(offset * math.sin(angle))
        icon = load_smenu_icon(icon_idx).copy()
        icon.set_alpha(int(255 * (1 - progress)))
        scene.surface.blit(icon, icon.get_rect(center=(x, y)))

    if target_icon is None:
        return

    # 白点/白框: 中心 → target icon 位置 + 2 → SURROUND_SIZE
    sel_x, sel_y = ucx, ucy
    for icon_idx, fx, fy, _ in placements:
        if icon_idx == target_icon:
            sel_x, sel_y = fx, fy
            break
    fx_pos = int(ucx + (sel_x - ucx) * progress)
    fy_pos = int(ucy + (sel_y - ucy) * progress)
    size = int(2 + (_SURROUND_SIZE - 2) * progress)
    rect = pygame.Rect(0, 0, size, size)
    rect.center = (fx_pos, fy_pos)
    if size <= 2:
        scene.surface.fill((255, 255, 255), rect)
    else:
        pygame.draw.rect(scene.surface, (255, 255, 255), rect, 1)


def _draw_menu_dismiss(scene: "BattleScene", ucx: int, ucy: int,
                       placements, offset: int) -> None:
    """一级菜单关闭回战斗 — 直接复用 _draw_icons_rotate_out."""
    progress = min(1.0, scene._menu_dismiss_t / scene.MENU_DISMISS_MS)
    _draw_icons_rotate_out(scene, ucx, ucy, placements, offset, progress,
                           scene._menu_dismiss_target)


def _draw_menu_transition(scene: "BattleScene", ucx: int, ucy: int,
                          placements, offset: int) -> None:
    """一级 → 二级 三段过渡:
       A: 4 icon 再顺时针 90° + 淡出; 白点扩成白框, 中心移到选中 icon 的位置 (复用 dismiss 原语).
       B: 二级菜单 panel 从中心缩放出现 (白框保持在选中 icon 位置).
       C: 白框移动 + 变形, 包到二级菜单首行选项.
    """
    t = scene._menu_transition_t
    A = scene.MENU_TRANSITION_A_MS
    B = A + scene.MENU_TRANSITION_B_MS
    sw, sh = scene.surface.get_size()

    # 选中 icon 的一级 final 位置 (白框中转点)
    target = scene._menu_transition_target
    sel_x, sel_y = ucx, ucy
    for icon_idx, fx, fy, _ in placements:
        if icon_idx == target:
            sel_x, sel_y = fx, fy
            break

    # 二级菜单首行选项 rect (白框最终落点; 跟 _draw_skill_submenu 保持一致)
    panel_full = pygame.Rect(sw - SKILL_PANEL_W - SKILL_DESC_BAR_SIDE_MARGIN,
                             SKILL_PANEL_TOP,
                             SKILL_PANEL_W, sh - SKILL_PANEL_BOTTOM_MARGIN)
    target_row = pygame.Rect(panel_full.x + 12, panel_full.y + 42,
                             panel_full.w - 24, SKILL_ROW_H)

    if t < A:
        # Phase A: 跟 dismiss 同形 — 直接复用 _draw_icons_rotate_out
        _draw_icons_rotate_out(scene, ucx, ucy, placements, offset,
                               progress=t / A, target_icon=target)
        return

    if t < B:
        # Phase B: 二级菜单 panel scale 0→1; 白框停在 sel icon 位置
        progress_b = (t - A) / (B - A)
        _draw_skill_submenu(scene, draw_highlight_row=False, scale=progress_b)
        rect = pygame.Rect(0, 0, _SURROUND_SIZE, _SURROUND_SIZE)
        rect.center = (sel_x, sel_y)
        pygame.draw.rect(scene.surface, (255, 255, 255), rect, 1)
        return

    # Phase C: 二级菜单已完整; 白框从 (sel icon 位置, 36×36) → 首行选项 rect
    progress_c = (t - B) / (scene.MENU_TRANSITION_TOTAL_MS - B)
    _draw_skill_submenu(scene, draw_highlight_row=False)
    start = pygame.Rect(0, 0, _SURROUND_SIZE, _SURROUND_SIZE)
    start.center = (sel_x, sel_y)
    cur_x = int(start.x + (target_row.x - start.x) * progress_c)
    cur_y = int(start.y + (target_row.y - start.y) * progress_c)
    cur_w = int(start.w + (target_row.w - start.w) * progress_c)
    cur_h = int(start.h + (target_row.h - start.h) * progress_c)
    pygame.draw.rect(scene.surface, (255, 255, 255),
                     pygame.Rect(cur_x, cur_y, cur_w, cur_h), 1)


def _draw_menu_open_anim(scene: "BattleScene", ucx: int, ucy: int,
                         placements, offset: int) -> None:
    """打开菜单的同步动画 (单段 progress 0→1):
      白方框 (border only) 从大收到 0,
      4 icon 同时顺时针绕中心一圈, scale 0→1, radius 0→32.
    """
    from core.sprites.loaders import load_smenu_icon
    progress = scene._menu_anim_t / scene.MENU_ANIM_TOTAL_MS
    progress = max(0.0, min(1.0, progress))

    # 白方框收缩 (按 tile 比例 64:48, 起始 3× tile = 192×144)
    OUTER_W = TILE_W * 3
    OUTER_H = TILE_H * 3
    w = int(OUTER_W * (1 - progress))
    h = int(OUTER_H * (1 - progress))
    if w > 0 and h > 0:
        rect = pygame.Rect(0, 0, w, h)
        rect.center = (ucx, ucy)
        pygame.draw.rect(scene.surface, (255, 255, 255), rect, 1)

    # 4 icon 旋转 + 放大. 顺时针 90°. pygame y 朝下, 视觉顺时针 = math 角度递增,
    # 所以 sweep 用负号: start = final - 90°, 向 final 推进时角度增大 → 屏幕顺时针.
    sweep = -math.pi / 2
    for icon_idx, fx, fy, final_angle in placements:
        angle = final_angle + (1 - progress) * sweep
        r = progress * offset
        x = ucx + int(r * math.cos(angle))
        y = ucy + int(r * math.sin(angle))
        scaled_size = max(1, int(32 * progress))
        icon = load_smenu_icon(icon_idx)
        if scaled_size != 32:
            icon = pygame.transform.scale(icon, (scaled_size, scaled_size))
        scene.surface.blit(icon, icon.get_rect(center=(x, y)))
    # 中心白点 (锚定)
    scene.surface.fill((255, 255, 255), pygame.Rect(ucx - 1, ucy - 1, 2, 2))


def _draw_skill_submenu(scene: "BattleScene", *,
                        draw_highlight_row: bool = True,
                        scale: float = 1.0) -> None:
    """二级菜单: 标题「特殊能力」+ 当前角色已学技能列表 (BattleUnit.known_skills).
    scale<1 时 panel 从中心缩放出现 (phase B 用);
    draw_highlight_row=False 时不画黄色行框 (phase C 由动画白框替代).
    布局参考原版 h070: 屏幕右半的高条 + 屏幕底部的水平描述长条 (= 选中技能的描述).
    """
    sw, sh = scene.surface.get_size()
    panel_full = pygame.Rect(sw - SKILL_PANEL_W - SKILL_DESC_BAR_SIDE_MARGIN,
                             SKILL_PANEL_TOP,
                             SKILL_PANEL_W, sh - SKILL_PANEL_BOTTOM_MARGIN)
    if scale < 0.05:
        return

    # 缩放后的 panel (保持 panel_full 中心)
    cx, cy = panel_full.center
    pw = max(2, int(panel_full.w * scale))
    ph = max(2, int(panel_full.h * scale))
    panel = pygame.Rect(0, 0, pw, ph)
    panel.center = (cx, cy)

    draw_beveled_panel(scene.surface, panel)

    if scale < 0.95:
        return    # 缩放中不画文字 / 选项行

    # 标题
    title = scene.font.render("特殊能力", True, PANEL_LIGHT)
    scene.surface.blit(title, (panel.x + 14, panel.y + 10))

    from core.skills import get_skill_name
    skills = scene.battle.current.known_skills
    cursor = scene._skill_cursor if skills else 0
    list_top = panel.y + 42

    if not skills:
        row = pygame.Rect(panel.x + 12, list_top, panel.w - 24, SKILL_ROW_H + 2)
        if draw_highlight_row:
            pygame.draw.rect(scene.surface, scene.HIGHLIGHT, row, 1)
        empty = scene._menu_font.render("(无)", True, scene.DIM)
        scene.surface.blit(empty, empty.get_rect(midleft=(row.x + 8, row.centery)))
    else:
        for i, sid in enumerate(skills):
            row = pygame.Rect(panel.x + 12, list_top + i * SKILL_ROW_H,
                              panel.w - 24, SKILL_ROW_H - 2)
            if draw_highlight_row and i == cursor:
                pygame.draw.rect(scene.surface, PANEL_LIGHT, row, 1)
            text_color = PANEL_LIGHT if i == cursor else (220, 220, 220)
            name = scene._menu_font.render(get_skill_name(sid), True, text_color)
            scene.surface.blit(name, name.get_rect(midleft=(row.x + 8, row.centery)))


def draw_skill_desc_bar(scene: "BattleScene") -> None:
    """L2 二级菜单底部的水平描述长条 — 显示当前选中技能的描述.
    布局: 横跨屏幕底部, 左右等距留白, 单行高 (= 字体 + 几像素边距).
    """
    sw, sh = scene.surface.get_size()
    sx = SKILL_DESC_BAR_SIDE_MARGIN
    rect = pygame.Rect(sx, sh - SKILL_DESC_BAR_H - SKILL_DESC_BAR_MARGIN,
                       sw - 2 * sx, SKILL_DESC_BAR_H)
    draw_beveled_panel(scene.surface, rect)

    skills = scene.battle.current.known_skills
    if not skills:
        return
    from core.skills import get_skill_desc
    sid = skills[min(scene._skill_cursor, len(skills) - 1)]
    desc = get_skill_desc(sid)
    if not desc:
        return
    # 单行渲染. 长 desc 也强制单行 (整段在一栏长条里); 实际原版 desc 都很短不会越界.
    t = scene._menu_font.render(desc, True, PANEL_LIGHT)
    scene.surface.blit(t, t.get_rect(midleft=(rect.x + 10, rect.centery)))


def draw_hud(scene: "BattleScene") -> None:
    draw_actor_card(scene, HUD_X, HUD_Y, HUD_W_CUR, 70, scene.battle.current,
                    label="当前行动", highlight=True)
    nxt = scene.battle.next_actor()
    if nxt is not None:
        draw_actor_card(scene, HUD_X + HUD_W_CUR + 12, HUD_Y, HUD_W_NEXT, 70, nxt,
                        label="下一行动", highlight=False)


def draw_actor_card(scene: "BattleScene", x: int, y: int, w: int, h: int,
                    u: BattleUnit, label: str, highlight: bool) -> None:
    rect = pygame.Rect(x, y, w, h)
    # 半透明底
    bg = pygame.Surface(rect.size, pygame.SRCALPHA)
    bg.fill((28, 22, 40, 220))
    scene.surface.blit(bg, rect)
    pygame.draw.rect(scene.surface,
                     scene.HIGHLIGHT if highlight else scene.PANEL_BORDER,
                     rect, 2 if highlight else 1)
    avatar = pygame.Rect(x + 6, y + 6, h - 12, h - 12)
    pygame.draw.rect(scene.surface, u.color, avatar)
    pygame.draw.rect(scene.surface, (0, 0, 0), avatar, 1)
    side = (u.name[0] if u.is_player else "敌")
    t = scene.font.render(side, True, (0, 0, 0))
    scene.surface.blit(t, t.get_rect(center=avatar.center))

    tx = avatar.right + 10
    ty = y + 4
    tag = scene.tiny.render(label, True,
                            scene.HIGHLIGHT if highlight else scene.DIM)
    scene.surface.blit(tag, (tx, ty)); ty += 14
    name_text = f"{u.name}  Lv{u.level}"
    t = scene.font.render(name_text, True, scene.TEXT)
    scene.surface.blit(t, (tx, ty)); ty += 22
    line = f"HP {u.display_hp}/{u.max_hp}   MP {u.mp}/{u.max_mp}"   # 显示滞后到结算 (见 BattleUnit.display_hp)
    t = scene.small.render(line, True, scene.TEXT)
    scene.surface.blit(t, (tx, ty)); ty += 16
    draw_sg_icons(scene, tx, ty, u.sg)
    agi_text = f"敏 {u.agile}  移 {u.move}"
    t = scene.tiny.render(agi_text, True, scene.DIM)
    scene.surface.blit(t, (tx + 80, ty + 1))


def draw_sg_icons(scene: "BattleScene", x: int, y: int, sg: int, max_slots: int = 5) -> None:
    if sg == UNSET:
        t = scene.small.render("SG ∞", True, scene.HIGHLIGHT)
        scene.surface.blit(t, (x, y - 1))
        return
    label = scene.tiny.render("SG", True, scene.DIM)
    scene.surface.blit(label, (x, y))
    slot_w = 6; gap = 2; ox = x + 22
    slots = max(1, min(max_slots, max(1, sg // 5 if sg > 0 else 1)))
    filled = min(slots, max(0, sg // 2))
    for i in range(slots):
        r = pygame.Rect(ox + i * (slot_w + gap), y + 2, slot_w, 10)
        color = scene.HIGHLIGHT if i < filled else scene.DIM
        pygame.draw.rect(scene.surface, color, r)


def draw_log(scene: "BattleScene") -> None:
    sw, sh = scene.surface.get_size()
    rect = pygame.Rect(8, sh - LOG_H - 8, sw - 16, LOG_H)
    bg = pygame.Surface(rect.size, pygame.SRCALPHA)
    bg.fill((20, 14, 30, 210))
    scene.surface.blit(bg, rect)
    pygame.draw.rect(scene.surface, scene.PANEL_BORDER, rect, 1)
    max_lines = max(1, (LOG_H - 12) // 18)
    msgs = scene.battle.messages[-max_lines:]
    for i, m in enumerate(msgs):
        t = scene.small.render(m, True, scene.TEXT)
        scene.surface.blit(t, (rect.x + 8, rect.y + 6 + i * 18))


def draw_end_banner(scene: "BattleScene") -> None:
    if scene.battle.phase == Phase.DEFEAT:
        _draw_simple_banner(scene, "战  败", (220, 90, 90), "游戏结束", "按任意键返回地图")
        return
    # VICTORY
    if not scene._victory_acknowledged:
        sub = f"经验 +{scene.battle.exp_gained}    金钱 +{scene.battle.money_gained}"
        _draw_simple_banner(scene, "胜  利", (90, 220, 100), sub, "按任意键继续")
        return
    # 翻升级对话框
    if 0 <= scene._levelup_idx < len(scene.battle.level_ups):
        _draw_levelup_dialog(scene, scene.battle.level_ups[scene._levelup_idx])


def _draw_simple_banner(scene: "BattleScene", title: str, color: tuple, sub: str, hint: str) -> None:
    sw, sh = scene.surface.get_size()
    big = scene.big.render(title, True, color)
    rect = big.get_rect(center=(sw // 2, sh // 2 - 30))
    bg = rect.inflate(80, 40)
    pygame.draw.rect(scene.surface, (0, 0, 0), bg)
    pygame.draw.rect(scene.surface, color, bg, 3)
    scene.surface.blit(big, rect)
    sub_t = scene.font.render(sub, True, scene.TEXT)
    scene.surface.blit(sub_t, sub_t.get_rect(center=(sw // 2, rect.bottom + 20)))
    hint_t = scene.small.render(hint, True, scene.DIM)
    scene.surface.blit(hint_t, hint_t.get_rect(center=(sw // 2, rect.bottom + 46)))


def _draw_levelup_dialog(scene: "BattleScene", rep: "LevelUpReport") -> None:
    """模仿原版 f144: 「<名字> 等级 up!」+ 「提升了 HP/攻击/防御 N」."""
    sw, sh = scene.surface.get_size()
    lines = [f"{rep.name}  等级 up!  → Lv{rep.new_level}"]
    if rep.hp_inc:  lines.append(f"  提升了 HP   +{rep.hp_inc}")
    if rep.mp_inc:  lines.append(f"  提升了 MP   +{rep.mp_inc}")
    if rep.atk_inc: lines.append(f"  提升了 攻击 +{rep.atk_inc}")
    if rep.def_inc: lines.append(f"  提升了 防御 +{rep.def_inc}")

    # 估算尺寸
    title_surf = scene.font.render(lines[0], True, scene.HIGHLIGHT)
    body_surfs = [scene.font.render(l, True, scene.TEXT) for l in lines[1:]]
    line_h = 28
    w = max(title_surf.get_width(), *(s.get_width() for s in body_surfs)) + 60
    h = 24 + line_h * len(lines) + 28  # title + body + hint
    box = pygame.Rect(0, 0, w, h)
    box.center = (sw // 2, sh // 2)

    # 半透明黑底 + 黄边
    bg = pygame.Surface(box.size, pygame.SRCALPHA)
    bg.fill((0, 0, 0, 230))
    scene.surface.blit(bg, box)
    pygame.draw.rect(scene.surface, scene.HIGHLIGHT, box, 2)

    y = box.y + 14
    scene.surface.blit(title_surf, title_surf.get_rect(midtop=(box.centerx, y)))
    y += line_h + 4
    for s in body_surfs:
        scene.surface.blit(s, (box.x + 30, y))
        y += line_h
    # 翻页提示
    idx = scene._levelup_idx + 1
    total = len(scene.battle.level_ups)
    hint = scene.small.render(f"按任意键继续 ({idx}/{total})", True, scene.DIM)
    scene.surface.blit(hint, hint.get_rect(midbottom=(box.centerx, box.bottom - 6)))
