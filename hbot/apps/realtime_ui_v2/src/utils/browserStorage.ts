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
