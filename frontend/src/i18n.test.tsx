import { afterEach, beforeEach, expect, test, vi } from 'vitest';
import { act, cleanup, render, screen } from '@testing-library/react';
import { getLocale, setLocale, translate, useI18n } from './i18n';
beforeEach(()=>{ const values=new Map<string,string>(); vi.stubGlobal('localStorage',{getItem:(key:string)=>values.get(key)??null,setItem:(key:string,value:string)=>values.set(key,value),clear:()=>values.clear()}); });
function LanguageProbe() { const {locale,t}=useI18n(); return <span>{locale}:{t('保存')}</span>; }
afterEach(()=>{cleanup();setLocale('zh-CN');window.localStorage.clear();vi.unstubAllGlobals();});
test('language changes update subscribers and persist without translating unknown data',()=>{
  render(<LanguageProbe/>);
  expect(screen.getByText('zh-CN:保存')).toBeInTheDocument();
  act(()=>setLocale('en-US'));
  expect(screen.getByText('en-US:Save')).toBeInTheDocument();
  expect(window.localStorage.getItem('gpupm.locale')).toBe('en-US');
  expect(document.documentElement.lang).toBe('en');
  expect(document.title).toBe('gpuPM · Server management');
  expect(translate('/data/模型A')).toBe('/data/模型A');
  expect(translate('unknown-future-code')).toBe('unknown-future-code');
  expect(translate('__proto__')).toBe('__proto__');
});
test('unsupported preference falls back to Chinese across tabs',()=>{
  render(<LanguageProbe/>);
  act(()=>setLocale('en-US'));
  window.localStorage.setItem('gpupm.locale','invalid');
  act(()=>window.dispatchEvent(new StorageEvent('storage',{key:'gpupm.locale',newValue:'invalid'})));
  expect(getLocale()).toBe('zh-CN');
  expect(screen.getByText('zh-CN:保存')).toBeInTheDocument();
});
test('language selection still works when browser storage is unavailable',()=>{
  vi.spyOn(window.localStorage,'setItem').mockImplementation(()=>{throw new Error('blocked');});
  setLocale('en-US');
  expect(getLocale()).toBe('en-US');
});
