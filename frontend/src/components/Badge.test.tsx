import { describe, it, expect } from 'vitest';
import { render, screen } from '@testing-library/react';
import Badge from './Badge';

describe('Badge', () => {
  it('renders children inside a span', () => {
    render(<Badge variant="blue">Hello</Badge>);
    const el = screen.getByText('Hello');
    expect(el).toBeInTheDocument();
    expect(el.tagName).toBe('SPAN');
  });

  it('applies the green variant classes', () => {
    render(<Badge variant="green">ok</Badge>);
    const el = screen.getByText('ok');
    expect(el).toHaveClass('bg-emerald-50/80', 'text-emerald-600');
  });

  it('applies the red variant classes (distinct from green)', () => {
    render(<Badge variant="red">stop</Badge>);
    const el = screen.getByText('stop');
    expect(el).toHaveClass('bg-red-50/80', 'text-red-600');
    expect(el).not.toHaveClass('bg-emerald-50/80');
  });

  it('renders no dot by default', () => {
    const { container } = render(<Badge variant="gray">no dot</Badge>);
    expect(container.querySelector('span > span[aria-hidden="true"]')).toBeNull();
  });

  it('renders an aria-hidden dot when dot prop is true', () => {
    const { container } = render(<Badge variant="orange" dot>with dot</Badge>);
    const dot = container.querySelector('span > span[aria-hidden="true"]');
    expect(dot).not.toBeNull();
    expect(dot).toHaveClass('rounded-full');
  });

  it('merges extra className without dropping variant classes', () => {
    render(<Badge variant="indigo" className="ml-4 custom-thing">x</Badge>);
    const el = screen.getByText('x');
    expect(el).toHaveClass('ml-4', 'custom-thing', 'bg-indigo-50/80', 'text-indigo-600');
  });

  it('covers every BadgeVariant key without throwing', () => {
    const variants = ['green', 'red', 'blue', 'yellow', 'orange', 'gray', 'indigo', 'teal'] as const;
    for (const v of variants) {
      const { unmount } = render(<Badge variant={v}>{v}</Badge>);
      expect(screen.getByText(v)).toBeInTheDocument();
      unmount();
    }
  });
});
