# 萌萌语音（astrbot_plugin_moe_tts）

让机器人用可配置音色开口说话——AstrBot 语音合成插件。默认接入 **TaskHub 中转站**，也可直连 **tts_serve 网关**（支持 ASR、后端切换、显存管理）。主力模型 Qwen3-TTS（极速克隆，无需参考文本），保留 CosyVoice3 回退。

> 设计与取舍见 [docs/设计说明.md](./docs/设计说明.md)。

## 功能

- **多音色 + 会话记忆**：按会话持久保存语音开关、音色、发送方式（重启不丢），互不影响。
- **多种触发**：会话级自动语音、关键词触发、LLM 工具、`/语音` 指令、语义 Skill。
- **文本绝不丢上下文**：默认「语音+文字」都发；「仅语音」时文字仍写入会话历史。
- **智能文本处理**：括号不朗读、换行/标点分段、副语言标记（换气/笑声）、可选翻译合成。
- **容错**：队列繁忙回退文字、失败退避重试 + 冷却、任何异常都不阻断文字消息。
- **精致 WebUI**：总览 / 音色库 / 会话管理 / 合成实验室 / 服务端 / 任务日志 / 配置 七页，动效 + 完整移动端适配。

## 指令

| 指令 | 作用 |
| --- | --- |
| `/语音开` | 开启本会话自动语音 |
| `/语音关` | 关闭本会话自动语音 |
| `/语音音色 [名]` | 查看/切换本会话音色 |
| `/语音状态` | 查看当前状态、服务端、冷却 |
| `/语音 <文本>` | 临时朗读一段文本（一次性） |

对话中说「以后用语音跟我交流 / 别用语音了 / 换成某某的声音」由内置 Skill 引导模型调用工具完成。

## LLM 工具

`text_to_speech`（朗读指定文本）、`set_voice_mode`（开/关语音）、`set_voice`（切音色）、`list_voices`（列音色）、`transcribe_audio`（ASR，直连网关时）。

## 快速开始

1. 部署服务：默认连 **TaskHub 中转站**（`http://127.0.0.1:9000`），中转站再连 tts_serve；也可在 WebUI「服务端」页改成直连 tts_serve 网关（`http://127.0.0.1:50001`）。**同时只启用一个服务端**。
2. 安装插件后在 WebUI「服务端」页确认服务在线、采样率正常。
3. 在「音色库」添加音色（或直接使用服务端 `/voices` 里的音色），设默认音色。
4. 在目标聊天发 `/语音开` 开启自动语音，或 `/语音 你好呀` 临时朗读。

### 服务端契约要点

- TaskHub：`POST /inference_zero_shot`（multipart `tts_text` + `prompt_wav_path`），返回裸 int16 PCM；采样率来自 `GET /`；有 `X-Queue-Position` 队列头；读超时默认 250s（吞吐 = queue_wait 120 + infer 120）。
- tts_serve 网关：合成支持 `fast_clone` 与生成参数，附 `X-Sample-Rate`；管理接口 `/api/status`、`/api/asr`、`/api/switch_backend`、`/api/vram/*`、`/api/voices/*`。
- 两者均无鉴权，请勿直接暴露到公网。

## WebUI

在 AstrBot 后台「插件 → 萌萌语音 → 管理面板」打开。页面是 Vue3 + Vite + Tailwind CSS v4 单文件产物（`pages/moe-tts/`），通过官方 Page 桥接调用后端 API。仅简体中文，无 i18n。

## 打包

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File .\build_webui.ps1   # 构建前端（改前端后必跑）
powershell -NoProfile -ExecutionPolicy Bypass -File .\build_zip.ps1     # 打包
```

产物 `dist/astrbot_plugin_moe_tts_v<版本>.zip`（套一层插件目录，含显式目录条目）。同名版本不覆盖，旧包保留便于回退。`dist/` 不入 git。

## 自检

```powershell
uv run --no-project --python 3.12 --with httpx python tests/test_core.py
uv run --no-project --python 3.12 python tests/test_webui_static.py
```

## 目录结构

```
astrbot_plugin_moe_tts/
├── main.py            Star 入口：钩子 + 指令 + LLM 工具 + 热重载
├── server.py          服务端适配：TaskHub / tts_serve + 单选路由 + 熔断重试
├── tts_engine.py      合成引擎：音色/分段/标记/翻译编排
├── textutil.py        文本纯函数
├── store.py           JSON 持久化
├── translator.py      通用翻译适配器
├── webapi.py          WebUI 后端 API
├── skills/            AstrBot 语义技能
├── webui-src/         Vue3 前端源码
├── pages/moe-tts/     前端构建产物（入库）
└── tests/             自检脚本
```
