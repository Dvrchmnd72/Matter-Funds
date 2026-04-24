export function formatCurrency(amount: number): string {
  return new Intl.NumberFormat('en-AU', {
    style: 'currency',
    currency: 'AUD',
  }).format(amount);
}

export function formatDate(dateStr: string): string {
  if (!dateStr) return '';
  const date = new Date(dateStr);
  return new Intl.DateTimeFormat('en-AU', {
    day: '2-digit',
    month: '2-digit',
    year: 'numeric',
  }).format(date);
}

export function formatDatetime(dateStr: string): string {
  if (!dateStr) return '';
  const date = new Date(dateStr);
  return new Intl.DateTimeFormat('en-AU', {
    day: '2-digit',
    month: '2-digit',
    year: 'numeric',
    hour: '2-digit',
    minute: '2-digit',
  }).format(date);
}

export function getMatterTypeLabel(type: string): string {
  const labels: Record<string, string> = {
    conveyancing: 'Conveyancing',
    family_law: 'Family Law',
    commercial: 'Commercial',
    litigation: 'Litigation',
    estate: 'Estate',
    criminal: 'Criminal',
    immigration: 'Immigration',
    employment: 'Employment',
    other: 'Other',
  };
  return labels[type] ?? type;
}

export function getTransactionTypeLabel(type: string): string {
  const labels: Record<string, string> = {
    deposit: 'Deposit',
    withdrawal: 'Withdrawal',
    transfer: 'Transfer',
    bank_fee: 'Bank Fee',
    interest: 'Interest',
  };
  return labels[type] ?? type;
}

export function getStatusColor(status: string): string {
  const colors: Record<string, string> = {
    active: '#22c55e',
    closed: '#6b7280',
    archived: '#9ca3af',
    pending: '#f59e0b',
    cleared: '#3b82f6',
    reconciled: '#22c55e',
    reversed: '#ef4444',
    draft: '#f59e0b',
    completed: '#3b82f6',
    approved: '#22c55e',
  };
  return colors[status] ?? '#6b7280';
}

export function getTransactionColor(type: string): string {
  const isCredit = type === 'deposit' || type === 'interest';
  return isCredit ? '#22c55e' : '#ef4444';
}
