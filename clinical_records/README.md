# Clinical Diagnosis and Treatment Records System
**DSCI 551 – Database Internals · Spring 2026**  
Diana Rulanova & Eliza Loke

A PostgreSQL-backed command-line application that demonstrates B-tree indexing, composite indexes, MVCC, and row-level locking in the context of a clinical records system.

---

## Prerequisites

| Requirement | Version |
|---|---|
| PostgreSQL | 14 or later |
| Python | 3.9 or later |
| psycopg2-binary | installed via pip |

---

## Setup

### 1 · Create the database

```bash
psql -U postgres -c "CREATE DATABASE clinical_db;"
```

### 2 · Edit connection settings

Open `config.py` and update with your PostgreSQL credentials:

```python
DB_CONFIG = {
    "dbname": "clinical_db",
    "user": "postgres",
    "password": "YOUR_PASSWORD",
    "host": "localhost",
    "port": "5432",
}
```

### 3 · Install Python dependencies

```bash
pip install -r requirements.txt
```

### 4 · Create tables and indexes

```bash
psql -U postgres -d clinical_db -f schema.sql
```

### 5 · Generate synthetic dataset

```bash
python generate_data.py
```

This inserts ~1 000 patients, 50 providers, 10 000 encounters, ~20 000 diagnoses, and ~35 000 treatments.

### 6 · Run the application

```bash
python app.py
```

---

## Application Operations

| Option | Feature | PostgreSQL Internal |
|---|---|---|
| 1 | Lookup diagnoses by code | B-tree index scan vs sequential scan |
| 2 | Patient encounter history | Composite index, skip-sort |
| 3 | Concurrent treatment update | MVCC / READ COMMITTED |
| 4 | Row-level locking demo | SELECT FOR UPDATE |
| 5 | Monthly diagnosis summary | Hash join + HashAggregate |

---

## Project Structure

```
clinical_records/
├── config.py           # Database connection settings
├── schema.sql          # Table definitions and indexes
├── generate_data.py    # Synthetic dataset generator
├── app.py              # Main CLI application
├── requirements.txt
└── README.md
```

---

## Internal Focus Areas

### B-Tree Indexing (Diana Rulanova)
- `idx_diagnoses_code` on `diagnoses(diagnosis_code)` — demonstrates Index Scan vs Bitmap Heap Scan vs Sequential Scan.
- `idx_encounters_patient_date` on `encounters(patient_id, encounter_date)` — demonstrates composite index prefix matching and sort elimination.
- All execution plans shown live via `EXPLAIN (ANALYZE, BUFFERS)`.

### MVCC & Row-Level Locking (Eliza Loke)
- Two concurrent connections update the same treatment row; session 2 reads the old committed version before session 1 commits (no dirty reads).
- `SELECT FOR UPDATE` demo shows explicit row-level locking and blocking behaviour.

