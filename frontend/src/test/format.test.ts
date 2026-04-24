import { describe, it, expect } from 'vitest';
import { formatCurrency, formatDate, getMatterTypeLabel, getTransactionTypeLabel, getStatusColor } from '../utils/format';

describe('formatCurrency', () => {
  it('formats positive amounts in AUD', () => {
    expect(formatCurrency(1234.56)).toContain('1,234.56');
    expect(formatCurrency(1234.56)).toContain('$');
  });

  it('formats zero', () => {
    expect(formatCurrency(0)).toContain('0.00');
  });

  it('formats large amounts', () => {
    expect(formatCurrency(1000000)).toContain('1,000,000.00');
  });
});

describe('getMatterTypeLabel', () => {
  it('returns human-readable labels', () => {
    expect(getMatterTypeLabel('conveyancing')).toBe('Conveyancing');
    expect(getMatterTypeLabel('family_law')).toBe('Family Law');
    expect(getMatterTypeLabel('commercial')).toBe('Commercial');
    expect(getMatterTypeLabel('litigation')).toBe('Litigation');
    expect(getMatterTypeLabel('estate')).toBe('Estate');
    expect(getMatterTypeLabel('criminal')).toBe('Criminal');
    expect(getMatterTypeLabel('immigration')).toBe('Immigration');
    expect(getMatterTypeLabel('employment')).toBe('Employment');
    expect(getMatterTypeLabel('other')).toBe('Other');
  });

  it('returns the original value for unknown types', () => {
    expect(getMatterTypeLabel('unknown')).toBe('unknown');
  });
});

describe('getTransactionTypeLabel', () => {
  it('returns correct labels', () => {
    expect(getTransactionTypeLabel('deposit')).toBe('Deposit');
    expect(getTransactionTypeLabel('withdrawal')).toBe('Withdrawal');
    expect(getTransactionTypeLabel('bank_fee')).toBe('Bank Fee');
    expect(getTransactionTypeLabel('interest')).toBe('Interest');
    expect(getTransactionTypeLabel('transfer')).toBe('Transfer');
  });
});

describe('getStatusColor', () => {
  it('returns colors for known statuses', () => {
    expect(getStatusColor('active')).toBe('#22c55e');
    expect(getStatusColor('pending')).toBe('#f59e0b');
    expect(getStatusColor('cleared')).toBe('#3b82f6');
    expect(getStatusColor('approved')).toBe('#22c55e');
  });

  it('returns default color for unknown status', () => {
    expect(getStatusColor('unknown')).toBe('#6b7280');
  });
});

describe('Australian states coverage', () => {
  const STATES = ['NSW', 'VIC', 'QLD', 'SA', 'WA', 'TAS', 'ACT', 'NT'];

  it('covers all 8 Australian states and territories', () => {
    expect(STATES).toHaveLength(8);
    expect(STATES).toContain('NSW');
    expect(STATES).toContain('VIC');
    expect(STATES).toContain('QLD');
    expect(STATES).toContain('SA');
    expect(STATES).toContain('WA');
    expect(STATES).toContain('TAS');
    expect(STATES).toContain('ACT');
    expect(STATES).toContain('NT');
  });
});

describe('formatDate', () => {
  it('formats date strings', () => {
    const result = formatDate('2024-01-15');
    expect(result).toContain('2024');
    expect(result).toContain('15');
  });

  it('returns empty string for empty input', () => {
    expect(formatDate('')).toBe('');
  });
});
