import { describe, it, expect, vi, beforeEach } from 'vitest';
import { screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { render } from '../utils';
import { QueueProjectModal } from '../../components/QueueProjectModal';

vi.mock('../../api/client', () => ({
  api: {
    getSettings: vi.fn().mockResolvedValue({}),
    getProjects: vi.fn().mockResolvedValue([
      { id: 1, name: 'Desk set', color: '#ff0000' },
      { id: 2, name: 'Arcade cabinet', color: null },
    ]),
    linkQueueItemsToProject: vi.fn().mockResolvedValue({
      updated_count: 2,
      skipped_count: 0,
      plan_items_created: 1,
      plan_items_linked: 0,
      library_files_created: 1,
      message: 'ok',
    }),
  },
}));

import { api } from '../../api/client';

describe('QueueProjectModal', () => {
  beforeEach(() => vi.clearAllMocks());

  it('links the items to the chosen project', async () => {
    const user = userEvent.setup();
    const onClose = vi.fn();
    render(<QueueProjectModal itemIds={[4, 5]} onClose={onClose} />);

    await user.click(await screen.findByText('Desk set'));

    await waitFor(() => {
      expect(api.linkQueueItemsToProject).toHaveBeenCalledWith({ item_ids: [4, 5], project_id: 1, add_to_plan: false });
    });
    await waitFor(() => expect(onClose).toHaveBeenCalled());
  });

  it('sends add_to_plan when the checkbox is ticked', async () => {
    const user = userEvent.setup();
    render(<QueueProjectModal itemIds={[4]} onClose={vi.fn()} />);

    await user.click(screen.getByRole('checkbox'));
    await user.click(await screen.findByText('Arcade cabinet'));

    await waitFor(() => {
      expect(api.linkQueueItemsToProject).toHaveBeenCalledWith({ item_ids: [4], project_id: 2, add_to_plan: true });
    });
  });

  it('offers unlinking only when the items are linked', async () => {
    const user = userEvent.setup();
    const { unmount } = render(<QueueProjectModal itemIds={[4]} onClose={vi.fn()} />);
    await screen.findByText('Desk set');
    expect(screen.queryByText('Remove from project')).not.toBeInTheDocument();
    unmount();

    render(<QueueProjectModal itemIds={[4]} currentProjectId={1} onClose={vi.fn()} />);
    await user.click(await screen.findByText('Remove from project'));
    await waitFor(() => {
      expect(api.linkQueueItemsToProject).toHaveBeenCalledWith({ item_ids: [4], project_id: null, add_to_plan: false });
    });
  });
});
