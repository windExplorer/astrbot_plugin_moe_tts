<script setup lang="ts">
import { computed, onMounted, ref } from "vue";
import { Mic2, Search, Plus, Play, Pencil, Trash2, Star, Volume2, X, LoaderCircle, RefreshCw, CloudDownload } from "lucide-vue-next";
import BaseSelect from "../components/BaseSelect.vue";
import { apiGet, apiPost } from "../api";
import type { Voice } from "../api";
import { toast } from "../toast";

const LANG_OPTIONS = [
  { value: "zh", label: "中文 zh" }, { value: "en", label: "英文 en" },
  { value: "ja", label: "日文 ja" }, { value: "ko", label: "韩文 ko" },
  { value: "ru", label: "俄文 ru" }, { value: "th", label: "泰文 th" },
  { value: "", label: "未分类" },
];

const voices = ref<Voice[]>([]);
const defaultVoice = ref("");
const keyword = ref("");
const loading = ref(true);
const syncing = ref(false);
const snapshot = ref<{ synced_at: string; source_url: string; count: number }>({ synced_at: "", source_url: "", count: 0 });
const playing = ref("");
const audio = new Audio();

function vname(v: Voice): string {
  // 服务端音色以文件名标识（如 萌1.wav），展示时去掉扩展名更清爽
  return v.name.replace(/\.[^.]+$/, "") || v.name;
}

const form = ref<{ show: boolean; edit: boolean; oldName: string; name: string; file: string; text: string; language: string; markup: boolean; enabled: boolean }>({
  show: false, edit: false, oldName: "", name: "", file: "", text: "", language: "", markup: true, enabled: true,
});

const filtered = computed(() => {
  const k = keyword.value.trim().toLowerCase();
  const list = k ? voices.value.filter((v) => v.name.toLowerCase().includes(k) || v.language.toLowerCase().includes(k)) : voices.value;
  const groups: Record<string, Voice[]> = {};
  for (const v of list) {
    const g = v.language || "未分类";
    (groups[g] ||= []).push(v);
  }
  return Object.entries(groups).sort((a, b) => a[0].localeCompare(b[0]));
});

async function load() {
  loading.value = true;
  try {
    const [r, snap] = await Promise.all([
      apiGet<{ voices: Voice[]; default: string }>("voices"),
      apiGet<{ meta: typeof snapshot.value }>("voices/snapshot").catch(() => ({ meta: snapshot.value })),
    ]);
    voices.value = r.voices || [];
    defaultVoice.value = r.default || "";
    snapshot.value = snap.meta || snapshot.value;
  } catch (e: any) { toast(e?.message || "加载音色失败", "err"); }
  finally { loading.value = false; }
}
onMounted(load);

async function syncVoices() {
  syncing.value = true;
  try {
    const r = await apiPost<{ ok: boolean; count: number; meta: typeof snapshot.value }>("voices/sync", {}, 30000);
    snapshot.value = r.meta || snapshot.value;
    toast(`已从服务端同步 ${r.count} 个音色`, "ok");
    await load();
  } catch (e: any) { toast(e?.message || "同步失败", "err"); }
  finally { syncing.value = false; }
}

function openAdd() {
  form.value = { show: true, edit: false, oldName: "", name: "", file: "", text: "", language: "zh", markup: true, enabled: true };
}
function openEdit(v: Voice) {
  form.value = { show: true, edit: true, oldName: v.name, name: v.name, file: v.file, text: v.text, language: v.language, markup: v.markup ?? true, enabled: v.enabled };
}
async function save() {
  const f = form.value;
  if (!f.name.trim()) return toast("音色名不能为空", "err");
  try {
    if (f.edit) {
      await apiPost("voices/update", { old_name: f.oldName, name: f.name, file: f.file, text: f.text, language: f.language, markup: f.markup, enabled: f.enabled });
      toast("音色已更新", "ok");
    } else {
      await apiPost("voices/create", { name: f.name, file: f.file || f.name, text: f.text, language: f.language, markup: f.markup, enabled: f.enabled });
      toast("音色已添加", "ok");
    }
    form.value.show = false;
    await load();
  } catch (e: any) { toast(e?.message || "保存失败", "err"); }
}
async function remove(v: Voice) {
  if (!confirm(`确定删除音色「${v.name}」？`)) return;
  try { await apiPost("voices/delete", { name: v.name }); toast("已删除", "ok"); await load(); }
  catch (e: any) { toast(e?.message || "删除失败", "err"); }
}
async function setDefault(v: Voice) {
  try { await apiPost("voices/default", { name: v.name }); defaultVoice.value = v.name; toast(`默认音色已设为 ${v.name}`, "ok"); }
  catch (e: any) { toast(e?.message || "设置失败", "err"); }
}
async function preview(v: Voice) {
  if (playing.value === v.name) { audio.pause(); playing.value = ""; return; }
  playing.value = v.name;
  try {
    // 直接取服务端参考音频（本地缓存优先），不走 TTS 克隆，秒开
    const r = await apiGet<{ audio: string; cached: boolean }>("voice/audio", { name: v.name }, 30000);
    audio.src = r.audio;
    audio.onended = () => { playing.value = ""; };
    audio.onerror = () => { playing.value = ""; toast("音频播放失败", "err"); };
    await audio.play();
    if (r.cached) { /* 命中本地缓存 */ }
  } catch (e: any) { playing.value = ""; toast(e?.message || "试听失败", "err"); }
}
</script>

<template>
  <div class="stack">
    <div class="card toolbar-sticky">
      <!-- 服务端音色快照信息 -->
      <div class="row wrap" style="padding-bottom:12px;border-bottom:1px solid var(--border);margin-bottom:14px;gap:8px">
        <CloudDownload :size="16" color="var(--brand-2)" />
        <div style="font-size:12px;color:var(--muted);flex:1;min-width:180px">
          <template v-if="snapshot.synced_at">
            服务端音色快照：{{ snapshot.count }} 个 · 同步于 {{ snapshot.synced_at }}
            <span v-if="snapshot.source_url" style="color:var(--faint)">（{{ snapshot.source_url }}）</span>
          </template>
          <template v-else>尚未从服务端同步音色，点右侧按钮拉取最新列表并存入本地。</template>
        </div>
        <button class="btn btn-sm btn-cyan" :disabled="syncing" @click="syncVoices">
          <LoaderCircle v-if="syncing" :size="14" class="animate-spin" />
          <CloudDownload v-else :size="14" />
          {{ syncing ? '同步中…' : '从服务端同步' }}
        </button>
      </div>
      <div class="row wrap">
        <div class="grow" style="min-width:200px;position:relative">
          <Search :size="16" style="position:absolute;left:12px;top:50%;transform:translateY(-50%);color:var(--faint)" />
          <input v-model="keyword" class="input" style="padding-left:36px" placeholder="搜索音色名 / 语种…" />
        </div>
        <button class="btn btn-primary" @click="openAdd"><Plus :size="16" /> 新增音色</button>
        <button class="btn" @click="load"><RefreshCw :size="15" /> 刷新</button>
      </div>
    </div>

    <div v-if="loading" class="grid grid-3">
      <div v-for="i in 6" :key="i" class="skeleton" style="height:120px"></div>
    </div>
    <div v-else-if="!voices.length" class="card empty">
      <div class="empty-icon"><Mic2 :size="30" /></div>
      <div>还没有音色。可以在 WebUI 新增，或先检查服务端是否配置了参考音频。</div>
    </div>
    <template v-else>
      <div v-for="[lang, list] in filtered" :key="lang" class="stack" style="gap:10px">
        <div class="row" style="gap:8px">
          <span class="badge brand">{{ lang }}</span>
          <span style="color:var(--faint);font-size:12px">{{ list.length }} 个音色</span>
        </div>
        <div class="grid grid-3 stagger">
          <div v-for="v in list" :key="v.name" class="card" style="padding:15px">
            <div class="row">
              <div class="avatar" style="width:36px;height:36px;flex-basis:36px"><Mic2 :size="17" /></div>
              <div class="grow" style="min-width:0">
                <div class="row" style="gap:6px">
                  <strong style="font-size:14px;overflow:hidden;text-overflow:ellipsis;white-space:nowrap">{{ vname(v) }}</strong>
                  <span v-if="defaultVoice === v.name" class="badge warn" style="font-size:10px"><Star :size="10" fill="currentColor" /> 默认</span>
                </div>
                <div style="color:var(--faint);font-size:11px;margin-top:3px">{{ v.file }}</div>
              </div>
            </div>
            <div v-if="v.text" style="color:var(--muted);font-size:12px;margin:12px 0;line-height:1.5;max-height:38px;overflow:hidden">
              {{ v.text }}
            </div>
            <div class="row" style="gap:7px;margin-top:12px">
              <button class="btn btn-sm" :class="playing === v.name ? 'btn-cyan' : ''" @click="preview(v)">
                <LoaderCircle v-if="playing === v.name" :size="14" class="animate-spin" />
                <Play v-else :size="14" fill="currentColor" />
                {{ playing === v.name ? '播放中' : '试听' }}
              </button>
              <button class="btn btn-sm btn-icon" title="设为默认" @click="setDefault(v)"><Star :size="14" /></button>
              <button class="btn btn-sm btn-icon" title="编辑" @click="openEdit(v)"><Pencil :size="14" /></button>
              <button class="btn btn-sm btn-icon btn-danger" title="删除" @click="remove(v)"><Trash2 :size="14" /></button>
            </div>
          </div>
        </div>
      </div>
    </template>

    <!-- 编辑弹窗 -->
    <div v-if="form.show" class="mask" @click.self="form.show = false">
      <div class="modal anim-pop">
        <div class="modal-head">
          <div class="modal-title">{{ form.edit ? '编辑音色' : '新增音色' }}</div>
          <button class="btn btn-ghost btn-icon" @click="form.show = false"><X :size="18" /></button>
        </div>
        <div class="stack">
          <div class="field"><label class="field-label">音色名</label><input v-model="form.name" class="input" placeholder="唯一标识，如 xiaoyu" /></div>
          <div class="field"><label class="field-label">参考音频文件</label><input v-model="form.file" class="input" placeholder="服务端音色文件名，如 xiaoyu.wav" /></div>
          <div class="field"><label class="field-label">参考文本</label><textarea v-model="form.text" class="textarea" placeholder="音频对应的逐字原文（极速克隆可留空）"></textarea></div>
          <div class="field"><label class="field-label">语种</label>
            <BaseSelect v-model="form.language" :options="LANG_OPTIONS" />
          </div>
          <div class="row" style="justify-content:space-between">
            <span>注入副语言标记</span><button class="switch" :class="{ on: form.markup }" @click="form.markup = !form.markup"></button>
          </div>
          <div class="row" style="justify-content:space-between">
            <span>启用该音色</span><button class="switch" :class="{ on: form.enabled }" @click="form.enabled = !form.enabled"></button>
          </div>
          <div class="row" style="margin-top:8px">
            <button class="btn grow" @click="form.show = false">取消</button>
            <button class="btn btn-primary grow" @click="save">保存</button>
          </div>
        </div>
      </div>
    </div>
  </div>
</template>
