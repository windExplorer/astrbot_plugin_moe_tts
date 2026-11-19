# 更新日志

## v0.5.6

加上萌系 Logo（用户提供图片），插件列表与 WebUI 统一形象。

- **插件 Logo**：根目录新增 `logo.png`（256×256，粉紫马卡龙色 Q 版小女孩 + 耳机 + 麦克风，双揪揪、大眼睛）。AstrBot 4.29.4 只认插件根目录固定文件名 `logo.png`，会自动在插件列表显示。
- **WebUI 品牌图标**：侧边栏原先的 AudioLines 图标换成同一张 logo，尺寸加大到 48px。
- **单文件产物保持**：Vite 配置 `assetsInlineLimit` 提到 1MB，logo 内联成 base64 进 JS，pages/ 产物仍只有一个 JS（371KB），无额外图片请求。
- **打包清单**：`build_zip.ps1` 加入 `logo.png`；WebUI 守卫新增"根目录有 logo.png"和"Logo 已内联进 JS"两项。自检 core 104 + webui 43 项全过。

## v0.5.5

修正 v0.5.4 的括号处理方式：文字气泡恢复显示完整原文，顺序为「括号描写在前、正文在后」。

- **背景**：v0.5.4 把补发正文里的括号剥掉了，结果变成两条消息「吃的什么。」+「（迷迷糊糊，声音很轻）」，顺序反了，也不是用户想要的。
- **正确行为**：文字气泡显示**完整原文**（如「（迷迷糊糊，声音很轻）\n吃的什么。」），遵守「文本绝不丢失」；语音侧仍按 `skip_bracket_tts` 剥括号只读正文（耳朵听正文、眼睛看全文，两者口径不同是有意的）。
- **修复**：
  - `_seg_text_for()` 恢复返回原文（单段/多段都保留括号），不再剥离。
  - 括号单独补发的条件从「not text_in_chain」收窄为「voice_only 且 not text_in_chain」——both 模式的正文已含完整原文（含括号），再补发就重复；只有 voice_only 模式正文完全不发，才需要单独补发括号。
- 守卫更新：`tests/test_hooks.py` 改为断言补发正文保留原文括号、括号补发仅限 voice_only。core 104 + webui 41 + hooks 12 项全过。

## v0.5.4

重新打包发布括号重复修复（v0.5.3 因构建偶发失败打进了旧前端产物，已作废，请勿安装）。

- 修复内容同下：文字补发正文按 `skip_bracket_tts` 剥离括号，避免与括号单独补发重复。
- 本次重新构建前端确认产物为新版（JS `index-DM5QaImm.js`），包内 JS 与 index.html 引用一致。

## v0.5.3（已作废，请勿安装）

打包时前端构建偶发失败，包内打进了旧版 JS，前端修复未生效。请用 v0.5.4 代替。

修复文字补发时括号语气描写重复出现的问题。

- **现象**：真机截图里，语音气泡下方出现两条文字——「（迷迷糊糊，声音很轻）吃的什么。」和「（迷迷糊糊，声音很轻）」，括号内容重复。
- **根因**：`_seg_text_for()` 在只有 1 段时直接 `return full`，把原文里的括号一起补发了；而语音侧 `_prepare_text()` 已按 `skip_bracket_tts` 剥离括号、括号由 `_do_tts` 末尾单独补发一次——于是正文带括号 + 括号补发 = 重复。
- **修复**：`_seg_text_for()` 无论单段/多段都按 `skip_bracket_tts` 剥离括号，与语音侧口径一致；`skip_bracket_tts=false` 时仍保留括号。
- **防再发**：`tests/test_hooks.py` 新增 AST 抠方法测试，驱动 `_seg_text_for` 验证单段/多段剥离与开关关闭时保留。自检 core 104 + webui 41 + hooks 12 项全过。

## v0.5.2

修复真机发送消息失败（`list has no attribute 'chain'`）。

- **现象**：真机日志反复出现 `[moe_tts] 发送消息失败: 'list' object has no attribute 'chain'`，语音发不出去。
- **根因**：`_realtime_send()` 把 `list[Component]` 直接传给 `context.send_message()`，但 AstrBot 的该 API 要的是 `MessageChain` 对象（内部访问 `.chain` 属性）。
- **修复**：发送前统一用 `MessageChain(list(chain))` 包装（已是 MessageChain 则跳过）。参考 AstrBot 4.29.4 源码与 cosyvoice 插件的主动发送写法确认。
- **防再发**：`tests/test_hooks.py` 新增 AST 守卫——检测 `_realtime_send` 里 `send_message` 调用前必须有 `MessageChain(...)` 构造；已验证旧写法会被捕获。自检 core 104 + webui 41 + hooks 8 项全过。

## v0.5.1

修复自定义下拉框被遮挡的问题。

- **现象**：配置页下拉框展开后，菜单只露出第一项，下面被「分段」等后续卡片盖住。
- **根因**：下拉菜单用 `position: absolute` 渲染在卡片内部，`z-index` 被困在卡片的层叠上下文里，盖不过后面的卡片及 sticky 元素。
- **修复**：菜单改用 Vue `Teleport` 渲染到 `body`，`position: fixed` 按触发按钮的 `getBoundingClientRect()` 定位；空间不足时自动向上翻转，滚动/缩放时实时跟随；点击外部与菜单内部正确区分。全局样式类避免 scoped 对 Teleport 节点失效。

## v0.5.0

音色同步支持语种（language）字段——后端后来补的语种/参考文本，二次同步会自动更新。

- **背景**：tts_serve 的 `voices.json` 新增了 `language` 字段（如 `"language": "zh"`）。此前同步链路会把语种丢掉，导致"后端补了语种，插件同步不到"。
- **链路改动**（三处配合，tts_serve 代码无需改，`VoicesStore.load()` 用 `dict(value)` 自动透传新字段）：
  - TaskHub `voices_info()` 增加 `languages: dict[文件名, 语种]` 字段，代理上游时透传（1.3.0）。
  - 插件两个适配器都解析语种：TaskHub 读 `languages` 映射，tts_serve 直连读条目的 `language` 字段。
  - `sync_server_voices()` 把语种写入快照；`set_server_voices()` 的策略是「服务端有值就覆盖、没值才保留本地旧值」——所以第一次同步为空、后端补上后第二次同步会更新；你在 WebUI 手打的语种在服务端没有时仍保留。
- 自检新增语种解析与"二次同步覆盖 text/language、保留本地 markup、移除已删音色"测试，core 104 项全过。

## v0.4.1

修复会话页操作后列表不自动刷新的问题。

- **现象**：点会话开关（启用/停用）或编辑保存后，列表状态不变，要手动点「刷新」才更新。
- **根因**：`toggle` 只改了传入的 `s` 对象，而这个对象是 `sessions` computed 从 `rawSessions` + 联系人快照重新生成的临时副本，改它不会影响源数据，computed 重算后改动丢失。
- **修复**：新增 `upsertLocalSession()` 把改动写回源数据 `rawSessions`（已有项就地替换、没有则新增，标记为已启用并更新 updated），`toggle` 与 `saveEdit` 都走它——后端保存成功后列表即时重算刷新，无需手动刷新、也不必重新拉全量联系人数据。

## v0.4.0

WebUI 体验升级：自定义下拉、帮助页、音色试听直取音频、顶部固定。

- **自定义下拉组件**：所有 `<select>`（配置页 effect_intensity/send_mode/tts_scope、语种、音色、服务端类型等）换成自研 `BaseSelect.vue`——玻璃拟态弹层、勾选态、滑入动效、点击外部关闭、移动端友好；枚举值用中文 label 展示（如「语音 + 文字」「仅大模型回复」「轻量/中等/密集」），不再显示 both/medium 这类英文原值。
- **副语言标记修正**：Qwen3-TTS 不支持 `[breath]/[laughter]`（CosyVoice3 tokenizer 才把它注册为 special token），开启会被念成英文单词。`auto_breath`/`auto_effect` 默认改为 false，引擎缺键兜底也改 false；配置提示与帮助页均注明仅 CosyVoice3 可用。
- **帮助页**：新增「帮助」页签，列出全部指令（/语音开|关|音色|状态|<文本>）、触发方式、5 个 LLM 工具、七页导览、重要说明（Qwen3 标记、文本不丢失、连通状态、试听说明等）。
- **音色试听改直取音频**：点击音色直接取服务端**参考音频文件**播放（本地缓存 `data/voice_previews/`，缓存命中秒开），不再走 TTS 克隆、不占 GPU；删掉顶部「试听文本」输入。克隆合成放到合成实验室。服务端侧：TaskHub 新增 `GET /voices/{name}/audio` 代理上游 tts_serve 的 `/api/voices/{name}/audio`（需重启 TaskHub）；插件两种服务端类型都实现了 voice_audio()。
- **顶部固定**：页面标题区 sticky 固定在顶部（毛玻璃背景），音色库/会话页工具栏 sticky 固定在标题下方，滚动时不再跟着跑。
- 自检 core 97 + webui 41 + hooks 7 项全过；TaskHub 改动单独语法验证通过。

## v0.3.5

修复 WebUI 配置项全空、保存后仍为空的严重 bug。

- **现象**：配置页所有项显示为空，改完点保存后再打开还是空。
- **根因**：`_refresh_cfg()` 每次被调用时用 `context.get_config()` 覆盖 `self.config`。但 `context.get_config()` 返回的是 AstrBot **全局配置**（`data/cmd_config.json`），与插件自己的 `data/config/<plugin>_config.json` 毫无关系——插件配置每轮消息都被全局配置冲成空；`__init__` 里配置的回退值也误用了它。
- **修复**：
  - `_refresh_cfg()` 直接返回注入的 `AstrBotConfig`（插件自己的配置对象），不再用全局配置覆盖；`__init__` 回退改为空 dict。
  - `GET /config` 以 `_conf_schema.json` 为准组装值，缺失键用 schema `default` 填充，页面永不空白。
  - 保存成功后 `_sync_runtime_config()` 把超时/重试/冷却/队列阈值等标量同步到 router/engine，无需重启即生效。
- **防再发**：`tests/test_hooks.py` 新增守卫——AST 检测 `_refresh_cfg` 不得调用 `get_config`，并验证返回的是插件配置对象而非全局配置；已验证旧写法会被捕获。自检 core 92 + webui 35 + hooks 7 项全过。

## v0.3.4

调整按钮交互配色，悬浮变化更柔和。

- 普通按钮 hover 从 `--fill` 跳到 `--hover-2`（透明度约翻倍）落差过大，新增按钮专用 `--btn-hover`（约 1.35x 变化幅度）；ghost 按钮用更淡的 `--btn-ghost-hover`（不再从全透明突变）。
- 危险按钮 hover 用专用 `--danger-hover`；主按钮/青色按钮的 `brightness` 从 1.08 降到 1.04；位移反馈从 -2px 收到 -1px。深/浅两套主题同步调整。

## v0.3.3

修复 v0.3.2 的消息处理崩溃 bug。

- **现象**：每条消息进入 LLM 回复钩子时抛 `TypeError: _flag() missing 1 required positional argument: 'key'`，语音功能整体不可用。
- **根因**：初版 `_flag(self, event, key)` 定义里带了一个多余的 `key` 参数，而所有调用处（ `_set_flag`/`_get_flag` ）只传 `event`。这是方法签名与调用不一致的遗留 bug，之前的自检只测独立的纯函数、从没驱动过钩子辅助方法，所以一直漏检。
- **修复**：`_flag(self, event)` 去掉多余参数。
- **防再发**：新增 `tests/test_hooks.py`——用 AST 从 `main.py` 原样抠出 `_flag`/`_set_flag`/`_get_flag`/`_clear` 到假类上执行，用假 event 驱动真实调用链；已验证旧签名会被该测试准确捕获。另用 AST 扫描全部后端模块的 self 方法调用，无其它同类问题。

## v0.3.2

修复三个使用问题（路由 / 音色同步 / 按钮样式）：

- **刷新页面保持当前页**：插件页在 AstrBot iframe 里，刷新时 hash 会丢导致跳回总览。现在切页时把当前页写进 localStorage，hash 丢失时从它恢复，不再一律回总览。
- **TaskHub 音色同步为空**：
  - 插件侧：TaskHub `/voices` 的 `files` 是**文件名 list**（不是 dict），旧解析只处理 dict、且没读 `texts`；重写为按 list 解析并把 `texts`（字符串或对象格式的 `prompt_text`）正确映射为音色参考文本。
  - 服务端侧（TaskHub 项目 `adapters/tts.py`）：`voices_info()` 改为**优先代理上游 tts_serve 的 `/voices`**（对象格式 → 转为标准 `{files, texts}`），上游不可用才回退本地配置。这样即使 TaskHub 自身 `voices_dir/voices_json` 未配置，也能透出上游真实音色。需重启 TaskHub 生效。
- **按钮字色**：`.btn-primary` / `.btn-cyan` 等深色/饱和渐变底按钮强制白色字体，修复浅色主题下「深底黑字看不清」。
- 自检新增 TaskHub 音色解析测试（list 格式 + 对象 texts），core 92 项全过。

## v0.3.1

修复 v0.3.0 安装即失败的严重 bug。

- **现象**：AstrBot 安装/加载 v0.3.0 时报 `'JsonStore' object is not callable`，插件直接装不上。
- **根因**：`contacts.py` 的 `ContactsScheduler.__init__` 里把 `store.contacts_meta` 当成方法调用了 `store.contacts_meta()`，但它是 `JsonStore` **实例属性**，实例化即对实例加括号触发 TypeError。v0.3.0 的自检只测了纯函数（normalize_friends/groups），没实例化调度器，所以漏检。
- **修复**：改为读实例属性 `store.contacts_meta.data`。
- **防再发**：自检新增「初始化烟雾测试」——真实实例化 `PluginStore` + `ContactsScheduler` 并走一遍联系人快照读写，构造期再出这类错误会被直接捕获。自检 86 项全过。

## v0.3.0

会话管理支持加载机器人全部群与好友；主题按钮精简。

- **全量联系人同步**（参考 `astrbot_plugin_moe_permission`）：新增 `contacts.py`，从 aiocqhttp(OneBot v11) 的 `get_group_list` / `get_friend_list` 拉取全部群和好友，落本地 `contacts.json` 快照（离线可读、WebUI 秒开）。后台定时同步（默认 30 分钟，`contacts_sync_interval_min` 可配/可关）+ WebUI「同步列表」手动触发，共用互斥锁。会话管理页以全量联系人为基础叠加语音状态：有状态的按活跃排前并显示开关，未启用的可一键开启；群/好友都带头像（CDN 后端抓取+缓存）、群名/昵称。只支持 aiocqhttp，其它平台跳过，失败写 `meta.error` 展示、不影响语音。
- **主题按钮**：去掉文字，改为纯图标，与版本号放同一行，hover 带旋转微动效。

## v0.2.1

修复服务端未连通却显示「在线」的判定 bug。

- **现象**：TaskHub / tts_serve 明明没启动，WebUI 总览的服务状态仍显示绿色「在线」，用户无法第一时间发现服务端失联。
- **根因**：`_overview` 里 `"ready": active is not None`——只判断「配置里有没有服务端」，从没真正发请求探测。而 `health()` 复用了合成的 250s 读超时，即便调用也会卡死页面，所以当初被绕开了。
- **修复**：
  - `BaseAdapter.health()` 改用独立的短超时（连接 3s / 读取 6s），连不上秒级失败，不再卡 WebUI；插件初始化时探测也不会再卡 250s。
  - `_overview` 实际 `await adapter.health()`，`ready` / `server.online` 取自真实探测结果；返回 `health_error` 显示具体连接失败原因。
  - 总览页徽章区分「未连通(红) / 冷却中(黄) / 在线(绿)」，连接失败时直接显示错误原因。

## v0.2.0

WebUI 体验与数据能力大升级（新功能系列）：

- **浅色主题**：新增完整浅色配色（一套语义令牌覆盖两套主题），侧栏底部 / 移动端顶栏可一键切换，localStorage 持久化记住偏好。
- **WebUI 配置可改**：配置页从只读升级为可编辑——按 schema 类型渲染开关/下拉/数字/文本/列表控件，保存写回 `AstrBotConfig` 并落盘，与官方配置弹窗双向一致、立即生效；有未保存改动时显示保存/撤销栏。
- **服务端音色入库**：新增「从服务端同步」——拉取服务端 `/voices` 后落盘本地快照（`server_voices.json`），离线也能读最新一次同步结果；音色页展示同步时间与来源。同步由 WebUI 显式触发，不随每次读取打服务端。
- **服务端可编辑**：服务端列表新增编辑弹窗，可改名称/类型/地址/超时；编辑当前启用项会立即重建 adapter 生效。
- **会话管理强化**：区分群聊/私聊（解析 UMO 第 2 段），tabs 全部/私聊/群聊；记录并展示群名（消息随附或后台 `get_group` 补查）、用户昵称、用户头像与群头像（腾讯 CDN 后端抓取 + 磁盘缓存 + data URI，失败降级首字母色块）；按最后活跃时间排序，展示「刚刚/N 分钟前」；可手动改群名/昵称。

## v0.1.1

发布前的代码审查（对照 AstrBot 4.29.4 源码）修掉两处隐患：

- **WebUI 错误处理**：`astrbot.api.web.error_response()` 返回 `{status:"error", message, data}` 信封，前端 `normalize()` 原先只认 `{success:false}`，导致后端错误（如合成失败、服务端不可用）被当成正常数据静默吞掉。现在两种信封都识别并抛出异常，页面能正确 toast 报错。
- **多会话串台**：用户「用文字回复」的原消息原先存在全局单键 `_last_llm["__user__"]`，多个会话并发时互相覆盖，可能让 B 会话被 A 会话的文字请求误 suppress。改为按 `unified_msg_origin` 存储并带 TTL 时效校验。

## v0.1.0

全新插件「萌萌语音」，独立于旧 `astrbot_plugin_cosyvoice` 重写。

- **服务端**：默认接 TaskHub 中转站（`:9000`），可直连 tts_serve 网关（`:50001`）；多服务端可配置、**同时只启用一个**。TaskHub 支持队列位置感知（`X-Queue-Position`）与 250s 读超时；直连网关额外开放 ASR、后端切换、显存管理、音色 CRUD、极速克隆与生成参数。采样率首次合成前自动探测。
- **触发**：会话级语音开关 / 音色 / 发送方式（持久）、自动语音、关键词、`/语音开|关|音色|状态|<文本>` 指令、5 个 LLM 工具、语义 Skill。
- **文本**：括号不朗读、换行/标点分段与试算、副语言标记（换气/音效）、相邻重复折叠、通用翻译适配器；错误回显不朗读。
- **容错**：429/504 退避重试、500/繁忙进冷却、失败一律降级文字、防重复与主动推送回环拦截。
- **WebUI**：Vue3 + Vite + TypeScript + Tailwind CSS v4 + lucide-vue-next，七页（总览/音色库/会话管理/合成实验室/服务端/任务日志/配置），渐变玻璃拟态、微动效、波形动画、完整移动端底部导航 + 安全区适配。单文件产物 `pages/moe-tts/`。
- **工程**：显式清单打包（顶层 .py 守卫 + 撞版检测，旧包保留），核心自检 68 项 + WebUI 守卫 20 项通过。无 i18n（仅简体中文）。
