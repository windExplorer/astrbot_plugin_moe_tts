<script setup lang="ts">
import { onMounted, ref, computed } from "vue";
import { ScrollText, CheckCircle2, XCircle, Search, RefreshCw, Clock3 } from "lucide-vue-next";
import { apiGet } from "../api";
import type { EventItem } from "../api";
import { toast } from "../toast";

const events = ref<EventItem[]>([]);
const stats = ref({ total: 0, ok: 0, failed: 0 });
const filter = ref<"all" | "ok" | "failed">("all");
const keyword = ref("");
const loading = ref(true);

const filtered = computed(() => {
  let list = events.value;
  if (filter.value !== "all") list = list.filter((e) => (filter.value === "ok") === e.ok);
  const k = keyword.value.trim().toLowerCase();
  if (k) list = list.filter((e) => (e.msg + e.origin + e.voice + (e.text || "") + (e.detail || "")).toLowerCase().includes(k));
  return list;
});
const successRate = computed(() => stats.value.total ? Math.round(stats.value.ok / stats.value.total * 100) : 0);

function textStateLabel(s?: string): string {
  if (!s) return "";
  if (s === "chain") return "原文随消息发送";
  if (s === "voice_only") return "仅语音 · 不发正文";
  if (s === "cancelled") return "被新消息取消 · 已补发全文";
  if (s === "send_failed") return "文字发送失败";
  if (s.startsWith("resent:")) return `已补发 ${s.split(":")[1]} 段文字`;
  return s;
}

async function load() {
  loading.value = true;
  try {
    const r = await apiGet<{ events: EventItem[]; stats: typeof stats.value }>("events", { limit: 200 });
    events.value = r.events || [];
    stats.value = r.stats || stats.value;
  } catch (e: any) { toast(e?.message || "加载失败", "err"); }
  finally { loading.value = false; }
}
onMounted(load);
</script>

<template>
  <div class="logs-page">
    <div class="logs-head">
      <div class="grid grid-4 stagger">
        <div class="stat"><div class="stat-label"><ScrollText :size="14" /> 总任务</div><div class="stat-value brand">{{ stats.total }}</div></div>
        <div class="stat"><div class="stat-label"><CheckCircle2 :size="14" /> 成功</div><div class="stat-value ok">{{ stats.ok }}</div></div>
        <div class="stat"><div class="stat-label"><XCircle :size="14" /> 失败</div><div class="stat-value" :class="stats.failed ? 'bad' : ''">{{ stats.failed }}</div></div>
        <div class="stat"><div class="stat-label"><Clock3 :size="14" /> 成功率</div><div class="stat-value ok">{{ successRate }}%</div></div>
      </div>

      <div class="card">
        <div class="row wrap">
          <div class="row" style="gap:6px">
            <button v-for="f in (['all','ok','failed'] as const)" :key="f" class="btn btn-sm" :class="filter === f ? 'btn-primary' : ''" @click="filter = f">
              {{ f === 'all' ? '全部' : f === 'ok' ? '成功' : '失败' }}
            </button>
          </div>
          <div class="grow" style="min-width:180px;position:relative">
            <Search :size="15" style="position:absolute;left:12px;top:50%;transform:translateY(-50%);color:var(--faint)" />
            <input v-model="keyword" class="input" style="padding-left:34px" placeholder="搜索会话 / 音色 / 文本 / 错误信息…" />
          </div>
          <button class="btn" @click="load"><RefreshCw :size="15" /> 刷新</button>
        </div>
      </div>
    </div>

    <div class="logs-body">
      <div v-if="loading" class="stack"><div v-for="i in 6" :key="i" class="skeleton" style="height:54px"></div></div>
      <div v-else-if="!filtered.length" class="card empty">
        <div class="empty-icon"><ScrollText :size="28" /></div>
        <div>没有匹配的日志记录</div>
      </div>
      <div v-else class="card" style="padding:8px 16px">
        <div v-for="e in filtered" :key="e.ts" class="tl-item anim-in" style="border-bottom:1px solid var(--border)">
          <div class="tl-dot" :style="{ background: e.ok ? 'var(--ok)' : 'var(--danger)' }"></div>
          <div class="grow" style="min-width:0">
            <div class="row wrap" style="gap:8px">
              <span style="font-size:13px;font-weight:600">{{ e.ok ? '成功' : '失败' }}</span>
              <span class="badge" style="font-size:10px">{{ e.kind }}</span>
              <span v-if="e.voice" class="badge brand" style="font-size:10px">{{ e.voice }}</span>
              <span style="color:var(--muted);font-size:12px;flex:1;min-width:120px;overflow:hidden;text-overflow:ellipsis;white-space:nowrap">{{ e.msg }}</span>
            </div>
            <div style="color:var(--faint);font-size:11px;margin-top:4px">
              {{ e.time }} · {{ e.chars }} 字 · {{ e.segments }} 段 · {{ (e.elapsed_ms / 1000).toFixed(1) }}s
              <span v-if="e.queue_position"> · 排队 {{ e.queue_position }}</span>
              <span v-if="e.origin"> · {{ e.origin.slice(0, 40) }}</span>
              <span v-if="e.text_state" :style="{ color: (e.text_state === 'send_failed' || e.text_state === 'cancelled') ? 'var(--danger)' : 'var(--brand-2)', fontWeight: 600 }">
                · {{ textStateLabel(e.text_state) }}
              </span>
            </div>
            <div v-if="e.detail" class="log-detail" :title="e.detail">{{ e.detail }}</div>
            <div v-if="e.text" class="log-text" :title="e.text">{{ e.text }}</div>
          </div>
        </div>
      </div>
    </div>
  </div>
</template>

<style scoped>
.logs-page { flex: 1 1 auto; min-height: 0; display: flex; flex-direction: column; }
.logs-head { flex: 0 0 auto; display: flex; flex-direction: column; gap: 16px; padding-bottom: 16px; }
.logs-body { flex: 1 1 auto; min-height: 0; overflow-y: auto; overscroll-behavior: contain; }
.log-text {
  margin-top: 6px; padding: 6px 10px; border-radius: 8px;
  background: var(--fill); color: var(--text); font-size: 12px; line-height: 1.5;
  display: -webkit-box; -webkit-line-clamp: 2; -webkit-box-orient: vertical;
  overflow: hidden; word-break: break-all;
}
.log-detail {
  margin-top: 5px; color: #c2872b; font-size: 11px; line-height: 1.45;
  overflow: hidden; text-overflow: ellipsis; white-space: nowrap;
}
</style>
