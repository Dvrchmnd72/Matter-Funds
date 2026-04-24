# MatterFunds — Australian Legal Trust Account Platform

A comprehensive legal trust account management platform for **all 8 Australian states and territories**.

## Overview

MatterFunds provides law firms with a complete trust accounting solution that complies with the trust accounting requirements of every Australian jurisdiction:

| State/Territory | Regulatory Body | Legislation |
|---|---|---|
| **NSW** | NSW Law Society | Legal Profession Uniform Law 2014 |
| **VIC** | Victorian Legal Services Board | Legal Profession Uniform Law Application Act 2014 |
| **QLD** | Queensland Law Society | Legal Profession Act 2007 (Qld) |
| **SA** | Law Society of South Australia | Legal Practitioners Act 1981 (SA) |
| **WA** | Legal Practice Board of WA | Legal Profession Act 2008 (WA) |
| **TAS** | Law Society of Tasmania | Legal Profession Act 2007 (Tas) |
| **ACT** | ACT Law Society | Legal Profession Uniform Law Application Act 2014 (ACT) |
| **NT** | Law Society Northern Territory | Legal Profession Act 2006 (NT) |

## Features

- 📁 **Matter Management** — Create and manage legal matters by state, client, matter type and responsible solicitor
- 🏦 **Trust Accounts** — Maintain separate trust accounts for each Australian state at approved ADIs
- 💸 **Trust Ledger** — Per-matter trust ledger showing all receipts, payments and running balance
- 🔄 **Monthly Reconciliation** — Reconcile trust ledger against bank statements as required by law
- 📊 **Dashboard** — Overview of all trust funds, matters, and transactions across all states
- ✅ **Compliance Guidance** — State-specific trust accounting rules and regulations
- 🔁 **Transaction Reversals** — Reverse transactions with audit trail
- 🔍 **Search & Filter** — Filter matters and transactions by state, type, status

## Architecture

```
matter-funds/
├── backend/          # Node.js + Express REST API (TypeScript)
│   ├── src/
│   │   ├── models/   # Data types and Australian state definitions
│   │   ├── routes/   # REST API endpoints
│   │   └── services/ # Business logic & in-memory data store
│   └── package.json
├── frontend/         # React + TypeScript SPA
│   ├── src/
│   │   ├── pages/    # Dashboard, Matters, TrustAccounts, Transactions, etc.
│   │   ├── utils/    # API client, formatting utilities
│   │   └── types/    # TypeScript type definitions
│   └── package.json
└── README.md
```

## Getting Started

### Prerequisites
- Node.js 18+
- npm 8+

### Installation

```bash
# Install all dependencies
npm run install:all
```

### Running (Development)

```bash
# Start the backend API (port 3001)
npm run dev:backend

# In another terminal, start the frontend (port 3000)
npm run dev:frontend
```

Open [http://localhost:3000](http://localhost:3000) in your browser.

### Running Tests

```bash
# Run all tests (backend + frontend)
npm test

# Backend tests only (20 tests)
npm test --prefix backend

# Frontend tests only (11 tests)
npm test --prefix frontend
```

### Building for Production

```bash
npm run build
```

## API Reference

The REST API is available at `http://localhost:3001/api/`.

| Endpoint | Description |
|---|---|
| `GET /api/health` | Health check |
| `GET /api/states` | All Australian states with compliance info |
| `GET /api/states/:code` | Single state info (e.g. `/api/states/NSW`) |
| `GET /api/states/dashboard/summary` | Dashboard statistics |
| `GET /api/matters` | List matters (filter with `?state=NSW`) |
| `POST /api/matters` | Create a new matter |
| `GET /api/matters/:id` | Get matter details |
| `PATCH /api/matters/:id` | Update matter |
| `GET /api/matters/:id/ledger` | Get trust ledger for a matter |
| `GET /api/trust-accounts` | List trust accounts |
| `POST /api/trust-accounts` | Create a trust account |
| `GET /api/transactions` | List transactions |
| `POST /api/transactions` | Record a transaction (deposit/withdrawal) |
| `POST /api/transactions/:id/reverse` | Reverse a transaction |
| `GET /api/reconciliations` | List reconciliations |
| `POST /api/reconciliations` | Create a reconciliation |
| `POST /api/reconciliations/:id/approve` | Approve a reconciliation |

## Trust Accounting Compliance

Australian trust accounting law requires:

1. **Separate accounts** — Client funds must be kept separate from office funds
2. **Trust ledger** — A separate trust ledger entry for each matter
3. **Monthly reconciliation** — Trust bank balance reconciled with trust ledger each month
4. **Annual audit** — Independent external audit of trust records required annually
5. **Record retention** — Trust records must be kept for a minimum of 7 years
6. **Authorised withdrawals** — Withdrawals only when entitled with proper authorisation
7. **Trust receipts** — Receipts issued for all trust money received

## Matter Types Supported

- Conveyancing
- Family Law
- Commercial
- Litigation
- Estate
- Criminal
- Immigration
- Employment
- Other

