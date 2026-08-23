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

  it('Enter on an empty input does nothing', () => {
    const { onChange, input } = setup();
    fireEvent.keyDown(input, { key: 'Enter' });
    expect(onChange).not.toHaveBeenCalled();
  });

  it('Enter on a whitespace-only input does nothing', () => {
    const { onChange, input } = setup();
    fireEvent.change(input, { target: { value: '   ' } });
    fireEvent.keyDown(input, { key: 'Enter' });
    expect(onChange).not.toHaveBeenCalled();
  });
});

describe('SkillTags — selected tag labels (i18n)', () => {
  it('renders the level label and remove button from the dictionary', () => {
    const { onChange } = setup([{ name: 'Python', level: 'beginner' }]);
    const levelBtn = screen.getByRole('button', { name: 'Beginner' });
    expect(levelBtn).toHaveAttribute('title', 'Click to change level (Beginner)');
    fireEvent.click(levelBtn);
    expect(onChange).toHaveBeenCalledWith([{ name: 'Python', level: 'experienced', confirmed: true }]);
    expect(screen.getByRole('button', { name: 'Remove Python' })).toBeInTheDocument();
  });

  it('has en + zh dictionary labels for every skill level', async () => {
    const { en, zh } = await import('@/i18n/dictionaries');
    for (const level of ['beginner', 'experienced', 'expert'] as const) {
      expect(en.skills.levels[level]).toBeTruthy();
      expect(zh.skills.levels[level]).toBeTruthy();
    }
  });
});

describe('SkillTags — level cycling', () => {
  it('cycles experienced → expert', () => {
    const { onChange } = setup([{ name: 'Python', level: 'experienced' }]);
    fireEvent.click(screen.getByRole('button', { name: 'Experienced' }));
    expect(onChange).toHaveBeenCalledWith([{ name: 'Python', level: 'expert', confirmed: true }]);
  });

  it('wraps expert → beginner', () => {
    const { onChange } = setup([{ name: 'Python', level: 'expert' }]);
    fireEvent.click(screen.getByRole('button', { name: 'Expert' }));
    expect(onChange).toHaveBeenCalledWith([{ name: 'Python', level: 'beginner', confirmed: true }]);
  });

  it('cycling one chip leaves sibling chips untouched', () => {
    const { onChange } = setup([
      { name: 'Python', level: 'expert' },
      { name: 'Java', level: 'beginner' },
    ]);
    fireEvent.click(screen.getByRole('button', { name: 'Beginner' }));
    expect(onChange).toHaveBeenCalledWith([
      // Untouched: cycling one chip confirms that chip only.
      { name: 'Python', level: 'expert' },
      { name: 'Java', level: 'experienced', confirmed: true },
    ]);
  });
});
