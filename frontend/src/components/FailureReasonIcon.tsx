import { TriangleAlert } from 'lucide-react';
import { api } from '../api/client';
import type { CustomFailureReason } from '../api/client';
import { FAILURE_REASON_ICONS } from '../utils/failureReasonIcons';

interface FailureReasonIconProps {
  reason: Pick<CustomFailureReason, 'id' | 'icon' | 'custom_icon_filename'> | undefined;
  className?: string;
}

/** A reason's uploaded image if it has one, otherwise its built-in icon. */
export function FailureReasonIcon({ reason, className = 'w-6 h-6' }: FailureReasonIconProps) {
  if (reason?.custom_icon_filename) {
    return (
      <img
        src={api.getCustomFailureReasonIconUrl(reason.id, reason.custom_icon_filename)}
        alt=""
        className={`${className} object-contain`}
      />
    );
  }
  const Icon = (reason?.icon && FAILURE_REASON_ICONS[reason.icon]) || TriangleAlert;
  return <Icon className={className} />;
}
