<script setup lang="ts">
import {
  CircleHelp, Terminal, Bot, Sparkles, Settings2, Mic2, FlaskConical,
  Server, ScrollText, Info, TriangleAlert, BookOpen,
} from "lucide-vue-next";

const cmds = [
  { cmd: "/语音开", desc: "开启当前聊天的自动语音，之后机器人回复会自动朗读，重启不丢。", persist: "持久" },
  { cmd: "/语音关", desc: "关闭当前聊天的自动语音，改回纯文字回复。", persist: "持久" },
  { cmd: "/语音音色 [名]", desc: "查看可用音色列表；带名字则切换本聊天的音色。", persist: "持久" },
  { cmd: "/语音状态", desc: "查看本会话语音开关、音色、发送方式、服务端与冷却状态。", persist: "—" },
  { cmd: "/语音 <文本>", desc: "临时朗读一段文本，不开启长期语音模式。例：/语音 你好呀。", persist: "一次性" },
];
const tools = [
  { name: "text_to_speech", desc: "朗读指定文本（模型判断用户明确要念某段内容时调用）。" },
  { name: "set_voice_mode", desc: "开/关当前聊天的自动语音（用户说「以后用语音交流 / 别用语音了」）。" },
  { name: "set_voice", desc: "切换当前聊天音色（用户说「换成某某的声音」）。" },
  { name: "list_voices", desc: "列出可用音色（用户问「你有哪些声音」）。" },
  { name: "transcribe_audio", desc: "音频转文字，仅直连 tts_serve 网关时可用。" },
];
const pages = [
  { name: "总览", icon: Sparkles, desc: "服务端连通状态、任务统计、最近任务。服务端没开时会显示红色「未连通」。" },
  { name: "音色库", icon: Mic2, desc: "从服务端同步音色并存本地；点音色直接播放服务端参考音频（带缓存），试听不走克隆。" },
  { name: "会话管理", icon: Settings2, desc: "全部/私聊/群聊标签；同步机器人全部群和好友；按会话开关语音、切音色。" },
  { name: "合成实验室", icon: FlaskConical, desc: "输入文本走 TTS 克隆合成，查看波形/耗时、分段试算、下载 WAV；ASR 识别也在这里。" },
  { name: "服务端", icon: Server, desc: "配置多个服务端、单选启用；直连 tts_serve 时可切换后端、管理显存。" },
  { name: "任务日志", icon: ScrollText, desc: "合成成功/失败历史、耗时、字数、排队位置，支持筛选与搜索。" },
  { name: "配置", icon: Settings2, desc: "查看与修改插件配置，保存后立即生效并写回 AstrBot 插件配置。" },
];
</script>

<template>
  <div class="stack">
    <div class="card" style="background:linear-gradient(100deg,var(--seg-bg),transparent);border-color:var(--seg-border)">
      <div class="row">
        <BookOpen :size="20" color="var(--brand-2)" />
        <div>
          <div style="font-size:15px;font-weight:700">萌萌语音 · 使用帮助</div>
          <div style="color:var(--muted);font-size:12px;margin-top:4px">
            接入 TaskHub 中转站 / tts_serve 网关，主力模型 Qwen3-TTS（极速克隆），让机器人用可配置音色开口说话。
          </div>
        </div>
      </div>
    </div>

    <!-- 指令 -->
    <div class="card">
      <div class="card-title"><Terminal class="ico" :size="17" /> 聊天指令</div>
      <div class="stack" style="gap:9px">
        <div v-for="c in cmds" :key="c.cmd" class="row" style="gap:12px;align-items:flex-start;padding:9px 0;border-bottom:1px solid var(--border)">
          <code style="color:var(--brand-soft);background:var(--seg-bg);padding:4px 9px;border-radius:7px;font-size:12px;white-space:nowrap">{{ c.cmd }}</code>
          <div class="grow" style="font-size:12.5px;line-height:1.6;color:var(--muted)">{{ c.desc }}</div>
          <span class="badge" :class="c.persist === '持久' ? 'ok' : ''" style="font-size:10px;white-space:nowrap">{{ c.persist }}</span>
        </div>
      </div>
    </div>

    <!-- 触发方式 -->
    <div class="card">
      <div class="card-title"><Bot class="ico" :size="17" /> 触发方式</div>
      <div class="grid grid-2" style="gap:12px;font-size:13px;color:var(--muted);line-height:1.7">
        <div>• <b style="color:var(--text)">自动语音</b>：配置开启 auto_tts，或某聊天发 /语音开。</div>
        <div>• <b style="color:var(--text)">关键词</b>：消息含「念出来/读出来」时本条朗读。</div>
        <div>• <b style="color:var(--text)">自然语言</b>：说「以后用语音交流」，模型通过 Skill 自动开关。</div>
        <div>• <b style="color:var(--text)">指定文字</b>：说「这段用文字回复」本条只发文字，不改开关。</div>
        <div>• <b style="color:var(--text)">LLM 工具</b>：模型自主决定朗读/切换/列音色。</div>
        <div>• <b style="color:var(--text)">指定范围</b>：白黑名单、仅 LLM 回复，避免误念固定文案。</div>
      </div>
    </div>

    <!-- LLM 工具 -->
    <div class="card">
      <div class="card-title"><Sparkles class="ico" :size="17" /> LLM 工具</div>
      <div class="stack" style="gap:8px">
        <div v-for="t in tools" :key="t.name" class="row" style="gap:12px;padding:7px 0;border-bottom:1px solid var(--border)">
          <code style="color:var(--brand-2);font-size:12px;white-space:nowrap;min-width:150px">{{ t.name }}</code>
          <span style="font-size:12.5px;color:var(--muted);line-height:1.5">{{ t.desc }}</span>
        </div>
      </div>
    </div>

    <!-- 页面导览 -->
    <div class="card">
      <div class="card-title"><CircleHelp class="ico" :size="17" /> 页面导览</div>
      <div class="grid grid-2" style="gap:12px">
        <div v-for="p in pages" :key="p.name" class="item" style="gap:10px;align-items:flex-start">
          <component :is="p.icon" :size="17" color="var(--brand-2)" style="flex:0 0 17px;margin-top:2px" />
          <div><div style="font-weight:650;font-size:13px">{{ p.name }}</div>
               <div style="color:var(--muted);font-size:11.5px;margin-top:4px;line-height:1.5">{{ p.desc }}</div></div>
        </div>
      </div>
    </div>

    <!-- 注意事项 -->
    <div class="card" style="border-color:rgba(251,191,36,.35)">
      <div class="card-title"><TriangleAlert class="ico" :size="17" style="color:var(--warn)" /> 重要说明</div>
      <div class="stack" style="gap:10px;font-size:12.5px;color:var(--muted);line-height:1.7">
        <div><b style="color:var(--warn)">副语言标记（[breath]/[laughter]）：</b>仅 CosyVoice3 的 tokenizer 支持；主力模型 <b style="color:var(--text)">Qwen3-TTS 不支持</b>，开启会被当成文本念出英文单词。因此「自动标点换气 / 关键词音效」默认关闭，只有把后端切到 CosyVoice3 时才建议开启。</div>
        <div><b style="color:var(--text)">文本绝不丢失：</b>默认「语音 + 文字」都发；选「仅语音」时文字仍写入会话上下文，大模型下一轮和记忆插件都能拿到。</div>
        <div><b style="color:var(--text)">服务端连通：</b>总览页状态来自真实探测。默认连 TaskHub 中转站（如 9000 端口），它再转发到上游推理服务；连不上会显示红色「未连通」并给出原因。</div>
        <div><b style="color:var(--text)">音色试听：</b>音色库点击试听直接播放服务端参考音频并本地缓存，速度快、不走 GPU 克隆；想测试克隆合成请到「合成实验室」。</div>
        <div><b style="color:var(--text)">刷新保持页面：</b>当前页签会被记住，刷新 WebUI 后仍停留在原来的页面。</div>
      </div>
    </div>

    <div class="card" style="text-align:center;color:var(--faint);font-size:11.5px">
      <Info :size="14" style="vertical-align:-2px" /> 更多设计细节见仓库 docs/设计说明.md
    </div>
  </div>
</template>
