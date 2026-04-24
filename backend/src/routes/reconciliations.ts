import { Router, Request, Response } from 'express';
import { reconciliationService } from '../services/dataService';
import { CreateReconciliationRequest, ApiResponse, Reconciliation } from '../models/types';

const router = Router();

// GET /api/reconciliations
router.get('/', (req: Request, res: Response) => {
  const { trustAccountId } = req.query;
  let recs: Reconciliation[];

  if (trustAccountId && typeof trustAccountId === 'string') {
    recs = reconciliationService.getByTrustAccount(trustAccountId);
  } else {
    recs = reconciliationService.getAll();
  }

  const response: ApiResponse<Reconciliation[]> = { success: true, data: recs };
  res.json(response);
});

// GET /api/reconciliations/:id
router.get('/:id', (req: Request, res: Response) => {
  const rec = reconciliationService.getById(req.params.id);
  if (!rec) {
    const response: ApiResponse<null> = { success: false, error: 'Reconciliation not found' };
    return res.status(404).json(response);
  }
  const response: ApiResponse<Reconciliation> = { success: true, data: rec };
  return res.json(response);
});

// POST /api/reconciliations
router.post('/', (req: Request, res: Response) => {
  const body = req.body as CreateReconciliationRequest;

  if (!body.trustAccountId || !body.periodStart || !body.periodEnd || body.bankStatementBalance === undefined) {
    const response: ApiResponse<null> = { success: false, error: 'Missing required fields' };
    return res.status(400).json(response);
  }

  const result = reconciliationService.create(body);
  if ('error' in result) {
    const response: ApiResponse<null> = { success: false, error: result.error };
    return res.status(400).json(response);
  }

  const response: ApiResponse<Reconciliation> = {
    success: true,
    data: result,
    message: 'Reconciliation created successfully',
  };
  return res.status(201).json(response);
});

// POST /api/reconciliations/:id/approve
router.post('/:id/approve', (req: Request, res: Response) => {
  const { approvedBy } = req.body as { approvedBy: string };

  if (!approvedBy) {
    const response: ApiResponse<null> = { success: false, error: 'approvedBy is required' };
    return res.status(400).json(response);
  }

  const rec = reconciliationService.approve(req.params.id, approvedBy);
  if (!rec) {
    const response: ApiResponse<null> = { success: false, error: 'Reconciliation not found' };
    return res.status(404).json(response);
  }

  const response: ApiResponse<Reconciliation> = {
    success: true,
    data: rec,
    message: 'Reconciliation approved',
  };
  return res.json(response);
});

export default router;
