/// <reference types="@testing-library/jest-dom" />

import { describe, it, expect, beforeEach } from 'vitest';
import { screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { http, HttpResponse } from 'msw';
import { render } from '../utils';
import { server } from '../mocks/server';
import { ProjectCostsCard } from '../../components/ProjectCostsCard';
import type { ProjectCosts } from '../../api/client';

const costs: ProjectCosts = {
  currency: 'EUR',
  has_plan: true,
  energy_cost_per_kwh: 0.4,
  waste_percent: 20,
  budget: 10,
  total_plates: 3,
  completed_plates: 0,
  planned: { material: 3.06, energy: 0.26, bom: 1, total: 4.32 },
  incurred: { material: 0, energy: 0, bom: 0.4, total: 0.4 },
  remaining: { material: 3.06, energy: 0.26, bom: 0.6, total: 3.92 },
  material: {
    planned_grams: 110,
    planned_cost: 2.55,
    waste_cost: 0.51,
    total_cost: 3.06,
    rows: [
      {
        type: 'PLA', color: '#FFFFFF', color_name: 'White', planned_grams: 40, completed_grams: 0, remaining_grams: 40,
        price_per_kg: 22, source: 'spools',
        spools: [
          { id: 1, brand: 'Bambu', color_name: 'White', cost_per_kg: 20, remaining_grams: 800 },
          { id: 2, brand: 'eSun', color_name: 'White', cost_per_kg: 30, remaining_grams: 200 },
        ],
        planned_cost: 0.88, completed_cost: 0, remaining_cost: 0.88,
      },
      {
        type: 'PETG', color: '#FF0000', color_name: null, planned_grams: 50, completed_grams: 0, remaining_grams: 50,
        price_per_kg: 25, source: 'default', spools: [], planned_cost: 1.25, completed_cost: 0, remaining_cost: 1.25,
      },
    ],
  },
  energy: {
    planned_kwh: 0.65,
    planned_cost: 0.26,
    rows: [
      {
        key: 'p:1', kind: 'printer', label: 'P1S-01', plates: 2, planned_hours: 2, remaining_hours: 2,
        kwh_per_hour: 0.2, source: 'power_setting', source_detail: '200 W', history_prints: 0,
        planned_kwh: 0.4, planned_cost: 0.16, remaining_cost: 0.16,
      },
    ],
  },
  bom: {
    total: 1,
    acquired: 0.4,
    rows: [{ id: 1, name: 'Magnets', quantity_needed: 10, quantity_acquired: 4, unit_price: 0.1, cost: 1 }],
  },
  actual: { material: 0, energy: 0, energy_kwh: 0, prints: 0 },
  warnings: [{ code: 'default_price', type: 'PETG', color: '#FF0000', color_name: null }],
};

describe('ProjectCostsCard', () => {
  let patchBody: unknown;

  beforeEach(() => {
    patchBody = undefined;
    server.use(
      http.get('/api/v1/projects/:id/costs', () => HttpResponse.json(costs)),
      http.patch('/api/v1/projects/:id', async ({ request }) => {
        patchBody = await request.json();
        return HttpResponse.json({});
      }),
    );
  });

  it('shows the total, its composition and the price source of each row', async () => {
    render(<ProjectCostsCard projectId={1} canEdit />);

    expect(await screen.findByText('Production costs')).toBeInTheDocument();
    expect(screen.getByText(/4[.,]32/, { selector: 'p' })).toBeInTheDocument();
    // Shares: material 71 %, energy 6 %, BOM 23 %
    expect(screen.getByText('71 %')).toBeInTheDocument();
    expect(screen.getByText('6 %')).toBeInTheDocument();
    expect(screen.getByText('23 %')).toBeInTheDocument();
    expect(screen.getByText('incl. 20 % waste')).toBeInTheDocument();

    expect(screen.getByText('Avg. of 2 spools')).toBeInTheDocument();
    expect(screen.getByText('Default price (settings)')).toBeInTheDocument();
    expect(screen.getByText('Configured power · 200 W')).toBeInTheDocument();
    expect(screen.getByText('4 / 10 acquired')).toBeInTheDocument();
    expect(screen.getByText(/no spool or catalogue price/i)).toBeInTheDocument();
  });

  it('switches between planned, spent and remaining totals', async () => {
    const user = userEvent.setup();
    render(<ProjectCostsCard projectId={1} canEdit />);

    await user.click(await screen.findByRole('tab', { name: 'Already spent' }));
    expect(screen.getByText('Spent so far (actual)')).toBeInTheDocument();
    expect(screen.getByText('100 %')).toBeInTheDocument(); // only BOM so far

    await user.click(screen.getByRole('tab', { name: 'Still to come' }));
    expect(screen.getByText('Still to come (estimate)')).toBeInTheDocument();
  });

  it('saves the waste surcharge', async () => {
    const user = userEvent.setup();
    render(<ProjectCostsCard projectId={1} canEdit />);

    const input = await screen.findByLabelText('Waste / purge surcharge');
    await user.clear(input);
    await user.type(input, '5');
    await user.tab();

    await waitFor(() => expect(patchBody).toEqual({ waste_percent: 5 }));
  });

  it('renders nothing for an empty project', async () => {
    server.use(
      http.get('/api/v1/projects/:id/costs', () =>
        HttpResponse.json({
          ...costs,
          has_plan: false,
          budget: null,
          planned: { material: 0, energy: 0, bom: 0, total: 0 },
          incurred: { material: 0, energy: 0, bom: 0, total: 0 },
        }),
      ),
    );
    const { container } = render(<ProjectCostsCard projectId={1} canEdit />);
    await waitFor(() => expect(within(container).queryByText('Production costs')).not.toBeInTheDocument());
  });
});
