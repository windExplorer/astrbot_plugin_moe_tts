<script setup lang="ts">
import { onMounted, ref } from "vue";
import {
  Activity, Mic2, CheckCircle2, XCircle, Radio, Zap, ArrowRight,
  Server as ServerIcon, Clock3, AlertTriangle, Sparkles,
} from "lucide-vue-next";
import { apiGet } from "../api";
import type { Overview } from "../api";
import { toast } from "../toast";
import { PLUGIN_VERSION } from "../version";

const emit = defineEmits<{ navigate: [key: string] }>();
const data = ref<Overview | null>(null);
const loading = ref(true);

async function load() {
  loading.value = true;
  try {
    data.value = await apiGet<Overview>("overview", undefined, 12000);
  } catch (e: any) {
    toast(e?.message || "加载总览失败", "err");
  } finally {
    loading.value = false;
  }
}
onMounted(load);

function statusColor() {
  if (!data.value?.ready) return "danger";
  if (data.value.server?.in_cooldown) return "warn";
  return "ok";
}
</script>

<template>
  <div class="stack">
    <!-- 服务状态横幅 -->
    <div v-if="loading" class="card">
      <div class="row"><div class="skeleton" style="width:120px;height:20px"></div></div>
      <div class="grid grid-4" style="margin-top:18px">
        <div v-for="i in 4" :key="i" class="skeleton" style="height:96px"></div>
      </div>
    </div>
    <template v-else-if="data">
      <div class="card anim-pop" style="padding:0;overflow:hidden">
        <div style="height:3px;background:linear-gradient(90deg,var(--brand),var(--brand-2),var(--brand-3))"></div>
        <div class="row" style="padding:18px 20px">
          <div class="avatar" style="width:48px;height:48px;flex-basis:48px">
            <Radio :size="24" />
          </div>
          <div class="grow">
            <div class="row" style="gap:10px">
              <strong style="font-size:15px">{{ data.server?.name || '未配置服务端' }}</strong>
              <span class="badge" :class="statusColor()">
                <span class="dot" :class="statusColor()"></span>
                {{ !data.ready ? '未连通' : (data.server?.in_cooldown ? '冷却中' : '在线') }}
              </span>
              <span v-if="data.active_type" class="badge brand">{{ data.active_type === 'taskhub' ? 'TaskHub 中转站' : 'tts_serve 网关' }}</span>
            </div>
            <div style="color:var(--muted);font-size:12px;margin-top:6px">
              {{ data.server?.url || '请在「服务端」页添加一个语音服务端' }}
              <span v-if="data.server"> · {{ data.server.sample_rate }} Hz</span>
            </div>
            <div v-if="data.server?.health_error" class="row" style="gap:6px;margin-top:6px;color:var(--danger);font-size:12px">
              <AlertTriangle :size="13" /> 连接失败：{{ data.server.health_error.slice(0, 100) }}
            </div>
            <div v-else-if="data.server?.last_error" class="row" style="gap:6px;margin-top:6px;color:var(--warn);font-size:12px">
              <AlertTriangle :size="13" /> {{ data.server.last_error.slice(0, 80) }}
            </div>
          </div>
          <button class="btn btn-sm" @click="emit('navigate','servers')">
            管理服务端 <ArrowRight :size="14" />
          </button>
        </div>
      </div>

      <!-- 统计卡 -->
      <div class="grid grid-4 stagger">
        <div class="stat">
          <div class="stat-label"><Activity :size="14" /> 合成任务总数</div>
          <div class="stat-value brand">{{ data.stats.total }}</div>
        </div>
        <div class="stat">
          <div class="stat-label"><CheckCircle2 :size="14" /> 成功</div>
          <div class="stat-value ok">{{ data.stats.ok }}</div>
        </div>
        <div class="stat">
          <div class="stat-label"><XCircle :size="14" /> 失败</div>
          <div class="stat-value" :class="data.stats.failed ? 'bad' : ''">{{ data.stats.failed }}</div>
        </div>
        <div class="stat">
          <div class="stat-label"><Mic2 :size="14" /> 音色数量</div>
          <div class="stat-value">{{ data.voices_count }}</div>
        </div>
      </div>

      <!-- 快捷操作 + 配置速览 -->
      <div class="grid grid-2">
        <div class="card">
          <div class="card-title"><Zap class="ico" :size="17" /> 快捷开始</div>
          <div class="stack" style="gap:12px">
            <div class="item" style="cursor:pointer" @click="emit('navigate','lab')">
              <div class="avatar"><Sparkles :size="18" /></div>
              <div class="grow">
                <div style="font-weight:650">合成实验室</div>
                <div style="color:var(--muted);font-size:12px;margin-top:2px">输入文本，立即试听音色效果</div>
              </div>
              <ArrowRight :size="16" color="var(--muted)" />
            </div>
            <div class="item" style="cursor:pointer" @click="emit('navigate','voices')">
              <div class="avatar"><Mic2 :size="18" /></div>
              <div class="grow">
                <div style="font-weight:650">音色库</div>
                <div style="color:var(--muted);font-size:12px;margin-top:2px">{{ data.voices_count }} 个音色 · 默认 {{ data.default_voice || '未设置' }}</div>
              </div>
              <ArrowRight :size="16" color="var(--muted)" />
            </div>
          </div>
        </div>
        <div class="card">
          <div class="card-title"><ServerIcon class="ico" :size="17" /> 运行配置</div>
          <div class="stack" style="gap:11px;font-size:13px">
            <div class="row" style="justify-content:space-between">
              <span style="color:var(--muted)">自动语音</span>
              <span class="badge" :class="data.auto_tts ? 'ok' : ''">{{ data.auto_tts ? '已开启' : '已关闭' }}</span>
            </div>
            <div class="row" style="justify-content:space-between">
              <span style="color:var(--muted)">发送方式</span>
              <span class="badge cyan">{{ data.send_mode === 'both' ? '语音 + 文字' : '仅语音' }}</span>
            </div>
            <div class="row" style="justify-content:space-between">
              <span style="color:var(--muted)">会话数</span>
              <span>{{ data.session_count }}</span>
            </div>
            <div class="row" style="justify-content:space-between">
              <span style="color:var(--muted)">插件版本</span>
              <span class="badge brand">{{ PLUGIN_VERSION }}</span>
            </div>
            <button class="btn btn-sm" style="margin-top:4px" @click="load">刷新状态</button>
          </div>
        </div>
      </div>

      <!-- 最近任务 -->
      <div class="card">
        <div class="card-title">
          <Clock3 class="ico" :size="17" /> 最近任务
          <button class="btn btn-ghost btn-sm" style="margin-left:auto" @click="emit('navigate','logs')">查看全部 <ArrowRight :size="13" /></button>
        </div>
        <div v-if="!data.recent.length" class="empty">
          <div class="empty-icon"><Mic2 :size="28" /></div>
          <div>还没有语音任务，去合成实验室试试吧～</div>
        </div>
        <div v-else class="timeline">
          <div v-for="e in data.recent.slice(0, 6)" :key="e.ts" class="tl-item anim-in">
            <div class="tl-dot" :style="{ background: e.ok ? 'var(--ok)' : 'var(--danger)' }"></div>
            <div class="grow">
              <div class="row" style="gap:8px">
                <span style="font-size:13px;color:var(--text)">{{ e.ok ? '合成成功' : '合成失败' }}</span>
                <span class="badge" style="font-size:10px">{{ (e.msg || '').slice(0, 30) }}</span>
              </div>
              <div style="color:var(--faint);font-size:11px;margin-top:3px">
                {{ e.time }} · {{ e.chars }} 字 · {{ e.segments }} 段 · {{ (e.elapsed_ms / 1000).toFixed(1) }}s
                <span v-if="e.queue_position"> · 排队 {{ e.queue_position }}</span>
              </div>
            </div>
          </div>
        </div>
      </div>
    </template>
  </div>
</template>
