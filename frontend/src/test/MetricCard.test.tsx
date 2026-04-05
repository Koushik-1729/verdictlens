import { render, screen } from '@testing-library/react';
import { describe, it, expect } from 'vitest';
import MetricCard from '../components/MetricCard';

describe('MetricCard', () => {
  it('renders label and value', () => {
    render(<MetricCard label="Total Traces" value={1234} />);
    expect(screen.getByText('Total Traces')).toBeInTheDocument();
    expect(screen.getByText('1234')).toBeInTheDocument();
  });

  it('renders sub text when provided', () => {
    render(<MetricCard label="Cost" value="$0.42" sub="last 7 days" />);
    expect(screen.getByText('last 7 days')).toBeInTheDocument();
  });

  it('does not render sub text when omitted', () => {
    render(<MetricCard label="Errors" value={0} />);
    expect(screen.queryByText('last 7 days')).not.toBeInTheDocument();
  });

  it('renders icon when provided', () => {
    render(
      <MetricCard
        label="Agents"
        value={5}
        icon={<span data-testid="metric-icon" />}
      />
    );
    expect(screen.getByTestId('metric-icon')).toBeInTheDocument();
  });
});
