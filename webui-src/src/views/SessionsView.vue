<script setup lang="ts">
import { computed, onMounted, ref } from "vue";
import { MessagesSquare, Search, Trash2, Volume2, Settings2, X, RefreshCw } from "lucide-vue-next";
import { apiGet, apiPost } from "../api";
import type { Session, Voice } from "../api";
import { toast } from "../toast";

const sessions = ref<Session[]>([]);
const voices = ref<Voice[]>([]);
const keyword = ref("");
const loading = ref(true);
const editing = ref<Session | null>(null);

const filtered = computed(() => {
  const k = keyword.value.trim().toLowerCase();
  if (!k) return sessions.value;
  return sessions.value.filter((s) =>
    (s.nickname || "").toLowerCase().includes(k) ||
    (s.group || "").toLowerCase().includes(k) ||
    s.origin.toLowerCase().includes(k));
});

async function load() {
  loading.value = true;
  try {
    const [s, v] = await Promise.all([
      apiGet<{ sessions: Session[] }>("sessions"),
      apiGet<{ voices: Voice[] }>("voices"),
    ]);
    sessions.value = s.sessions || [];
    voices.value = v.voices || [];
  } catch (e: any) { toast(e?.message || "加载失败", "err"); }
  finally { loading.value = false; }
}
onMounted(load);

function shortOrigin(origin: string): string {
  // aiocqhttp:GroupMessage:123456 -> 群 123456
  const parts = origin.split(":");
  const kind = parts[1] || "";
  const id = parts[parts.length - 1] || "";
  const label = /group/i.test(kind) ? "群" : /private|friend/i.test(kind) ? "私聊" : kind;
  return `${label} ${id}`.trim();
}
function initial(s: Session): string {
  return (s.nickname || s.group || "?").slice(0, 1).toUpperCase();
}
async function toggle(s: Session) {
  try {
    await apiPost("sessions/set", { origin: s.origin, on: !s.on });
    s.on = !s.on;
    toast(s.on ? "已开启语音" : "已关闭语音", "ok");
  } catch (e: any) { toast(e?.message || "操作失败", "err"); }
}
async function remove(s: Session) {
  if (!confirm(`删除会话「${s.nickname || shortOrigin(s.origin)}」的语音状态？`)) return;
  try { await apiPost("sessions/delete", { origin: s.origin }); await load(); toast("已删除", "ok"); }
  catch (e: any) { toast(e?.message || "删除失败", "err"); }
}
async function clearAll() {
  if (!sessions.value.length) return;
  if (!confirm("确定清空全部会话语音状态？")) return;
  try { await apiPost("sessions/clear"); await load(); toast("已清空", "ok"); }
  catch (e: any) { toast(e?.message || "清空失败", "err"); }
}
function openEdit(s: Session) { editing.value = { ...s }; }
async function saveEdit() {
  const s = editing.value;
  if (!s) return;
  try {
    await apiPost("sessions/set", { origin: s.origin, voice: s.voice, send_mode: s.send_mode, on: s.on });
    editing.value = null;
    await load();
    toast("已保存", "ok");
  } catch (e: any) { toast(e?.message || "保存失败", "err"); }
}
</script>

<template>
  <div class="stack">
    <div class="card">
      <div class="row wrap">
        <div class="grow" style="min-width:200px;position:relative">
          <Search :size="16" style="position:absolute;left:12px;top:50%;transform:translateY(-50%);color:var(--faint)" />
          <input v-model="keyword" class="input" style="padding-left:36px" placeholder="搜索昵称 / 群 / 会话…" />
        </div>
        <button class="btn" @click="load"><RefreshCw :size="15" /> 刷新</button>
        <button class="btn btn-danger" @click="clearAll"><Trash2 :size="15" /> 清空</button>
      </div>
    </div>

    <div v-if="loading" class="stack">
      <div v-for="i in 4" :key="i" class="skeleton" style="height:66px"></div>
    </div>
    <div v-else-if="!filtered.length" class="card empty">
      <div class="empty-icon"><MessagesSquare :size="30" /></div>
      <div>{{ sessions.length ? '没有匹配的会话' : '还没有会话语音状态。在聊天里发 /语音开 或让模型调用工具后会出现在这里。' }}</div>
    </div>
    <div v-else class="stack" style="gap:10px">
      <div v-for="s in filtered" :key="s.origin" class="item anim-in">
        <div class="avatar">{{ initial(s) }}</div>
        <div class="grow" style="min-width:0">
          <div class="row" style="gap:8px">
            <strong style="font-size:14px">{{ s.nickname || s.group || '未命名会话' }}</strong>
            <span class="badge" :class="s.on ? 'ok' : ''" style="font-size:10px"><Volume2 :size="10" /> {{ s.on ? '语音开' : '语音关' }}</span>
          </div>
          <div style="color:var(--faint);font-size:11px;margin-top:4px;overflow:hidden;text-overflow:ellipsis;white-space:nowrap">
            {{ shortOrigin(s.origin) }} · 音色 {{ s.voice || '默认' }} · {{ s.send_mode || '默认' }} · {{ s.updated }}
          </div>
        </div>
        <button class="switch" :class="{ on: s.on }" @click="toggle(s)"></button>
        <button class="btn btn-sm btn-icon" title="编辑" @click="openEdit(s)"><Settings2 :size="15" /></button>
        <button class="btn btn-sm btn-icon btn-danger" title="删除" @click="remove(s)"><Trash2 :size="14" /></button>
      </div>
    </div>

    <div v-if="editing" class="mask" @click.self="editing = null">
      <div class="modal anim-pop">
        <div class="modal-head">
          <div class="modal-title">编辑会话语音状态</div>
          <button class="btn btn-ghost btn-icon" @click="editing = null"><X :size="18" /></button>
        </div>
        <div class="stack">
          <div class="field"><label class="field-label">会话</label><input class="input" :value="editing.origin" disabled /></div>
          <div class="field"><label class="field-label">音色</label>
            <select v-model="editing.voice" class="select">
              <option value="">跟随默认</option>
              <option v-for="v in voices" :key="v.name" :value="v.name">{{ v.name }}</option>
            </select>
          </div>
          <div class="field"><label class="field-label">发送方式</label>
            <select v-model="editing.send_mode" class="select">
              <option value="">跟随全局</option>
              <option value="both">语音 + 文字</option>
              <option value="voice_only">仅语音</option>
            </select>
          </div>
          <div class="row" style="justify-content:space-between">
            <span>自动语音</span><button class="switch" :class="{ on: editing.on }" @click="editing.on = !editing.on"></button>
          </div>
          <div class="row" style="margin-top:8px">
            <button class="btn grow" @click="editing = null">取消</button>
            <button class="btn btn-primary grow" @click="saveEdit">保存</button>
          </div>
        </div>
      </div>
    </div>
  </div>
</template>
