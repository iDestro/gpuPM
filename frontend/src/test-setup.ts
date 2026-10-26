import "@testing-library/jest-dom/vitest";
import { configure } from "@testing-library/react";
import { vi } from "vitest";
// Ant Design portal rendering can exceed the one-second default on busy CI hosts.
configure({ asyncUtilTimeout: 5000 });
Object.defineProperty(window, "matchMedia", {
  value: vi
    .fn()
    .mockImplementation(() => ({
      matches: false,
      addListener: vi.fn(),
      removeListener: vi.fn(),
      addEventListener: vi.fn(),
      removeEventListener: vi.fn(),
    })),
});
globalThis.ResizeObserver = class {
  observe() {}
  unobserve() {}
  disconnect() {}
};

const getStyle = window.getComputedStyle;
window.getComputedStyle = (element) => getStyle(element);
