import "@testing-library/jest-dom/vitest";
import { vi } from "vitest";
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
