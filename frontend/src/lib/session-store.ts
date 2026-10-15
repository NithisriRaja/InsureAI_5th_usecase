// Session id pointer in localStorage (identity itself lives server-side in SQLite).
// Shared by all tabs through the `storage` event.

const KEY = "ipoc.session";
const listeners = new Set<() => void>();

function read(): string | null {
  try {
    return localStorage.getItem(KEY);
  } catch {
    return null;
  }
}

export const sessionStore = {
  get: read,
  getServer: (): string | null => null,
  set(token: string | null) {
    try {
      if (token) localStorage.setItem(KEY, token);
      else localStorage.removeItem(KEY);
    } catch {
      // storage blocked: session lasts for this page only
    }
    listeners.forEach((l) => l());
  },
  subscribe(l: () => void) {
    listeners.add(l);
    const onStorage = (e: StorageEvent) => e.key === KEY && l();
    window.addEventListener("storage", onStorage);
    return () => {
      listeners.delete(l);
      window.removeEventListener("storage", onStorage);
    };
  },
};
