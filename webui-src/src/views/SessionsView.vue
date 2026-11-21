<script setup lang="ts">
import { computed, onMounted, ref } from "vue";
import {
  MessagesSquare, Search, Trash2, Volume2, Settings2, X, RefreshCw,
  MessageCircle, Users, ImageUp, CloudDownload, AlertTriangle,
} from "lucide-vue-next";
import BaseSelect from "../components/BaseSelect.vue";
import { apiGet, apiPost } from "../api";
import type { Session, Voice } from "../api";
import { toast } from "../toast";

const SEND_OPTIONS = [
  { value: "", label: "跟随全局" }, { value: "both", label: "语音 + 文字" },
  { value: "voice_only", label: "仅语音" },
];

interface SessionFull extends Session {
  is_group: boolean;
  group_id: string;
  user_id: string;
  group_name: string;
  avatar_id: string;
  avatar_kind: "group" | "user";
  last_active: number;
  has_state: boolean;
}
interface Contact { id: string; name: string; nickname?: string; remark?: string; platform?: string }
interface ContactsData {
  friends: Contact[];
  groups: Contact[];
  meta: { synced_at: string; platforms: number; friends: number; groups: number; error: string };
}

const rawSessions = ref<SessionFull[]>([]);
const contacts = ref<ContactsData>({ friends: [], groups: [], meta: { synced_at: "", platforms: 0, friends: 0, groups: 0, error: "" } });
const voices = ref<Voice[]>([]);
const VOICE_OPTIONS = computed(() => [
  { value: "", label: "跟随默认" },
  ...voices.value.map((v) => ({ value: v.name, label: v.name })),
]);
const keyword = ref("");
const tab = ref<"all" | "private" | "group">("all");
const loading = ref(true);
const syncingContacts = ref(false);
const avatars = ref<Record<string, string>>({});
const editing = ref<SessionFull | null>(null);
const busyAvatar = ref(false);

// 合并：以全量联系人为基础，叠加会话语音状态；未有状态的显示「未启用」，可一键开启
const sessions = computed<SessionFull[]>(() => {
  const map = new Map<string, SessionFull>();
  for (const s of rawSessions.value) map.set(s.origin, { ...s, has_state: true });

  const merged: SessionFull[] = [];
  // 群联系人
  for (const g of contacts.value.groups) {
    const origin = `aiocqhttp:GroupMessage:${g.id}`;
    const exist = map.get(origin);
    if (exist) { merged.push(exist); map.delete(origin); }
    else {
      merged.push({
        origin, on: false, prob: 100, has_prob: false, voice: "", send_mode: "", is_group: true,
        group_id: g.id, user_id: "", group_name: g.name, nickname: "",
        avatar_id: g.id, avatar_kind: "group", last_active: 0,
        updated: "", has_state: false,
      });
    }
  }
  // 好友联系人
  for (const f of contacts.value.friends) {
    const origin = `aiocqhttp:FriendMessage:${f.id}`;
    const exist = map.get(origin);
    if (exist) { merged.push(exist); map.delete(origin); }
    else {
      merged.push({
        origin, on: false, prob: 100, has_prob: false, voice: "", send_mode: "", is_group: false,
        group_id: "", user_id: f.id, group_name: "", nickname: f.name || f.nickname || f.id,
        avatar_id: f.id, avatar_kind: "user", last_active: 0,
        updated: "", has_state: false,
      });
    }
  }
  // 剩余有语音状态但不在联系人快照里的会话（其它平台/历史数据）
  for (const s of map.values()) merged.push(s);

  // 活跃优先：有语音状态/活跃的排前面，其余按名称
  merged.sort((a, b) => {
    if (a.last_active !== b.last_active) return b.last_active - a.last_active;
    if (a.has_state !== b.has_state) return a.has_state ? -1 : 1;
    return displayName(a).localeCompare(displayName(b), "zh");
  });
  return merged;
});

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
  return list;
});

async function load() {
  loading.value = true;
  try {
    const [s, c, v] = await Promise.all([
      apiGet<{ sessions: SessionFull[] }>("sessions"),
      apiGet<ContactsData>("contacts").catch(() => null),
      apiGet<{ voices: Voice[] }>("voices"),
    ]);
    rawSessions.value = s.sessions || [];
    contacts.value = c || contacts.value;
    voices.value = v.voices || [];
    await loadAvatars(false);
  } catch (e: any) { toast(e?.message || "加载失败", "err"); }
  finally { loading.value = false; }
}
onMounted(load);

async function syncContacts() {
  syncingContacts.value = true;
  try {
    const r = await apiPost<{ ok: boolean; friends: number; groups: number; error: string }>("contacts/sync", {}, 60000);
    if (r.ok) toast(`已同步 ${r.groups} 个群、${r.friends} 位好友`, "ok");
    else toast(r.error || "同步失败（可能未连接 aiocqhttp）", "err");
    await load();
  } catch (e: any) { toast(e?.message || "同步失败", "err"); }
  finally { syncingContacts.value = false; }
}

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
    ? `群号 ${s.group_id}`
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

// 把改动写回源数据 rawSessions，让 sessions computed 立即重算刷新列表。
// 注意 s 可能来自 computed 生成的临时对象，直接改它不会反映到列表。
function upsertLocalSession(s: SessionFull, changes: Partial<SessionFull>) {
  const idx = rawSessions.value.findIndex((x) => x.origin === s.origin);
  const base: SessionFull = idx >= 0 ? rawSessions.value[idx] : { ...s };
  const next: SessionFull = { ...base, ...changes, has_state: true,
    updated: new Date().toLocaleString("zh-CN", { hour12: false }) };
  if (idx >= 0) rawSessions.value[idx] = next;
  else rawSessions.value.push(next);
  return next;
}

async function toggle(s: SessionFull) {
  const newOn = !s.on;
  try {
    await apiPost("sessions/set", { origin: s.origin, on: newOn });
    upsertLocalSession(s, { on: newOn });
    toast(newOn ? `已开启「${displayName(s)}」的语音` : "已关闭语音", "ok");
  } catch (e: any) { toast(e?.message || "操作失败", "err"); }
}
async function remove(s: SessionFull) {
  if (!confirm(`删除「${displayName(s)}」的语音状态？`)) return;
  try { await apiPost("sessions/delete", { origin: s.origin }); await load(); toast("已删除", "ok"); }
  catch (e: any) { toast(e?.message || "删除失败", "err"); }
}
async function clearAll() {
  if (!rawSessions.value.length) return;
  if (!confirm("确定清空全部会话语音状态？")) return;
  try { await apiPost("sessions/clear"); await load(); toast("已清空", "ok"); }
  catch (e: any) { toast(e?.message || "清空失败", "err"); }
}
function openEdit(s: SessionFull) { editing.value = { ...s, prob: s.has_prob ? Math.round(s.prob) : 0 }; }
async function saveEdit() {
  const s = editing.value;
  if (!s) return;
  let prob = Number(s.prob);
  if (!Number.isFinite(prob) || prob < 0) prob = 0;
  prob = Math.min(100, Math.round(prob));
  try {
    await apiPost("sessions/set", { origin: s.origin, voice: s.voice, send_mode: s.send_mode,
      on: s.on, prob, nickname: s.nickname, group_name: s.group_name });
    // 立即写回源数据刷新列表，同时显示名/音色/开关等就地更新
    upsertLocalSession(s, {
      on: s.on, voice: s.voice, send_mode: s.send_mode,
      prob: prob || 100, has_prob: prob > 0,
      nickname: s.nickname, group_name: s.group_name,
    });
    editing.value = null;
    toast("已保存", "ok");
  } catch (e: any) { toast(e?.message || "保存失败", "err"); }
}
</script>

<template>
  <div class="stack">
    <!-- 联系人同步信息 -->
    <div class="card toolbar-sticky">
      <div class="row wrap" style="padding-bottom:12px;border-bottom:1px solid var(--border);margin-bottom:14px;gap:8px">
        <CloudDownload :size="16" color="var(--brand-2)" />
        <div style="font-size:12px;color:var(--muted);flex:1;min-width:180px">
          <template v-if="contacts.meta.synced_at">
            联系人快照：{{ contacts.meta.groups }} 个群 · {{ contacts.meta.friends }} 位好友 · 同步于 {{ contacts.meta.synced_at }}
          </template>
          <template v-else>尚未同步联系人，点「同步列表」从机器人拉取全部群和好友（需机器人在线）。</template>
          <div v-if="contacts.meta.error" style="color:var(--warn);margin-top:4px;display:flex;align-items:center;gap:5px">
            <AlertTriangle :size="12" /> {{ contacts.meta.error.slice(0, 100) }}
          </div>
        </div>
        <button class="btn btn-sm btn-cyan" :disabled="syncingContacts" @click="syncContacts">
          <RefreshCw v-if="syncingContacts" :size="14" class="animate-spin" />
          <CloudDownload v-else :size="14" />
          {{ syncingContacts ? '同步中…' : '同步列表' }}
        </button>
      </div>
      <div class="row wrap" style="margin-bottom:12px">
        <div class="tabs">
          <button class="tab" :class="{ active: tab === 'all' }" @click="tab = 'all'">全部 <span class="tab-count">{{ counts.all }}</span></button>
          <button class="tab" :class="{ active: tab === 'private' }" @click="tab = 'private'"><MessageCircle :size="14" /> 私聊 <span class="tab-count">{{ counts.private }}</span></button>
          <button class="tab" :class="{ active: tab === 'group' }" @click="tab = 'group'"><Users :size="14" /> 群聊 <span class="tab-count">{{ counts.group }}</span></button>
        </div>
        <span class="grow"></span>
        <button class="btn btn-sm" :disabled="busyAvatar" @click="refreshAvatars"><ImageUp :size="14" /> {{ busyAvatar ? '刷新中…' : '刷新头像' }}</button>
        <button class="btn btn-sm" @click="load"><RefreshCw :size="14" /> 刷新</button>
        <button class="btn btn-sm btn-danger" @click="clearAll"><Trash2 :size="14" /> 清空状态</button>
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
      <div>{{ contacts.meta.synced_at || sessions.length ? '没有匹配的会话' : '点上方「同步列表」拉取机器人的全部群和好友。' }}</div>
    </div>
    <div v-else class="stack" style="gap:10px">
      <div v-for="s in filtered" :key="s.origin" class="item anim-in" :class="{ 'item-off': !s.has_state }">
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
            <span v-if="!s.has_state" class="badge" style="font-size:10px">未启用</span>
            <span v-else class="badge" :class="s.on ? 'ok' : ''" style="font-size:10px"><Volume2 :size="10" /> {{ s.on ? '语音开' : '语音关' }}</span>
          </div>
          <div style="color:var(--faint);font-size:11px;margin-top:4px;overflow:hidden;text-overflow:ellipsis;white-space:nowrap">
            {{ subName(s) }}<template v-if="s.has_state"> · 音色 {{ s.voice || '默认' }} · {{ s.send_mode || '默认' }} · {{ s.has_prob ? `${Math.round(s.prob)}% 发声` : '概率跟随全局' }}</template>
          </div>
        </div>
        <div style="color:var(--faint);font-size:11px;white-space:nowrap;text-align:right;min-width:52px">
          {{ activeText(s.last_active) }}
        </div>
        <button class="switch" :class="{ on: s.on }" @click="toggle(s)"></button>
        <button class="btn btn-sm btn-icon" title="编辑" @click="openEdit(s)"><Settings2 :size="15" /></button>
        <button v-if="s.has_state" class="btn btn-sm btn-icon btn-danger" title="删除状态" @click="remove(s)"><Trash2 :size="14" /></button>
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
            <BaseSelect v-model="editing.voice" :options="VOICE_OPTIONS" />
          </div>
          <div class="field"><label class="field-label">发送方式</label>
            <BaseSelect v-model="editing.send_mode" :options="SEND_OPTIONS" />
          </div>
          <div class="field"><label class="field-label">语音概率（0=跟随全局，1~100=发声百分比）</label>
            <input v-model.number="editing.prob" class="input" type="number" min="0" max="100" step="1" />
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
.item-off { opacity: .78; }
@media (max-width: 560px) { .tabs { width: 100%; } .tab { flex: 1; justify-content: center; padding: 8px 6px; } }
</style>
