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

