<script setup lang="ts">
import { onMounted, ref, computed } from "vue";
import { SlidersHorizontal, Info, ExternalLink, Languages } from "lucide-vue-next";
import { apiGet, apiPost } from "../api";
import { toast } from "../toast";

const config = ref<Record<string, any>>({});
const groups = ref<Record<string, string[]>>({});
const loading = ref(true);
const keyword = ref("");

// 漂亮的键名映射
const labels: Record<string, string> = {
  servers: "服务端列表", timeout: "请求超时（秒）", tts_queue_max_position: "排队阈值",
  fast_clone: "极速克隆", default_voice: "默认音色", voices: "音色备注",
  auto_tts: "自动语音", tts_scope: "语音范围", enable_llm_tool: "启用 LLM 工具",
  enable_user_trigger: "启用关键词触发", trigger_keywords: "触发关键词", text_keywords: "纯文字关键词",
  blocklist: "不转语音名单", allowlist: "仅名单内转语音", send_mode: "发送方式",
  skip_bracket_tts: "括号不朗读", auto_breath: "自动标点换气", auto_effect: "关键词音效",
  effect_intensity: "音效密度", split_by_newline: "优先按换行分段", newline_min_len: "换行段最小字数",
  segment_len: "分段字数", segment_first_len: "首段字数", segment_punct: "分段符号",
  segment_merge: "分段合并发送", max_text_len: "单段硬上限", tts_concurrency: "合成并发数",
  tts_max_retry: "失败重试次数", tts_retry_backoff: "重试退避基数", tts_cooldown_sec: "失败冷却时长",
};

const filteredGroups = computed(() => {
  const k = keyword.value.trim().toLowerCase();
  const result: Record<string, string[]> = {};
  for (const [g, keys] of Object.entries(groups.value)) {
    const matched = keys.filter((key) => !k || key.toLowerCase().includes(k) || (labels[key] || "").includes(k));
    if (matched.length) result[g] = matched;
  }
  return result;
});

function displayValue(v: any): string {
  if (v === null || v === undefined || v === "") return "（空）";
  if (typeof v === "boolean") return v ? "开启" : "关闭";
  if (Array.isArray(v)) {
    if (!v.length) return "（空）";
    return v.map((x) => typeof x === "object" ? JSON.stringify(x) : x).join("、");
  }
  if (typeof v === "object") return JSON.stringify(v);
  return String(v);
}

async function load() {
  loading.value = true;
  try {
    const r = await apiGet<{ config: Record<string, any>; schema_groups: Record<string, string[]> }>("config");
    config.value = r.config || {};
    groups.value = r.schema_groups || {};
  } catch (e: any) { toast(e?.message || "加载配置失败", "err"); }
  finally { loading.value = false; }
}
onMounted(load);
</script>

<template>
  <div class="stack">
    <div class="card" style="background:linear-gradient(100deg,rgba(124,108,255,.12),rgba(34,211,238,.05));border-color:rgba(124,108,255,.25)">
      <div class="row">
        <Info :size="18" color="var(--brand-2)" />
        <div style="font-size:13px;line-height:1.6;color:var(--text)">
          配置在 AstrBot 后台的「插件配置」弹窗中修改，保存后本页会自动同步。这里展示的是当前生效值。
          <a href="#" @click.prevent="load" style="color:var(--brand-2);text-decoration:none">点此刷新 <ExternalLink :size="12" style="vertical-align:-1px" /></a>
        </div>
      </div>
    </div>

    <div class="card">
      <div class="row wrap">
        <div class="grow" style="min-width:180px;position:relative">
          <SlidersHorizontal :size="15" style="position:absolute;left:12px;top:50%;transform:translateY(-50%);color:var(--faint)" />
          <input v-model="keyword" class="input" style="padding-left:34px" placeholder="搜索配置项…" />
        </div>
      </div>
    </div>

    <div v-if="loading" class="stack"><div v-for="i in 5" :key="i" class="skeleton" style="height:80px"></div></div>
    <template v-else>
      <div v-for="[gname, keys] in Object.entries(filteredGroups)" :key="gname" class="card">
        <div class="card-title"><Languages class="ico" :size="16" /> {{ gname }} <span class="badge" style="margin-left:auto;font-size:10px">{{ keys.length }} 项</span></div>
        <div class="grid grid-2" style="gap:10px 22px">
          <div v-for="key in keys" :key="key" class="row" style="justify-content:space-between;gap:12px;padding:7px 0;border-bottom:1px solid var(--border)">
            <div style="min-width:0">
              <div style="font-size:13px;font-weight:600">{{ labels[key] || key }}</div>
              <div style="color:var(--faint);font-size:10px">{{ key }}</div>
            </div>
            <div style="color:var(--muted);font-size:12px;text-align:right;max-width:55%;word-break:break-all">{{ displayValue(config[key]) }}</div>
          </div>
        </div>
      </div>
      <div v-if="!Object.keys(filteredGroups).length" class="card empty">没有匹配的配置项</div>
    </template>
  </div>
</template>
