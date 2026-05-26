import { describe, it, expect } from 'vitest';
import { render, screen } from '@testing-library/react';
import DatabaseLinkCard from './DatabaseLinkCard';
import { DATABASES } from './types';

describe('DatabaseLinkCard', () => {
  it('renders the database name from i18n', () => {
    const ie = DATABASES.find((d) => d.key === 'illinoisExperts')!;
    render(<DatabaseLinkCard link={ie} />);
    expect(screen.getByText('Illinois Experts')).toBeInTheDocument();
  });

  it('renders the short label badge', () => {
    const nih = DATABASES.find((d) => d.key === 'nihReporter')!;
    render(<DatabaseLinkCard link={nih} />);
    expect(screen.getByText('NIH')).toBeInTheDocument();
  });

  it('renders the visible domain', () => {
    const nsf = DATABASES.find((d) => d.key === 'nsfAwards')!;
    render(<DatabaseLinkCard link={nsf} />);
    expect(screen.getByText('nsf.gov')).toBeInTheDocument();
  });

  it('opens in a new tab with rel=noopener', () => {
    const gs = DATABASES.find((d) => d.key === 'googleScholar')!;
    render(<DatabaseLinkCard link={gs} />);
    const anchor = screen.getByRole('link');
    expect(anchor).toHaveAttribute('href', 'https://scholar.google.com/');
    expect(anchor).toHaveAttribute('target', '_blank');
    expect(anchor).toHaveAttribute('rel', 'noopener noreferrer');
  });

  it('renders the description text', () => {
    const ie = DATABASES.find((d) => d.key === 'illinoisExperts')!;
    render(<DatabaseLinkCard link={ie} />);
    expect(screen.getByText(/UIUC database of faculty profiles/i)).toBeInTheDocument();
  });

  it('covers all four DATABASES entries without throwing', () => {
    for (const link of DATABASES) {
      const { unmount } = render(<DatabaseLinkCard link={link} />);
      expect(screen.getByText(link.short)).toBeInTheDocument();
      unmount();
    }
  });
});
