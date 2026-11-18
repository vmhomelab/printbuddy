/**
 * Tests for user-reported failure reasons: the "Report failed print" dialog
 * (reason tiles and the cog settings) and the "Fail reason statistics" widget.
 */

import { describe, it, expect, afterEach, vi } from 'vitest';
import { screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { http, HttpResponse } from 'msw';
import { render } from '../utils';
import { server } from '../mocks/server';
import { ReportFailureModal } from '../../components/ReportFailureModal';
import { FailReasonStatisticsWidget } from '../../components/FailReasonStatisticsWidget';
import type { CustomFailureReason, CustomFailureReport } from '../../api/client';
import { reasonGridColumns } from '../../utils/customFailure';

const API = '/api/v1/custom-failure-reports';

afterEach(() => {
  server.resetHandlers();
  vi.restoreAllMocks();
});

function buildReasons(overrides: Record<string, Partial<CustomFailureReason>> = {}): CustomFailureReason[] {
  return Array.from({ length: 10 }, (_, i) => {
    const code = `fail_reason_${String(i + 1).padStart(2, '0')}`;
    return {
      id: i + 1,
      code,
      title: null,
      subtitle: null,
      icon: 'Wrench',
      custom_icon_filename: null,
      is_system: true,
      is_hidden: false,
      sort_order: i + 1,
      ...overrides[code],
    };
  });
}

function useReasons(reasons: CustomFailureReason[] = buildReasons()) {
  server.use(http.get(`${API}/reasons/`, () => HttpResponse.json(reasons)));
}

function buildReport(id: number, overrides: Partial<CustomFailureReport> = {}): CustomFailureReport {
  return {
    id,
    custom_failure_reason: 'fail_reason_08',
    comment: null,
    reported_by: null,
    reported_at: '2026-11-02T13:50:00',
    printer_id: 1,
    printer_name: 'X2D',
    archive_id: null,
    print_name: `Part ${id}`,
    filename: `part_${id}.gcode`,
    print_status: 'failed',
    print_started_at: '2026-11-02T13:41:00',
    print_date: '2026-11-02T13:41:00',
    materials: [{ type: 'PLA', color: '#FFFFFF', grams: 4.28 }],
    filament_used_grams: 4.28,
    print_time_seconds: 1824,
    has_thumbnail: false,
    ...overrides,
  };
}

function useTarget(existing: CustomFailureReport | null = null, reasons = buildReasons()) {
  useReasons(reasons);
  server.use(
    http.get(`${API}/printers/1/target`, () =>
      HttpResponse.json({
        printer_id: 1,
        printer_name: 'X2D',
        is_current_print: false,
        archive_id: 42,
        print_name: 'Halterung_Testteil',
        filename: 'Halterung_Testteil_0.2mm_PLA_30m24s.gcode',
        print_status: 'failed',
        print_started_at: '2026-11-02T13:41:00',
        has_thumbnail: false,
        existing_report: existing,
      })
    )
  );
}

function renderModal(onClose: () => void = () => {}) {
  return render(<ReportFailureModal printer={{ id: 1, name: 'X2D' }} onClose={onClose} />);
}

describe('ReportFailureModal', () => {
  it('shows which print is flagged and leaves the name empty by default', async () => {
    useTarget();
    renderModal();

    expect(await screen.findByText('Halterung_Testteil')).toBeInTheDocument();
    expect(screen.getByLabelText('Your name (optional)')).toHaveValue('');
    expect(screen.getByRole('button', { name: 'Report' })).toBeDisabled();
  });

  it('submits the chosen tile with comment and an empty name', async () => {
    useTarget();
    let body: Record<string, unknown> | null = null;
    server.use(
      http.post(`${API}/`, async ({ request }) => {
        body = (await request.json()) as Record<string, unknown>;
        return HttpResponse.json(buildReport(1));
      })
    );
    const onClose = vi.fn();
    const user = userEvent.setup();
    renderModal(onClose);

    await screen.findByText('Halterung_Testteil');
    await user.click(await screen.findByRole('radio', { name: /Tangled filament/ }));
    expect(screen.getByRole('radio', { name: /Tangled filament/ })).toHaveAttribute('aria-checked', 'true');
    await user.type(screen.getByLabelText('Comment (optional)'), 'Spaghetti');
    await user.click(screen.getByRole('button', { name: 'Report' }));

    await waitFor(() => expect(onClose).toHaveBeenCalled());
    expect(body).toMatchObject({
      printer_id: 1,
      archive_id: 42,
      custom_failure_reason: 'fail_reason_08',
      comment: 'Spaghetti',
      reported_by: '',
    });
  });

  it('prefills an existing report and offers to withdraw it', async () => {
    useTarget(buildReport(7, { custom_failure_reason: 'fail_reason_03', comment: 'Warping' }));
    renderModal();

    expect(await screen.findByRole('button', { name: 'Withdraw report' })).toBeInTheDocument();
    await waitFor(() =>
      expect(screen.getByRole('radio', { name: /Layer shift/ })).toHaveAttribute('aria-checked', 'true')
    );
    expect(screen.getByLabelText('Comment (optional)')).toHaveValue('Warping');
    expect(screen.getByRole('button', { name: 'Update report' })).toBeEnabled();
  });

  it('shows one tile per visible reason, own text before the default text', async () => {
    useTarget(
      null,
      buildReasons({
        fail_reason_02: { is_hidden: true },
        fail_reason_06: { title: 'Drucker kaputt', subtitle: 'Lüfter, Sensor' },
      })
    );
    renderModal();

    await screen.findByText('Halterung_Testteil');
    expect(await screen.findAllByRole('radio')).toHaveLength(9);
    expect(screen.queryByRole('radio', { name: /Warping/ })).not.toBeInTheDocument();
    expect(screen.getByRole('radio', { name: /Drucker kaputt/ })).toHaveTextContent('Lüfter, Sensor');
    expect(screen.getByRole('radio', { name: /Clogged nozzle/ })).toHaveTextContent('No material coming out');
  });

  it('keeps a hidden reason selectable for the report that already uses it', async () => {
    useTarget(
      buildReport(7, { custom_failure_reason: 'fail_reason_02' }),
      buildReasons({ fail_reason_02: { is_hidden: true } })
    );
    renderModal();

    await waitFor(() => expect(screen.getByRole('radio', { name: /Warping/ })).toHaveAttribute('aria-checked', 'true'));
    expect(screen.getAllByRole('radio')).toHaveLength(10);
  });
});

describe('reason settings (cog)', () => {
  it('adds a custom reason with title, subtitle and icon', async () => {
    useTarget();
    let created: Record<string, unknown> | null = null;
    server.use(
      http.post(`${API}/reasons/`, async ({ request }) => {
        created = (await request.json()) as Record<string, unknown>;
        return HttpResponse.json({ ...buildReasons()[0], id: 11, code: 'custom_abc', is_system: false, ...created });
      })
    );
    const user = userEvent.setup();
    renderModal();

    await user.click(await screen.findByRole('button', { name: 'Edit failure reasons' }));
    expect(screen.getByText('10 of 100 reasons')).toBeInTheDocument();
    await user.click(screen.getByRole('button', { name: 'New reason' }));
    await user.type(screen.getByLabelText('Title'), 'Head crash');
    await user.type(screen.getByLabelText('Subtitle (optional)'), 'Collision, nozzle torn off');
    await user.click(screen.getByRole('button', { name: 'Zap' }));
    await user.click(screen.getByRole('button', { name: 'Save' }));

    await waitFor(() =>
      expect(created).toEqual({ title: 'Head crash', subtitle: 'Collision, nozzle torn off', icon: 'Zap' })
    );
  });

  it('uploads an own image as icon when saving', async () => {
    useTarget();
    let uploaded = false;
    server.use(
      http.patch(`${API}/reasons/1`, () => HttpResponse.json(buildReasons()[0])),
      http.post(`${API}/reasons/1/icon`, () => {
        uploaded = true;
        return HttpResponse.json({ ...buildReasons()[0], custom_icon_filename: 'reason_1_x.png' });
      })
    );
    const user = userEvent.setup();
    renderModal();

    await user.click(await screen.findByRole('button', { name: 'Edit failure reasons' }));
    await user.click(screen.getAllByRole('button', { name: 'Edit' })[0]);
    await user.upload(screen.getByTestId('reason-icon-upload'), new File(['png'], 'icon.png', { type: 'image/png' }));
    expect(screen.getByText(/Uploaded when you save/)).toBeInTheDocument();
    await user.click(screen.getByRole('button', { name: 'Save' }));

    await waitFor(() => expect(uploaded).toBe(true));
  });

  it('hides a default reason and offers hidden ones back', async () => {
    useTarget(null, buildReasons({ fail_reason_10: { is_hidden: true } }));
    let removed = '';
    server.use(
      http.delete(`${API}/reasons/:id`, ({ params }) => {
        removed = String(params.id);
        return HttpResponse.json({ status: 'hidden' });
      })
    );
    const user = userEvent.setup();
    renderModal();

    await user.click(await screen.findByRole('button', { name: 'Edit failure reasons' }));
    expect(screen.getByText('Hidden reasons')).toBeInTheDocument();
    expect(screen.getByRole('button', { name: /Show again/ })).toBeInTheDocument();
    expect(screen.getByRole('button', { name: /Restore default reasons/ })).toBeInTheDocument();
    await user.click(screen.getAllByRole('button', { name: 'Hide' })[0]);
    await waitFor(() => expect(removed).toBe('1'));
  });
});

describe('reasonGridColumns', () => {
  it('arranges tiles as square as possible, limited by the screen width', () => {
    expect(reasonGridColumns(10, 2000)).toBe(4);
    expect(reasonGridColumns(16, 2000)).toBe(4);
    expect(reasonGridColumns(17, 2000)).toBe(5);
    expect(reasonGridColumns(30, 2000)).toBe(6);
    expect(reasonGridColumns(10, 320)).toBe(2);
    expect(reasonGridColumns(1, 2000)).toBe(1);
  });
});

describe('FailReasonStatisticsWidget', () => {
  it('lists reasons collapsed, expands to the latest prints and shows all on demand', async () => {
    useReasons();
    const latest = Array.from({ length: 15 }, (_, i) => buildReport(17 - i, { print_name: `Part ${17 - i}` }));
    const all = Array.from({ length: 17 }, (_, i) => buildReport(17 - i, { print_name: `Part ${17 - i}` }));
    server.use(
      http.get(`${API}/stats`, () =>
        HttpResponse.json({
          total: 20,
          latest_limit: 15,
          reasons: [
            { reason: 'fail_reason_08', count: 17, percent: 85, latest },
            { reason: 'fail_reason_02', count: 3, percent: 15, latest: [] },
            { reason: 'fail_reason_05', count: 0, percent: 0, latest: [] },
          ],
        })
      ),
      http.get(`${API}/`, ({ request }) => {
        expect(new URL(request.url).searchParams.get('reason')).toBe('fail_reason_08');
        return HttpResponse.json(all);
      })
    );
    const user = userEvent.setup();
    render(<FailReasonStatisticsWidget />);

    expect(await screen.findByText('Tangled filament')).toBeInTheDocument();
    expect(screen.getByText('85.0')).toBeInTheDocument();
    expect(screen.queryByText('Part 17')).not.toBeInTheDocument(); // collapsed by default

    await user.click(screen.getByText('Tangled filament'));
    expect(screen.getByText('Part 17')).toBeInTheDocument();
    expect(screen.queryByText('Part 2')).not.toBeInTheDocument(); // only the latest 15
    expect(screen.getAllByText('2026-11-02').length).toBe(15);

    await user.click(screen.getByRole('button', { name: 'Show all (17)' }));
    expect(await screen.findByText('Part 1')).toBeInTheDocument();
    expect(screen.queryByRole('button', { name: 'Show all (17)' })).not.toBeInTheDocument();
  });

  it('shows a renamed reason with its own title', async () => {
    useReasons(buildReasons({ fail_reason_08: { title: 'Filamentsalat' } }));
    server.use(
      http.get(`${API}/stats`, () =>
        HttpResponse.json({
          total: 1,
          latest_limit: 15,
          reasons: [{ reason: 'fail_reason_08', count: 1, percent: 100, latest: [buildReport(1)] }],
        })
      )
    );
    render(<FailReasonStatisticsWidget />);
    expect(await screen.findByText('Filamentsalat')).toBeInTheDocument();
  });

  it('says so when nothing has been reported', async () => {
    useReasons();
    server.use(http.get(`${API}/stats`, () => HttpResponse.json({ total: 0, latest_limit: 15, reasons: [] })));
    render(<FailReasonStatisticsWidget dateFrom="2026-10-01" dateTo="2026-10-31" />);
    expect(await screen.findByText('No failed prints have been reported in this period.')).toBeInTheDocument();
  });
});
