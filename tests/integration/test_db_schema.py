import pytest
import psycopg2
import os

def test_database_is_empty_or_baselined():
    # Connect to the database
    conn = psycopg2.connect(
        dbname=os.getenv("POSTGRES_DB", "litellm"),
        user=os.getenv("POSTGRES_USER", "postgres"),
        password=os.getenv("POSTGRES_PASSWORD", "postgres"),
        host="postgres",
        port="5432"
    )
    cur = conn.cursor()
    # Check for tables
    cur.execute("SELECT count(*) FROM information_schema.tables WHERE table_schema = 'public'")
    count = cur.fetchone()[0]
    
    # In a clean dev environment, this should be very low (e.g., just the init-db.sql tables)
    # If it's high, it implies an un-baselined database.
    assert count < 5, f"Database seems to have {count} tables already, migrations might fail."
    cur.close()
    conn.close()
