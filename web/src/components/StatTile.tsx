interface Props {
  label: string;
  value: string;
  /** vs a named period; `good` says whether the direction is good news. */
  delta?: { text: string; direction: 'up' | 'down' | 'flat'; goodWhenUp?: boolean };
  /** The one number a view leads with. */
  hero?: boolean;
}

const ARROW = { up: '▲', down: '▼', flat: '■' } as const;

export function StatTile({ label, value, delta, hero }: Props) {
  const good = delta?.direction === 'flat' ? null : delta?.direction === 'up' ? (delta.goodWhenUp ?? true) : !(delta?.goodWhenUp ?? true);
  return (
    <div className={`tile${hero ? ' tile-hero' : ''}`}>
      <div className="tile-label">{label}</div>
      <div className="tile-value">{value}</div>
      {delta && (
        <div className="tile-delta">
          <span className={good == null ? undefined : good ? 'up' : 'down'}>
            <span aria-hidden="true">{ARROW[delta.direction]} </span>
            {delta.text}
          </span>
        </div>
      )}
    </div>
  );
}
