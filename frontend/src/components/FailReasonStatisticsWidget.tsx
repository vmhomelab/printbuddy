import { Fragment, useState } from 'react';
import { useTranslation } from 'react-i18next';
import { useQuery } from '@tanstack/react-query';
import { ChevronDown, ChevronRight, Loader2 } from 'lucide-react';
import { api } from '../api/client';
import type { CustomFailureReasonStats, CustomFailureReport } from '../api/client';
import { formatDuration } from '../utils/date';
import { FailureReasonIcon } from './FailureReasonIcon';
import {
  customFailureReasonTitle,
  formatGrams,
  formatIsoDay,
  normalizeFilamentColor,
  totalMaterialGrams,
} from '../utils/customFailure';

interface FailReasonStatisticsWidgetProps {
  dateFrom?: string;
  dateTo?: string;
}

/**
 * "Fail reason statistics": user-reported failure reasons ("Report failed print")
 * per reason, expandable to the affected prints. Independent of the existing
 * Failure Analysis widget, which uses the automatic failure_reason.
 */
export function FailReasonStatisticsWidget({ dateFrom, dateTo }: FailReasonStatisticsWidgetProps) {
  const { t } = useTranslation();
  const [expanded, setExpanded] = useState<Set<string>>(new Set());

  const { data: stats, isLoading } = useQuery({
    queryKey: ['customFailureStats', dateFrom, dateTo],
    queryFn: () => api.getCustomFailureStats({ dateFrom, dateTo }),
  });
  // Hidden reasons included: their earlier reports still show up here.
  const { data: reasons = [] } = useQuery({
    queryKey: ['customFailureReasons'],
    queryFn: () => api.getCustomFailureReasons({ includeHidden: true }),
  });

  if (isLoading) {
    return (
      <div className="flex justify-center py-4">
        <Loader2 className="w-6 h-6 text-bambu-green animate-spin" />
      </div>
    );
  }
  if (!stats || stats.total === 0) {
    return <p className="text-bambu-gray text-center py-4">{t('customFailure.widget.noReports')}</p>;
  }

  const toggle = (reason: string) =>
    setExpanded((prev) => {
      const next = new Set(prev);
      if (next.has(reason)) next.delete(reason);
      else next.add(reason);
      return next;
    });

  return (
    <div className="overflow-x-auto">
      <p className="text-xs text-bambu-gray mb-2">{t('customFailure.widget.totalReports', { count: stats.total })}</p>
      <table className="w-full text-sm">
        <thead>
          <tr className="text-left text-bambu-gray border-b border-bambu-dark-tertiary">
            <th className="py-2 pr-2 font-medium">{t('customFailure.widget.colReason')}</th>
            <th className="py-2 px-2 font-medium text-right w-20">{t('customFailure.widget.colCount')}</th>
            <th className="py-2 pl-2 font-medium text-right w-20">{t('customFailure.widget.colPercent')}</th>
          </tr>
        </thead>
        <tbody>
          {stats.reasons.map((row) => {
            const isOpen = expanded.has(row.reason);
            const reason = reasons.find((r) => r.code === row.reason);
            const canOpen = row.count > 0;
            return (
              <Fragment key={row.reason}>
                <tr
                  className={`border-b border-bambu-dark-tertiary/60 ${canOpen ? 'cursor-pointer hover:bg-bambu-dark/40' : 'opacity-50'}`}
                  onClick={canOpen ? () => toggle(row.reason) : undefined}
                  aria-expanded={canOpen ? isOpen : undefined}
                >
                  <td className="py-2 pr-2 text-white">
                    <span className="inline-flex items-center gap-2">
                      {canOpen ? (
                        isOpen ? <ChevronDown className="w-4 h-4" /> : <ChevronRight className="w-4 h-4" />
                      ) : (
                        <span className="w-4" />
                      )}
                      <FailureReasonIcon reason={reason} className="w-5 h-5 text-bambu-gray flex-shrink-0" />
                      {customFailureReasonTitle(t, row.reason, reason)}
                    </span>
                  </td>
                  <td className="py-2 px-2 text-right text-white">{row.count}</td>
                  <td className="py-2 pl-2 text-right text-white">{row.percent.toFixed(1)}</td>
                </tr>
                {isOpen && (
                  <tr>
                    <td colSpan={3} className="pb-3 pl-5">
                      <AffectedPrints row={row} dateFrom={dateFrom} dateTo={dateTo} />
                    </td>
                  </tr>
                )}
              </Fragment>
            );
          })}
        </tbody>
      </table>
    </div>
  );
}

function AffectedPrints({
  row,
  dateFrom,
  dateTo,
}: {
  row: CustomFailureReasonStats;
  dateFrom?: string;
  dateTo?: string;
}) {
  const { t } = useTranslation();
  const [showAll, setShowAll] = useState(false);

  const { data: all, isLoading } = useQuery({
    queryKey: ['customFailureReports', row.reason, dateFrom, dateTo],
    queryFn: () => api.getCustomFailureReports({ reason: row.reason, dateFrom, dateTo }),
    enabled: showAll,
  });

  const entries = showAll && all ? all : row.latest;
  const hiddenCount = row.count - row.latest.length;

  return (
    <table className="w-full text-xs mt-1">
      <thead>
        <tr className="text-left text-bambu-gray">
          <th className="py-1 pr-2 font-medium">{t('customFailure.widget.colPrinter')}</th>
          <th className="py-1 px-2 font-medium whitespace-nowrap">{t('customFailure.widget.colDate')}</th>
          <th className="py-1 px-2 font-medium">{t('customFailure.widget.colMaterial')}</th>
          <th className="py-1 px-2 font-medium text-right whitespace-nowrap">{t('customFailure.widget.colAmount')}</th>
          <th className="py-1 px-2 font-medium text-right whitespace-nowrap">{t('customFailure.widget.colTime')}</th>
          <th className="py-1 px-2 font-medium">{t('customFailure.widget.colPrintName')}</th>
          <th className="py-1 pl-2 font-medium">{t('customFailure.widget.colComment')}</th>
        </tr>
      </thead>
      <tbody>
        {entries.map((report) => (
          <AffectedPrintRow key={report.id} report={report} />
        ))}
        {!showAll && hiddenCount > 0 && (
          <tr>
            <td colSpan={7} className="py-1">
              <button
                type="button"
                className="italic text-bambu-green hover:underline"
                onClick={() => setShowAll(true)}
              >
                {t('customFailure.widget.showAll', { count: row.count })}
              </button>
            </td>
          </tr>
        )}
        {showAll && isLoading && (
          <tr>
            <td colSpan={7} className="py-1">
              <Loader2 className="w-4 h-4 text-bambu-green animate-spin" />
            </td>
          </tr>
        )}
      </tbody>
    </table>
  );
}

function AffectedPrintRow({ report }: { report: CustomFailureReport }) {
  const { t } = useTranslation();
  const grams = totalMaterialGrams(report.materials, report.filament_used_grams);
  const multiMaterial = report.materials.length > 1;

  return (
    <tr className="border-t border-bambu-dark-tertiary/40 align-top text-white">
      <td className="py-1 pr-2">{report.printer_name || '–'}</td>
      <td className="py-1 px-2 whitespace-nowrap">{formatIsoDay(report.print_date)}</td>
      <td className="py-1 px-2">
        {report.materials.length === 0 ? (
          '–'
        ) : (
          <div className="flex flex-col gap-0.5">
            {report.materials.map((material, index) => {
              const color = normalizeFilamentColor(material.color);
              return (
                <span key={index} className="inline-flex items-center gap-1 whitespace-nowrap">
                  {color && (
                    <span
                      className="inline-block w-3 h-3 rounded-full border border-white/30"
                      style={{ backgroundColor: color }}
                      title={color}
                    />
                  )}
                  {material.type || '?'}
                  {multiMaterial && material.grams != null && (
                    <span className="text-bambu-gray">{formatGrams(material.grams)}</span>
                  )}
                </span>
              );
            })}
          </div>
        )}
      </td>
      <td className="py-1 px-2 text-right whitespace-nowrap">{formatGrams(grams)}</td>
      <td className="py-1 px-2 text-right whitespace-nowrap">
        {report.print_time_seconds != null ? formatDuration(report.print_time_seconds) : '–'}
      </td>
      <td className="py-1 px-2">
        <span className="inline-flex items-center gap-2" title={report.filename ?? undefined}>
          {report.has_thumbnail && report.archive_id != null && (
            <img
              src={api.getArchiveThumbnail(report.archive_id)}
              alt=""
              loading="lazy"
              className="w-8 h-8 object-contain rounded bg-bambu-dark flex-shrink-0"
            />
          )}
          <span className="break-all">{report.print_name || report.filename || '–'}</span>
        </span>
      </td>
      <td className="py-1 pl-2 text-bambu-gray">
        {report.comment && <div className="whitespace-pre-line">{report.comment}</div>}
        {report.reported_by && (
          <div className="italic">{t('customFailure.widget.reportedByLabel', { name: report.reported_by })}</div>
        )}
      </td>
    </tr>
  );
}
