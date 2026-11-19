<script setup lang="ts">
import { onMounted, ref } from "vue";
import { FlaskConical, Play, Download, WandSparkles, Gauge, Layers, Mic, Upload, Square } from "lucide-vue-next";
import { apiGet, apiPost } from "../api";
import type { Voice } from "../api";
import { toast } from "../toast";

const voices = ref<Voice[]>([]);
const defaultVoice = ref("");
const text = ref("你好呀，我是萌萌语音。今天天气不错，我们一起出去走走吧！");
const voice = ref("");
const loading = ref(false);
const audioSrc = ref("");
const meta = ref<{ duration_ms: number; sample_rate: number; queue_position: number; generation_time: number; elapsed_ms: number } | null>(null);
const segs = ref<{ index: number; text: string; chars: number }[]>([]);
const audio = new Audio();

const canManage = ref(false);
const asrAudio = ref<{ name: string; data: string } | null>(null);
const asrText = ref("");
const asrBusy = ref(false);

async function load() {
  try {
    const [v, o] = await Promise.all([
      apiGet<{ voices: Voice[]; default: string }>("voices"),
      apiGet<{ can_manage: boolean }>("overview"),
    ]);
    voices.value = v.voices || [];
    voice.value = v.default || "";
    canManage.value = !!o.can_manage;
  } catch (e: any) { toast(e?.message || "加载失败", "err"); }
}
onMounted(load);

async function synthesize() {
  if (!text.value.trim()) return toast("请输入要合成的文本", "err");
  loading.value = true;
  meta.value = null;
  try {
    const r = await apiPost<{ audio: string; duration_ms: number; sample_rate: number; queue_position: number; generation_time: number; elapsed_ms: number }>(
      "synthesize", { text: text.value, voice: voice.value }, 300000);
    audioSrc.value = r.audio;
    meta.value = r;
    audio.src = r.audio;
    await audio.play();
    toast("合成完成", "ok");
  } catch (e: any) { toast(e?.message || "合成失败", "err"); }
  finally { loading.value = false; }
}
async function previewSegments() {
  try {
    const r = await apiPost<{ segments: typeof segs.value }>("segment_preview", { text: text.value });
    segs.value = r.segments || [];
    toast(`已切成 ${segs.value.length} 段`, "info");
  } catch (e: any) { toast(e?.message || "分段试算失败", "err"); }
}
function download() {
  if (!audioSrc.value) return;
  const a = document.createElement("a");
  a.href = audioSrc.value;
  a.download = `moe-tts-${Date.now()}.wav`;
  a.click();
}
function pickAsr(e: Event) {
  const input = e.target as HTMLInputElement;
  const file = input.files?.[0];
  if (!file) return;
  const reader = new FileReader();
  reader.onload = () => {
    const result = String(reader.result || "");
    asrAudio.value = { name: file.name, data: result.includes(",") ? result.split(",")[1] : result };
  };
  reader.readAsDataURL(file);
}
async function runAsr() {
  if (!asrAudio.value) return toast("请先选择音频文件", "err");
  asrBusy.value = true;
  try {
    const r = await apiPost<{ text: string }>("server/asr", { audio: asrAudio.value.data, filename: asrAudio.value.name }, 120000);
    asrText.value = r.text || "";
    toast("识别完成", "ok");
  } catch (e: any) { toast(e?.message || "识别失败", "err"); }
  finally { asrBusy.value = false; }
}
</script>

<template>
  <div class="stack">
    <div class="grid" style="grid-template-columns:minmax(0,1.4fr) minmax(0,1fr)">
      <!-- 合成 -->
      <div class="card">
        <div class="card-title"><FlaskConical class="ico" :size="17" /> 文本合成</div>
        <div class="stack" style="gap:14px">
          <div class="field">
            <label class="field-label">要合成的文本</label>
            <textarea v-model="text" class="textarea" style="min-height:130px" placeholder="输入任意文本…"></textarea>
          </div>
          <div class="field">
            <label class="field-label">选择音色</label>
            <select v-model="voice" class="select">
              <option value="">默认音色</option>
              <option v-for="v in voices" :key="v.name" :value="v.name">{{ v.name }}{{ v.language ? ` · ${v.language}` : '' }}</option>
            </select>
          </div>
          <div class="row wrap">
            <button class="btn btn-primary grow" :disabled="loading" @click="synthesize">
              <Play :size="16" fill="currentColor" /> {{ loading ? '合成中…' : '合成并播放' }}
            </button>
            <button class="btn" @click="previewSegments"><Layers :size="16" /> 分段试算</button>
          </div>

          <!-- 波形 + 播放器 -->
          <div class="card" style="background:var(--fill);padding:18px">
            <div class="wave" :class="{ static: !loading }">
              <span v-for="i in 5" :key="i"></span>
            </div>
            <audio v-if="audioSrc" :src="audioSrc" controls style="width:100%;margin-top:12px"></audio>
            <div v-else style="text-align:center;color:var(--faint);font-size:12px;margin-top:8px">合成后可在此播放</div>
            <div v-if="meta" class="row wrap" style="gap:8px;margin-top:12px;justify-content:center">
              <span class="badge cyan"><Gauge :size="12" /> {{ (meta.duration_ms / 1000).toFixed(1) }}s</span>
              <span class="badge">{{ meta.sample_rate }} Hz</span>
              <span v-if="meta.queue_position" class="badge warn">排队 {{ meta.queue_position }}</span>
              <span class="badge brand">耗时 {{ (meta.elapsed_ms / 1000).toFixed(1) }}s</span>
              <button class="btn btn-sm" @click="download"><Download :size="13" /> 下载</button>
            </div>
          </div>
        </div>
      </div>

      <!-- 分段预览 -->
      <div class="card">
        <div class="card-title"><Layers class="ico" :size="17" /> 分段预览</div>
        <div v-if="!segs.length" style="color:var(--faint);font-size:13px;line-height:1.7">
          点「分段试算」查看当前配置会把文本切成几段、每段多少字。调参不用猜。
        </div>
        <div v-else class="stack" style="gap:8px;max-height:460px;overflow-y:auto">
          <div v-for="s in segs" :key="s.index" class="seg-chip anim-in" style="align-items:flex-start">
            <span class="badge brand" style="font-size:10px">#{{ s.index }}</span>
            <span style="flex:1;line-height:1.5">{{ s.text }}</span>
            <span style="color:var(--faint);font-size:11px;white-space:nowrap">{{ s.chars }}字</span>
          </div>
        </div>
      </div>
    </div>

    <!-- ASR -->
    <div class="card">
      <div class="card-title"><Mic class="ico" :size="17" /> 语音识别（ASR） 
        <span v-if="!canManage" class="badge warn" style="margin-left:auto;font-size:10px">仅 tts_serve 直连可用</span>
        <span v-else class="badge ok" style="margin-left:auto;font-size:10px">可用</span>
      </div>
      <div class="row wrap">
        <label class="btn" style="cursor:pointer">
          <Upload :size="16" /> 选择音频
          <input type="file" accept="audio/*" style="display:none" @change="pickAsr" />
        </label>
        <span v-if="asrAudio" style="color:var(--muted);font-size:12px">{{ asrAudio.name }}</span>
        <button class="btn btn-cyan" :disabled="!canManage || asrBusy || !asrAudio" @click="runAsr">
          <WandSparkles :size="16" /> {{ asrBusy ? '识别中…' : '开始识别' }}
        </button>
      </div>
      <div v-if="asrText" class="card" style="margin-top:14px;background:var(--fill)">
        <div style="color:var(--muted);font-size:12px;margin-bottom:6px">识别结果</div>
        <div style="font-size:14px;line-height:1.7">{{ asrText }}</div>
      </div>
    </div>
  </div>
</template>
