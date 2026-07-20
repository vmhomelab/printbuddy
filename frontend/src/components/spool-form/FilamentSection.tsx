import { useState, useRef, useEffect, useMemo } from 'react';
import { Search, Loader2, ChevronDown, Cloud, CloudOff } from 'lucide-react';
import { useTranslation } from 'react-i18next';
import { api, ApiError } from '../../api/client';
import type { OpenFilamentDatabaseBrandSummary, OpenFilamentDatabaseMaterialSummary, OpenFilamentDatabaseFilamentSummary, OpenFilamentDatabaseVariantSummary } from '../../api/client';
import type { FilamentSectionProps, FilamentOption } from './types';
import { KNOWN_VARIANTS } from './constants';
import { parsePresetName } from './utils';

export function FilamentSection({
  formData,
  updateField,
  cloudAuthenticated,
  loadingCloudPresets,
  presetInputValue,
  setPresetInputValue,
  selectedPresetOption,
  filamentOptions,
  availableBrands,
  availableMaterials,
  quickAdd,
  quantity,
  onQuantityChange,
  showQuantity = false,
  errors,
  openFilamentDatabaseEnabled,
}: FilamentSectionProps) {
  const { t } = useTranslation();
  const [presetDropdownOpen, setPresetDropdownOpen] = useState(false);
  const [brandDropdownOpen, setBrandDropdownOpen] = useState(false);
  const [subtypeDropdownOpen, setSubtypeDropdownOpen] = useState(false);
  const [materialDropdownOpen, setMaterialDropdownOpen] = useState(false);
  const [brandSearch, setBrandSearch] = useState('');
  const [subtypeSearch, setSubtypeSearch] = useState('');
  const [materialSearch, setMaterialSearch] = useState('');
  const [labelInput, setLabelInput] = useState(String(formData.label_weight));
  const [isLabelFocused, setIsLabelFocused] = useState(false);
  const [quantityInput, setQuantityInput] = useState(String(quantity));
  const [isQuantityFocused, setIsQuantityFocused] = useState(false);
  const [ofdbBrandQuery, setOfdbBrandQuery] = useState('');
  const [ofdbBrands, setOfdbBrands] = useState<OpenFilamentDatabaseBrandSummary[]>([]);
  const [ofdbMaterials, setOfdbMaterials] = useState<OpenFilamentDatabaseMaterialSummary[]>([]);
  const [ofdbSelectedBrand, setOfdbSelectedBrand] = useState<OpenFilamentDatabaseBrandSummary | null>(null);
  const [ofdbSelectedMaterial, setOfdbSelectedMaterial] = useState<OpenFilamentDatabaseMaterialSummary | null>(null);
  const [ofdbQuery, setOfdbQuery] = useState('');
  const [ofdbFilaments, setOfdbFilaments] = useState<OpenFilamentDatabaseFilamentSummary[]>([]);
  const [ofdbVariants, setOfdbVariants] = useState<OpenFilamentDatabaseVariantSummary[]>([]);
  const [ofdbSelectedFilament, setOfdbSelectedFilament] = useState<OpenFilamentDatabaseFilamentSummary | null>(null);
  const [ofdbSelectedVariant, setOfdbSelectedVariant] = useState<OpenFilamentDatabaseVariantSummary | null>(null);
  const [ofdbLoading, setOfdbLoading] = useState(false);
  const [ofdbBrandLoading, setOfdbBrandLoading] = useState(false);
  const [ofdbError, setOfdbError] = useState<string | null>(null);
  const presetRef = useRef<HTMLDivElement>(null);
  const brandRef = useRef<HTMLDivElement>(null);
  const subtypeRef = useRef<HTMLDivElement>(null);
  const materialRef = useRef<HTMLDivElement>(null);

  // Close dropdowns on outside click
  useEffect(() => {
    const handleClick = (e: MouseEvent) => {
      if (presetRef.current && !presetRef.current.contains(e.target as Node)) {
        setPresetDropdownOpen(false);
      }
      if (materialRef.current && !materialRef.current.contains(e.target as Node)) {
        setMaterialDropdownOpen(false);
      }
      if (brandRef.current && !brandRef.current.contains(e.target as Node)) {
        setBrandDropdownOpen(false);
      }
      if (subtypeRef.current && !subtypeRef.current.contains(e.target as Node)) {
        setSubtypeDropdownOpen(false);
      }
    };
    document.addEventListener('mousedown', handleClick);
    return () => document.removeEventListener('mousedown', handleClick);
  }, []);

  // Filtered presets based on search
  const filteredPresets = useMemo(() => {
    if (!presetInputValue) return filamentOptions;
    const search = presetInputValue.toLowerCase();
    return filamentOptions.filter(o =>
      o.displayName.toLowerCase().includes(search) ||
      o.code.toLowerCase().includes(search),
    );
  }, [filamentOptions, presetInputValue]);

  // Filtered brands
  const filteredBrands = useMemo(() => {
    if (!brandSearch) return availableBrands;
    const search = brandSearch.toLowerCase();
    const filtered = availableBrands.filter(b => b.toLowerCase().includes(search));
    // Sort: exact match first, then others
    return filtered.sort((a, b) => {
      const aExact = a.toLowerCase() === search;
      const bExact = b.toLowerCase() === search;
      if (aExact && !bExact) return -1;
      if (!aExact && bExact) return 1;
      return a.localeCompare(b);
    });
  }, [availableBrands, brandSearch]);

  const filteredVariants = useMemo(() => {
    if (!subtypeSearch) return KNOWN_VARIANTS;
    const search = subtypeSearch.toLowerCase();
    return KNOWN_VARIANTS.filter(v => v.toLowerCase().includes(search));
  }, [subtypeSearch]);

  const filteredMaterials = useMemo(() => {
    if (!materialSearch) return availableMaterials;
    const search = materialSearch.toLowerCase();
    const filtered = availableMaterials.filter(m => m.toLowerCase().includes(search));
    // Sort: exact match first, then others
    return filtered.sort((a, b) => {
      const aExact = a.toLowerCase() === search;
      const bExact = b.toLowerCase() === search;
      if (aExact && !bExact) return -1;
      if (!aExact && bExact) return 1;
      return a.localeCompare(b);
    });
  }, [materialSearch, availableMaterials]);

  useEffect(() => {
    if (!isLabelFocused) {
      setLabelInput(String(formData.label_weight));
    }
  }, [formData.label_weight, isLabelFocused]);

  useEffect(() => {
    if (!isQuantityFocused) {
      setQuantityInput(String(quantity));
    }
  }, [quantity, isQuantityFocused]);

  // Handle preset selection
  const handlePresetSelect = (option: FilamentOption) => {
    updateField('slicer_filament', option.code);
    setPresetInputValue(option.displayName);
    setPresetDropdownOpen(false);

    // Auto-fill material, brand, subtype from preset name
    const parsed = parsePresetName(option.name);
    if (parsed.material) updateField('material', parsed.material);
    if (parsed.brand) updateField('brand', parsed.brand);
    if (parsed.variant) updateField('subtype', parsed.variant);
  };

  const filteredOfdbBrands = useMemo(() => {
    const search = ofdbBrandQuery.trim().toLowerCase();
    const brands = search
      ? ofdbBrands.filter((brand) =>
        brand.name.toLowerCase().includes(search) || brand.slug.toLowerCase().includes(search),
      )
      : ofdbBrands;
    return [...brands].sort((a, b) => {
      const aExact = a.name.toLowerCase() === search || a.slug.toLowerCase() === search;
      const bExact = b.name.toLowerCase() === search || b.slug.toLowerCase() === search;
      if (aExact && !bExact) return -1;
      if (!aExact && bExact) return 1;
      return a.name.localeCompare(b.name);
    }).slice(0, 30);
  }, [ofdbBrandQuery, ofdbBrands]);

  const ofdbBrandSlug = ofdbSelectedBrand?.slug ?? '';
  const ofdbMaterial = ofdbSelectedMaterial?.material ?? '';
  const canSearchOfdb = Boolean(ofdbBrandSlug && ofdbMaterial);

  const resetOfdbDownstream = () => {
    setOfdbSelectedMaterial(null);
    setOfdbFilaments([]);
    setOfdbVariants([]);
    setOfdbSelectedFilament(null);
    setOfdbSelectedVariant(null);
    setOfdbQuery('');
  };

  const loadOfdbBrands = async () => {
    if (ofdbBrands.length > 0 || ofdbBrandLoading) return;
    setOfdbBrandLoading(true);
    setOfdbError(null);
    try {
      const response = await api.getOpenFilamentDatabaseBrands();
      setOfdbBrands(response.brands);
      if (response.brands.length === 0) {
        setOfdbError(t('inventory.openFilamentDatabase.noBrands'));
      }
    } catch (error) {
      const message = error instanceof ApiError ? error.message : t('inventory.openFilamentDatabase.brandLoadFailed');
      setOfdbError(message);
    } finally {
      setOfdbBrandLoading(false);
    }
  };

  const handleOfdbBrandSelect = async (brand: OpenFilamentDatabaseBrandSummary) => {
    setOfdbSelectedBrand(brand);
    setOfdbBrandQuery(brand.name);
    updateField('brand', brand.name);
    resetOfdbDownstream();
    setOfdbMaterials([]);
    setOfdbLoading(true);
    setOfdbError(null);
    try {
      const response = await api.getOpenFilamentDatabaseBrand(brand.slug);
      setOfdbMaterials(response.materials);
      if (response.materials.length === 0) {
        setOfdbError(t('inventory.openFilamentDatabase.noMaterials'));
      }
    } catch (error) {
      const message = error instanceof ApiError ? error.message : t('inventory.openFilamentDatabase.materialLoadFailed');
      setOfdbError(message);
    } finally {
      setOfdbLoading(false);
    }
  };

  const handleOfdbMaterialSelect = (material: OpenFilamentDatabaseMaterialSummary) => {
    setOfdbSelectedMaterial(material);
    updateField('material', material.material);
    setOfdbFilaments([]);
    setOfdbVariants([]);
    setOfdbSelectedFilament(null);
    setOfdbSelectedVariant(null);
    setOfdbQuery('');
    setOfdbError(null);
  };

  const handleOfdbSearch = async () => {
    if (!canSearchOfdb) {
      setOfdbError(t('inventory.openFilamentDatabase.missingBrandMaterial'));
      return;
    }
    setOfdbLoading(true);
    setOfdbError(null);
    setOfdbSelectedFilament(null);
    setOfdbVariants([]);
    try {
      const response = await api.searchOpenFilamentDatabase(ofdbBrandSlug, ofdbMaterial, ofdbQuery);
      setOfdbFilaments(response.filaments);
      if (response.filaments.length === 0) {
        setOfdbError(t('inventory.openFilamentDatabase.noFilaments'));
      }
    } catch (error) {
      const message = error instanceof ApiError ? error.message : t('inventory.openFilamentDatabase.searchFailed');
      setOfdbError(message);
      setOfdbFilaments([]);
    } finally {
      setOfdbLoading(false);
    }
  };

  const handleOfdbFilamentSelect = async (filament: OpenFilamentDatabaseFilamentSummary) => {
    if (!canSearchOfdb) return;
    setOfdbLoading(true);
    setOfdbError(null);
    setOfdbSelectedFilament(filament);
    setOfdbSelectedVariant(null);
    setOfdbVariants([]);
    try {
      const response = await api.getOpenFilamentDatabaseFilament(ofdbBrandSlug, ofdbMaterial, filament.slug);
      setOfdbVariants(response.variants);
      const prefill = response.spool_prefill;
      if (typeof prefill.material === 'string') updateField('material', prefill.material);
      if (typeof prefill.subtype === 'string') updateField('subtype', prefill.subtype);
      if (typeof prefill.slicer_filament === 'string') updateField('slicer_filament', prefill.slicer_filament);
      if (typeof prefill.slicer_filament_name === 'string') setPresetInputValue(prefill.slicer_filament_name);
      if (typeof prefill.nozzle_temp_min === 'number') updateField('nozzle_temp_min', prefill.nozzle_temp_min);
      if (typeof prefill.nozzle_temp_max === 'number') updateField('nozzle_temp_max', prefill.nozzle_temp_max);
      if (typeof prefill.data_origin === 'string') updateField('data_origin', prefill.data_origin);
      if (response.variants.length === 0) {
        setOfdbError(t('inventory.openFilamentDatabase.noVariants'));
      }
    } catch (error) {
      const message = error instanceof ApiError ? error.message : t('inventory.openFilamentDatabase.filamentLoadFailed');
      setOfdbError(message);
    } finally {
      setOfdbLoading(false);
    }
  };

  const handleOfdbVariantSelect = async (variant: OpenFilamentDatabaseVariantSummary) => {
    if (!ofdbSelectedFilament || !canSearchOfdb) return;
    setOfdbLoading(true);
    setOfdbError(null);
    setOfdbSelectedVariant(variant);
    try {
      const response = await api.getOpenFilamentDatabaseVariant(
        ofdbBrandSlug,
        ofdbMaterial,
        ofdbSelectedFilament.slug,
        variant.slug,
      );
      const prefill = response.spool_prefill;
      if (typeof prefill.brand === 'string') updateField('brand', prefill.brand);
      if (typeof prefill.material === 'string') updateField('material', prefill.material);
      if (typeof prefill.subtype === 'string') updateField('subtype', prefill.subtype);
      if (typeof prefill.color_name === 'string') updateField('color_name', prefill.color_name);
      if (typeof prefill.rgba === 'string') updateField('rgba', prefill.rgba);
      if (typeof prefill.label_weight === 'number') updateField('label_weight', prefill.label_weight);
      if (typeof prefill.slicer_filament === 'string') updateField('slicer_filament', prefill.slicer_filament);
      if (typeof prefill.slicer_filament_name === 'string') setPresetInputValue(prefill.slicer_filament_name);
      if (typeof prefill.nozzle_temp_min === 'number') updateField('nozzle_temp_min', prefill.nozzle_temp_min);
      if (typeof prefill.nozzle_temp_max === 'number') updateField('nozzle_temp_max', prefill.nozzle_temp_max);
      if (typeof prefill.data_origin === 'string') updateField('data_origin', prefill.data_origin);
    } catch (error) {
      const message = error instanceof ApiError ? error.message : t('inventory.openFilamentDatabase.variantLoadFailed');
      setOfdbError(message);
    } finally {
      setOfdbLoading(false);
    }
  };

  return (
    <div className="space-y-4">
      {/* Cloud status indicator */}
      {!quickAdd && (
        <div className="flex items-center gap-2 text-xs text-bambu-gray">
          {loadingCloudPresets ? (
            <><Loader2 className="w-3 h-3 animate-spin" /> {t('inventory.loadingPresets')}</>
          ) : cloudAuthenticated ? (
            <><Cloud className="w-3 h-3 text-bambu-green" /> {t('inventory.cloudConnected')}</>
          ) : (
            <><CloudOff className="w-3 h-3" /> {t('inventory.cloudNotConnected')}</>
          )}
        </div>
      )}

      {openFilamentDatabaseEnabled && !quickAdd && (
        <div className="p-3 rounded-lg border border-bambu-dark-tertiary bg-bambu-dark-secondary/60 space-y-3">
          <div className="text-sm text-white">
            <span className="block font-medium">{t('inventory.openFilamentDatabase.searchToggle')}</span>
            <span className="block text-xs text-bambu-gray mt-0.5">
              {t('inventory.openFilamentDatabase.searchHint')}
            </span>
          </div>

          <div className="space-y-3">
            <div className="space-y-1">
                <label className="block text-xs font-medium text-bambu-gray">
                  {t('inventory.openFilamentDatabase.brandLabel')}
                </label>
                <div className="relative">
                  <Search className="absolute left-3 top-1/2 -translate-y-1/2 w-4 h-4 text-bambu-gray/50 pointer-events-none" />
                  <input
                    type="text"
                    className="w-full pl-9 pr-3 py-2 bg-bambu-dark border border-bambu-dark-tertiary rounded-lg text-white text-sm placeholder:text-bambu-gray/50 focus:outline-none focus:border-bambu-green"
                    placeholder={t('inventory.openFilamentDatabase.brandPlaceholder')}
                    value={ofdbBrandQuery}
                    onFocus={() => void loadOfdbBrands()}
                    onChange={(event) => {
                      setOfdbBrandQuery(event.target.value);
                      setOfdbSelectedBrand(null);
                      resetOfdbDownstream();
                    }}
                  />
                </div>
                {ofdbBrandLoading && (
                  <p className="text-xs text-bambu-gray">{t('inventory.openFilamentDatabase.loadingBrands')}</p>
                )}
                {filteredOfdbBrands.length > 0 && !ofdbSelectedBrand && (
                  <div className="max-h-40 overflow-y-auto rounded-lg border border-bambu-dark-tertiary">
                    {filteredOfdbBrands.map((brand) => (
                      <button
                        key={brand.id}
                        type="button"
                        className="w-full px-3 py-2 text-left text-sm text-white hover:bg-bambu-dark-tertiary"
                        onClick={() => void handleOfdbBrandSelect(brand)}
                      >
                        <span className="block">{brand.name}</span>
                        <span className="block text-xs text-bambu-gray">
                          {t('inventory.openFilamentDatabase.materialCount', { count: brand.material_count })}
                        </span>
                      </button>
                    ))}
                  </div>
                )}
              </div>

              {ofdbSelectedBrand && (
                <div className="space-y-1">
                  <label className="block text-xs font-medium text-bambu-gray">
                    {t('inventory.openFilamentDatabase.materialLabel')}
                  </label>
                  {ofdbMaterials.length === 0 && ofdbLoading ? (
                    <p className="text-xs text-bambu-gray">{t('common.loading')}</p>
                  ) : (
                    <div className="grid grid-cols-2 sm:grid-cols-3 gap-1 max-h-36 overflow-y-auto">
                      {ofdbMaterials.map((material) => (
                        <button
                          key={material.id}
                          type="button"
                          className={`px-3 py-2 rounded-lg border border-bambu-dark-tertiary text-left text-sm hover:bg-bambu-dark-tertiary ${
                            ofdbSelectedMaterial?.id === material.id ? 'bg-bambu-green/10 text-bambu-green' : 'text-white'
                          }`}
                          onClick={() => handleOfdbMaterialSelect(material)}
                        >
                          <span className="block font-medium">{material.material}</span>
                          <span className="block text-xs text-bambu-gray">
                            {t('inventory.openFilamentDatabase.filamentCount', { count: material.filament_count })}
                          </span>
                        </button>
                      ))}
                    </div>
                  )}
                </div>
              )}

              {ofdbSelectedMaterial && (
                <div className="space-y-2">
                  <label className="block text-xs font-medium text-bambu-gray">
                    {t('inventory.openFilamentDatabase.filamentLabel')}
                  </label>
                  <div className="flex gap-2">
                    <div className="relative flex-1">
                      <Search className="absolute left-3 top-1/2 -translate-y-1/2 w-4 h-4 text-bambu-gray/50 pointer-events-none" />
                      <input
                        type="text"
                        className="w-full pl-9 pr-3 py-2 bg-bambu-dark border border-bambu-dark-tertiary rounded-lg text-white text-sm placeholder:text-bambu-gray/50 focus:outline-none focus:border-bambu-green"
                        placeholder={t('inventory.openFilamentDatabase.searchPlaceholder')}
                        value={ofdbQuery}
                        onChange={(event) => setOfdbQuery(event.target.value)}
                        onKeyDown={(event) => {
                          if (event.key === 'Enter') {
                            event.preventDefault();
                            void handleOfdbSearch();
                          }
                        }}
                      />
                    </div>
                    <button
                      type="button"
                      className="px-3 py-2 rounded-lg bg-bambu-green text-white text-sm font-medium disabled:opacity-50"
                      disabled={ofdbLoading || !canSearchOfdb}
                      onClick={() => void handleOfdbSearch()}
                    >
                      {ofdbLoading ? t('common.loading') : t('common.search')}
                    </button>
                  </div>
                </div>
              )}

              {ofdbError && <p className="text-xs text-red-400">{ofdbError}</p>}

              {ofdbFilaments.length > 0 && (
                <div className="space-y-1">
                  <p className="text-xs font-medium text-bambu-gray">{t('inventory.openFilamentDatabase.filamentResults')}</p>
                  <div className="max-h-40 overflow-y-auto rounded-lg border border-bambu-dark-tertiary">
                    {ofdbFilaments.map((filament) => (
                      <button
                        key={filament.id}
                        type="button"
                        className={`w-full px-3 py-2 text-left text-sm hover:bg-bambu-dark-tertiary ${
                          ofdbSelectedFilament?.id === filament.id ? 'bg-bambu-green/10 text-bambu-green' : 'text-white'
                        }`}
                        onClick={() => void handleOfdbFilamentSelect(filament)}
                      >
                        <span className="block">{filament.name}</span>
                        <span className="block text-xs text-bambu-gray">
                          {t('inventory.openFilamentDatabase.variantCount', { count: filament.variant_count })}
                        </span>
                      </button>
                    ))}
                  </div>
                </div>
              )}

              {ofdbVariants.length > 0 && (
                <div className="space-y-1">
                  <p className="text-xs font-medium text-bambu-gray">{t('inventory.openFilamentDatabase.variantResults')}</p>
                  <div className="grid grid-cols-1 sm:grid-cols-2 gap-1 max-h-48 overflow-y-auto">
                    {ofdbVariants.map((variant) => {
                      const selected = ofdbSelectedVariant?.id === variant.id || ofdbSelectedVariant?.slug === variant.slug;
                      return (
                      <button
                        key={variant.id}
                        type="button"
                        className={`flex items-center gap-2 px-3 py-2 rounded-lg border text-left text-sm transition-colors ${
                          selected
                            ? 'border-bambu-green bg-bambu-green/15 text-bambu-green ring-1 ring-bambu-green/30'
                            : 'border-bambu-dark-tertiary text-white hover:bg-bambu-dark-tertiary'
                        }`}
                        aria-pressed={selected}
                        onClick={() => void handleOfdbVariantSelect(variant)}
                      >
                        <span
                          className="w-4 h-4 rounded-full border border-white/20 flex-shrink-0"
                          style={{ backgroundColor: variant.color_hex || '#808080' }}
                        />
                        <span>
                          <span className="block">{variant.name}</span>
                          <span className="block text-xs text-bambu-gray">
                            {t('inventory.openFilamentDatabase.sizeCount', { count: variant.size_count })}
                          </span>
                        </span>
                      </button>
                      );
                    })}
                  </div>
                </div>
              )}
          </div>
        </div>
      )}

      {/* Slicer Preset (autocomplete) — hidden in quick-add mode */}
      {!quickAdd && (
        <div>
          <label className="block text-sm font-medium text-bambu-gray mb-1">
            {t('inventory.slicerPreset')}{formData.data_origin !== 'openfilamentdatabase' && ' *'}
          </label>
          <div className="relative" ref={presetRef}>
            <Search className="absolute left-3 top-1/2 -translate-y-1/2 w-4 h-4 text-bambu-gray/50 pointer-events-none" />
            <input
              type="text"
              className="w-full pl-9 pr-3 py-2 bg-bambu-dark border border-bambu-dark-tertiary rounded-lg text-white text-sm placeholder:text-bambu-gray/50 focus:outline-none focus:border-bambu-green"
              placeholder={t('inventory.searchPresets')}
              value={presetInputValue}
              onChange={(e) => {
                setPresetInputValue(e.target.value);
                setPresetDropdownOpen(true);
              }}
              onFocus={() => {
                setPresetDropdownOpen(true);
                setPresetInputValue('');
              }}
            />
            {presetDropdownOpen && (
              <div className="absolute z-50 w-full mt-1 bg-bambu-dark-secondary border border-bambu-dark-tertiary rounded-lg shadow-lg max-h-64 overflow-y-auto">
                {filteredPresets.length === 0 ? (
                  <div className="px-3 py-2 text-sm text-bambu-gray">{t('inventory.noPresetsFound')}</div>
                ) : (
                  filteredPresets.map(option => (
                    <button
                      key={`${option.code}::${option.name}`}
                      type="button"
                      className={`w-full px-3 py-2 text-left text-sm hover:bg-bambu-dark-tertiary truncate ${
                        selectedPresetOption?.code === option.code
                          ? 'bg-bambu-green/10 text-bambu-green'
                          : 'text-white'
                      }`}
                      onClick={() => handlePresetSelect(option)}
                    >
                      {option.displayName}
                    </button>
                  ))
                )}
              </div>
            )}
          </div>
          {selectedPresetOption && (
            <div className="mt-1 text-xs text-bambu-gray">
              {t('inventory.selectedPreset')}: <span className="font-mono text-bambu-green">{selectedPresetOption.code}</span>
            </div>
          )}
          {errors?.slicer_filament && (
            <p className="mt-1 text-xs text-red-400">{errors.slicer_filament}</p>
          )}
        </div>
      )}

      {/* Material */}
      <div>
        <label className="block text-sm font-medium text-bambu-gray mb-1">{t('inventory.material')} *</label>
        <div className="relative" ref={materialRef}>
          <input
            type="text"
            className="w-full px-3 py-2 bg-bambu-dark border border-bambu-dark-tertiary rounded-lg text-white text-sm placeholder:text-bambu-gray/50 focus:outline-none focus:border-bambu-green"
            placeholder={t('inventory.selectMaterial')}
            value={materialDropdownOpen ? materialSearch : formData.material}
            onChange={(e) => {
              setMaterialSearch(e.target.value);
              setMaterialDropdownOpen(true);
            }}
            onFocus={() => {
              setMaterialDropdownOpen(true);
              setMaterialSearch('');
            }}
          />
          <ChevronDown className="absolute right-3 top-1/2 -translate-y-1/2 w-4 h-4 text-bambu-gray/50 pointer-events-none" />
          {materialDropdownOpen && (
            <div className="absolute z-50 w-full mt-1 bg-bambu-dark-secondary border border-bambu-dark-tertiary rounded-lg shadow-lg max-h-48 overflow-y-auto">
              {filteredMaterials.length === 0 ? (
                <div className="px-3 py-2 text-sm text-bambu-gray">{t('inventory.noResults')}</div>
              ) : (
                filteredMaterials.map((material) => (
                  <button
                    key={material}
                    type="button"
                    className={`w-full px-3 py-2 text-left text-sm hover:bg-bambu-dark-tertiary ${
                      formData.material === material ? 'bg-bambu-green/10 text-bambu-green' : 'text-white'
                    }`}
                    onClick={() => {
                      updateField('material', material);
                      setMaterialDropdownOpen(false);
                      setMaterialSearch('');
                    }}
                  >
                    {material}
                  </button>
                ))
              )}
              {/* Allow custom material */}
              {materialSearch && !filteredMaterials.includes(materialSearch) && (
                <button
                  type="button"
                  className="w-full px-3 py-2 text-left text-sm hover:bg-bambu-dark-tertiary text-bambu-green border-t border-bambu-dark-tertiary"
                  onClick={() => {
                    updateField('material', materialSearch);
                    setMaterialDropdownOpen(false);
                    setMaterialSearch('');
                  }}
                >
                  {t('inventory.useCustomMaterial', { material: materialSearch })}
                </button>
              )}
            </div>
          )}
        </div>
        {errors?.material && (
          <p className="mt-1 text-xs text-red-400">{errors.material}</p>
        )}
      </div>

      {/* Brand (dropdown with search) */}
      <div>
        <label className="block text-sm font-medium text-bambu-gray mb-1">
          {t('inventory.brand')}{!quickAdd && ' *'}
        </label>
          <div className="relative" ref={brandRef}>
            <input
              type="text"
              className="w-full px-3 py-2 bg-bambu-dark border border-bambu-dark-tertiary rounded-lg text-white text-sm placeholder:text-bambu-gray/50 focus:outline-none focus:border-bambu-green"
              placeholder={t('inventory.searchBrand')}
              value={brandDropdownOpen ? brandSearch : formData.brand}
              onChange={(e) => {
                setBrandSearch(e.target.value);
                setBrandDropdownOpen(true);
              }}
              onFocus={() => {
                setBrandDropdownOpen(true);
                setBrandSearch('');
              }}
            />
            <ChevronDown className="absolute right-3 top-1/2 -translate-y-1/2 w-4 h-4 text-bambu-gray/50 pointer-events-none" />
            {brandDropdownOpen && (
              <div className="absolute z-50 w-full mt-1 bg-bambu-dark-secondary border border-bambu-dark-tertiary rounded-lg shadow-lg max-h-48 overflow-y-auto">
                {filteredBrands.length === 0 ? (
                  <div className="px-3 py-2 text-sm text-bambu-gray">{t('inventory.noResults')}</div>
                ) : (
                  filteredBrands.map(brand => (
                    <button
                      key={brand}
                      type="button"
                      className={`w-full px-3 py-2 text-left text-sm hover:bg-bambu-dark-tertiary ${
                        formData.brand === brand ? 'bg-bambu-green/10 text-bambu-green' : 'text-white'
                      }`}
                      onClick={() => {
                        updateField('brand', brand);
                        setBrandDropdownOpen(false);
                        setBrandSearch('');
                      }}
                    >
                      {brand}
                    </button>
                  ))
                )}
                {/* Allow custom brand */}
                {brandSearch && !filteredBrands.includes(brandSearch) && (
                  <button
                    type="button"
                    className="w-full px-3 py-2 text-left text-sm hover:bg-bambu-dark-tertiary text-bambu-green border-t border-bambu-dark-tertiary"
                    onClick={() => {
                      updateField('brand', brandSearch);
                      setBrandDropdownOpen(false);
                      setBrandSearch('');
                    }}
                  >
                    {t('inventory.useCustomBrand', { brand: brandSearch })}
                  </button>
                )}
              </div>
            )}
          </div>
          {errors?.brand && (
            <p className="mt-1 text-xs text-red-400">{errors.brand}</p>
          )}
      </div>

      {/* Variant / Subtype */}
      <div>
        <label className="block text-sm font-medium text-bambu-gray mb-1">
          {t('inventory.subtype')}{!quickAdd && ' *'}
        </label>
          <div className="relative" ref={subtypeRef}>
            <input
              type="text"
              value={subtypeDropdownOpen ? subtypeSearch : formData.subtype}
              onChange={(e) => {
                setSubtypeSearch(e.target.value);
                setSubtypeDropdownOpen(true);
              }}
              onFocus={() => {
                setSubtypeDropdownOpen(true);
                setSubtypeSearch('');
              }}
              placeholder="Basic, Matte, Silk..."
              className="w-full px-3 py-2 bg-bambu-dark border border-bambu-dark-tertiary rounded-lg text-white text-sm placeholder:text-bambu-gray/50 focus:outline-none focus:border-bambu-green"
            />
            <ChevronDown className="absolute right-3 top-1/2 -translate-y-1/2 w-4 h-4 text-bambu-gray/50 pointer-events-none" />
            {subtypeDropdownOpen && (
              <div className="absolute z-50 w-full mt-1 bg-bambu-dark-secondary border border-bambu-dark-tertiary rounded-lg shadow-lg max-h-48 overflow-y-auto">
                {filteredVariants.length === 0 ? (
                  <div className="px-3 py-2 text-sm text-bambu-gray">{t('inventory.noResults')}</div>
                ) : (
                  filteredVariants.map(variant => (
                    <button
                      key={variant}
                      type="button"
                      className={`w-full px-3 py-2 text-left text-sm hover:bg-bambu-dark-tertiary ${
                        formData.subtype === variant ? 'bg-bambu-green/10 text-bambu-green' : 'text-white'
                      }`}
                      onClick={() => {
                        updateField('subtype', variant);
                        setSubtypeDropdownOpen(false);
                        setSubtypeSearch('');
                      }}
                    >
                      {variant}
                    </button>
                  ))
                )}
                {subtypeSearch && !KNOWN_VARIANTS.some(v => v.toLowerCase() === subtypeSearch.toLowerCase().trim()) && (
                  <button
                    type="button"
                    className="w-full px-3 py-2 text-left text-sm hover:bg-bambu-dark-tertiary text-bambu-green border-t border-bambu-dark-tertiary"
                    onClick={() => {
                      updateField('subtype', subtypeSearch);
                      setSubtypeDropdownOpen(false);
                      setSubtypeSearch('');
                    }}
                  >
                    {t('inventory.useCustomBrand', { brand: subtypeSearch })}
                  </button>
                )}
              </div>
            )}
          </div>
          {errors?.subtype && (
            <p className="mt-1 text-xs text-red-400">{errors.subtype}</p>
          )}
      </div>

      {/* Label Weight */}
      <div>
        <label className="block text-sm font-medium text-bambu-gray mb-1">{t('inventory.labelWeight')}</label>
        <div className="relative">
          <input
            type="number"
            className="w-full px-3 py-2 pr-7 bg-bambu-dark border border-bambu-dark-tertiary rounded-lg text-white text-sm focus:outline-none focus:border-bambu-green"
            value={labelInput}
            min={0}
            onFocus={() => setIsLabelFocused(true)}
            onChange={(e) => setLabelInput(e.target.value)}
            onBlur={() => {
              setIsLabelFocused(false);
              const raw = labelInput.trim();
              const next = Number(raw);
              if (!raw || !Number.isFinite(next) || next < 0) {
                setLabelInput(String(formData.label_weight));
                return;
              }
              const rounded = Math.round(next);
              updateField('label_weight', rounded);
              setLabelInput(String(rounded));
            }}
          />
          <span className="absolute right-2 top-1/2 -translate-y-1/2 text-xs text-bambu-gray">g</span>
        </div>
      </div>

      {/* Quantity — only when creating new spools */}
      {showQuantity && (
        <div>
          <label className="block text-sm font-medium text-bambu-gray mb-1">{t('inventory.quantity')}</label>
          <input
            type="number"
            aria-label={t('inventory.quantity')}
            className="w-full px-3 py-2 bg-bambu-dark border border-bambu-dark-tertiary rounded-lg text-white text-sm focus:outline-none focus:border-bambu-green"
            value={quantityInput}
            min={1}
            max={100}
            onFocus={() => setIsQuantityFocused(true)}
            onChange={(e) => {
              const raw = e.target.value;
              if (!/^\d*$/.test(raw)) return;
              setQuantityInput(raw);
              if (raw === '') return;
              const parsed = Number(raw);
              if (Number.isFinite(parsed)) {
                onQuantityChange(Math.max(1, Math.min(100, parsed)));
              }
            }}
            onBlur={() => {
              setIsQuantityFocused(false);
              const parsed = Number(quantityInput);
              const next = Number.isFinite(parsed) && quantityInput.trim() !== ''
                ? Math.max(1, Math.min(100, parsed))
                : 1;
              onQuantityChange(next);
              setQuantityInput(String(next));
            }}
          />
        </div>
      )}

    </div>
  );
}
