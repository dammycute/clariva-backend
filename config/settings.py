import sys
import os
from pathlib import Path
from decouple import config, Csv

BASE_DIR = Path(__file__).resolve().parent.parent

SECRET_KEY = config('SECRET_KEY', default=None)
DEBUG = config('DEBUG', default=False, cast=bool)

if not SECRET_KEY:
    if DEBUG:
        SECRET_KEY = 'django-insecure-dev-only-key-not-for-production'
    else:
        from django.core.exceptions import ImproperlyConfigured
        raise ImproperlyConfigured('SECRET_KEY environment variable is required in production')

# Keys the fingerprints used to find access codes. Kept apart from SECRET_KEY so that
# changing SECRET_KEY never stops codes from being found.
LOOKUP_HASH_KEY = config('LOOKUP_HASH_KEY', default='')
if not LOOKUP_HASH_KEY:
    if DEBUG or sys.argv[1:2] == ['test']:
        LOOKUP_HASH_KEY = 'dev-only-lookup-key-not-for-production'
    else:
        from django.core.exceptions import ImproperlyConfigured
        raise ImproperlyConfigured('LOOKUP_HASH_KEY environment variable is required in production')

FERNET_KEYS = config('FERNET_KEYS', default=None)
if FERNET_KEYS:
    FERNET_KEYS = [k.strip() for k in FERNET_KEYS.split(',') if k.strip()]
ALLOWED_HOSTS = config('ALLOWED_HOSTS', default='localhost,127.0.0.1', cast=Csv())
# A host is a bare name like api.example.com. Forgive a pasted URL: drop the scheme and any path.
ALLOWED_HOSTS = [h.split('://', 1)[-1].split('/', 1)[0] for h in ALLOWED_HOSTS if h]
# Vercel sets these on every deployment (from Vercel itself, not from the request):
# the deployment's own host, the branch host, and the project's production host.
for _name in ('VERCEL_URL', 'VERCEL_BRANCH_URL', 'VERCEL_PROJECT_PRODUCTION_URL'):
    _host = config(_name, default='')
    if _host and _host not in ALLOWED_HOSTS:
        ALLOWED_HOSTS = [*ALLOWED_HOSTS, _host]

INSTALLED_APPS = [
    'django.contrib.admin',
    'django.contrib.auth',
    'django.contrib.contenttypes',
    'django.contrib.sessions',
    'django.contrib.messages',
    'django.contrib.staticfiles',
    # Third-party
    'rest_framework',
    'corsheaders',
    'rest_framework_simplejwt.token_blacklist',
    'fernet_fields',
    # Local apps
    'apps.accounts',
    'apps.schools.apps.SchoolsConfig',
    'apps.students',
    'apps.classes',
    'apps.staff',
    'apps.fees',
    'apps.locations',
    'apps.attendance',
    'apps.grades',
    'apps.exams',
    'apps.timetable',
    'apps.results',
    'apps.comms',
    'apps.audit',
    'apps.guardian',
    'apps.leads',
    'apps.billing',
]

MIDDLEWARE = [
    # First: the load balancer's health check must be answered before host and HTTPS checks.
    'config.health.HealthCheckMiddleware',
    'corsheaders.middleware.CorsMiddleware',
    'django.middleware.security.SecurityMiddleware',
    'django.contrib.sessions.middleware.SessionMiddleware',
    'django.middleware.common.CommonMiddleware',
    'django.middleware.csrf.CsrfViewMiddleware',
    'django.contrib.auth.middleware.AuthenticationMiddleware',
    'apps.audit.signals.RequestMiddleware',
    'django.contrib.messages.middleware.MessageMiddleware',
    'django.middleware.clickjacking.XFrameOptionsMiddleware',
]

ROOT_URLCONF = 'config.urls'

TEMPLATES = [{
    'BACKEND': 'django.template.backends.django.DjangoTemplates',
    'DIRS': [],
    'APP_DIRS': True,
    'OPTIONS': {
        'context_processors': [
            'django.template.context_processors.debug',
            'django.template.context_processors.request',
            'django.contrib.auth.context_processors.auth',
            'django.contrib.messages.context_processors.messages',
        ],
    },
}]

WSGI_APPLICATION = 'config.wsgi.application'

# Database
import re
from urllib.parse import unquote
db_url = config('DATABASE_URL', default='sqlite:///db.sqlite3')
if db_url.startswith('sqlite'):
    DATABASES = {'default': {'ENGINE': 'django.db.backends.sqlite3', 'NAME': BASE_DIR / 'db.sqlite3'}}
else:
    match = re.match(r'postgres(?:ql)?://(.+):(.+)@(.+):(\d+)/(.+)', db_url)
    if not match:
        from django.core.exceptions import ImproperlyConfigured
        raise ImproperlyConfigured('DATABASE_URL must be sqlite:///... or postgres://user:pass@host:port/name')
    if match:
            DATABASES = {
                'default': {
                    'ENGINE': 'django.db.backends.postgresql',
                    'NAME': match.group(5),
                    'USER': unquote(match.group(1)),
                    'PASSWORD': unquote(match.group(2)),
                    'HOST': match.group(3),
                    'PORT': match.group(4),
                    'OPTIONS': {'sslmode': config('DB_SSLMODE', default='prefer' if DEBUG else 'require')},
                    # Set DB_POOLED=true when connecting through a transaction pooler
                    # (for example Supabase port 6543), which cannot keep server-side cursors.
                    'DISABLE_SERVER_SIDE_CURSORS': config('DB_POOLED', default=False, cast=bool),
                }
            }

# Cache. The portal OTP codes and the rate-limit counters live here. The default
# in-memory cache is per process, so on serverless hosts (Vercel) or with several
# workers set CACHE_BACKEND=db to share them through the database instead.
if config('CACHE_BACKEND', default='locmem') == 'db':
    CACHES = {'default': {'BACKEND': 'django.core.cache.backends.db.DatabaseCache', 'LOCATION': 'django_cache'}}
else:
    CACHES = {'default': {'BACKEND': 'django.core.cache.backends.locmem.LocMemCache'}}

# The Django admin site needs static files, which serverless hosts do not serve.
# It is on in development and off in production unless ENABLE_ADMIN=true.
ENABLE_ADMIN = config('ENABLE_ADMIN', default=DEBUG, cast=bool)

AUTH_PASSWORD_VALIDATORS = [
    {'NAME': 'django.contrib.auth.password_validation.UserAttributeSimilarityValidator'},
    {'NAME': 'django.contrib.auth.password_validation.MinimumLengthValidator', 'OPTIONS': {'min_length': 8}},
    {'NAME': 'django.contrib.auth.password_validation.CommonPasswordValidator'},
    {'NAME': 'django.contrib.auth.password_validation.NumericPasswordValidator'},
]

LANGUAGE_CODE = 'en-us'
TIME_ZONE = 'Africa/Lagos'
USE_I18N = True
USE_TZ = True

STATIC_URL = 'static/'
DEFAULT_AUTO_FIELD = 'django.db.models.BigAutoField'

AUTH_USER_MODEL = 'accounts.User'

AUTHENTICATION_BACKENDS = [
    'apps.accounts.auth_backends.EmailAuthBackend',
    'django.contrib.auth.backends.ModelBackend',
]

# Production hardening
if not DEBUG:
    SECURE_SSL_REDIRECT = config('SECURE_SSL_REDIRECT', default=True, cast=bool)
    SECURE_PROXY_SSL_HEADER = ('HTTP_X_FORWARDED_PROTO', 'https')
    SESSION_COOKIE_SECURE = True
    CSRF_COOKIE_SECURE = True
    SECURE_HSTS_SECONDS = 31536000
    SECURE_HSTS_INCLUDE_SUBDOMAINS = True
    SECURE_HSTS_PRELOAD = True
SECURE_CONTENT_TYPE_NOSNIFF = True
X_FRAME_OPTIONS = 'DENY'

# Demo requests from the landing page are emailed through Resend. Without the key the
# request is still saved; only the email is skipped. DEMO_NOTIFY_EMAIL takes a
# comma-separated list; when it is empty the platform admins are emailed instead.
RESEND_API_KEY = config('RESEND_API_KEY', default='')
DEMO_NOTIFY_EMAIL = config('DEMO_NOTIFY_EMAIL', default='')
DEMO_FROM_EMAIL = config('DEMO_FROM_EMAIL', default='Clarriva <onboarding@resend.dev>')

# Billing (apps.billing). Ship dark: BILLING_ENFORCE stays false until every existing
# school has been covered, then it is switched on per environment.
BILLING_ENFORCE = config('BILLING_ENFORCE', default=False, cast=bool)
PAYSTACK_SECRET_KEY = config('PAYSTACK_SECRET_KEY', default='')
PAYSTACK_PUBLIC_KEY = config('PAYSTACK_PUBLIC_KEY', default='')
# The webhook signing secret (whsec_...). Separate from the secret key on purpose.
PAYSTACK_SIGNING_SECRET = config('PAYSTACK_SIGNING_SECRET', default='')
PAYSTACK_CALLBACK_URL = config('PAYSTACK_CALLBACK_URL', default='')
BILLING_CRON_SECRET = config('BILLING_CRON_SECRET', default='')
CRON_SECRET = config('CRON_SECRET', default='')     # the name Vercel's scheduler uses
BILLING_FROM_EMAIL = config('BILLING_FROM_EMAIL', default=DEMO_FROM_EMAIL)

# The domain the product runs on. A school's own portal is
# <subdomain>.<PLATFORM_DOMAIN>, so staff sign in at their school's address
# instead of coming through the base site first.
PLATFORM_DOMAIN = config('PLATFORM_DOMAIN', default='clarriva.com')

# CORS
CORS_ALLOWED_ORIGINS = config('CORS_ALLOWED_ORIGINS', default='http://localhost:3000', cast=Csv())
CORS_ALLOW_CREDENTIALS = True
# Every school address under the platform domain, such as https://queens.clarriva.com.
CORS_ALLOWED_ORIGIN_REGEXES = (
    [r'^https://[a-z0-9-]+\.' + PLATFORM_DOMAIN.replace('.', r'\.') + r'$'] if PLATFORM_DOMAIN else []
)

# A test run must never send real email or call Paystack, whatever is in .env.
if len(sys.argv) > 1 and sys.argv[1] == 'test':
    RESEND_API_KEY = PAYSTACK_SECRET_KEY = PAYSTACK_SIGNING_SECRET = ''
    BILLING_ENFORCE = False                   # tests that need the gate switch it on themselves

# DRF
REST_FRAMEWORK = {
    'DEFAULT_AUTHENTICATION_CLASSES': (
        'apps.accounts.authentication.SessionJWTAuthentication',
    ),
    'DEFAULT_PERMISSION_CLASSES': (
        'rest_framework.permissions.IsAuthenticated',
    ),
    'DEFAULT_PAGINATION_CLASS': 'apps.mixins.CustomPagination',
    'PAGE_SIZE': 200,
    'DEFAULT_RENDERER_CLASSES': (
        'rest_framework.renderers.JSONRenderer',
    ),
    'DEFAULT_THROTTLE_CLASSES': (
        'rest_framework.throttling.AnonRateThrottle',
        'rest_framework.throttling.UserRateThrottle',
    ),
    'DEFAULT_THROTTLE_RATES': {
        'anon': '30/minute',
        'user': '60/minute',
        'otp': '5/minute',
        'auth': '10/minute',
        'demo': '5/hour',
    },
    # Number of trusted reverse proxies, so throttles see the real client IP.
    'NUM_PROXIES': config('NUM_PROXIES', default=0, cast=int),
    'EXCEPTION_HANDLER': 'config.exceptions.custom_exception_handler',
}

# SimpleJWT
from datetime import timedelta
SIMPLE_JWT = {
    'ACCESS_TOKEN_LIFETIME': timedelta(hours=2),
    'REFRESH_TOKEN_LIFETIME': timedelta(days=7),
    'ROTATE_REFRESH_TOKENS': True,
    'BLACKLIST_AFTER_ROTATION': True,
    'AUTH_HEADER_TYPES': ('Bearer',),
    'TOKEN_OBTAIN_SERIALIZER': 'apps.accounts.serializers.EmailTokenObtainPairSerializer',
}

# Logging
LOGGING = {
    'version': 1,
    'disable_existing_loggers': False,
    'formatters': {
        'verbose': {
            'format': '{levelname} {asctime} {module} {message}',
            'style': '{',
        },
        'simple': {
            'format': '{levelname} {message}',
            'style': '{',
        },
    },
    'handlers': {
        'console': {
            'class': 'logging.StreamHandler',
            'formatter': 'simple',
        },
    },
    'root': {
        'handlers': ['console'],
        'level': 'WARNING',
    },
    'loggers': {
        'django': {
            'handlers': ['console'],
            'level': 'WARNING' if not DEBUG else 'INFO',
            'propagate': False,
        },
        'apps': {
            'handlers': ['console'],
            'level': 'DEBUG' if DEBUG else 'INFO',
            'propagate': False,
        },
    },
}
