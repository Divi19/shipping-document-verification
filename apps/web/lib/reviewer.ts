/**
 * The reviewer's name, remembered per browser so it need not be typed for every
 * decision. Storage can be unavailable (private windows, blocked site data), so
 * an in-memory copy keeps the page working without it.
 */

const STORAGE_KEY = "sdoc.reviewer";
const listeners = new Set<() => void>();
let memory = "";

export function subscribeReviewer(listener: () => void): () => void {
  listeners.add(listener);
  window.addEventListener("storage", listener);
  return () => {
    listeners.delete(listener);
    window.removeEventListener("storage", listener);
  };
}

export function readReviewer(): string {
  try {
    return window.localStorage.getItem(STORAGE_KEY) ?? memory;
  } catch {
    return memory;
  }
}

export function writeReviewer(name: string): void {
  memory = name;
  try {
    window.localStorage.setItem(STORAGE_KEY, name);
  } catch {
    // Storage is optional; the in-memory copy is enough for this session.
  }
  listeners.forEach((listener) => listener());
}
