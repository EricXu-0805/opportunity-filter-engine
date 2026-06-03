import { describe, it, expect } from 'vitest';
import { render, screen } from '@testing-library/react';
import ScoreBar from './ScoreBar';

function getFillBar(container: HTMLElement): HTMLElement {
  const fill = container.querySelector('div.bg-gradient-to-r') as HTMLElement | null;
  if (!fill) throw new Error('expected gradient fill bar to be rendered');
  return fill;
}

describe('ScoreBar', () => {
  describe('label rendering', () => {
    it('renders the rounded percentage when showLabel is default (true)', () => {
      render(<ScoreBar score={72.3} />);
      expect(screen.getByText('72%')).toBeInTheDocument();
    });

    it('hides the percentage label when showLabel=false', () => {
      render(<ScoreBar score={72} showLabel={false} />);
      expect(screen.queryByText('72%')).toBeNull();
    });
  });

  describe('size variants', () => {
    it('defaults to size=md (h-1.5 track)', () => {
      const { container } = render(<ScoreBar score={50} />);
      expect(container.querySelector('.h-1\\.5')).not.toBeNull();
    });

    it('applies h-1 for size=sm', () => {
      const { container } = render(<ScoreBar score={50} size="sm" />);
      expect(container.querySelector('.h-1')).not.toBeNull();
      expect(container.querySelector('.h-1\\.5')).toBeNull();
    });

    it('applies h-2 for size=lg', () => {
      const { container } = render(<ScoreBar score={50} size="lg" />);
      expect(container.querySelector('.h-2')).not.toBeNull();
    });
  });

  describe('color bucketing by score', () => {
    it('uses emerald gradient for score >= 80', () => {
      const { container } = render(<ScoreBar score={92} />);
      expect(getFillBar(container).className).toMatch(/from-emerald-400/);
      expect(screen.getByText('92%')).toHaveClass('text-emerald-600');
    });

    it('uses blue gradient for 60 <= score < 80', () => {
      const { container } = render(<ScoreBar score={70} />);
      expect(getFillBar(container).className).toMatch(/from-blue-400/);
      expect(screen.getByText('70%')).toHaveClass('text-blue-600');
    });

    it('uses amber gradient for 40 <= score < 60', () => {
      const { container } = render(<ScoreBar score={50} />);
      expect(getFillBar(container).className).toMatch(/from-amber-400/);
      expect(screen.getByText('50%')).toHaveClass('text-amber-600');
    });

    it('uses gray gradient for score < 40', () => {
      const { container } = render(<ScoreBar score={15} />);
      expect(getFillBar(container).className).toMatch(/from-gray-300/);
      expect(screen.getByText('15%')).toHaveClass('text-gray-500');
    });

    it('treats exactly 80 as emerald (inclusive boundary)', () => {
      const { container } = render(<ScoreBar score={80} />);
      expect(getFillBar(container).className).toMatch(/from-emerald-400/);
    });
  });

  describe('color from bucket (FE-3)', () => {
    it('uses the bucket color over the score threshold when bucket is provided', () => {
      // A 78-79 score earns the green high_priority badge but is < 80, so the
      // score-only path would paint it blue. The bucket prop keeps them in sync.
      const { container } = render(<ScoreBar score={79} bucket="high_priority" />);
      expect(getFillBar(container).className).toMatch(/from-emerald-400/);
      expect(screen.getByText('79%')).toHaveClass('text-emerald-600');
    });

    it('paints a percentile-demoted reach amber even when the score is high', () => {
      const { container } = render(<ScoreBar score={66} bucket="reach" />);
      expect(getFillBar(container).className).toMatch(/from-amber-400/);
    });

    it('falls back to score thresholds when no bucket is given', () => {
      const { container } = render(<ScoreBar score={79} />);
      expect(getFillBar(container).className).toMatch(/from-blue-400/);
    });
  });

  describe('clamping + rounding', () => {
    it('clamps negative scores to 0', () => {
      const { container } = render(<ScoreBar score={-25} />);
      expect(screen.getByText('0%')).toBeInTheDocument();
      expect(getFillBar(container).style.width).toBe('0%');
    });

    it('clamps scores over 100 to 100', () => {
      const { container } = render(<ScoreBar score={150} />);
      expect(screen.getByText('100%')).toBeInTheDocument();
      expect(getFillBar(container).style.width).toBe('100%');
    });

    it('rounds fractional scores to the nearest integer (75.7 -> 76)', () => {
      render(<ScoreBar score={75.7} />);
      expect(screen.getByText('76%')).toBeInTheDocument();
    });

    it('sets fill width to match the (clamped, rounded) score', () => {
      const { container } = render(<ScoreBar score={37} />);
      expect(getFillBar(container).style.width).toBe('37%');
    });
  });
});
