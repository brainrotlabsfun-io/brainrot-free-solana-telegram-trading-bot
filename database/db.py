"""
database/db.py
==============
SQLite database layer using aiosqlite (async).
All tables — legacy Raid Center and new Raid Hub — are created here on startup.
"""

import aiosqlite
import logging

logger = logging.getLogger(__name__)

DB_PATH = "brainrot.db"


async def init_db() -> None:
    """
    Creates all required tables if they don't already exist.
    Safe to run on every startup — uses CREATE TABLE IF NOT EXISTS.
    """
    async with aiosqlite.connect(DB_PATH) as db:

        # ══════════════════════════════════════════════════════════════════════
        # LEGACY RAID CENTER TABLES (admin-created raids)
        # ══════════════════════════════════════════════════════════════════════

        await db.execute("""
            CREATE TABLE IF NOT EXISTS raids (
                id              INTEGER PRIMARY KEY AUTOINCREMENT,
                title           TEXT    NOT NULL,
                target_url      TEXT    NOT NULL,
                platform        TEXT    NOT NULL,
                instructions    TEXT    NOT NULL,
                reward_points   INTEGER NOT NULL DEFAULT 50,
                created_by      INTEGER NOT NULL,
                created_at      TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                expires_at      TIMESTAMP,
                active          INTEGER DEFAULT 1
            )
        """)

        await db.execute("""
            CREATE TABLE IF NOT EXISTS raid_participants (
                id              INTEGER PRIMARY KEY AUTOINCREMENT,
                raid_id         INTEGER NOT NULL,
                user_id         INTEGER NOT NULL,
                username        TEXT,
                completed_at    TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                points_awarded  INTEGER NOT NULL,
                FOREIGN KEY (raid_id) REFERENCES raids(id),
                UNIQUE(raid_id, user_id)
            )
        """)

        await db.execute("""
            CREATE TABLE IF NOT EXISTS raid_points (
                id              INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id         INTEGER NOT NULL UNIQUE,
                username        TEXT,
                total_points    INTEGER DEFAULT 0
            )
        """)

        # ══════════════════════════════════════════════════════════════════════
        # RAID HUB TABLES (user-generated raids)
        # ══════════════════════════════════════════════════════════════════════

        await db.execute("""
            CREATE TABLE IF NOT EXISTS users (
                id               INTEGER PRIMARY KEY AUTOINCREMENT,
                telegram_user_id INTEGER NOT NULL UNIQUE,
                username         TEXT,
                first_name       TEXT,
                created_at       TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)

        await db.execute("""
            CREATE TABLE IF NOT EXISTS hub_raids (
                id               INTEGER PRIMARY KEY AUTOINCREMENT,
                creator_user_id  INTEGER NOT NULL,
                title            TEXT    NOT NULL,
                platform         TEXT    NOT NULL,
                target_link      TEXT    NOT NULL,
                instructions     TEXT    NOT NULL,
                comment_ideas    TEXT,
                hashtag_ideas    TEXT,
                expiry_at        TIMESTAMP NOT NULL,
                reward_points    INTEGER DEFAULT 10,
                premium_only     INTEGER DEFAULT 0,
                status           TEXT    DEFAULT 'pending',
                featured         INTEGER DEFAULT 0,
                created_at       TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                approved_at      TIMESTAMP,
                approved_by      INTEGER
            )
        """)

        await db.execute("""
            CREATE TABLE IF NOT EXISTS hub_participants (
                id           INTEGER PRIMARY KEY AUTOINCREMENT,
                raid_id      INTEGER NOT NULL,
                user_id      INTEGER NOT NULL,
                joined_at    TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                completed_at TIMESTAMP,
                proof_text   TEXT,
                status       TEXT DEFAULT 'joined',
                FOREIGN KEY (raid_id) REFERENCES hub_raids(id),
                UNIQUE(raid_id, user_id)
            )
        """)

        await db.execute("""
            CREATE TABLE IF NOT EXISTS user_points (
                id           INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id      INTEGER NOT NULL UNIQUE,
                username     TEXT,
                total_points INTEGER DEFAULT 0,
                updated_at   TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)

        await db.execute("""
            CREATE TABLE IF NOT EXISTS premium_users (
                id               INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id          INTEGER NOT NULL UNIQUE,
                active           INTEGER DEFAULT 1,
                entitlement_type TEXT    DEFAULT 'manual',
                created_at       TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)

        # ══════════════════════════════════════════════════════════════════════
        # BURN / BADGE SYSTEM TABLES
        # ══════════════════════════════════════════════════════════════════════

        await db.execute("""
            CREATE TABLE IF NOT EXISTS wallet_links (
                id             INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id        INTEGER NOT NULL UNIQUE,
                wallet_address TEXT    NOT NULL,
                created_at     TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                updated_at     TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)

        await db.execute("""
            CREATE TABLE IF NOT EXISTS burn_activations (
                id              INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id         INTEGER NOT NULL,
                wallet_address  TEXT    NOT NULL,
                token_mint      TEXT    NOT NULL,
                required_amount REAL    NOT NULL DEFAULT 0,
                burned_amount   REAL    NOT NULL DEFAULT 0,
                tx_signature    TEXT    NOT NULL UNIQUE,
                status          TEXT    NOT NULL DEFAULT 'pending',
                verified_at     TIMESTAMP,
                created_at      TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                updated_at      TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)

        await db.execute("""
            CREATE TABLE IF NOT EXISTS badge_definitions (
                id                  INTEGER PRIMARY KEY AUTOINCREMENT,
                badge_key           TEXT    NOT NULL UNIQUE,
                badge_name          TEXT    NOT NULL,
                description         TEXT,
                min_total_burn      REAL    DEFAULT 0,
                min_burn_count      INTEGER DEFAULT 1,
                requires_activation INTEGER DEFAULT 0,
                icon                TEXT    DEFAULT '🏅',
                tier_rank           INTEGER DEFAULT 1,
                active              INTEGER DEFAULT 1,
                created_at          TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                updated_at          TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)

        await db.execute("""
            CREATE TABLE IF NOT EXISTS user_badges (
                id                   INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id              INTEGER NOT NULL,
                badge_key            TEXT    NOT NULL,
                awarded_at           TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                source_tx_signature  TEXT,
                active               INTEGER DEFAULT 1,
                created_at           TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                updated_at           TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                UNIQUE(user_id, badge_key)
            )
        """)

        await db.execute("""
            CREATE TABLE IF NOT EXISTS user_burn_stats (
                id               INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id          INTEGER NOT NULL UNIQUE,
                total_burned     REAL    DEFAULT 0,
                burn_count       INTEGER DEFAULT 0,
                last_burn_at     TIMESTAMP,
                highest_badge_key TEXT,
                updated_at       TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)

        # ── Indexes ─────────────────────────────────────────────────────────────
        await db.execute(
            "CREATE INDEX IF NOT EXISTS idx_burn_activations_user  ON burn_activations(user_id)"
        )
        await db.execute(
            "CREATE INDEX IF NOT EXISTS idx_burn_activations_tx    ON burn_activations(tx_signature)"
        )
        await db.execute(
            "CREATE INDEX IF NOT EXISTS idx_user_badges_user       ON user_badges(user_id)"
        )
        await db.execute(
            "CREATE INDEX IF NOT EXISTS idx_wallet_links_user      ON wallet_links(user_id)"
        )

        # ── Migrate holder_access: add columns that may not exist yet ─────────
        _holder_access_new_cols = [
            "ALTER TABLE holder_access ADD COLUMN wallet_address          TEXT    DEFAULT ''",
            "ALTER TABLE holder_access ADD COLUMN activated_via           TEXT    DEFAULT 'manual'",
            "ALTER TABLE holder_access ADD COLUMN activation_tx_signature TEXT",
            "ALTER TABLE holder_access ADD COLUMN activated_at            TIMESTAMP",
            "ALTER TABLE holder_access ADD COLUMN expires_at              TIMESTAMP",
            "ALTER TABLE holder_access ADD COLUMN updated_at              TIMESTAMP DEFAULT CURRENT_TIMESTAMP",
        ]
        for col_sql in _holder_access_new_cols:
            try:
                await db.execute(col_sql)
            except Exception:
                pass  # Column already exists

        # ── Migrate trading_wallets: add updated_at if missing ───────────────
        try:
            await db.execute(
                "ALTER TABLE trading_wallets ADD COLUMN updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP"
            )
        except Exception:
            pass

        # ══════════════════════════════════════════════════════════════════════
        # BOT-MANAGED HOT WALLETS
        # ══════════════════════════════════════════════════════════════════════

        await db.execute("""
            CREATE TABLE IF NOT EXISTS bot_wallets (
                id                    INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id               INTEGER NOT NULL UNIQUE,
                wallet_address        TEXT    NOT NULL,
                encrypted_private_key TEXT    NOT NULL,
                created_at            TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)

        # ══════════════════════════════════════════════════════════════════════
        # SNIPER TOOL TABLES
        # ══════════════════════════════════════════════════════════════════════

        await db.execute("""
            CREATE TABLE IF NOT EXISTS holder_access (
                id                      INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id                 INTEGER NOT NULL UNIQUE,
                wallet_address          TEXT    DEFAULT '',
                tier                    TEXT    NOT NULL DEFAULT 'supreme',
                active                  INTEGER DEFAULT 1,
                activated_via           TEXT    DEFAULT 'manual',
                activation_tx_signature TEXT,
                activated_at            TIMESTAMP,
                expires_at              TIMESTAMP,
                granted_by              INTEGER,
                granted_at              TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                updated_at              TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)

        await db.execute("""
            CREATE TABLE IF NOT EXISTS sniper_settings (
                id                            INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id                       INTEGER NOT NULL UNIQUE,
                min_liquidity                 REAL    DEFAULT 2000,
                min_volume                    REAL    DEFAULT 1000,
                min_buys                      INTEGER DEFAULT 10,
                max_token_age_minutes         INTEGER DEFAULT 60,
                max_risk_level                INTEGER DEFAULT 3,
                default_buy_size              REAL    DEFAULT 0.05,
                default_slippage              REAL    DEFAULT 15.0,
                strict_mode                   INTEGER DEFAULT 0,
                auto_filter_enabled           INTEGER DEFAULT 0,
                prioritize_fresh_launches     INTEGER DEFAULT 0,
                prioritize_liquidity_strength INTEGER DEFAULT 0,
                auto_hide_weak_metadata       INTEGER DEFAULT 0,
                auto_hide_low_momentum        INTEGER DEFAULT 0,
                instant_alert_on_match        INTEGER DEFAULT 0,
                premium_ranking_boost         INTEGER DEFAULT 0,
                preferred_platform            TEXT    DEFAULT 'auto',
                updated_at                    TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)

        # Migrate existing sniper_settings rows — add preferred_platform if missing
        try:
            await db.execute(
                "ALTER TABLE sniper_settings ADD COLUMN preferred_platform TEXT DEFAULT 'auto'"
            )
        except Exception:
            pass  # column already exists

        await db.execute("""
            CREATE TABLE IF NOT EXISTS sniper_presets (
                id          INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id     INTEGER NOT NULL,
                name        TEXT    NOT NULL,
                settings_json TEXT  NOT NULL,
                created_at  TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)

        await db.execute("""
            CREATE TABLE IF NOT EXISTS sniper_watch_targets (
                id            INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id       INTEGER NOT NULL,
                token_address TEXT    NOT NULL,
                added_at      TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                UNIQUE(user_id, token_address)
            )
        """)

        await db.execute("""
            CREATE TABLE IF NOT EXISTS sniper_blacklist (
                id            INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id       INTEGER NOT NULL,
                token_address TEXT    NOT NULL,
                added_at      TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                UNIQUE(user_id, token_address)
            )
        """)

        await db.execute("""
            CREATE TABLE IF NOT EXISTS whale_sniper_settings (
                id                INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id           INTEGER NOT NULL UNIQUE,
                enabled           INTEGER DEFAULT 0,
                kill_switch       INTEGER DEFAULT 0,
                min_whale_sol     REAL    DEFAULT 1.0,
                curve_depth_pct   REAL    DEFAULT 0.0,
                copy_buy_size_sol REAL    DEFAULT 0.01,
                slippage          REAL    DEFAULT 20.0,
                priority_fee      REAL    DEFAULT 0.0002,
                max_buys_per_hour INTEGER DEFAULT 5,
                updated_at        TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)

        await db.execute("""
            CREATE TABLE IF NOT EXISTS creator_blacklist (
                id               INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id          INTEGER NOT NULL,
                creator_address  TEXT    NOT NULL,
                note             TEXT    DEFAULT '',
                added_at         TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                UNIQUE(user_id, creator_address)
            )
        """)

        await db.execute("""
            CREATE TABLE IF NOT EXISTS sniper_alert_settings (
                id              INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id         INTEGER NOT NULL UNIQUE,
                alerts_enabled  INTEGER DEFAULT 1,
                min_score       INTEGER DEFAULT 60,
                updated_at      TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)

        await db.execute("""
            CREATE TABLE IF NOT EXISTS trading_wallets (
                id             INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id        INTEGER NOT NULL UNIQUE,
                wallet_address TEXT    NOT NULL,
                label          TEXT    DEFAULT 'Main',
                added_at       TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)

        await db.execute("""
            CREATE TABLE IF NOT EXISTS auto_buy_settings (
                id                  INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id             INTEGER NOT NULL UNIQUE,
                enabled             INTEGER DEFAULT 0,
                kill_switch         INTEGER DEFAULT 0,
                max_buy_size_sol    REAL    DEFAULT 0.05,
                max_buys_per_hour   INTEGER DEFAULT 5,
                score_threshold     INTEGER DEFAULT 30,
                slippage            REAL    DEFAULT 15.0,
                priority_fee        REAL    DEFAULT 0.005,
                cooldown_seconds    INTEGER DEFAULT 60,
                min_initial_buy_sol REAL    DEFAULT 0,
                liq_exit_preset_id       INTEGER DEFAULT NULL,
                min_wallet_balance_sol   REAL    DEFAULT 0.05,
                daily_spend_limit_sol    REAL    DEFAULT 0.0,
                updated_at               TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)

        # ── Migrate auto_buy_settings: fix bad defaults written by earlier schema ──
        # Slippage of 1.0% fails on pump.fun; fix any row where it was never changed.
        await db.execute(
            "UPDATE auto_buy_settings SET slippage = 15.0 WHERE slippage <= 1.5"
        )
        # Priority fee: old default was 0.000005 (too low — TXs don't land).
        # Upgrade any row still at the old default to the reliable 0.005 value.
        await db.execute(
            "UPDATE auto_buy_settings SET priority_fee = 0.005 WHERE priority_fee <= 0.0001"
        )
        # Copy trade priority fee — same issue.
        await db.execute(
            "UPDATE copy_trade_settings SET priority_fee = 0.005 WHERE priority_fee <= 0.0001"
        )
        # Auto-exit priority fee — upgrade from 0.0001 factory default.
        await db.execute(
            "UPDATE auto_exit_settings SET custom_priority_fee = 0.005 WHERE custom_priority_fee <= 0.001"
        )
        # Fix updated_at for rows that were created with CURRENT_TIMESTAMP default but
        # the user never actually configured anything — reset to NULL so the worker's
        # "never_configured" check works correctly.
        await db.execute("""
            UPDATE auto_exit_settings
            SET updated_at = NULL
            WHERE enabled = 0 AND selected_preset_id IS NULL
        """)
        # score_threshold: old default was 65 (too high), then 30 (too low — buys too much noise).
        # Migrate rows still at 30 (factory default) to 45 for better signal quality.
        await db.execute(
            "UPDATE auto_buy_settings SET score_threshold = 45 WHERE score_threshold IN (30, 65) AND enabled = 0"
        )
        # Sniper filters: update still-at-default rows to tighter values.
        await db.execute(
            "UPDATE sniper_settings SET min_liquidity = 5000 WHERE min_liquidity <= 2000"
        )
        await db.execute(
            "UPDATE sniper_settings SET min_volume = 2000 WHERE min_volume <= 1000"
        )
        await db.execute(
            "UPDATE sniper_settings SET min_buys = 15 WHERE min_buys <= 10"
        )
        await db.execute(
            "UPDATE sniper_settings SET max_token_age_minutes = 30 WHERE max_token_age_minutes >= 60"
        )
        # max_buys_per_hour: 5 was the old default — lower to 3 for selectivity.
        await db.execute(
            "UPDATE auto_buy_settings SET max_buys_per_hour = 3 WHERE max_buys_per_hour >= 5 AND enabled = 0"
        )
        # cooldown_seconds: 60 → 90
        await db.execute(
            "UPDATE auto_buy_settings SET cooldown_seconds = 90 WHERE cooldown_seconds = 60 AND enabled = 0"
        )
        # Align buy size
        await db.execute(
            "UPDATE auto_buy_settings SET max_buy_size_sol = 0.05 WHERE max_buy_size_sol >= 0.1 AND enabled = 0"
        )

        try:
            await db.execute(
                "ALTER TABLE auto_buy_settings ADD COLUMN min_initial_buy_sol REAL DEFAULT 0"
            )
        except Exception:
            pass  # column already exists
        # Reset min_initial_buy_sol for all users — the Liq Sniper tab sets it
        # explicitly when activated. Any stuck value from a previous session
        # (including DEGEN FIRE users who also have score_threshold=1) is cleared here.
        await db.execute("UPDATE auto_buy_settings SET min_initial_buy_sol = 0")
        try:
            await db.execute(
                "ALTER TABLE auto_buy_settings ADD COLUMN liq_exit_preset_id INTEGER DEFAULT NULL"
            )
        except Exception:
            pass
        try:
            await db.execute(
                "ALTER TABLE auto_buy_settings ADD COLUMN min_wallet_balance_sol REAL DEFAULT 0.05"
            )
        except Exception:
            pass
        try:
            await db.execute(
                "ALTER TABLE auto_buy_settings ADD COLUMN daily_spend_limit_sol REAL DEFAULT 0.0"
            )
        except Exception:
            pass

        try:
            await db.execute(
                "ALTER TABLE auto_buy_settings ADD COLUMN min_market_cap_usd REAL DEFAULT 0.0"
            )
        except Exception:
            pass
        try:
            await db.execute(
                "ALTER TABLE auto_buy_settings ADD COLUMN max_market_cap_usd REAL DEFAULT 0.0"
            )
        except Exception:
            pass

        # ── Migrate candle_sniper_settings: add max_hold_minutes column ──────────
        try:
            await db.execute(
                "ALTER TABLE candle_sniper_settings ADD COLUMN max_hold_minutes INTEGER DEFAULT 480"
            )
        except Exception:
            pass  # column already exists

        # ── Migrate candle_sniper_settings: add surge detector columns ───────────
        try:
            await db.execute(
                "ALTER TABLE candle_sniper_settings ADD COLUMN surge_enabled INTEGER DEFAULT 0"
            )
        except Exception:
            pass
        try:
            await db.execute(
                "ALTER TABLE candle_sniper_settings ADD COLUMN surge_threshold_pct REAL DEFAULT 500.0"
            )
        except Exception:
            pass
        try:
            await db.execute(
                "ALTER TABLE candle_sniper_settings ADD COLUMN surge_track_hours INTEGER DEFAULT 24"
            )
        except Exception:
            pass
        try:
            await db.execute(
                "ALTER TABLE candle_sniper_settings ADD COLUMN slippage_pct REAL DEFAULT 5.0"
            )
        except Exception:
            pass

        # ── Migrate sniper_blacklist: add label column ──────────────────────────
        try:
            await db.execute(
                "ALTER TABLE sniper_blacklist ADD COLUMN label TEXT DEFAULT ''"
            )
        except Exception:
            pass

        # ── Migrate candle_sniper_settings: align DB defaults with code defaults ──
        await db.execute(
            "UPDATE candle_sniper_settings SET min_confirmations = 3 WHERE min_confirmations >= 5 AND enabled = 0"
        )
        await db.execute(
            "UPDATE candle_sniper_settings SET confidence_threshold = 45 WHERE confidence_threshold >= 55 AND enabled = 0"
        )
        await db.execute(
            "UPDATE candle_sniper_settings SET max_open_positions = 5 WHERE max_open_positions <= 3 AND enabled = 0"
        )

        # ── Migrate sniper_settings: add columns missing from initial schema ────
        _sniper_new_cols = [
            "ALTER TABLE sniper_settings ADD COLUMN max_risk_level              INTEGER DEFAULT 3",
            "ALTER TABLE sniper_settings ADD COLUMN auto_hide_weak_metadata     INTEGER DEFAULT 0",
            "ALTER TABLE sniper_settings ADD COLUMN auto_hide_low_momentum      INTEGER DEFAULT 0",
            "ALTER TABLE sniper_settings ADD COLUMN premium_ranking_boost       INTEGER DEFAULT 0",
            "ALTER TABLE sniper_settings ADD COLUMN strategy_mode               TEXT    DEFAULT 'none'",
        ]
        for col_sql in _sniper_new_cols:
            try:
                await db.execute(col_sql)
            except Exception:
                pass  # Column already exists

        await db.execute("""
            CREATE TABLE IF NOT EXISTS auto_buy_jobs (
                id            INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id       INTEGER NOT NULL,
                token_address TEXT    NOT NULL,
                amount_sol    REAL    NOT NULL,
                score         INTEGER,
                status        TEXT    DEFAULT 'queued',
                tx_signature  TEXT,
                created_at    TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                executed_at   TIMESTAMP,
                source        TEXT      DEFAULT 'auto_buy',
                updated_at    TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)
        # Migration: add updated_at to existing auto_buy_jobs tables
        try:
            await db.execute(
                "ALTER TABLE auto_buy_jobs ADD COLUMN updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP"
            )
        except Exception:
            pass  # column already exists
        try:
            await db.execute(
                "ALTER TABLE auto_buy_jobs ADD COLUMN source TEXT DEFAULT 'auto_buy'"
            )
        except Exception:
            pass

        await db.execute("""
            CREATE TABLE IF NOT EXISTS submitted_transactions (
                id            INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id       INTEGER NOT NULL,
                token_address TEXT    NOT NULL,
                tx_signature  TEXT,
                amount_sol    REAL,
                direction     TEXT    DEFAULT 'buy',
                status        TEXT    DEFAULT 'pending',
                created_at    TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)

        await db.execute("""
            CREATE TABLE IF NOT EXISTS tracked_positions (
                id              INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id         INTEGER NOT NULL,
                token_address   TEXT    NOT NULL,
                token_symbol    TEXT,
                buy_price_sol   REAL,
                amount_sol      REAL,
                tx_signature    TEXT,
                status          TEXT    DEFAULT 'open',
                opened_at       TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                closed_at       TIMESTAMP,
                UNIQUE(user_id, token_address, opened_at)
            )
        """)

        await db.execute("""
            CREATE TABLE IF NOT EXISTS cached_token_data (
                id            INTEGER PRIMARY KEY AUTOINCREMENT,
                token_address TEXT    NOT NULL UNIQUE,
                data_json     TEXT    NOT NULL,
                fetched_at    TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)

        # ══════════════════════════════════════════════════════════════════════
        # SUPREME BLACK — AUTO-EXIT MANAGER TABLES
        # ══════════════════════════════════════════════════════════════════════

        await db.execute("""
            CREATE TABLE IF NOT EXISTS auto_exit_settings (
                id                    INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id               INTEGER NOT NULL UNIQUE,
                enabled               INTEGER DEFAULT 0,
                live_mode             INTEGER DEFAULT 1,
                selected_preset_id    INTEGER,
                custom_slippage       REAL    DEFAULT 15.0,
                custom_priority_fee   REAL    DEFAULT 0.005,
                notifications_enabled INTEGER DEFAULT 1,
                updated_at            TIMESTAMP
            )
        """)

        # Presets — system presets have is_system=1, user_id=NULL
        await db.execute("""
            CREATE TABLE IF NOT EXISTS exit_presets (
                id                   INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id              INTEGER,
                name                 TEXT    NOT NULL,
                description          TEXT,
                is_system            INTEGER DEFAULT 0,
                tp1_pct              REAL,
                tp1_sell_pct         REAL,
                tp2_pct              REAL,
                tp2_sell_pct         REAL,
                tp3_pct              REAL,
                tp3_sell_pct         REAL,
                moon_bag_pct         REAL    DEFAULT 0,
                sl_pct               REAL,
                trailing_stop_pct    REAL,
                trailing_after_tp    INTEGER DEFAULT 1,
                break_even_after_tp  INTEGER DEFAULT 1,
                max_hold_minutes     INTEGER,
                created_at           TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)

        # Live watcher state per position
        await db.execute("""
            CREATE TABLE IF NOT EXISTS position_state (
                id                INTEGER PRIMARY KEY AUTOINCREMENT,
                position_id       INTEGER NOT NULL UNIQUE,
                user_id           INTEGER NOT NULL,
                token_address     TEXT    NOT NULL,
                entry_price_sol   REAL    DEFAULT 0,
                current_price_sol REAL    DEFAULT 0,
                highest_price_sol REAL    DEFAULT 0,
                qty_remaining_pct REAL    DEFAULT 100.0,
                tp1_fired         INTEGER DEFAULT 0,
                tp2_fired         INTEGER DEFAULT 0,
                tp3_fired         INTEGER DEFAULT 0,
                sl_fired          INTEGER DEFAULT 0,
                trailing_active   INTEGER DEFAULT 0,
                trailing_high_sol REAL    DEFAULT 0,
                break_even_active INTEGER DEFAULT 0,
                preset_id         INTEGER,
                status            TEXT    DEFAULT 'watching',
                last_checked_at   TIMESTAMP,
                opened_at         TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                updated_at        TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)

        # Immutable audit log — one row per trigger event
        await db.execute("""
            CREATE TABLE IF NOT EXISTS position_events (
                id           INTEGER PRIMARY KEY AUTOINCREMENT,
                position_id  INTEGER NOT NULL,
                user_id      INTEGER NOT NULL,
                event_type   TEXT    NOT NULL,
                price_sol    REAL,
                sell_pct     REAL,
                pnl_sol      REAL,
                note         TEXT,
                created_at   TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)

        # Per-sell idempotency guard and audit trail
        await db.execute("""
            CREATE TABLE IF NOT EXISTS sell_executions (
                id             INTEGER PRIMARY KEY AUTOINCREMENT,
                position_id    INTEGER NOT NULL,
                user_id        INTEGER NOT NULL,
                token_address  TEXT    NOT NULL,
                sell_pct       REAL    NOT NULL,
                amount_sol_est REAL,
                tx_signature   TEXT,
                status         TEXT    DEFAULT 'pending',
                trigger_type   TEXT,
                created_at     TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                confirmed_at   TIMESTAMP
            )
        """)

        await db.execute(
            "CREATE INDEX IF NOT EXISTS idx_pos_state_status ON position_state(status)"
        )
        await db.execute(
            "CREATE INDEX IF NOT EXISTS idx_pos_state_user ON position_state(user_id)"
        )
        await db.execute(
            "CREATE INDEX IF NOT EXISTS idx_pos_events_pos ON position_events(position_id)"
        )

        # ══════════════════════════════════════════════════════════════════════
        # COPY TRADING TABLES
        # ══════════════════════════════════════════════════════════════════════

        await db.execute("""
            CREATE TABLE IF NOT EXISTS copy_trade_wallets (
                id             INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id        INTEGER NOT NULL,
                wallet_address TEXT    NOT NULL,
                label          TEXT    DEFAULT '',
                enabled        INTEGER DEFAULT 1,
                created_at     TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                UNIQUE(user_id, wallet_address)
            )
        """)

        await db.execute("""
            CREATE TABLE IF NOT EXISTS copy_trade_settings (
                user_id              INTEGER PRIMARY KEY,
                enabled              INTEGER DEFAULT 0,
                kill_switch          INTEGER DEFAULT 0,
                copy_buys            INTEGER DEFAULT 1,
                copy_sells           INTEGER DEFAULT 0,
                copy_size_mode       TEXT    DEFAULT 'fixed',
                fixed_amount_sol     REAL    DEFAULT 0.05,
                percentage_amount    REAL    DEFAULT 10.0,
                max_buy_amount_sol   REAL    DEFAULT 0.5,
                max_slippage         REAL    DEFAULT 15.0,
                min_liquidity_usd    REAL    DEFAULT 0.0,
                auto_sell            INTEGER DEFAULT 0,
                take_profit_pct      REAL    DEFAULT 0.0,
                stop_loss_pct        REAL    DEFAULT 0.0,
                cooldown_seconds     INTEGER DEFAULT 30,
                max_trades_per_hour  INTEGER DEFAULT 30,
                priority_fee         REAL    DEFAULT 0.005,
                updated_at           TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)

        await db.execute("""
            CREATE TABLE IF NOT EXISTS copy_trade_token_blacklist (
                id            INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id       INTEGER NOT NULL,
                token_address TEXT    NOT NULL,
                added_at      TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                UNIQUE(user_id, token_address)
            )
        """)

        await db.execute("""
            CREATE TABLE IF NOT EXISTS copy_trade_token_whitelist (
                id            INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id       INTEGER NOT NULL,
                token_address TEXT    NOT NULL,
                added_at      TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                UNIQUE(user_id, token_address)
            )
        """)

        await db.execute("""
            CREATE TABLE IF NOT EXISTS processed_copy_txs (
                tx_signature   TEXT    NOT NULL,
                user_id        INTEGER NOT NULL,
                wallet_address TEXT    NOT NULL,
                token_mint     TEXT    NOT NULL,
                direction      TEXT    NOT NULL,
                processed_at   TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                PRIMARY KEY (tx_signature, user_id)
            )
        """)

        await db.execute("""
            CREATE TABLE IF NOT EXISTS copy_trade_jobs (
                id                   INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id              INTEGER NOT NULL,
                followed_wallet      TEXT    NOT NULL,
                token_address        TEXT    NOT NULL,
                direction            TEXT    NOT NULL,
                leader_amount_sol    REAL    DEFAULT 0.0,
                copy_amount_sol      REAL    DEFAULT 0.0,
                status               TEXT    DEFAULT 'queued',
                skip_reason          TEXT    DEFAULT '',
                tx_signature         TEXT    DEFAULT '',
                source_tx_signature  TEXT    DEFAULT '',
                created_at           TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                executed_at          TIMESTAMP
            )
        """)

        # ── Copy trade indexes ────────────────────────────────────────────────
        await db.execute(
            "CREATE INDEX IF NOT EXISTS idx_ct_wallets_user   ON copy_trade_wallets(user_id)"
        )
        await db.execute(
            "CREATE INDEX IF NOT EXISTS idx_ct_wallets_addr   ON copy_trade_wallets(wallet_address)"
        )
        await db.execute(
            "CREATE INDEX IF NOT EXISTS idx_ct_jobs_user      ON copy_trade_jobs(user_id)"
        )
        await db.execute(
            "CREATE INDEX IF NOT EXISTS idx_processed_txs     ON processed_copy_txs(tx_signature, user_id)"
        )

        # ══════════════════════════════════════════════════════════════════════
        # DRAGON INTEL — WALLET DISCOVERY TABLES
        # ══════════════════════════════════════════════════════════════════════

        # System-discovered wallets with computed scores (refreshed daily)
        await db.execute("""
            CREATE TABLE IF NOT EXISTS discovered_wallets (
                id              INTEGER PRIMARY KEY AUTOINCREMENT,
                wallet_address  TEXT    NOT NULL UNIQUE,
                preset_key      TEXT    NOT NULL,   -- 'hot_today'|'consistent'|'snipers'|'high_pnl'
                win_rate        REAL    DEFAULT 0,
                pnl_7d          REAL    DEFAULT 0,
                pnl_30d         REAL    DEFAULT 0,
                appearances     INTEGER DEFAULT 1,  -- times seen as top trader across tokens
                avg_hold_secs   REAL    DEFAULT 0,
                tags            TEXT    DEFAULT '',  -- JSON list
                intel_score     REAL    DEFAULT 0,   -- composite ranking score
                discovered_at   TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                last_updated    TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)

        # Per-user subscriptions to system presets
        await db.execute("""
            CREATE TABLE IF NOT EXISTS wallet_preset_subscriptions (
                id           INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id      INTEGER NOT NULL,
                preset_key   TEXT    NOT NULL,
                subscribed_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                active       INTEGER DEFAULT 1,
                UNIQUE(user_id, preset_key)
            )
        """)

        # Log of each discovery run
        await db.execute("""
            CREATE TABLE IF NOT EXISTS discovery_runs (
                id              INTEGER PRIMARY KEY AUTOINCREMENT,
                started_at      TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                finished_at     TIMESTAMP,
                tokens_scanned  INTEGER DEFAULT 0,
                wallets_found   INTEGER DEFAULT 0,
                status          TEXT    DEFAULT 'running'
            )
        """)

        await db.execute(
            "CREATE INDEX IF NOT EXISTS idx_discovered_preset ON discovered_wallets(preset_key)"
        )
        await db.execute(
            "CREATE INDEX IF NOT EXISTS idx_discovered_score  ON discovered_wallets(intel_score DESC)"
        )
        await db.execute(
            "CREATE INDEX IF NOT EXISTS idx_preset_subs_user  ON wallet_preset_subscriptions(user_id)"
        )

        # ══════════════════════════════════════════════════════════════════════
        # CANDLE SNIPER TABLES
        # ══════════════════════════════════════════════════════════════════════

        # Per-user Candle Sniper configuration & mode override settings
        await db.execute("""
            CREATE TABLE IF NOT EXISTS candle_sniper_settings (
                user_id                 INTEGER PRIMARY KEY,
                enabled                 INTEGER DEFAULT 0,
                strategy_profile        TEXT    DEFAULT 'balanced',
                timeframe               TEXT    DEFAULT '5m',
                scan_window             INTEGER DEFAULT 20,
                min_confirmations       INTEGER DEFAULT 3,
                confidence_threshold    INTEGER DEFAULT 45,
                auto_buy                INTEGER DEFAULT 0,
                max_open_positions      INTEGER DEFAULT 5,
                trade_size_sol          REAL    DEFAULT 0.05,
                stop_loss_pct           REAL    DEFAULT 15.0,
                take_profit_pct         REAL    DEFAULT 50.0,
                trailing_stop_pct       REAL    DEFAULT 10.0,
                slippage_pct            REAL    DEFAULT 5.0,
                cooldown_seconds        INTEGER DEFAULT 300,
                restore_previous_config INTEGER DEFAULT 1,
                surge_enabled           INTEGER DEFAULT 0,
                surge_threshold_pct     REAL    DEFAULT 500.0,
                surge_track_hours       INTEGER DEFAULT 24,
                updated_at              TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)

        # Snapshot of sniper_settings captured when CS mode is enabled
        # Restored automatically when CS mode is disabled (if restore_previous_config = 1)
        await db.execute("""
            CREATE TABLE IF NOT EXISTS candle_sniper_previous_config (
                user_id       INTEGER PRIMARY KEY,
                settings_json TEXT,
                saved_at      TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)

        # Scored token candidates from the CS discovery engine (shared across users)
        await db.execute("""
            CREATE TABLE IF NOT EXISTS candle_sniper_candidates (
                id               INTEGER PRIMARY KEY AUTOINCREMENT,
                token_address    TEXT    NOT NULL,
                token_name       TEXT    DEFAULT '',
                token_symbol     TEXT    DEFAULT '',
                composite_score  REAL    DEFAULT 0,
                equations_passed INTEGER DEFAULT 0,
                equations_json   TEXT    DEFAULT '{}',
                liquidity_usd    REAL    DEFAULT 0,
                volume_h1        REAL    DEFAULT 0,
                buy_ratio_h1     REAL    DEFAULT 0,
                age_minutes      INTEGER DEFAULT 0,
                strategy_profile TEXT    DEFAULT 'balanced',
                discovered_at    TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                expires_at       TIMESTAMP,
                status           TEXT    DEFAULT 'active'
            )
        """)

        # Open Candle Sniper positions (separate from regular tracked_positions)
        await db.execute("""
            CREATE TABLE IF NOT EXISTS candle_sniper_positions (
                id                   INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id              INTEGER NOT NULL,
                token_address        TEXT    NOT NULL,
                candidate_id         INTEGER,
                entry_price_sol      REAL    DEFAULT 0,
                current_price_sol    REAL    DEFAULT 0,
                highest_price_sol    REAL    DEFAULT 0,
                trade_size_sol       REAL    DEFAULT 0,
                stop_loss_pct        REAL    DEFAULT 15.0,
                take_profit_pct      REAL    DEFAULT 50.0,
                trailing_stop_pct    REAL    DEFAULT 10.0,
                trailing_active      INTEGER DEFAULT 0,
                tp_fired             INTEGER DEFAULT 0,
                sl_fired             INTEGER DEFAULT 0,
                tx_signature         TEXT    DEFAULT '',
                status               TEXT    DEFAULT 'open',
                exit_reason          TEXT    DEFAULT '',
                max_duration_minutes INTEGER DEFAULT 120,
                opened_at            TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                closed_at            TIMESTAMP
            )
        """)

        # Per-user custom watchlist additions on top of pump.fun market cap discovery
        await db.execute("""
            CREATE TABLE IF NOT EXISTS candle_sniper_watchlist (
                id            INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id       INTEGER NOT NULL,
                token_address TEXT    NOT NULL,
                token_symbol  TEXT    DEFAULT '',
                token_name    TEXT    DEFAULT '',
                added_at      TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                UNIQUE(user_id, token_address)
            )
        """)

        # ── Candle Sniper indexes ─────────────────────────────────────────────
        await db.execute(
            "CREATE INDEX IF NOT EXISTS idx_cs_candidates_status  ON candle_sniper_candidates(status)"
        )
        await db.execute(
            "CREATE INDEX IF NOT EXISTS idx_cs_candidates_score   ON candle_sniper_candidates(composite_score DESC)"
        )
        await db.execute(
            "CREATE INDEX IF NOT EXISTS idx_cs_positions_user     ON candle_sniper_positions(user_id)"
        )
        await db.execute(
            "CREATE INDEX IF NOT EXISTS idx_cs_positions_status   ON candle_sniper_positions(status)"
        )
        await db.execute(
            "CREATE INDEX IF NOT EXISTS idx_cs_watchlist_user     ON candle_sniper_watchlist(user_id)"
        )

        # Token price snapshots for surge detection
        # Records price the first time a token is seen in a discovery cycle.
        # Surge loop re-checks every 10 min and fires a buy if price has risen >= threshold.
        await db.execute("""
            CREATE TABLE IF NOT EXISTS cs_price_history (
                id              INTEGER PRIMARY KEY AUTOINCREMENT,
                token_address   TEXT    NOT NULL,
                token_symbol    TEXT    DEFAULT '',
                price_usd       REAL    DEFAULT 0.0,
                market_cap_usd  REAL    DEFAULT 0.0,
                recorded_at     TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                expires_at      TIMESTAMP NOT NULL,
                alerted         INTEGER DEFAULT 0,
                global_alerted  INTEGER DEFAULT 0,
                UNIQUE(token_address)
            )
        """)
        await db.execute(
            "CREATE INDEX IF NOT EXISTS idx_cs_price_history_exp ON cs_price_history(expires_at)"
        )
        # Migration: add global_alerted column to existing databases
        try:
            await db.execute(
                "ALTER TABLE cs_price_history ADD COLUMN global_alerted INTEGER DEFAULT 0"
            )
            await db.commit()
        except Exception:
            pass  # column already exists

        # ── Migrate sniper_watch_targets: add price alert columns ────────────
        _watch_new_cols = [
            "ALTER TABLE sniper_watch_targets ADD COLUMN token_symbol    TEXT    DEFAULT ''",
            "ALTER TABLE sniper_watch_targets ADD COLUMN alert_drop_pct  REAL    DEFAULT 20.0",
            "ALTER TABLE sniper_watch_targets ADD COLUMN alert_pump_pct  REAL    DEFAULT 100.0",
            "ALTER TABLE sniper_watch_targets ADD COLUMN quick_buy_sol   REAL    DEFAULT 0.05",
            "ALTER TABLE sniper_watch_targets ADD COLUMN entry_price_sol REAL    DEFAULT 0",
            "ALTER TABLE sniper_watch_targets ADD COLUMN last_price_sol  REAL    DEFAULT 0",
            "ALTER TABLE sniper_watch_targets ADD COLUMN alert_enabled   INTEGER DEFAULT 1",
            "ALTER TABLE sniper_watch_targets ADD COLUMN last_alerted_at TIMESTAMP",
        ]
        for col_sql in _watch_new_cols:
            try:
                await db.execute(col_sql)
            except Exception:
                pass  # Column already exists

        # ══════════════════════════════════════════════════════════════════════
        # SOL PAYMENT — TIMED SUPREME BLACK ACCESS
        # ══════════════════════════════════════════════════════════════════════

        await db.execute("""
            CREATE TABLE IF NOT EXISTS sol_payment_pending (
                user_id        INTEGER NOT NULL UNIQUE,
                expected_sol   REAL    NOT NULL,
                duration_hours INTEGER NOT NULL,
                from_wallet    TEXT    NOT NULL,
                initiated_at   TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                expires_at     TIMESTAMP NOT NULL
            )
        """)

        await db.execute("""
            CREATE TABLE IF NOT EXISTS processed_sol_txs (
                id           INTEGER PRIMARY KEY AUTOINCREMENT,
                tx_signature TEXT    NOT NULL UNIQUE,
                user_id      INTEGER NOT NULL,
                processed_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)

        await db.execute(
            "CREATE INDEX IF NOT EXISTS idx_sol_txs_sig ON processed_sol_txs(tx_signature)"
        )

        # ══════════════════════════════════════════════════════════════════════
        # AFFILIATE / REFERRAL SYSTEM TABLES
        # These are ADDITIVE — they do NOT modify or replace the burn access
        # system. Burn access (burn_activations, holder_access, wallet_links)
        # remains fully intact and independent.
        # ══════════════════════════════════════════════════════════════════════

        # Per-wallet affiliate stats and tier tracking
        await db.execute("""
            CREATE TABLE IF NOT EXISTS affiliate_profiles (
                id                          INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id                     INTEGER,
                telegram_username           TEXT,
                affiliate_wallet_address    TEXT    NOT NULL UNIQUE,
                total_referrals             INTEGER DEFAULT 0,
                total_commission_earned_usd REAL    DEFAULT 0,
                total_commission_paid_usd   REAL    DEFAULT 0,
                unpaid_commission_usd       REAL    DEFAULT 0,
                current_tier                TEXT    DEFAULT 'None',
                highest_tier                TEXT    DEFAULT 'None',
                created_at                  TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                updated_at                  TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)

        # One record per referred user — tracks which affiliate wallet referred them
        await db.execute("""
            CREATE TABLE IF NOT EXISTS referral_events (
                id                          INTEGER PRIMARY KEY AUTOINCREMENT,
                referred_user_id            INTEGER NOT NULL UNIQUE,
                affiliate_wallet_address    TEXT    NOT NULL,
                supreme_signup_status       TEXT    DEFAULT 'pending',
                affiliate_commission_eligible INTEGER DEFAULT 0,
                created_at                  TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                updated_at                  TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)

        # $100 qualifying payment records — separate from burn_activations
        # burn_access_verified and supreme_payment_verified are distinct states
        await db.execute("""
            CREATE TABLE IF NOT EXISTS supreme_payment_verifications (
                id                  INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id             INTEGER NOT NULL,
                payment_amount_usd  REAL    DEFAULT 100.0,
                payment_amount_sol  REAL    NOT NULL,
                payment_tx_hash     TEXT    UNIQUE,
                payment_status      TEXT    DEFAULT 'pending',
                verified_at         TIMESTAMP,
                created_at          TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                updated_at          TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)

        # Commission ledger — one entry per confirmed qualifying payment
        # UNIQUE(referred_user_id) prevents duplicate commissions
        await db.execute("""
            CREATE TABLE IF NOT EXISTS commission_ledger (
                id                          INTEGER PRIMARY KEY AUTOINCREMENT,
                affiliate_wallet_address    TEXT    NOT NULL,
                referred_user_id            INTEGER NOT NULL UNIQUE,
                commission_amount_usd       REAL    DEFAULT 21.0,
                commission_status           TEXT    DEFAULT 'pending',
                payout_tx_hash              TEXT,
                created_at                  TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                updated_at                  TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)

        # Pending $100 Supreme signup payments (parallel to sol_payment_pending)
        # Expires after 30 minutes if not confirmed
        await db.execute("""
            CREATE TABLE IF NOT EXISTS affiliate_signup_pending (
                user_id          INTEGER NOT NULL UNIQUE,
                from_wallet      TEXT    NOT NULL,
                expected_sol     REAL    NOT NULL,
                affiliate_wallet TEXT,
                initiated_at     TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                expires_at       TIMESTAMP NOT NULL
            )
        """)

        # ── Affiliate indexes ──────────────────────────────────────────────────
        await db.execute(
            "CREATE INDEX IF NOT EXISTS idx_affiliate_wallet   ON affiliate_profiles(affiliate_wallet_address)"
        )
        await db.execute(
            "CREATE INDEX IF NOT EXISTS idx_referral_user      ON referral_events(referred_user_id)"
        )
        await db.execute(
            "CREATE INDEX IF NOT EXISTS idx_referral_affiliate ON referral_events(affiliate_wallet_address)"
        )
        await db.execute(
            "CREATE INDEX IF NOT EXISTS idx_commission_wallet  ON commission_ledger(affiliate_wallet_address)"
        )
        await db.execute(
            "CREATE INDEX IF NOT EXISTS idx_spv_user           ON supreme_payment_verifications(user_id)"
        )

        # ── Persistent FSM Storage ─────────────────────────────────────────────
        # Keeps aiogram FSM states alive across bot restarts.
        # Prevents "session expired" when users are mid-flow (affiliate signup,
        # sniper settings, supreme activation, etc.) and the bot restarts.

        await db.execute("""
            CREATE TABLE IF NOT EXISTS fsm_states (
                chat_id    INTEGER NOT NULL,
                user_id    INTEGER NOT NULL,
                bot_id     INTEGER NOT NULL,
                state      TEXT,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                PRIMARY KEY (chat_id, user_id, bot_id)
            )
        """)

        await db.execute("""
            CREATE TABLE IF NOT EXISTS fsm_data (
                chat_id    INTEGER NOT NULL,
                user_id    INTEGER NOT NULL,
                bot_id     INTEGER NOT NULL,
                data       TEXT DEFAULT '{}',
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                PRIMARY KEY (chat_id, user_id, bot_id)
            )
        """)

        await db.commit()
        logger.info("Database initialized — all tables ready.")
