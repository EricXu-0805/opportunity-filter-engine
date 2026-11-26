import { webcrypto } from 'node:crypto';
import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import { afterEach, beforeEach, expect, it, vi } from 'vitest';
import { LinkedInExperienceImport } from './LinkedInExperienceImport';
import type { ExperienceEntry } from '@/lib/types';

beforeEach(() => vi.stubGlobal('crypto', webcrypto));
afterEach(() => vi.unstubAllGlobals());
function selectMode(mode: string) {
  fireEvent.click(screen.getByText('Import LinkedIn experience'));
  fireEvent.change(screen.getByLabelText('Input method'), { target: { value: mode } });
}

it('previews the supplied file locally and lets the owner correct facts and retry a rejected save', async () => {
  const save = vi.fn().mockReturnValueOnce(false).mockReturnValueOnce(true);
  render(<LinkedInExperienceImport entries={[]} raw="" disabled={false} onSave={save} />);
  selectMode('file');
  const csv = 'Company Name,Title,Description,Started On,Finished On\nExample Works,Trainee,Documented tests,2024,2025';
  const file = new File([csv], 'Positions.csv', { type: 'text/csv' });
  fireEvent.change(screen.getByLabelText('Positions.csv', { selector: 'input' }), { target: { files: [file] } });
  fireEvent.click(screen.getByText('Preview experiences'));
  await screen.findByDisplayValue('Example Works');
  expect(save).not.toHaveBeenCalled();
  fireEvent.change(screen.getByLabelText('Results'), { target: { value: 'Rescued three missing test cases.' } });
  fireEvent.change(screen.getByLabelText('Choose what to save'), { target: { value: 'new' } });
  fireEvent.click(screen.getByText('Confirm selected experiences'));
  expect(await screen.findByRole('alert')).toHaveTextContent('Your profile changed');
  expect(screen.getByLabelText('Results')).toHaveValue('Rescued three missing test cases.');
  fireEvent.click(screen.getByText('Confirm selected experiences'));
  expect(await screen.findByRole('status')).toHaveTextContent('Confirmed experiences');
  const [next, base] = save.mock.calls[1];
  expect(next[0]).toMatchObject({ source: { kind: 'manual' }, status: 'confirmed' });
  expect(next[0].text).toContain('Rescued three missing test cases.');
  expect(base).toEqual({ resumeText: '', entriesJson: '[]' });
});

it('rejects a link and blocks a preview prepared before a saved profile change', async () => {
  const save = vi.fn();
  const props = { entries: [] as ExperienceEntry[], raw: '', disabled: false, onSave: save };
  const view = render(<LinkedInExperienceImport {...props} />);
  selectMode('paste');
  fireEvent.change(screen.getByLabelText('Experience text'), { target: { value: 'https://www.linkedin.com/in/example' } });
  fireEvent.click(screen.getByText('Preview experiences'));
  expect(await screen.findByRole('alert')).toHaveTextContent('profile link alone');
  fireEvent.change(screen.getByLabelText('Experience text'), { target: { value: 'Company: Fictional Co\nRole: Analyst' } });
  fireEvent.click(screen.getByText('Preview experiences'));
  await screen.findByDisplayValue('Fictional Co');
  view.rerender(<LinkedInExperienceImport {...props} raw="Later résumé edit" />);
  fireEvent.change(screen.getByLabelText('Choose what to save'), { target: { value: 'new' } });
  fireEvent.click(screen.getByText('Confirm selected experiences'));
  await waitFor(() => expect(screen.getByRole('alert')).toHaveTextContent('Your profile changed'));
  expect(save).not.toHaveBeenCalled();
});

it('supports structured manual entry with blank optional dates and outcomes', async () => {
  const save = vi.fn(() => true);
  render(<LinkedInExperienceImport entries={[]} raw="" disabled={false} onSave={save} />);
  selectMode('manual');
  fireEvent.change(screen.getByLabelText('Company'), { target: { value: 'Example Studio' } });
  fireEvent.change(screen.getByLabelText('Responsibilities'), { target: { value: 'Updated simulation scripts.' } });
  fireEvent.click(screen.getByText('Preview experiences'));
  await screen.findByText('Choose what to save');
  fireEvent.change(screen.getByLabelText('Choose what to save'), { target: { value: 'new' } });
  fireEvent.click(screen.getByText('Confirm selected experiences'));
  expect(save).toHaveBeenCalledOnce();
});
