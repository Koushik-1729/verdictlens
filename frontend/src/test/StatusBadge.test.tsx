import { render, screen } from '@testing-library/react';
import { describe, it, expect } from 'vitest';
import StatusBadge from '../components/StatusBadge';

describe('StatusBadge', () => {
  it('renders the status text', () => {
    render(<StatusBadge status="success" />);
    expect(screen.getByText('success')).toBeInTheDocument();
  });

  it('renders error status', () => {
    render(<StatusBadge status="error" />);
    expect(screen.getByText('error')).toBeInTheDocument();
  });

  it('renders unknown status', () => {
    render(<StatusBadge status="pending" />);
    expect(screen.getByText('pending')).toBeInTheDocument();
  });
});
