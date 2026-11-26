/**
 * Tests for the MaintenancePage component.
 */

import { describe, it, expect, beforeEach, afterEach, vi } from 'vitest';
import { screen, waitFor, fireEvent } from '@testing-library/react';
import { render } from '../utils';
import { MaintenancePage } from '../../pages/MaintenancePage';
import { http, HttpResponse } from 'msw';
import { server } from '../mocks/server';

const mockPrinters = [
  {
    id: 1,
    name: 'X1 Carbon',
    model: 'X1C',
    serial_number: '00M09A350100001',
  },
];

const mockMaintenanceTypes = [
  {
    id: 1,
    name: 'Clean Nozzle',
    description: 'Clean the printer nozzle',
    default_interval_hours: 50,
    applies_to_models: ['X1C', 'P1S'],
  },
  {
    id: 2,
    name: 'Lubricate Rods',
    description: 'Lubricate linear rods',
    default_interval_hours: 200,
    applies_to_models: ['X1C', 'P1S'],
  },
];

const mockMaintenanceTasks = [
  {
    id: 1,
    printer_id: 1,
    maintenance_type_id: 1,
    maintenance_type_name: 'Clean Nozzle',
    interval_hours: 50,
    last_completed_at: '2024-01-01T00:00:00Z',
    next_due_at: '2024-01-03T00:00:00Z',
    hours_until_due: 10,
    is_due: false,
    notes: null,
  },
  {
    id: 2,
    printer_id: 1,
    maintenance_type_id: 2,
    maintenance_type_name: 'Lubricate Rods',
    interval_hours: 200,
    last_completed_at: '2023-12-01T00:00:00Z',
    next_due_at: '2023-12-15T00:00:00Z',
    hours_until_due: -100,
    is_due: true,
    notes: 'Use PTFE lubricant',
  },
];

describe('MaintenancePage', () => {
  beforeEach(() => {
    server.use(
      http.get('/api/v1/printers/', () => {
        return HttpResponse.json(mockPrinters);
      }),
      http.get('/api/v1/maintenance/types', () => {
        return HttpResponse.json(mockMaintenanceTypes);
      }),
      http.get('/api/v1/maintenance/', () => {
        return HttpResponse.json(mockMaintenanceTasks);
      }),
      http.get('/api/v1/maintenance/overview', () => {
        // Overview is an array of printer summaries
        return HttpResponse.json([
          {
            printer_id: 1,
            printer_name: 'X1 Carbon',
            due_count: 1,
            warning_count: 0,
            total_print_hours: 100,
            maintenance_items: [
              {
                id: 1,
                maintenance_type_id: 1,
                maintenance_type_name: 'Clean Nozzle',
                interval_hours: 50,
                hours_since_last: 45,
                hours_until_due: 5,
                is_due: false,
                is_warning: false,
              },
              {
                id: 2,
                maintenance_type_id: 2,
                maintenance_type_name: 'Lubricate Rods',
                interval_hours: 200,
                hours_since_last: 250,
                hours_until_due: -50,
                is_due: true,
                is_warning: false,
              },
            ],
          },
        ]);
      }),
      http.post('/api/v1/maintenance/', async ({ request }) => {
        const body = await request.json() as { name: string };
        return HttpResponse.json({ id: 3, ...body });
      }),
      http.post('/api/v1/maintenance/:id/complete', () => {
        return HttpResponse.json({ success: true });
      })
    );
  });

  describe('rendering', () => {
    it('renders the page title', async () => {
      render(<MaintenancePage />);

      await waitFor(() => {
        expect(screen.getByText('Maintenance')).toBeInTheDocument();
      });
    });

    it('renders maintenance page content', async () => {
      render(<MaintenancePage />);

      await waitFor(() => {
        // Page should render with printer tabs or tasks
        expect(screen.getByText('Maintenance')).toBeInTheDocument();
      });
    });
  });

  describe('printer tabs', () => {
    it('shows printer tabs when printers exist', async () => {
      render(<MaintenancePage />);

      await waitFor(() => {
        // Should show printer name in tabs
        expect(screen.getByText('X1 Carbon')).toBeInTheDocument();
      });
    });
  });

  describe('location filter', () => {
    const overviewWithLocations = [
      { printer_id: 1, printer_name: 'Printer Alpha', printer_model: 'X1C', printer_location: 'Site A', total_print_hours: 10, maintenance_items: [], due_count: 0, warning_count: 0 },
      { printer_id: 2, printer_name: 'Printer Beta', printer_model: 'P1S', printer_location: 'Site B', total_print_hours: 10, maintenance_items: [], due_count: 0, warning_count: 0 },
    ];
    let store: Map<string, string>;

    beforeEach(() => {
      store = new Map();
      vi.mocked(localStorage.getItem).mockImplementation((key: string) => store.get(key) ?? null);
      vi.mocked(localStorage.setItem).mockImplementation((key: string, value: string) => { store.set(key, value); });
      vi.mocked(localStorage.removeItem).mockImplementation((key: string) => { store.delete(key); });
      server.use(
        http.get('/api/v1/maintenance/overview', () => HttpResponse.json(overviewWithLocations)),
        http.get('/api/v1/printers/', () => HttpResponse.json([
          { id: 1, name: 'Printer Alpha', model: 'X1C', location: 'Site A' },
          { id: 2, name: 'Printer Beta', model: 'P1S', location: 'Site B' },
          { id: 3, name: 'Printer Gamma', model: 'P1S', location: 'Site C', is_active: false },
        ])),
      );
    });

    afterEach(() => {
      vi.mocked(localStorage.getItem).mockReset();
      vi.mocked(localStorage.setItem).mockReset();
      vi.mocked(localStorage.removeItem).mockReset();
    });

    it('filters the status tab by the selected location', async () => {
      render(<MaintenancePage />);
      await waitFor(() => expect(screen.getByText('Printer Beta')).toBeInTheDocument());

      fireEvent.change(screen.getByLabelText('All Locations'), { target: { value: 'Site A' } });

      expect(screen.getByText('Printer Alpha')).toBeInTheDocument();
      expect(screen.queryByText('Printer Beta')).not.toBeInTheDocument();
    });

    it('applies a locked location on load and shows the badge', async () => {
      store.set('locationFilterLocked', 'true');
      store.set('locationFilter', 'Site B');
      render(<MaintenancePage />);

      await waitFor(() => expect(screen.getByText('Printer Beta')).toBeInTheDocument());
      expect(screen.queryByText('Printer Alpha')).not.toBeInTheDocument();
      expect(screen.getByTestId('location-lock-badge')).toHaveTextContent('Location: Site B');
    });

    it('keeps a lock whose location has no printers in the overview (e.g. only inactive printers)', async () => {
      store.set('locationFilterLocked', 'true');
      store.set('locationFilter', 'Site C');
      render(<MaintenancePage />);

      await waitFor(() =>
        expect(screen.getByText('No printers with maintenance at Site C.')).toBeInTheDocument(),
      );
      expect(screen.getByTestId('location-lock-badge')).toHaveTextContent('Location: Site C');
      expect(store.get('locationFilterLocked')).toBe('true');
      expect(store.get('locationFilter')).toBe('Site C');
    });
  });
});
