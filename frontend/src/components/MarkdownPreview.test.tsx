import { describe, it, expect } from 'vitest';
import { render, screen } from '@testing-library/react';
import MarkdownPreview from './MarkdownPreview';

describe('MarkdownPreview', () => {
  describe('core markdown rendering', () => {
    it('renders plain text inside a paragraph', () => {
      const { container } = render(<MarkdownPreview>{'just some text'}</MarkdownPreview>);
      const p = container.querySelector('p');
      expect(p).not.toBeNull();
      expect(p).toHaveTextContent('just some text');
    });

    it('renders an ATX heading as the matching level element', () => {
      const { container } = render(<MarkdownPreview>{'# Big Title'}</MarkdownPreview>);
      const h1 = container.querySelector('h1');
      expect(h1).not.toBeNull();
      expect(h1).toHaveTextContent('Big Title');
    });

    it('renders bold text as <strong>', () => {
      const { container } = render(<MarkdownPreview>{'this is **bold** here'}</MarkdownPreview>);
      const strong = container.querySelector('strong');
      expect(strong).not.toBeNull();
      expect(strong).toHaveTextContent('bold');
    });

    it('renders italic text as <em>', () => {
      const { container } = render(<MarkdownPreview>{'this is *slanted* here'}</MarkdownPreview>);
      const em = container.querySelector('em');
      expect(em).not.toBeNull();
      expect(em).toHaveTextContent('slanted');
    });

    it('renders a markdown link as an anchor with href', () => {
      const { container } = render(
        <MarkdownPreview>{'see [the docs](https://example.com/docs)'}</MarkdownPreview>,
      );
      const a = container.querySelector('a');
      expect(a).not.toBeNull();
      expect(a).toHaveAttribute('href', 'https://example.com/docs');
      expect(a).toHaveTextContent('the docs');
    });

    it('renders an unordered list with one <li> per item', () => {
      const { container } = render(
        <MarkdownPreview>{'- alpha\n- beta\n- gamma'}</MarkdownPreview>,
      );
      const ul = container.querySelector('ul');
      expect(ul).not.toBeNull();
      expect(ul!.querySelectorAll('li')).toHaveLength(3);
    });

    it('renders an ordered list as <ol>', () => {
      const { container } = render(
        <MarkdownPreview>{'1. first\n2. second'}</MarkdownPreview>,
      );
      const ol = container.querySelector('ol');
      expect(ol).not.toBeNull();
      expect(ol!.querySelectorAll('li')).toHaveLength(2);
    });

    it('renders inline code as <code>', () => {
      const { container } = render(<MarkdownPreview>{'run `npm test` now'}</MarkdownPreview>);
      const code = container.querySelector('code');
      expect(code).not.toBeNull();
      expect(code).toHaveTextContent('npm test');
    });

    it('renders a fenced code block inside <pre>', () => {
      const { container } = render(
        <MarkdownPreview>{'```\nconst x = 1;\n```'}</MarkdownPreview>,
      );
      const pre = container.querySelector('pre');
      expect(pre).not.toBeNull();
      expect(pre).toHaveTextContent('const x = 1;');
    });

    it('renders a blockquote', () => {
      const { container } = render(<MarkdownPreview>{'> quoted line'}</MarkdownPreview>);
      const bq = container.querySelector('blockquote');
      expect(bq).not.toBeNull();
      expect(bq).toHaveTextContent('quoted line');
    });
  });

  describe('GFM features (remark-gfm wiring)', () => {
    it('renders ~~strikethrough~~ as <del>', () => {
      const { container } = render(
        <MarkdownPreview>{'this is ~~gone~~ now'}</MarkdownPreview>,
      );
      const del = container.querySelector('del');
      expect(del).not.toBeNull();
      expect(del).toHaveTextContent('gone');
    });

    it('renders a GFM pipe table with header and body cells', () => {
      const md = ['| Name | Role |', '| --- | --- |', '| Ada | Eng |'].join('\n');
      const { container } = render(<MarkdownPreview>{md}</MarkdownPreview>);
      const table = container.querySelector('table');
      expect(table).not.toBeNull();
      expect(table!.querySelectorAll('th')).toHaveLength(2);
      expect(table!.querySelectorAll('tbody td')).toHaveLength(2);
      expect(screen.getByText('Ada')).toBeInTheDocument();
    });

    it('renders a GFM task list as checkbox inputs', () => {
      const md = '- [x] done\n- [ ] todo';
      const { container } = render(<MarkdownPreview>{md}</MarkdownPreview>);
      const boxes = container.querySelectorAll('input[type="checkbox"]');
      expect(boxes).toHaveLength(2);
      expect((boxes[0] as HTMLInputElement).checked).toBe(true);
      expect((boxes[1] as HTMLInputElement).checked).toBe(false);
    });

    it('autolinks a bare URL into an anchor', () => {
      const { container } = render(
        <MarkdownPreview>{'visit https://example.com today'}</MarkdownPreview>,
      );
      const a = container.querySelector('a');
      expect(a).not.toBeNull();
      expect(a).toHaveAttribute('href', 'https://example.com');
    });
  });

  describe('edge cases', () => {
    it('renders nothing meaningful for an empty string without crashing', () => {
      const { container } = render(<MarkdownPreview>{''}</MarkdownPreview>);
      expect(container.querySelector('p')).toBeNull();
      expect(container.textContent).toBe('');
    });

    it('reflows output when the children prop changes', () => {
      const { container, rerender } = render(<MarkdownPreview>{'# One'}</MarkdownPreview>);
      expect(container.querySelector('h1')).toHaveTextContent('One');
      rerender(<MarkdownPreview>{'## Two'}</MarkdownPreview>);
      expect(container.querySelector('h1')).toBeNull();
      expect(container.querySelector('h2')).toHaveTextContent('Two');
    });

    it('renders raw HTML as escaped text (no dangerouslySetInnerHTML)', () => {
      const { container } = render(
        <MarkdownPreview>{'before <b>bold</b> after'}</MarkdownPreview>,
      );
      expect(container.querySelector('b')).toBeNull();
      expect(container).toHaveTextContent('before <b>bold</b> after');
    });
  });
});
