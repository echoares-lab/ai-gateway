import os
import sys
import psycopg2
from psycopg2.extras import DictCursor
from mcp.server.fastmcp import FastMCP

# Initialize FastMCP Server
mcp = FastMCP("PostgreSQL Read-Only MCP Server")

# Get Database URL from environment
DB_URL = os.environ.get("DATABASE_URL", "postgresql://mcp_readonly:mcp_readonly_secret@postgres:5432/postgres")

def get_connection():
    return psycopg2.connect(DB_URL)

@mcp.tool()
def list_tables() -> str:
    """Lists all available user tables in the database."""
    try:
        with get_connection() as conn:
            with conn.cursor() as cur:
                cur.execute("""
                    SELECT table_name 
                    FROM information_schema.tables 
                    WHERE table_schema = 'public' 
                    ORDER BY table_name;
                """)
                tables = [r[0] for r in cur.fetchall()]
                if not tables:
                    return "No tables found in schema 'public'."
                return "Tables in 'public' schema:\n" + "\n".join(f"- {t}" for t in tables)
    except Exception as e:
        return f"Error listing tables: {str(e)}"

@mcp.tool()
def inspect_schema(table_name: str) -> str:
    """Gets the schema (column names and types) of a specific table.
    
    Args:
        table_name: The name of the table to inspect.
    """
    try:
        with get_connection() as conn:
            with conn.cursor() as cur:
                cur.execute("""
                    SELECT column_name, data_type, is_nullable
                    FROM information_schema.columns
                    WHERE table_schema = 'public' AND table_name = %s
                    ORDER BY ordinal_position;
                """, (table_name,))
                columns = cur.fetchall()
                if not columns:
                    return f"Table '{table_name}' not found or has no columns."
                
                result = [f"Schema for table '{table_name}':", f"{'Column':<30} {'Type':<15} {'Nullable':<10}"]
                result.append("-" * 60)
                for name, dtype, nullable in columns:
                    result.append(f"{name:<30} {dtype:<15} {nullable:<10}")
                return "\n".join(result)
    except Exception as e:
        return f"Error inspecting schema: {str(e)}"

@mcp.tool()
def execute_query(query: str) -> str:
    """Executes a read-only SELECT query against the database.
    Only SELECT statements are allowed.
    
    Args:
        query: The SQL SELECT statement to execute.
    """
    # Enforce read-only at the query text level as an extra layer of defense
    normalized = query.strip().lower()
    if not normalized.startswith("select"):
        return "Security Error: Only SELECT queries are permitted on this database connection."
    
    # Block semi-colon query chaining or nested DDL/DML statements
    ddl_keywords = ["insert ", "update ", "delete ", "drop ", "alter ", "create ", "truncate ", "grant ", "revoke ", "replace ", "upsert "]
    if any(keyword in normalized for keyword in ddl_keywords):
        return "Security Error: Mutation and DDL operations are strictly prohibited."
        
    try:
        with get_connection() as conn:
            # Set session-level read-only mode explicitly
            conn.set_session(readonly=True)
            with conn.cursor(cursor_factory=DictCursor) as cur:
                cur.execute(query)
                # Fetch columns
                if cur.description is None:
                    return "Query executed successfully, but returned no description/data."
                
                colnames = [desc[0] for desc in cur.description]
                rows = cur.fetchall()
                
                if not rows:
                    return "Query returned 0 rows."
                
                # Format output nicely
                header = " | ".join(colnames)
                separator = "-" * len(header)
                formatted_rows = []
                for row in rows[:50]: # Limit to first 50 rows for safety and context efficiency
                    formatted_rows.append(" | ".join(str(row[col]) for col in colnames))
                
                result = [header, separator] + formatted_rows
                if len(rows) > 50:
                    result.append(f"... and {len(rows) - 50} more rows (truncated for readability).")
                return "\n".join(result)
    except Exception as e:
        return f"Database Error: {str(e)}"

if __name__ == "__main__":
    mcp.run()
