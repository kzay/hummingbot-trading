import { useRef, useState, useEffect } from "react";

/**
 * Returns a transient CSS class ("flash-up" or "flash-down") for 400ms
 * whenever `value` changes direction. Useful for price/PnL flashing.
 */
export function useFlashClass(value: number | null | undefined): string {
  const prevRef = useRef<number | null>(null);
  const [cls, setCls] = useState("");
  const timerRef = useRef<ReturnType<typeof setTimeout> | null>(null);

  useEffect(() => {
    const num = typeof value === "number" && Number.isFinite(value) ? value : null;
    if (num === null || prevRef.current === null) {
      prevRef.current = num;
      return;
    }
    if (num === prevRef.current) return;

    const direction = num > prevRef.current ? "flash-up" : "flash-down";
    prevRef.current = num;

    queueMicrotask(() => {
      setCls(direction);
      if (timerRef.current !== null) clearTimeout(timerRef.current);
      timerRef.current = setTimeout(() => setCls(""), 400);
    });

    return () => { if (timerRef.current !== null) clearTimeout(timerRef.current); };
  }, [value]);

  return cls;
}
