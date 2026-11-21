// 通过 AstrBot 官方插件 Page 桥接调用后端 Web API。
// 桥接会处理 /api/plug/ 路由与 asset_token，不能用裸 fetch（CORS/鉴权会失败）。

export const PAGE_PLUGIN_NAME = "astrbot_plugin_moe_tts";

interface Bridge {
  apiGet(endpoint: string, params?: Record<string, any>): Promise<any>;
  apiPost(endpoint: string, body?: Record<string, any>): Promise<any>;
}

function getBridge(): Bridge | null {
  const w = window as any;
  if (w.AstrBotPluginPage) return w.AstrBotPluginPage;
  try {
    if (w.parent && w.parent !== w && w.parent.AstrBotPluginPage) return w.parent.AstrBotPluginPage;
  } catch { return null; }
  return null;
}

function isUsable(b: Bridge | null | undefined): b is Bridge {
  return Boolean(b && typeof b.apiGet === "function" && typeof b.apiPost === "function");
}

async function getPageBridge(timeoutMs = 2500): Promise<Bridge> {
  const start = Date.now();
  while (true) {
    const b = getBridge();
    if (isUsable(b)) return b;
    if (Date.now() - start > timeoutMs) throw new Error("未检测到 AstrBot 页面桥接，请从 AstrBot 后台插件页打开");
    await new Promise((r) => setTimeout(r, 100));
  }
}

function candidates(routePath: string): string[] {
  const clean = routePath.replace(/^\/+/, "");
  return [...new Set([
    clean,
    "/" + clean,
    PAGE_PLUGIN_NAME + "/" + clean,
    "/" + PAGE_PLUGIN_NAME + "/" + clean,
  ])].filter(Boolean);
}

function routeMissing(p: any): boolean {
  if (!p || typeof p !== "object") return false;
  const text = String((p.error || "") + " " + (p.message || "") + " " + (p.detail || "")).toLowerCase();
  return /未找到.*路由|route.*not.*found|not.*found.*route/.test(text);
}

function withTimeout<T>(promise: Promise<T>, ms: number, label: string): Promise<T> {
  let timer: ReturnType<typeof setTimeout> | null = null;
  const timeout = new Promise<never>((_, reject) => {
    timer = setTimeout(() => reject(new Error(`${label} 超时（${ms / 1000}s）`)), ms);
  });
  return Promise.race([promise, timeout]).finally(() => { if (timer) clearTimeout(timer); });
}

function normalize(payload: any): any {
  if (!payload || typeof payload !== "object") return payload;
  // AstrBot error_response() 信封：{status: "error", message, data}
  if (payload.status === "error") throw new Error(payload.message || payload.error || "请求失败");
  // 部分桥接版本的 {success: false, error} 信封
  if ("success" in payload && payload.success === false) throw new Error(payload.error || "请求失败");
  if ("success" in payload) return payload.data !== undefined ? payload.data : payload;
  return payload;
}

async function raw(path: string, method: "GET" | "POST", body?: unknown, timeoutMs?: number): Promise<any> {
  const br = await getPageBridge();
  const url = new URL(path, "https://moe-tts.local/");
  const route = url.pathname.replace(/^\/+/, "");
  const list = candidates(route);
  const errors: string[] = [];
  const ms = timeoutMs ?? 6000;
  if (method === "GET") {
    const params = Object.fromEntries(url.searchParams.entries());
    for (const c of list) {
      try {
        const p = await withTimeout(br.apiGet(c, Object.keys(params).length ? params : undefined), ms, "GET " + c);
        if (routeMissing(p)) { errors.push(p.message || p.error || "未找到路由"); continue; }
        return normalize(p);
      } catch (e: any) { errors.push(e?.message || String(e)); }
    }
  } else {
    let payload: any;
    try { payload = JSON.parse(JSON.stringify(body || {})); } catch { payload = {}; }
    for (const c of list) {
      try {
        const r = await withTimeout(br.apiPost(c, payload), ms, "POST " + c);
        if (routeMissing(r)) { errors.push(r.message || r.error || "未找到路由"); continue; }
        return normalize(r);
      } catch (e: any) { errors.push(e?.message || String(e)); }
    }
  }
  throw new Error(errors[0] || "未找到可用的页面 API 路由");
}

export function apiGet<T = any>(endpoint: string, params?: Record<string, any>, timeoutMs?: number): Promise<T> {
  let path = endpoint;
  if (params && Object.keys(params).length) {
    const qs = new URLSearchParams();
    for (const k of Object.keys(params)) {
      const v = params[k];
      if (v === undefined || v === null || v === "") continue;
      qs.set(k, String(v));
    }
    const q = qs.toString();
    if (q) path += "?" + q;
  }
  return raw(path, "GET", undefined, timeoutMs) as Promise<T>;
}

export function apiPost<T = any>(endpoint: string, body?: unknown, timeoutMs?: number): Promise<T> {
  return raw(endpoint, "POST", body || {}, timeoutMs) as Promise<T>;
}

// ---------- 类型 ----------
export interface Overview {
  ready: boolean;
  server: { name: string; type: string; url: string; sample_rate: number; cooldown_remaining: number; in_cooldown: boolean; last_error: string } | null;
  active_type: string;
  can_manage: boolean;
  auto_tts: boolean;
  send_mode: string;
  default_voice: string;
  voices_count: number;
  session_count: number;
  stats: { total: number; ok: number; failed: number };
  recent: EventItem[];
  version: string;
}
export interface EventItem {
  time: string; ts: number; ok: boolean; msg: string; origin: string; voice: string;
  chars: number; elapsed_ms: number; queue_position: number; kind: string; segments: number;
  text?: string; text_state?: string;
}
export interface Voice { name: string; file: string; text: string; language: string; enabled: boolean; markup?: boolean; source: string }
export interface Server { index: number; name: string; type: string; url: string; enabled: boolean; timeout: number }
export interface Session { origin: string; on: boolean; voice: string; send_mode: string; nickname: string; group: string; updated: string }
