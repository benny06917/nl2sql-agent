
import random
import sqlite3
from datetime import datetime, timedelta
from pathlib import Path

SEED = 42
random.seed(SEED)

DB_PATH = Path(__file__).parent / "retail.db"

# reference pool
US_CITIES = [
    ("New York", "NY"), ("Los Angeles", "CA"), ("Chicago", "IL"),
    ("Houston", "TX"), ("Phoenix", "AZ"), ("Philadelphia", "PA"),
    ("San Antonio", "TX"), ("San Diego", "CA"), ("Dallas", "TX"),
    ("Austin", "TX"), ("Seattle", "WA"), ("Denver", "CO"),
    ("Boston", "MA"), ("Miami", "FL"), ("Atlanta", "GA"),
]
CITY_WEIGHTS = [25, 18, 12, 10, 4, 6, 3, 5, 4, 3, 3, 2, 2, 2, 1]


CATEGORIES = {
    "electronics":      (80, 1200, 30),
    "home_and_kitchen": (15, 300,  18),
    "sports_leisure":   (20, 400,  12),
    "beauty_and_health":(8,  150,  12),
    "toys":             (10, 200,  10),
    "books":            (5,  60,   8),
    "furniture":        (50, 900,  6),
    "pet_supplies":     (8,  120,  4),
}

PAYMENT_TYPES = ["credit_card", "debit_card", "voucher", "boleto"]
PAYMENT_WEIGHTS = [70, 15, 8, 7]

ORDER_STATUSES = ["delivered", "shipped", "canceled", "processing"]
STATUS_WEIGHTS = [88, 5, 4, 3]


def _rand_date(start: datetime, end: datetime) -> datetime:
    delta = end - start
    return start + timedelta(seconds=random.randint(0, int(delta.total_seconds())))


def _monthly_order_count(base: int) -> list[int]:
    """24 months of order counts with an upward trend + mild noise."""
    counts = []
    for i in range(24):
        growth = 1 + (i * 0.04)            
        noise = random.uniform(0.85, 1.15)
        counts.append(int(base * growth * noise))
    return counts


def build():
    if DB_PATH.exists():
        DB_PATH.unlink()
    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()

    # schema 
    cur.executescript(
        """
        CREATE TABLE customers (
            customer_id        INTEGER PRIMARY KEY,
            customer_city      TEXT,
            customer_state     TEXT,
            customer_signup_date TEXT
        );
        CREATE TABLE sellers (
            seller_id    INTEGER PRIMARY KEY,
            seller_city  TEXT,
            seller_state TEXT
        );
        CREATE TABLE products (
            product_id       INTEGER PRIMARY KEY,
            product_name     TEXT,
            product_category TEXT,
            product_weight_g INTEGER
        );
        CREATE TABLE orders (
            order_id                  INTEGER PRIMARY KEY,
            customer_id               INTEGER,
            order_status              TEXT,
            order_purchase_timestamp  TEXT,
            order_delivered_date      TEXT,
            order_estimated_delivery_date TEXT,
            FOREIGN KEY (customer_id) REFERENCES customers(customer_id)
        );
        CREATE TABLE order_items (
            order_id      INTEGER,
            order_item_id INTEGER,
            product_id    INTEGER,
            seller_id     INTEGER,
            price         REAL,
            freight_value REAL,
            PRIMARY KEY (order_id, order_item_id),
            FOREIGN KEY (order_id)   REFERENCES orders(order_id),
            FOREIGN KEY (product_id) REFERENCES products(product_id),
            FOREIGN KEY (seller_id)  REFERENCES sellers(seller_id)
        );
        CREATE TABLE payments (
            order_id             INTEGER,
            payment_type         TEXT,
            payment_installments INTEGER,
            payment_value        REAL,
            FOREIGN KEY (order_id) REFERENCES orders(order_id)
        );
        CREATE TABLE reviews (
            review_id    INTEGER PRIMARY KEY,
            order_id     INTEGER,
            review_score INTEGER,
            review_date  TEXT,
            FOREIGN KEY (order_id) REFERENCES orders(order_id)
        );
        """
    )

    # customers
    n_customers = 2000
    customers = []
    for cid in range(1, n_customers + 1):
        city, state = random.choices(US_CITIES, weights=CITY_WEIGHTS)[0]
        signup = _rand_date(datetime(2022, 6, 1), datetime(2024, 12, 1))
        customers.append((cid, city, state, signup.strftime("%Y-%m-%d")))
    cur.executemany("INSERT INTO customers VALUES (?,?,?,?)", customers)

    # sellers 
    n_sellers = 100
    sellers = []
    for sid in range(1, n_sellers + 1):
        city, state = random.choices(US_CITIES, weights=CITY_WEIGHTS)[0]
        sellers.append((sid, city, state))
    cur.executemany("INSERT INTO sellers VALUES (?,?,?)", sellers)

    # products
    n_products = 300
    products = []
    product_meta = {}  
    cat_names = list(CATEGORIES.keys())
    cat_weights = [CATEGORIES[c][2] for c in cat_names]
    for pid in range(1, n_products + 1):
        category = random.choices(cat_names, weights=cat_weights)[0]
        low, high, _ = CATEGORIES[category]
        name = f"{category.replace('_', ' ').title()} Item {pid}"
        weight = random.randint(100, 5000)
        products.append((pid, name, category, weight))
        product_meta[pid] = (category, low, high)
    cur.executemany("INSERT INTO products VALUES (?,?,?,?)", products)

    monthly_counts = _monthly_order_count(base=150)
    order_id = 0
    item_pk = 0
    review_id = 0

    orders, items, payments, reviews = [], [], [], []

    start_month = datetime(2023, 1, 1)
    for month_idx, count in enumerate(monthly_counts):
        month_start = start_month + timedelta(days=30 * month_idx)
        month_end = month_start + timedelta(days=29)

        for _ in range(count):
            order_id += 1
            customer_id = random.randint(1, n_customers)
            status = random.choices(ORDER_STATUSES, weights=STATUS_WEIGHTS)[0]
            purchase = _rand_date(month_start, month_end)
            estimated = purchase + timedelta(days=random.randint(5, 12))

            delivered_date = None
            is_late = False
            if status == "delivered":
                if random.random() < 0.25:
                    delivered = estimated + timedelta(days=random.randint(1, 10))
                    is_late = True
                else:
                    delivered = estimated - timedelta(days=random.randint(0, 4))
                delivered_date = delivered.strftime("%Y-%m-%d")

            orders.append((
                order_id, customer_id, status,
                purchase.strftime("%Y-%m-%d"),
                delivered_date,
                estimated.strftime("%Y-%m-%d"),
            ))

            n_items = random.choices([1, 2, 3], weights=[70, 22, 8])[0]
            order_value = 0.0
            for i in range(1, n_items + 1):
                item_pk += 1
                pid = random.randint(1, n_products)
                _, low, high = product_meta[pid]
                price = round(random.uniform(low, high), 2)
                freight = round(random.uniform(5, 40), 2)
                order_value += price + freight
                items.append((order_id, i, pid, random.randint(1, n_sellers),
                              price, freight))

            ptype = random.choices(PAYMENT_TYPES, weights=PAYMENT_WEIGHTS)[0]
            installments = 1
            if ptype == "credit_card" and order_value > 200:
                installments = random.choice([1, 2, 3, 6, 12])
            payments.append((order_id, ptype, installments, round(order_value, 2)))

            if status == "delivered" and random.random() < 0.85:
                review_id += 1
                if is_late:
                    score = random.choices([1, 2, 3, 4], weights=[40, 30, 20, 10])[0]
                else:
                    score = random.choices([3, 4, 5], weights=[10, 35, 55])[0]
                rev_date = purchase + timedelta(days=random.randint(10, 20))
                reviews.append((review_id, order_id, score,
                                rev_date.strftime("%Y-%m-%d")))

    cur.executemany("INSERT INTO orders VALUES (?,?,?,?,?,?)", orders)
    cur.executemany("INSERT INTO order_items VALUES (?,?,?,?,?,?)", items)
    cur.executemany("INSERT INTO payments VALUES (?,?,?,?)", payments)
    cur.executemany("INSERT INTO reviews VALUES (?,?,?,?)", reviews)

    conn.commit()

    # quick summary
    summary = {}
    for table in ["customers", "sellers", "products", "orders",
                  "order_items", "payments", "reviews"]:
        summary[table] = cur.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
    conn.close()
    return summary


if __name__ == "__main__":
    counts = build()
    print(f"Database written to: {DB_PATH}")
    print("Row counts:")
    for table, n in counts.items():
        print(f"  {table:<12} {n:>7,}")
