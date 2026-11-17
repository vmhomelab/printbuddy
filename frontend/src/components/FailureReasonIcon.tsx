import { TriangleAlert } from 'lucide-react';
import type { CustomFailureReason } from '../api/client';
import { FAILURE_REASON_ICONS } from '../utils/failureReasonIcons';

interface FailureReasonIconProps {
  reason: Pick<CustomFailureReason, 'icon'> | undefined;
  className?: string;
}

/** A reason's built-in icon. */
export function FailureReasonIcon({ reason, className = 'w-6 h-6' }: FailureReasonIconProps) {
  const Icon = (reason?.icon && FAILURE_REASON_ICONS[reason.icon]) || TriangleAlert;
  return <Icon className={className} />;
}
