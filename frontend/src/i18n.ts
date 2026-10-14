import { useSyncExternalStore } from 'react';
import { messages } from './messages';
export type Locale = 'zh-CN' | 'en-US';
const preferenceKey = 'gpupm.locale';
function storedLocale(): Locale {
  try { return window.localStorage.getItem(preferenceKey) === 'en-US' ? 'en-US' : 'zh-CN'; }
  catch { return 'zh-CN'; }
}
let locale = storedLocale();
const listeners = new Set<() => void>();
export const getLocale = () => locale;
function applyLocale(next: Locale) {
  locale = next;
  if (typeof document !== 'undefined') document.documentElement.lang = next === 'en-US' ? 'en' : 'zh-CN';
  if (typeof document !== 'undefined') document.title = translate('gpuPM · 服务器管理');
  listeners.forEach(listener => listener());
}
export function setLocale(next: Locale) {
  if (next !== 'zh-CN' && next !== 'en-US') return;
  try { window.localStorage.setItem(preferenceKey,next); } catch { /* Browser storage can be unavailable. */ }
  applyLocale(next);
}
function storageChanged(event: StorageEvent) {
  if (event.key === preferenceKey || event.key === null) applyLocale(storedLocale());
}
function subscribe(listener: () => void) {
  if (listeners.size === 0) window.addEventListener('storage',storageChanged);
  listeners.add(listener);
  return () => {
    listeners.delete(listener);
    if (listeners.size === 0) window.removeEventListener('storage',storageChanged);
  };
}
export function translate(text: string, values: Record<string,string|number> = {}) {
  let result = locale === 'en-US' && Object.hasOwn(messages,text) ? messages[text] : text;
  for (const [key,value] of Object.entries(values)) result = result.replaceAll(`{${key}}`,String(value));
  return result;
}
export function useI18n() {
  const selected = useSyncExternalStore(subscribe,getLocale,()=> 'zh-CN' as const);
  return {locale:selected,setLocale,t:translate};
}
if (typeof document !== 'undefined') {
  document.documentElement.lang = locale === 'en-US' ? 'en' : 'zh-CN';
  document.title = translate('gpuPM · 服务器管理');
}
