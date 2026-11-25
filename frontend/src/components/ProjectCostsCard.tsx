import { useState } from 'react';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { useTranslation } from 'react-i18next';
import { AlertTriangle, Receipt } from 'lucide-react';
import { api } from '../api/client';
import type { CostEnergyRow, CostMaterialRow, CostTotals, CostWarning, ProjectCosts } from '../api/client';
import { Card, CardContent } from './Card';

type Mode = 'planned' | 'incurred' | 'remaining';

const SEGMENTS: Array<{ key: keyof Omit<CostTotals, 'total'>; color: string }> = [
  { key: 'material', color: '#00ae42' },
  { key: 'energy', color: '#facc15' },
  { key: 'bom', color: '#60a5fa' },
];

function useMoney(currency: string) {
  const { i18n } = useTranslation();
  let formatter: Intl.NumberFormat | null = null;
  try {
    formatter = new Intl.NumberFormat(i18n.language, { style: 'currency', currency: currency || 'USD' });
  } catch {
    formatter = null;
  }
  return (value: number) => (formatter ? formatter.format(value) : `${value.toFixed(2)} ${currency}`);
}

function formatHours(hours: number): string {
  if (!hours) return '–';
  const minutes = Math.round(hours * 60);
  const h = Math.floor(minutes / 60);
  const m = minutes % 60;
  if (h === 0) return `${m}m`;
  return m ? `${h}h ${m}m` : `${h}h`;
}

function formatGrams(grams: number): string {
  if (!grams) return '0 g';
  return grams >= 1000 ? `${(grams / 1000).toFixed(2)} kg` : `${Math.round(grams)} g`;
}

function Swatch({ color }: { color: string }) {
  return (
    <span
      className="inline-block h-3 w-3 shrink-0 rounded-full border border-white/25"
      style={{ backgroundColor: /^#[0-9a-f]{6}$/i.test(color) ? color : '#6b7280' }}
    />
  );
}

function SourceBadge({ tone, children, title }: { tone: 'green' | 'blue' | 'amber'; children: React.ReactNode; title?: string }) {
  const tones = {
    green: 'bg-bambu-green/15 text-green-300',
    blue: 'bg-blue-500/15 text-blue-300',
    amber: 'bg-yellow-500/15 text-yellow-300',
  };
  return (
    <span className={`inline-block whitespace-nowrap rounded px-1.5 py-0.5 text-[11px] ${tones[tone]}`} title={title}>
      {children}
    </span>
  );
}

function MaterialSource({ row, money }: { row: CostMaterialRow; money: (v: number) => string }) {
  const { t } = useTranslation();
  if (row.source === 'spools') {
    const detail = row.spools
      .map((s) => `${[s.brand, s.color_name].filter(Boolean).join(' ') || `#${s.id}`}: ${money(s.cost_per_kg)}/kg, ${Math.round(s.remaining_grams)} g`)
      .join('\n');
    return (
      <SourceBadge tone="green" title={detail}>
        {row.spools.length === 1
          ? t('projectCosts.sourceSpool', { name: [row.spools[0].brand, row.spools[0].color_name].filter(Boolean).join(' ') || `#${row.spools[0].id}` })
          : t('projectCosts.sourceSpools', { count: row.spools.length })}
      </SourceBadge>
    );
  }
  if (row.source === 'catalog') {
    return <SourceBadge tone="blue">{t('projectCosts.sourceCatalog', { type: row.type })}</SourceBadge>;
  }
  return <SourceBadge tone="amber">{t('projectCosts.sourceDefault')}</SourceBadge>;
}

function EnergySource({ row }: { row: CostEnergyRow }) {
  const { t } = useTranslation();
  switch (row.source) {
    case 'power_setting':
      return <SourceBadge tone="green">{t('projectCosts.energyPower', { value: row.source_detail || '' })}</SourceBadge>;
    case 'history':
      return <SourceBadge tone="green">{t('projectCosts.energyHistory', { count: row.history_prints })}</SourceBadge>;
    case 'fleet_average':
      return <SourceBadge tone="amber">{t('projectCosts.energyFleet')}</SourceBadge>;
    default:
      return <SourceBadge tone="amber">{t('projectCosts.energyNone')}</SourceBadge>;
  }
}

function WarningText({ warning }: { warning: CostWarning }) {
  const { t } = useTranslation();
  switch (warning.code) {
    case 'unestimated_plates':
      return <>{t('projectCosts.warnUnestimated', { count: warning.count })}</>;
    case 'default_price':
      return <>{t('projectCosts.warnDefaultPrice', { material: `${warning.type}${warning.color_name ? ` · ${warning.color_name}` : ` ${warning.color}`}` })}</>;
    case 'no_energy_rate':
      return <>{t('projectCosts.warnNoEnergy')}</>;
    case 'bom_without_price':
      return <>{t('projectCosts.warnBomNoPrice', { count: warning.count })}</>;
    default:
      return null;
  }
}

function CostBar({ totals }: { totals: CostTotals }) {
  if (totals.total <= 0) return <div className="my-3 h-3.5 rounded-full bg-bambu-dark" />;
  return (
    <div className="my-3 flex h-3.5 overflow-hidden rounded-full bg-bambu-dark">
      {SEGMENTS.map((s) =>
        totals[s.key] > 0 ? (
          <div key={s.key} style={{ width: `${(totals[s.key] / totals.total) * 100}%`, backgroundColor: s.color }} />
        ) : null,
      )}
    </div>
  );
}

export function CostMiniBar({ totals, className = 'h-1.5 w-16' }: { totals: CostTotals; className?: string }) {
  if (totals.total <= 0) return null;
  return (
    <span className={`flex overflow-hidden rounded-sm ${className}`}>
      {SEGMENTS.map((s) =>
        totals[s.key] > 0 ? (
          <span key={s.key} className="block h-full" style={{ width: `${(totals[s.key] / totals.total) * 100}%`, backgroundColor: s.color }} />
        ) : null,
      )}
    </span>
  );
}

function Summary({ costs, mode, money }: { costs: ProjectCosts; mode: Mode; money: (v: number) => string }) {
  const { t } = useTranslation();
  const totals = costs[mode];
  const labels = {
    material: t('projectCosts.material'),
    energy: t('projectCosts.energy'),
    bom: t('projectCosts.bom'),
  };
  const budgetUsed = costs.budget ? (costs.planned.total / costs.budget) * 100 : 0;

  return (
    <div className="rounded-lg border border-bambu-dark-tertiary bg-bambu-dark/60 p-4">
      <p className="text-xs text-bambu-gray">{t(`projectCosts.totalLabel.${mode}`)}</p>
      <p className="text-3xl font-bold tracking-tight text-white">
        {money(totals.total)}
        {mode === 'planned' && costs.has_plan && (
          <span className="ml-2 text-sm font-medium text-bambu-gray">{t('projectCosts.forPlates', { count: costs.total_plates })}</span>
        )}
      </p>
      <CostBar totals={totals} />
      <div className="space-y-2">
        {SEGMENTS.map((s) => (
          <div key={s.key} className="flex items-center gap-2 text-sm">
            <span className="h-2.5 w-2.5 shrink-0 rounded-sm" style={{ backgroundColor: s.color }} />
            <span className="flex-1 text-bambu-gray-light">
              {labels[s.key]}
              {s.key === 'material' && mode !== 'incurred' && costs.waste_percent > 0 && (
                <span className="ml-1 text-xs text-bambu-gray">{t('projectCosts.inclWaste', { percent: costs.waste_percent })}</span>
              )}
            </span>
            <span className="w-12 text-right text-bambu-gray">
              {totals.total > 0 ? `${Math.round((totals[s.key] / totals.total) * 100)} %` : '–'}
            </span>
            <span className="w-24 text-right font-semibold text-white">{money(totals[s.key])}</span>
          </div>
        ))}
      </div>
      {mode === 'incurred' && (
        <p className="mt-3 text-xs text-bambu-gray">
          {t('projectCosts.incurredNote', { count: costs.actual.prints, kwh: costs.actual.energy_kwh.toFixed(2) })}
        </p>
      )}

      <div className="mt-4 grid grid-cols-2 gap-3 border-t border-bambu-dark-tertiary pt-3">
        <div>
          <p className="text-xs text-bambu-gray">{t('projectCosts.modes.incurred')}</p>
          <p className="font-semibold text-white">{money(costs.incurred.total)}</p>
        </div>
        <div>
          <p className="text-xs text-bambu-gray">{t('projectCosts.modes.remaining')}</p>
          <p className="font-semibold text-white">{money(costs.remaining.total)}</p>
        </div>
      </div>

      {costs.budget != null && (
        <div className="mt-4 border-t border-bambu-dark-tertiary pt-3">
          <div className="flex justify-between text-xs">
            <span className="text-bambu-gray">{t('projectCosts.budget', { value: money(costs.budget) })}</span>
            <span className={costs.planned.total > costs.budget ? 'text-red-300' : 'text-white'}>
              {t('projectCosts.budgetUsed', { percent: Math.round(budgetUsed), value: money(costs.budget - costs.planned.total) })}
            </span>
          </div>
          <div className="mt-1.5 h-2 overflow-hidden rounded-full bg-bambu-dark">
            <div
              className={`h-full ${costs.planned.total > costs.budget ? 'bg-red-400' : 'bg-bambu-green'}`}
              style={{ width: `${Math.min(100, budgetUsed)}%` }}
            />
          </div>
        </div>
      )}

      {costs.warnings.length > 0 && (
        <ul className="mt-4 space-y-1.5">
          {costs.warnings.map((w, i) => (
            <li key={`${w.code}-${i}`} className="flex gap-1.5 text-xs text-yellow-300">
              <AlertTriangle className="mt-0.5 h-3.5 w-3.5 shrink-0" />
              <span>
                <WarningText warning={w} />
              </span>
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}

function SectionHeader({ color, title, pill, total }: { color: string; title: string; pill?: string; total: string }) {
  return (
    <h3 className="mb-2 flex items-center gap-2 text-sm font-semibold text-white">
      <span className="h-2.5 w-2.5 rounded-sm" style={{ backgroundColor: color }} />
      {title}
      {pill && <span className="rounded-full bg-bambu-dark px-2 py-0.5 text-xs font-medium text-bambu-gray-light">{pill}</span>}
      <span className="ml-auto">{total}</span>
    </h3>
  );
}

const th = 'px-3 py-2 text-left text-[11px] font-medium uppercase text-bambu-gray';
const td = 'border-t border-bambu-dark-tertiary px-3 py-2 text-bambu-gray-light';

export function ProjectCostsCard({ projectId, canEdit }: { projectId: number; canEdit: boolean }) {
  const { t } = useTranslation();
  const queryClient = useQueryClient();
  const [modeOverride, setModeOverride] = useState<Mode | null>(null);

  const { data: costs } = useQuery({
    queryKey: ['project-costs', projectId],
    queryFn: () => api.getProjectCosts(projectId),
    enabled: projectId > 0,
    refetchInterval: 30000,
  });
  const money = useMoney(costs?.currency || 'USD');

  const wasteMutation = useMutation({
    mutationFn: (value: number | null) => api.updateProject(projectId, { waste_percent: value }),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['project-costs', projectId] });
      queryClient.invalidateQueries({ queryKey: ['project', projectId] });
      queryClient.invalidateQueries({ queryKey: ['projects'] });
    },
  });

  if (!costs) return null;
  const isEmpty =
    !costs.has_plan && costs.incurred.total <= 0 && costs.planned.total <= 0 && costs.budget == null;
  if (isEmpty) return null;

  const mode: Mode = modeOverride ?? (costs.has_plan ? 'planned' : 'incurred');
  const modes: Mode[] = costs.has_plan ? ['planned', 'incurred', 'remaining'] : ['incurred', 'remaining'];

  return (
    <Card>
      <CardContent className="p-4">
        <div className="mb-4 flex flex-col gap-3 md:flex-row md:items-start md:justify-between">
          <div>
            <h2 className="flex items-center gap-2 text-lg font-semibold text-white">
              <Receipt className="h-5 w-5" />
              {t('projectCosts.title')}
            </h2>
            <p className="mt-1 text-xs text-bambu-gray">{t('projectCosts.subtitle')}</p>
          </div>
          <div className="inline-flex overflow-hidden rounded-lg border border-bambu-dark-tertiary bg-bambu-dark text-xs" role="tablist">
            {modes.map((m) => (
              <button
                key={m}
                type="button"
                role="tab"
                aria-selected={mode === m}
                onClick={() => setModeOverride(m)}
                className={`px-3 py-1.5 ${mode === m ? 'bg-bambu-green/20 font-semibold text-bambu-green' : 'text-bambu-gray-light hover:text-white'}`}
              >
                {t(`projectCosts.modes.${m}`)}
              </button>
            ))}
          </div>
        </div>

        <div className="grid grid-cols-1 gap-4 xl:grid-cols-[340px_minmax(0,1fr)]">
          <Summary costs={costs} mode={mode} money={money} />

          <div className="min-w-0 space-y-5">
            {/* Material */}
            {costs.material.rows.length > 0 && (
              <div>
                <SectionHeader
                  color="#00ae42"
                  title={t('projectCosts.material')}
                  pill={formatGrams(costs.material.planned_grams)}
                  total={money(costs.material.total_cost)}
                />
                <div className="overflow-x-auto rounded-lg border border-bambu-dark-tertiary">
                  <table className="w-full text-sm">
                    <thead className="bg-bambu-dark-tertiary">
                      <tr>
                        <th className={th}>{t('projectCosts.colMaterial')}</th>
                        <th className={`${th} text-right`}>{t('projectCosts.colAmount')}</th>
                        <th className={`${th} text-right`}>{t('projectCosts.colPricePerKg')}</th>
                        <th className={th}>{t('projectCosts.colSource')}</th>
                        <th className={`${th} text-right`}>{t('projectCosts.colCost')}</th>
                      </tr>
                    </thead>
                    <tbody>
                      {costs.material.rows.map((row) => (
                        <tr key={`${row.type}-${row.color}`}>
                          <td className={td}>
                            <span className="inline-flex items-center gap-1.5 text-white">
                              <Swatch color={row.color} />
                              {row.type}
                              {row.color_name && <span className="text-bambu-gray">· {row.color_name}</span>}
                            </span>
                          </td>
                          <td className={`${td} text-right`}>{formatGrams(row.planned_grams)}</td>
                          <td className={`${td} text-right`}>{money(row.price_per_kg)}</td>
                          <td className={td}>
                            <MaterialSource row={row} money={money} />
                          </td>
                          <td className={`${td} text-right text-white`}>{money(row.planned_cost)}</td>
                        </tr>
                      ))}
                      <tr>
                        <td className={td} colSpan={4}>
                          <label className="inline-flex items-center gap-2">
                            {t('projectCosts.waste')}
                            <input
                              key={costs.waste_percent}
                              type="number"
                              min={0}
                              step={0.5}
                              disabled={!canEdit}
                              defaultValue={costs.waste_percent || ''}
                              placeholder="0"
                              onBlur={(e) => {
                                const raw = e.target.value.trim();
                                const value = raw === '' ? null : Math.max(0, Number(raw));
                                if ((value ?? 0) !== costs.waste_percent) wasteMutation.mutate(value || null);
                              }}
                              onKeyDown={(e) => {
                                if (e.key === 'Enter') (e.target as HTMLInputElement).blur();
                              }}
                              className="w-16 rounded border border-bambu-dark-tertiary bg-bambu-dark px-2 py-0.5 text-sm text-white focus:border-bambu-green focus:outline-none"
                              aria-label={t('projectCosts.waste')}
                            />
                            %
                            <span className="text-xs text-bambu-gray">{t('projectCosts.wasteHint')}</span>
                          </label>
                        </td>
                        <td className={`${td} text-right text-white`}>{money(costs.material.waste_cost)}</td>
                      </tr>
                    </tbody>
                  </table>
                </div>
                <p className="mt-1.5 text-xs italic text-bambu-gray">{t('projectCosts.priceOrder')}</p>
              </div>
            )}

            {/* Energy */}
            {costs.energy.rows.length > 0 && (
              <div>
                <SectionHeader
                  color="#facc15"
                  title={t('projectCosts.energy')}
                  pill={`${costs.energy.planned_kwh.toFixed(2)} kWh · ${money(costs.energy_cost_per_kwh)}/kWh`}
                  total={money(costs.energy.planned_cost)}
                />
                <div className="overflow-x-auto rounded-lg border border-bambu-dark-tertiary">
                  <table className="w-full text-sm">
                    <thead className="bg-bambu-dark-tertiary">
                      <tr>
                        <th className={th}>{t('projectCosts.colPrinter')}</th>
                        <th className={`${th} text-right`}>{t('projectCosts.colPrintTime')}</th>
                        <th className={`${th} text-right`}>{t('projectCosts.colKwhPerHour')}</th>
                        <th className={th}>{t('projectCosts.colSource')}</th>
                        <th className={`${th} text-right`}>kWh</th>
                        <th className={`${th} text-right`}>{t('projectCosts.colCost')}</th>
                      </tr>
                    </thead>
                    <tbody>
                      {costs.energy.rows.map((row) => (
                        <tr key={row.key}>
                          <td className={td}>
                            <span className="text-white">
                              {row.kind === 'printer'
                                ? row.label
                                : row.kind === 'model'
                                  ? t('projectPlan.anyModel', { model: row.label })
                                  : t('projectPlan.unassigned')}
                            </span>{' '}
                            <span className="text-xs text-bambu-gray">({t('projectCosts.platesCount', { count: row.plates })})</span>
                          </td>
                          <td className={`${td} text-right`}>{formatHours(row.planned_hours)}</td>
                          <td className={`${td} text-right`}>{row.kwh_per_hour != null ? row.kwh_per_hour.toFixed(2) : '–'}</td>
                          <td className={td}>
                            <EnergySource row={row} />
                          </td>
                          <td className={`${td} text-right`}>{row.planned_kwh.toFixed(2)}</td>
                          <td className={`${td} text-right text-white`}>{money(row.planned_cost)}</td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
                <p className="mt-1.5 text-xs italic text-bambu-gray">{t('projectCosts.energyOrder')}</p>
              </div>
            )}

            {/* BOM */}
            {costs.bom.rows.length > 0 && (
              <div>
                <SectionHeader
                  color="#60a5fa"
                  title={t('projectCosts.bom')}
                  pill={t('projectCosts.positions', { count: costs.bom.rows.length })}
                  total={money(costs.bom.total)}
                />
                <div className="overflow-x-auto rounded-lg border border-bambu-dark-tertiary">
                  <table className="w-full text-sm">
                    <thead className="bg-bambu-dark-tertiary">
                      <tr>
                        <th className={th}>{t('projectCosts.colPart')}</th>
                        <th className={`${th} text-right`}>{t('projectCosts.colQuantity')}</th>
                        <th className={`${th} text-right`}>{t('projectCosts.colUnitPrice')}</th>
                        <th className={th}>{t('projectCosts.colStatus')}</th>
                        <th className={`${th} text-right`}>{t('projectCosts.colCost')}</th>
                      </tr>
                    </thead>
                    <tbody>
                      {costs.bom.rows.map((row) => {
                        const done = row.quantity_acquired >= row.quantity_needed;
                        return (
                          <tr key={row.id}>
                            <td className={`${td} text-white`}>{row.name}</td>
                            <td className={`${td} text-right`}>{row.quantity_needed}</td>
                            <td className={`${td} text-right`}>{money(row.unit_price)}</td>
                            <td className={td}>
                              {done ? (
                                <SourceBadge tone="green">{t('projectCosts.acquired')}</SourceBadge>
                              ) : (
                                <SourceBadge tone="amber">
                                  {t('projectCosts.acquiredPartial', { have: row.quantity_acquired, need: row.quantity_needed })}
                                </SourceBadge>
                              )}
                            </td>
                            <td className={`${td} text-right text-white`}>{money(row.cost)}</td>
                          </tr>
                        );
                      })}
                    </tbody>
                  </table>
                </div>
              </div>
            )}

            {!costs.has_plan && (
              <p className="text-sm text-bambu-gray">{t('projectCosts.noPlanHint')}</p>
            )}
          </div>
        </div>
      </CardContent>
    </Card>
  );
}
