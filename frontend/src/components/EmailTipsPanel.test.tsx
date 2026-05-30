import { describe, it, expect } from 'vitest';
import { render, screen } from '@testing-library/react';
import EmailTipsPanel from './EmailTipsPanel';

describe('EmailTipsPanel', () => {
  it('renders nothing when labType is null', () => {
    const { container } = render(<EmailTipsPanel labType={null} />);
    expect(container.firstChild).toBeNull();
  });

  it('renders Skills + Mistakes headings for dry lab', () => {
    render(<EmailTipsPanel labType="dry" />);
    expect(screen.getByText('Skills to highlight')).toBeInTheDocument();
    expect(screen.getByText('Avoid these mistakes')).toBeInTheDocument();
  });

  it('shows dry-lab-specific tips (GitHub link)', () => {
    render(<EmailTipsPanel labType="dry" />);
    expect(screen.getByText(/GitHub link/i)).toBeInTheDocument();
  });

  it('shows wet-lab-specific tips (PCR, cell culture)', () => {
    render(<EmailTipsPanel labType="wet" />);
    expect(screen.getByText(/PCR/)).toBeInTheDocument();
    expect(screen.getByText(/cell culture/)).toBeInTheDocument();
  });

  it('shows humanities-specific tips (IRB)', () => {
    render(<EmailTipsPanel labType="humanities" />);
    expect(screen.getByText(/IRB/)).toBeInTheDocument();
  });

  it('renders 4 skill bullets per lab type', () => {
    const { container } = render(<EmailTipsPanel labType="wet" />);
    const skillsSection = container.querySelector('section.bg-emerald-50\\/60');
    expect(skillsSection).not.toBeNull();
    const bullets = skillsSection?.querySelectorAll('li');
    expect(bullets?.length).toBe(4);
  });

  it('renders 3 mistake bullets per lab type', () => {
    const { container } = render(<EmailTipsPanel labType="dry" />);
    const mistakesSection = container.querySelector('section.bg-amber-50\\/60');
    expect(mistakesSection).not.toBeNull();
    const bullets = mistakesSection?.querySelectorAll('li');
    expect(bullets?.length).toBe(3);
  });

  it('renders a Read-more link that deep-links to /resources for wet', () => {
    render(<EmailTipsPanel labType="wet" />);
    const link = screen.getByTestId('tips-read-more');
    expect(link.getAttribute('href')).toBe('/resources?lab=wet#tips-card-wet');
  });

  it('renders a Read-more link that deep-links to /resources for dry', () => {
    render(<EmailTipsPanel labType="dry" />);
    const link = screen.getByTestId('tips-read-more');
    expect(link.getAttribute('href')).toBe('/resources?lab=dry#tips-card-dry');
  });

  it('renders a Read-more link that deep-links to /resources for humanities', () => {
    render(<EmailTipsPanel labType="humanities" />);
    const link = screen.getByTestId('tips-read-more');
    expect(link.getAttribute('href')).toBe('/resources?lab=humanities#tips-card-humanities');
  });

  it('does not render the read-more link when labType is null', () => {
    render(<EmailTipsPanel labType={null} />);
    expect(screen.queryByTestId('tips-read-more')).toBeNull();
  });
});
