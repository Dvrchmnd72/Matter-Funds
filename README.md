# Matter Funds

Trust account software for Australian legal practices, built with Django 4.2 + PostgreSQL.

---

## PythonAnywhere Deployment Guide

### 1 — Clone the repository

Open a **Bash console** on PythonAnywhere and run:

```bash
git clone https://github.com/Dvrchmnd72/Matter-Funds.git ~/matter-funds
cd ~/matter-funds
```

### 2 — Create and activate a virtual environment

```bash
python3 -m venv venv
source venv/bin/activate
```

### 3 — Install dependencies

```bash
pip install --upgrade pip
pip install -r requirements.txt
```

### 4 — Create your `.env` file

```bash
cp .env.example .env
nano .env   # or use the PythonAnywhere file editor
```

Fill in every `CHANGE_ME` value:

| Variable | Where to find it |
|---|---|
| `DJANGO_SECRET_KEY` | Generate: `python -c "from django.core.management.utils import get_random_secret_key; print(get_random_secret_key())"` |
| `DJANGO_DEBUG` | `False` in production |
| `DJANGO_ALLOWED_HOSTS` | Your domain(s), comma-separated |
| `DB_NAME` | Your Postgres database name |
| `DB_USER` | Your Postgres role name |
| `DB_PASSWORD` | Your Postgres password |
| `DB_HOST` | From PythonAnywhere **Databases** tab (e.g. `Settlex-4321.postgres.pythonanywhere-services.com`) |
| `DB_PORT` | From PythonAnywhere **Databases** tab — **NOT 5432** (e.g. `14321`) |

### 5 — Run migrations

```bash
python manage.py migrate
```

### 6 — Create a superuser

```bash
python manage.py createsuperuser
```

### 7 — Collect static files

```bash
python manage.py collectstatic --noinput
```

Static files will be written to `staticfiles/`.

### 8 — Configure the WSGI file on PythonAnywhere

In the PythonAnywhere **Web** tab:
1. Add a new web app → **Manual configuration** → Python 3.10 (or your version).
2. Set the **source code** directory to `/home/<username>/matter-funds`.
3. Set the **virtualenv** path to `/home/<username>/matter-funds/venv`.
4. Click the **WSGI configuration file** link and replace its entire contents with:

```python
import os
import sys

path = '/home/<username>/matter-funds'
if path not in sys.path:
    sys.path.insert(0, path)

os.environ['DJANGO_SETTINGS_MODULE'] = 'matterfunds.settings.production'

from django.core.wsgi import get_wsgi_application
application = get_wsgi_application()
```

Replace `<username>` with your PythonAnywhere username.

### 9 — Reload the web app

Click **Reload** on the Web tab. Your site should now be live.

---

## Local development

```bash
# Use development settings (SQLite, DEBUG=True)
export DJANGO_SETTINGS_MODULE=matterfunds.settings.development
python manage.py migrate
python manage.py runserver
```

---

## Tech stack

- **Django 4.2** — web framework
- **PostgreSQL** + psycopg2 — production database
- **python-decouple** — environment variable management
- **WhiteNoise** — static file serving
- **Gunicorn** — WSGI server
- **django-allauth** — authentication (ready to configure)
- **crispy-forms** + crispy-bootstrap5 — form rendering

- **reportlab** — PDF generation
- **openpyxl** — Excel export

---

## Compliance mapping (NSW)

This phase implements the Legal Profession Uniform General Rules 2015 (NSW) as
described in the Law Society of NSW Legal Accounting Handbook (8th Ed., Jan 2020).

| Rule | Where it lives |
|------|----------------|
| R36–R38 Receipts | apps/trust/models.py::Receipt + services.create_receipt |
| R39 Trust journals | apps/trust/models.py::TrustJournal + services.create_trust_journal |
| R41 Banking timing | Receipt.late_banking flag |
| R42 Irregularities | apps/trust/models.py::Irregularity (auto-created on failed recon) |
| R43–R45 Payments | apps/trust/models.py::Payment + services.create_payment |
| R45 Trust ledger | apps/trust/models.py::MatterLedger |
| R47 Monthly recon | apps/trust/models.py::MonthlyReconciliation |
| R50–R54 Controlled money | apps/trust/models.py::ControlledMoneyAccount |
| R55 Transit money | apps/trust/models.py::TransitMoneyEntry |
| R56 Power money | apps/trust/models.py::PowerMoneyEntry |
| R53 7-year retention | Soft-delete only; hard-delete forbidden in admin |
| R66–R75 External examiner | apps/trust/reports.py::external_examiner_pack_zip |

Other Australian states (VIC, QLD, WA, SA, TAS, ACT, NT) will be added in later phases.
The `Firm.jurisdiction` field is the future hook for state-specific rule sets.
