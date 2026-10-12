# 幻想西游记 重制版

用 Python + Pygame 重制 1990 年代的 Windows 战棋 RPG《幻想西游记》。

战斗系统、技能演出、音效时序等均通过对原版 `FlyingSB.exe` 的逆向工程逐帧还原
（动画字节码、伤害结算时序、AOE 范围表、音效映射等都取自 exe 真值）。

> **版权说明**：本仓库**只包含重制代码，不含任何原版游戏资源**（图像 / 音频 / 地图 /
> 存档）。运行游戏需要你自备原版游戏拷贝，资源由脚本从你自己的拷贝中提取。
> 原游戏版权归原开发商所有。

## 环境要求

- Python 3.12+（开发环境 3.14）
- 原版《幻想西游记》游戏目录（含 `ase_fm.dll`、`ase_ps.dll`、`mapset.dll`、
  `pcxset.dll`、`se_event.dll`、`wav_eft.dll` 及 `Data/` BGM 目录）

## 跑起来

### 1. 安装依赖

```sh
python3 -m venv venv
venv/bin/pip install -r requirements.txt
```

### 2. 放置原版游戏

默认路径为仓库**上一级**的 `origin/flyingsb`：

```
你的工作目录/
├── origin/flyingsb/    # 原版游戏 (自备)
└── rewrite/            # 本仓库
```

放在别处也行，用环境变量指定：

```sh
export FLYINGSB_ORIGIN=/path/to/flyingsb
```

### 3. 提取资源

从原版 6 个 DLL 里把 sprite / 地图 / UI / 音效批量 dump 到 `assets/`，
并自动把 BGM（`assets/audio`）符号链接到原版 `Data/` 目录（无符号链接权限时
自动回退为复制 `.wav`）：

```sh
venv/bin/python -m tools.extract_dll
```

### 4. 渲染地图预览（可选）

`extract_dll` 已把原版地图原样 dump 到 `assets/maps/`：
`.map`（二进制网格）/ `.mfo`（文本元数据）/ `.pcx`（图集）。
再用 `tools.extract_maps` 解析并渲染成 PNG：

```sh
venv/bin/python -m tools.extract_maps
```

产物：`assets/maps_preview/<地图>.png`（共 487 张）+ `_index.json`
（地图名 / 尺寸 / 瓦片集 / pcpos）。地图格式说明见 `tools/extract_maps.py` 顶部注释。

**游戏内已直接使用真实地图**：世界地图场景默认加载 `T_LOC0_P`（东海之滨），
战斗 / 竞技场场景默认加载 `TARA_00P`，地形与障碍都取自原版地图
（`core/real_map.py`）。缺资源时自动回退到占位地形。

### 5. 提取剧本（可选）

从 `FlyingSB.exe` 里把原版剧情剧本（Big5 明文 + 标记语言 `<msg_id=>`/`<$SONA>`/`<&item329>` 等）
导出成可读文本与统计：

```sh
venv/bin/python -m tools.extract_script
```

产物：`assets/script/scenario_full.txt`（剧本全文）/ `stats.json`（规模 + 标签直方图）
/ `messages.json`（按 msg_id 分组）。

### 6. 解析地图事件与存档 flags（可选）

```sh
venv/bin/python -m tools.extract_events           # .mfo → assets/maps_events.json
venv/bin/python -m tools.inspect_save <save> ["<save2>"]
```

`.mfo` = 地图事件表（`pcpos` 站位 / `jmp` 传送 / `anime` / 战斗配置 `enemytype`/`partylevel`…），
注释与地名是原版**韩文 (EUC-KR)**。
**位置 ID 系统**：`mapname` 为数字时 = 该地图的位置 ID（48..487），`jmp` 的 `m` 字段 = 目标位置 ID；
据此生成 `assets/map_graph.json`（430 个位置、1032 条跳转边，92% 双向）。
**传送点**：`pcpos[i].link` = `jmp` 下标 → 站在 `pcpos[i]` 的 (x,y) 上传送到 `jmp[link].m`。
`tools/extract_locations.py` → `assets/location_map.json`（429 数字ID位置 + 40 命名位置 + 1136 传送点），
由 `core/world_graph.py` 读取；世界地图场景已接入：走到传送点即切图
（**F1** 跳枢纽 348 / **F2** 回世界地图 / **T** 剧本预览）。
**小 ID 空间 0..47**（世界地图/城镇）：0–9 `T_LOC0..9`、10–21 아스람(雅士蘭)、
22–29 다섯손가락마을(五指村)、30–47 오행산(五行山)。
剧情试水：`scenes/dialogue.py` 播放原版对白（Enter/→ 翻页，← 上一条，ESC 返回），
框内同时显示剧本指令（音乐/立绘/道具，道具名走 `core.items`）。
城镇功能：`scenes/shop.py` —— 进入 아스람 店铺地图自动开店（道具/武器/首饰店列出分类道具；
旅馆住宿恢复全队，直接改存档 HP/MP）。**价格用原版真实值**（见下面 §7 的 `extract_item_table`）。
存档 flags 位图在 `0xC04..0x1C00`，`state[2]` 是剧情进度；`inspect_save` 可对比两档看哪些位变化。

**存档结构（已解出的部分）**：
- `0x00` 标记 / `0x04` 地名(Big5) / `0x20` 5×DWORD state / **`0x44..0xC03` = 16 个角色块**（每块 `0xBC`）/
  `0xBF4` 金钱 / `0xC04..` 起为标志/状态区。
- **角色块顺序 = exe 角色定义表的记录号**（已用「装备 + 技能」双向实证）：
  slot1 孙悟空 / slot3 美娜 / slot4 三藏 / slot5 八戒 / slot6 沙悟净 / slot8 蒙面人 /
  slot9 乐神 / slot10 破无 / slot11 捕山 / slot12 紫河（0/2 是悟空备用定义、7=迪特、13-15 是紫河备用）。
  `core/character.py` 的 `CHARACTER_NAMES/PLAYABLE_SLOTS/TOTAL_SLOTS(16)` 已按此修正。
- **角色块 `extra[3..12]` = 已学技能列表**（10 槽，`-1` 空）；`load_save` 会读进 `Character.skills`，
  战斗优先用它（载入原版存档即得原版技能集）。
- 原版**运行时库存模型**：335 个物品槽 + 3 个并行 u32 数组（起始记录下标 `0x7C8B38` /
  数量 `0x7C9080` / 第三字段 `0x7D4B60`）+ 28 字节物品实例堆 `0x7D509C` + 记录总数 `0x7BAD30`；
  取出/删除会 memmove 实例并回改所有起始下标。**该模型在存档里的落盘编码尚未定案**
  （`0xC04..` 区按 u32 看是 0..6 的 flags/状态表，物品 id 未以明文出现）——待更多证据。

### 7. 提取对白分派表 / 物品价格 / 地图角色（可选）

```sh
venv/bin/python -m tools.extract_script_table   # 反汇编 exe → assets/script/script_table.json
venv/bin/python -m tools.extract_item_table     # 读 exe 物品表 → assets/items_table.json
venv/bin/python -m tools.extract_map_npcs       # 解析 .mfo    → assets/map_npcs.json
venv/bin/python -m tools.extract_characters     # 读 exe 角色表/成长表/经验表 → assets/characters_table.json
venv/bin/python -m tools.extract_enemies        # 读 exe 敌人表 → assets/enemy_table.json
venv/bin/python -m tools.extract_skill_learn    # 读 exe 技能学习表 → assets/skill_learn.json
venv/bin/python -m tools.extract_enemy_actions  # 读 exe 敌方行动表 → assets/enemy_actions.json
```

- **剧情分派表**：原版用一张 669 项跳转表（VA `0x467006`）把「位置 / 角色 ID」映射到剧本分支；
  `PlayScript` 入口 `0x45b7d0`，对白播放函数 `0x45b173`，当前剧本 ID 全局 `0x7d75b8`。
  产出 **669 条**（649 条对白 + 20 条 default）。逆向细节见 `tools/extract_script_table.py` 顶部注释。
- **物品价格 / 属性 / 效果 / 描述**：物品记录表 VA `0x6954D4`、步长 **76** 字节。
  字段：`+0x04` 卖价 / `+0x08` 买价（`-1` = 不可交易；商店用
  `玩家金钱(0x867e7c) >= rec[+0x08]` 判断能否买）/ `+0x18` 装备槽掩码 /
  `+0x1c` 效果类型（5 装备 / 6 属性药丸 / 10 状态 / 14 HP·MP 回复）/ `+0x20..+0x34`
  = **力量/智慧/敏捷/攻击/防御/幸运** 加成（归属由装备应用函数 `0x4334b0..0x4335a8`
  逐条证实）/ `+0x44` 描述。
  与原版名字逐项校验（**354/356 一致**，余 2 项仅尾字符差异）。
  产物 `assets/items_table.json` 由 `core/items.py` 读取：`item_combat_bonus`（真实攻防/五维）、
  `item_effect`（真实回复量，全回复记 9999）、`item_desc`（原版描述）；
  背包界面已显示描述 + 属性；商店已换成真实价格；旅馆/船票/格斗赛门票取剧本真实值。
- **角色真实数据（新游戏初始值 / 成长 / 经验）**：角色定义表 VA `0x689D64`、步长 `0xBC`、16 条
  （与存档角色块同布局），给出每个角色 **Lv1 初始 HP/MP/五维 + 初始装备**（如 美娜 HP25 身65 手129、
  孙悟空 HP30 手121）；**裸装基础攻/防/运** 在 `Unknow_5/6/7`。
  成长表：`0x64422C`(记录→成长组) → `0x64412C`(组→HP/MP/攻/防 4 行) → `0x6429B8`(每行 100 级)；
  经验表 `0x642670`（Lv1→2 需 100、Lv2→3 需 220 …）。
  产物 `assets/characters_table.json` 由 `core/character_data.py` 读取：
  新游戏初始数值（`core/party.py` / `new_game_save`）与**升级结算**（`core/battle/tactics.py`，
  真实经验表 + 成长表，取代旧的随机成长）均已换成真值。技能学习等级**未定位到数据表**（当前仍是满池）。
- **敌人真实数据**：敌人表 VA `0x68BFF0`、步长 `0x7C`、约 208 条（索引 = `.mfo` 的 `enemytype`）。
  已证实字段：名称 / **HP**(+0x0C) / **攻击**(+0x2C，`攻击 - 角色防御` 即伤害) / 经验 / 金钱 /
  AI 行动组 / 阵型 / 技能 / 掉落；防御/敏捷为推断值（JSON 里保留原始字段）。
  产物 `assets/enemy_table.json`；`core/battle/setup.make_enemy_by_type` 用它建敌，
  野外遇敌改为按地图 `.mfo` 的 `enemytype` 池 + 真实数值生成（缺数据回退占位模板）。
- **技能学习等级（角色→等级→技能）**：学习表 VA `0x64216C`，每个角色记录 `0x50` 字节
  = **10 组 `[等级, 技能池下标]`**；访问函数 `0x49CCF2(charIdx, newLevel)` 只在该等级
  恰好命中时授技。技能 = `core.skills.CHARACTER_SKILL_POOL[角色][下标]`；
  **未出现在表里的池下标 = 开局就会**（如美娜开局带 小回复/召唤精灵）。
  产物 `assets/skill_learn.json` → `core.character_data.learned_skills(name, level)`；
  战斗单位的 `known_skills` 与升级后刷新都按此表（不再满池）。
  **沙悟净**学习表为空 —— 他的技能是**剧情里向忍者 NPC 学**的（`core.character_data.STORY_LEARNED`）。
- **技能类别 / 回血量**：`core/skills.py` 的 `skill_kind()` 把 66 个技能分成
  heal(HP恢复) / revive(复活) / cure(解异常) / buff(增益) / drain(吸取) / attack，
  `targets_allies()` 指出「打友军」的技能（AI/选目标用）；回血量取自原版**描述文本**
  （小回复100 / 大恢复500 / 恢复乐章200 / 回复优卡500 / 超回复=全满…见 `HEAL_AMOUNT`）。
  `core.skill_seq.is_heal_skill` 已扩到全部治疗+复活技（此前只认生命之火）。
- **敌方行动表 / 战斗 AI**：行动表 VA `0x692F54`、步长 `0x20`、248 条（名称/标志
  `0x800000`=远程/参数/执行函数指针）；**单位 `+0xE8` = 当前行动 id**（`0x4CFF33` 处读取）。
  敌人记录 `+0x18` = **AI 行为组**（1..50），摆阵时写入单位 `+0x86ADBC`
  （`0x49FA5B`；部分敌人再 `+3` 随机化）。行为组在 `0x4AA8DE` 处作为**概率阈值的加值**
  参与判定（`add ecx,[unit+0x86ADBC]; cmp edx,ecx`），并非独立状态机。
  产物 `assets/enemy_actions.json`。remake 的敌人 AI（`core/battle/ai.py`）改为
  **真实数据驱动**：用敌人表里的技能列表 + exe 技能 pattern（`core.skill_patterns`）
  选「命中玩家最多」的技能（按技能真实射程校验、跳过治疗/复活/增益类），
  否则走向最近玩家普攻；「放技能 vs 普攻」的倾向按行为组单调映射（`ai.skill_chance`）。
  **注**：原版 AI 的完整决策状态机尚未逐条复刻（行为组的具体语义只到"参与概率阈值"这一层）。
- **地图角色（FC 放置）**：`.mfo` 的 `pcpos` + `jmp` 给出每张地图每个角色的
  (x, y, 朝向, 精灵帧, 位置 ID)，共 **1087 个**（1014 个能解出真实对白）。
  **该 ID 同时是「传送目标位置 ID」与「script_table 索引」——原版位置表与剧本表共用同一套
  ID 空间**，所以「走到某处 → 去位置 m → 播放 script[m]」是一条统一链路。

**世界地图已接入地图角色**（`core/map_npcs.py` + `scenes/world_map/npcs.py`）：
地图上的村民 / 守卫 / 神像会按原版坐标显示，**走上去即播放该位置的原版对白**
（内容取自 `script_table.json`，用 `core/script_text.py` 解析标记）。
HUD 顶部显示该地图「有对白角色数 / 总角色数」，玩家面前有可交谈角色时底部会出现台词预告。
例：阿尔夏 `TAL0___P` 有 14 个角色（13 个有对白）；五指村雕像剧情是 script 18~21。

**NPC 用的是原版真精灵**（`core/npc_sprites.py`）：角色表在 exe `0x1b01a9`（133 条）+
`0x1bd9c9`（20 条），每条 416 字节存一个 `ps_*.PCX` 图集名；游戏按表顺序把它们拼成
一个**虚拟大图集**，帧号是全局的（`.mfo jmp` 的 `c0/c1/o0/o1` 与剧本 `<SON:NNNN>` 都是这个空间）。
每帧 64×96，**行 = 朝向（0 背 / 1 正 / 2 左 / 3 右），列 = 动画帧**。
`jmp.c0` 缺省的地图（如阿尔夏，全为 -1）：**原版把角色/门的图形烘焙进了地图瓦片层**，
不再另画精灵。实证：每个 `pcpos` 落点的地图可视瓦片都是稀有瓦片（整图只在这些位置各出现一次），
且 **瓦片号 == `jmp.c0 + 20`**（阿尔夏 220/222、雅士兰 312/352/392 ↔ c0 292/332/372、五指村 69 ↔ 49）。
因此 remake 只对 `jmp.c0 >= 0` 的条目（全 1087 里仅 27 条）额外叠 FC 精灵，
其余**依赖地图美术本身**（不再画程序占位小人，避免叠出两个小人）；
`.mfo` 的 `anime` 段是**背景动态瓦片**（注释 `//물결`/`//강 애니` = 波浪/河水），与 NPC 精灵无关。

### 8. 启动

```sh
venv/bin/python main.py
```

标题菜单：**竞技场**（选人 → 沙盒战斗，推荐入口）/ **剧情回放** / 新游戏 / 读取存档 / 退出。

**剧情回放**（`scenes/script_viewer.py`）：浏览原版 669 条剧本分派表，左侧列表 + 右侧对白预览，
`Enter` 进入全屏回放。会自动剥离剧本标记并渲染说话人 / 强调 / 道具名（走 `core.items`），
`T` 可切换简体（默认，t2s）/ 繁体原文。

**主线剧情推进**（`core/story.py` + `core.director.Director`，B）：`assets/script/messages.json`
里 `scene == "P"` 的条目按数组顺序就是原版主线剧本（段落内部连续）。**完整章节链已补成「序章·禁断之卵 →
第2章五指村 → 第3章五行山(收蒙面人/孙悟空) → 第4章雅士蘭/诗郓之森 → 第5章巴喇寺(收三藏/乐神) →
第6章名气城/盖蒲/格斗场 → 第7章超合金 → 第8章花果山/天龙之泪 → 第9章母亲消息 →
第10章阿玛琼纳森林(收破无/捕山/紫河) → 第11章魔塔 → 第12章真·魔塔 → 终章决战玉皇大帝 → 结局」**，
在世界地图按 **`G`** 推进；HUD 显示 `[已完成/总节点] 当前章节｜目标`，有花费的节点（如请嗜酒老人喝酒
**300G**）会从存档扣钱。`Director` 是主线流程的"导演"层：把 `BEATS`/`StoryState` 编排成可执行的演出序列
（对白 → 剧情战斗 → 置进度/入队/结局），flag 门控保证按官方攻略 `origin/flyingsb/游戏攻略.txt` 顺序推进。
关键剧情战斗（蒙面人救美娜、巴喇寺斗武、西洲格斗场、魔塔、决战玉皇等）已挂 `battle` 配置：对白后开战，
**胜利**才标记完成并入队（失败可重试，不会跳过战斗解锁后续）。`Beat.enter` 支持**区域前缀**匹配
（如 `"TOH0"` 命中五行山全部 18 张图、`"TDI"` 命中整个巴喇寺区域），走到该区域任意一张图即自动触发——
前缀映射取自 `scenes/world_map/atlas.py` 的 `LOCATIONS`（游戏世界地图权威地名→base）：五指村=TFI0、雅士蘭=TAS0、
五指山=TOH0、巴喇寺=TDI、盖蒲=TMY、花果山=TMT、狄阿曼地=TMA、乌来城=TMO、阿尔夏=TAL 等。
诗郓之森/天龙之泪/阿玛琼纳森林/天庭等无 exe 提取地名的后期区域用世界图连通性**推断**前缀（标注 `INFERRED`，保留 G 兜底）。
**已知提取缺口**：`atlas.py` 中名气城=TGE0___P，但该 base 未出现在已提取的 `location_map.json`（为孤立桩图），
故第 6 章名气城、第 11/12 章魔塔（enter=`TGE`）暂靠 `G` 推进，待补完名气城 `.mfo` 后自动走到触发。
剧情对白优先用 exe 原版剧本（按 `script_kw` 检索），缺锚点时用官方攻略叙事文本兜底（`narrative`），
保证流程完整可玩；后续可把 `narrative` 替换为真实剧本下标。

读取存档默认找原版目录里的全剧情存档，路径可用 `FLYINGSB_SAVE` 环境变量覆盖：

```sh
export FLYINGSB_SAVE=/path/to/Save1.dat
```

## 操作

| 按键 | 作用 |
|---|---|
| 方向键 / WASD | 移动光标、走格、菜单选择 |
| Enter / Space | 确认、攻击、进入瞄准 |
| ESC | 打开战斗菜单（技能 / 道具 / 回合结束）、取消 |
| X | 取消 / 回退 |
| Shift + 方向键 | 瞄准阶段转朝向（攻击范围随朝向旋转） |
| `/` | 竞技场战斗内控制台（加敌人、退出战斗等） |

| `G` | 世界地图上推进主线剧情（完整章节链：序章→收悟空→各章→决战玉皇→结局） |

世界地图上**走向地图角色**（村民 / 守卫 / 神像）即触发其原版对白（`Enter`/`→` 翻页，`ESC` 返回地图）；
`F1` 跳到枢纽阿尔夏（348）/ `F2` 回世界地图 / `T` 打开剧本预览。

## 测试

```sh
venv/bin/python -m pytest tests/ -q
```

测试不依赖原版资源（缺资源的用例会自动 skip）。

## 目录结构

```
core/       战斗引擎、动画字节码引擎、技能演出、存档解析、音效表、真实地图 (real_map.py)、
            物品价格 (prices.py)、剧本解析 (script_text.py)、地图角色 (map_npcs.py)、
            NPC 真精灵 (npc_sprites.py)
scenes/     标题 / 世界地图 (含 NPC 图层 world_map/npcs.py) / 战斗 / 竞技场 / 商店 / 剧情回放 场景
tools/      资源提取 (extract_dll / extract_maps / extract_script / extract_events /
            extract_locations / extract_script_table / extract_item_table / extract_map_npcs)
            + inspect_save
tests/      pytest 单元测试
assets/     提取产物 (不入库, 由 tools/extract_dll 生成)
  maps_preview/  地图渲染预览 (由 tools/extract_maps 生成)
  script/        剧本分派表 / 原始对白 (由 extract_script_table / extract_script 生成)
  items_table.json  原版物品买卖价 (由 extract_item_table 生成)
  map_npcs.json     每张地图的角色放置 (由 extract_map_npcs 生成)
```
