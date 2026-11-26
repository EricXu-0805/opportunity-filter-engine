import { useState } from 'react';
import { fireEvent, render, screen } from '@testing-library/react';
import { expect, it } from 'vitest';
import { ResultsTabs } from './ResultsTabs';
import type { Tab } from './types';

function Results() {
  const [selected, select] = useState<Tab>('all');
  return <ResultsTabs activeTab={selected} onChange={select} t={key => key}
    counts={{ all: 3, high_priority: 1, good_match: 2, reach: 0, starred: 0 }} />;
}

it('moves through categories with one tab stop, wraps arrows, and retains keyboard focus', () => {
  render(<Results />);
  const tabs = screen.getAllByRole('tab');
  tabs[0].focus();
  fireEvent.keyDown(tabs[0], { key: 'ArrowRight' });
  expect(tabs[1]).toHaveFocus();
  expect(tabs.filter(tab => tab.tabIndex === 0)).toEqual([tabs[1]]);
  expect(tabs[1]).toHaveAttribute('aria-selected', 'true');
  fireEvent.keyDown(tabs[1], { key: 'Home' });
  expect(tabs[0]).toHaveFocus();
  fireEvent.keyDown(tabs[0], { key: 'ArrowLeft' });
  expect(tabs.at(-1)).toHaveFocus();
  fireEvent.keyDown(tabs.at(-1)!, { key: 'ArrowRight' });
  expect(tabs[0]).toHaveFocus();
  fireEvent.keyDown(tabs[0], { key: 'End' });
  expect(tabs.at(-1)).toHaveFocus();
  expect(tabs.at(-1)).toHaveAttribute('aria-selected', 'true');
  expect(tabs.at(-1)).toHaveAttribute('aria-controls','match-category-results');
});
