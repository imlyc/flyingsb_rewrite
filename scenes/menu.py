"""主菜单场景."""

from __future__ import annotations

import os
from pathlib import Path

import pygame

from core.audio_manager import AudioManager
from core.save_manager import load_save, new_game_save
from scenes.base import Scene

CHINESE_FONT_CANDIDATES = [
    # macOS
    "/System/Library/Fonts/STHeiti Medium.ttc",
    "/System/Library/Fonts/STHeiti Light.ttc",
    "/System/Library/Fonts/Supplemental/Songti.ttc",
    "/System/Library/Fonts/Supplemental/Arial Unicode.ttf",
    "/System/Library/Fonts/PingFang.ttc",
    # Windows
    "C:/Windows/Fonts/msyh.ttc",     # 微软雅黑
    "C:/Windows/Fonts/msyhbd.ttc",
    "C:/Windows/Fonts/simhei.ttf",   # 黑体
    "C:/Windows/Fonts/simsun.ttc",   # 宋体
    "C:/Windows/Fonts/simkai.ttf",   # 楷体
    "C:/Windows/Fonts/Deng.ttf",     # 等线
    # Linux
    "/usr/share/fonts/truetype/wqy/wqy-microhei.ttc",
    "/usr/share/fonts/truetype/wqy/wqy-zenhei.ttc",
    "/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc",
    "/usr/share/fonts/truetype/arphic/uming.ttc",
]

# 系统字体名 (pygame.font.match_font 用, 需小写无空格); 覆盖 Win/macOS/Linux 常见中文字体
CHINESE_SYSFONT_NAMES = [
    "microsoftyahei", "microsoftyaheiui", "simhei", "simsun", "nsimsun",
    "kaiti", "dengxian", "pingfangsc", "stheiti", "heitisc",
    "notosanscjksc", "notosanscjktc", "wenquanyimicrohei", "wenquanyizenhei",
    "arplumingcn", "arplukai",
]

# 原版存档: 默认 repo 上一级 origin/ 里的全剧情存档, 可用 FLYINGSB_SAVE 环境变量覆盖
DEFAULT_SAVE = Path(os.environ.get(
    "FLYINGSB_SAVE",
    Path(__file__).resolve().parents[2] / "origin" / "flyingsb"
    / "工具大全" / "存档" / "全剧情存档" / "0" / "Save1.dat",
))


def load_chinese_font(size: int) -> pygame.font.Font:
    """加载支持中文的字体: 依次尝试已知字体文件路径 → 系统字体名匹配 → 兜底."""
    # 1. 直接按文件路径加载 (跨平台常见中文字体)
    for p in CHINESE_FONT_CANDIDATES:
        try:
            return pygame.font.Font(p, size)
        except (FileNotFoundError, OSError):
            continue
    # 2. 用系统字体名让 pygame 定位字体文件 (Windows/macOS/Linux 通用)
    for name in CHINESE_SYSFONT_NAMES:
        path = pygame.font.match_font(name)
        if path:
            try:
                return pygame.font.Font(path, size)
            except (FileNotFoundError, OSError):
                continue
    # 3. 最后兜底: 让 SysFont 自己在候选名里挑 (找不到中文时也不崩)
    return pygame.font.SysFont(
        "microsoftyahei,simhei,simsun,pingfangsc,notosanscjk", size
    )


class TitleScene(Scene):
    """标题画面: 标题 + 3 个菜单项, 上下选择, 回车确认."""

    BG_COLOR = (20, 20, 40)
    TITLE_COLOR = (255, 215, 90)
    ITEM_COLOR = (220, 220, 220)
    ITEM_HIGHLIGHT = (255, 255, 255)
    ITEM_HIGHLIGHT_BG = (80, 60, 30)

    def __init__(self, surface: pygame.Surface, audio: AudioManager):
        super().__init__(surface)
        self.audio = audio
        self.title_font = load_chinese_font(64)
        self.item_font = load_chinese_font(36)
        self.items: list[tuple[str, callable]] = [
            ("竞技场", self._action_arena),
            ("剧情回放", self._action_script_viewer),
            ("新游戏", self._action_new_game),
            ("读取存档", self._action_load_save),
            ("退出", self._action_quit),
        ]
        self.selected = 0
        self._quit_requested = False

    def on_enter(self) -> None:
        try:
            self.audio.play_bgm("INTRO_.WAV")
        except FileNotFoundError as e:
            print(f"BGM 缺失: {e}")

    # ------- 输入 -------
    def handle_event(self, event: pygame.event.Event) -> bool:
        if event.type == pygame.QUIT:
            return False
        if event.type != pygame.KEYDOWN:
            return True
        if event.key == pygame.K_ESCAPE:
            return False
        if event.key in (pygame.K_UP, pygame.K_w):
            self.selected = (self.selected - 1) % len(self.items)
        elif event.key in (pygame.K_DOWN, pygame.K_s):
            self.selected = (self.selected + 1) % len(self.items)
        elif event.key in (pygame.K_RETURN, pygame.K_SPACE, pygame.K_KP_ENTER):
            self.items[self.selected][1]()
            if self._quit_requested:
                return False
        return True

    # ------- 菜单动作 -------
    def _action_new_game(self) -> None:
        # 延迟 import 避免 menu <-> world_map 循环导入
        from scenes.world_map.scene import WorldMapScene
        from scenes import prologue as prologue_scene

        def world_after_prologue() -> WorldMapScene:
            # 复刻原版: 新游戏主角 **美娜** 开局 (其余角色后续入队); 序章末尾车坏在小森林 (TBB0___P, id 476),
            # 玩家从那里接手, 出村(南) -> 五指村 (见 world_graph._EXTRA_TRANSITIONS)
            scene = WorldMapScene(self.surface, self.audio, save=new_game_save())
            # 序章 ev9 结尾 42.01 把美娜放在 (10,8) (车坏处), 不是 .mfo 的东口 pcpos (22,9)
            scene.enter_location("TBB0___P", spawn=(10, 8), auto_beat=False)
            return scene

        if not prologue_scene.available():
            scene = world_after_prologue()
            scene.enter_location("TBB0___P")          # 没有序章数据: 走旧的对白版开篇
            self.next_scene = scene
            return
        # 标题直接进序章; 演完 (或 ESC 跳过) 再建世界地图, 并把"序章"节点记为已完成
        pro = prologue_scene.PrologueScene(self.surface, return_scene=None, audio=self.audio)

        def on_close() -> None:
            scene = world_after_prologue()
            beat = scene.story.current()
            if beat is not None and beat.id == "intro":
                scene.story.apply_presave(beat, scene.save)
                scene._after_beat(beat)
            pro.next_scene = scene

        pro.on_close = on_close
        self.next_scene = pro

    def _action_load_save(self) -> None:
        # 打开读档界面 (3 个 remake 存档槽 + 可选的原版全剧情存档)
        from scenes.pause import PauseScene
        self.next_scene = PauseScene(self.surface, None, self.audio,
                                     mode="load", include_original=True)

    def _action_arena(self) -> None:
        from scenes.arena import ArenaSetupScene
        self.next_scene = ArenaSetupScene(self.surface, self.audio)

    def _action_script_viewer(self) -> None:
        from scenes.script_viewer import ScriptViewerScene
        self.next_scene = ScriptViewerScene(self.surface, self)

    def _action_quit(self) -> None:
        self._quit_requested = True

    # ------- 渲染 -------
    def draw(self) -> None:
        self.surface.fill(self.BG_COLOR)
        w, h = self.surface.get_size()

        title = self.title_font.render("幻想西游记", True, self.TITLE_COLOR)
        self.surface.blit(title, title.get_rect(center=(w // 2, h // 4)))

        # 菜单项从中线略上开始, 行距按条数算, 最后一行离底边 ≥ 40px
        spacing = min(56, (h - 40 - (h // 2 - 30)) // max(1, len(self.items)))
        start_y = h // 2 - 30
        for i, (label, _) in enumerate(self.items):
            highlight = (i == self.selected)
            color = self.ITEM_HIGHLIGHT if highlight else self.ITEM_COLOR
            text = self.item_font.render(label, True, color)
            rect = text.get_rect(center=(w // 2, start_y + i * spacing))
            if highlight:
                bg = rect.inflate(40, 12)
                pygame.draw.rect(self.surface, self.ITEM_HIGHLIGHT_BG, bg, border_radius=6)
            self.surface.blit(text, rect)
