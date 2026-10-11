import { describe, expect, it, vi } from 'vitest';
import { render, screen } from '@testing-library/react';

vi.mock('next/navigation', () => ({ useRouter: () => ({ push: vi.fn() }) }));

import { FavoritesEmptyState } from './FavoritesEmptyState';

describe('FavoritesEmptyState', () => {
  it('links the import shortcut straight to the Import tab of the Resources page', () => {
    render(<FavoritesEmptyState t={(key: string) => key} />);
    expect(screen.getByRole('link', { name: 'favorites.importLink' })).toHaveAttribute('href', '/resources?tab=import');
  });
});
