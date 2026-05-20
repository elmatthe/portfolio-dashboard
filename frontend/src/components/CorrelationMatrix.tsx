import type { CorrelationMatrix as CorrelationMatrixData } from "../types";

interface Props {
  data: CorrelationMatrixData | undefined;
  isLoading: boolean;
}

function color(value: number): string {
  // Red (-1) → white (0) → green (+1).
  const v = Math.max(-1, Math.min(1, value));
  if (v >= 0) return `rgba(16, 185, 129, ${(v * 0.35 + 0.05).toFixed(3)})`;
  return `rgba(239, 68, 68, ${(-v * 0.35 + 0.05).toFixed(3)})`;
}

export default function CorrelationMatrix({ data, isLoading }: Props) {
  if (isLoading) {
    return <div className="card text-sm text-text-muted">Loading correlation…</div>;
  }
  if (!data || data.tickers.length === 0) {
    return (
      <div className="card text-sm text-text-muted">
        No correlation data yet — refresh prices to populate history.
      </div>
    );
  }

  const { tickers, matrix } = data;
  return (
    <div className="card overflow-x-auto">
      <table className="text-sm border-collapse">
        <thead>
          <tr>
            <th className="p-2 text-left font-medium text-text-muted">Ticker</th>
            {tickers.map((t) => (
              <th key={t} className="p-2 text-right font-medium text-text-muted">
                {t}
              </th>
            ))}
          </tr>
        </thead>
        <tbody>
          {tickers.map((row, i) => (
            <tr key={row}>
              <td className="p-2 font-medium">{row}</td>
              {tickers.map((col, j) => {
                const v = matrix[i]?.[j] ?? 0;
                return (
                  <td
                    key={col}
                    className="p-2 text-right num"
                    style={{ background: color(v) }}
                  >
                    {v.toFixed(2)}
                  </td>
                );
              })}
            </tr>
          ))}
        </tbody>
      </table>
      <p className="mt-3 text-xs text-text-muted">
        Pearson correlation of weekly returns. Diagonal = 1.00 (a security is perfectly correlated
        with itself).
      </p>
    </div>
  );
}
