import '@testing-library/jest-dom/vitest';
import { cleanup } from '@testing-library/react';
import { afterEach, vi } from 'vitest';

// Every test starts from a clean DOM; a leaked component from the previous test
// makes failures appear in the wrong place.
afterEach(() => {
  cleanup();
  vi.clearAllMocks();
});

// jsdom implements neither, and components that use them would throw.
globalThis.matchMedia ??= ((query: string) => ({
  matches: false, media: query, onchange: null,
  addEventListener: vi.fn(), removeEventListener: vi.fn(), dispatchEvent: vi.fn(),
  addListener: vi.fn(), removeListener: vi.fn(),
})) as unknown as typeof globalThis.matchMedia;

globalThis.ResizeObserver ??= class {
  observe() {} unobserve() {} disconnect() {}
} as unknown as typeof ResizeObserver;
