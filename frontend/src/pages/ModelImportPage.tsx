import { useSearchParams } from 'react-router-dom';
import { useTranslation } from 'react-i18next';
import { Boxes, Download, Globe, Settings, type LucideIcon } from 'lucide-react';

import { useAuth } from '../contexts/AuthContext';
import { MakerworldPage } from './MakerworldPage';
import { GyroidVaultPage } from './GyroidVaultPage';
import { GyroidVaultSettings } from '../components/GyroidVaultSettings';
import { MakerworldImportDefaults } from '../components/MakerworldImportDefaults';
import type { Permission } from '../api/client';

export type ModelImportSource = 'makerworld' | 'gyroidvault' | 'settings';

const TABS: Array<{ id: ModelImportSource; labelKey: string; icon: LucideIcon; permission: Permission }> = [
  { id: 'makerworld', labelKey: 'modelImport.tabs.makerworld', icon: Globe, permission: 'makerworld:view' },
  { id: 'gyroidvault', labelKey: 'modelImport.tabs.gyroidvault', icon: Boxes, permission: 'library:read' },
  { id: 'settings', labelKey: 'modelImport.tabs.settings', icon: Settings, permission: 'settings:read' },
];

/**
 * One place for every way of getting models into the library: MakerWorld,
 * GyroidVault and the settings of both. The active tab lives in ``?source=``
 * so the old /makerworld and /gyroidvault routes can redirect straight to it.
 */
export function ModelImportPage() {
  const { t } = useTranslation();
  const { hasPermission } = useAuth();
  const [searchParams, setSearchParams] = useSearchParams();

  const visibleTabs = TABS.filter((tab) => hasPermission(tab.permission));
  const requested = searchParams.get('source') as ModelImportSource | null;
  const active = visibleTabs.find((tab) => tab.id === requested)?.id ?? visibleTabs[0]?.id;

  const selectTab = (id: ModelImportSource) => {
    const next = new URLSearchParams(searchParams);
    next.set('source', id);
    setSearchParams(next, { replace: true });
  };

  return (
    <div className="p-4 md:p-8 max-w-screen-2xl space-y-6">
      <div>
        <h1 className="text-2xl font-bold text-white flex items-center gap-3">
          <Download className="w-7 h-7 text-bambu-green" />
          {t('modelImport.title')}
        </h1>
        <p className="text-bambu-gray mt-1">{t('modelImport.description')}</p>
      </div>

      {visibleTabs.length === 0 ? (
        <p className="text-bambu-gray">{t('modelImport.noAccess')}</p>
      ) : (
        <>
          <div role="tablist" aria-label={t('modelImport.title')} className="flex gap-1 border-b border-bambu-dark-tertiary">
            {visibleTabs.map((tab) => {
              const Icon = tab.icon;
              const selected = tab.id === active;
              return (
                <button
                  key={tab.id}
                  type="button"
                  role="tab"
                  aria-selected={selected}
                  onClick={() => selectTab(tab.id)}
                  className={`flex items-center gap-2 px-4 py-2 -mb-px border-b-2 text-sm font-medium transition-colors ${
                    selected
                      ? 'border-bambu-green text-white'
                      : 'border-transparent text-bambu-gray hover:text-white'
                  }`}
                >
                  <Icon className="w-4 h-4" />
                  {t(tab.labelKey)}
                </button>
              );
            })}
          </div>

          <div role="tabpanel">
            {active === 'makerworld' && <MakerworldPage embedded />}
            {active === 'gyroidvault' && <GyroidVaultPage embedded />}
            {active === 'settings' && (
              <div className="grid gap-6 lg:grid-cols-2 items-start max-w-6xl">
                <GyroidVaultSettings />
                <MakerworldImportDefaults />
              </div>
            )}
          </div>
        </>
      )}
    </div>
  );
}
