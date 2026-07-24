/**
 * Tests for the ProjectDetailPage component.
 * Covers: isSlicedFilename conditional print-button logic, linked folder file rendering,
 * and the PrintModal open trigger with projectId.
 */

/// <reference types="@testing-library/jest-dom" />

import { describe, it, expect, beforeEach, vi } from 'vitest';
import { screen, waitFor } from '@testing-library/react';
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
    );
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
        expect(screen.getByTitle('Print Now')).toBeInTheDocument();
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
        expect(screen.getByTitle('Print Now')).toBeInTheDocument();
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

      expect(screen.queryByTitle('Print Now')).not.toBeInTheDocument();
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

      expect(screen.queryByTitle('Print Now')).not.toBeInTheDocument();
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
        expect(screen.getByTitle('Print Now')).toBeInTheDocument();
      });

      await user.click(screen.getByTitle('Print Now'));

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
        http.get('/api/v1/library/files/:id/filament-requirements', () => HttpResponse.json({ file_id: 41, filename: 'gridfinity-bin-plate-02.gcode.3mf', filaments: [] })),
      );

      render(<ProjectDetailPage />);

      expect(await screen.findByRole('heading', { name: 'Production Plan' })).toBeInTheDocument();
      await user.click(screen.getByRole('button', { name: /stage gridfinity-bin-plate-02\.gcode\.3mf to queue/i }));

      expect(await screen.findByRole('heading', { name: 'Schedule Print' })).toBeInTheDocument();
    });
  });
});
