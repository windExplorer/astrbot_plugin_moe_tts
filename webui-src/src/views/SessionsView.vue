<script setup lang="ts">
import { computed, onMounted, ref } from "vue";
import {
  MessagesSquare, Search, Trash2, Volume2, Settings2, X, RefreshCw,
  MessageCircle, Users, ImageUp,
} from "lucide-vue-next";
import { apiGet, apiPost } from "../api";
import type { Session, Voice } from "../api";
import { toast } from "../toast";

interface SessionFull extends Session {
  is_group: boolean;
  group_id: string;
  user_id: string;
  group_name: string;
  avatar_id: string;
  avatar_kind: "group" | "user";
  last_active: number;
}

const sessions = ref<SessionFull[]>([]);
const voices = ref<Voice[]>([]);
const keyword = ref("");
const tab = ref<"all" | "private" | "group">("all");
const loading = ref(true);
const avatars = ref<Record<string, string>>({});
const editing = ref<SessionFull | null>(null);
const busyAvatar = ref(false);

const counts = computed(() => ({
  all: sessions.value.length,
  private: sessions.value.filter((s) => !s.is_group).length,
  group: sessions.value.filter((s) => s.is_group).length,
}));

const filtered = computed(() => {
  let list = sessions.value;
  if (tab.value !== "all") list = list.filter((s) => (tab.value === "group") === s.is_group);
  const k = keyword.value.trim().toLowerCase();
  if (k) list = list.filter((s) =>
    (s.group_name || "").toLowerCase().includes(k) ||
    (s.nickname || "").toLowerCase().includes(k) ||
    s.origin.toLowerCase().includes(k));
  return list; // 后端已按 last_active 降序排好
});

async function load() {
  loading.value = true;
  try {
    const [s, v] = await Promise.all([
      apiGet<{ sessions: SessionFull[] }>("sessions"),
      apiGet<{ voices: Voice[] }>("voices"),
    ]);
    sessions.value = s.sessions || [];
    voices.value = v.voices || [];
    await loadAvatars(false);
  } catch (e: any) { toast(e?.message || "加载失败", "err"); }
  finally { loading.value = false; }
}
onMounted(load);

async function loadAvatars(force: boolean) {
  const byKind: Record<string, string[]> = { user: [], group: [] };
  for (const s of sessions.value) {
    const kind = s.avatar_kind === "group" ? "group" : "user";
    if (s.avatar_id && !byKind[kind].includes(s.avatar_id)) byKind[kind].push(s.avatar_id);
  }
  const merged: Record<string, string> = {};
  for (const kind of ["user", "group"]) {
    if (!byKind[kind].length) continue;
    try {
      const r = await apiGet<{ items: Record<string, string> }>("avatars",
        { type: kind, ids: byKind[kind].join(","), force: force ? 1 : 0 }, 20000);
      Object.assign(merged, r.items || {});
    } catch { /* 头像失败不影响会话列表 */ }
  }
  avatars.value = merged;
}
async function refreshAvatars() {
  busyAvatar.value = true;
  try { await loadAvatars(true); toast("头像已刷新", "ok"); }
  catch (e: any) { toast(e?.message || "刷新失败", "err"); }
  finally { busyAvatar.value = false; }
}

function displayName(s: SessionFull): string {
  return s.is_group ? (s.group_name || `群 ${s.group_id}`) : (s.nickname || `用户 ${s.user_id}`);
}
function subName(s: SessionFull): string {
  return s.is_group
    ? (s.nickname ? `最近：${s.nickname}` : `群号 ${s.group_id}`)
    : `QQ ${s.user_id}`;
}
function initial(s: SessionFull): string { return displayName(s).slice(0, 1).toUpperCase(); }
function avatarSrc(s: SessionFull): string { return avatars.value[s.avatar_id] || ""; }
function activeText(ts: number): string {
  if (!ts) return "—";
  const d = Date.now() / 1000 - ts;
  if (d < 60) return "刚刚";
  if (d < 3600) return `${Math.floor(d / 60)} 分钟前`;
  if (d < 86400) return `${Math.floor(d / 3600)} 小时前`;
  if (d < 86400 * 7) return `${Math.floor(d / 86400)} 天前`;
  const dt = new Date(ts * 1000);
  return `${dt.getMonth() + 1}/${dt.getDate()}`;
}

async function toggle(s: SessionFull) {
  try {
    await apiPost("sessions/set", { origin: s.origin, on: !s.on });
    s.on = !s.on;
    toast(s.on ? "已开启语音" : "已关闭语音", "ok");
  } catch (e: any) { toast(e?.message || "操作失败", "err"); }
}
async function remove(s: SessionFull) {
  if (!confirm(`删除会话「${displayName(s)}」的语音状态？`)) return;
  try { await apiPost("sessions/delete", { origin: s.origin }); await load(); toast("已删除", "ok"); }
  catch (e: any) { toast(e?.message || "删除失败", "err"); }
}
async function clearAll() {
  if (!sessions.value.length) return;
  if (!confirm("确定清空全部会话语音状态？")) return;
  try { await apiPost("sessions/clear"); await load(); toast("已清空", "ok"); }
  catch (e: any) { toast(e?.message || "清空失败", "err"); }
}
function openEdit(s: SessionFull) { editing.value = { ...s }; }
async function saveEdit() {
  const s = editing.value;
  if (!s) return;
  try {
    await apiPost("sessions/set", { origin: s.origin, voice: s.voice, send_mode: s.send_mode,
      on: s.on, nickname: s.nickname, group_name: s.group_name });
    editing.value = null;
    await load();
    toast("已保存", "ok");
  } catch (e: any) { toast(e?.message || "保存失败", "err"); }
}
</script>

<template>
  <div class="stack">
    <div class="card">
      <div class="row wrap" style="margin-bottom:14px">
        <!-- Tabs -->
        <div class="tabs">
          <button class="tab" :class="{ active: tab === 'all' }" @click="tab = 'all'">全部 <span class="tab-count">{{ counts.all }}</span></button>
          <button class="tab" :class="{ active: tab === 'private' }" @click="tab = 'private'"><MessageCircle :size="14" /> 私聊 <span class="tab-count">{{ counts.private }}</span></button>
          <button class="tab" :class="{ active: tab === 'group' }" @click="tab = 'group'"><Users :size="14" /> 群聊 <span class="tab-count">{{ counts.group }}</span></button>
        </div>
        <span class="grow"></span>
        <button class="btn btn-sm" :disabled="busyAvatar" @click="refreshAvatars"><ImageUp :size="14" /> {{ busyAvatar ? '刷新中…' : '刷新头像' }}</button>
        <button class="btn btn-sm" @click="load"><RefreshCw :size="14" /> 刷新</button>
        <button class="btn btn-sm btn-danger" @click="clearAll"><Trash2 :size="14" /> 清空</button>
      </div>
      <div class="row wrap">
        <div class="grow" style="min-width:200px;position:relative">
          <Search :size="16" style="position:absolute;left:12px;top:50%;transform:translateY(-50%);color:var(--faint)" />
          <input v-model="keyword" class="input" style="padding-left:36px" placeholder="搜索群名 / 昵称 / 会话…" />
        </div>
      </div>
    </div>

    <div v-if="loading" class="stack"><div v-for="i in 5" :key="i" class="skeleton" style="height:72px"></div></div>
    <div v-else-if="!filtered.length" class="card empty">
      <div class="empty-icon"><MessagesSquare :size="30" /></div>
      <div>{{ sessions.length ? '没有匹配的会话' : '还没有会话语音状态。在聊天里发 /语音开 或让模型调用工具后会出现在这里。' }}</div>
    </div>
    <div v-else class="stack" style="gap:10px">
      <div v-for="s in filtered" :key="s.origin" class="item anim-in">
        <!-- 头像（群=群头像，私聊=用户头像，失败回退首字母色块） -->
        <div class="session-avatar" :class="{ group: s.is_group }">
          <img v-if="avatarSrc(s)" :src="avatarSrc(s)" :alt="displayName(s)" />
          <span v-else>{{ initial(s) }}</span>
        </div>
        <div class="grow" style="min-width:0">
          <div class="row wrap" style="gap:8px">
            <strong style="font-size:14px">{{ displayName(s) }}</strong>
            <span class="badge" :class="s.is_group ? 'cyan' : 'brand'" style="font-size:10px">
              <Users v-if="s.is_group" :size="10" /><MessageCircle v-else :size="10" />
              {{ s.is_group ? '群聊' : '私聊' }}
            </span>
            <span class="badge" :class="s.on ? 'ok' : ''" style="font-size:10px"><Volume2 :size="10" /> {{ s.on ? '语音开' : '语音关' }}</span>
          </div>
          <div style="color:var(--faint);font-size:11px;margin-top:4px;overflow:hidden;text-overflow:ellipsis;white-space:nowrap">
            {{ subName(s) }} · 音色 {{ s.voice || '默认' }} · {{ s.send_mode || '默认' }}
          </div>
        </div>
        <div style="color:var(--faint);font-size:11px;white-space:nowrap;text-align:right;min-width:52px">
          {{ activeText(s.last_active) }}
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
          <div class="row" style="gap:12px">
            <div class="field grow" v-if="editing.is_group"><label class="field-label">群名</label>
              <input v-model="editing.group_name" class="input" />
            </div>
            <div class="field grow" v-else><label class="field-label">昵称</label>
              <input v-model="editing.nickname" class="input" />
            </div>
          </div>
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

<style scoped>
.tabs { display: inline-flex; gap: 4px; padding: 4px; border-radius: 12px; background: var(--fill); border: 1px solid var(--border); }
.tab { display: inline-flex; align-items: center; gap: 6px; padding: 8px 14px; border-radius: 9px; border: 0; background: transparent; color: var(--muted); font-size: 13px; font-family: inherit; cursor: pointer; transition: background .2s, color .2s; white-space: nowrap; }
.tab:hover { color: var(--text); }
.tab.active { background: var(--surface-solid); color: var(--text); font-weight: 650; box-shadow: var(--shadow); }
.tab-count { font-size: 11px; color: var(--faint); background: var(--fill); padding: 1px 7px; border-radius: 10px; }
.session-avatar { width: 44px; height: 44px; border-radius: 13px; flex: 0 0 44px; overflow: hidden; display: grid; place-items: center; font-weight: 800; font-size: 16px; color: var(--avatar-text); background: linear-gradient(135deg, var(--brand), var(--brand-2)); }
.session-avatar.group { background: linear-gradient(135deg, var(--brand-2), var(--brand-3)); }
.session-avatar img { width: 100%; height: 100%; object-fit: cover; }
@media (max-width: 560px) { .tabs { width: 100%; } .tab { flex: 1; justify-content: center; padding: 8px 6px; } }
</style>
