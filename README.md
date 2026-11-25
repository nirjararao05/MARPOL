# MARPOL-SAFE | Shipping Operations Demo

A Streamlit demonstration for shipboard environmental records, review workflows, evidence attachments, screening prompts, audit history, reporting, and a searchable MARPOL reference index. The application uses **MongoDB** for operational data and keeps uploaded evidence files in a local `evidence_store/` directory.

## Requirements

- Python 3.10 or newer
- A reachable MongoDB server (local MongoDB Community Server or MongoDB Atlas)
- VS Code or another Python editor

## Setup on Windows

1. Extract the ZIP and open the `MARPOL-SAFE-Shipping-Demo` folder in VS Code.
2. Open a terminal in that folder and create a virtual environment:

   ```powershell
   py -m venv .venv
   .\.venv\Scripts\python.exe -m pip install -r requirements.txt
   ```

3. Start your MongoDB server. For a local MongoDB installation, the default connection is `mongodb://localhost:27017`. For MongoDB Atlas, copy your deployment connection string.
4. Set the connection details in the same PowerShell terminal. For local MongoDB:

   ```powershell
   $env:MONGODB_URI="mongodb://localhost:27017"
   $env:MONGODB_DATABASE="marpol_safe"
   ```

   For Atlas, use your Atlas connection string as the `MONGODB_URI` value. Keep credentials private; do not commit them to GitHub.

5. Import the existing demo data from the SQLite database included with this ZIP:

   ```powershell
   .\.venv\Scripts\python.exe migrate_sqlite_to_mongodb.py
   ```

   The migration imports the `records`, `alerts`, `audit`, `attachments`, `vessel_profile`, and `library_items` tables as MongoDB collections. It preserves their existing `id` values. The importer stops rather than overwriting non-empty collections. Use `--replace` only when you deliberately want to delete and replace those six collections.

6. Start the application:

   ```powershell
   .\.venv\Scripts\python.exe -m streamlit run app.py
   ```

7. Open the local address printed in the terminal, usually `http://localhost:8501`. Keep the terminal open while using the app; press **Ctrl+C** to stop it.

The application connects using `MONGODB_URI` and `MONGODB_DATABASE`. When these variables are not set, it uses the local defaults above. A blank MongoDB database is initialized with the demo vessel profile and sample data automatically.

## Demo sign-ins

| Role | Username | Password |
|---|---|---|
| Admin | `admin` | `admin123` |
| Chief Engineer | `chief` | `marpol123` |
| Officer | `officer` | `marpol123` |
| Cadet | `cadet` | `marpol123` |

These are hard-coded demo accounts for local use only.

## MongoDB structure

The app stores data in these collections:

- `records` — shipboard operational records and approval status.
- `alerts` — screening prompts and resolution status.
- `audit` — user actions and review history.
- `attachments` — evidence file metadata linked to records.
- `vessel_profile` — vessel identity and voyage profile.
- `library_items` — MARPOL reference summaries and company guidance.
- `counters` — atomic integer ID allocation for the app's displayed IDs.

The MongoDB collections contain operational data and attachment metadata. The evidence file bytes remain in `evidence_store/`; back up that folder together with MongoDB.

## Project files

- `app.py` — Streamlit UI and MongoDB-backed application logic.
- `migrate_sqlite_to_mongodb.py` — one-time importer for the legacy SQLite database.
- `marpol_safe.db` — original SQLite source retained only for migration/backup; the running application does not read or write it.
- `assets/` — local SVG ship illustrations.
- `evidence_store/` — created beside the app when a user uploads evidence.
- `.env.example` — example MongoDB environment variables (copy values into your shell or deployment environment; the app does not load `.env` automatically).

## MARPOL Library scope

The library contains summaries of Annexes I–VI and links to IMO pages. These summaries are navigation aids, not the full legal text. Follow current IMO publications, supplements, and the vessel's approved procedures when checking requirements. The demo does not automatically synchronize amendments.

## Demonstration limitations

This is a local sales-demo prototype, not a production shipboard service or legal compliance determination. Demo GPS coordinates are simulated; alerts are review prompts; and the queue action only changes a MongoDB flag. It is not connected to vessel equipment, a company identity provider, or a shore server. Demo passwords are stored in plaintext in the application.

Before using operational data, add managed identity, password hashing, company/vessel tenancy, authorization review, secure evidence storage, backups, synchronization controls, and operational/regulatory validation. Do not expose this prototype directly to the public internet.
