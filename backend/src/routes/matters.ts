import { Router, Request, Response } from 'express';
import { matterService } from '../services/dataService';
import { CreateMatterRequest, AustralianState, ApiResponse, Matter } from '../models/types';

const router = Router();

// GET /api/matters
router.get('/', (req: Request, res: Response) => {
  const { state } = req.query;
  let matters: Matter[];

  if (state && typeof state === 'string') {
    matters = matterService.getByState(state as AustralianState);
  } else {
    matters = matterService.getAll();
  }

  const response: ApiResponse<Matter[]> = { success: true, data: matters };
  res.json(response);
});

// GET /api/matters/:id
router.get('/:id', (req: Request, res: Response) => {
  const matter = matterService.getById(req.params.id);
  if (!matter) {
    const response: ApiResponse<null> = { success: false, error: 'Matter not found' };
    return res.status(404).json(response);
  }
  const response: ApiResponse<Matter> = { success: true, data: matter };
  return res.json(response);
});

// GET /api/matters/:id/ledger
router.get('/:id/ledger', (req: Request, res: Response) => {
  const ledger = matterService.getTrustLedger(req.params.id);
  if (!ledger) {
    const response: ApiResponse<null> = { success: false, error: 'Matter not found' };
    return res.status(404).json(response);
  }
  const response: ApiResponse<typeof ledger> = { success: true, data: ledger };
  return res.json(response);
});

// POST /api/matters
router.post('/', (req: Request, res: Response) => {
  const body = req.body as CreateMatterRequest;

  if (!body.matterNumber || !body.description || !body.clientName || !body.state) {
    const response: ApiResponse<null> = { success: false, error: 'Missing required fields' };
    return res.status(400).json(response);
  }

  const validStates: AustralianState[] = ['NSW', 'VIC', 'QLD', 'SA', 'WA', 'TAS', 'ACT', 'NT'];
  if (!validStates.includes(body.state)) {
    const response: ApiResponse<null> = { success: false, error: 'Invalid Australian state' };
    return res.status(400).json(response);
  }

  const matter = matterService.create(body);
  const response: ApiResponse<Matter> = { success: true, data: matter, message: 'Matter created successfully' };
  return res.status(201).json(response);
});

// PATCH /api/matters/:id
router.patch('/:id', (req: Request, res: Response) => {
  const matter = matterService.update(req.params.id, req.body as Partial<Matter>);
  if (!matter) {
    const response: ApiResponse<null> = { success: false, error: 'Matter not found' };
    return res.status(404).json(response);
  }
  const response: ApiResponse<Matter> = { success: true, data: matter };
  return res.json(response);
});

// DELETE /api/matters/:id
router.delete('/:id', (req: Request, res: Response) => {
  const deleted = matterService.delete(req.params.id);
  if (!deleted) {
    const response: ApiResponse<null> = { success: false, error: 'Matter not found' };
    return res.status(404).json(response);
  }
  const response: ApiResponse<null> = { success: true, message: 'Matter deleted' };
  return res.json(response);
});

export default router;
