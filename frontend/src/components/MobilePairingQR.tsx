import { useTranslation } from 'react-i18next';
import { QRCodeSVG } from 'qrcode.react';
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
  const isLocal = isLocalOnly(serverUrl);

  return (
    <div className="mt-4 flex flex-col sm:flex-row gap-4 items-start" data-testid="mobile-pairing-qr">
      {/* qrcode.react, as the API key QR modal uses: no second QR library. */}
      <QRCodeSVG
        value={buildPairingUri(serverUrl, apiKey)}
        size={160}
        level="M"
        marginSize={1}
        role="img"
        aria-label={t('settings.mobilePairing.qrAlt')}
        className="rounded-lg bg-white p-1 flex-shrink-0"
      />
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
