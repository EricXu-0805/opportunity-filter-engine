import { afterEach, describe, expect, it, vi } from 'vitest';
import { cleanup, fireEvent, render, screen } from '@testing-library/react';

vi.mock('@/i18n/client', () => ({
  useT: () => ({
    t: (key: string, vars?: Record<string, string | number>) =>
      vars ? `${key}:${Object.values(vars).join(',')}` : key,
  }),
}));

import MajorTags from './MajorTags';

afterEach(cleanup);

const OPTIONS = ['Statistics', 'Data Science', 'Economics'];
const identity = (m: string) => m;

function setup(selected: string[] = []) {
  const onChange = vi.fn();
  render(
    <MajorTags selected={selected} options={OPTIONS} onChange={onChange} translate={identity} />,
  );
  return { onChange };
}

describe('MajorTags', () => {
  it('renders a chip per selected major using the translate fn for the label', () => {
    cleanup();
    const onChange = vi.fn();
    render(
      <MajorTags
        selected={['CS_KEY']}
        options={OPTIONS}
        onChange={onChange}
        translate={(m) => (m === 'CS_KEY' ? 'Computer Science' : m)}
      />,
    );
    expect(screen.getByText('Computer Science')).toBeInTheDocument();
  });

  it('adds a catalog major (raw value) when its suggestion is clicked', () => {
    const { onChange } = setup([]);
    fireEvent.focus(screen.getByRole('textbox'));
    fireEvent.mouseDown(screen.getByText('Statistics'));
    expect(onChange).toHaveBeenCalledWith(['Statistics']);
  });

  it('lets the student add a minor not in the catalog (custom free-add)', () => {
    const { onChange } = setup([]);
    const input = screen.getByRole('textbox');
    fireEvent.focus(input);
    fireEvent.change(input, { target: { value: 'Music Minor' } });
    // The custom-add row is offered because "Music Minor" is no catalog option.
    fireEvent.mouseDown(screen.getByText(/additionalMajorsAddCustom:Music Minor/));
    expect(onChange).toHaveBeenCalledWith(['Music Minor']);
  });

  it('Enter adds the first matching suggestion', () => {
    const { onChange } = setup([]);
    const input = screen.getByRole('textbox');
    fireEvent.focus(input);
    fireEvent.change(input, { target: { value: 'Data' } });
    fireEvent.keyDown(input, { key: 'Enter' });
    expect(onChange).toHaveBeenCalledWith(['Data Science']);
  });

  it('never suggests an already-selected major', () => {
    setup(['Statistics']);
    fireEvent.focus(screen.getByRole('textbox'));
    // Statistics is selected (as a chip) so it must not appear as a suggestion.
    expect(screen.queryAllByText('Statistics').length).toBe(1);
    expect(screen.getByText('Data Science')).toBeInTheDocument();
  });

  it('removing a chip reports the remaining majors', () => {
    const { onChange } = setup(['Statistics', 'Economics']);
    fireEvent.click(screen.getByLabelText('home.form.additionalMajorsRemove:Statistics'));
    expect(onChange).toHaveBeenCalledWith(['Economics']);
  });
});
