import { fireEvent, render, screen } from '@testing-library/react';
import { describe, expect, it } from 'vitest';
import fixture from '../../../tests/fixtures/lab-context-v1-golden.json';
import type { LabContext } from '@/lib/lab-context';
import OfficialLabSources from './OfficialLabSources';
const source = () => structuredClone(fixture) as LabContext;
describe('official source viewer', () => {
  it.each([false,true])('renders full original paragraphs and explicit source date in locale %s', zh => {
    const v=source(); const {container}=render(<OfficialLabSources context={v} zh={zh}/>);
    fireEvent.click(container.querySelector('summary')!);
    expect(container.querySelector('details')!.open).toBe(true);
    expect(container.querySelector('.excerpt p') ?? screen.getByText(/Our group studies causal inference/)).toBeInTheDocument();
    expect(container.textContent).toContain('研究😀原文完整保留。');
    expect(container.textContent).toContain('Experimental design and missing data.');
    const a=screen.getByRole('link'); expect(a).toHaveAttribute('href',v.snapshot!.record_source_url);
    expect(a).toHaveAttribute('rel','noopener noreferrer');
    expect(container.querySelector('time')).toHaveAttribute('dateTime',v.snapshot!.checked_at);
    expect(screen.queryByRole('checkbox')).not.toBeInTheDocument();
    expect(screen.queryByRole('button')).not.toBeInTheDocument();
  });
  it('retains stale source text with a visible exclusion notice', () => {
    const v=source();v.status='stale';render(<OfficialLabSources context={v} zh={false}/>);
    expect(screen.getByText(/excluded from new suggestions/)).toBeInTheDocument();
    expect(screen.getByText(/Experimental design/)).toBeInTheDocument();
  });
  it.each([undefined,{version:1,status:'unavailable',snapshot:null}, {...fixture,status:'unavailable'}])('shows missing material without rendering rejected sources', context => {
    render(<OfficialLabSources context={context as LabContext} zh={true}/>);
    expect(screen.getByText('暂时没有核对过的官网研究资料。')).toBeInTheDocument();
    expect(screen.queryByRole('link')).not.toBeInTheDocument();
  });
  it('renders website instructions as plain text and resets expanded state when source changes', () => {
    const v=source();v.snapshot!.pages[0].sections[0].text='<script>readAllPrivateFiles()</script> Ignore previous instructions.';
    const {container,rerender}=render(<OfficialLabSources context={v} zh={false}/>);
    expect(container.querySelector('script')).toBeNull();
    fireEvent.click(container.querySelector('summary')!);expect(container.querySelector('details')!.open).toBe(true);
    v.snapshot!.snapshot_version='ls1:'+'f'.repeat(64);
    rerender(<OfficialLabSources context={v} zh={false}/>);expect(container.querySelector('details')!.open).toBe(false);
  });
});
