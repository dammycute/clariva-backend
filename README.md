# Clariva — Backend

Django 5 REST API for school management: CBT exams, fees, grades, timetables, attendance, and parent portal.

## Stack

- **Django 5.x** + **Django REST Framework 3.15**
- **PostgreSQL 15** (SQLite in development)
- **JWT auth** via `djangorestframework-simplejwt`
- **Fernet encryption** for PII fields
- School-isolated multi-tenant design via `SchoolFilterMixin`

## Project structure

```
apps/
├── accounts/     # Custom User model (UUID pk, email auth), JWT login, student login
├── schools/      # School model, onboarding, grading config, backup/restore
├── students/     # Student profiles, CSV import, bulk account creation
├── classes/      # Class groups, arms, year groups
├── staff/        # Teacher/staff profiles, CSV import
├── exams/        # CBT engine, subjects, questions, exam sessions
├── timetable/    # TimeTable, TimeSlot, publish/unpublish
├── results/      # ReportCard, release/unrelease, generate
├── fees/         # Fee items (ARM-level pricing), invoices
├── grades/       # CA1/CA2/assignment/exam scores, grading config
├── attendance/   # Daily attendance records
├── guardian/     # Parent/guardian portal (lookup, OTP login, children)
├── locations/    # States, LGAs (school onboarding)
├── comms/        # Announcements
├── audit/        # Automatic activity logging (post_save/post_delete signals)
└── base/         # BaseUUIDModel, encryption helpers
```

URL prefixes (mounted in `config/urls.py`):

| Prefix | App |
|---|---|
| `/api/auth/` | accounts |
| `/api/schools/` | schools (CRUD + backup/restore/grading) |
| `/api/students/` | students |
| `/api/staff/` | staff |
| `/api/classes/` | classes |
| `/api/exams/` | exams (subjects, questions, sessions) |
| `/api/timetable/` | timetable |
| `/api/results/` | results (report cards) |
| `/api/fees/` | fees |
| `/api/grades/` | grades |
| `/api/attendance/` | attendance |
| `/api/portal/` | guardian |
| `/api/comms/` | comms |
| `/api/audit/` | audit |
| `/api/locations/` | locations |

## Getting started

```bash
cp .env.example .env
pip install -r requirements.txt
python manage.py migrate
python manage.py runserver
```

API runs at [http://localhost:8000/api/](http://localhost:8000/api/).

### Environment

| Variable | Default | Description |
|---|---|---|
| `SECRET_KEY` | `dev-secret-key-...` | Django secret key |
| `DEBUG` | `True` | Debug mode |
| `DATABASE_URL` | `postgres://user:password@localhost:5432/clariva` | Connection string (postgres:// or sqlite://) |
| `CORS_ALLOWED_ORIGINS` | `http://localhost:3000` | Comma-separated C origins |

## Key API endpoints

| Endpoint | Description |
|---|---|
| `POST /api/auth/login/` | Email + password login, returns JWT |
| `POST /api/auth/student-login/` | Student ID + password login |
| `POST /api/exams/exams/{id}/start/` | Start/resume exam session |
| `GET /api/exams/exams/{id}/questions/` | Questions in session order |
| `POST /api/exams/sessions/{id}/submit/` | Submit answers, server-side grading |
| `POST /api/exams/exams/{id}/upload_questions/` | Upload DOCX question bank |
| `POST /api/schools/backup/` | Export school data (IsSchoolAdminRole) |
| `POST /api/schools/restore/` | Restore school data (confirm=true required) |
| `GET/PUT /api/schools/{id}/grading/` | Grading config (GET: any auth, PUT: admin) |
| `POST /api/timetable/timetables/{id}/publish/` | Publish timetable (admin only) |
| `POST /api/results/report-cards/{id}/release/` | Release report card (principal only) |
| `POST /api/portal/lookup/` | Public student record by code |

## Multi-tenant architecture

- `SchoolFilterMixin` scopes every ViewSet queryset to `request.user.school`
- Suspended schools are rejected at the mixin level
- `super_admin` has no school; passes `?school_id=` to target a specific school
- `IsSchoolAdminRole` gates write operations (backup, restore, grading PUT/PATCH, publish, release)

## Permissions

| Operation | Required role |
|---|---|
| Read (GET) | Any authenticated user in the school |
| Write (POST/PUT/PATCH/DELETE) | `school_admin`, `principal`, `admin_officer`, `teacher` |
| Backup/Restore | `school_admin` or `super_admin` |
| Grading config (PUT/PATCH) | `school_admin` or `super_admin` |
| Report card release/unrelease | `principal` or `super_admin` |
| Timetable publish/unpublish | `school_admin` or `super_admin` |

## Tests

```bash
# All tests (99 tests)
python manage.py test

# Specific apps
python manage.py test apps.exams.tests
python manage.py test apps.schools.tests
python manage.py test apps.results.tests
python manage.py test apps.timetable.tests
```

Test coverage spans: DOCX parsing, CBT start/submit/grading, tenant scoping (schools, students, results, timetable), authorization gates (backup, restore, grading, release, publish), and audit signal robustness.

## CI

GitHub Actions workflow (`.github/workflows/ci.yml`) runs on push/PR to main:
- Python 3.10 + PostgreSQL 15
- Migrations check (`makemigrations --check --dry-run`)
- System check + full test suite
