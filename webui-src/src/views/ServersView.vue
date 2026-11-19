<script setup lang="ts">
import { onMounted, ref } from "vue";
import {
  Server as ServerIcon, Plus, Trash2, Check, Radio, RefreshCw,
  Cpu, MemoryStick, X, Zap, Activity,
} from "lucide-vue-next";
import { apiGet, apiPost } from "../api";
import type { Server } from "../api";
import { toast } from "../toast";

const servers = ref<Server[]>([]);
const activeIndex = ref(0);
const loading = ref(true);
const probing = ref(-1);
const canManage = ref(false);
const status = ref<any>(null);

const form = ref({ show: false, name: "", type: "taskhub", url: "http://127.0.0.1:9000", timeout: 250 });

async function load() {
  loading.value = true;
  try {
    const [s, o] = await Promise.all([
      apiGet<{ servers: Server[]; active_index: number }>("servers"),
      apiGet<{ can_manage: boolean }>("overview"),
    ]);
    servers.value = s.servers || [];
    activeIndex.value = s.active_index ?? 0;
    canManage.value = !!o.can_manage;
  } catch (e: any) { toast(e?.message || "加载失败", "err"); }
  finally { loading.value = false; }
  if (canManage.value) await loadStatus();
}
onMounted(load);

async function loadStatus() {
  try { status.value = await apiGet("server/status", undefined, 8000); }
  catch (e: any) { status.value = null; }
}
async function activate(index: number) {
  if (activeIndex.value === index) return;
  probing.value = index;
  try {
    const r = await apiPost<{ ok: boolean; health: any }>("servers/activate", { index }, 20000);
    activeIndex.value = index;
    servers.value.forEach((s) => s.enabled = s.index === index);
    if (r.health?.ok) toast(`已切换到 ${servers.value[index].name}`, "ok");
    else toast("已切换，但服务暂时探测不到，请检查地址", "warn" as any);
    await loadStatus();
  } catch (e: any) { toast(e?.message || "切换失败", "err"); }
  finally { probing.value = -1; }
}
async function addServer() {
  if (!form.value.url.trim()) return toast("服务地址不能为空", "err");
  try {
    await apiPost("servers/add", { ...form.value, enabled: servers.value.length === 0 });
    form.value.show = false;
    await load();
    toast("服务端已添加", "ok");
  } catch (e: any) { toast(e?.message || "添加失败", "err"); }
}
async function remove(s: Server) {
  if (!confirm(`删除服务端「${s.name}」？`)) return;
  try { await apiPost("servers/remove", { index: s.index }); await load(); toast("已删除", "ok"); }
  catch (e: any) { toast(e?.message || "删除失败", "err"); }
}
async function switchBackend(backend: string) {
  try { await apiPost("server/backend", { backend }, 200000); toast(`已切换到 ${backend}`, "ok"); await loadStatus(); }
  catch (e: any) { toast(e?.message || "切换失败", "err"); }
}
async function vram(action: "load" | "unload") {
  try { await apiPost("server/vram", { action }, 90000); toast(`显存已${action === 'load' ? '加载' : '卸载'}`, "ok"); await loadStatus(); }
  catch (e: any) { toast(e?.message || "操作失败", "err"); }
}
</script>

<template>
  <div class="stack">
    <div class="card">
      <div class="row wrap">
        <div class="grow">
          <div class="card-title" style="margin:0"><ServerIcon class="ico" :size="17" /> 服务端列表 <span class="badge brand" style="font-size:10px">同时启用一个</span></div>
          <div style="color:var(--muted);font-size:12px;margin-top:6px">点击「启用」切换当前使用的服务端；切换后自动探测采样率。</div>
        </div>
        <button class="btn btn-primary" @click="form.show = true"><Plus :size="16" /> 添加服务端</button>
        <button class="btn" @click="load"><RefreshCw :size="15" /> 刷新</button>
      </div>
    </div>

    <div v-if="loading" class="stack">
      <div v-for="i in 3" :key="i" class="skeleton" style="height:78px"></div>
    </div>
    <div v-else-if="!servers.length" class="card empty">
      <div class="empty-icon"><ServerIcon :size="30" /></div>
      <div>还没有服务端，点「添加服务端」开始配置。</div>
    </div>
    <div v-else class="stack" style="gap:10px">
      <div v-for="s in servers" :key="s.index" class="item anim-in" :class="{ active: s.enabled }">
        <div class="avatar" :style="s.enabled ? {} : { background: 'rgba(148,163,184,.2)' }"><ServerIcon :size="18" /></div>
        <div class="grow" style="min-width:0">
          <div class="row" style="gap:8px">
            <strong style="font-size:14px">{{ s.name || s.url }}</strong>
            <span class="badge" :class="s.type === 'taskhub' ? 'cyan' : 'brand'" style="font-size:10px">
              {{ s.type === 'taskhub' ? 'TaskHub' : 'tts_serve' }}
            </span>
            <span v-if="s.enabled" class="badge ok" style="font-size:10px"><Check :size="10" /> 使用中</span>
          </div>
          <div style="color:var(--faint);font-size:11px;margin-top:4px;overflow:hidden;text-overflow:ellipsis;white-space:nowrap">
            {{ s.url }} · 超时 {{ s.timeout }}s
          </div>
        </div>
        <button class="btn btn-sm" :class="s.enabled ? 'btn-cyan' : ''" :disabled="s.enabled || probing === s.index" @click="activate(s.index)">
          <Radio v-if="probing === s.index" :size="14" class="animate-spin" />
          <Check v-else-if="s.enabled" :size="14" />
          <Zap v-else :size="14" />
          {{ s.enabled ? '当前' : '启用' }}
        </button>
        <button class="btn btn-sm btn-icon btn-danger" title="删除" @click="remove(s)"><Trash2 :size="14" /></button>
      </div>
    </div>

    <!-- 网关管理（仅直连） -->
    <div v-if="canManage" class="card">
      <div class="card-title"><Cpu class="ico" :size="17" /> 网关管理 <span class="badge ok" style="font-size:10px">tts_serve</span></div>
      <div v-if="status" class="grid grid-4" style="margin-bottom:16px">
        <div class="stat"><div class="stat-label"><Activity :size="13" /> 后端</div><div class="stat-value" style="font-size:19px">{{ status.backend || '-' }}</div></div>
        <div class="stat"><div class="stat-label">设备</div><div class="stat-value" style="font-size:19px">{{ status.device || '-' }}</div></div>
        <div class="stat"><div class="stat-label"><MemoryStick :size="13" /> 空闲显存</div><div class="stat-value" style="font-size:19px">{{ status.free_vram_mb ?? '-' }} MB</div></div>
        <div class="stat"><div class="stat-label">采样率</div><div class="stat-value" style="font-size:19px">{{ status.sample_rate || '-' }}</div></div>
      </div>
      <div class="row wrap">
        <span style="color:var(--muted);font-size:12px">切换后端：</span>
        <button class="btn btn-sm" :class="status?.backend === 'qwen3' ? 'btn-cyan' : ''" @click="switchBackend('qwen3')">Qwen3-TTS</button>
        <button class="btn btn-sm" :class="status?.backend === 'cosyvoice3' ? 'btn-cyan' : ''" @click="switchBackend('cosyvoice3')">CosyVoice3</button>
        <span style="width:16px"></span>
        <button class="btn btn-sm" @click="vram('unload')"><MemoryStick :size="13" /> 卸载显存</button>
        <button class="btn btn-sm" @click="vram('load')"><Zap :size="13" /> 加载权重</button>
        <button class="btn btn-sm" @click="loadStatus"><RefreshCw :size="13" /> 刷新状态</button>
      </div>
      <div v-if="status?.gpu_name" style="color:var(--faint);font-size:11px;margin-top:12px">GPU: {{ status.gpu_name }}</div>
    </div>

    <!-- 添加弹窗 -->
    <div v-if="form.show" class="mask" @click.self="form.show = false">
      <div class="modal anim-pop">
        <div class="modal-head">
          <div class="modal-title">添加服务端</div>
          <button class="btn btn-ghost btn-icon" @click="form.show = false"><X :size="18" /></button>
        </div>
        <div class="stack">
          <div class="field"><label class="field-label">名称</label><input v-model="form.name" class="input" placeholder="如：家里中转站" /></div>
          <div class="field"><label class="field-label">类型</label>
            <select v-model="form.type" class="select">
              <option value="taskhub">TaskHub 中转站（推荐，队列调度）</option>
              <option value="tts_serve">tts_serve 网关（支持 ASR / 管理）</option>
            </select>
          </div>
          <div class="field"><label class="field-label">服务地址</label><input v-model="form.url" class="input" placeholder="http://127.0.0.1:9000" /></div>
          <div class="field"><label class="field-label">超时（秒）</label><input v-model.number="form.timeout" type="number" class="input" /></div>
          <div class="row" style="margin-top:8px">
            <button class="btn grow" @click="form.show = false">取消</button>
            <button class="btn btn-primary grow" @click="addServer">添加</button>
          </div>
        </div>
      </div>
    </div>
  </div>
</template>
