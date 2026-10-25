#!/bin/bash
# Clutch — Google Calendar API setup via gcloud CLI
# Run these commands in Google Cloud Shell (https://shell.cloud.google.com)
# or any terminal with gcloud CLI authenticated.

set -e

# ── Configuration ──────────────────────────────────────
PROJECT_ID="clutch-radar"
PROJECT_NAME="Clutch Radar"
REGION="asia-south1"

# ── Step 1: Create project ─────────────────────────────
echo "=== Step 1: Create project ==="
gcloud projects create "$PROJECT_ID" --name="$PROJECT_NAME" 2>/dev/null || echo "Project already exists"
gcloud config set project "$PROJECT_ID"

# ── Step 2: Enable Calendar API ────────────────────────
echo "=== Step 2: Enable Calendar API ==="
gcloud services enable calendar-json.googleapis.com

# ── Step 3: Configure OAuth consent screen ─────────────
# This is required before creating OAuth credentials.
# Type: External (available to any Google account)
# Scopes: Google Calendar read/write
echo "=== Step 3: Configure OAuth consent screen ==="
echo "NOTE: OAuth consent screen must be configured via the console."
echo "Opening: https://console.cloud.google.com/apis/credentials/consent?project=$PROJECT_ID"
echo ""
echo "Set these values:"
echo "  User type:        External"
echo "  App name:         Clutch"
echo "  Support email:    (your email)"
echo "  Scopes:           Add .../auth/calendar"
echo "  Test users:       Add your Gmail address"
echo ""
echo "Press Enter after completing the consent screen setup..."
read -r

# ── Step 4: Create OAuth 2.0 credentials ──────────────
echo "=== Step 4: Create OAuth client ID ==="
gcloud auth application-default set-quota-project "$PROJECT_ID"

# Create OAuth client for desktop app
CLIENT_NAME="clutch-desktop"
echo "Creating OAuth client..."
gcloud alpha iap oauth-clients create "projects/$PROJECT_ID/brands/-" \
  --display_name="$CLIENT_NAME" 2>/dev/null || true

# If the above doesn't work (alpha command), create manually:
echo ""
echo "If the above command failed, create credentials manually:"
echo "  1. Go to: https://console.cloud.google.com/apis/credentials?project=$PROJECT_ID"
echo "  2. Click: + CREATE CREDENTIALS > OAuth client ID"
echo "  3. Application type: Desktop app"
echo "  4. Name: clutch-desktop"
echo "  5. Click: CREATE"
echo "  6. Click: DOWNLOAD JSON"
echo "  7. Save as: ~/.clutch/google_credentials.json"
echo ""
echo "Press Enter after downloading the credentials JSON..."
read -r

# ── Step 5: Verify ─────────────────────────────────────
echo "=== Step 5: Verify ==="
gcloud services list --enabled --filter="calendar" --project="$PROJECT_ID"
echo ""
echo "Done. Now on your local machine run:"
echo "  mkdir -p ~/.clutch"
echo "  # Copy the downloaded JSON to ~/.clutch/google_credentials.json"
echo "  clutch auth google"
