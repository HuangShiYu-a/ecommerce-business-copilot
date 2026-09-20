-- E-commerce Business Copilot — PostgreSQL DDL（Database §13 对齐；S4 导入用）
-- id 用显式 BIGINT PK：canonical 提供稳定 id（非自增）；空串导入时由 import.py 转 NULL
-- 时间戳默认 now()；canonical 未提供的 created_at/updated_at 走默认

CREATE EXTENSION IF NOT EXISTS vector;
CREATE SCHEMA IF NOT EXISTS knowledge;

-- ============ 租户 / 身份 ============
CREATE TABLE IF NOT EXISTS stores (
    id BIGINT PRIMARY KEY,
    store_code VARCHAR(64) NOT NULL UNIQUE,
    name VARCHAR(128) NOT NULL,
    status VARCHAR(32) NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS staff_users (
    id BIGINT PRIMARY KEY,
    store_id BIGINT NOT NULL REFERENCES stores(id),
    username VARCHAR(64) NOT NULL,
    display_name VARCHAR(128),
    role VARCHAR(32) NOT NULL,
    is_active BOOLEAN NOT NULL DEFAULT true,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (store_id, username)
);

-- ============ 商品 ============
CREATE TABLE IF NOT EXISTS product_categories (
    id BIGINT PRIMARY KEY,
    store_id BIGINT NOT NULL REFERENCES stores(id),
    parent_id BIGINT REFERENCES product_categories(id),
    name VARCHAR(128) NOT NULL,
    status VARCHAR(32) NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS products (
    id BIGINT PRIMARY KEY,
    store_id BIGINT NOT NULL REFERENCES stores(id),
    product_code VARCHAR(64) NOT NULL,
    name VARCHAR(256) NOT NULL,
    category_id BIGINT REFERENCES product_categories(id),
    brand VARCHAR(128),
    description TEXT,
    status VARCHAR(32) NOT NULL,
    cost_price NUMERIC(12,2),
    listed_at TIMESTAMPTZ,
    launch_date DATE,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (store_id, product_code)
);

CREATE TABLE IF NOT EXISTS product_skus (
    id BIGINT PRIMARY KEY,
    store_id BIGINT NOT NULL REFERENCES stores(id),
    product_id BIGINT NOT NULL REFERENCES products(id),
    sku_code VARCHAR(64) NOT NULL,
    attributes JSONB NOT NULL DEFAULT '{}',
    selling_price NUMERIC(12,2) NOT NULL,
    cost_price NUMERIC(12,2),
    status VARCHAR(32) NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS idx_product_skus_product ON product_skus(product_id);
CREATE INDEX IF NOT EXISTS idx_product_skus_store ON product_skus(store_id);

-- ============ 仓储 / 库存 ============
CREATE TABLE IF NOT EXISTS warehouses (
    id BIGINT PRIMARY KEY,
    store_id BIGINT NOT NULL REFERENCES stores(id),
    warehouse_code VARCHAR(64) NOT NULL,
    name VARCHAR(128) NOT NULL,
    location VARCHAR(256),
    status VARCHAR(32) NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (store_id, warehouse_code)
);

CREATE TABLE IF NOT EXISTS inventory (
    id BIGINT PRIMARY KEY,
    store_id BIGINT NOT NULL REFERENCES stores(id),
    warehouse_id BIGINT NOT NULL REFERENCES warehouses(id),
    sku_id BIGINT NOT NULL REFERENCES product_skus(id),
    available_qty INTEGER NOT NULL DEFAULT 0 CHECK (available_qty >= 0),
    reserved_qty INTEGER NOT NULL DEFAULT 0 CHECK (reserved_qty >= 0),
    safety_stock INTEGER NOT NULL DEFAULT 0,
    reorder_point INTEGER,
    updated_at TIMESTAMPTZ NOT NULL,
    UNIQUE (warehouse_id, sku_id)
);

CREATE TABLE IF NOT EXISTS inventory_movements (
    id BIGINT PRIMARY KEY,
    store_id BIGINT NOT NULL REFERENCES stores(id),
    warehouse_id BIGINT NOT NULL,
    sku_id BIGINT NOT NULL,
    movement_type VARCHAR(32) NOT NULL,
    quantity INTEGER NOT NULL,
    reference_type VARCHAR(32),
    reference_id BIGINT,
    occurred_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- ============ 客户 ============
CREATE TABLE IF NOT EXISTS customers (
    id BIGINT PRIMARY KEY,
    store_id BIGINT NOT NULL REFERENCES stores(id),
    customer_code VARCHAR(64) NOT NULL,
    name VARCHAR(128),
    phone VARCHAR(32),
    email VARCHAR(256),
    level VARCHAR(32),
    status VARCHAR(32) NOT NULL DEFAULT 'ACTIVE',
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS customer_addresses (
    id BIGINT PRIMARY KEY,
    store_id BIGINT NOT NULL REFERENCES stores(id),
    customer_id BIGINT NOT NULL REFERENCES customers(id),
    contact_name VARCHAR(128),
    phone VARCHAR(32),
    province VARCHAR(64),
    city VARCHAR(64),
    district VARCHAR(64),
    detail_address VARCHAR(512),
    is_default BOOLEAN NOT NULL DEFAULT false,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- ============ 订单 / 履约 ============
CREATE TABLE IF NOT EXISTS orders (
    id BIGINT PRIMARY KEY,
    store_id BIGINT NOT NULL REFERENCES stores(id),
    order_no VARCHAR(64) NOT NULL,
    customer_id BIGINT NOT NULL REFERENCES customers(id),
    status VARCHAR(32) NOT NULL,
    payment_status VARCHAR(32),
    shipping_status VARCHAR(32),
    total_amount NUMERIC(12,2) NOT NULL,
    paid_amount NUMERIC(12,2),
    shipping_contact_name VARCHAR(128),
    shipping_phone VARCHAR(32),
    shipping_province VARCHAR(64),
    shipping_city VARCHAR(64),
    shipping_district VARCHAR(64),
    shipping_detail VARCHAR(512),
    ordered_at TIMESTAMPTZ NOT NULL,
    paid_at TIMESTAMPTZ,
    promised_ship_at TIMESTAMPTZ,
    promised_delivery_at TIMESTAMPTZ,
    shipped_at TIMESTAMPTZ,
    delivered_at TIMESTAMPTZ,
    signed_at TIMESTAMPTZ,
    completed_at TIMESTAMPTZ,
    cancelled_at TIMESTAMPTZ,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (store_id, order_no)
);
CREATE INDEX IF NOT EXISTS idx_orders_store_status ON orders(store_id, status);
CREATE INDEX IF NOT EXISTS idx_orders_ordered ON orders(ordered_at);

CREATE TABLE IF NOT EXISTS order_items (
    id BIGINT PRIMARY KEY,
    store_id BIGINT NOT NULL REFERENCES stores(id),
    order_id BIGINT NOT NULL REFERENCES orders(id),
    product_id BIGINT NOT NULL REFERENCES products(id),
    sku_id BIGINT NOT NULL REFERENCES product_skus(id),
    quantity INTEGER NOT NULL CHECK (quantity > 0),
    unit_price NUMERIC(12,2) NOT NULL,
    discount_amount NUMERIC(12,2) NOT NULL DEFAULT 0,
    line_amount NUMERIC(12,2) NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS idx_order_items_order ON order_items(order_id);
CREATE INDEX IF NOT EXISTS idx_order_items_sku ON order_items(sku_id);

CREATE TABLE IF NOT EXISTS shipments (
    id BIGINT PRIMARY KEY,
    store_id BIGINT NOT NULL REFERENCES stores(id),
    order_id BIGINT NOT NULL REFERENCES orders(id),
    tracking_no VARCHAR(128),
    carrier VARCHAR(64),
    status VARCHAR(32) NOT NULL,
    shipped_at TIMESTAMPTZ,
    estimated_delivery_at TIMESTAMPTZ,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS shipment_events (
    id BIGINT PRIMARY KEY,
    shipment_id BIGINT NOT NULL REFERENCES shipments(id),
    event_type VARCHAR(64),
    description TEXT,
    location VARCHAR(256),
    event_time TIMESTAMPTZ NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS idx_shipment_events_shipment ON shipment_events(shipment_id);

-- ============ 售后 / 工单 / 反馈 / 价格 / 活动 ============
CREATE TABLE IF NOT EXISTS after_sales_requests (
    id BIGINT PRIMARY KEY,
    store_id BIGINT NOT NULL REFERENCES stores(id),
    request_no VARCHAR(64) NOT NULL,
    order_id BIGINT NOT NULL REFERENCES orders(id),
    order_item_id BIGINT REFERENCES order_items(id),
    customer_id BIGINT NOT NULL REFERENCES customers(id),
    type VARCHAR(32) NOT NULL,
    quantity INTEGER NOT NULL CHECK (quantity > 0),
    reason VARCHAR(128),
    description TEXT,
    status VARCHAR(32) NOT NULL,
    idempotency_key VARCHAR(64) NOT NULL,
    requested_by BIGINT REFERENCES staff_users(id),
    approver_id BIGINT REFERENCES staff_users(id),
    approved_at TIMESTAMPTZ,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (store_id, request_no),
    UNIQUE (store_id, idempotency_key)
);

CREATE TABLE IF NOT EXISTS service_tickets (
    id BIGINT PRIMARY KEY,
    store_id BIGINT NOT NULL,
    ticket_no VARCHAR(64) NOT NULL,
    ticket_type VARCHAR(32) NOT NULL,
    order_id BIGINT,
    customer_id BIGINT,
    product_id BIGINT,
    priority VARCHAR(16),
    status VARCHAR(32) NOT NULL,
    idempotency_key VARCHAR(64) NOT NULL,
    created_by BIGINT,
    approver_id BIGINT,
    approved_at TIMESTAMPTZ,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (store_id, ticket_no),
    UNIQUE (store_id, idempotency_key)
);

CREATE TABLE IF NOT EXISTS customer_feedback (
    id BIGINT PRIMARY KEY,
    store_id BIGINT NOT NULL REFERENCES stores(id),
    customer_id BIGINT REFERENCES customers(id),
    order_id BIGINT REFERENCES orders(id),
    product_id BIGINT REFERENCES products(id),
    type VARCHAR(32) NOT NULL,
    category VARCHAR(64),
    sentiment VARCHAR(16),
    rating INTEGER CHECK (rating BETWEEN 1 AND 5),
    content TEXT NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS idx_feedback_product ON customer_feedback(product_id, created_at);
CREATE INDEX IF NOT EXISTS idx_feedback_store ON customer_feedback(store_id, created_at);

CREATE TABLE IF NOT EXISTS price_history (
    id BIGINT PRIMARY KEY,
    store_id BIGINT NOT NULL REFERENCES stores(id),
    sku_id BIGINT NOT NULL REFERENCES product_skus(id),
    old_price NUMERIC(12,2) NOT NULL,
    new_price NUMERIC(12,2) NOT NULL,
    change_reason VARCHAR(128),
    effective_at TIMESTAMPTZ NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS idx_price_history_sku ON price_history(sku_id, effective_at DESC);

CREATE TABLE IF NOT EXISTS campaigns (
    id BIGINT PRIMARY KEY,
    store_id BIGINT NOT NULL REFERENCES stores(id),
    campaign_code VARCHAR(64) NOT NULL,
    name VARCHAR(128),
    type VARCHAR(32),
    status VARCHAR(32),
    start_time TIMESTAMPTZ,
    end_time TIMESTAMPTZ,
    budget NUMERIC(12,2),
    description TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (store_id, campaign_code)
);

CREATE TABLE IF NOT EXISTS campaign_products (
    id BIGINT PRIMARY KEY,
    campaign_id BIGINT NOT NULL REFERENCES campaigns(id),
    product_id BIGINT NOT NULL REFERENCES products(id),
    discount_rate NUMERIC(8,4),
    promotion_price NUMERIC(12,2),
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (campaign_id, product_id)
);

-- ============ 配置 / 审计 ============
CREATE TABLE IF NOT EXISTS store_configs (
    id BIGINT PRIMARY KEY,
    store_id BIGINT NOT NULL REFERENCES stores(id),
    config_key VARCHAR(128) NOT NULL,
    config_value JSONB NOT NULL,
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (store_id, config_key)
);

CREATE TABLE IF NOT EXISTS audit_logs (
    id BIGINT PRIMARY KEY,
    store_id BIGINT NOT NULL,
    actor_id BIGINT NOT NULL,
    approver_id BIGINT,
    action VARCHAR(64) NOT NULL,
    resource_type VARCHAR(64),
    resource_id BIGINT,
    payload JSONB,
    result VARCHAR(32),
    request_id VARCHAR(64),
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- ============ Knowledge（knowledge schema，pgvector）============
CREATE TABLE IF NOT EXISTS knowledge.knowledge_documents (
    id BIGINT PRIMARY KEY,
    store_id BIGINT,
    title VARCHAR(256),
    knowledge_type VARCHAR(64) NOT NULL,
    layer VARCHAR(32) NOT NULL,
    platform VARCHAR(32),
    source_uri VARCHAR(512),
    status VARCHAR(32) NOT NULL,
    version VARCHAR(32) NOT NULL,
    effective_from TIMESTAMPTZ NOT NULL,
    effective_to TIMESTAMPTZ,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    CHECK (effective_to IS NULL OR effective_to > effective_from)
);

CREATE TABLE IF NOT EXISTS knowledge.knowledge_chunks (
    id BIGINT PRIMARY KEY,
    document_id BIGINT NOT NULL REFERENCES knowledge.knowledge_documents(id),
    chunk_index INTEGER,
    content TEXT NOT NULL,
    section VARCHAR(128),
    embedding vector(1024),   -- bge-m3（R3，Q1 定案）
    metadata JSONB,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS idx_knowledge_chunks_doc ON knowledge.knowledge_chunks(document_id);
