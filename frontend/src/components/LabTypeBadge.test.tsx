import { describe, it, expect } from 'vitest';
import { render, screen } from '@testing-library/react';
import LabTypeBadge from './LabTypeBadge';

describe('LabTypeBadge', () => {
  it('renders nothing when labType is null', () => {
    const { container } = render(<LabTypeBadge labType={null} />);
    expect(container.firstChild).toBeNull();
  });

  it('renders nothing when labType is undefined', () => {
    const { container } = render(<LabTypeBadge labType={undefined} />);
    expect(container.firstChild).toBeNull();
  });

  it('renders the Wet Lab label with emerald styling', () => {
    render(<LabTypeBadge labType="wet" />);
    const el = screen.getByText('Wet Lab');
    expect(el).toBeInTheDocument();
    expect(el).toHaveClass('bg-emerald-50', 'text-emerald-700');
  });

  it('renders the Dry Lab label with blue styling', () => {
    render(<LabTypeBadge labType="dry" />);
    const el = screen.getByText('Dry Lab');
    expect(el).toBeInTheDocument();
    expect(el).toHaveClass('bg-indigo-50', 'text-indigo-700');
  });

  it('renders the Humanities label with amber styling', () => {
    render(<LabTypeBadge labType="humanities" />);
    const el = screen.getByText('Humanities');
    expect(el).toBeInTheDocument();
    expect(el).toHaveClass('bg-amber-50', 'text-amber-700');
  });

  it('renders an aria-hidden icon (decorative)', () => {
    const { container } = render(<LabTypeBadge labType="dry" />);
    const icon = container.querySelector('svg[aria-hidden="true"]');
    expect(icon).not.toBeNull();
  });

  it('uses larger padding when size="md"', () => {
    render(<LabTypeBadge labType="dry" size="md" />);
    const el = screen.getByText('Dry Lab');
    expect(el).toHaveClass('px-2.5', 'py-1');
  });
});
