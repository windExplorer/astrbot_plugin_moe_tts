<script setup lang="ts">
import { ref, computed, onMounted, onUnmounted, nextTick } from "vue";
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
const menuStyle = ref<Record<string, string>>({});
const selected = computed(() => props.options.find((o) => o.value === props.modelValue));

// 菜单 Teleport 到 body 并 fixed 定位：避免被卡片/sticky 的层叠上下文遮挡
function positionMenu() {
  const el = root.value;
  if (!el) return;
  const r = el.getBoundingClientRect();
  const gap = 6;
  const menuMaxH = 260;
  const spaceBelow = window.innerHeight - r.bottom;
  const flipUp = spaceBelow < Math.min(menuMaxH, 140) && r.top > spaceBelow;
  const style: Record<string, string> = {
    left: `${r.left}px`,
    width: `${r.width}px`,
    zIndex: "9999",
  };
  if (flipUp) {
    style.bottom = `${window.innerHeight - r.top + gap}px`;
    style.maxHeight = `${Math.min(menuMaxH, r.top - gap - 12)}px`;
  } else {
    style.top = `${r.bottom + gap}px`;
    style.maxHeight = `${Math.min(menuMaxH, spaceBelow - gap - 12)}px`;
  }
  menuStyle.value = style;
}

async function toggle() {
  if (props.disabled) return;
  open.value = !open.value;
  if (open.value) { await nextTick(); positionMenu(); }
}
function choose(value: string) { emit("update:modelValue", value); open.value = false; }
function onClickOutside(e: MouseEvent) {
  const t = e.target as Node;
  if (root.value?.contains(t)) return;
  // 菜单在 body 上，需额外判断是否点在菜单内
  if ((t as Element)?.closest?.(".bsel-menu-global")) return;
  open.value = false;
}
function onViewportChange() { if (open.value) positionMenu(); }
onMounted(() => {
  document.addEventListener("click", onClickOutside);
  window.addEventListener("scroll", onViewportChange, true);
  window.addEventListener("resize", onViewportChange);
});
onUnmounted(() => {
  document.removeEventListener("click", onClickOutside);
  window.removeEventListener("scroll", onViewportChange, true);
  window.removeEventListener("resize", onViewportChange);
});
</script>

<template>
  <div ref="root" class="bsel" :class="{ open }">
    <button type="button" class="bsel-trigger" :disabled="disabled" @click="toggle">
      <span class="bsel-value" :class="{ ph: !selected }">{{ selected?.label || placeholder || '请选择' }}</span>
      <ChevronDown :size="16" class="bsel-arrow" />
    </button>
    <Teleport to="body">
      <Transition name="bsel-pop">
        <div v-if="open" class="bsel-menu-global" :style="menuStyle">
          <button v-for="o in options" :key="o.value" type="button" class="bsel-opt-global"
                  :class="{ active: o.value === modelValue }" @click="choose(o.value)">
            <span>{{ o.label }}</span>
            <Check v-if="o.value === modelValue" :size="14" />
          </button>
          <div v-if="!options.length" class="bsel-empty-global">无选项</div>
        </div>
      </Transition>
    </Teleport>
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
</style>

<!-- Teleport 到 body 的菜单：必须非 scoped，且用 :deep 无法作用于 body 节点，故单独全局样式 -->
<style>
.bsel-menu-global {
  position: fixed;
  background: var(--surface-solid); border: 1px solid var(--border-hi);
  border-radius: 10px; padding: 5px; box-shadow: var(--shadow-modal);
  overflow-y: auto;
}
.bsel-opt-global {
  width: 100%; display: flex; align-items: center; justify-content: space-between; gap: 8px;
  padding: 9px 11px; border-radius: 7px; border: 0; background: transparent;
  color: var(--text); font-size: 13px; font-family: inherit; text-align: left; cursor: pointer;
  transition: background .15s, color .15s;
}
.bsel-opt-global:hover { background: var(--hover); }
.bsel-opt-global.active { color: var(--brand-soft); background: var(--seg-bg); font-weight: 600; }
.bsel-empty-global { padding: 12px; text-align: center; color: var(--faint); font-size: 12px; }
.bsel-pop-enter-active { animation: bselIn .16s ease-out; }
.bsel-pop-leave-active { animation: bselIn .12s ease-in reverse; }
@keyframes bselIn { from { opacity: 0; transform: translateY(-5px); } to { opacity: 1; transform: translateY(0); } }
</style>
