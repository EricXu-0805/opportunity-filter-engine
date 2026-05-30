import { describe, it, expect } from 'vitest';
import { render, screen } from '@testing-library/react';
import ContactTipsCard from './ContactTipsCard';

describe('ContactTipsCard', () => {
  it('renders the Wet Lab card with bench-work content', () => {
    render(<ContactTipsCard labType="wet" />);
    expect(screen.getByText('Wet Lab')).toBeInTheDocument();
    expect(screen.getByText(/Biology, Chemistry, Life Sciences/i)).toBeInTheDocument();
    expect(screen.getByText(/PCR/)).toBeInTheDocument();
  });

  it('renders the Dry Lab card with skills + GitHub content', () => {
    render(<ContactTipsCard labType="dry" />);
    expect(screen.getByText('Dry Lab')).toBeInTheDocument();
    expect(screen.getByText(/CS, Engineering/i)).toBeInTheDocument();
    expect(screen.getAllByText(/GitHub link/i).length).toBeGreaterThan(0);
  });

  it('renders the Humanities Lab card with RA / IRB content', () => {
    render(<ContactTipsCard labType="humanities" />);
    expect(screen.getByText('Humanities')).toBeInTheDocument();
    expect(screen.getByText(/research assistantships/i)).toBeInTheDocument();
    expect(screen.getAllByText(/IRB/).length).toBeGreaterThan(0);
  });

  it('renders three sections (What / Skills / Mistakes) per lab type', () => {
    render(<ContactTipsCard labType="dry" />);
    expect(screen.getByText('What makes this lab type different')).toBeInTheDocument();
    expect(screen.getByText('Skills to highlight')).toBeInTheDocument();
    expect(screen.getByText('Common mistakes')).toBeInTheDocument();
  });

  it('renders 4 + 4 + 3 bullets per card', () => {
    const { container } = render(<ContactTipsCard labType="wet" />);
    const sections = container.querySelectorAll('section');
    expect(sections.length).toBe(3);
    expect(sections[0].querySelectorAll('li').length).toBe(4);
    expect(sections[1].querySelectorAll('li').length).toBe(4);
    expect(sections[2].querySelectorAll('li').length).toBe(3);
  });
});
