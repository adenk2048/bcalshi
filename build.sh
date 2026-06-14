#!/usr/bin/env bash
# Render runs this on every deploy. Exit immediately if any step fails.
set -o errexit

pip install -r requirements.txt
python manage.py collectstatic --no-input
python manage.py migrate

# Create the admin account from env vars if they're set, on first deploy.
# Safe to leave in: "|| true" so redeploys (user already exists) don't fail.
python manage.py createsuperuser --noinput || true
