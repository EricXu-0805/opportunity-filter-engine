import { afterEach, describe, expect, it } from 'vitest';
import { cleanup, fireEvent, render, screen } from '@testing-library/react';
import type { Opportunity } from '@/lib/types';
import RadarChart from './RadarChart';
import type { CompareRow } from './scores';

function row(id: string, title: string, score: number, base: number): CompareRow {
  return {
    opp: { id, title, organization: 'Test U' } as Opportunity,
    inputIndex: base,
    status: 'ready',
    match: {
      final_score: score,
      bucket: score > 80 ? 'high_priority' : 'good_match',
      reasons_fit: [],
      reasons_gap: [],
      explanation: '',
      method: 'local',
      matcher_version: 'test-matcher-v1',
    },
    factors: {
      skill_match: base + 1,
      eligibility: base + 2,
      ease: base + 3,
      compensation: base + 4,
      deadline_runway: base + 5,
      intl_friendly: base + 6,
    },
  };
}

const ROWS = [
  row('opp-a', 'Alpha Lab', 91, 70),
  row('opp-b', 'Beta Lab', 76, 40),
];

afterEach(cleanup);

describe('RadarChart', () => {
  it('renders an honest estimate scale, data points, and an exact accessible value table', () => {
    const { container } = render(<RadarChart rows={ROWS} />);

    expect(screen.getByRole('heading', { name: 'Decision factors (estimated)' })).toBeInTheDocument();
    expect(screen.getByText(/Decision factors come from listed requirements/i)).toBeInTheDocument();
    expect(screen.getByText(/higher means less effort/i)).toBeInTheDocument();
    expect(screen.getByTestId('radar-scroll-region')).toHaveClass('overflow-x-auto', 'lg:w-[430px]');
    expect(container.querySelector('svg[role="img"]')).toHaveClass('min-w-[320px]');
    for (const tick of [0, 25, 50, 75, 100]) {
      expect(screen.getByTestId(`radar-tick-${tick}`)).toHaveTextContent(String(tick));
    }

    expect(screen.getByRole('columnheader', { name: 'Ease' })).toBeInTheDocument();
    expect(screen.getByRole('row', { name: /Alpha Lab 71 72 73 74 75 76/ })).toBeInTheDocument();
    expect(screen.getByRole('row', { name: /Beta Lab 41 42 43 44 45 46/ })).toBeInTheDocument();

    expect(container.querySelectorAll('circle[data-series-id]')).toHaveLength(12);
    expect(container.querySelector('circle[data-series-id="opp-a"][data-value="73"]')).toBeTruthy();
  });

  it('uses a unique outline per opportunity and highlights only the focused series', () => {
    const { container } = render(<RadarChart rows={ROWS} />);
    const polygons = Array.from(container.querySelectorAll('polygon[data-series-id]'));

    expect(new Set(polygons.map((polygon) => polygon.getAttribute('stroke'))).size).toBe(2);
    expect(polygons.every((polygon) => polygon.getAttribute('fill') === 'none')).toBe(true);

    const betaControl = screen.getByRole('button', { name: /Beta Lab/ });
    expect(betaControl).toHaveAttribute('tabindex', '0');
    fireEvent.focus(betaControl);

    expect(container.querySelector('polygon[data-series-id="opp-b"]')).toHaveAttribute('stroke-width', '4');
    expect(container.querySelector('polygon[data-series-id="opp-a"]')).toHaveAttribute('opacity', '0.2');

    fireEvent.blur(betaControl);
    const alphaControl = screen.getByRole('button', { name: /Alpha Lab/ });
    fireEvent.mouseEnter(alphaControl);
    expect(container.querySelector('polygon[data-series-id="opp-a"]')).toHaveAttribute('stroke-width', '4');
    expect(container.querySelector('polygon[data-series-id="opp-b"]')).toHaveAttribute('opacity', '0.2');
    fireEvent.mouseLeave(alphaControl);
    expect(container.querySelector('polygon[data-series-id="opp-b"]')).toHaveAttribute('opacity', '1');

    fireEvent.click(betaControl);
    expect(betaControl).toHaveAttribute('aria-pressed', 'true');
    fireEvent.blur(betaControl);
    expect(container.querySelector('polygon[data-series-id="opp-b"]')).toHaveAttribute('stroke-width', '4');
    expect(container.querySelector('polygon[data-series-id="opp-a"]')).toHaveAttribute('opacity', '0.2');
    fireEvent.click(betaControl);
    expect(betaControl).toHaveAttribute('aria-pressed', 'false');
  });

  it('shows missing evidence as Unknown and does not draw a fabricated point', () => {
    const partial = row('partial', 'Partial listing', 55, 50);
    partial.factors.skill_match = null;
    partial.factors.compensation = null;
    const { container } = render(<RadarChart rows={[partial]} />);

    expect(screen.getByRole('row', { name: /Partial listing Unknown 52 53 Unknown 55 56/ }))
      .toBeInTheDocument();
    expect(container.querySelector('circle[data-series-id="partial"][data-value="51"]'))
      .toBeNull();
    expect(container.querySelectorAll('circle[data-series-id="partial"]')).toHaveLength(4);
    expect(screen.getByText(/Missing evidence stays Unknown/i)).toBeInTheDocument();
  });

  it('shows the canonical score in the legend, never a locally computed overall', () => {
    render(<RadarChart rows={ROWS} />);
    expect(screen.getByRole('button', { name: /Alpha Lab, 91%/ })).toBeInTheDocument();

    cleanup();
    const failed = row('failed', 'Failed Lab', 0, 20);
    failed.match = null;
    failed.status = 'error';
    render(<RadarChart rows={[failed]} />);
    expect(screen.getByRole('button', { name: /Failed Lab, score unavailable/ })).toBeInTheDocument();
  });
});
