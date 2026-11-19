<script setup lang="ts">
import { ref, computed, onMounted, onUnmounted } from "vue";
import { ChevronDown, Check } from "lucide-vue-next";

interface Option { value: string; label: string }
const props = defineProps<{
  modelValue: string;
  options: Option[];
  placeholder?: string;
  disabled?: boolean;
}>();
const emit = defineEmits<{ "update:modelValue": [value: string] }>();

const open = ref(false);
const root = ref<HTMLElement | null>(null);
const selected = computed(() => props.options.find((o) => o.value === props.modelValue));

function toggle() { if (!props.disabled) open.value = !open.value; }
function choose(value: string) { emit("update:modelValue", value); open.value = false; }
function onClickOutside(e: MouseEvent) {
  if (root.value && !root.value.contains(e.target as Node)) open.value = false;
}
onMounted(() => document.addEventListener("click", onClickOutside));
onUnmounted(() => document.removeEventListener("click", onClickOutside));
</script>

<template>
  <div ref="root" class="bsel" :class="{ open }">
    <button type="button" class="bsel-trigger" :disabled="disabled" @click="toggle">
      <span class="bsel-value" :class="{ ph: !selected }">{{ selected?.label || placeholder || '请选择' }}</span>
      <ChevronDown :size="16" class="bsel-arrow" />
    </button>
    <Transition name="bsel-pop">
      <div v-if="open" class="bsel-menu">
        <button v-for="o in options" :key="o.value" type="button" class="bsel-opt"
                :class="{ active: o.value === modelValue }" @click="choose(o.value)">
          <span>{{ o.label }}</span>
          <Check v-if="o.value === modelValue" :size="14" />
        </button>
        <div v-if="!options.length" class="bsel-empty">无选项</div>
      </div>
    </Transition>
  </div>
</template>

<style scoped>
.bsel { position: relative; width: 100%; }
.bsel-trigger {
  width: 100%; display: flex; align-items: center; justify-content: space-between; gap: 8px;
  background: var(--field-bg); border: 1px solid var(--border-hi); border-radius: 10px;
  padding: 10px 12px; color: var(--text); font-size: 13px; font-family: inherit;
  cursor: pointer; outline: none; text-align: left;
  transition: border-color .2s, box-shadow .2s, background .2s;
}
.bsel-trigger:hover:not(:disabled) { border-color: var(--border-hi); background: var(--field-bg-focus); }
.bsel.open .bsel-trigger, .bsel-trigger:focus { border-color: var(--brand); box-shadow: 0 0 0 3px var(--focus-ring); }
.bsel-trigger:disabled { opacity: .45; cursor: not-allowed; }
.bsel-value { flex: 1; min-width: 0; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.bsel-value.ph { color: var(--faint); }
.bsel-arrow { color: var(--muted); flex: 0 0 16px; transition: transform .2s; }
.bsel.open .bsel-arrow { transform: rotate(180deg); }
.bsel-menu {
  position: absolute; top: calc(100% + 6px); left: 0; right: 0; z-index: 30;
  background: var(--surface-solid); border: 1px solid var(--border-hi);
  border-radius: 10px; padding: 5px; box-shadow: var(--shadow-modal);
  max-height: 260px; overflow-y: auto;
}
.bsel-opt {
  width: 100%; display: flex; align-items: center; justify-content: space-between; gap: 8px;
  padding: 9px 11px; border-radius: 7px; border: 0; background: transparent;
  color: var(--text); font-size: 13px; font-family: inherit; text-align: left; cursor: pointer;
  transition: background .15s, color .15s;
}
.bsel-opt:hover { background: var(--hover); }
.bsel-opt.active { color: var(--brand-soft); background: var(--seg-bg); font-weight: 600; }
.bsel-empty { padding: 12px; text-align: center; color: var(--faint); font-size: 12px; }
.bsel-pop-enter-active { animation: bselIn .16s ease-out; }
.bsel-pop-leave-active { animation: bselIn .12s ease-in reverse; }
@keyframes bselIn { from { opacity: 0; transform: translateY(-5px); } to { opacity: 1; transform: translateY(0); } }
</style>
