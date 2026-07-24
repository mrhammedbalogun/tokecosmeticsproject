import "@testing-library/jest-dom/vitest";

// jsdom under Node 26 does not expose a working `localStorage` (Node's native one is
// gated behind --localstorage-file, and jsdom leaves it undefined for opaque origins).
// A tiny in-memory Storage keeps browser-storage code (e.g. recently-viewed) testable.
if (typeof globalThis.localStorage === "undefined") {
  class MemoryStorage implements Storage {
    private store = new Map<string, string>();
    get length(): number { return this.store.size; }
    clear(): void { this.store.clear(); }
    getItem(key: string): string | null {
      return this.store.has(key) ? (this.store.get(key) as string) : null;
    }
    key(index: number): string | null {
      return Array.from(this.store.keys())[index] ?? null;
    }
    removeItem(key: string): void { this.store.delete(key); }
    setItem(key: string, value: string): void { this.store.set(key, String(value)); }
  }
  const storage = new MemoryStorage();
  Object.defineProperty(globalThis, "localStorage", { value: storage, configurable: true });
  if (typeof window !== "undefined") {
    Object.defineProperty(window, "localStorage", { value: storage, configurable: true });
  }
}
