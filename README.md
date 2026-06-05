# Clariva — Backend

Django 5 REST API for school management: CBT exams, fees, grades, timetables, attendance, and parent portal.

## Stack

- **Django 5.x** + **Django REST Framework 3.15**
- **PostgreSQL** (SQLite in development)
- **JWT auth** via `djangorestframework-simplejwt`
- School-isolated multi-tenant design via `SchoolFilterMixin`

## Project structure

```
apps/
├── accounts/     # User model, registration, JWT login, student login
├── schools/      # School model, onboarding, grading config
├── students/     # Student profiles, class groups
├── classes/      # Class groups, arms, year groups
├── staff/        # Teacher/staff profiles
├── exams/        # CBT engine, subjects, timetables, report cards
│   ├── models.py     # Exam, Question, ExamSession, Subject, ReportCard
│   ├── views.py      # ViewSets with @action endpoints
│   ├── parsers.py    # DOCX question bank parser (stdlib zipfile + ElementTree)
│   ├── serializers.py
│   └── tests.py      # 26 tests (parser + API + grading)
├── fees/         # Fee items (with ARM-level pricing), invoices
├── grades/       # CA1/CA2/assignment/exam scores, grading config
├── attendance/   # Daily attendance records
├── guardian/     # Parent/guardian portal (lookup, login, children)
├── locations/    # States, LGAs (school onboarding)
└── comms/        # Announcements
```

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
| `DATABASE_URL` | `sqlite:///db.sqlite3` | Connection string (postgres:// or sqlite://) |
| `CORS_ALLOWED_ORIGINS` | `http://localhost:3000` | Comma-separated C origins |
| `ALLOWED_HOSTS` | `localhost,127.0.0.1` | Django allowed hosts |

## Key API endpoints

| Endpoint | Description |
|---|---|
| `POST /api/auth/login/` | Email + password login, returns JWT |
| `POST /api/auth/student-login/` | Student ID + password login |
| `POST /api/exams/exams/{id}/start/` | Start/resume exam session |
| `GET /api/exams/exams/{id}/questions/` | Questions in session order |
| `POST /api/exams/sessions/{id}/submit/` | Submit answers, server-side grading |
| `POST /api/exams/exams/{id}/upload_questions/` | Upload DOCX question bank |
| `POST /api/exams/exams/{id}/duplicate/` | Clone exam + questions |
| `POST /api/portal/lookup/` | Public student record by code |

## CBT engine

- **Start** — creates/returns active session, shuffles question order if enabled, returns elapsed-aware `time_remaining` for resuming students, enforces `start_time`/`end_time` window.
- **Questions** — returns questions in session order with per-student option shuffling (seeded by session ID). `correct_answer` is stripped for student role.
- **Submit** — server-side grading with case-insensitive comparison. MCQ letter answers (A-D) are resolved to option text for backward compatibility. `tab_switches` and `late_submission` saved.
- **DOCX parser** — stdlib-only (no lxml). Header metadata, MCQ letter-to-text resolution, True/False, Short Answer.

## Permissions

- Write operations on exams/questions require `school_admin`, `principal`, `teacher`, or `super_admin` roles.
- Students can only start, read questions, and submit sessions.
- `SchoolFilterMixin` applies automatic school-scoping on all ViewSets.

## Tests

```bash
python manage.py test apps.exams.tests
```

26 tests covering DOCX parsing, upload API, start/submit/grading flows, edge cases.

## Scripts

| Command | Description |
|---|---|
| `python manage.py runserver` | Development server |
| `python manage.py test` | Run all tests |
| `python manage.py makemigrations` | Create model migrations |
| `python manage.py migrate` | Apply migrations |
