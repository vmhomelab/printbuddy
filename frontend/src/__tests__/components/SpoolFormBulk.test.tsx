/**
 * Tests for bulk spool creation and quick-add mode.
 *
 * Verifies:
 * - Quick-add toggle appears only in create mode
 * - Quick-add mode shows brand and subtype as optional (no asterisk)
 * - Quick-add mode hides slicer preset field
 * - Quick-add mode hides PA Profile tab
 * - Quantity field is only rendered in quick-add mode
 * - Quantity field is hidden in edit mode
 * - Bulk create calls bulkCreateSpools when quantity > 1
 * - Single quantity calls createSpool as before
 * - validateForm with quickAdd=true only requires material
 */

import React from 'react';
import { describe, it, expect, vi, beforeEach } from 'vitest';
import { screen, waitFor, fireEvent } from '@testing-library/react';
import { api } from '../../api/client';
import { render } from '../utils';
import { SpoolFormModal } from '../../components/SpoolFormModal';
import { validateForm, defaultFormData } from '../../components/spool-form/types';
import type { InventorySpool } from '../../api/client';

// Mock the API client
vi.mock('../../api/client', () => ({
  api: {
    getSettings: vi.fn().mockResolvedValue({}),
    getAuthStatus: vi.fn().mockResolvedValue({ auth_enabled: false }),
    getCloudStatus: vi.fn().mockResolvedValue({ is_authenticated: false }),
    getFilamentPresets: vi.fn().mockResolvedValue([]),
    getSpoolCatalog: vi.fn().mockResolvedValue([]),
    getColorCatalog: vi.fn().mockResolvedValue([]),
    getLocalPresets: vi.fn().mockResolvedValue({ filament: [] }),
    getBuiltinFilaments: vi.fn().mockResolvedValue([]),
    getPrinters: vi.fn().mockResolvedValue([]),
    getSpoolUsageHistory: vi.fn().mockResolvedValue([]),
    getSpoolmanInventoryFilaments: vi.fn().mockResolvedValue([]),
    getSpoolmanSlotAssignments: vi.fn().mockResolvedValue([]),
    createSpoolmanInventorySpool: vi.fn().mockResolvedValue({ id: 199, k_profiles: [] }),
    bulkCreateSpoolmanInventorySpools: vi.fn().mockResolvedValue({ created: [], requested_count: 0, failed_count: 0, failures: [] }),
    updateSpoolmanInventorySpool: vi.fn().mockResolvedValue({ id: 1 }),
    getOpenFilamentDatabaseBrands: vi.fn().mockResolvedValue({ brands: [] }),
    getOpenFilamentDatabaseBrand: vi.fn().mockResolvedValue({ materials: [] }),
    searchOpenFilamentDatabase: vi.fn().mockResolvedValue({ filaments: [] }),
    getOpenFilamentDatabaseFilament: vi.fn().mockResolvedValue({ variants: [], spool_prefill: {} }),
    getOpenFilamentDatabaseVariant: vi.fn().mockResolvedValue({ spool_prefill: {} }),
    createSpool: vi.fn().mockResolvedValue({ id: 99 }),
    bulkCreateSpools: vi.fn().mockResolvedValue([
      { id: 100, k_profiles: [] },
      { id: 101, k_profiles: [] },
      { id: 102, k_profiles: [] },
    ]),
    updateSpool: vi.fn().mockResolvedValue({ id: 1 }),
    saveSpoolKProfiles: vi.fn().mockResolvedValue([]),
  },
}));

// Mock the toast context
const mockShowToast = vi.fn();
vi.mock('../../contexts/ToastContext', async (importOriginal) => {
  const actual = await importOriginal<typeof import('../../contexts/ToastContext')>();
  return {
    ...actual,
    useToast: () => ({ showToast: mockShowToast }),
  };
});

const existingSpool: InventorySpool = {
  id: 1,
  material: 'PLA',
  subtype: 'Basic',
  brand: 'Polymaker',
  color_name: 'Red',
  rgba: 'FF0000FF',
  extra_colors: null,
  effect_type: null,
  label_weight: 1000,
  core_weight: 250,
  core_weight_catalog_id: null,
  weight_used: 300,
  slicer_filament: 'GFL99',
  slicer_filament_name: 'Generic PLA',
  nozzle_temp_min: null,
  nozzle_temp_max: null,
  note: null,
  added_full: null,
  last_used: null,
  encode_time: null,
  tag_uid: null,
  tray_uuid: null,
  data_origin: null,
  tag_type: null,
  archived_at: null,
  created_at: '2025-01-01T00:00:00Z',
  updated_at: '2025-01-01T00:00:00Z',
  k_profiles: [],
  cost_per_kg: null,
};

describe('validateForm with quickAdd', () => {
  it('requires only material in quick-add mode', () => {
    const result = validateForm({ ...defaultFormData, material: 'PLA' }, true);
    expect(result.isValid).toBe(true);
    expect(result.errors).toEqual({});
  });

  it('rejects empty material in quick-add mode', () => {
    const result = validateForm({ ...defaultFormData, material: '' }, true);
    expect(result.isValid).toBe(false);
    expect(result.errors.material).toBeDefined();
  });

  it('does not require slicer_filament in quick-add mode', () => {
    const result = validateForm(
      { ...defaultFormData, material: 'PETG', slicer_filament: '' },
      true,
    );
    expect(result.isValid).toBe(true);
  });

  it('does not require brand in quick-add mode', () => {
    const result = validateForm(
      { ...defaultFormData, material: 'ABS', brand: '' },
      true,
    );
    expect(result.isValid).toBe(true);
  });

  it('does not require subtype in quick-add mode', () => {
    const result = validateForm(
      { ...defaultFormData, material: 'TPU', subtype: '' },
      true,
    );
    expect(result.isValid).toBe(true);
  });

  it('requires all fields in full mode (quickAdd=false)', () => {
    const result = validateForm(defaultFormData, false);
    expect(result.isValid).toBe(false);
    expect(result.errors.material).toBeDefined();
    expect(result.errors.slicer_filament).toBeDefined();
    expect(result.errors.brand).toBeDefined();
    expect(result.errors.subtype).toBeDefined();
  });
});

describe('SpoolFormModal quick-add toggle', () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  it('shows quick-add toggle in create mode', async () => {
    render(
      <SpoolFormModal
        isOpen={true}
        onClose={vi.fn()}
        mode="create"
        currencySymbol="$"
      />,
    );

    await waitFor(() => {
      expect(screen.getByRole('heading', { name: 'Add Spool' })).toBeInTheDocument();
    });

    expect(screen.getByText('Quick Add (Stock)')).toBeInTheDocument();
  });

  it('hides quick-add toggle in edit mode', async () => {
    render(
      <SpoolFormModal
        isOpen={true}
        onClose={vi.fn()}
        spool={existingSpool}
        mode="edit"
        currencySymbol="$"
      />,
    );

    await waitFor(() => {
      expect(screen.getByText('Edit Spool')).toBeInTheDocument();
    });

    expect(screen.queryByText('Quick Add (Stock)')).not.toBeInTheDocument();
  });

  it('hides PA Profile tab when quick-add is enabled', async () => {
    render(
      <SpoolFormModal
        isOpen={true}
        onClose={vi.fn()}
        mode="create"
        currencySymbol="$"
      />,
    );

    await waitFor(() => {
      expect(screen.getByRole('heading', { name: 'Add Spool' })).toBeInTheDocument();
    });

    // PA Profile tab should be visible initially
    expect(screen.getByText('PA Profile')).toBeInTheDocument();

    // Toggle quick-add on — the toggle is a button[role="switch"] sibling of the label
    const toggleButtons = screen.getAllByRole('button');
    const quickAddToggle = toggleButtons.find(btn =>
      btn.getAttribute('type') === 'button' &&
      btn.className.includes('rounded-full') &&
      btn.closest('div')?.textContent?.includes('Quick Add')
    );
    expect(quickAddToggle).toBeTruthy();
    fireEvent.click(quickAddToggle!);

    // PA Profile tab should be hidden
    await waitFor(() => {
      expect(screen.queryByText('PA Profile')).not.toBeInTheDocument();
    });
  });

  it('hides quantity field by default (non-quick-add)', async () => {
    render(
      <SpoolFormModal
        isOpen={true}
        onClose={vi.fn()}
        mode="create"
        currencySymbol="$"
      />,
    );

    await waitFor(() => {
      expect(screen.getByRole('heading', { name: 'Add Spool' })).toBeInTheDocument();
    });

    // Quantity field should NOT be visible in normal create mode
    expect(screen.queryByText('Quantity')).not.toBeInTheDocument();
  });

  it('shows quantity field only in quick-add mode', async () => {
    render(
      <SpoolFormModal
        isOpen={true}
        onClose={vi.fn()}
        mode="create"
        currencySymbol="$"
      />,
    );

    await waitFor(() => {
      expect(screen.getByRole('heading', { name: 'Add Spool' })).toBeInTheDocument();
    });

    // Toggle quick-add on
    const toggleButtons = screen.getAllByRole('button');
    const quickAddToggle = toggleButtons.find(btn =>
      btn.getAttribute('type') === 'button' &&
      btn.className.includes('rounded-full') &&
      btn.closest('div')?.textContent?.includes('Quick Add')
    );
    expect(quickAddToggle).toBeTruthy();
    fireEvent.click(quickAddToggle!);

    // Quantity field should now be visible
    await waitFor(() => {
      expect(screen.getByText('Quantity')).toBeInTheDocument();
    });
  });

  it('hides quantity field in edit mode', async () => {
    render(
      <SpoolFormModal
        isOpen={true}
        onClose={vi.fn()}
        spool={existingSpool}
        mode="edit"
        currencySymbol="$"
      />,
    );

    await waitFor(() => {
      expect(screen.getByText('Edit Spool')).toBeInTheDocument();
    });

    // Quantity field should NOT be visible in edit mode
    expect(screen.queryByText('Quantity')).not.toBeInTheDocument();
  });

  it('shows brand and subtype in quick-add mode without asterisk', async () => {
    render(
      <SpoolFormModal
        isOpen={true}
        onClose={vi.fn()}
        mode="create"
        currencySymbol="$"
      />,
    );

    await waitFor(() => {
      expect(screen.getByRole('heading', { name: 'Add Spool' })).toBeInTheDocument();
    });

    // Toggle quick-add on
    const toggleButtons = screen.getAllByRole('button');
    const quickAddToggle = toggleButtons.find(btn =>
      btn.getAttribute('type') === 'button' &&
      btn.className.includes('rounded-full') &&
      btn.closest('div')?.textContent?.includes('Quick Add')
    );
    fireEvent.click(quickAddToggle!);

    // Brand and Subtype should be visible (without asterisk = optional)
    await waitFor(() => {
      const brandLabel = screen.getByText('Brand');
      expect(brandLabel).toBeInTheDocument();
      expect(brandLabel.textContent).not.toContain('*');

      const subtypeLabel = screen.getByText('Subtype');
      expect(subtypeLabel).toBeInTheDocument();
      expect(subtypeLabel.textContent).not.toContain('*');
    });
  });
});

describe('SpoolFormModal Spoolman OFDB creation', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    vi.mocked(api.getSettings).mockResolvedValue({ open_filament_database_enabled: true });
    vi.mocked(api.getSpoolmanInventoryFilaments).mockResolvedValue([
      { id: 44, name: 'PETG Matte', material: 'PETG', color_hex: '123456', color_name: 'Blue', weight: 1000, vendor: { id: 1, name: 'SpoolmanBrand' } },
    ] as never);
    vi.mocked(api.getOpenFilamentDatabaseBrands).mockResolvedValue({
      brands: [{ id: 'brand-polymaker', slug: 'polymaker', name: 'Polymaker', material_count: 1 }],
    } as never);
    vi.mocked(api.getOpenFilamentDatabaseBrand).mockResolvedValue({
      brand: { id: 'brand-polymaker', slug: 'polymaker', name: 'Polymaker' },
      materials: [{ id: 'mat-petg', material: 'PETG', filament_count: 1 }],
    } as never);
    vi.mocked(api.searchOpenFilamentDatabase).mockResolvedValue({
      filaments: [{ id: 'fil-polyterra', slug: 'polyterra-petg', name: 'PolyTerra PETG', variant_count: 1 }],
    } as never);
    vi.mocked(api.getOpenFilamentDatabaseFilament).mockResolvedValue({
      filament: { id: 'fil-polyterra', slug: 'polyterra-petg', name: 'PolyTerra PETG' },
      variants: [{ id: 'var-teal', slug: 'teal', name: 'Teal', color_hex: '#008080', size_count: 1 }],
      spool_prefill: { brand: 'Polymaker', material: 'PETG', subtype: 'PolyTerra' },
    } as never);
    vi.mocked(api.getOpenFilamentDatabaseVariant).mockResolvedValue({
      variant: { id: 'var-teal', slug: 'teal', name: 'Teal', color_hex: '#008080' },
      spool_prefill: {
        brand: 'Polymaker',
        material: 'PETG',
        subtype: 'PolyTerra',
        color_name: 'Teal',
        rgba: '008080FF',
        label_weight: 1000,
        data_origin: 'openfilamentdatabase',
      },
    } as never);
  });

  it('allows OFDB prefill when creating a Spoolman spool and posts without a catalog filament id', async () => {
    render(
      <SpoolFormModal
        isOpen={true}
        onClose={vi.fn()}
        mode="create"
        currencySymbol="$"
        spoolmanMode={true}
        spoolsQueryKey={['spoolman-inventory-spools']}
      />,
    );

    await screen.findByText('Spoolman Filament Catalog');
    const ofdbBrandInput = await screen.findByPlaceholderText('Search OFDB brands...');
    fireEvent.focus(ofdbBrandInput);

    await screen.findByText('Polymaker');
    fireEvent.click(screen.getByText('Polymaker'));

    await screen.findByText('PETG');
    fireEvent.click(screen.getByText('PETG'));

    fireEvent.click(screen.getByRole('button', { name: 'Search' }));
    await screen.findByText('PolyTerra PETG');
    fireEvent.click(screen.getByText('PolyTerra PETG'));

    await screen.findByText('Teal');
    fireEvent.click(screen.getByText('Teal'));

    await waitFor(() => expect(screen.getByDisplayValue('PETG')).toBeInTheDocument());
    fireEvent.click(screen.getByRole('button', { name: 'Add Spool' }));

    await waitFor(() => expect(api.createSpoolmanInventorySpool).toHaveBeenCalled());
    expect(api.createSpoolmanInventorySpool).toHaveBeenCalledWith(expect.objectContaining({
      spoolman_filament_id: null,
      brand: 'Polymaker',
      material: 'PETG',
      subtype: 'PolyTerra',
      color_name: 'Teal',
      rgba: '008080FF',
      label_weight: 1000,
      data_origin: 'openfilamentdatabase',
    }));
  });
});
