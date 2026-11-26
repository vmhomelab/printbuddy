import { Lock, LockOpen, MapPin, X } from 'lucide-react';
import { useTranslation } from 'react-i18next';

interface LocationLockButtonProps {
  locked: boolean;
  /** False while "all locations" is selected — nothing to lock yet. */
  canLock: boolean;
  onToggle: (locked: boolean) => void;
  className?: string;
}

/** Lock toggle placed next to a location dropdown. */
export function LocationLockButton({ locked, canLock, onToggle, className = '' }: LocationLockButtonProps) {
  const { t } = useTranslation();
  const disabled = !locked && !canLock;
  const label = locked
    ? t('locationFilter.unlock')
    : canLock
      ? t('locationFilter.lock')
      : t('locationFilter.selectToLock');

  return (
    <button
      type="button"
      onClick={() => onToggle(!locked)}
      disabled={disabled}
      aria-pressed={locked}
      aria-label={label}
      title={label}
      className={`h-8 w-8 flex-shrink-0 rounded-lg border flex items-center justify-center transition-colors ${
        locked
          ? 'bg-bambu-green border-bambu-green text-white'
          : 'bg-bambu-dark border-bambu-dark-tertiary text-bambu-gray hover:text-white hover:bg-bambu-dark-tertiary'
      } disabled:opacity-40 disabled:cursor-not-allowed disabled:hover:bg-bambu-dark disabled:hover:text-bambu-gray ${className}`}
    >
      {locked ? <Lock className="w-4 h-4" /> : <LockOpen className="w-4 h-4" />}
    </button>
  );
}

interface LocationLockBadgeProps {
  location: string;
  onUnlock: () => void;
  className?: string;
}

/** Hint shown while a location is locked, so missing printers aren't a surprise. */
export function LocationLockBadge({ location, onUnlock, className = '' }: LocationLockBadgeProps) {
  const { t } = useTranslation();
  return (
    <span
      className={`inline-flex items-center gap-1.5 rounded-full border border-bambu-green/40 bg-bambu-green/10 pl-2.5 pr-1 py-0.5 text-xs font-medium text-bambu-green ${className}`}
      title={t('locationFilter.lockedHint')}
      data-testid="location-lock-badge"
    >
      <MapPin className="w-3.5 h-3.5" />
      <span>{t('locationFilter.badge', { location })}</span>
      <Lock className="w-3 h-3" />
      <button
        type="button"
        onClick={onUnlock}
        className="ml-0.5 rounded-full p-0.5 hover:bg-bambu-green/20"
        aria-label={t('locationFilter.unlock')}
        title={t('locationFilter.unlock')}
      >
        <X className="w-3 h-3" />
      </button>
    </span>
  );
}
