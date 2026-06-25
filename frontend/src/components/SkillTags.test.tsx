/*
 * SkillTags lets users pick from ~80 preset skills AND add their own
 * (the presets are a starter set, not a closed list). These tests cover
 * the custom-add affordance and that it reuses the normal add path.
 */

import { afterEach, describe, expect, it, vi } from 'vitest';
import { cleanup, fireEvent, render, screen } from '@testing-library/react';
import type { SkillWithLevel } from '@/lib/types';
import SkillTags from './SkillTags';

afterEach(cleanup);

function setup(selected: SkillWithLevel[] = []) {
  const onChange = vi.fn();
  render(<SkillTags selected={selected} onChange={onChange} />);
  const input = screen.getByPlaceholderText(/search or add|add more/i);
  fireEvent.focus(input);
  return { onChange, input };
}

describe('SkillTags — custom skill input', () => {
  it('offers "Add" for a skill not in the presets and adds it at beginner level', () => {
    const { onChange, input } = setup();
    fireEvent.change(input, { target: { value: 'Quantum Computing' } });
    const addBtn = screen.getByRole('button', { name: /Add/i });
    fireEvent.mouseDown(addBtn);
    expect(onChange).toHaveBeenCalledWith([
      { name: 'Quantum Computing', level: 'beginner' },
    ]);
  });

  it('adds the custom skill on Enter when no preset matches', () => {
    const { onChange, input } = setup();
    fireEvent.change(input, { target: { value: 'Magnetometry' } });
    fireEvent.keyDown(input, { key: 'Enter' });
    expect(onChange).toHaveBeenCalledWith([
      { name: 'Magnetometry', level: 'beginner' },
    ]);
  });

  it('does not offer a custom-add for an exact preset (case-insensitive)', () => {
    const { input } = setup();
    fireEvent.change(input, { target: { value: 'python' } });
    // 'Python' shows as a preset option, but there is no "Add" custom row.
    expect(screen.queryByRole('button', { name: /^Add/i })).toBeNull();
    expect(screen.getByRole('button', { name: 'Python' })).toBeInTheDocument();
  });

  it('Enter on an exact preset query adds the preset, not a duplicate custom', () => {
    const { onChange, input } = setup();
    fireEvent.change(input, { target: { value: 'Rust' } });
    fireEvent.keyDown(input, { key: 'Enter' });
    expect(onChange).toHaveBeenCalledWith([{ name: 'Rust', level: 'beginner' }]);
  });
});
