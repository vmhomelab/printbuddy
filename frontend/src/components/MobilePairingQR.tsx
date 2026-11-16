import { useEffect, useState } from 'react';
import { useTranslation } from 'react-i18next';
import QRCode from 'qrcode';
import { Smartphone } from 'lucide-react';

import { buildPairingUri, currentServerUrl, isLocalOnly } from '../utils/mobilePairing';

/**
 * Pairing QR code for the Printbuddy mobile app, shown next to a newly created
 * API key. The phone's camera app opens the app straight from it; the app
 * always asks before connecting. Rendered locally, so the key never leaves the
 * browser again.
 */
export function MobilePairingQR({ apiKey, serverUrl = currentServerUrl() }: { apiKey: string; serverUrl?: string }) {
  const { t } = useTranslation();
  const [dataUrl, setDataUrl] = useState<string | null>(null);
  const isLocal = isLocalOnly(serverUrl);

  useEffect(() => {
    let cancelled = false;
    QRCode.toDataURL(buildPairingUri(serverUrl, apiKey), { margin: 1, width: 220, errorCorrectionLevel: 'M' })
      .then((url) => {
        if (!cancelled) setDataUrl(url);
      })
      .catch(() => {
        if (!cancelled) setDataUrl(null);
      });
    return () => {
      cancelled = true;
    };
  }, [apiKey, serverUrl]);

  return (
    <div className="mt-4 flex flex-col sm:flex-row gap-4 items-start" data-testid="mobile-pairing-qr">
      {dataUrl && (
        <img
          src={dataUrl}
          alt={t('settings.mobilePairing.qrAlt')}
          width={160}
          height={160}
          className="rounded-lg bg-white p-1 flex-shrink-0"
        />
      )}
      <div className="text-sm text-bambu-gray space-y-1 min-w-0">
        <p className="text-white font-medium flex items-center gap-2">
          <Smartphone className="w-4 h-4" />
          {t('settings.mobilePairing.title')}
        </p>
        <p>{t('settings.mobilePairing.description')}</p>
        <p className="font-mono text-xs break-all">{serverUrl}</p>
        {isLocal && <p className="text-yellow-500">{t('settings.mobilePairing.localhostWarning')}</p>}
      </div>
    </div>
  );
}
