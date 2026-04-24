import express from 'express';
import cors from 'cors';
import mattersRouter from './routes/matters';
import trustAccountsRouter from './routes/trustAccounts';
import transactionsRouter from './routes/transactions';
import reconciliationsRouter from './routes/reconciliations';
import statesRouter from './routes/states';

const app = express();
const PORT = process.env.PORT || 3001;

app.use(cors());
app.use(express.json());

// Health check
app.get('/api/health', (_req, res) => {
  res.json({ status: 'ok', service: 'Matter Funds API', timestamp: new Date().toISOString() });
});

// Routes
app.use('/api/matters', mattersRouter);
app.use('/api/trust-accounts', trustAccountsRouter);
app.use('/api/transactions', transactionsRouter);
app.use('/api/reconciliations', reconciliationsRouter);
app.use('/api/states', statesRouter);

// Dashboard summary is also accessible at top level
app.get('/api/dashboard', (_req, res) => {
  res.redirect('/api/states/dashboard/summary');
});

// 404 handler
app.use((_req, res) => {
  res.status(404).json({ success: false, error: 'Route not found' });
});

if (require.main === module) {
  app.listen(PORT, () => {
    console.log(`Matter Funds API running on port ${PORT}`);
  });
}

export default app;
