# 2026-09-22

## rewrite 项目跑通（幻想西游记 Pygame 重制版）

- 项目位置：`rewrite/`，是原版《幻想西游记》(FlyingSB.exe) 的 Python+Pygame 重制版，通过逆向原版 DLL 还原战斗系统。
- 原版游戏目录：`origin/flyingsb/`（含 ASE_FM.dll、ASE_PS.dll、MAPSET.dll、PCXSET.dll、se_event.dll、WAV_EFT.dll 和 Data/ BGM）。README 默认路径正好匹配，无需设 `FLYINGSB_ORIGIN`。
- 环境：系统 Python 3.12.3（满足 3.12+ 要求）。已在 `rewrite/venv` 建虚拟环境并装好依赖（pygame-ce 2.5.8、pefile、pytest 9.1.1、opencc）。
- 资源提取：`venv\Scripts\python.exe -m tools.extract_dll` → 提取 2508 项到 `assets/`。Windows 无符号链接权限，BGM 自动复制（71 个 wav）。
- 测试：`venv\Scripts\python.exe -m pytest tests/ -q` → 196 passed, 4 skipped。
- 启动：`venv\Scripts\pythonw.exe main.py`，窗口标题「幻想西游记」正常弹出。

### Windows 运行命令备忘（README 里是 Linux 写法，需改成 Scripts/）
```powershell
cd rewrite
python -m venv venv
.\venv\Scripts\python.exe -m pip install -r requirements.txt
$env:PYTHONIOENCODING="utf-8"          # 避免 pip/脚本输出 gbk 解码报错
.\venv\Scripts\python.exe -m tools.extract_dll
.\venv\Scripts\pythonw.exe main.py     # 运行游戏
```
- 操作：方向键/WASD 移动，Enter/Space 确认，ESC 战斗菜单，Shift+方向键 转向，竞技场内 `/` 控制台。

## 修复：中文显示乱码（豆腐块）

- 现象：游戏界面里所有中文都是乱码方框，只有 ASCII 正常。
- 根因：`scenes/menu.py` 的 `CHINESE_FONT_CANDIDATES` 只有 macOS 字体路径（`/System/Library/...`），Windows 上全部不存在，回落到 `pygame.font.SysFont(None)`（无中文字形）。所有场景都 `from scenes.menu import load_chinese_font`，故一处修复全站生效。
- 修复：在 `load_chinese_font` 里新增 Windows 字体路径（msyh.ttc 微软雅黑 / simhei.ttf / simsun.ttc / simkai.ttf / Deng.ttf）、Linux 字体路径，并加一层 `pygame.font.match_font` 按系统字体名匹配，最后才兜底 `SysFont`。
- 验证：本机字体解析为 "Microsoft YaHei"，无头渲染中文 mask 像素 3956；pytest 196 passed, 4 skipped；重启游戏窗口正常。

## 新增：原版地图解析+渲染工具 tools/extract_maps.py

- 需求：把 `assets/maps/` 里的原版地图解析成可视 PNG。
- **逆向出的 .map 格式**（已用多张图互验）：
  - `.map` = **120 个 u32 头部**（10 条 ×12）+ **两张 W×H 的 u32 网格**
  - 头部关键字段：`u[6]=宽W`、`u[7]=高H`、`u[8]=tileset列数`、`u[9]=tileset行数`（u[10]/u[11] 是运行时指针，忽略）
  - 网格 A = 可视瓦片索引（行优先，0..cols*rows-1）；网格 B = 碰撞/属性（每格 u32，高16位=flag，低16位=index）
  - 恒等式 `120 + 2*W*H == 文件u32总数`（对 5+ 张图验证通过）
  - 瓦片尺寸 **64×48**（= `core.sprites.base.TILE_W/TILE_H`）
- `.mfo` = **GBK 文本**元数据（`mapname` 数字ID / `pcpos` 玩家坐标 / `jmp` / `battleset`）。
- **tileset 配对规律**：多数地图没有同名 `.pcx`。用头部 `(ts_cols,ts_rows)` 去匹配现有 P 面图集即可（多候选时同页前缀优先、同名优先）。
- 产物：`assets/maps_preview/<地图>.png`（**487/487 全渲染成功**）+ `_index.json`。
- 跑法：`venv\Scripts\python.exe -m tools.extract_maps`。
- 抽查（房间/迷宫/天空/湖泊/城镇/树林）全部连贯正确。README 已同步更新。
- 备注：地图命名形如 `TAA0_00P`/`TAM0___P`/`THG12__P`，末尾 P/S = 主/阴影层。

## 真实地图接入场景（战斗 + 世界地图）

- 新增 core/real_map.py（RealMap）：解析 .map + tileset，提供 draw_terrain/_camera_offset/passable/build_battle_map，可当 ArenaTerrain 直接用。
- 通行：出界 或 网格B flag≠0 或 纯色空瓦片(品红/纯黑) = 不可走。
- 接入：world_map/scene.py 用 T_LOC0_P；arena/battle_scene.py 用 TARA_00P；battle_launch.py 障碍/刷怪走真实地图。缺资源自动回退占位图。pytest 196 passed。

## 调研：原版剧情/事件数据在 FlyingSB.exe 内（关键结论）

用户目标：把原版完整复刻到 Win10/11。第一步调研（只读 exe）结论：**剧情数据可得，最大风险排除**。
- exe 内 Big5 剧本区约 0.8MB（文件偏移 0x208000–0x330000），16249 条文本。
- 剧本是**带标记语言的脚本**：`<msg_id=X>`(说话人)、`<$SON:1413>`(立绘/语音ID)、`<$SONA>`/`<$MIRO>`(BGM，对应 Data/*.WAV)、`<&item329>`(给道具)、`<br_r>`/`<D1..8>`/`<W-10>`(显示控制)、`<#NPC>` 等。
- 技能/道具表 = `名字\0\0类型\0\0描述\0\0`（0x290000–0x2a0000）。
- 地图事件在 `.mfo`（pcpos/jmp/battleset/anime）。存档 0x0C00 起 ~12KB flags 区（7492 非零）= 剧情进度。
- exe 残留引擎源码名（26 个）：seq.cpp(595) 序列引擎、dlgbox.cpp 对话框、event.cpp 事件、map.cpp/localmap.cpp、btl_do.cpp 战斗、avi.cpp 过场、menu.cpp、fc_station.cpp/whlp.cpp 等 → 说明原版引擎结构；重制版已大量还原 seq.cpp 那部分。
- 待办（未做）：解析 msg_id→文本 索引表、存档 flags 位定义、.mfo 事件表、AVI 播放（需 ffmpeg/pyav）。

## 已完成：剧本提取器 tools/extract_script.py

- 只读 FlyingSB.exe，用 1KB 窗口 CJK 密度(=0.30)自动找剧本区 → 119 段 / 401408 字节(11%)。
- 按 NUL 切条目 → 7348 条 / 259109 字符；23 种 msg_id（NPC/P/SAM/KEY...）。
- 输出 assets/script/：scenario_full.txt(全文可读)、stats.json(规模+标签直方图)、messages.json(按 msg_id 分组)。
- 标签直方图 top：`<->`2512 `<WA>`726 `<D4>`725 `<$SONA>`397 `<$SON>`379 `<$MIRO>`311 `<br_r>`306 `<D8>`275 `<$MASK>`233（<$XXX> = 立绘/语音+BGM，对应 Data/*.WAV；DIR2/4/6/8 = 朝向；possub_u / widthXL = 显示控制）。
- 样本（0x21b000 起）能读出完整对话：`<msg_id=NPC><#P>唉,很煩.;`、城市介绍"這裡是名氣城.…"。
- exe 路径可用 FLYINGSB_EXE 覆盖；README 已更新。

## 复刻三部曲：剧本结构 / 存档 flags / .mfo 事件表

1) 剧本结构（tools/extract_script.py 增强）：无索引表，是线性流（NUL 分隔、';' 结束一条、'|' 换行）。
   窗口 CJK 阈值 0.40 + 区域质量门限（去标签后中文占比≥0.35、单字占比<0.22）+ 条目过滤 → 5039 条。
   输出 messages.json = [{scene, speaker, text, tags, cmds}]（cmds: item/voice/bgm）。
2) 存档 flags（core/save_manager.py 扩展 + tools/inspect_save.py）：
   布局 0x00 标记 / 0x04 地点(Big5) / 0x20 5×DWORD state / 0x44 16×0xBC 角色 / 0xBF4 金钱 /
   0xC04..0x1C00 flags 位图 / 0x1C00+ 其它表。
   `state[2]` = 剧情进度（SAVE0=0 → Save1=19）。flag_bit()/set_flag_bits()/progress 已加。
   inspect_save 可对比两档：diff 出变化位（示例 +1923,+13472,-13473）。
3) .mfo 事件表（tools/extract_events.py）：文本配置，**地名/注释是原版韩文（cp949/EUC-KR）**，不是中文！
   指令：pcpos(x,y,z,朝向d,act,link) / jmp(m,pp,key,act,c0,c1,o0,o1) / anime / scroll /
   mapname / enemy / player / battlearea / partylevel / escape / enemytype / [battleset N..end]。
   输出 assets/maps_events.json：487 张，pcpos 1164 条、jmp 1136 条、带战斗配置 226 张。
   注：exe 剧本是 Big5，.mfo 是 EUC-KR（原版韩文文件未本地化）。

## 剧本↔地图关联 + 存档 0x1C00+ 表（进行中）

### 已解开：地图↔地图（位置 ID 系统）
- .mfo 的 `mapname` 为数字 = 该地图**位置 ID**（434 张数字 ID 图，范围 48..487，近乎连续）；
  文字名的 53 张是 T_LOC*（世界地图，韩文名 남남주）。
- .mfo 的 `jmp` 字段 `m` = **目标位置 ID**（表头 m pp key act c0 c1 o0 o1）。
- 生成 `assets/map_graph.json`：430 个位置 ID、1032 条跳转边、**92% 双向**（如 TARA 248↔249↔250）。
- 工具：`tools/extract_events.py`（同时输出 maps_events.json）。

### 未解开：剧本↔地图（证据）
- exe 中**没有**指向剧本区的索引表（file-offset 表 0 段；VA 表只有 26 个小表，均为杂项字符串表）。
- MAPSET.dll 只有 MAP/MFO/MAT/PCX 四种资源，无额外"对话/事件"资源类型。
- 剧本里的 `<msg_id=X>` 是**说话人名**（NPC/P/SAM…），不是位置 ID（仅 13/14 两个数字）。
- 结论：剧本与地图的绑定很可能在 **exe 代码里**（解释器分发），需反汇编才能确证。

### 存档 0x1C00+ 表（结构已定、语义待解）
- 布局：0x00 标记 / 0x04 地点(Big5) / 0x20 5×DWORD state(state[2]=进度) / 0x44 16×0xBC 角色 /
  0xBF4 金钱 / 0xC04..0x1C00 flags 位图 / **0x1C00..0x3B80 状态表**。
- 状态表约 8064 字节；u32 绝大多数是 `0x00192B44`(=1649476) 及其高位变体 `0x80192B44`；
  疑似"每位置/每对象默认状态表"（448 或 504 项），但**语义未解**，需更多不同进度存档对比。

## B 完成：位置 ID 驱动的地图切换骨架

- **传送点机制破解**：`.mfo` 的 `pcpos[i]`=(x,y,z,d,act,**link**)，`link` = `jmp` 下标；
  站在 (x,y) 上 → 触发 `jmp[link]` → 目标 `m` = 目标位置 ID。（TAL0___P/TAS0___P 实证）
- `jmp` 的 c0/c1/o0/o1 是目标端的坐标区（单位未定，暂存）。
- 新增 `tools/extract_locations.py` → `assets/location_map.json`：429 数字ID位置 + 40 命名位置 + 1136 传送点。
- 新增 `core/world_graph.py`：`base_for(id)` / `transitions(base)` / `spawn(base)` / `named_locations()`。
- `scenes/world_map/scene.py` 接入：`enter_location(base)` + 走上传送点自动切图；
  调试键 **F1** 跳枢纽 `TAL0___P`(348)、**F2** 回世界地图（`T_LOC0_P`）；HUD 显示当前地图。
- 验证：`T_LOC0_P → F1→ TAL0___P(2,37) → 站上(7,9) → 切到 TAL0_00P(9,17)` ✅；pytest 196 passed。
- 注意：目标 ID < 48 属"命名/世界地图空间"，目前无法解析（打日志跳过）。命名位置 40 个含韩文名
  （아스람=雅士蘭 含INN/PUB/ROOM/ITEM/WEP、다섯손가락마을=五指村、오행산=五行山、남남주）。

## C：批量对比 saveData 7 档（进展）

- 7 档全是晚期（魔塔/真·魔塔），state=(38~41, 38~46, 3~54, 11~45, 0)，金钱 75万~212万。
- **0x1C00 区结构破解**（重要）：每档该区（2016 个 u32）几乎只由三个值构成：
  `V`（约 890~900 个）、`V|0x80000000`（恰好 500 个）、`~V`（约 132 个），另 ~480 个其它。
  `V` 的低 16 位随档变化，但**高 16 位是每档常数**（Save1=0x0a1b, Save3=0x0013, Save5=0x022e…）。
  → 说明这不是"加密"，而是高度规律的状态/校验数组；2016 ≠ 任何地图的 W×H。
  **语义仍未解**（疑似 flags/校验/引擎状态数组），需要更多"不同地图/早期"的存档。
- flags 位：对比发现变化集中在若干区段（0-3、32-34、64-67、288-321、11552-11809、13472-13507、27392-27395），
  但样本全是晚期塔内存档，早期剧情位无法映射。

## D 完成：命名镇子接入 → 全图连通

- **小 ID 空间 0..47 破解**（共 48 张世界/城镇地图，由 jmp 邻接结构推得）：
  - 0–9 = `T_LOC0..9_P`（남남주 世界地图段）
  - 10–21 = 아스람(雅士蘭)：hub `TAS0___P`=10，店铺 `TAS0_00P..10P`=11..21（店铺都跳回 10）
  - 22–29 = 다섯손가락마을(五指村)：hub `TFI0___P`=22，房间 23..29
  - 30–47 = 오행산(五行山)：`TOH0_*` 18 张（相邻互跳链验证）
- `tools/extract_locations.py` 内置 `_SMALL_ID` 映射 → `location_map.json` 现有 **487 个位置**，
  1136 传送点中仅 8 个目标无地图（ID 空间空缺：91/211/218/283/291/292/458/464）。
- 实测往返：`T_LOC0_P 站上(10,9) → TFI0___P(13,39) → 走(13,39) → 回 T_LOC0_P(10,9)` ✅
- 工具链：`extract_locations` → `location_map.json` → `core/world_graph.py` → 世界地图场景。

## E 试水完成：可播放原版对白

- `scenes/dialogue.py`（原来是 `# TODO` 占位）→ `DialogueScene`：
  读 `assets/script/messages.json`，底部对话框逐条播放；**Enter/→ 下一条、← 上一条、ESC 返回**。
- `load_dialogue()` 筛出 3616 条"像对白"的条目（有说话人/含句读/够长）。
- 世界地图按 **T** 进入剧本预览（`next_scene=DialogueScene(return_scene=self)`）。
- 验证：无头渲染出对白框（"剧本预览 1/3616 / 旁白 / 要在這裡儲存記錄嗎？"）✅；pytest 196 passed。
- 玩家操作键位汇总（世界地图）：方向键走，**F1** 枢纽348，**F2** 回世界地图，**T** 剧本预览，ESC 菜单。

## 修 bug + G + H

### 修：人物泡在水里
- 原因：`core/real_map.py` 的 `passable()` 只挡"出界/网格B flag≠0/色键空瓦片(品红·纯黑)"，
  水瓦片是真美术且 flag=0 → 被判可走，于是主角/战斗摆阵都站到水上。
- 修法：`_detect_void_tiles()` 增加**蓝色水域启发式**（单元格 5 点采样均值 `b-r>40 且 b-g>25 且 b>90` → 不可通行）。
- 效果：T_LOC0_P 可走 225→181；TARA_00P 不变（无水域）。注意这是启发式，蓝色地面/地毯可能误判。

### G：对白显示剧本指令
- `scenes/dialogue.py` 加了 `_cmd_labels()`：把 `cmds` 翻成可读标签。
  - `<&itemNNN>` → 走 `core.items.get_item_name()` 出**道具中文名**
  - `<$X:N>` → 立绘/语音；`<$X>` → 音乐/立绘
- 渲染在对白框内（金色小字），例：`音乐/立绘 → NPC2`。

### H：城镇商店 / 旅馆
- 新增 `scenes/shop.py`：`ShopScene`，`SHOPS` 表把 아스람 店铺地图映射到店型：
  `TAS0_08P`道具店(`CONSUMABLE`) / `TAS0_09P`武器店(`WEAPON`) / `TAS0_04P`首饰店(`ACCESSORY`) /
  `TAS0_01P`旅馆 / `TAS0_02P`酒馆。
- `enter_location()` 里 `if base in SHOPS: next_scene = ShopScene(...)`（进店自动开店）。
- 旅馆真实生效：改 `save.characters` 的 HP/MP、扣钱（实测 12 人恢复，-50 金）。
- 诚实标注：**价格表未提取**，现用分类档位估值；购买只扣钱+日志（库存段未解析）。

## 修：城里不遇怪 + J + I（部分）

### 遇敌规则（破解）
- `.mfo` 里**有 `enemytype` 的地图才有随机遇敌**（226 张，escape 多为 yes）；无 enemytype 的 261 张是安全地图。
- `tools/extract_locations.py` 增加 `enc` 字段 = 有 enemytype 且名字不含城镇标记
  （`SAFE_MARKERS = 마을/ROOM/INN/PUB/ITEM/WEP/ACC/슬럼/아스람/여관`）；`world_graph.has_encounters(base)`。
- `battle_launch._maybe_real_map_battle` 先查 `has_encounters(location_base)` → 城镇/房间不再遇敌。
- 注意：**世界地图 T_LOC0 本身 enemytype=False（原版世界图不遇敌）**；野外遇敌在如五行山 TOH0_*、TARA_* 等 225 张图。
- 实测：TAS0___P 城镇 60 次掷骰 0 触发；TOH0_00P enc=True。

### J：战斗摆阵修复
- `battle_launch._reachable_from(scene, start)`：从起点在可通行格上 BFS 求连通域；
  `_scatter_positions` 只在连通域内取格 → 单位不会被摆到水上/孤岛。
- 实测：TOH0_00P 开战，4 个单位全部落在可通行格。

### I：价格/库存（未完成，如实记录）
- `item.txt` 不在仓库；exe 里扫到的候选数组（@0x144b7c 的 1024 项 100,201,301…；
  @0x242b50 的 499 项 1,1,1,2,2…）**都不确实**是 356 项道具价格表 → 未采用。
- 角色块 extra 18 DWORD 里有**道具 ID 递增序列**（slot1=0..9、slot3=10..18），疑似库存/拥有标记，但语义未定 → 未接入。
- 结论：价格与库存需更多证据；商店仍用估值价格并已在 UI 标注。

## F：剧情绑定（机制已打通，映射表部分提取）

- **找到分发机制**（用 capstone 反汇编 exe .text，364039 条指令）：
  - 引擎播放对白 = `call 0x45b173(npc_idx, script_ptr, arg)`；
  - `script_ptr`（剧本入口）以 `push imm32` / `mov reg, imm32` 直接写在代码里；
  - **入口处正好是台词行首**！实例：`0x214b54` → `<msg_id=NPC>我...你說我說過要把神像給毀了?我...`；
    `0x2148b4` → `<widthM>@@<+><fast>這裡在買賣<br_r>武器...`（商店对白）。
  - 入口选择由**全局变量 + 常量比较**的 if-else 链驱动（如全局 `0x867e7c`：10/25/35/45/55/80/100/120/300/5000 → 各自入口）。
  - 扫到字符串 `scseq_.txt` → 原版剧本文件名（scene sequence）。
- 关键澄清：之前认为"没有索引表"是对的——**入口是代码里的立即数，不是数据表**。
- 新增 `tools/extract_script_entries.py`（依赖 capstone，已加入 requirements）：
  反汇编 .text，收集所有指向剧本区 `0x208000-0x340000` 的立即数/内存位移，
  解出入口处台词 → `assets/script/entries.json`（**6769 个入口点**；含非对白数据引用如 ase_data.FE）。
- 部分分发表已存 `assets/script/dispatch.json`（9 个全局组 / 46 条 (全局,值)→入口）。
- **仍待做**：完整提取 if-else 链的 (全局,值)→入口 映射（当前窗口启发式只捞到一小部分），
  再确定"全局值"与地图/NPC 的对应（值域横跨小ID 0..47 与 48..487 两套空间）。

## F 已完成（剧情分派总表 669 项全部解出）★

- **重要纠正**：F-3 抽到的 25/35/45/100/300 是**商品价格**，不是剧本分派。
  `0x867e7c` = **玩家的钱**（`cmp [0x867e7c], 0x5f5e0ff`=99999999 钳制上限；扣钱模式
  `cmp ...,价 / jge 有钱 / sub reg,价 / mov [0x867e7c],reg`；失败文案 0x215000="錢不夠"）。
- **真正的分派链路**（VA，ImageBase=0x400000）：
  ```
  0x45b7d0 PlayScript(param)        ; 函数入口: push ebp/sub esp,0x1f8
    index = param + 1
    if index > 0x29c -> default     ; 0x45b835
    jmp dword ptr [index*4 + 0x467006]   ; ★ 669 项跳转表
      各分支: push <对白地址>; push npc; call 0x45b173   ; 对白播放函数
  ```
  - 播放函数 `0x45b173`，全 exe 有 **1180 个调用点**（范围 0x4591cf..0x531e77）。
  - `0x7d75b8` = 当前 script 索引；`0x7d75bc` = 参数&0xFF；
    `0x7d75b0` = **"Input Field-Character ID"（地图角色 ID / FC ID）**，
    由 `call 0x404b6d("FC-Flag View", "Input Field-Character ID", &0x7d75b0)` 读取，
    引擎钳制到 **0..0x29b**。
  - `0x45b835` default 分支的对白是开发期英文占位串 `Field Character Speaking. Default String`。
- **新增 `tools/extract_script_table.py`** → `assets/script/script_table.json`：
  **669 项全部解析成功（649 条对白 + 20 个 default）**。
  顺序与剧情一致：id 0=拾取道具；id 18=「這裡是*五指村*」；19=五行山妖怪；20=神像被破坏；21=「供奉一隻*猴子*」。
- **顺带修正 I**：真实价格（来自 exe 扣钱点）——
  旅馆 130/140/150/180/300 G（id 387/419/477/543/564）、格斗赛门票 **10,000,000 G**（id 198/521）、
  早期另有 25/35/55 小道具、45 旅馆、80 住宿、100 格斗报名/一组10个、120 酒店、300 请醉老伯喝酒、10000 船票。
- **仍未定位**：FC id 与具体地图的对应。`.map` 头 120 u32 全解出=10 条渲染参数（调色板/尺寸），
  不含 FC 放置；`.mfo` mapname 是字符串且 445 个里绝大多数就是纯数字，用"对白提到地名"反查无效（只误命中数字）。

## B：剧情回放（完成）

- 新增 `scenes/script_viewer.py`：浏览 `script_table.json` 669 条（左列表 + 右预览），
  `Enter` 全屏回放；自动解析原版剧本标记（`<msg_id=X>`/`<#X>`/`<ids_X>` 说话人优先级、
  `*强调*`、`|` 换行、`;`=一个对话框、`@` 段首、`<&itemNNN>`→`core.items` 中文名、
  `<br_r>`/`<BR>` 换行、`<WidthM>`/`<push>`/`<pop>` 等显示标记剥掉）。
- 键位：↑↓ 选择、←→ 翻页、Enter 回放、`/` 搜索、Tab 只看有效对白、`T` 简/繁切换、ESC 返回。
- 标题菜单加了「剧情回放」项（`scenes/menu.py`）。
- `tools/extract_script_table.py` 改为**读全文**（原先截断 48B；现读到 NUL，最长 477 字符），
  并额外输出 `s` 字段（opencc t2s 简体）。
- 测试：`tests/scenes/test_script_viewer.py`（13 个用例）。

## C：真实价格（完成）

- **找法**：用 `tools/extract_script_table` 扫到的扣钱点确认 `0x867e7c` = 玩家金钱；
  再用物品名（exe 里的 Big5 字符串）反查指针表 → 定位 **物品记录表 VA 0x6954D4、步长 76 (0x4C)**。
- **字段**：`+0x00` 名称指针 / `+0x04` **卖价** / `+0x08` **买价**（-1=不可交易）/
  `+0x14` 分类（0x10帽 0x20衣 0x30武器 0x40首饰）/ `+0x44` 描述指针。
  代码访问模式 `imul reg, reg, 0x4c` + `[reg + 0x6954xx]`。
  买价确认：`0x4c5eca: mov edx,[0x867e7c]; sub edx,[0x867ca8]; cmp edx,[ecx+0x6954dc]; jge 买`。
  卖价确认：`0x4c5d3c: cmp [edx+0x6954d8], 0; jle 跳过`（筛可卖列表）。
- 名字与 `core/items.py` 逐项校验：**349/356 完全一致**（7 处仅简繁/尾字差异，
  含 `core/items.py` 的错字「莫亚**剑**」，原版是「莫亞**刀**」）。
- 新增 `tools/extract_item_table.py` → `assets/items_table.json`；新增 `core/prices.py`
  （buy_price/sell_price/is_available + 服务价）；`scenes/shop.py` 改用真实价格，
  只上架有买价的商品（武器店 52 项，如 双截棍122=3000、刀129=500）。
- 服务真实价：旅馆 **45/80/120/130/140/150/180/300 G**、船票 **10000**、格斗赛门票 **10000000**。
- 彩蛋：原版唯一「卖价>买价」的是 **314 兴奋剂（买700 卖1000）**，已写进测试当锚点。
- 测试：`tests/core/test_prices.py`。

## A：地图角色（FC 放置）放置数据（完成）★

- **结论：`.mfo` 的 `pcpos` 就是地图上的角色/入口**：`pcpos[i] = x, y, z, d, act, link`，
  `link` → `jmp[link]`，`jmp = m, pp, key, act, c0, c1, o0, o1`。
- **关键：那个 ID 同时是「传送目标位置 ID」和「script_table 索引」——原版位置表与剧本表
  共用同一套 ID 空间**（1136 条 jmp 里 982 条 m 是现存地图 ID；1087 条角色里 1014 条能解出对白）。
  所以「走到某处 → 去位置 m → 播放 script[m]」是一条统一链路。
- 实证锚点（人肉核对，已写进测试）：
  - `TAS0___P`：m=18「这里是*五指村*, 是位于世界最南方的村庄」、19 五行山妖怪、20 神像被破坏、21 供奉猴子；
    其 act=0 的两条（m=1, m=11）是传送点。
  - `TAL0___P`（阿尔夏）：m=353「这里是*阿尔夏*, 是北洲唯一的港口」、351「我是负责酒店的」、
    130「您不能从这儿通过」、298「有个不错的东西…你拿去吧」。
  - `T_LOC0_P`（南南部洲世界地图）：m=22 指路村民、30 饰品情报。
  - `TFI0___P`（다섯손가락마을 = 五指村）：m=23..28 神像/村民。
- `jmp.act`：0/1 ≈ 纯传送点、>=2 ≈ 站立角色，但更像精灵/动画类型（TAL0___P 全为 2 却仍是各房间入口），
  **不要当硬分类用**；`jmp.c0/o0` = 精灵帧号（292/293、332/333、372/373 这类 2 帧）。
- 新增 `tools/extract_map_npcs.py` → `assets/map_npcs.json`：
  **487 张地图 / 1087 个角色（1014 有对白）/ 49 个纯传送点**，每条含 x,y,d,act,script,sprite,text。
- 注：`tools/extract_locations.py` 把**所有** pcpos 都当传送点用（未按 act 区分），
  在统一 ID 空间的读法下仍然自洽，故**未改动游戏地图切换逻辑**（避免破坏现有可玩流程）。
- 测试：`tests/tools/test_map_npcs.py`。
- 全量回归：**228 passed, 4 skipped**。README 已同步（新增 §7 与剧情回放说明）。
