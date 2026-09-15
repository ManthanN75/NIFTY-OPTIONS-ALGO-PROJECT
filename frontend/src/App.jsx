import { useEffect, useState } from "react";
import { fetchPeriod } from "./api";
import { computeDrawdownSeries } from "./format";
import PeriodMetricsColumn from "./components/PeriodMetricsColumn";
import EquityChart from "./components/EquityChart";
import DrawdownChart from "./components/DrawdownChart";
import TradeTable from "./components/TradeTable";

export default function App() {
  // `data` holds both periods once loaded: { tuning: {...}, test: {...} }
  const [data, setData] = useState(null);
  const [error, setError] = useState(null);
  // Which period's charts + trade table are currently shown below the
  // metric cards. The metric cards themselves always show BOTH periods
  // side by side, since comparing them is the main point of the dashboard.
  const [activePeriod, setActivePeriod] = useState("test");

  useEffect(() => {
    async function loadData() {
      try {
        const [tuning, test] = await Promise.all([fetchPeriod("tuning"), fetchPeriod("test")]);
        setData({ tuning, test });
      } catch (err) {
        setError(err.message);
      }
    }
    loadData();
  }, []);

  if (error) {
    return (
      <div className="status-screen">
        <p>Couldn't load data: {error}</p>
        <p className="status-hint">Is the FastAPI backend running? Start it with: uvicorn api:app --reload</p>
      </div>
    );
  }

  if (!data) {
    return <div className="status-screen">Loading backtest results...</div>;
  }

  const active = data[activePeriod];
  const drawdownSeries = computeDrawdownSeries(active.equity_curve);

  return (
    <div className="app">
      <header className="app-header">
        <h1>Nifty Iron Condor Strategy</h1>
        <p className="app-subtitle">
          Backtest dashboard &middot; IV-rank triggered iron condors on Nifty index options
        </p>
      </header>

      <section className="metrics-comparison">
        <PeriodMetricsColumn title="Tuning Period" subtitle="First 4 months" metrics={data.tuning.metrics} />
        <PeriodMetricsColumn title="Test Period" subtitle="Remaining ~6 months (unseen)" metrics={data.test.metrics} />
      </section>

      <section className="period-toggle-section">
        <div className="period-toggle">
          <button
            className={activePeriod === "tuning" ? "toggle-btn active" : "toggle-btn"}
            onClick={() => setActivePeriod("tuning")}
          >
            Tuning
          </button>
          <button
            className={activePeriod === "test" ? "toggle-btn active" : "toggle-btn"}
            onClick={() => setActivePeriod("test")}
          >
            Test
          </button>
        </div>

        <div className="chart-grid">
          <div className="panel">
            <h3>Equity Curve</h3>
            <EquityChart data={active.equity_curve} />
          </div>
          <div className="panel">
            <h3>Drawdown</h3>
            <DrawdownChart data={drawdownSeries} />
          </div>
        </div>

        <div className="panel">
          <h3>Trade Log</h3>
          <TradeTable trades={active.trades} />
        </div>
      </section>
    </div>
  );
}
