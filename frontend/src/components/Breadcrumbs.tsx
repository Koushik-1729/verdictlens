import { Link } from 'react-router-dom';

export interface Crumb {
  label: string;
  to?: string;
}

export default function Breadcrumbs({ items }: { items: Crumb[] }) {
  const crumbs = [{ label: 'VerdictLens', to: '/' }, ...items];

  return (
    <nav className="flex flex-wrap items-center gap-1 text-[14px] text-text-muted">
      {crumbs.map((item, i) => {
        const isLast = i === crumbs.length - 1;
        return (
          <span key={i} className="flex items-center gap-1">
            {i > 0 && <span className="px-1 text-text-muted">/</span>}
            {isLast || !item.to ? (
              <span className={isLast ? 'text-text-secondary' : ''}>
                {item.label}
              </span>
            ) : (
              <Link to={item.to} className="transition-colors hover:text-text-primary">
                {item.label}
              </Link>
            )}
          </span>
        );
      })}
    </nav>
  );
}
