-- 비트코인 자동매매 봇 데이터베이스 초기화

-- OHLCV 데이터 테이블
CREATE TABLE IF NOT EXISTS ohlcv_data (
    id SERIAL PRIMARY KEY,
    market VARCHAR(20) NOT NULL,
    interval_type VARCHAR(10) NOT NULL,
    timestamp BIGINT NOT NULL,
    open_price DECIMAL(20, 8) NOT NULL,
    high_price DECIMAL(20, 8) NOT NULL,
    low_price DECIMAL(20, 8) NOT NULL,
    close_price DECIMAL(20, 8) NOT NULL,
    volume DECIMAL(20, 8) NOT NULL,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    UNIQUE(market, interval_type, timestamp)
);

-- 주문 내역 테이블
CREATE TABLE IF NOT EXISTS orders (
    id SERIAL PRIMARY KEY,
    uuid VARCHAR(100) UNIQUE NOT NULL,
    market VARCHAR(20) NOT NULL,
    side VARCHAR(10) NOT NULL,
    ord_type VARCHAR(20) NOT NULL,
    price DECIMAL(20, 8),
    volume DECIMAL(20, 8),
    state VARCHAR(20) NOT NULL,
    created_at TIMESTAMP NOT NULL,
    executed_volume DECIMAL(20, 8) DEFAULT 0,
    paid_fee DECIMAL(20, 8) DEFAULT 0,
    remaining_fee DECIMAL(20, 8) DEFAULT 0,
    reserved_fee DECIMAL(20, 8) DEFAULT 0,
    locked DECIMAL(20, 8) DEFAULT 0,
    trades_count INTEGER DEFAULT 0,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- 포지션 상태 테이블
CREATE TABLE IF NOT EXISTS positions (
    id SERIAL PRIMARY KEY,
    market VARCHAR(20) UNIQUE NOT NULL,
    side VARCHAR(10),
    entry_price DECIMAL(20, 8),
    volume DECIMAL(20, 8),
    stop_price DECIMAL(20, 8),
    trail_price DECIMAL(20, 8),
    unrealized_pnl DECIMAL(20, 8),
    realized_pnl DECIMAL(20, 8) DEFAULT 0,
    created_at TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- 거래 내역 테이블
CREATE TABLE IF NOT EXISTS trades (
    id SERIAL PRIMARY KEY,
    order_uuid VARCHAR(100) NOT NULL,
    market VARCHAR(20) NOT NULL,
    side VARCHAR(10) NOT NULL,
    price DECIMAL(20, 8) NOT NULL,
    volume DECIMAL(20, 8) NOT NULL,
    fee DECIMAL(20, 8) NOT NULL,
    pnl DECIMAL(20, 8),
    r_multiple DECIMAL(10, 4),
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- 계좌 잔고 스냅샷 테이블
CREATE TABLE IF NOT EXISTS account_snapshots (
    id SERIAL PRIMARY KEY,
    total_krw DECIMAL(20, 8) NOT NULL,
    total_btc DECIMAL(20, 8) NOT NULL,
    total_value_krw DECIMAL(20, 8) NOT NULL,
    daily_pnl DECIMAL(20, 8),
    weekly_pnl DECIMAL(20, 8),
    total_pnl DECIMAL(20, 8),
    current_r DECIMAL(10, 4),
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- 시스템 로그 테이블
CREATE TABLE IF NOT EXISTS system_logs (
    id SERIAL PRIMARY KEY,
    level VARCHAR(10) NOT NULL,
    module VARCHAR(50) NOT NULL,
    message TEXT NOT NULL,
    data JSONB,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- 인덱스 생성
CREATE INDEX IF NOT EXISTS idx_ohlcv_market_interval_timestamp ON ohlcv_data(market, interval_type, timestamp);
CREATE INDEX IF NOT EXISTS idx_orders_market_created_at ON orders(market, created_at);
CREATE INDEX IF NOT EXISTS idx_trades_market_created_at ON trades(market, created_at);
CREATE INDEX IF NOT EXISTS idx_account_snapshots_created_at ON account_snapshots(created_at);
CREATE INDEX IF NOT EXISTS idx_system_logs_level_created_at ON system_logs(level, created_at);
