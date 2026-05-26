import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';
import { render, waitFor } from '@testing-library/react';
import HighlightLabType from './HighlightLabType';

function setLocation(search: string) {
  window.history.replaceState({}, '', search === '' ? window.location.pathname : `${window.location.pathname}${search}`);
}

function mountTarget(labType: string) {
  const el = document.createElement('article');
  el.id = `tips-card-${labType}`;
  el.scrollIntoView = vi.fn();
  document.body.appendChild(el);
  return el;
}

beforeEach(() => {
  document.body.innerHTML = '';
  setLocation('');
});

afterEach(() => {
  vi.useRealTimers();
});

describe('HighlightLabType', () => {
  it('renders nothing visible', () => {
    const { container } = render(<HighlightLabType />);
    expect(container.firstChild).toBeNull();
  });

  it('does nothing when there is no ?lab= param', () => {
    const el = mountTarget('wet');
    render(<HighlightLabType />);
    expect(el.className).not.toContain('ring-2');
  });

  it('does nothing for an invalid ?lab= param', () => {
    setLocation('?lab=robotics');
    const el = mountTarget('wet');
    render(<HighlightLabType />);
    expect(el.className).not.toContain('ring-2');
  });

  it('does nothing when the target card is missing from the DOM', () => {
    setLocation('?lab=wet');
    const { container } = render(<HighlightLabType />);
    expect(container.firstChild).toBeNull();
  });

  it('rings + scrolls to the wet card', async () => {
    setLocation('?lab=wet');
    const el = mountTarget('wet');
    render(<HighlightLabType />);
    await waitFor(() => expect(el.className).toContain('ring-2'));
    expect(el.scrollIntoView).toHaveBeenCalledWith({ behavior: 'smooth', block: 'center' });
  });

  it('removes the ring after the timeout', async () => {
    vi.useFakeTimers();
    setLocation('?lab=dry');
    const el = mountTarget('dry');
    render(<HighlightLabType />);
    expect(el.className).toContain('ring-2');
    vi.advanceTimersByTime(3000);
    expect(el.className).not.toContain('ring-2');
  });

  it('handles all three valid lab types', async () => {
    for (const lab of ['wet', 'dry', 'humanities']) {
      document.body.innerHTML = '';
      setLocation(`?lab=${lab}`);
      const el = mountTarget(lab);
      render(<HighlightLabType />);
      await waitFor(() => expect(el.className).toContain('ring-2'));
    }
  });
});
