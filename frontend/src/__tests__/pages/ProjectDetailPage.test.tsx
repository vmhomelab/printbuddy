/**
 * Tests for the ProjectDetailPage component.
 * Covers: isSlicedFilename conditional print-button logic, linked folder file rendering,
 * and the PrintModal open trigger with projectId.
 */

/// <reference types="@testing-library/jest-dom" />

import { describe, it, expect, beforeEach, vi } from 'vitest';
import { screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { render } from '../utils';
import { ProjectDetailPage } from '../../pages/ProjectDetailPage';
import { http, HttpResponse } from 'msw';
import { server } from '../mocks/server';

// Mock useParams so the component receives a fixed project id without a nested Router
vi.mock('react-router-dom', async () => {
  const actual = await vi.importActual<typeof import('react-router-dom')>('react-router-dom');
  return {
    ...actual,
    useParams: () => ({ id: '1' }),
    useNavigate: () => vi.fn(),
  };
});

const mockProject = {
  id: 1,
  name: 'Test Project',
  description: 'A test project',
  color: '#00ae42',
  status: 'active',
  priority: 'normal',
  due_date: null,
  notes: null,
  budget: null,
  target_count: null,
  target_parts_count: null,
  parent_id: null,
  archive_count: 0,
  total_print_time_seconds: 0,
  total_filament_grams: 0,
  created_at: '2024-01-01T00:00:00Z',
  updated_at: '2024-01-01T00:00:00Z',
};

const mockFolder = {
  id: 10,
  name: 'Sliced Files',
  project_id: 1,
  archive_id: null,
  parent_id: null,
  file_count: 3,
  created_at: '2024-01-01T00:00:00Z',
  updated_at: '2024-01-01T00:00:00Z',
};

const mockStats = {
  total_archives: 2,
  total_items: 7,
  completed_prints: 6,
  failed_prints: 1,
  queued_prints: 1,
  in_progress_prints: 0,
  total_print_time_hours: 2.5,
  total_filament_grams: 114,
  progress_percent: 50,
  parts_progress_percent: 60,
  estimated_cost: 0,
  total_energy_kwh: 0,
  total_energy_cost: 0,
  remaining_prints: 2,
  remaining_parts: 4,
  bom_total_items: 10,
  bom_completed_items: 6,
  bom_cost: 0,
};

const productionProject = {
  ...mockProject,
  target_count: 4,
  target_parts_count: 10,
  stats: mockStats,
};

const gridfinityBinBom = {
  id: 21,
  project_id: 1,
  name: 'Gridfinity Bin',
  quantity_needed: 10,
  quantity_acquired: 6,
  unit_price: null,
  sourcing_url: null,
  archive_id: null,
  archive_name: null,
  stl_filename: 'gridfinity-bin.stl',
  remarks: null,
  sort_order: 0,
  is_complete: false,
  created_at: '2024-01-01T00:00:00Z',
  updated_at: '2024-01-01T00:00:00Z',
};

const dispatchPrinters = [
  {
    id: 1,
    name: 'PRA-01',
    serial_number: 'PRA01',
    ip_address: '10.0.0.11',
    access_code: '',
    provider: 'bambu',
    api_url: null,
    auth_token: null,
    provider_options: null,
    model: 'P1S',
    location: 'Production Row A',
    nozzle_count: 1,
    is_active: true,
    auto_archive: true,
    external_camera_url: null,
    external_camera_type: null,
    external_camera_enabled: false,
    external_camera_snapshot_url: null,
    camera_rotation: 0,
    plate_detection_enabled: false,
    created_at: '2024-01-01T00:00:00Z',
    updated_at: '2024-01-01T00:00:00Z',
  },
  {
    id: 2,
    name: 'PRB-04',
    serial_number: 'PRB04',
    ip_address: '10.0.0.12',
    access_code: '',
    provider: 'klipper',
    api_url: null,
    auth_token: null,
    provider_options: null,
    model: 'Generic FDM Printer',
    location: 'Engineering Row B',
    nozzle_count: 1,
    is_active: true,
    auto_archive: true,
    external_camera_url: null,
    external_camera_type: null,
    external_camera_enabled: false,
    external_camera_snapshot_url: null,
    camera_rotation: 0,
    plate_detection_enabled: false,
    created_at: '2024-01-01T00:00:00Z',
    updated_at: '2024-01-01T00:00:00Z',
  },
];

function dispatchStatus(id: number) {
  return {
    id,
    name: id === 1 ? 'PRA-01' : 'PRB-04',
    connected: true,
    state: id === 1 ? 'IDLE' : 'PRINTING',
    current_print: id === 1 ? null : 'Busy print',
    subtask_name: null,
    gcode_file: null,
    progress: id === 1 ? null : 42,
    remaining_time: null,
    layer_num: null,
    total_layers: null,
    temperatures: { nozzle: 28, bed: 27 },
    hms_errors: [],
    ams: [],
    ams_exists: false,
    vt_tray: [],
    supports_drying: false,
    awaiting_plate_clear: false,
  };
}

const gridfinityArchive = {
  id: 31,
  printer_id: 1,
  project_id: 1,
  project_name: 'Test Project',
  filename: 'gridfinity-bin-plate-01.gcode.3mf',
  file_path: '/archives/gridfinity-bin-plate-01.gcode.3mf',
  file_size: 1024,
  content_hash: null,
  thumbnail_path: null,
  timelapse_path: null,
  source_3mf_path: null,
  f3d_path: null,
  duplicates: null,
  duplicate_count: 0,
  duplicate_sequence: 0,
  original_archive_id: null,
  object_count: 4,
  print_name: 'Gridfinity Bin Plate 01',
  print_time_seconds: 5400,
  actual_time_seconds: null,
  time_accuracy: null,
  filament_used_grams: 84,
  filament_type: 'PLA',
  filament_color: 'Blue',
  layer_height: null,
  total_layers: null,
  nozzle_diameter: null,
  bed_temperature: null,
  bed_type: 'Textured PEI Plate',
  nozzle_temperature: null,
  sliced_for_model: 'P1S',
  status: 'completed',
  started_at: null,
  completed_at: null,
  extra_data: null,
  makerworld_url: null,
  designer: null,
  external_url: null,
  is_favorite: false,
  tags: null,
  notes: null,
  cost: null,
  photos: null,
  failure_reason: null,
  quantity: 4,
  energy_kwh: null,
  energy_cost: null,
  created_at: '2024-01-01T00:00:00Z',
  created_by_id: null,
  created_by_username: null,
  run_count: 1,
  last_run_at: null,
  total_filament_actual_grams: null,
  successful_run_count: 1,
  failed_run_count: 0,
};

function makeFile(overrides: { id: number; filename: string; file_type?: string }) {
  return {
    id: overrides.id,
    filename: overrides.filename,
    print_name: null,
    file_type: overrides.file_type ?? '3mf',
    folder_id: 10,
    project_id: 1,
    file_hash: null,
    file_size_bytes: 1024,
    thumbnail_path: null,
    created_at: '2024-01-01T00:00:00Z',
    updated_at: '2024-01-01T00:00:00Z',
    duplicate_count: 0,
  };
}

describe('ProjectDetailPage', () => {
  beforeEach(() => {
    server.use(
      http.get('/api/v1/projects/:id', () => {
        return HttpResponse.json(mockProject);
      }),
      http.get('/api/v1/projects/:id/archives', () => {
        return HttpResponse.json([]);
      }),
      http.get('/api/v1/projects/:id/bom', () => {
        return HttpResponse.json([]);
      }),
      http.get('/api/v1/projects/:id/timeline', () => {
        return HttpResponse.json([]);
      }),
      http.get('/api/v1/library/folders/by-project/:id', () => {
        return HttpResponse.json([mockFolder]);
      }),
      http.get('/api/v1/printers/', () => HttpResponse.json([])),
      http.get('/api/v1/queue/', () => HttpResponse.json([])),
      http.get('/api/v1/inventory/assignments', () => HttpResponse.json([])),
      http.get('/api/v1/library/files/:id/filament-requirements', ({ params }) => HttpResponse.json({ file_id: Number(params.id), filename: 'test.gcode.3mf', filaments: [] })),
    );
  });

  describe('archive tiles', () => {
    it('open the archive on the Archives page, marked (#3336)', async () => {
      server.use(
        http.get('/api/v1/projects/:id/archives', () =>
          HttpResponse.json([{ id: 42, print_name: 'Bracket', status: 'completed', thumbnail_path: null }]),
        ),
        http.get('/api/v1/library/files', () => HttpResponse.json([])),
      );

      render(<ProjectDetailPage />);

      // ?search= was never read by the Archives page. The name also appears in
      // Printbuddy's production plan table, so pick the tile's own link.
      const names = await screen.findAllByText('Bracket');
      const tile = names.map((name) => name.closest('a')).find((link) => link !== null);
      expect(tile).toHaveAttribute('href', '/archives?highlight=42');
    });
  });

  describe('isSlicedFilename — conditional print button', () => {
    it('shows print button for .gcode files', async () => {
      server.use(
        http.get('/api/v1/library/files', () => {
          return HttpResponse.json([makeFile({ id: 1, filename: 'benchy.gcode', file_type: 'gcode' })]);
        })
      );

      render(<ProjectDetailPage />);

      await waitFor(() => {
        expect(screen.getByTitle('Print')).toBeInTheDocument();
      });
    });

    it('shows print button for .gcode.3mf files', async () => {
      server.use(
        http.get('/api/v1/library/files', () => {
          return HttpResponse.json([makeFile({ id: 2, filename: 'benchy.gcode.3mf', file_type: '3mf' })]);
        })
      );

      render(<ProjectDetailPage />);

      await waitFor(() => {
        expect(screen.getByTitle('Print')).toBeInTheDocument();
      });
    });

    it('does NOT show print button for .gcode.bak files (regression for includes bug)', async () => {
      server.use(
        http.get('/api/v1/library/files', () => {
          return HttpResponse.json([makeFile({ id: 3, filename: 'benchy.gcode.bak', file_type: '3mf' })]);
        })
      );

      render(<ProjectDetailPage />);

      await waitFor(() => {
        expect(screen.getAllByText('benchy.gcode.bak').length).toBeGreaterThan(0);
      });

      expect(screen.queryByTitle('Print')).not.toBeInTheDocument();
    });

    it('does NOT show print button for .stl files', async () => {
      server.use(
        http.get('/api/v1/library/files', () => {
          return HttpResponse.json([makeFile({ id: 4, filename: 'model.stl', file_type: 'stl' })]);
        })
      );

      render(<ProjectDetailPage />);

      await waitFor(() => {
        expect(screen.getAllByText('model.stl').length).toBeGreaterThan(0);
      });

      expect(screen.queryByTitle('Print')).not.toBeInTheDocument();
    });
  });

  describe('linked folder file rendering', () => {
    it('renders filenames from linked folder', async () => {
      server.use(
        http.get('/api/v1/library/files', () => {
          return HttpResponse.json([
            makeFile({ id: 5, filename: 'part_a.gcode.3mf', file_type: '3mf' }),
            makeFile({ id: 6, filename: 'design.stl', file_type: 'stl' }),
          ]);
        })
      );

      render(<ProjectDetailPage />);

      await waitFor(() => {
        expect(screen.getAllByText('part_a.gcode.3mf').length).toBeGreaterThan(0);
        expect(screen.getAllByText('design.stl').length).toBeGreaterThan(0);
      });
    });

    it('renders the linked folder name', async () => {
      server.use(
        http.get('/api/v1/library/files', () => {
          return HttpResponse.json([]);
        })
      );

      render(<ProjectDetailPage />);

      await waitFor(() => {
        expect(screen.getByText('Sliced Files')).toBeInTheDocument();
      });
    });
  });

  describe('print modal trigger', () => {
    it('opens PrintModal when print button is clicked on a sliced file', async () => {
      const user = userEvent.setup();

      server.use(
        http.get('/api/v1/library/files', () => {
          return HttpResponse.json([makeFile({ id: 7, filename: 'cube.gcode.3mf', file_type: '3mf' })]);
        }),
        http.get('/api/v1/printers/', () => {
          return HttpResponse.json([]);
        }),
        http.get('/api/v1/library/files/:id', () => {
          return HttpResponse.json(makeFile({ id: 7, filename: 'cube.gcode.3mf', file_type: '3mf' }));
        }),
        http.get('/api/v1/library/files/:id/plates', () => {
          return HttpResponse.json({ is_multi_plate: false, plates: [] });
        }),
        http.get('/api/v1/library/files/:id/filament-requirements', () => {
          return HttpResponse.json({ file_id: 7, filename: 'cube.gcode.3mf', filaments: [] });
        }),
      );

      render(<ProjectDetailPage />);

      await waitFor(() => {
        expect(screen.getByTitle('Print')).toBeInTheDocument();
      });

      await user.click(screen.getByTitle('Print'));

      // PrintModal should open — look for the modal heading "Print"
      await waitFor(() => {
        expect(screen.getByRole('heading', { name: 'Print' })).toBeInTheDocument();
      });
    });
  });

  describe('production plan overview', () => {
    it('summarizes project parts, build plates, quantities, material, and queue/archive states', async () => {
      server.use(
        http.get('/api/v1/projects/:id', () => HttpResponse.json(productionProject)),
        http.get('/api/v1/projects/:id/archives', () => HttpResponse.json([gridfinityArchive])),
        http.get('/api/v1/projects/:id/bom', () => HttpResponse.json([gridfinityBinBom])),
        http.get('/api/v1/library/files', () => HttpResponse.json([
          makeFile({ id: 41, filename: 'gridfinity-bin-plate-02.gcode.3mf', file_type: '3mf' }),
        ])),
      );

      render(<ProjectDetailPage />);

      expect(await screen.findByRole('heading', { name: 'Production Plan' })).toBeInTheDocument();
      expect(screen.getAllByText('Gridfinity Bin').length).toBeGreaterThan(0);
      expect(screen.getByText('6 / 10 complete')).toBeInTheDocument();
      expect(screen.getAllByText('Gridfinity Bin Plate 01').length).toBeGreaterThan(0);
      expect(screen.getAllByText('gridfinity-bin-plate-02.gcode.3mf').length).toBeGreaterThan(0);
      expect(screen.getByText('PLA')).toBeInTheDocument();
      expect(screen.getByText('P1S')).toBeInTheDocument();
      expect(screen.getByText('Textured PEI Plate')).toBeInTheDocument();
      expect(screen.getByText(/84g/)).toBeInTheDocument();
      expect(screen.getByText(/1h 30m/)).toBeInTheDocument();
      expect(screen.getByText('Needs staging')).toBeInTheDocument();
    });

    it('marks production plan files as printing from live printer status and queue links', async () => {
      server.use(
        http.get('/api/v1/projects/:id', () => HttpResponse.json(productionProject)),
        http.get('/api/v1/projects/:id/archives', () => HttpResponse.json([gridfinityArchive])),
        http.get('/api/v1/projects/:id/bom', () => HttpResponse.json([gridfinityBinBom])),
        http.get('/api/v1/library/files', () => HttpResponse.json([
          makeFile({ id: 41, filename: 'gridfinity-bin-plate-02.gcode.3mf', file_type: '3mf' }),
        ])),
        http.get('/api/v1/printers/', () => HttpResponse.json(dispatchPrinters)),
        http.get('/api/v1/printers/:id/status', ({ params }) => HttpResponse.json(Number(params.id) === 1 ? {
          ...dispatchStatus(1),
          state: 'PRINTING',
          current_print: 'gridfinity-bin-plate-02.gcode.3mf',
          progress: 68,
        } : dispatchStatus(Number(params.id)))),
        http.get('/api/v1/queue/', () => HttpResponse.json([
          {
            id: 91,
            status: 'printing',
            project_id: 1,
            library_file_id: 41,
            library_file_name: 'gridfinity-bin-plate-02.gcode.3mf',
            archive_name: null,
            printer_name: 'PRA-01',
          },
        ])),
      );

      render(<ProjectDetailPage />);

      expect(await screen.findByRole('heading', { name: 'Production Plan' })).toBeInTheDocument();
      await waitFor(() => expect(screen.getByText('Printing on PRA-01')).toBeInTheDocument());
      // Printer statuses arrive through the batched bulk read, a beat after the page.
      expect(await screen.findByText('68%')).toBeInTheDocument();
    });

    it('opens add-to-queue modal from a production plan project file', async () => {
      const user = userEvent.setup();
      server.use(
        http.get('/api/v1/projects/:id', () => HttpResponse.json(productionProject)),
        http.get('/api/v1/projects/:id/archives', () => HttpResponse.json([gridfinityArchive])),
        http.get('/api/v1/projects/:id/bom', () => HttpResponse.json([gridfinityBinBom])),
        http.get('/api/v1/library/files', () => HttpResponse.json([
          makeFile({ id: 41, filename: 'gridfinity-bin-plate-02.gcode.3mf', file_type: '3mf' }),
        ])),
        http.get('/api/v1/printers/', () => HttpResponse.json([])),
        http.get('/api/v1/library/files/:id', () => HttpResponse.json(makeFile({ id: 41, filename: 'gridfinity-bin-plate-02.gcode.3mf', file_type: '3mf' }))),
        http.get('/api/v1/library/files/:id/plates', () => HttpResponse.json({ is_multi_plate: false, plates: [] })),
        http.get('/api/v1/library/files/:id/filament-requirements', () => HttpResponse.json({ file_id: 41, filename: 'gridfinity-bin-plate-02.gcode.3mf', filaments: [{ slot_id: 1, type: 'PLA', color: '#0000ff', used_grams: 84, used_meters: 28 }] })),
      );

      render(<ProjectDetailPage />);

      expect(await screen.findByRole('heading', { name: 'Production Plan' })).toBeInTheDocument();
      await user.click(screen.getByRole('button', { name: /stage gridfinity-bin-plate-02\.gcode\.3mf to queue/i }));

      expect(await screen.findByRole('heading', { name: 'Print' })).toBeInTheDocument();
    });

    it('reviews selected dispatch suggestions before opening the staging modal', async () => {
      const user = userEvent.setup();
      server.use(
        http.get('/api/v1/projects/:id', () => HttpResponse.json(productionProject)),
        http.get('/api/v1/projects/:id/archives', () => HttpResponse.json([gridfinityArchive])),
        http.get('/api/v1/projects/:id/bom', () => HttpResponse.json([gridfinityBinBom])),
        http.get('/api/v1/library/files', () => HttpResponse.json([
          makeFile({ id: 41, filename: 'gridfinity-bin-plate-02.gcode.3mf', file_type: '3mf' }),
          makeFile({ id: 42, filename: 'gridfinity-bin-plate-03.gcode.3mf', file_type: '3mf' }),
        ])),
        http.get('/api/v1/printers/', () => HttpResponse.json(dispatchPrinters)),
        http.get('/api/v1/printers/:id/status', ({ params }) => HttpResponse.json(dispatchStatus(Number(params.id)))),
        http.get('/api/v1/queue/', () => HttpResponse.json([])),
        http.get('/api/v1/library/files/:id', ({ params }) => HttpResponse.json(makeFile({ id: Number(params.id), filename: Number(params.id) === 42 ? 'gridfinity-bin-plate-03.gcode.3mf' : 'gridfinity-bin-plate-02.gcode.3mf', file_type: '3mf' }))),
        http.get('/api/v1/library/files/:id/plates', () => HttpResponse.json({ is_multi_plate: false, plates: [] })),
        http.get('/api/v1/library/files/:id/filament-requirements', ({ params }) => HttpResponse.json({ file_id: Number(params.id), filename: 'gridfinity-bin-plate.gcode.3mf', filaments: [] })),
      );

      render(<ProjectDetailPage />);

      const dispatchHeading = await screen.findByRole('heading', { name: 'Dispatch Suggestions' });
      const dispatchSection = dispatchHeading.closest('.rounded-lg, .card, div')?.parentElement?.parentElement?.parentElement || document.body;
      await waitFor(() => expect(within(dispatchSection).getAllByText('Ready to stage').length).toBeGreaterThanOrEqual(2));

      await user.click(within(dispatchSection).getByRole('checkbox', { name: /select gridfinity-bin-plate-02\.gcode\.3mf/i }));
      await user.click(within(dispatchSection).getByRole('checkbox', { name: /select gridfinity-bin-plate-03\.gcode\.3mf/i }));
      await user.click(within(dispatchSection).getByRole('button', { name: /review selected dispatch jobs/i }));

      const dialog = await screen.findByRole('dialog', { name: /batch dispatch review/i });
      expect(within(dialog).getByText('2 jobs selected for staging review.')).toBeInTheDocument();
      expect(within(dialog).getByText('gridfinity-bin-plate-02.gcode.3mf')).toBeInTheDocument();
      expect(within(dialog).getByText('gridfinity-bin-plate-03.gcode.3mf')).toBeInTheDocument();

      await user.click(within(dialog).getByRole('button', { name: /stage first selected job/i }));
      expect(await screen.findByRole('heading', { name: 'Print' })).toBeInTheDocument();
    });

    it('suggests safe dispatch targets and opens review staging for the suggested printer', async () => {
      const user = userEvent.setup();
      server.use(
        http.get('/api/v1/projects/:id', () => HttpResponse.json(productionProject)),
        http.get('/api/v1/projects/:id/archives', () => HttpResponse.json([gridfinityArchive])),
        http.get('/api/v1/projects/:id/bom', () => HttpResponse.json([gridfinityBinBom])),
        http.get('/api/v1/library/files', () => HttpResponse.json([
          makeFile({ id: 41, filename: 'gridfinity-bin-plate-02.gcode.3mf', file_type: '3mf' }),
        ])),
        http.get('/api/v1/printers/', () => HttpResponse.json(dispatchPrinters)),
        http.get('/api/v1/printers/:id/status', ({ params }) => HttpResponse.json(dispatchStatus(Number(params.id)))),
        http.get('/api/v1/queue/', () => HttpResponse.json([])),
        http.get('/api/v1/inventory/assignments', () => HttpResponse.json([
          {
            id: 501,
            spool_id: 301,
            printer_id: 1,
            printer_name: 'PRA-01',
            ams_id: 0,
            tray_id: 0,
            fingerprint_color: null,
            fingerprint_type: null,
            configured: true,
            created_at: '2024-01-01T00:00:00Z',
            ams_label: 'CFS',
            spool: { id: 301, material: 'PLA', color_name: 'Blue', label_weight: 1000, weight_used: 84, archived_at: null },
          },
        ])),
        http.get('/api/v1/library/files/:id', () => HttpResponse.json(makeFile({ id: 41, filename: 'gridfinity-bin-plate-02.gcode.3mf', file_type: '3mf' }))),
        http.get('/api/v1/library/files/:id/plates', () => HttpResponse.json({ is_multi_plate: false, plates: [] })),
        http.get('/api/v1/library/files/:id/filament-requirements', () => HttpResponse.json({ file_id: 41, filename: 'gridfinity-bin-plate-02.gcode.3mf', filaments: [{ slot_id: 1, type: 'PLA', color: '#0000ff', used_grams: 84, used_meters: 28 }] })),
      );

      render(<ProjectDetailPage />);

      const dispatchHeading = await screen.findByRole('heading', { name: 'Dispatch Suggestions' });
      const dispatchSection = dispatchHeading.closest('.rounded-lg, .card, div')?.parentElement?.parentElement?.parentElement || document.body;
      expect(within(dispatchSection).getByText('gridfinity-bin-plate-02.gcode.3mf')).toBeInTheDocument();
      await waitFor(() => expect(within(dispatchSection).getByText('Ready to stage')).toBeInTheDocument());
      expect(within(dispatchSection).getByText('Suggested printer: PRA-01')).toBeInTheDocument();
      expect(within(dispatchSection).getByText(/PLA ready in CFS T1/)).toBeInTheDocument();
      expect(within(dispatchSection).getByText(/916g remaining/)).toBeInTheDocument();

      await user.click(screen.getByRole('button', { name: /review staging for gridfinity-bin-plate-02\.gcode\.3mf on PRA-01/i }));

      expect(await screen.findByRole('heading', { name: 'Print' })).toBeInTheDocument();
    });
  });
  describe('per-file print progress (#1897)', () => {
    it('shows X / N badges and the Complete Sets bar when target_sets is set', async () => {
      server.use(
        http.get('/api/v1/projects/:id', () => {
          return HttpResponse.json({ ...mockProject, target_sets: 10 });
        }),
        http.get('/api/v1/library/files', () => {
          return HttpResponse.json([
            makeFile({ id: 5, filename: 'plate_1.gcode.3mf', file_type: '3mf' }),
            makeFile({ id: 6, filename: 'plate_2.gcode.3mf', file_type: '3mf' }),
          ]);
        }),
        http.get('/api/v1/projects/:id/file-progress', () => {
          return HttpResponse.json([{ file_id: 5, completed_count: 3 }]);
        }),
      );

      render(<ProjectDetailPage />);

      // Per-file badges: 3 / 10 for plate_1, 0 / 10 for the never-printed plate_2
      await waitFor(() => {
        expect(screen.getByTitle('3 of 10 completed prints')).toBeInTheDocument();
      });
      expect(screen.getByTitle('0 of 10 completed prints')).toBeInTheDocument();

      // Complete sets = min across printable files = 0
      expect(screen.getByText('Complete Sets')).toBeInTheDocument();
      expect(
        screen.getByText((_, element) => element?.tagName === 'SPAN' && element.textContent === '0 / 10 sets')
      ).toBeInTheDocument();
    });

    it('counts a complete set once every printable file reached the target', async () => {
      server.use(
        http.get('/api/v1/projects/:id', () => {
          return HttpResponse.json({ ...mockProject, target_sets: 2 });
        }),
        http.get('/api/v1/library/files', () => {
          return HttpResponse.json([
            makeFile({ id: 5, filename: 'plate_1.gcode.3mf', file_type: '3mf' }),
            // STL is not printable and must not drag the set count to 0
            makeFile({ id: 8, filename: 'source.stl', file_type: 'stl' }),
            makeFile({ id: 6, filename: 'plate_2.gcode.3mf', file_type: '3mf' }),
          ]);
        }),
        http.get('/api/v1/projects/:id/file-progress', () => {
          // plate_1 overshot the target; capped at 2 for the set count
          return HttpResponse.json([
            { file_id: 5, completed_count: 3 },
            { file_id: 6, completed_count: 2 },
          ]);
        }),
      );

      render(<ProjectDetailPage />);

      await waitFor(() => {
        expect(
          screen.getByText((_, element) => element?.tagName === 'SPAN' && element.textContent === '2 / 2 sets')
        ).toBeInTheDocument();
      });
    });

    it('shows a plain printed-count badge when no target_sets is set', async () => {
      server.use(
        http.get('/api/v1/library/files', () => {
          return HttpResponse.json([makeFile({ id: 5, filename: 'plate_1.gcode.3mf', file_type: '3mf' })]);
        }),
        http.get('/api/v1/projects/:id/file-progress', () => {
          return HttpResponse.json([{ file_id: 5, completed_count: 4 }]);
        }),
      );

      render(<ProjectDetailPage />);

      await waitFor(() => {
        expect(screen.getByText('4\u00d7')).toBeInTheDocument();
      });
      // No sets bar without a target
      expect(screen.queryByText('Complete Sets')).not.toBeInTheDocument();
    });
  });
  describe('sub-project roll-up (#1264)', () => {
    const withChildren = {
      ...mockProject,
      // Supplying `stats` opens the cost card, which reads `budget` — the API
      // always sends the key, so the mock has to as well.
      budget: null,
      descendant_count: 2,
      children: [
        {
          id: 2,
          name: 'Wing',
          color: '#ff0000',
          status: 'active',
          progress_percent: 50,
          descendant_count: 1,
          total_archives: 4,
          completed_prints: 4,
          total_print_time_hours: 6,
          total_filament_grams: 250,
          total_cost: 12.5,
        },
      ],
      stats: {
        total_archives: 1,
        total_items: 1,
        completed_prints: 1,
        failed_prints: 0,
        queued_prints: 0,
        in_progress_prints: 0,
        total_print_time_hours: 2,
        total_filament_grams: 100,
        progress_percent: null,
        parts_progress_percent: null,
        estimated_cost: 5,
        total_energy_kwh: 0,
        total_energy_cost: 0,
        remaining_prints: null,
        remaining_parts: null,
        bom_total_items: 0,
        bom_completed_items: 0,
        bom_cost: 0,
      },
      rollup_stats: {
        total_archives: 5,
        total_items: 5,
        completed_prints: 5,
        failed_prints: 0,
        queued_prints: 0,
        in_progress_prints: 0,
        total_print_time_hours: 8,
        total_filament_grams: 350,
        progress_percent: 40,
        parts_progress_percent: null,
        estimated_cost: 17.5,
        total_energy_kwh: 0,
        total_energy_cost: 0,
        remaining_prints: 3,
        remaining_parts: null,
        bom_total_items: 0,
        bom_completed_items: 0,
        bom_cost: 0,
      },
    };

    it('shows the whole programme alongside the project own numbers', async () => {
      server.use(http.get('/api/v1/projects/:id', () => HttpResponse.json(withChildren)));

      render(<ProjectDetailPage />);

      await waitFor(() => {
        expect(screen.getByText('Including 2 sub-projects')).toBeInTheDocument();
      });
      // Both sets are on screen at once, which is the point — the roll-up must
      // not quietly replace what the project itself printed.
      expect(screen.getByText('350g')).toBeInTheDocument();
      expect(screen.getByText('100g')).toBeInTheDocument();
    });

    it('stays quiet when the project has no sub-projects', async () => {
      // Reversion-proof: if the roll-up were computed unconditionally it would
      // print a second, identical set of figures under every ordinary project.
      server.use(
        http.get('/api/v1/projects/:id', () =>
          HttpResponse.json({ ...withChildren, children: [], descendant_count: 0, rollup_stats: null })
        )
      );

      render(<ProjectDetailPage />);

      await waitFor(() => {
        expect(screen.getByText('100g')).toBeInTheDocument();
      });
      expect(screen.queryByText(/Including .* sub-projects/)).not.toBeInTheDocument();
    });

    it('gives each listed sub-project its own branch total', async () => {
      server.use(http.get('/api/v1/projects/:id', () => HttpResponse.json(withChildren)));

      render(<ProjectDetailPage />);

      await waitFor(() => {
        expect(screen.getByText('Wing')).toBeInTheDocument();
      });
      expect(screen.getByText('4 jobs')).toBeInTheDocument();
      expect(screen.getByText('250g')).toBeInTheDocument();
      expect(screen.getByText('50%')).toBeInTheDocument();
    });

    it('marks a sub-project that is itself a parent', async () => {
      // Otherwise its figures look inflated for a single project rather than
      // covering the branch under it.
      server.use(http.get('/api/v1/projects/:id', () => HttpResponse.json(withChildren)));

      render(<ProjectDetailPage />);

      await waitFor(() => {
        expect(screen.getByText('Wing')).toBeInTheDocument();
      });
      const row = screen.getByText('Wing').closest('a');
      expect(row).not.toBeNull();
      expect(row!.textContent).toContain('1');
    });
  });
});
