import { useState, useEffect, useCallback } from 'react';

const API = '/api';

function useFetch(path, interval = 60000) {
  const [data, setData] = useState(null);
  const [loading, setLoading] = useState(true);
  const load = useCallback(async () => {
    try {
      const r = await fetch(`${API}${path}`);
      if (r.ok) setData(await r.json());
    } catch {}
    setLoading(false);
  }, [path]);
  useEffect(() => { load(); const t = setInterval(load, interval); return () => clearInterval(t); }, [load, interval]);
  return { data, loading, reload: load };
}

function AnimatedNumber({ value, decimals = 2, prefix = '', suffix = '', className = '' }) {
  const [display, setDisplay] = useState(value);
  useEffect(() => { setDisplay(value); }, [value]);
  return <span className={`animate-count ${className}`}>{prefix}{typeof display === 'number' ? display.toFixed(decimals) : display}{suffix}</span>;
}

function CountdownTimer({ targetDate }) {
  const [diff, setDiff] = useState('');
  useEffect(() => {
    const update = () => {
      const ms = new Date(targetDate) - new Date();
      if (ms <= 0) { setDiff('Resolved'); return; }
      const h = Math.floor(ms / 3600000);
      const m = Math.floor((ms % 3600000) / 60000);
      const s = Math.floor((ms % 60000) / 1000);
      setDiff(`${h}h ${m}m ${s}s`);
    };
    update();
    const t = setInterval(update, 1000);
    return () => clearInterval(t);
  }, [targetDate]);
  return <span className="font-mono text-sm text-primary">{diff}</span>;
}

function SummaryCard({ title, value, prefix = '', suffix = '', color = 'text-primary', sub = '' }) {
  return (
    <div className="bg-card border border-border rounded-xl p-4 card-glow transition-all animate-fade-in">
      <div className="text-muted text-xs uppercase tracking-wider mb-1">{title}</div>
      <div className={`text-2xl font-bold ${color}`}>
        {prefix}{typeof value === 'number' ? value.toFixed(2) : value}{suffix}
      </div>
      {sub && <div className="text-muted text-xs mt-1">{sub}</div>}
    </div>
  );
}

function OpenPositionCard({ market }) {
  const pos = market.position || {};
  const hasPrice = pos.currentPrice != null && pos.currentPrice !== '';
  const isProfit = hasPrice && pos.currentPrice > pos.entry_price;
  const isLoss = hasPrice && pos.currentPrice < pos.entry_price;
  const borderClass = isProfit ? 'border-success/40' : isLoss ? 'border-red-500/40' : 'border-border';
  const unrealizedPnl = hasPrice ? (pos.currentPrice - pos.entry_price) * (pos.shares || 0) : null;
  const winProb = hasPrice ? (pos.currentPrice * 100).toFixed(1) : '—';

  return (
    <div className={`bg-card border ${borderClass} rounded-xl p-4 card-glow transition-all animate-fade-in`}>
      <div className="flex justify-between items-start mb-3">
        <div>
          <h3 className="text-lg font-bold text-white">{market.city_name || market.city}</h3>
          <span className="text-muted text-sm">{market.date}</span>
        </div>
        {market.event_end_date && <CountdownTimer targetDate={market.event_end_date} />}
      </div>
      <div className="grid grid-cols-2 sm:grid-cols-4 gap-3 text-sm">
        <div><span className="text-muted">Bucket</span><br/><span className="text-white">{pos.bucket_low}°-{pos.bucket_high}°C</span></div>
        <div><span className="text-muted">Entry</span><br/><span className="text-primary">{(pos.entry_price * 100).toFixed(1)}¢</span></div>
        <div><span className="text-muted">Current</span><br/><span className={isProfit ? 'text-success' : isLoss ? 'text-red-400' : 'text-primary'}>{pos.currentPrice ? (pos.currentPrice * 100).toFixed(1) + '¢' : '—'}</span></div>
        <div><span className="text-muted">Win Prob</span><br/><span className={isProfit ? 'text-success' : 'text-warn'}>{winProb}%</span></div>
        <div><span className="text-muted">Forecast</span><br/><span className="text-highlight">{pos.forecast_temp}°C ({pos.forecast_src})</span></div>
        <div><span className="text-muted">Confidence</span>
          <div className="w-full bg-gray-700 rounded-full h-2 mt-1">
            <div className="bg-primary rounded-full h-2 transition-all" style={{ width: `${(pos.gfs_confidence || 0) * 100}%` }} />
          </div>
          <span className="text-xs text-muted">{((pos.gfs_confidence || 0) * 100).toFixed(0)}%</span>
        </div>
        <div><span className="text-muted">EV</span><br/><span className="text-success">{((pos.ev || 0) * 100).toFixed(0)}%</span></div>
        <div>
          <span className="text-muted">Unrealized P&L</span><br/>
          <span className={unrealizedPnl > 0 ? 'text-success' : unrealizedPnl < 0 ? 'text-red-400' : 'text-muted'}>
            {unrealizedPnl !== null ? `$${unrealizedPnl.toFixed(2)}` : '—'}
          </span>
        </div>
      </div>
      {pos.trade_reason && <div className="mt-2 text-xs text-muted italic">"{pos.trade_reason}"</div>}
    </div>
  );
}

function RecentTrades({ markets }) {
  const resolved = markets
    .filter(m => m.status === 'resolved' && m.position)
    .sort((a, b) => new Date(b.event_end_date) - new Date(a.event_end_date))
    .slice(0, 10);

  return (
    <div className="bg-card border border-border rounded-xl p-4 animate-fade-in">
      <h2 className="text-lg font-bold text-primary mb-3">Recent Trades</h2>
      <div className="space-y-2">
        {resolved.map((m, i) => {
          const isWin = m.pnl > 0;
          return (
            <div key={i} className={`flex justify-between items-center p-2 rounded-lg ${isWin ? 'bg-success/5' : 'bg-red-500/5'}`}>
              <div className="flex items-center gap-3">
                <span className={`text-xs font-bold px-2 py-0.5 rounded ${isWin ? 'bg-success/20 text-success' : 'bg-red-500/20 text-red-400'}`}>
                  {isWin ? 'WIN' : 'LOSS'}
                </span>
                <span className="text-white text-sm">{m.city_name}</span>
                <span className="text-muted text-xs">{m.date}</span>
              </div>
              <span className={`font-mono font-bold ${isWin ? 'text-success' : 'text-red-400'}`}>
                {m.pnl >= 0 ? '+' : ''}{m.pnl?.toFixed(2)}
              </span>
            </div>
          );
        })}
        {resolved.length === 0 && <div className="text-muted text-sm">No resolved trades yet</div>}
      </div>
    </div>
  );
}

function CityPerformance({ markets }) {
  const byCity = {};
  markets.filter(m => m.status === 'resolved' && m.position).forEach(m => {
    const c = m.city_name || m.city;
    if (!byCity[c]) byCity[c] = { wins: 0, total: 0, pnl: 0 };
    byCity[c].total++;
    if (m.pnl > 0) byCity[c].wins++;
    byCity[c].pnl += m.pnl || 0;
  });
  const cities = Object.entries(byCity).sort((a, b) => b[1].pnl - a[1].pnl);

  return (
    <div className="bg-card border border-border rounded-xl p-4 animate-fade-in">
      <h2 className="text-lg font-bold text-primary mb-3">City Performance</h2>
      <div className="space-y-2">
        {cities.map(([city, d]) => (
          <div key={city} className="flex justify-between items-center p-2 rounded-lg hover:bg-white/5">
            <div>
              <span className="text-white text-sm">{city}</span>
              <span className="text-muted text-xs ml-2">{d.wins}/{d.total} wins</span>
            </div>
            <div className="flex items-center gap-3">
              <div className="w-20 bg-gray-700 rounded-full h-2">
                <div className="bg-primary rounded-full h-2" style={{ width: `${(d.total ? d.wins / d.total : 0) * 100}%` }} />
              </div>
              <span className={`font-mono text-sm ${d.pnl >= 0 ? 'text-success' : 'text-red-400'}`}>{d.pnl >= 0 ? '+' : ''}{d.pnl.toFixed(2)}</span>
            </div>
          </div>
        ))}
      </div>
    </div>
  );
}

function PerformanceChart({ markets }) {
  const [ReactRecharts, setLib] = useState(null);
  useEffect(() => { import('recharts').then(m => setLib(m)); }, []);
  
  const resolved = markets
    .filter(m => m.status === 'resolved' && m.position && m.event_end_date)
    .sort((a, b) => new Date(a.event_end_date) - new Date(b.event_end_date));

  let cumulative = 0;
  const chartData = resolved.map(m => {
    cumulative += m.pnl || 0;
    return { date: m.date, pnl: +(cumulative.toFixed(2)), city: m.city_name };
  });

  if (!ReactRecharts || chartData.length === 0) return null;
  const { LineChart, Line, XAxis, YAxis, Tooltip, ResponsiveContainer, CartesianGrid } = ReactRecharts;

  return (
    <div className="bg-card border border-border rounded-xl p-4 animate-fade-in">
      <h2 className="text-lg font-bold text-primary mb-3">Cumulative P&L</h2>
      <ResponsiveContainer width="100%" height={250}>
        <LineChart data={chartData}>
          <CartesianGrid strokeDasharray="3 3" stroke="#16213e" />
          <XAxis dataKey="date" stroke="#6c757d" tick={{ fontSize: 11 }} />
          <YAxis stroke="#6c757d" tick={{ fontSize: 11 }} />
          <Tooltip contentStyle={{ background: '#1a1a2e', border: '1px solid #16213e', borderRadius: 8 }}
            labelStyle={{ color: '#00b4d8' }} itemStyle={{ color: '#00ff88' }} />
          <Line type="monotone" dataKey="pnl" stroke="#00ff88" strokeWidth={2} dot={{ r: 3, fill: '#00ff88' }} />
        </LineChart>
      </ResponsiveContainer>
    </div>
  );
}

export default function App() {
  const { data: state } = useFetch('/state');
  const { data: perf } = useFetch('/performance');
  const { data: marketsData } = useFetch('/markets', 60000);
  const { data: openPosData } = useFetch('/open-positions', 60000);
  const markets = marketsData?.markets || [];
  const openMarkets = (openPosData?.markets || markets.filter(m => m.position && m.position.status === 'open'));

  if (!state) return <div className="flex items-center justify-center h-screen text-primary text-xl">Loading...</div>;

  const totalPnl = (perf?.totalPnl ?? state.realized_profits);
  const last24hPnl = perf?.last24hPnl ?? 0;
  const winRate = perf?.winRate ?? (state.total_trades ? (state.wins / state.total_trades * 100) : 0);
  const last24hWinRate = perf?.last24hWinRate ?? 0;

  return (
    <div className="min-h-screen bg-bg p-4 max-w-7xl mx-auto">
      {/* Header */}
      <div className="flex items-center gap-3 mb-6 animate-fade-in">
        <h1 className="text-2xl font-bold text-primary">Tempo-Bet v3.4</h1>
        <div className="flex items-center gap-1.5">
          <div className="w-2.5 h-2.5 rounded-full bg-success animate-pulse-live" />
          <span className="text-success text-xs font-semibold">LIVE</span>
        </div>
      </div>

      {/* Summary Cards */}
      <div className="grid grid-cols-2 sm:grid-cols-3 lg:grid-cols-6 gap-3 mb-6">
        <SummaryCard title="Total P&L" value={totalPnl} prefix="$" color={totalPnl >= 0 ? 'text-success' : 'text-red-400'} />
        <SummaryCard title="P&L 24h" value={last24hPnl} prefix="$" color={last24hPnl >= 0 ? 'text-success' : 'text-red-400'} />
        <SummaryCard title="Win Rate" value={winRate} suffix="%" color="text-primary" />
        <SummaryCard title="Win Rate 24h" value={last24hWinRate} suffix="%" color="text-primary" />
        <SummaryCard title="Open Positions" value={openMarkets.length} decimals={0} color="text-highlight" />
        <SummaryCard title="Balance" value={state.balance} prefix="$" color="text-success" />
      </div>

      {/* Open Positions */}
      <div className="mb-6">
        <h2 className="text-lg font-bold text-primary mb-3">Open Positions ({openMarkets.length})</h2>
        <div className="grid grid-cols-1 lg:grid-cols-2 gap-3">
          {openMarkets.map((m, i) => <OpenPositionCard key={i} market={m} />)}
          {openMarkets.length === 0 && <div className="text-muted text-sm bg-card border border-border rounded-xl p-6 text-center">No open positions</div>}
        </div>
      </div>

      {/* Charts */}
      <div className="mb-6">
        <PerformanceChart markets={markets} />
      </div>

      {/* Bottom grid */}
      <div className="grid grid-cols-1 lg:grid-cols-2 gap-3">
        <RecentTrades markets={markets} />
        <CityPerformance markets={markets} />
      </div>

      <div className="text-center text-muted text-xs mt-8 mb-4">Auto-refresh every 60s · Data from local bot files</div>
    </div>
  );
}
