import { Router, Request, Response } from 'express';
import { transactionService } from '../services/dataService';
import { CreateTransactionRequest, ApiResponse, Transaction } from '../models/types';

const router = Router();

// GET /api/transactions
router.get('/', (req: Request, res: Response) => {
  const { matterId, trustAccountId } = req.query;

  let txns: Transaction[];
  if (matterId && typeof matterId === 'string') {
    txns = transactionService.getByMatter(matterId);
  } else if (trustAccountId && typeof trustAccountId === 'string') {
    txns = transactionService.getByTrustAccount(trustAccountId);
  } else {
    txns = transactionService.getAll();
  }

  const response: ApiResponse<Transaction[]> = { success: true, data: txns };
  res.json(response);
});

// GET /api/transactions/:id
router.get('/:id', (req: Request, res: Response) => {
  const txn = transactionService.getById(req.params.id);
  if (!txn) {
    const response: ApiResponse<null> = { success: false, error: 'Transaction not found' };
    return res.status(404).json(response);
  }
  const response: ApiResponse<Transaction> = { success: true, data: txn };
  return res.json(response);
});

// POST /api/transactions
router.post('/', (req: Request, res: Response) => {
  const body = req.body as CreateTransactionRequest;

  if (!body.matterId || !body.trustAccountId || !body.type || !body.amount || !body.date) {
    const response: ApiResponse<null> = { success: false, error: 'Missing required fields' };
    return res.status(400).json(response);
  }

  if (body.amount <= 0) {
    const response: ApiResponse<null> = { success: false, error: 'Amount must be greater than zero' };
    return res.status(400).json(response);
  }

  const validTypes = ['deposit', 'withdrawal', 'transfer', 'bank_fee', 'interest'];
  if (!validTypes.includes(body.type)) {
    const response: ApiResponse<null> = { success: false, error: 'Invalid transaction type' };
    return res.status(400).json(response);
  }

  const result = transactionService.create(body);
  if ('error' in result) {
    const response: ApiResponse<null> = { success: false, error: result.error };
    return res.status(400).json(response);
  }

  const response: ApiResponse<Transaction> = {
    success: true,
    data: result,
    message: 'Transaction created successfully',
  };
  return res.status(201).json(response);
});

// PATCH /api/transactions/:id/status
router.patch('/:id/status', (req: Request, res: Response) => {
  const { status } = req.body as { status: Transaction['status'] };
  const validStatuses = ['pending', 'cleared', 'reconciled', 'reversed'];

  if (!status || !validStatuses.includes(status)) {
    const response: ApiResponse<null> = { success: false, error: 'Invalid status' };
    return res.status(400).json(response);
  }

  const txn = transactionService.updateStatus(req.params.id, status);
  if (!txn) {
    const response: ApiResponse<null> = { success: false, error: 'Transaction not found' };
    return res.status(404).json(response);
  }

  const response: ApiResponse<Transaction> = { success: true, data: txn };
  return res.json(response);
});

// POST /api/transactions/:id/reverse
router.post('/:id/reverse', (req: Request, res: Response) => {
  const { reason } = req.body as { reason: string };

  if (!reason) {
    const response: ApiResponse<null> = { success: false, error: 'Reversal reason is required' };
    return res.status(400).json(response);
  }

  const result = transactionService.reverse(req.params.id, reason);
  if ('error' in result) {
    const response: ApiResponse<null> = { success: false, error: result.error };
    return res.status(400).json(response);
  }

  const response: ApiResponse<Transaction> = {
    success: true,
    data: result,
    message: 'Transaction reversed successfully',
  };
  return res.json(response);
});

export default router;
