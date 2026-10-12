"""手工编排的 NPC 与商店表.

背景: 原版 `.mfo` 里 pcpos/jmp **只是"门/出入口"**(jmp.m = 目标地图 id), 并没有独立
的 NPC 实体 —— 城镇村民是**烘焙进地图美术**的装饰, 无法交互; 因此 remake 里"屋里没人、
店里没老板". 为让重制版有可对话的人物与商店, 这里人工编排:

  · `SHOPS_RAW`: 城镇店铺 (base → (店名, 类别)), 由 xlsx「游戏显示中文名」整理;
    每个店铺地图会**自动生成一个店老板 NPC**, 面对面按空格即开店 (见 scenes/shop.py)。
  · `NPCs`: 额外手工 NPC (村口/要地人物), 每条 {name, lines[]};
    位置自动放在"地图中心附近可走的非门格"(见 scenes/world_map/npcs.py)。
  · 室内地图 (ROOM/家/宿舍/宅邸…) 自动补一个"居民"NPC, 避免进屋空无一人。
"""

from __future__ import annotations

# base → (店名, 类别)  类别: ITEM 道具 / WEP 武器 / ARMOR 防具 / ACC 饰品 / INN 旅馆 / PUB 酒馆
SHOPS_RAW: dict[str, tuple[str, str]] = {
    # 五指村 (南洲)
    "TFI0_05P": ("五指村客栈", "INN"),
    # 雅士兰
    "TAS0_08P": ("道具店", "ITEM"),
    "TAS0_09P": ("武器店", "WEP"),
    "TAS0_04P": ("首饰店", "ACC"),
    "TAS0_01P": ("旅馆", "INN"),
    "TAS0_02P": ("酒馆", "PUB"),
    # 阿尔夏 (北洲港口)
    "TAL0_04P": ("道具店", "ITEM"),
    "TAL0_07P": ("武器店", "WEP"),
    "TAL0_03P": ("防具店", "ARMOR"),
    "TAL0_06P": ("旅馆", "INN"),
    "TAL0_05P": ("客栈", "INN"),
    # 阿玛琼纳
    "TAM0_08P": ("道具店", "ITEM"),
    "TAM0_01P": ("武器店", "WEP"),
    "TAM0_07P": ("饰品店", "ACC"),
    "TAM0_09P": ("客栈", "INN"),
    # 狄阿曼地
    "TDI0_10P": ("道具店", "ITEM"),
    "TDI0_11P": ("防具店", "ARMOR"),
    "TDI0_03P": ("旅馆", "INN"),
    # 名气城
    "TMY0_05P": ("武器防具店", "WEP"),
    "TMY0_01P": ("饰品店", "ACC"),
    "TMY0_06P": ("旅馆", "INN"),
    # 欧明汉 / 特拉路村
    "TOM0_01P": ("饰品店", "ACC"),
    "TOM0_02P": ("旅馆", "INN"),
    "TOM0_07P": ("客栈", "INN"),
    "TTR0_01P": ("饰品店", "ACC"),
    "TTR0_03P": ("客栈", "INN"),
    # 盖普 / 乌来城 / 泰泰忧 / 老大村
    "TKA0_02P": ("武器防具店", "WEP"),
    "TKA0_08P": ("旅馆", "INN"),
    "TOR0_04P": ("武器饰品店", "WEP"),
    "TOR0_00P": ("客栈", "INN"),
    "TTE0_03P": ("武器店", "WEP"),
    "TTE0_04P": ("防具店", "ARMOR"),
    "TTE0_00P": ("酒店旅馆", "INN"),
    "TTS0_03P": ("防具店", "ARMOR"),
    "TTS0_07P": ("客栈", "INN"),
    "TTS0_00P": ("饰品店", "ACC"),
    "THW0_07P": ("武器防具店", "WEP"),
}


# 额外手工 NPC: base -> [{name, lines}]
NPCs: dict[str, list[dict]] = {
    "TBB0___P": [
        {"name": "樵夫", "lines": ["姑娘, 你的车怕是坏啦。",
                               "这林子叫小森林, 南边出去就是五指村。",
                               "先去村里打听打听, 兴许有人会修。"]},
    ],
    "TFI0___P": [
        {"name": "村口老人", "lines": [
            "听说 200 年前, 那只大闹天宫的猴子被镇在五行山下。",
            "要越过五行山, 先得备好干粮和土制炸弹。",
            "酒馆里那位老伯年纪最大, 兴许知道些什么。",
            "村中央还立着一尊猴子神像, 是 200 年前就有的。"]},
        {"name": "村姑", "lines": ["往北出村, 越过那座像手掌的山, 就能到雅士兰了。",
                                 "路上妖怪多, 可要当心。",
                                 "你要是累了, 村东头有间客栈能歇脚。"]},
        {"name": "杂货郎", "lines": ["道具店的土制炸弹? 那玩意儿可不好惹。",
                                  "南边那洲有两个港口, 过了山再说吧。"]},
    ],
    "TOH0_00P": [
        {"name": "猎户", "lines": ["这一带妖怪多, 走路当心。",
                                "前面拇指峰常有落石, 别靠太近。",
                                "听说山里压着一只猴子, 谁也没见过。"]},
    ],
    "TAS0___P": [
        {"name": "贫民", "lines": ["咱们这儿是废水厂改的贫民区, 跟难民营一样。",
                                 "前些日子有人瞧见 UFO 往西边的诗郓之森去了。",
                                 "村里武器店有把光剑, 可惜没人买得起。"]},
    ],
    "TSI0_00P": [
        {"name": "徘徊的旅人", "lines": ["这林子有股血腥味……我怎么都走不出去。", "听说里面有一枚水晶, 可开启五行之阵。"]},
    ],
    "TBA1___P": [
        {"name": "小和尚", "lines": ["施主是来参加斗武大会的吗?", "方丈说, 这几日村里将有异象。"]},
    ],
    "TMY0___P": [
        {"name": "守城士兵", "lines": ["名气城近年不太平, 城主宅第常有妖怪作乱。", "往西出城, 便是去盖普港的路。"]},
    ],
    "TKA0___P": [
        {"name": "水手", "lines": ["盖普是西洲唯一的港。", "船长的情人蒂娜在格斗场失踪后, 他就一直买醉。"]},
    ],
    "TOM0___P": [
        {"name": "渔民", "lines": ["欧明汉的船都停在码头。", "听说西边纪湄山的桥断了, 只能绕废矿走。"]},
    ],
    "TAL0___P": [
        {"name": "港口工人", "lines": ["这儿是北洲唯一的港口阿尔夏。", "人族与机器族在这儿和平共处。"]},
    ],
    "TAM0___P": [
        {"name": "村民", "lines": ["阿玛琼纳的魔军最近常来抓飞燕。", "飞燕之子破无、捕山, 你可曾见过?"]},
    ],
    "TDI0___P": [
        {"name": "士兵", "lines": ["狄阿曼地城的国王寝宫, 闲人免进。", "地下迷宫可不好走, 别乱闯。"]},
    ],
    "TTR0___P": [
        {"name": "村民", "lines": ["特拉路村道窄, 往西就是名气城。"]},
    ],
    "TTE0___P": [
        {"name": "村民", "lines": ["泰泰忧近来被那印搅得不得安宁。"]},
    ],
    "TTS0___P": [
        {"name": "村民", "lines": ["老大村靠着港口做买卖, 日子还过得去。"]},
    ],
    "TOR0___P": [
        {"name": "市民", "lines": ["乌来城是东洲的大城, 城墙里头别乱走。"]},
    ],
    "THG0___P": [
        {"name": "小猴", "lines": ["大王回来啦! 大王回来啦!", "花果山的水濂洞, 就藏在瀑布后头。"]},
    ],
    "THS0___P": [
        {"name": "矿工", "lines": ["火山里头热, 装备不济别下去。"]},
    ],
    "TST0___P": [
        {"name": "村民", "lines": ["石油村靠山吃山, 石油山的洞口在村北。"]},
    ],
    "TAA0___P": [
        {"name": "难民", "lines": ["雅士兰一夜之间就烧成了这样……", "诗郓先生留下的东西, 好像埋在下水道里。"]},
    ],
    "TIV0_00P": [
        {"name": "旅人", "lines": ["冰谷寒气重, 多备些御寒之物。"]},
    ],
}

# 室内地图名关键字 → 自动补一个"居民"NPC (避免进屋没人)
_INTERIOR_MARKS = ("ROOM", "ＲＯＯＭ", "家", "宿舍", "宅邸", "客房", "善房", "大殿", "寢室")
_RESIDENT_LINES = ["这儿是我家, 随便坐坐。", "外面世道乱, 妖怪越来越多咯。", "你要出远门? 路上小心。"]


def shop_for(base: str) -> tuple[str, str] | None:
    return SHOPS_RAW.get(base)


# 角色名 → 原版地图角色精灵 (ps_ 图集, 6×4: 行=朝向 列=走路帧; 见 core.npc_sprites / loaders)
SPRITE_BY_NAME: dict[str, str] = {
    "樵夫": "ps_CMAN000",
    "村口老人": "ps_COLD000",
    "村姑": "ps_CWOM000",
    "猎户": "ps_CMAN000",
    "贫民": "ps_COLD000",
    "徘徊的旅人": "ps_COLD000",
    "小和尚": "ps_CBASI00",
    "守城士兵": "ps_CSOLD00",
    "水手": "ps_CCAPT00",
    "渔民": "ps_CMAN000",
    "港口工人": "ps_CSOHA00",
    "村民": "ps_CMAN000",
    "士兵": "ps_CSOLD00",
    "市民": "ps_CMAN000",
    "小猴": "ps_CMAN000",
    "矿工": "ps_CMAN000",
    "难民": "ps_CWOM000",
    "旅人": "ps_COLD000",
}
SHOPKEEPER_SPRITE = "ps_CMER00"
RESIDENT_SPRITES = ("ps_CMAN000", "ps_CWOM000", "ps_COLD000")


def resident_sprite(base: str) -> str:
    """室内"居民"按地图名稳定选一个外形 (免得每间屋子都同一个人)."""
    return RESIDENT_SPRITES[sum(map(ord, base)) % len(RESIDENT_SPRITES)]


def npcs_for(base: str) -> list[dict]:
    out = []
    for n in NPCs.get(base, ()):
        d = dict(n)
        d.setdefault("sprite", SPRITE_BY_NAME.get(d.get("name", ""), resident_sprite(base)))
        out.append(d)
    return out


def resident_lines() -> list[str]:
    return list(_RESIDENT_LINES)


def is_interior(name: str) -> bool:
    return bool(name) and any(m in name for m in _INTERIOR_MARKS)
