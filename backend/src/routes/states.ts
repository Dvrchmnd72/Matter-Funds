import { Router, Request, Response } from 'express';
import { statsService } from '../services/dataService';
import { AUSTRALIAN_STATES, AustralianState, ApiResponse } from '../models/types';

const router = Router();

// GET /api/states
router.get('/', (_req: Request, res: Response) => {
  const response: ApiResponse<typeof AUSTRALIAN_STATES> = { success: true, data: AUSTRALIAN_STATES };
  res.json(response);
});

// GET /api/states/:code
router.get('/:code', (req: Request, res: Response) => {
  const code = req.params.code.toUpperCase() as AustralianState;
  const stateInfo = AUSTRALIAN_STATES[code];

  if (!stateInfo) {
    const response: ApiResponse<null> = { success: false, error: 'State not found' };
    return res.status(404).json(response);
  }

  const response: ApiResponse<typeof stateInfo> = { success: true, data: stateInfo };
  return res.json(response);
});

// GET /api/dashboard
router.get('/dashboard/summary', (_req: Request, res: Response) => {
  const data = statsService.getDashboard();
  const response: ApiResponse<typeof data> = { success: true, data };
  res.json(response);
});

export default router;
