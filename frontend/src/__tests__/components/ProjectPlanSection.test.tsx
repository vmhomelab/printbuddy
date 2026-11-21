/// <reference types="@testing-library/jest-dom" />

import { describe, it, expect, beforeEach } from 'vitest';
import { screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { http, HttpResponse } from 'msw';
import { render } from '../utils';
import { server } from '../mocks/server';
import { ProjectPlanSection } from '../../components/ProjectPlanSection';
import type { PlanItem, PlanSummary, Printer } from '../../api/client';

const printers = [
  { id: 1, name: 'PRA-01', model: 'P1S' },
  { id: 2, name: 'PRA-02', model: 'X1C' },
] as unknown as Printer[];

function makeItem(overrides: Partial<PlanItem> = {}): PlanItem {
  return {
    id: 1,
    project_id: 1,
    library_file_id: 10,
    library_file_name: 'base.gcode.3mf',
    library_file_missing: false,
    is_sliced: true,
    thumbnail_url: null,
    plate_id: 1,
    name: 'Base – Plate 1',
    group_label: 'Base set',
    quantity: 2,
    filaments: [
      { slot_id: 1, type: 'PETG', color: '#FF0000', color_name: 'Red', used_grams: 20, original_type: 'PLA', original_color: '#FFFFFF' },
    ],
    est_print_time_seconds: 3600,
    est_filament_grams: 20,
    printer_id: 1,
    printer_name: 'PRA-01',
    target_model: null,
    notes: null,
    sort_order: 1,
    progress: { completed: 1, printing: 0, queued: 0, failed: 0, remaining: 1, percent: 50 },
    created_at: '2026-01-01T00:00:00Z',
    updated_at: '2026-01-01T00:00:00Z',
    ...overrides,
  };
}

const summary: PlanSummary = {
  total_plates: 3,
  completed_plates: 1,
  printing_plates: 0,
  queued_plates: 0,
  failed_plates: 0,
  remaining_plates: 2,
  progress_percent: 33.3,
  planned_print_time_seconds: 3 * 3600,
  remaining_print_time_seconds: 2 * 3600,
  planned_filament_grams: 60,
  remaining_filament_grams: 40,
  unestimated_items: 1,
  materials: [
    { type: 'PETG', color: '#FF0000', color_name: 'Red', planned_grams: 40, completed_grams: 20, remaining_grams: 20 },
    { type: 'PLA', color: '#000000', color_name: null, planned_grams: 20, completed_grams: 0, remaining_grams: 20 },
  ],
};

describe('ProjectPlanSection', () => {
  let enqueueBody: unknown;
  let patchBody: unknown;

  beforeEach(() => {
    enqueueBody = undefined;
    patchBody = undefined;
    server.use(
      http.get('/api/v1/projects/:id/plan', () =>
        HttpResponse.json([
          makeItem(),
          makeItem({
            id: 2,
            name: 'Accessory hook',
            group_label: 'Accessory A',
            quantity: 1,
            is_sliced: false,
            library_file_name: 'hook.stl',
            filaments: [],
            est_print_time_seconds: null,
            est_filament_grams: null,
            printer_id: null,
            printer_name: null,
            progress: { completed: 0, printing: 0, queued: 0, failed: 0, remaining: 1, percent: 0 },
          }),
        ]),
      ),
      http.get('/api/v1/projects/:id/plan/summary', () => HttpResponse.json(summary)),
      http.get('/api/v1/inventory/spools', () =>
        HttpResponse.json([
          { id: 5, material: 'PETG', color_name: 'Red', rgba: 'FF0000FF', brand: 'Acme', label_weight: 1000, weight_used: 990 },
        ]),
      ),
      http.post('/api/v1/projects/:id/plan/enqueue', async ({ request }) => {
        enqueueBody = await request.json();
        return HttpResponse.json({ queued_total: 1, results: [{ plan_item_id: 1, queued: 1, error: null }] });
      }),
      http.patch('/api/v1/projects/:id/plan/:itemId', async ({ request }) => {
        patchBody = await request.json();
        return HttpResponse.json(makeItem());
      }),
    );
  });

  const renderSection = () =>
    render(<ProjectPlanSection projectId={1} projectFiles={[]} printers={printers} canEdit canQueue />);

  it('renders groups, overridden materials, progress and the material totals', async () => {
    renderSection();

    expect(await screen.findByText('Base – Plate 1')).toBeInTheDocument();
    expect(screen.getByText('Base set', { exact: false })).toBeInTheDocument();
    expect(screen.getByText('Accessory A', { exact: false })).toBeInTheDocument();
    // Unsliced file is flagged
    expect(screen.getByText(/file is not sliced/i)).toBeInTheDocument();
    // Running totals + per-material breakdown
    expect(await screen.findByText('1/3 · 33%')).toBeInTheDocument();
    expect(screen.getByText('3h')).toBeInTheDocument();
    expect(screen.getByText('60 g')).toBeInTheDocument();
    // Inventory has only 10 g red PETG (and no black PLA) for 20 g remaining each → both flagged
    expect(screen.getAllByTitle(/not enough filament/i)).toHaveLength(2);
    expect(screen.getByText(/1 plate\(s\) without estimate/i)).toBeInTheDocument();
  });

  it('queues all open copies with one click', async () => {
    const user = userEvent.setup();
    renderSection();

    const button = await screen.findByRole('button', { name: /queue all open \(2\)/i });
    await user.click(button);

    await waitFor(() => expect(enqueueBody).toEqual({ item_ids: null, manual_start: false }));
  });

  it('can stage items instead of printing automatically', async () => {
    const user = userEvent.setup();
    renderSection();

    await user.click(await screen.findByLabelText(/stage only/i));
    await user.click(screen.getByRole('button', { name: /queue all open/i }));

    await waitFor(() => expect(enqueueBody).toEqual({ item_ids: null, manual_start: true }));
  });

  it('switches a row to a printer model', async () => {
    const user = userEvent.setup();
    renderSection();

    await screen.findByText('Base – Plate 1');
    const row = screen.getByText('Base – Plate 1').closest('tr')!;
    await user.selectOptions(within(row).getByLabelText('Printer'), 'm:X1C');

    await waitFor(() => expect(patchBody).toEqual({ printer_id: null, target_model: 'X1C' }));
  });

  it('lists project files first and other library files only on request', async () => {
    const file = (id: number, filename: string) => ({
      id, folder_id: id, is_external: false, filename, file_type: '3mf', file_size: 1, thumbnail_path: null,
      print_count: 0, duplicate_count: 0, created_at: '2026-01-01T00:00:00Z', print_time_seconds: 600,
      filament_used_grams: 5, filament_type: 'PLA', sliced_for_model: 'P1S', print_name: null,
    });
    const projectFile = file(10, 'base.gcode.3mf');
    server.use(
      http.get('/api/v1/library/files', () =>
        HttpResponse.json([projectFile, file(11, 'unrelated.gcode.3mf')]),
      ),
    );
    const user = userEvent.setup();
    render(
      <ProjectPlanSection
        projectId={1}
        projectFiles={[projectFile] as never}
        printers={printers}
        canEdit
        canQueue
      />,
    );

    await user.click((await screen.findAllByRole('button', { name: 'Add plates' }))[0]);
    const dialog = screen.getByRole('dialog', { name: 'Add plates' });
    expect(within(dialog).getByText('base')).toBeInTheDocument();
    expect(within(dialog).queryByText('unrelated')).not.toBeInTheDocument();

    await user.click(within(dialog).getByRole('button', { name: /other files \(not in project\)/i }));
    expect(await within(dialog).findByText('unrelated')).toBeInTheDocument();
    // project files are not repeated in the "other" list
    expect(within(dialog).queryByText('base')).not.toBeInTheDocument();
  });
});
