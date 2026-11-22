"""Database persistence for Orders Service (PostgreSQL with SQLite fallback)."""

import datetime
import os
import sqlite3
from typing import Any, Dict, List, Optional
from target_app.common.config import settings
from target_app.common.logging import setup_logger

logger = setup_logger("orders_db")


class OrderDB:
    def __init__(self):
        self.use_postgres = False
        self.sqlite_conn: Optional[sqlite3.Connection] = None
        self._init_db()

    def _init_db(self):
        # Attempt PostgreSQL connection
        try:
            import psycopg2
            conn = psycopg2.connect(
                host=settings.POSTGRES_HOST,
                port=settings.POSTGRES_PORT,
                user=settings.POSTGRES_USER,
                password=settings.POSTGRES_PASSWORD,
                dbname=settings.POSTGRES_DB,
                connect_timeout=2,
            )
            with conn.cursor() as cur:
                cur.execute("""
                    CREATE TABLE IF NOT EXISTS orders (
                        order_id VARCHAR(64) PRIMARY KEY,
                        customer_id VARCHAR(64) NOT NULL,
                        item VARCHAR(128) NOT NULL,
                        quantity INT NOT NULL,
                        price NUMERIC(10, 2) NOT NULL,
                        total NUMERIC(10, 2) NOT NULL,
                        status VARCHAR(32) NOT NULL,
                        created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP
                    );
                """)
                conn.commit()
            conn.close()
            self.use_postgres = True
            logger.info("Connected to PostgreSQL database for Orders.")
            return
        except Exception as exc:
            logger.info(f"PostgreSQL not reachable ({exc}). Falling back to SQLite.")

        # Fallback to local SQLite database
        settings.SQLITE_FALLBACK_PATH.parent.mkdir(parents=True, exist_ok=True)
        self.sqlite_conn = sqlite3.connect(
            str(settings.SQLITE_FALLBACK_PATH), check_same_thread=False
        )
        with self.sqlite_conn:
            self.sqlite_conn.execute("""
                CREATE TABLE IF NOT EXISTS orders (
                    order_id TEXT PRIMARY KEY,
                    customer_id TEXT NOT NULL,
                    item TEXT NOT NULL,
                    quantity INTEGER NOT NULL,
                    price REAL NOT NULL,
                    total REAL NOT NULL,
                    status TEXT NOT NULL,
                    created_at TEXT NOT NULL
                );
            """)

    def save_order(self, order: Dict[str, Any]) -> None:
        created_at = datetime.datetime.now(datetime.timezone.utc).isoformat()
        if self.use_postgres:
            import psycopg2
            conn = psycopg2.connect(
                host=settings.POSTGRES_HOST,
                port=settings.POSTGRES_PORT,
                user=settings.POSTGRES_USER,
                password=settings.POSTGRES_PASSWORD,
                dbname=settings.POSTGRES_DB,
            )
            with conn.cursor() as cur:
                cur.execute("""
                    INSERT INTO orders (order_id, customer_id, item, quantity, price, total, status, created_at)
                    VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
                    ON CONFLICT (order_id) DO UPDATE SET status = EXCLUDED.status;
                """, (
                    order["order_id"], order["customer_id"], order["item"],
                    order["quantity"], order["price"], order["total"],
                    order["status"], created_at
                ))
                conn.commit()
            conn.close()
        else:
            with self.sqlite_conn:
                self.sqlite_conn.execute("""
                    INSERT OR REPLACE INTO orders (order_id, customer_id, item, quantity, price, total, status, created_at)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """, (
                    order["order_id"], order["customer_id"], order["item"],
                    order["quantity"], order["price"], order["total"],
                    order["status"], created_at
                ))

    def get_order(self, order_id: str) -> Optional[Dict[str, Any]]:
        if self.use_postgres:
            import psycopg2
            conn = psycopg2.connect(
                host=settings.POSTGRES_HOST,
                port=settings.POSTGRES_PORT,
                user=settings.POSTGRES_USER,
                password=settings.POSTGRES_PASSWORD,
                dbname=settings.POSTGRES_DB,
            )
            with conn.cursor() as cur:
                cur.execute("SELECT order_id, customer_id, item, quantity, price, total, status, created_at FROM orders WHERE order_id = %s", (order_id,))
                row = cur.fetchone()
            conn.close()
        else:
            cur = self.sqlite_conn.cursor()
            cur.execute("SELECT order_id, customer_id, item, quantity, price, total, status, created_at FROM orders WHERE order_id = ?", (order_id,))
            row = cur.fetchone()

        if not row:
            return None
        return {
            "order_id": row[0],
            "customer_id": row[1],
            "item": row[2],
            "quantity": int(row[3]),
            "price": float(row[4]),
            "total": float(row[5]),
            "status": row[6],
            "created_at": str(row[7]),
        }

    def list_orders(self, limit: int = 50) -> List[Dict[str, Any]]:
        if self.use_postgres:
            import psycopg2
            conn = psycopg2.connect(
                host=settings.POSTGRES_HOST,
                port=settings.POSTGRES_PORT,
                user=settings.POSTGRES_USER,
                password=settings.POSTGRES_PASSWORD,
                dbname=settings.POSTGRES_DB,
            )
            with conn.cursor() as cur:
                cur.execute("SELECT order_id, customer_id, item, quantity, price, total, status, created_at FROM orders ORDER BY created_at DESC LIMIT %s", (limit,))
                rows = cur.fetchall()
            conn.close()
        else:
            cur = self.sqlite_conn.cursor()
            cur.execute("SELECT order_id, customer_id, item, quantity, price, total, status, created_at FROM orders ORDER BY created_at DESC LIMIT ?", (limit,))
            rows = cur.fetchall()

        return [
            {
                "order_id": r[0],
                "customer_id": r[1],
                "item": r[2],
                "quantity": int(r[3]),
                "price": float(r[4]),
                "total": float(r[5]),
                "status": r[6],
                "created_at": str(r[7]),
            }
            for r in rows
        ]


db = OrderDB()
