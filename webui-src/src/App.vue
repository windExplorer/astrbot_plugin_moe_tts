<script setup lang="ts">
import { computed, onMounted, onUnmounted, ref } from "vue";
import {
  AudioLines, LayoutDashboard, Mic2, MessagesSquare, FlaskConical,
  Server, ScrollText, SlidersHorizontal, Radio, X, CheckCircle2, AlertCircle, Info,
  Sun, Moon,
} from "lucide-vue-next";
import { toasts } from "./toast";
import { PLUGIN_VERSION } from "./version";
import OverviewView from "./views/OverviewView.vue";
import VoicesView from "./views/VoicesView.vue";
import SessionsView from "./views/SessionsView.vue";
import LabView from "./views/LabView.vue";
import ServersView from "./views/ServersView.vue";
import LogsView from "./views/LogsView.vue";
import ConfigView from "./views/ConfigView.vue";

const routes = [
  { key: "overview", label: "总览", icon: LayoutDashboard, comp: OverviewView },
  { key: "voices", label: "音色库", icon: Mic2, comp: VoicesView },
  { key: "sessions", label: "会话管理", icon: MessagesSquare, comp: SessionsView },
  { key: "lab", label: "合成实验室", icon: FlaskConical, comp: LabView },
  { key: "servers", label: "服务端", icon: Server, comp: ServersView },
  { key: "logs", label: "任务日志", icon: ScrollText, comp: LogsView },
  { key: "config", label: "配置", icon: SlidersHorizontal, comp: ConfigView },
];

const current = ref("overview");
const comp = computed(() => routes.find((r) => r.key === current.value)?.comp || OverviewView);
const title = computed(() => routes.find((r) => r.key === current.value)?.label || "总览");
const desc: Record<string, string> = {
  overview: "服务状态、快捷操作与最近的语音任务",
  voices: "管理可用音色、语种与试听",
  sessions: "按会话开关语音、切换音色与发送方式",
  lab: "输入文本即时合成试听，查看波形与耗时",
  servers: "配置服务端地址，切换 TaskHub 中转站 / tts_serve 网关",
  logs: "查看合成任务历史与成功/失败统计",
  config: "查看与修改插件配置，保存后立即生效并写回 AstrBot",
};

// 主题：dark / light，持久化到 localStorage
const theme = ref<"dark" | "light">("dark");
function applyTheme(t: "dark" | "light") {
  theme.value = t;
  document.documentElement.setAttribute("data-theme", t);
  try { localStorage.setItem("moe-tts-theme", t); } catch { /* ignore */ }
}
function toggleTheme() { applyTheme(theme.value === "dark" ? "light" : "dark"); }

const PAGE_KEY = "moe-tts-page";
function validKey(key: string): boolean { return routes.some((r) => r.key === key); }

function go(key: string) {
  current.value = key;
  location.hash = "#/" + key;
  // AstrBot 插件页在 iframe 里，刷新时 hash 可能丢失；同步记到 localStorage 兜底
  try { localStorage.setItem(PAGE_KEY, key); } catch { /* ignore */ }
}
function onHash() {
  const key = location.hash.replace(/^#\/?/, "");
  if (key && validKey(key)) {
    current.value = key;
    try { localStorage.setItem(PAGE_KEY, key); } catch { /* ignore */ }
    return;
  }
  // hash 为空/无效：从 localStorage 恢复上次页签，而不是一律回总览
  let saved = "";
  try { saved = localStorage.getItem(PAGE_KEY) || ""; } catch { /* ignore */ }
  current.value = validKey(saved) ? saved : "overview";
}
onMounted(() => {
  onHash();
  window.addEventListener("hashchange", onHash);
  let saved = "";
  try { saved = localStorage.getItem("moe-tts-theme") || ""; } catch { /* ignore */ }
  applyTheme(saved === "light" ? "light" : "dark");
});
onUnmounted(() => window.removeEventListener("hashchange", onHash));

const toastIcon = { ok: CheckCircle2, err: AlertCircle, info: Info };
</script>

<template>
  <div class="app-shell">
    <!-- 侧边栏 -->
    <aside class="sidebar">
      <div class="brand">
        <div class="brand-logo"><AudioLines :size="22" :stroke-width="2.4" /></div>
        <div>
          <div class="brand-title">萌萌语音</div>
          <div class="brand-sub">Moe TTS Console</div>
        </div>
      </div>
      <nav class="nav">
        <div v-for="r in routes" :key="r.key" class="nav-item" :class="{ active: current === r.key }" @click="go(r.key)">
          <component :is="r.icon" :size="18" :stroke-width="2" />
          <span class="nav-label">{{ r.label }}</span>
        </div>
      </nav>
      <div class="side-foot">
        <span class="version-pill"><span class="dot"></span> {{ PLUGIN_VERSION }}</span>
        <button class="theme-btn" @click="toggleTheme" :title="theme === 'dark' ? '切换到浅色主题' : '切换到深色主题'">
          <Sun v-if="theme === 'dark'" :size="15" />
          <Moon v-else :size="15" />
        </button>
      </div>
    </aside>

    <!-- 主内容 -->
    <main class="main">
      <header class="page-head anim-up">
        <div class="row" style="justify-content:space-between;align-items:flex-start">
          <div>
            <h1 class="page-title">{{ title }}</h1>
            <div class="page-desc">{{ desc[current] }}</div>
          </div>
          <button class="btn btn-icon theme-btn-mobile" @click="toggleTheme" :title="theme === 'dark' ? '浅色主题' : '深色主题'">
            <Sun v-if="theme === 'dark'" :size="18" />
            <Moon v-else :size="18" />
          </button>
        </div>
      </header>
      <Transition name="page" mode="out-in">
        <component :is="comp" :key="current" @navigate="go" />
      </Transition>
    </main>

    <!-- 移动端底部导航 -->
    <nav class="mobile-nav">
      <div v-for="r in routes" :key="r.key" class="mnav-item" :class="{ active: current === r.key }" @click="go(r.key)">
        <component :is="r.icon" :size="20" :stroke-width="2" />
        <span>{{ r.label }}</span>
      </div>
    </nav>

    <!-- 全局 Toast -->
    <div class="toast-wrap">
      <Transition group name="page">
        <div v-for="t in toasts" :key="t.id" class="toast" :class="t.type">
          <component :is="toastIcon[t.type]" :size="17" :class="t.type === 'ok' ? 'text-ok' : t.type === 'err' ? 'text-danger' : ''" />
          <span>{{ t.text }}</span>
        </div>
      </Transition>
    </div>
  </div>
</template>

<style scoped>
.text-ok { color: var(--ok); }
.text-danger { color: var(--danger); }
.side-foot { display: flex; align-items: center; justify-content: space-between; gap: 8px; }
.theme-btn {
  display: inline-flex; align-items: center; justify-content: center;
  width: 30px; height: 30px; flex: 0 0 30px; border-radius: 9px;
  border: 1px solid var(--border); background: var(--fill);
  color: var(--muted); cursor: pointer;
  transition: background .2s, color .2s, border-color .2s, transform .2s;
}
.theme-btn:hover { background: var(--btn-hover); color: var(--brand-2); border-color: var(--border-hi); transform: rotate(-15deg); }
.theme-btn-mobile { display: none; }
@media (max-width: 900px) { .theme-btn-mobile { display: inline-flex; flex: 0 0 34px; } }
</style>
