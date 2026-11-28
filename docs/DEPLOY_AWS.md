# Putting the backend on AWS (production)

Use **Amazon ECS Express Mode**. (AWS App Runner stopped taking new customers on 30 April 2026.)
Prices, regions and console screens change, so check them in AWS as you go.

## Before you start
- Two-step sign-in on the AWS root account, a separate admin user, and a **budget alert**.
- Pick a region. Cape Town (`af-south-1`) must be enabled in the account first. Check ECS Express Mode is offered there.
- Production gets its **own** database and its **own** secrets. Never point it at the test database.

## 1. Database
Create **RDS for PostgreSQL**: not publicly accessible, automated backups on, deletion protection on.
Allow port 5432 only from the service's security group.

## 2. Secrets
Put these in **AWS Secrets Manager** and give them to the service as environment variables.

Make a new `SECRET_KEY`, `FERNET_KEYS` and `LOOKUP_HASH_KEY` for production. Run this once for each:

```bash
python -c "import secrets; print(secrets.token_urlsafe(50))"
```

**Back up `FERNET_KEYS` somewhere safe.** It unlocks the encrypted fields. If it is lost, that data cannot be read.
If you ever copy data from another database, you must use that database's key.

## 3. Settings

| Name | Production value |
|---|---|
| `DEBUG` | `False` |
| `SECRET_KEY`, `FERNET_KEYS`, `LOOKUP_HASH_KEY` | the new secrets, each one different |
| `DATABASE_URL` | `postgres://USER:PASSWORD@HOST:5432/DBNAME` (the port is required; URL-encode symbols in the password) |
| `DB_SSLMODE` | `require` |
| `CACHE_BACKEND` | `db` |
| `ALLOWED_HOSTS` | `api.clarriva.com` |
| `CORS_ALLOWED_ORIGINS` | `https://clarriva.com,https://www.clarriva.com` |
| `PLATFORM_DOMAIN` | `clarriva.com` (school addresses under it are allowed automatically) |
| `NUM_PROXIES` | `2` for Cloudflare plus the load balancer. Check that rate limits see real visitor addresses. |
| `SECURE_SSL_REDIRECT` | `True` |
| `ENABLE_ADMIN` | `False` |
| `RESEND_API_KEY`, `DEMO_NOTIFY_EMAIL`, `DEMO_FROM_EMAIL`, `BILLING_FROM_EMAIL` | your email settings |
| `PAYSTACK_SECRET_KEY`, `PAYSTACK_PUBLIC_KEY`, `PAYSTACK_SIGNING_SECRET` | test keys first |
| `PAYSTACK_CALLBACK_URL` | `https://clarriva.com/dashboard/billing` |
| `BILLING_CRON_SECRET` | a long random value |
| `BILLING_ENFORCE` | `False` until the checks at the end are done |

## 4. Build and publish the container
Create an **ECR** repository, then follow its "View push commands" button. They amount to:

```bash
docker build --platform linux/amd64 -t clarriva-api .
```

## 5. The service
Create an **ECS Express Mode** service from that image: container port `8000`, health check path `/health/`.
`/health/` answers the load balancer even though it calls by IP address.

## 6. First release, and every release after
Run these as **one-off ECS tasks** using the same image and settings.

Every release, before the new version takes traffic:

```bash
python manage.py migrate
```

First time only. This loads the states that signup and billing need, and is safe to run again:

```bash
python manage.py seed_locations
```

First time only, your platform admin account. `createsuperuser` alone is not enough: the console also needs the role.

```bash
python manage.py createsuperuser
```

```bash
python manage.py shell -c "from apps.accounts.models import User; print(User.objects.filter(username='YOUR_USERNAME').update(role='super_admin'))"
```

## 7. Domain and HTTPS
- Request a certificate for `api.clarriva.com` in **AWS Certificate Manager**, in the same region.
- Attach it to the load balancer.
- In Cloudflare DNS, point `api` at the load balancer. Set SSL/TLS to **Full (strict)**.

## 8. Billing reminders
`vercel.json` schedules do not run on AWS. Use **EventBridge Scheduler** to run an ECS task once a day (06:00 UTC):

```bash
python manage.py billing_reminders
```

## 9. Website
In the Cloudflare **build** settings set `NEXT_PUBLIC_API_URL=https://api.clarriva.com/api` and
`NEXT_PUBLIC_PLATFORM_DOMAIN=clarriva.com`, then rebuild. These values are fixed at build time.

## Checks before real schools and real money
1. `https://api.clarriva.com/health/` says healthy.
2. From `https://clarriva.com`: sign in works, and the demo form sends an email.
3. State term dates are entered in the admin console.
4. A Paystack **test** payment works, and a test webhook from the Paystack dashboard is accepted
   (webhook address: `https://api.clarriva.com/api/billing/webhook/`).
5. Every existing school has a covering period with a student count.
6. Restore a database backup once, to prove it works.

Only then use live Paystack keys and set `BILLING_ENFORCE=True`.
