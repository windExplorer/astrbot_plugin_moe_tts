import { reactive } from "vue";

export interface ToastItem { id: number; text: string; type: "ok" | "err" | "info" }
export const toasts = reactive<ToastItem[]>([]);
let seq = 0;

export function toast(text: string, type: "ok" | "err" | "info" = "info", ms = 2600) {
  const id = ++seq;
  toasts.push({ id, text, type });
  setTimeout(() => {
    const i = toasts.findIndex((t) => t.id === id);
    if (i >= 0) toasts.splice(i, 1);
  }, ms);
}
