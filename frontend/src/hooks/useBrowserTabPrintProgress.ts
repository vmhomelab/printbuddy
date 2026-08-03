import { useEffect, useRef, useState } from 'react';

type PrinterStatusDetail = {
  printer_id?: number;
  data?: {
    progress?: number | string | null;
    remaining_time?: number | string | null;
    state?: string | null;
    status?: string | null;
  };
};

type ActivePrintStatus = {
  printerId: number;
  progress: number;
  remainingTime: number | null;
  state: string;
};

const DEFAULT_TITLE = 'Printbuddy';

function parseNumber(value: number | string | null | undefined): number | null {
  if (value === null || value === undefined || value === '') return null;
  const parsed = Number(value);
  return Number.isFinite(parsed) ? parsed : null;
}

function isActivePrint(status: ActivePrintStatus): boolean {
  const state = status.state.toLowerCase();
  if (status.progress < 0 || status.progress >= 100) return false;
  if (['idle', 'offline', 'finish', 'finished', 'completed', 'failed', 'cancelled', 'canceled'].includes(state)) {
    return false;
  }
  return state.includes('print') || state.includes('run') || state.includes('pause') || status.progress > 0;
}

function chooseDisplayedPrint(statuses: Map<number, ActivePrintStatus>): ActivePrintStatus | null {
  const active = Array.from(statuses.values()).filter(isActivePrint);
  if (active.length === 0) return null;

  return active.sort((a, b) => {
    const aRemaining = a.remainingTime ?? Number.POSITIVE_INFINITY;
    const bRemaining = b.remainingTime ?? Number.POSITIVE_INFINITY;
    if (aRemaining !== bRemaining) return aRemaining - bRemaining;
    return b.progress - a.progress;
  })[0];
}

function buildProgressFavicon(progress: number): string {
  const clamped = Math.max(0, Math.min(100, Math.round(progress)));
  const radius = 42;
  const circumference = 2 * Math.PI * radius;
  const dash = (clamped / 100) * circumference;
  const svg = `
    <svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 100 100">
      <circle cx="50" cy="50" r="42" fill="#111827" stroke="#374151" stroke-width="10"/>
      <circle cx="50" cy="50" r="42" fill="none" stroke="#10b981" stroke-width="10"
        stroke-linecap="round" stroke-dasharray="${dash} ${circumference - dash}"
        transform="rotate(-90 50 50)"/>
      <text x="50" y="57" text-anchor="middle" font-family="Arial, sans-serif" font-size="28" font-weight="700" fill="#ffffff">${clamped}</text>
    </svg>`;
  return `data:image/svg+xml,${encodeURIComponent(svg)}`;
}

function getOrCreateFavicon(): HTMLLinkElement | null {
  if (typeof document === 'undefined') return null;
  let icon = document.querySelector<HTMLLinkElement>('link[rel="icon"]');
  if (!icon) {
    icon = document.createElement('link');
    icon.rel = 'icon';
    document.head.appendChild(icon);
  }
  return icon;
}

export function useBrowserTabPrintProgress() {
  const statusesRef = useRef<Map<number, ActivePrintStatus>>(new Map());
  const originalTitleRef = useRef<string | null>(null);
  const originalFaviconRef = useRef<string | null>(null);
  const [version, setVersion] = useState(0);

  useEffect(() => {
    if (typeof document === 'undefined') return;
    const currentTitle = document.title || DEFAULT_TITLE;
    originalTitleRef.current = /^\d+% · Printbuddy$/.test(currentTitle) ? DEFAULT_TITLE : currentTitle;
    const icon = document.querySelector<HTMLLinkElement>('link[rel="icon"]');
    originalFaviconRef.current = icon?.href ?? null;
  }, []);

  useEffect(() => {
    const handleStatus = (event: Event) => {
      const detail = (event as CustomEvent<PrinterStatusDetail>).detail;
      if (!detail?.printer_id || !detail.data) return;

      const progress = parseNumber(detail.data.progress);
      const remainingTime = parseNumber(detail.data.remaining_time);
      const state = String(detail.data.state ?? detail.data.status ?? '').trim();

      if (progress === null) {
        statusesRef.current.delete(detail.printer_id);
      } else {
        statusesRef.current.set(detail.printer_id, {
          printerId: detail.printer_id,
          progress,
          remainingTime,
          state,
        });
      }
      setVersion((current) => current + 1);
    };

    window.addEventListener('printbuddy-printer-status', handleStatus);
    return () => window.removeEventListener('printbuddy-printer-status', handleStatus);
  }, []);

  useEffect(() => {
    if (typeof document === 'undefined') return;
    const displayed = chooseDisplayedPrint(statusesRef.current);
    const icon = getOrCreateFavicon();

    if (!displayed) {
      document.title = originalTitleRef.current || DEFAULT_TITLE;
      if (icon && originalFaviconRef.current) icon.href = originalFaviconRef.current;
      return;
    }

    const progress = Math.max(0, Math.min(100, Math.round(displayed.progress)));
    document.title = `${progress}% · ${DEFAULT_TITLE}`;
    if (icon) icon.href = buildProgressFavicon(progress);
  }, [version]);

  useEffect(() => {
    return () => {
      if (typeof document === 'undefined') return;
      document.title = originalTitleRef.current || DEFAULT_TITLE;
      const icon = document.querySelector<HTMLLinkElement>('link[rel="icon"]');
      if (icon && originalFaviconRef.current) icon.href = originalFaviconRef.current;
    };
  }, []);
}
