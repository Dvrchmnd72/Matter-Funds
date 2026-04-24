import { Router, Request, Response } from 'express';
import { trustAccountService } from '../services/dataService';
import { CreateTrustAccountRequest, AustralianState, ApiResponse, TrustAccount } from '../models/types';

const router = Router();

// GET /api/trust-accounts
router.get('/', (req: Request, res: Response) => {
  const { state } = req.query;
  let accounts: TrustAccount[];

  if (state && typeof state === 'string') {
    accounts = trustAccountService.getByState(state as AustralianState);
  } else {
    accounts = trustAccountService.getAll();
  }

  const response: ApiResponse<TrustAccount[]> = { success: true, data: accounts };
  res.json(response);
});

// GET /api/trust-accounts/:id
router.get('/:id', (req: Request, res: Response) => {
  const account = trustAccountService.getById(req.params.id);
  if (!account) {
    const response: ApiResponse<null> = { success: false, error: 'Trust account not found' };
    return res.status(404).json(response);
  }
  const response: ApiResponse<TrustAccount> = { success: true, data: account };
  return res.json(response);
});

// POST /api/trust-accounts
router.post('/', (req: Request, res: Response) => {
  const body = req.body as CreateTrustAccountRequest;

  if (!body.accountName || !body.bsb || !body.accountNumber || !body.bankName || !body.state) {
    const response: ApiResponse<null> = { success: false, error: 'Missing required fields' };
    return res.status(400).json(response);
  }

  const validStates: AustralianState[] = ['NSW', 'VIC', 'QLD', 'SA', 'WA', 'TAS', 'ACT', 'NT'];
  if (!validStates.includes(body.state)) {
    const response: ApiResponse<null> = { success: false, error: 'Invalid Australian state' };
    return res.status(400).json(response);
  }

  const account = trustAccountService.create(body);
  const response: ApiResponse<TrustAccount> = {
    success: true,
    data: account,
    message: 'Trust account created successfully',
  };
  return res.status(201).json(response);
});

// PATCH /api/trust-accounts/:id
router.patch('/:id', (req: Request, res: Response) => {
  const account = trustAccountService.update(req.params.id, req.body as Partial<TrustAccount>);
  if (!account) {
    const response: ApiResponse<null> = { success: false, error: 'Trust account not found' };
    return res.status(404).json(response);
  }
  const response: ApiResponse<TrustAccount> = { success: true, data: account };
  return res.json(response);
});

export default router;
