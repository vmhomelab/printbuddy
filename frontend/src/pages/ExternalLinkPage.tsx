import { useCallback, useEffect, useRef, type RefObject } from 'react';
import { useNavigate, useParams } from 'react-router-dom';
import { useQuery } from '@tanstack/react-query';
import { Loader2, AlertTriangle } from 'lucide-react';
import { useTranslation } from 'react-i18next';
import { api } from '../api/client';
import { useTheme } from '../contexts/ThemeContext';

export function ExternalLinkPage() {
  const { t } = useTranslation();
  const { id } = useParams<{ id: string }>();
  const { mode } = useTheme();
  const iframeRef = useRef<HTMLIFrameElement>(null);
  const sendTheme = useThemeMessenger(iframeRef);
  useNavigateMessages(iframeRef);

  const { data: link, isLoading, error } = useQuery({
    queryKey: ['external-link', id],
    queryFn: () => api.getExternalLink(Number(id)),
    enabled: !!id,
  });

  if (isLoading) {
    return (
      <div className="flex items-center justify-center h-full">
        <Loader2 className="w-8 h-8 text-bambu-green animate-spin" />
      </div>
    );
  }

  if (error || !link) {
    return (
      <div className="flex flex-col items-center justify-center h-full gap-4 text-bambu-gray">
        <AlertTriangle className="w-12 h-12" />
        <p>{t('common.linkNotFound')}</p>
      </div>
    );
  }

  return (
    <iframe
      ref={iframeRef}
      src={link.url}
      onLoad={sendTheme}
      className="h-full w-full border-0"
      style={{ colorScheme: mode }}
      title={link.name}
      sandbox="allow-scripts allow-same-origin allow-forms allow-popups allow-popups-to-escape-sandbox"
    />
  );
}

/**
 * Tell the framed page which theme Printbuddy is showing, so an app built to
 * sit in the sidebar (Printbuddy Orders) can match it. Sent when the page
 * loads, when the theme changes, and when the page asks for it. Only to the
 * link's own origin, and it carries nothing but the theme names, plus
 * ``canNavigate``: this Printbuddy takes the page's navigate requests (see
 * useNavigateMessages), so the page can tell it apart from older builds.
 */
function useThemeMessenger(iframeRef: RefObject<HTMLIFrameElement | null>) {
  const { resolvedMode, darkStyle, darkBackground, darkAccent, lightStyle, lightBackground, lightAccent } = useTheme();
  const dark = resolvedMode === 'dark';
  const style = dark ? darkStyle : lightStyle;
  const background = dark ? darkBackground : lightBackground;
  const accent = dark ? darkAccent : lightAccent;

  const sendTheme = useCallback(() => {
    const frame = iframeRef.current;
    if (!frame?.contentWindow) return;
    let origin: string;
    try {
      origin = new URL(frame.src).origin;
    } catch {
      return;
    }
    frame.contentWindow.postMessage(
      { type: 'printbuddy:theme', mode: resolvedMode, style, background, accent, canNavigate: true },
      origin,
    );
  }, [iframeRef, resolvedMode, style, background, accent]);

  useEffect(() => sendTheme(), [sendTheme]);

  useEffect(() => {
    const onMessage = (e: MessageEvent) => {
      if (e.source === iframeRef.current?.contentWindow && e.data?.type === 'printbuddy:theme-request') sendTheme();
    };
    window.addEventListener('message', onMessage);
    return () => window.removeEventListener('message', onMessage);
  }, [iframeRef, sendTheme]);

  return sendTheme;
}

/** Longest in-app path a framed page may ask for; real ones are far shorter. */
const MAX_NAVIGATE_PATH = 512;

/**
 * Let the framed page open a Printbuddy page in place, e.g. Printbuddy Orders'
 * "In Printbuddy" link to a batch. The sandbox rightly doesn't let the frame
 * navigate the top window itself, so it asks:
 * ``{type: 'printbuddy:navigate', path: '/queue?batch=12'}``.
 *
 * Accepted only from the frame, only from the link's own origin, and only for
 * a path inside Printbuddy: anything else is ignored, so the request can never
 * lead anywhere a typed address bar couldn't. The theme message's
 * ``canNavigate`` tells the page it can ask; without it the page opens a new
 * tab instead.
 */
function useNavigateMessages(iframeRef: RefObject<HTMLIFrameElement | null>) {
  const navigate = useNavigate();

  useEffect(() => {
    const onMessage = (e: MessageEvent) => {
      const frame = iframeRef.current;
      if (!frame?.contentWindow || e.source !== frame.contentWindow) return;
      if (e.data?.type !== 'printbuddy:navigate') return;
      let origin: string;
      try {
        origin = new URL(frame.src).origin;
      } catch {
        return;
      }
      if (e.origin !== origin) return;
      const target = inAppPath(e.data.path);
      if (target === null) return;
      navigate(target);
    };
    window.addEventListener('message', onMessage);
    return () => window.removeEventListener('message', onMessage);
  }, [iframeRef, navigate]);
}

/** The path, query and hash of a same-origin path, or null for anything else. */
function inAppPath(path: unknown): string | null {
  if (typeof path !== 'string' || path.length > MAX_NAVIGATE_PATH) return null;
  // "//host" and "/\\host" are other sites to a browser; only a plain absolute path is in-app.
  if (!path.startsWith('/') || path.startsWith('//') || path.includes('\\')) return null;
  let url: URL;
  try {
    url = new URL(path, window.location.origin);
  } catch {
    return null;
  }
  if (url.origin !== window.location.origin) return null;
  return url.pathname + url.search + url.hash;
}
