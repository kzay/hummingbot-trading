/** If stored API base uses a different loopback host than the page, rewrite (localhost vs 127.0.0.1). */
export function alignLoopbackApiBaseWithPageHost(storageKey = "hbV2ApiBase"): void {
  try {
    const stored = window.localStorage.getItem(storageKey);
    if (!stored?.trim()) return;
    let url: URL;
    try {
      url = new URL(stored.trim());
    } catch {
      return;
    }
    const loopback = new Set(["localhost", "127.0.0.1", "[::1]"]);
    const pageHost = window.location.hostname;
    if (!loopback.has(pageHost) || !loopback.has(url.hostname)) return;
    if (url.hostname === pageHost) return;
    url.hostname = pageHost;
    window.localStorage.setItem(storageKey, url.origin);
  } catch {
    // ignore
  }
}

export function readLocalStorage(key: string, fallback = ""): string {
  try {
    const value = window.localStorage.getItem(key);
    return value ?? fallback;
  } catch {
    return fallback;
  }
}

export function writeLocalStorage(key: string, value: string): void {
  try {
    window.localStorage.setItem(key, value);
  } catch {
    // Ignore storage failures in hardened/private browser sessions.
  }
}

export function readSessionStorage(key: string, fallback = ""): string {
  try {
    const value = window.sessionStorage.getItem(key);
    return value ?? fallback;
  } catch {
    return fallback;
  }
}

export function writeSessionStorage(key: string, value: string): void {
  try {
    if (!value) {
      window.sessionStorage.removeItem(key);
      return;
    }
    window.sessionStorage.setItem(key, value);
  } catch {
    // Ignore storage failures in hardened/private browser sessions.
  }
}
