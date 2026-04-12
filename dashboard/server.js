import express from 'express';
import path from 'path';
import fs from 'fs';
import { fileURLToPath } from 'url';

const __dirname = path.dirname(fileURLToPath(import.meta.url));
const DATA_DIR = path.resolve(__dirname, '../data');
const app = express();
const PORT = 3001;

// Serve React build
app.use(express.static(path.join(__dirname, 'dist')));

// Cache for Polymarket prices
let priceCache = {};
let lastPriceFetch = 0;

async function fetchPolymarketPrice(marketId) {
  if (!marketId) return null;
  if (priceCache[marketId] && Date.now() - lastPriceFetch < 300000) return priceCache[marketId];
  try {
    const r = await fetch(`https://gamma-api.polymarket.com/markets/${marketId}`);
    if (r.ok) {
      const data = await r.json();
      const price = parseFloat(data.outcomePrices?.[0] || data.bestBid || 0);
      priceCache[marketId] = price;
      lastPriceFetch = Date.now();
      return price;
    }
  } catch {}
  return priceCache[marketId] || null;
}

function readJSON(filepath) {
  try { return JSON.parse(fs.readFileSync(filepath, 'utf-8')); } catch { return null; }
}

function loadMarkets() {
  const dir = path.join(DATA_DIR, 'markets');
  if (!fs.existsSync(dir)) return [];
  return fs.readdirSync(dir)
    .filter(f => f.endsWith('.json'))
    .map(f => readJSON(path.join(dir, f)))
    .filter(Boolean);
}

// API routes
app.get('/api/state', (req, res) => {
  const state = readJSON(path.join(DATA_DIR, 'state.json'));
  res.json(state || {});
});

app.get('/api/markets', (req, res) => {
  res.json({ markets: loadMarkets() });
});

app.get('/api/open-positions', async (req, res) => {
  const markets = loadMarkets().filter(m => m.position && m.position.status === 'open');
  const enriched = await Promise.all(markets.map(async m => {
    if (m.position?.market_id) {
      const price = await fetchPolymarketPrice(m.position.market_id);
      m.position.currentPrice = price;
    }
    return m;
  }));
  res.json({ markets: enriched });
});

app.get('/api/performance', (req, res) => {
  const state = readJSON(path.join(DATA_DIR, 'state.json')) || {};
  const markets = loadMarkets().filter(m => m.status === 'resolved' && m.position);
  const now = Date.now();
  const day24 = 24 * 60 * 60 * 1000;
  const last24 = markets.filter(m => new Date(m.event_end_date) > now - day24);

  const winRate = markets.length ? markets.filter(m => m.pnl > 0).length / markets.length * 100 : 0;
  const last24hWinRate = last24.length ? last24.filter(m => m.pnl > 0).length / last24.length * 100 : 0;
  const last24hPnl = last24.reduce((s, m) => s + (m.pnl || 0), 0);

  res.json({
    totalPnl: state.realized_profits || 0,
    winRate,
    last24hPnl,
    last24hWinRate,
    totalTrades: markets.length,
    wins: markets.filter(m => m.pnl > 0).length,
    losses: markets.filter(m => m.pnl <= 0).length,
  });
});

app.get('/api/calibration', (req, res) => {
  const cal = readJSON(path.join(DATA_DIR, 'calibration.json'));
  res.json(cal || {});
});

// SPA fallback
app.get('*', (req, res) => {
  const indexPath = path.join(__dirname, 'dist', 'index.html');
  if (fs.existsSync(indexPath)) {
    res.sendFile(indexPath);
  } else {
    res.status(404).send('Dashboard not built. Run: npm run build');
  }
});

app.listen(PORT, () => {
  console.log(`Tempo-Bet Dashboard running on http://localhost:${PORT}`);
});
