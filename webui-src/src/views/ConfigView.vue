<script setup lang="ts">
import { onMounted, ref, computed } from "vue";
import { SlidersHorizontal, Info, Save, RotateCcw, Server, Mic2 } from "lucide-vue-next";
import BaseSelect from "../components/BaseSelect.vue";
import { apiGet, apiPost } from "../api";
import { toast } from "../toast";

const config = ref<Record<string, any>>({});
const original = ref<Record<string, any>>({});
const groups = ref<Record<string, string[]>>({});
const schema = ref<Record<string, any>>({});
const loading = ref(true);
const saving = ref(false);
const keyword = ref("");

const labels: Record<string, string> = {
  servers: "服务端列表", timeout: "请求超时（秒）", tts_queue_max_position: "排队阈值",
  fast_clone: "极速克隆", default_voice: "默认音色", voices: "音色备注",
  auto_tts: "自动语音", tts_probability: "语音触发概率（%）", tts_scope: "语音范围", enable_llm_tool: "启用 LLM 工具",
  enable_user_trigger: "启用关键词触发", trigger_keywords: "触发关键词", text_keywords: "纯文字关键词",
  blocklist: "不转语音名单", allowlist: "仅名单内转语音", send_mode: "发送方式",
  command_card: "指令回卡片（关=发文字）", voice_card_cols: "音色卡每行个数", card_font_path: "卡片字体路径",
  skip_bracket_tts: "括号不朗读", auto_breath: "自动标点换气", auto_effect: "关键词音效",
  effect_intensity: "音效密度", split_by_newline: "优先按换行分段", newline_min_len: "换行段最小字数",
  segment_len: "分段字数", segment_first_len: "首段字数", segment_punct: "分段符号",
  segment_merge: "分段合并发送", max_text_len: "单段硬上限", tts_concurrency: "合成并发数",
  tts_max_retry: "失败重试次数", tts_retry_backoff: "重试退避基数", tts_cooldown_sec: "失败冷却时长",
  contacts_sync_interval_min: "联系人同步间隔（分钟）", contacts_sync_timeout_sec: "联系人同步超时（秒）",
};
// 枚举值的中文展示（key -> {英文值: 中文label}）
const optionLabels: Record<string, Record<string, string>> = {
  send_mode: { both: "语音 + 文字", voice_only: "仅语音" },
  tts_scope: { llm_only: "仅大模型回复", all_text: "所有文本" },
  effect_intensity: { light: "轻量（每句≤1）", medium: "中等（每句≤3）", strong: "密集（每句≤5）" },
};
function optionsFor(key: string): { value: string; label: string }[] {
  const opts = schOptions(key);
  return opts.map((v) => ({ value: String(v), label: optionLabels[key]?.[String(v)] || String(v) }));
}
function schOptions(key: string): any[] {
  const o = schema.value[key]?.options;
  return Array.isArray(o) ? o : [];
}

const hints: Record<string, string> = {
  timeout: "TaskHub 建议 ≥250s（排队120+推理120）；直连网关可按需调小",
  tts_queue_max_position: "排队位置超过此值直接回退文字，0=不限制",
  segment_len: "格式「最小,最大」，如 30,50；0=关闭",
  segment_first_len: "首段独立窗口，让首句更快出声；0=沿用分段字数",
  tts_cooldown_sec: "服务端失败后多久内只发文字、不打服务端",
  tts_concurrency: "同时打到服务端的请求数，中转站保持 1 即可",
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
const dirty = computed(() => JSON.stringify(config.value) !== JSON.stringify(original.value));

function isListOnly(key: string): boolean { return key === "servers" || key === "voices"; }
function sch(key: string): any { return schema.value[key] || {}; }

async function load() {
  loading.value = true;
  try {
    const r = await apiGet<{ config: Record<string, any>; schema_groups: Record<string, string[]>; schema: Record<string, any> }>("config");
    config.value = JSON.parse(JSON.stringify(r.config || {}));
    original.value = JSON.parse(JSON.stringify(r.config || {}));
    groups.value = r.schema_groups || {};
    schema.value = r.schema || {};
  } catch (e: any) { toast(e?.message || "加载配置失败", "err"); }
  finally { loading.value = false; }
}
onMounted(load);

function toggleBool(key: string) { config.value[key] = !config.value[key]; }
function asList(v: any): string {
  if (Array.isArray(v)) return v.map((x) => typeof x === "object" ? JSON.stringify(x) : x).join(", ");
  return v == null ? "" : String(v);
}
function setList(key: string, val: string) {
  config.value[key] = val.split(",").map((s) => s.trim()).filter(Boolean);
}

async function save() {
  saving.value = true;
  try {
    // 只提交发生变化的键，跳过在专门页面维护的 servers / voices
    const changed: Record<string, any> = {};
    for (const k of Object.keys(config.value)) {
      if (isListOnly(k)) continue;
      if (JSON.stringify(config.value[k]) !== JSON.stringify(original.value[k])) changed[k] = config.value[k];
    }
    if (!Object.keys(changed).length) { toast("没有需要保存的改动", "info"); return; }
    await apiPost("config/save", changed, 20000);
    toast("配置已保存并生效", "ok");
    await load();
  } catch (e: any) { toast(e?.message || "保存失败", "err"); }
  finally { saving.value = false; }
}
function reset() { config.value = JSON.parse(JSON.stringify(original.value)); toast("已撤销未保存的改动", "info"); }
</script>

<template>
  <div class="stack" :class="{ 'with-save-float': dirty }">
    <div class="card" style="background:linear-gradient(100deg,var(--seg-bg),transparent);border-color:var(--seg-border)">
      <div class="row wrap">
        <Info :size="18" color="var(--brand-2)" />
        <div style="font-size:13px;line-height:1.6;flex:1;min-width:200px">
          这里修改后点「保存更改」立即生效，并写回 AstrBot 插件配置（与官方配置弹窗双向一致）。
          服务端列表与音色库请在对应页面编辑。
        </div>
        <button class="btn btn-sm" @click="load"><RotateCcw :size="14" /> 刷新</button>
      </div>
    </div>

    <!-- 悬浮保存条：有未保存改动时固定在视口底部，滚动到任意位置都能保存 -->
    <div v-if="dirty" class="save-float">
      <span style="font-size:13px;color:var(--brand-soft);font-weight:600;white-space:nowrap">有未保存的改动</span>
      <span class="grow"></span>
      <button class="btn btn-sm" @click="reset">撤销</button>
      <button class="btn btn-primary btn-sm" :disabled="saving" @click="save"><Save :size="14" /> {{ saving ? '保存中…' : '保存更改' }}</button>
    </div>

    <div class="card">
      <div class="row" style="position:relative">
        <SlidersHorizontal :size="15" style="position:absolute;left:12px;top:50%;transform:translateY(-50%);color:var(--faint)" />
        <input v-model="keyword" class="input" style="padding-left:34px" placeholder="搜索配置项…" />
      </div>
    </div>

    <div v-if="loading" class="stack"><div v-for="i in 5" :key="i" class="skeleton" style="height:80px"></div></div>
    <template v-else>
      <div v-for="[gname, keys] in Object.entries(filteredGroups)" :key="gname" class="card">
        <div class="card-title">{{ gname }} <span class="badge" style="margin-left:auto;font-size:10px">{{ keys.length }} 项</span></div>
        <div class="grid grid-2" style="gap:14px 24px">
          <div v-for="key in keys" :key="key" class="field" style="padding:8px 0;border-bottom:1px solid var(--border)">
            <div class="row" style="justify-content:space-between;gap:8px">
              <div style="min-width:0">
                <div style="font-size:13px;font-weight:600">{{ labels[key] || key }}</div>
                <div style="color:var(--faint);font-size:10px">{{ key }}</div>
              </div>
              <span v-if="isListOnly(key)" class="badge brand" style="font-size:10px">
                <component :is="key === 'servers' ? Server : Mic2" :size="10" /> {{ key === 'servers' ? '服务端页' : '音色库页' }}
              </span>
            </div>

            <!-- 专门页维护：只读展示 -->
            <template v-if="isListOnly(key)">
              <div style="color:var(--muted);font-size:12px;margin-top:6px">
                {{ Array.isArray(config[key]) ? `${config[key].length} 项` : '—' }}（请在对应页面编辑）
              </div>
            </template>

            <!-- bool 开关 -->
            <template v-else-if="sch(key).type === 'bool'">
              <button class="switch" :class="{ on: config[key] }" style="align-self:flex-start;margin-top:8px" @click="toggleBool(key)"></button>
            </template>

            <!-- options 下拉 -->
            <template v-else-if="schOptions(key).length">
              <div style="margin-top:6px"><BaseSelect v-model="config[key]" :options="optionsFor(key)" /></div>
            </template>

            <!-- 数字 -->
            <template v-else-if="sch(key).type === 'int' || sch(key).type === 'float'">
              <input v-model="config[key]" :type="sch(key).type === 'int' ? 'number' : 'number'" step="any" class="input" style="margin-top:6px" />
            </template>

            <!-- 字符串列表 -->
            <template v-else-if="sch(key).type === 'list'">
              <input :value="asList(config[key])" @input="setList(key, ($event.target as HTMLInputElement).value)" class="input" style="margin-top:6px" placeholder="多个值用逗号分隔" />
            </template>

            <!-- 字符串 -->
            <template v-else>
              <input v-model="config[key]" class="input" style="margin-top:6px" :placeholder="sch(key).hint || ''" />
            </template>

            <div v-if="hints[key] || sch(key).hint" style="color:var(--faint);font-size:11px;margin-top:5px;line-height:1.5">
              {{ hints[key] || sch(key).hint }}
            </div>
          </div>
        </div>
      </div>
      <div v-if="!Object.keys(filteredGroups).length" class="card empty">没有匹配的配置项</div>
    </template>
  </div>
</template>

<style scoped>
.with-save-float { padding-bottom: 96px; }
@media (max-width: 900px) { .with-save-float { padding-bottom: 130px; } }
.save-float {
  position: fixed;
  right: 30px;
  bottom: 26px;
  z-index: 60;
  display: flex;
  align-items: center;
  gap: 12px;
  width: min(440px, calc(100vw - 32px));
  padding: 12px 16px;
  border: 1px solid var(--item-active-border);
  border-radius: 14px;
  background: var(--surface-solid);
  backdrop-filter: blur(14px);
  box-shadow: 0 12px 36px rgba(0, 0, 0, .28);
  animation: saveFloatIn .25s ease both;
}
@keyframes saveFloatIn {
  from { opacity: 0; transform: translateY(14px); }
  to { opacity: 1; transform: translateY(0); }
}
@media (max-width: 900px) {
  .save-float {
    left: 16px;
    right: 16px;
    bottom: calc(64px + env(safe-area-inset-bottom) + 12px);
    width: auto;
  }
}
</style>
