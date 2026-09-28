import { fireEvent, render, screen } from '@testing-library/react';
import { describe, expect, it } from 'vitest';
import fixture from '../../../tests/fixtures/lab-context-v1-golden.json';
import chainFixture from '../../../tests/fixtures/lab-context-v2-golden.json';
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

describe('V2 actual source path display',()=>{
 it.each([false,true])('shows all four pages, exact links and team identity without implying reading (%s)',zh=>{
  const v=structuredClone(chainFixture) as LabContext;const {container}=render(<OfficialLabSources context={v} zh={zh}/>);
  fireEvent.click(screen.getByText(zh?'查看来源核对过程':'View source verification'));
  expect(screen.getByRole('list',{name:zh?'来源页面':'Source pages'}).querySelectorAll('a')).toHaveLength(4);
  expect(screen.getByRole('list',{name:zh?'已观察到的链接':'Observed links'}).querySelectorAll('li')).toHaveLength(3);
  expect(screen.getByText('Rasmus Nielsen')).toBeVisible();
  expect(container.textContent).toContain(chainFixture.snapshot.source_chain.identity.role_text);
  for(const link of chainFixture.snapshot.source_chain.links) expect(container.textContent).toContain(link.raw_href);
  fireEvent.click(screen.getByText((zh?'实验室研究全文：':'Full lab research: ')+chainFixture.snapshot.pages[1].page_title));
  expect(screen.getByText(chainFixture.snapshot.pages[1].sections[9].text)).toBeVisible();
  expect(container.textContent).toContain(zh?'不是你的阅读记录':'not your reading');
  expect(screen.queryByRole('checkbox')).toBeNull();expect(screen.queryByRole('button')).toBeNull();
  for(const a of container.querySelectorAll('a'))expect(a).toHaveAttribute('rel','noopener noreferrer');
 });
 it('keeps stale history and its chain visible but marks it excluded from new suggestions',()=>{
  const v=structuredClone(chainFixture) as LabContext;v.status='stale';render(<OfficialLabSources context={v} zh={false}/>);
  expect(screen.getByText(/excluded from new suggestions/)).toBeVisible();
  fireEvent.click(screen.getByText('View source verification'));expect(screen.getByText('Rasmus Nielsen')).toBeVisible();
 });
 it('closes source details after a new source version and hides malformed chains',()=>{
  const v=structuredClone(chainFixture) as LabContext;const {container,rerender}=render(<OfficialLabSources context={v} zh={false}/>);
  fireEvent.click(screen.getByText('View source verification'));expect(container.querySelector('details')!.open).toBe(true);
  v.snapshot!.snapshot_version='ls2:'+'a'.repeat(64);rerender(<OfficialLabSources context={v} zh={false}/>);
  expect(container.querySelector('details')!.open).toBe(false);
  if(v.snapshot!.version===2)v.snapshot!.source_chain.links[2].from_url=v.snapshot!.record_source_url;
  rerender(<OfficialLabSources context={v} zh={false}/>);expect(screen.queryByRole('link')).toBeNull();
 });
});
