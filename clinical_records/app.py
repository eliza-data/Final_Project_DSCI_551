import psycopg2
import psycopg2.extras
import threading
import time

from config import DB_CONFIG


def get_connection():
    return psycopg2.connect(**DB_CONFIG)


# ── Operation 1: Lookup diagnoses by diagnosis code ──────────────────────────
# This demonstrates B-tree index scan vs sequential scan

def lookup_diagnosis_by_code(conn):
    print("\n" + "="*60)
    print("OPERATION 1: Lookup Diagnoses by Code")
    print("Internal focus: B-Tree Index Scan vs Sequential Scan")
    print("="*60)

    code = input("\nEnter diagnosis code (e.g. G43, J45, E11, I10): ").strip().upper()
    if not code:
        code = "G43"

    query = """
        SELECT diagnosis_id, diagnosis_code, description
        FROM diagnoses
        WHERE diagnosis_code = %s
    """

    print("\n[APPLICATION] Searching for diagnoses with code:", code)
    print("\n[SQL QUERY]")
    print("    SELECT diagnosis_id, diagnosis_code, description")
    print("    FROM diagnoses")
    print("    WHERE diagnosis_code = %s")

    # Show execution plan WITH the index (normal behavior)
    print("\n--- EXPLAIN ANALYZE with B-tree index ---")
    cur = conn.cursor()
    cur.execute("EXPLAIN (ANALYZE, BUFFERS) " + query, (code,))
    rows = cur.fetchall()
    for row in rows:
        print("   ", row[0])

    print("\n[EXPLANATION]")
    print("PostgreSQL uses idx_diagnoses_code (B-tree index) to find matching rows.")
    print("It does a Bitmap Index Scan to collect matching heap pointers,")
    print("then a Bitmap Heap Scan to read only the relevant pages.")
    print("This avoids reading rows that don't match the condition.")

    # Disable index to show what happens without it (for comparison)
    print("\n--- EXPLAIN ANALYZE without index (forced Sequential Scan) ---")
    cur.execute("SET enable_indexscan = off")
    cur.execute("SET enable_bitmapscan = off")
    cur.execute("EXPLAIN (ANALYZE, BUFFERS) " + query, (code,))
    rows = cur.fetchall()
    for row in rows:
        print("   ", row[0])
    cur.execute("SET enable_indexscan = on")
    cur.execute("SET enable_bitmapscan = on")

    print("\n[EXPLANATION]")
    print("Without the index, PostgreSQL has to scan every row in the table.")
    print("You can see 'Rows Removed by Filter' which shows the wasted work.")
    print("Compare the Execution Time between the two plans above.")

    # Show actual results
    print("\n--- Results ---")
    cur2 = conn.cursor(cursor_factory=psycopg2.extras.DictCursor)
    cur2.execute(query + " LIMIT 10", (code,))
    results = cur2.fetchall()

    if results:
        print(f"Found diagnoses for code '{code}' (showing first 10):")
        for r in results:
            print(f"  ID: {r['diagnosis_id']}  |  Code: {r['diagnosis_code']}  |  {r['description']}")
    else:
        print(f"No diagnoses found for code '{code}'")

    cur.close()
    cur2.close()
    input("\nPress Enter to go back to the menu...")


# ── Operation 2: Get patient encounter history ordered by date ────────────────
# This demonstrates composite B-tree index (patient_id, encounter_date)

def get_encounter_history(conn):
    print("\n" + "="*60)
    print("OPERATION 2: Patient Encounter History")
    print("Internal focus: Composite Index, Skip Sort")
    print("="*60)

    patient_id = input("\nEnter patient ID (1-1000): ").strip()
    if not patient_id.isdigit():
        patient_id = "10"
    patient_id = int(patient_id)

    query = """
        SELECT encounter_id, patient_id, encounter_date, chief_complaint
        FROM encounters
        WHERE patient_id = %s
        ORDER BY encounter_date DESC
        LIMIT 10
    """

    print(f"\n[APPLICATION] Getting encounter history for patient #{patient_id}")
    print("\n[SQL QUERY]")
    print("    SELECT encounter_id, patient_id, encounter_date, chief_complaint")
    print("    FROM encounters")
    print("    WHERE patient_id = %s")
    print("    ORDER BY encounter_date DESC")
    print("    LIMIT 10")

    print("\n--- EXPLAIN ANALYZE ---")
    cur = conn.cursor()
    cur.execute("EXPLAIN (ANALYZE, BUFFERS) " + query, (patient_id,))
    rows = cur.fetchall()
    for row in rows:
        print("   ", row[0])

    print("\n[EXPLANATION]")
    print("The composite index idx_encounters_patient_date is on (patient_id, encounter_date).")
    print("PostgreSQL uses 'Index Scan Backward' - it scans the index in reverse")
    print("to get encounter_date in descending order.")
    print("There is NO Sort node in the plan because the index already stores")
    print("data sorted by (patient_id, encounter_date).")
    print("This is the key benefit of composite indexes - they can satisfy")
    print("both the WHERE filter and the ORDER BY in one index traversal.")

    print("\n--- Results ---")
    cur2 = conn.cursor(cursor_factory=psycopg2.extras.DictCursor)
    cur2.execute(query, (patient_id,))
    results = cur2.fetchall()

    if results:
        print(f"Encounter history for patient #{patient_id}:")
        for r in results:
            print(f"  Encounter {r['encounter_id']}  |  Date: {r['encounter_date']}  |  {r['chief_complaint']}")
    else:
        print(f"No encounters found for patient #{patient_id}")

    cur.close()
    cur2.close()
    input("\nPress Enter to go back to the menu...")


# ── Operation 3: Concurrent update to show MVCC behavior ─────────────────────
# Two sessions update the same row at the same time
# Session 2 should see the OLD value while Session 1 hasn't committed yet

def mvcc_demo():
    print("\n" + "="*60)
    print("OPERATION 3: Concurrent Update - MVCC Demo")
    print("Internal focus: Multi-Version Concurrency Control")
    print("="*60)

    print("\n[APPLICATION] Two clinical staff update the same treatment record.")
    print("Isolation level: READ COMMITTED (PostgreSQL default)")
    print("\nWhat will happen:")
    print("  Session 1 updates a row but does NOT commit right away (waits 3s)")
    print("  Session 2 reads the same row BEFORE Session 1 commits")
    print("  -> Session 2 should see the OLD committed value (MVCC)")
    print("  After Session 1 commits, Session 2 reads again")
    print("  -> Now Session 2 sees the NEW value")

    # Get a treatment row to work with
    conn_temp = get_connection()
    cur = conn_temp.cursor()
    cur.execute("SELECT treatment_id, outcome FROM treatments LIMIT 1")
    treatment_id, original_outcome = cur.fetchone()
    cur.close()
    conn_temp.close()

    print(f"\nTarget row: treatment_id = {treatment_id}, current outcome = '{original_outcome}'")
    input("\nPress Enter to start the demo...")

    # Events to coordinate the two threads
    session1_updated = threading.Event()
    session1_committed = threading.Event()
    results = {}

    def session1():
        conn = get_connection()
        conn.autocommit = False
        cur = conn.cursor()

        print("\n[SESSION 1] BEGIN transaction")
        cur.execute(
            "UPDATE treatments SET outcome = %s WHERE treatment_id = %s",
            ("Improved", treatment_id)
        )
        print("[SESSION 1] UPDATE outcome -> 'Improved'  (not committed yet)")
        session1_updated.set()

        # Wait before committing so Session 2 can read first
        time.sleep(3)
        conn.commit()
        session1_committed.set()
        print("[SESSION 1] COMMIT")

        cur.close()
        conn.close()

    def session2():
        # Wait for Session 1 to update but not commit
        session1_updated.wait()

        conn = get_connection()
        conn.autocommit = False
        cur = conn.cursor()

        # Read BEFORE Session 1 commits
        cur.execute(
            "SELECT outcome FROM treatments WHERE treatment_id = %s",
            (treatment_id,)
        )
        value_before = cur.fetchone()[0]
        results["before"] = value_before
        print(f"\n[SESSION 2] Read BEFORE Session 1 commits -> outcome = '{value_before}'")
        print("[MVCC] Session 2 sees the last committed version, not the in-progress update")

        # Wait for Session 1 to commit
        session1_committed.wait()

        # Read AFTER Session 1 commits
        cur.execute(
            "SELECT outcome FROM treatments WHERE treatment_id = %s",
            (treatment_id,)
        )
        value_after = cur.fetchone()[0]
        results["after"] = value_after
        print(f"\n[SESSION 2] Read AFTER Session 1 commits  -> outcome = '{value_after}'")
        print("[MVCC] READ COMMITTED: each statement sees the latest committed data")

        conn.commit()
        cur.close()
        conn.close()

    t1 = threading.Thread(target=session1)
    t2 = threading.Thread(target=session2)
    t1.start()
    t2.start()
    t1.join()
    t2.join()

    print("\n--- MVCC Summary ---")
    print(f"Before Session 1 commit: Session 2 saw '{results.get('before')}'")
    print(f"After  Session 1 commit: Session 2 saw '{results.get('after')}'")
    print("\n[EXPLANATION]")
    print("PostgreSQL stores multiple versions of each row (xmin/xmax).")
    print("When Session 1 updates, it creates a new row version.")
    print("The old version stays visible to other transactions until they")
    print("start a new statement after the commit.")
    print("This means readers never block writers and writers never block readers.")

    # Reset the row back to original value
    conn_reset = get_connection()
    cur_reset = conn_reset.cursor()
    cur_reset.execute(
        "UPDATE treatments SET outcome = %s WHERE treatment_id = %s",
        (original_outcome, treatment_id)
    )
    conn_reset.commit()
    cur_reset.close()
    conn_reset.close()

    input("\nPress Enter to go back to the menu...")


# ── Operation 4: Row-level locking with SELECT FOR UPDATE ─────────────────────

def locking_demo():
    print("\n" + "="*60)
    print("OPERATION 4: Row-Level Locking - SELECT FOR UPDATE")
    print("Internal focus: Explicit row locks, blocking writes")
    print("="*60)

    print("\n[APPLICATION] A clinician locks a treatment record before updating.")
    print("This prevents another session from modifying the same row at the same time.")
    print("\nWhat will happen:")
    print("  Session 1 locks the row with SELECT FOR UPDATE and holds it 4 seconds")
    print("  Session 2 tries to UPDATE the same row -> gets BLOCKED")
    print("  Session 1 commits -> lock is released")
    print("  Session 2 unblocks and completes the update")

    conn_temp = get_connection()
    cur = conn_temp.cursor()
    cur.execute("SELECT treatment_id FROM treatments LIMIT 1 OFFSET 1")
    treatment_id = cur.fetchone()[0]
    cur.close()
    conn_temp.close()

    print(f"\nTarget row: treatment_id = {treatment_id}")
    input("\nPress Enter to start the demo...")

    lock_acquired = threading.Event()

    def session1():
        conn = get_connection()
        conn.autocommit = False
        cur = conn.cursor()

        print("\n[SESSION 1] Locking row with SELECT FOR UPDATE...")
        cur.execute(
            "SELECT outcome FROM treatments WHERE treatment_id = %s FOR UPDATE",
            (treatment_id,)
        )
        lock_acquired.set()
        print("[SESSION 1] Row locked. Holding lock for 4 seconds...")

        time.sleep(4)

        cur.execute(
            "UPDATE treatments SET outcome = %s WHERE treatment_id = %s",
            ("Recovered", treatment_id)
        )
        conn.commit()
        print("[SESSION 1] COMMIT - lock released")

        cur.close()
        conn.close()

    def session2():
        lock_acquired.wait()
        time.sleep(0.3)

        conn = get_connection()
        conn.autocommit = False
        cur = conn.cursor()

        print(f"\n[SESSION 2] Trying to UPDATE treatment_id = {treatment_id}...")
        print("[SESSION 2] BLOCKED - waiting for Session 1 to release the lock")

        start = time.time()
        cur.execute(
            "UPDATE treatments SET outcome = %s WHERE treatment_id = %s",
            ("Stable", treatment_id)
        )
        waited = time.time() - start
        conn.commit()
        print(f"[SESSION 2] Unblocked! Update succeeded after waiting {waited:.1f} seconds")

        cur.close()
        conn.close()

    t1 = threading.Thread(target=session1)
    t2 = threading.Thread(target=session2)
    t1.start()
    time.sleep(0.2)
    t2.start()
    t1.join()
    t2.join()

    print("\n--- Locking Summary ---")
    print("[EXPLANATION]")
    print("SELECT FOR UPDATE puts an exclusive lock on the row.")
    print("Any other transaction trying to UPDATE the same row will wait.")
    print("This is different from MVCC - MVCC handles read/write concurrency,")
    print("SELECT FOR UPDATE handles write/write concurrency.")
    print("In a healthcare system, this prevents two nurses from overwriting")
    print("each other's treatment updates.")

    input("\nPress Enter to go back to the menu...")


# ── Operation 5: Monthly diagnosis summary ────────────────────────────────────
# This shows Hash Join + HashAggregate + Sequential Scan

def monthly_summary(conn):
    print("\n" + "="*60)
    print("OPERATION 5: Monthly Diagnosis Summary")
    print("Internal focus: Hash Join, HashAggregate, Sequential Scan")
    print("="*60)

    query = """
        SELECT
            DATE_TRUNC('month', e.encounter_date) AS month,
            d.diagnosis_code,
            COUNT(*) AS diagnosis_count
        FROM diagnoses d
        JOIN encounters e ON d.encounter_id = e.encounter_id
        GROUP BY 1, 2
        ORDER BY month DESC, diagnosis_count DESC
        LIMIT 15
    """

    print("\n[APPLICATION] Generate a monthly report of how many diagnoses per code.")
    print("\n[SQL QUERY]")
    print("    SELECT DATE_TRUNC('month', e.encounter_date) AS month,")
    print("           d.diagnosis_code, COUNT(*) AS diagnosis_count")
    print("    FROM diagnoses d")
    print("    JOIN encounters e ON d.encounter_id = e.encounter_id")
    print("    GROUP BY 1, 2")
    print("    ORDER BY month DESC, diagnosis_count DESC")
    print("    LIMIT 15")

    print("\n--- EXPLAIN ANALYZE ---")
    cur = conn.cursor()
    cur.execute("EXPLAIN (ANALYZE, BUFFERS) " + query)
    rows = cur.fetchall()
    for row in rows:
        print("   ", row[0])

    print("\n[EXPLANATION]")
    print("Hash Join: PostgreSQL builds a hash table from encounters,")
    print("then probes it for each row in diagnoses.")
    print("HashAggregate: groups rows by (month, diagnosis_code) and counts them.")
    print("Sequential Scan on both tables: since we need ALL rows to compute the")
    print("aggregation, the index won't help here. The query planner is smart")
    print("enough to know that a full table scan is cheaper in this case.")
    print("This is the opposite of Operations 1 and 2 where we only need a few rows.")

    print("\n--- Results ---")
    cur2 = conn.cursor(cursor_factory=psycopg2.extras.DictCursor)
    cur2.execute(query)
    results = cur2.fetchall()

    print(f"{'Month':<14} {'Code':<10} {'Count'}")
    print("-" * 35)
    for r in results:
        month_str = r['month'].strftime('%Y-%m') if r['month'] else 'N/A'
        print(f"{month_str:<14} {r['diagnosis_code']:<10} {r['diagnosis_count']}")

    cur.close()
    cur2.close()
    input("\nPress Enter to go back to the menu...")


# ── Main menu ─────────────────────────────────────────────────────────────────

def main():
    print("\nConnecting to PostgreSQL...")

    try:
        conn = get_connection()
        conn.autocommit = True
        print("Connected successfully!")
    except psycopg2.OperationalError as e:
        print(f"Error connecting to database: {e}")
        print("Make sure PostgreSQL is running and check config.py")
        return

    while True:
        print("\n" + "="*60)
        print("   CLINICAL DIAGNOSIS AND TREATMENT RECORDS SYSTEM")
        print("   DSCI 551 - PostgreSQL Internals Demo")
        print("="*60)
        print("  1. Lookup Diagnoses by Code        [B-Tree Index]")
        print("  2. Patient Encounter History        [Composite Index]")
        print("  3. Concurrent Treatment Update      [MVCC]")
        print("  4. Row-Level Locking Demo           [SELECT FOR UPDATE]")
        print("  5. Monthly Diagnosis Summary        [Aggregation]")
        print("  0. Exit")
        print("="*60)

        choice = input("\nEnter choice: ").strip()

        if choice == "0":
            print("Goodbye!")
            break
        elif choice == "1":
            lookup_diagnosis_by_code(conn)
        elif choice == "2":
            get_encounter_history(conn)
        elif choice == "3":
            mvcc_demo()
        elif choice == "4":
            locking_demo()
        elif choice == "5":
            monthly_summary(conn)
        else:
            print("Invalid choice, please try again.")

    conn.close()


if __name__ == "__main__":
    main()
