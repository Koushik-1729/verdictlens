import { render, screen } from '@testing-library/react';
import { describe, it, expect } from 'vitest';
import EmptyState from '../components/EmptyState';

describe('EmptyState', () => {
  it('renders title and description', () => {
    render(
      <EmptyState
        icon={<span data-testid="icon" />}
        title="No traces found"
        description="Instrument your agent to start collecting traces."
      />
    );
    expect(screen.getByText('No traces found')).toBeInTheDocument();
    expect(screen.getByText('Instrument your agent to start collecting traces.')).toBeInTheDocument();
  });

  it('renders action when provided', () => {
    render(
      <EmptyState
        icon={<span />}
        title="Empty"
        description="Nothing here."
        action={<button>Get started</button>}
      />
    );
    expect(screen.getByRole('button', { name: 'Get started' })).toBeInTheDocument();
  });

  it('does not render action slot when not provided', () => {
    const { container } = render(
      <EmptyState icon={<span />} title="Empty" description="Nothing here." />
    );
    expect(container.querySelectorAll('button')).toHaveLength(0);
  });
});
