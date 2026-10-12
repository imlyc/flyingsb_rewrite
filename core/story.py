"""剧情推进系统 (B): 主线剧本流 + 事件 flag + 章节链路.

真值来源
--------
1. **剧本流**：`assets/script/messages.json` 里 `scene == "P"` 的条目按**数组顺序**
   就是原版主线剧本（exe 剧本区线性排布，段落内部连续）。例如：
     P[131]「連個礦山都沒有的村莊，到底為什麼會需要*土製炸彈*」
     P[140]「得到四個*土製炸彈*」
     P[179]「請他喝酒( 300*G* )」      ← 攻略里的嗜酒老人 300G
     P[185]「美娜，與醉老伯談話」
     P[195]「五行山!!」
     P[2944]「*蒙面人*加入，一起同行」
     P[2946]「我姓*孫*，名叫*悟空*」
     P[3056]「這叫*精靈香吻*」
     P[3098]「這是叫*禁箍之笛*的東西」
     P[3100]「那頂*帽子*是絕對脫不下來的!」
2. **流程顺序**（哪一章先、哪一章后）依据官方攻略 `origin/flyingsb/游戏攻略.txt`。
3. **事件模型**：原版是"事件编号 + 位标记"（exe 调试串
   `Input Event No.` / `EVENT-Flag View` / `Event %d's flag : %d`）；
   `.mfo` 里没有 event/group 段（487 张图全都没有），所以"谁在哪触发什么"
   由位置/角色 ID + 剧本表决定，流程由攻略串起来 —— 本模块就是这个串接层。

对外 API
--------
    main_story()                scene=P 的剧本流 (按数组顺序)
    BEATS                       章节节点 (来自攻略, 锚定真实剧本下标)
    StoryState                  flag 集合 + 已完成节点; current() / messages() / complete()
"""

from __future__ import annotations

import json
import re
from functools import lru_cache
from pathlib import Path

from core.script_text import parse

ROOT = Path(__file__).resolve().parent.parent
MESSAGES = ROOT / "assets" / "script" / "messages.json"
MAIN_SCENE = "P"


@lru_cache(maxsize=1)
def main_story() -> list[dict]:
    """主线剧本流: scene == 'P' 的条目, 按数组顺序.

    每条保留 `"_idx"` = 它在 messages.json 里的**全局下标** —— 章节锚点用的就是这个下标
    (见文件头注释里的 P[131]/P[2944]/P[3098] 等), 与过滤后的列表下标不同。
    """
    if not MESSAGES.exists():
        return []
    data = json.loads(MESSAGES.read_text(encoding="utf-8"))
    out = []
    for i, m in enumerate(data):
        if m.get("scene") == MAIN_SCENE:
            item = dict(m)
            item["_idx"] = i
            out.append(item)
    return out


def story_index(keyword: str) -> int | None:
    """按关键词找全局下标 (用于定位/校验章节锚点)."""
    for m in main_story():
        if keyword in (m.get("text") or ""):
            return m["_idx"]
    return None


def _clean(text: str) -> str:
    """剥掉剧本标记, 供 DialogueScene 显示 (pages → lines → runs 三层)."""
    parsed = parse(text)
    out: list[str] = []
    for page in parsed["pages"]:
        for line in page:
            out.append("".join(t for t, _ in line))
    return "\n".join(out) if out else ""


@lru_cache(maxsize=1)
def cutscenes() -> dict[int, str]:
    """P 全局下标 → **带演出标签的过场原文** (assets/script/cutscenes.json).

    messages.json 的 P 条目丢失了 `<$CODE:帧号>` 立绘等演出标签; 而
    `assets/script/scenario_full.txt` 是 exe 剧本区的原文 dump, 标签齐全。
    tools.extract_cutscenes 把两者按文本回挂, 这里优先用回挂后的原文播过场。
    """
    p = ROOT / "assets" / "script" / "cutscenes.json"
    if not p.exists():
        return {}
    try:
        return {int(k): v for k, v in
                json.loads(p.read_text(encoding="utf-8")).items()}
    except Exception:
        return {}


def _messages_from_text(raw: str, scene: str, tags=None, cmds=None) -> list[dict]:
    """一段原版剧本 → DialogueScene 可播的 messages.

    逐页一条 (一个对话框 = 一页), 并携带该页的**原版立绘帧号** (`portraits`,
    由 core.script_text.parse 从 `<$CODE:帧号>` 解出; 可多人同框)。
    """
    parsed = parse(raw)
    ports = parsed.get("portraits") or []
    bgms = parsed.get("bgms") or []
    out: list[dict] = []
    for i, page in enumerate(parsed["pages"]):
        lines = ["".join(t for t, _ in line) for line in page]
        body = "\n".join(lines).strip()
        if not body:
            continue
        out.append({"scene": scene, "speaker": parsed.get("speaker"),
                    "text": body, "tags": tags or [], "cmds": cmds or [],
                    "portraits": ports[i] if i < len(ports) else [],
                    "bgm": bgms[i] if i < len(bgms) else None})
    return out


class Beat:
    """一个剧情节点 (主线的一环).

    start/end: 主线剧本流 (scene=P) 的全局下标区间 [start, end]（二选一：也可仅用
               ``script_kw`` 在剧本里按关键词检索，或仅用 ``narrative`` 文本）。
    requires: 需要先完成的 flag; sets: 完成后置位的 flag。
    cost:     触发需要的金钱 (攻略里 300G 请酒等)。
    enter:    进入这些地图 (base 名) 时自动触发本节点 (原版也是走到某处才触发剧情)。
    join:     完成本节点时加入队伍的角色名 (str 或 tuple[str, ...])；剧情战斗中在胜利后入队。
    battle:   剧情战斗配置 {"enemies":[名字...]}（make_enemy 用名）。有则对白后开战，胜利后再置完成/入队。
    narrative:剧本缺锚点时的叙事兜底文本（取自官方攻略，保证流程完整可玩）。
    script_kw:在主线剧本里按关键词检索对白（优先于 narrative 与 [start,end]）。
    ending:   是否为终章（全队通关，进入结局画面）。
    """

    def __init__(self, bid: str, title: str, start: int = -1, end: int = -1,
                 hint: str = "", requires: tuple[str, ...] = (),
                 sets: str | None = None, cost: int = 0,
                 enter: tuple[str, ...] = (), join=None,
                 battle: dict | None = None, narrative: str = "",
                 script_kw: str | None = None, ending: bool = False) -> None:
        self.id = bid
        self.title = title
        self.start = start
        self.end = end
        self.hint = hint
        self.requires = requires
        self.sets = sets
        self.cost = cost
        self.enter = enter
        self.join = join
        self.battle = battle
        self.narrative = narrative
        self.script_kw = script_kw
        self.ending = ending

    def messages(self) -> list[dict]:
        """剧本内容：优先 script_kw 检索，其次 [start,end] 区间，最后 narrative 兜底。"""
        if self.script_kw:
            out = []
            seen: set[str] = set()
            for m in main_story():
                t = m.get("text") or ""
                if self.script_kw not in t:
                    continue
                raw = self._raw_for(m, seen)
                out.extend(_messages_from_text(raw, MAIN_SCENE,
                                               m.get("tags"), m.get("cmds")))
            if out:
                return out
        if self.start >= 0 and self.end >= 0:
            out = []
            seen: set[str] = set()
            for m in main_story():
                if not (self.start <= m["_idx"] <= self.end):
                    continue
                raw = self._raw_for(m, seen)
                out.extend(_messages_from_text(raw, MAIN_SCENE,
                                               m.get("tags"), m.get("cmds")))
            if out:
                return out
        if self.narrative:
            return [{"scene": MAIN_SCENE, "speaker": None, "text": self.narrative,
                     "tags": [], "cmds": []}]
        return []

    @staticmethod
    def _raw_for(m: dict, seen: set[str]) -> str:
        """该剧本条目要播的原文: 优先回挂的过场原文 (带立绘), 否则原条目文本.

        多个 P 条目可能回挂到同一条过场原文 (原版一条原文覆盖多段), 用 seen 去重,
        避免同一段话被播两遍。
        """
        raw = cutscenes().get(m["_idx"])
        if raw is None:
            return m.get("text") or ""
        if raw in seen:
            return ""
        seen.add(raw)
        return raw


# ---------------------------------------------------------------------------
# 完整主线章节链 (据官方攻略 origin/flyingsb/游戏攻略.txt 编排, 忠实原版流程).
#
# 设计:
#   · 顺序即通关顺序; 每个 Beat 的 requires/sets 形成 flag 门控, StoryState.current()
#     永远返回「当前可推进」的第一个节点 —— 这正是原版"按剧情进度解锁"的机制。
#   · enter: 走到这些地图 (base) 自动触发 (原版走到某地才触发)。全部章节的 base 均已
#     「渲染地图读牌匾/连通性」实证确认, 走到即触发 (见下方区域前缀表)。
#   · battle: 剧情战斗 (make_enemy 名); 有则对白后开战, 胜利后才置完成/入队。
#   · join:   完成 (或战胜) 后入队的角色; 剧情战斗中在胜利后入队。
#   · narrative: 剧本缺锚点时的叙事兜底 (取自官方攻略, 保证流程完整可玩); 后期章节
#     待从 exe 剧本流按 script_kw 锚定真实台词后替换。
# ---------------------------------------------------------------------------
# 区域前缀表 (enter 用前缀触发整片区域; base↔中文名 以「光盘版全宝箱数据.xlsx」的
#   「游戏显示中文名」列为准 —— 该列直接来自光盘地图名, 权威; 见 tools/import_chests_xlsx.py):
#   五指村=TFI0 · 小森林=TBB0 · 五指山(五行山)=TOH0
#       (姆指峰 TOH0_00P/食指峰 04P/中指峰 05~06P·09P·19P/无名指峰 13P/小指峰 14P/瀑布后山洞 18P)
#   雅士兰=TAS0 (贫民区 TAS0_00P) · 焚毁雅士兰: 廢墟之村=TAA0 / 雅士兰废墟=TBR0
#   诗郓之森=TSI0 (入口 00P → 诗郓之机器森林 01~03P → 出口 04P)
#   巴喇寺=TBA1 (魔河山区域 TBA0: 大雄殿/住持宿舍/善房/客房) · 名气城=TMY0 · 盖普/盖蒲=TKA0 · 欧明汉=TOM0
#   西州格斗场=TARA (内部迷宫 TARA_02~09P, 崁达乌斯 TARA_10P) · 花果山=THG0~12
#   魔塔=TMO1~18P (另 TMT1~18P 同名) · 真·魔塔=TMA0_xxP · 水濂洞/大殿=THW0
#   阿玛琼纳=TAM0 (空地/飞燕之家 TAM0_10P) · 狄阿曼地=TDI0 (地下迷宫 TDD0) · 阿尔夏=TAL0 · 火山=THS0
#   ※待考: 天龙之泪(神台)=THW 与「水濂洞」同名冲突; 天庭=THG 与「花果山」冲突 —— 二者在 xlsx 里
#     没有独立地图名(可能无宝箱), 暂按原值保留并加注释, 待进一步核实。
#   注: 旧标注 巴喇寺=TDI / 诗郓之森=TDD0 / 西洲格斗场=TTR / 花果山=TMT / 盖蒲=TOM0 / 阿玛琼纳=TSO
#       均被 xlsx 证伪(TDI=狄阿曼地, TDD0=狄阿曼地地下迷宫, TTR=特拉路村, TMT=魔塔, TOM0=欧明汉, TSO=小头洞), 已改正。

BEATS: tuple[Beat, ...] = (
    # ---- 序章 ----
    Beat("intro", "序章 · 禁断之卵",
         hint="美娜公主的梦境引出禁断之卵，玉帝命她下凡寻找孙悟空",
         sets="PROLOGUE",
         narrative="禁断之卵：美娜公主在十六岁生日舞会后发现有关母亲的梦境，潜入禁地见到一只"
                   "飘浮的巨蛋，它发出光芒击倒迪特将军，从天宫落入凡间。玉帝震怒，命美娜下凡寻找"
                   "二百年前被乐神压在五行山下的孙悟空，并解开自身的谜题。"),
    # ---- 第 1 章: 小森林 (起始村; 车坏 → 徒步去五指村) ----
    # 无地点约束 (enter=()): 作为开篇演出, 紧接序章自动播 (小森林本身没有可对话 NPC)
    Beat("c1_forest", "第1章 · 小森林",
         hint="美娜的车在小森林抛锚，徒步前往五指村打听孙悟空",
         requires=("PROLOGUE",), sets="ARRIVED",
         narrative="美娜驱车从高空坠落，车在小森林里损坏，只好徒步出林，前往附近的五指村打听孙悟空的下落。"),
    # ---- 第 2~3 章: 五指村 → 五行山 → 收悟空 (下标锚点见文件头注释) ----
    Beat("c2_arrive", "第2章 五指村 · 抵达", 128, 130,
         hint="在五指村打听孙大王的下落",
         requires=("ARRIVED",),
         enter=("TFI0",)),
    Beat("c2_ask", "第2章 五指村 · 打听姓孙的", 143, 162,
         hint="向村中酒客与长辈打听姓孙的人",
         requires=("ARRIVED",), sets="ASKED",
         enter=("TFI0",)),
    Beat("c2_bomb", "第2章 五指村 · 土制炸弹", 131, 142,
         hint="去道具店买下四个土制炸弹", requires=("ARRIVED",), sets="BOMB",
         enter=("TFI0",)),
    Beat("c2_drunk", "第2章 五指村 · 嗜酒老人", 179, 185,
         hint="找村里年纪最大的嗜酒老人，花 300G 请他喝酒",
         requires=("ASKED",), sets="DRUNK_TOLD", cost=300,
         enter=("TFI0",)),   # 嗜酒老人在五指村 (与标题"第2章 五指村"一致; 剧本 P[179-202] 属五指村线)
    Beat("c2_learn", "第2章 五指村 · 五行山线索", 186, 202,
         hint="听老人说出孙大王与五行山的消息",
         requires=("DRUNK_TOLD",), sets="LEFT_VILLAGE",
         enter=("TFI0",)),   # 五指山线索 (老人所说) 同样在五指村; 雅士兰为第4章地点
    Beat("c3_masked", "第3章 五指山 · 蒙面人现身", 2930, 2950,
         hint="前往五行山，拇指峰遇袭后蒙面人现身相救",
         requires=("LEFT_VILLAGE",), sets="MASKED_DONE", join="蒙面人",
         battle={"enemies": ["乌鸦怪", "乌鸦怪", "黄色怪"]},
         enter=("TOH0",)),
    Beat("c3_wukong", "第3章 五指山 · 孙悟空加入", 2951, 3100,
         hint="中指峰用土制炸弹炸开青石，救出孙悟空",
         requires=("MASKED_DONE", "BOMB"), sets="WUKONG_JOINED", join="孙悟空",
         enter=("TOH0",)),
    Beat("c3_sprites", "第3章 · 云妮与仙杜莉",
         hint="无名指山花丛，精灵云妮、仙杜莉现身并用香吻救出悟空",
         requires=("WUKONG_JOINED",), sets="SPRITES",
         enter=("TOH0",),
         narrative="无名指山花丛中，精灵云妮与仙杜莉现身——她们正是受命封印并监视孙悟空的存在。"
                   "二精灵以香吻救出悟空，给他换上新潮衣衫；悟空欲食言逃走时，美娜吹响禁箍之笛，"
                   "他只好乖乖就范，加入队伍一同寻找禁断之卵。"),
    # ---- 第 4 章: 雅士蘭 → 诗郓之森 ----
    Beat("c4_yashilan", "第4章 · 雅士蘭贫民区",
         hint="小指峰洞穴抵达雅士蘭，打听诗郓与 UFO 的线索",
         requires=("SPRITES",), sets="YASHILAN",
         enter=("TAS0",),
         narrative="从五指山小指峰的瀑布洞穴穿出，抵达雅士蘭村。村中贫民区由废水处理厂改建，"
                   "一名助手告知悟空诗郓的往事；向西找到拄拐老人控诉诗郓之害，又探听到诗郓之森的消息。"
                   "贫民区有人目击 UFO 飞向诗郓之森，循线再出村即可进入森林。"),
    Beat("c4_forest", "第4章 · 诗郓之森",
         hint="穿过三片水晶迷宫，六魔王自破卵中逃脱",
         requires=("YASHILAN",), sets="FOREST",
         enter=("TSI0",),   # 诗郓之森=TSI0 (xlsx 权威: TSI0_00P 入口/01~03P 机器森林/04P 出口; 旧 TDD0 实为狄阿曼地地下迷宫)
         battle={"enemies": ["妖怪", "妖怪", "魔将"]},
         narrative="诗郓之森的木牌警示有进无出。林中躺着天宫战士尸体，禁断之卵已破，"
                   "封印其中的六大魔王重临世间，雅士蘭危在旦夕。穿过三片水晶迷宫（按序集齐水晶开启通道）后方出森林，"
                   "木牌上留下诗郓的留言：去雅士蘭某处寻得超大型合金，交给他的孙子。"),
    # ---- 第 5 章: 巴喇寺的三藏 ----
    Beat("c5_balas", "第5章 · 巴喇寺的三藏",
         hint="魔河山巴喇寺，斗武大会上乐神现身，三藏与乐神加入",
         requires=("FOREST",), sets="BALAS", join=("三藏法师", "乐神杰特"),
         enter=("TBA1",),   # 巴喇寺=TBA1___P (xlsx 权威; 旧 TDI 实为狄阿曼地)
         battle={"enemies": ["妖怪", "乐神杰特", "妖怪"]},
         narrative="魔河山巴喇寺，三藏从恶梦中惊醒，主持提及村庄被焚的异象。百年一度的斗武大会上，"
                   "混入的妖怪称三藏为娘娘腔，三藏怒而痛殴，妖怪现出原形竟是乐神杰特。乐神道出禁断之卵消失、"
                   "美娜下凡寻悟空之事，邀三藏同赴使命——三藏与乐神杰特就此加入。"),
    # ---- 第 6 章: 名气城 + 盖蒲港 + 西洲格斗场 ----
    Beat("c6_mingqi", "第6章 · 名气城与盖蒲港",
         hint="名气城得知海萨与城主之女染病，盖蒲港船长痛失蒂娜",
         requires=("BALAS",), sets="MINGQI",
         enter=("TMY",),   # 名气城 = TMY0___P (渲染地图读牌匾实证: 城市图带围墙, 北门直连塔层;
                          # 原 atlas 的 TGE0___P 资源不存在, TMY0 曾被误标为盖蒲, 已修正. 盖蒲=TOM0___P)
         narrative="南行抵名气城，城墙上士兵提及海萨；城主宅第近年怪物作乱，其女染病。出城西行到西洲唯一港镇盖蒲，"
                   "船长因爱人蒂娜在格斗场失踪而终日买醉，恳请众人寻回。"),
    Beat("c6_arena", "第6章 · 西洲格斗场",
         hint="格斗场击败香茹小子与后台干达休斯，救出蒂娜",
         requires=("MINGQI",), sets="ARENA",
         enter=("TARA",),   # 西洲格斗场=TARA (xlsx 权威: TARA_00P 场地 + TARA_02~09P 内部迷宫; 旧 TTR 实为特拉路村)
         battle={"enemies": ["香茹小子", "香茹小子", "干达休斯"]},
         narrative="格斗场中香茹小子骁勇，乐神功力平平，倒是三藏的「南瓜破」了得。击溃后问出后台是牛魔王副官干达休斯；"
                   "追入迷宫取到钥匙，狭道尽头战退干达休斯，于石牢救出蒂娜——她却不肯离去，无奈打昏带回盖蒲。"),
    # ---- 第 7 章: 寻找超合金 (悟空支线 → 欧明汉/昆仑) ----
    Beat("c7_alloy", "第7章 · 寻找超合金",
         hint="失火后的雅士蘭，悟空一行寻超合金前往欧明汉",
         requires=("ARENA",), sets="ALLOY",
         enter=("TAS0", "TAA0", "TBR0"),   # 失火后的雅士蘭: 廢墟之村 TAA0 + 雅士兰废墟 TBR0 (xlsx 权威); 任一触发
         narrative="失火的雅士蘭，悟空一行被第六魔王重创，决意赶往欧明汉、西洲昆仑寻找诗郓所求的超大型合金。"),
    # ---- 第 8 章: 花果山 / 天龙之泪 ----
    Beat("c8_huaguo", "第8章 · 花果山",
         hint="悟空返乡花果山，重整旧部",
         requires=("ALLOY",), sets="HUAGUO",
         enter=("THG",),   # 花果山=THG0~12 (xlsx 权威; 旧 TMT 实为魔塔楼层)
         narrative="悟空率众回到花果山，重整流派旧部，为后续神之山之战积蓄力量。"),
    Beat("c8_tianlong", "第8章 · 天龙之泪",
         hint="泰泰忧夺得天龙之泪，那印再度现身",
         requires=("HUAGUO",), sets="TIANLONG",
         enter=("THW",),   # ※待考: xlsx 里 THW0=水濂洞/大殿, 与「天龙之泪(神台)」同名冲突, 暂按原值保留
         battle={"enemies": ["那印", "魔兵", "魔兵"]},
         narrative="众人登神台欲取天龙之泪，那印突现抢夺；击退他却让其遁走。循迹至泰泰忧，正遇那印屠戮村民，"
                   "沙地亚亦现身。二人离去后，众人决定先回花果山等待悟空。"),
    # ---- 第 9 章: 母亲的消息 ----
    Beat("c9_mother", "第9章 · 母亲的消息",
         hint="花果山汇合，迪特显露身份，美娜得知生母马太",
         requires=("TIANLONG",), sets="MOTHER",
         enter=("TMT",),
         narrative="花果山两队汇齐，悟空命流派打理山务，迪特将军显露身份。美娜向乐神追问母亲，"
                   "方知自己并非西王母所生，而是人间女子马太之女——神魔大战时马太产下玉皇骨肉，"
                   "却被魔王那印吸入体内。六魔王已赴神之山，欲以三件宝物复活魔皇，美娜决意直面。"),
    # ---- 第 10 章: 阿玛琼纳森林 (破无/捕山/紫河加入) ----
    Beat("c10_amajona", "第10章 · 阿玛琼纳森林",
         hint="飞燕之子破无、捕山与紫河仙女相继加入",
         requires=("MOTHER",), sets="AMAJONA", join=("破无", "捕山", "紫河"),
         enter=("TAM",),   # 阿玛琼纳=TAM0 (xlsx 权威: 村庄 TAM0___P + 空地/飞燕之家 TAM0_10P; 旧 TSO 实为小头洞)
         narrative="渡河至阿玛琼纳森林，魔军正捕捉飞燕，击退后入屋见喜娜——捕山、破无皆为飞燕（青春永驻的千年女神、"
                   "天宫八仙女之一）之子。二人拜见母亲问及生父未果。出村时破无、捕山加入队伍；"
                   "夜宿旅馆，悟空与紫河仙女幽会定情。天明辞别族长，直奔名气城。"),
    # ---- 第 11 章: 名气城北魔塔 ----
    Beat("c11_tower", "第11章 · 名气城北魔塔",
         hint="魔塔幻身分两路：悟空组与乐神组",
         requires=("AMAJONA",), sets="MAGIC_TOWER",
         enter=("TMO",),   # 魔塔=TMO1~18P (xlsx 权威: 魔塔 n 楼; 旧 TMY0_13/14P 实为名气城「城墙内部」)
         battle={"enemies": ["魔塔守卫", "魔塔守卫", "魔塔三姐妹"]},
         narrative="名气城门前城主宅第遇袭，三藏等击退妖怪，悟空等随后汇合。玉皇突现叮嘱美娜莫入魔塔，"
                   "却唤她为唯一骨肉。出城见魔塔双门，众人如法分成两组展开行动。"),
    # ---- 第 12 章: 真正的魔塔 ----
    Beat("c12_real_tower", "第12章 · 真正的魔塔",
         hint="两组交替开启通道，深入魔塔重创魔王合体",
         requires=("MAGIC_TOWER",), sets="REAL_TOWER",
         enter=("TMA0",),   # 真·魔塔=TMA0_xxP (xlsx 权威: 真．魔塔 n 楼)
         battle={"enemies": ["魔王合体", "魔王合体", "魔兵"]},
         narrative="两组在魔塔会合，交替操控星芒阵与开关层层深入。第十层拉杆木桥迷宫汇为一处，"
                   "遭遇魔王合体——一组留战，一组去阻止魔皇复活。"),
    # ---- 终章: 决战玉皇大帝 ----
    Beat("final", "终章 · 决战玉皇大帝",
         hint="祭坛之上，玉皇以神物之泪开启神力，全力击破",
         requires=("REAL_TOWER",), sets="FINAL",
         enter=("THG",),   # 天庭=THG (已证: THG1___P 云海浮岛图; THG8 竖直天河瀑布连 THW0)
         battle={"enemies": ["玉皇大帝", "玉皇大帝", "神力化身"]},
         narrative="悟空等闯入祭坛，竟见玉皇大帝正以神物之泪开启神之力——六魔神逃脱、三神物聚齐、"
                   "魔皇复活，皆是他精心布置的陷阱，只为寻得封印已久的神力。击败获得神力变身的玉皇，"
                   "浩劫终焉。"),
    # ---- 结局 ----
    Beat("ending", "结局 · 和平降临",
         hint="三藏归寺，破无返宫，紫河回城，悟空回花果山，美娜执掌天宫",
         requires=("FINAL",), sets="ENDING", ending=True,
         narrative="三藏重回巴喇寺，续圆满正和尚之愿；破无返狄阿曼地王宫为警卫队长；紫河归冰蔷薇城；"
                   "悟空回花果山，临行仍戴着那顶忘不掉的禁箍头盔，不由大笑。美娜完成使命，将和平带回人间与天庭，"
                   "粉碎玉皇阴谋，执掌天宫，成为第一位女帝。神魔大战的故事，就此落幕。"),
)


class StoryState:
    """剧情状态: 已完成节点 + flag 集合 + 当前队伍."""

    def __init__(self, beats: tuple[Beat, ...] = BEATS, save=None) -> None:
        self.beats = beats
        self.done: set[str] = set()
        self.flags: set[str] = set()
        # 当前队伍: 从存档推导 (已激活槽位), 无存档则新游戏默认 (美娜)
        self.party: list[str] = self._derive_party(save)

    @staticmethod
    def _derive_party(save) -> list[str]:
        from core import party as party_mod
        return party_mod.active_party(save)

    # ---- 查询 ----
    def _ready(self, b: Beat) -> bool:
        return b.id not in self.done and all(f in self.flags for f in b.requires)

    def current(self) -> Beat | None:
        """下一个可推进的节点 (顺序靠前的优先)."""
        for b in self.beats:
            if self._ready(b):
                return b
        return None

    def beat_for_location(self, base: str) -> Beat | None:
        """走到 base 这张地图时, 应自动触发的「当前可推进」节点 (若有).

        只返回 ready 且与 base 关联的节点; flags 门控保证按攻略顺序推进。
        没有对应地图的节点 (或还没轮到) 返回 None —— 此时仍可手动按 G 推进。

        enter 支持"区域前缀" (如 "TOH0" 匹配 TOH0_00P..TOH0_19P、"TDI" 匹配整个巴喇寺
        区域), 一整个区域只要走到任意一张图就触发, 不必逐个枚举。前缀映射依据
        scenes/world_map/atlas.py 的 LOCATIONS (游戏世界地图权威地名→base)。
        """
        for b in self.beats:
            if self._enter_matches(base, b.enter) and self._ready(b):
                return b
        return None

    @staticmethod
    def _enter_matches(base: str, tokens: tuple[str, ...]) -> bool:
        for t in tokens:
            if t == base or base.startswith(t):
                return True
        return False

    def remaining(self) -> int:
        return sum(1 for b in self.beats if b.id not in self.done)

    def messages_for(self, b: Beat) -> list[dict]:
        return b.messages()

    # ---- 推进 ----
    def _join_names(self, b: Beat) -> list[str]:
        if b.join is None:
            return []
        return list(b.join) if isinstance(b.join, (tuple, list)) else [b.join]

    def complete(self, b: Beat, save=None) -> bool:
        """即时完成 (对白型节点): 扣花费、置 flag、入队、标记完成。"""
        if not self.pre_complete(b, save):
            return False
        self.mark_done(b, save)
        return True

    def pre_complete(self, b: Beat, save=None) -> bool:
        """前置: 仅扣花费 (不置 flag / 不标记完成 / 不入队).

        剧情战斗节点在胜利后才置 flag, 避免"战斗失败却已解锁后续"导致跳过战斗。
        """
        if b.cost and save is not None and getattr(save, "money", 0) < b.cost:
            return False
        if b.cost and save is not None:
            save.money -= b.cost
        return True

    def mark_done(self, b: Beat, save=None) -> None:
        """标记完成 + 置 flag + 入队 (对白结束 / 剧情战斗胜利后调用)."""
        self.done.add(b.id)
        if b.sets:
            self.flags.add(b.sets)
        for name in self._join_names(b):
            from core import party as party_mod
            if party_mod.activate_character(save, name):
                self.party.append(name)

    # ---- 终局 ----
    def is_complete(self) -> bool:
        """所有主线节点完成 (抵达结局)."""
        return all(b.id in self.done for b in self.beats)

    def ending_beat(self) -> Beat | None:
        for b in self.beats:
            if b.ending and b.id in self.done:
                return b
        return None

    def ending_text(self) -> str:
        b = self.ending_beat()
        if b is not None:
            return b.narrative or b.title
        return "通关！"

    def progress_text(self) -> str:
        if self.is_complete():
            return "★ 主线全通 · 已通关"
        cur = self.current()
        if cur is None:
            return "主线推进完毕"
        total = len(self.beats)
        done = sum(1 for b in self.beats if b.id in self.done)
        return f"[{done}/{total}] {cur.title}｜{cur.hint}" + (f"（{cur.cost}G）" if cur.cost else "")

    def party_text(self) -> str:
        return "、".join(self.party) if self.party else "（空）"


# ---------------------------------------------------------------------------
# Scene Director: 主线流程的"导演"层
#
# 对外只暴露高层决策, 屏蔽 StoryState 的内部细节, 供 WorldMapScene 调用:
#   · beat_for_location(base)  —— 走到某图该触发哪个节点
#   · current()               —— 当前该推进的节点 (G 键)
#   · ready(beat)             —— 是否可推进 (flag 门控)
#   · is_complete()           —— 是否已通关
#   · plan(beat, save)        —— 给出一个节点的"演出计划" (对白 / 战斗 / 结局)
#   · apply(beat, save, won)  —— 节点结算 (扣费->置flag; 战斗胜利后才标记完成+入队)
# ---------------------------------------------------------------------------
class Director:
    """主线流程导演: 把剧情数据 (BEATS/StoryState) 编排成可执行的演出序列."""

    def __init__(self, save=None) -> None:
        self.state = StoryState(save=save)

    # ---- 查询 ----
    def beat_for_location(self, base: str) -> Beat | None:
        return self.state.beat_for_location(base)

    def current(self) -> Beat | None:
        return self.state.current()

    def ready(self, b: Beat) -> bool:
        return self.state._ready(b)

    def is_complete(self) -> bool:
        return self.state.is_complete()

    def ending_text(self) -> str:
        return self.state.ending_text()

    # ---- 兼容 WorldMapScene 的便捷委托 ----
    @property
    def party(self) -> list[str]:
        return self.state.party

    def messages_for(self, beat: Beat) -> list[dict]:
        return self.state.messages_for(beat)

    def progress_text(self) -> str:
        return self.state.progress_text()

    def party_text(self) -> str:
        return self.state.party_text()

    # ---- 演出计划 ----
    def plan(self, beat: Beat, save=None) -> dict:
        """给出一个节点的演出计划.

        返回 {"messages": [...], "battle": dict|None, "ending": bool,
              "cost": int, "affordable": bool}。"""
        msgs = self.state.messages_for(beat)
        affordable = True
        if beat.cost and save is not None and getattr(save, "money", 0) < beat.cost:
            affordable = False
        return {
            "messages": msgs,
            "battle": beat.battle,
            "ending": beat.ending,
            "cost": beat.cost,
            "affordable": affordable,
        }

    # ---- 结算 ----
    def apply_presave(self, beat: Beat, save=None) -> bool:
        """节点前置结算: 扣费 + 置 flag。返回 False=钱不够。战斗节点此时不标记完成。"""
        return self.state.pre_complete(beat, save)

    def apply_postbattle(self, beat: Beat, save=None) -> None:
        """战斗胜利 / 纯对白节点结束后: 标记完成 + 入队。"""
        self.state.mark_done(beat, save)
