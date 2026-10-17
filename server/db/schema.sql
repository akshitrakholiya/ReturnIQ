-- ReturnIQ · Phase 1 schema (Flow A only; Flow B lives in db/flow_b_schema.sql) · AlloyDB / AlloyDB Omni / PostgreSQL 14+
-- IDs are prefixed text (r_101, m_123, o_456) so evidence refs in agent output
-- match primary keys exactly and the citation check is a plain lookup.
-- Apply with: python -m scripts.init_db   (use --reset to drop and recreate)

-- ───────────── Enums ─────────────
CREATE TYPE root_cause AS ENUM (
  'size_fit', 'defect_quality', 'damaged_in_transit', 'wrong_item',
  'not_as_described', 'changed_mind', 'suspicious', 'other'
);
CREATE TYPE return_status AS ENUM (
  'pending_analysis', 'analyzing', 'awaiting_review', 'reviewed', 'analysis_failed'
);
CREATE TYPE recommended_action AS ENUM (
  'approve_return', 'request_more_evidence', 'reject_return', 'manual_review'
);
CREATE TYPE review_decision AS ENUM ('accepted', 'rejected');
CREATE TYPE media_type      AS ENUM ('photo', 'video');
CREATE TYPE severity_level  AS ENUM ('none', 'low', 'medium', 'high');
CREATE TYPE agent_name      AS ENUM ('return', 'rca', 'solution', 'qa');
CREATE TYPE run_status      AS ENUM ('running', 'succeeded', 'failed');

-- ───────────── Sequences for prefixed IDs ─────────────
CREATE SEQUENCE seller_seq;   CREATE SEQUENCE customer_seq; CREATE SEQUENCE product_seq;
CREATE SEQUENCE orders_seq;   CREATE SEQUENCE shipment_seq; CREATE SEQUENCE returns_seq;
CREATE SEQUENCE media_seq;    CREATE SEQUENCE finding_seq;  CREATE SEQUENCE analysis_seq;
CREATE SEQUENCE run_seq;     CREATE SEQUENCE eval_seq;

-- ───────────── Reference data ─────────────
CREATE TABLE seller (
  id          text PRIMARY KEY DEFAULT 's_' || nextval('seller_seq'),
  name        text NOT NULL,
  created_at  timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE category_profile (
  category            text PRIMARY KEY,           -- 'apparel', 'footwear', ...
  variant_dimensions  jsonb NOT NULL,             -- ["size","color"]
  key_attributes      jsonb NOT NULL,             -- ["size_chart","material"]
  media_focus         text  NOT NULL,             -- passed to analyze_media()
  listing_checks      jsonb NOT NULL,
  updated_at          timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE policy (
  id       text PRIMARY KEY,                      -- 'policy_2.1'
  section  text NOT NULL UNIQUE,                  -- '2.1'
  title    text NOT NULL,
  text     text NOT NULL,
  tsv      tsvector GENERATED ALWAYS AS
           (to_tsvector('english', title || ' ' || text)) STORED
);
CREATE INDEX policy_tsv_idx ON policy USING gin (tsv);

-- PII lives only here; tools never select name/email/phone.
CREATE TABLE customer (
  id          text PRIMARY KEY DEFAULT 'c_' || nextval('customer_seq'),
  name        text NOT NULL,
  email       text,
  phone       text,
  created_at  timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE product (
  id                  text PRIMARY KEY DEFAULT 'p_' || nextval('product_seq'),
  seller_id           text NOT NULL REFERENCES seller(id),
  category            text NOT NULL REFERENCES category_profile(category),
  name                text NOT NULL,
  description         text,
  attributes          jsonb NOT NULL DEFAULT '{}',  -- size chart / specs / dimensions
  listing_image_urls  text[] NOT NULL DEFAULT '{}',
  report_stale        boolean NOT NULL DEFAULT false, -- set by Flow A on review
  created_at          timestamptz NOT NULL DEFAULT now(),
  updated_at          timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX product_seller_idx ON product (seller_id);

-- ───────────── Transactions ─────────────
-- One product per order (order = order line) to keep Phase 1 simple.
CREATE TABLE orders (
  id           text PRIMARY KEY DEFAULT 'o_' || nextval('orders_seq'),
  customer_id  text NOT NULL REFERENCES customer(id),
  product_id   text NOT NULL REFERENCES product(id),
  variant      jsonb NOT NULL DEFAULT '{}',        -- {"size":"L","color":"navy"}
  batch_id     text,
  price        numeric(10,2) NOT NULL CHECK (price >= 0),
  order_date   timestamptz NOT NULL
);
CREATE INDEX orders_product_idx  ON orders (product_id, order_date);
CREATE INDEX orders_customer_idx ON orders (customer_id);
CREATE INDEX orders_batch_idx    ON orders (batch_id);

CREATE TABLE shipment (
  id              text PRIMARY KEY DEFAULT 'sh_' || nextval('shipment_seq'),
  order_id        text NOT NULL UNIQUE REFERENCES orders(id),
  warehouse       text NOT NULL,
  shipped_at      timestamptz,
  delivered_date  timestamptz,
  damage_flag     boolean NOT NULL DEFAULT false
);

-- One return per order. product_id/customer_id copied from the order
-- so Flow B breakdowns don't need a join for every query.
CREATE TABLE returns (
  id                 text PRIMARY KEY DEFAULT 'r_' || nextval('returns_seq'),
  order_id           text NOT NULL UNIQUE REFERENCES orders(id),
  product_id         text NOT NULL REFERENCES product(id),
  customer_id        text NOT NULL REFERENCES customer(id),
  stated_reason      root_cause NOT NULL CHECK (stated_reason <> 'suspicious'),
  comment            text,
  status             return_status NOT NULL DEFAULT 'pending_analysis',
  created_at         timestamptz NOT NULL DEFAULT now(),
  status_updated_at  timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX returns_queue_idx    ON returns (status, created_at);
CREATE INDEX returns_product_idx  ON returns (product_id, created_at);
CREATE INDEX returns_customer_idx ON returns (customer_id);

CREATE FUNCTION touch_return_status() RETURNS trigger AS $$
BEGIN
  IF NEW.status IS DISTINCT FROM OLD.status THEN
    NEW.status_updated_at := now();
  END IF;
  RETURN NEW;
END $$ LANGUAGE plpgsql;
CREATE TRIGGER returns_status_touch BEFORE UPDATE ON returns
  FOR EACH ROW EXECUTE FUNCTION touch_return_status();

CREATE TABLE return_media (
  id           text PRIMARY KEY DEFAULT 'm_' || nextval('media_seq'),
  return_id    text NOT NULL REFERENCES returns(id) ON DELETE CASCADE,
  type         media_type NOT NULL,
  storage_url  text NOT NULL,
  mime_type    text,
  size_bytes   bigint,
  created_at   timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX return_media_return_idx ON return_media (return_id);

-- ───────────── Agent traces (shared by all flows) ─────────────
CREATE TABLE agent_run (
  id            text PRIMARY KEY DEFAULT 'run_' || nextval('run_seq'),
  agent         agent_name NOT NULL,
  subject_type  text NOT NULL CHECK (subject_type IN ('return', 'product')),
  subject_id    text NOT NULL,                     -- r_101 or p_12
  attempt       smallint NOT NULL DEFAULT 1,
  status        run_status NOT NULL DEFAULT 'running',
  model         text,
  tool_calls    jsonb NOT NULL DEFAULT '[]',       -- ADK trace: name, args, result size, ms
  raw_output    jsonb,
  error         text,
  tokens_in     integer,
  tokens_out    integer,
  started_at    timestamptz NOT NULL DEFAULT now(),
  finished_at   timestamptz
);
CREATE INDEX agent_run_subject_idx ON agent_run (subject_type, subject_id, started_at);

-- ───────────── Flow A outputs ─────────────
-- History kept: a reanalysis adds a row and flips is_current.
CREATE TABLE return_analysis (
  id                   text PRIMARY KEY DEFAULT 'ra_' || nextval('analysis_seq'),
  return_id            text NOT NULL REFERENCES returns(id) ON DELETE CASCADE,
  agent_run_id         text REFERENCES agent_run(id),
  is_current           boolean NOT NULL DEFAULT true,
  root_cause           root_cause NOT NULL,
  reason_mismatch      boolean NOT NULL,
  confidence           numeric(3,2) NOT NULL CHECK (confidence BETWEEN 0 AND 1),
  explanation          text NOT NULL,
  evidence             jsonb NOT NULL DEFAULT '[]',  -- [{"ref","finding"}], refs checked
  context_notes        jsonb NOT NULL DEFAULT '[]',  -- completeness notes given to agent
  recommended_action   recommended_action NOT NULL,
  needs_manual_review  boolean NOT NULL,
  model_version        text,
  created_at           timestamptz NOT NULL DEFAULT now(),
  -- the < 0.6 rule, enforced in the DB as well as the API
  CHECK (confidence >= 0.60 OR needs_manual_review)
);
CREATE UNIQUE INDEX return_analysis_current_idx
  ON return_analysis (return_id) WHERE is_current;

-- One finding per media file per analysis; Flow B counts current ones in SQL.
CREATE TABLE media_finding (
  id               text PRIMARY KEY DEFAULT 'mf_' || nextval('finding_seq'),
  analysis_id      text NOT NULL REFERENCES return_analysis(id) ON DELETE CASCADE,
  return_id        text NOT NULL REFERENCES returns(id) ON DELETE CASCADE,
  media_id         text NOT NULL REFERENCES return_media(id) ON DELETE CASCADE,
  defect_type      text,                           -- 'sole_separation', 'stain', ...
  severity         severity_level NOT NULL DEFAULT 'none',
  visible_damage   boolean NOT NULL,
  matches_listing  boolean,                         -- null when not judgeable
  description      text NOT NULL,
  created_at       timestamptz NOT NULL DEFAULT now(),
  UNIQUE (analysis_id, media_id)
);
CREATE INDEX media_finding_return_idx ON media_finding (return_id);

-- One human decision per return. final_root_cause is always filled
-- (equals the AI cause when accepted) so Flow B never needs to infer it.
CREATE TABLE return_review (
  return_id         text PRIMARY KEY REFERENCES returns(id) ON DELETE CASCADE,
  analysis_id       text REFERENCES return_analysis(id), -- verdict the reviewer saw; null if analysis_failed
  decision          review_decision NOT NULL,
  final_root_cause  root_cause NOT NULL,
  note              text,
  reviewer          text NOT NULL,
  reviewed_at       timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE eval_label (
  id               text PRIMARY KEY DEFAULT 'ev_' || nextval('eval_seq'),
  subject_type     text NOT NULL CHECK (subject_type IN ('return', 'product')),
  subject_id       text NOT NULL,
  true_root_cause  root_cause,
  scenario         text,
  note             text
);
CREATE INDEX eval_label_subject_idx ON eval_label (subject_type, subject_id);

-- ───────────── Views ─────────────
-- Cause used by every breakdown: reviewed cause if present, else current AI cause.
CREATE VIEW v_return_effective_cause AS
SELECT r.id AS return_id, r.product_id,
       COALESCE(rv.final_root_cause, ra.root_cause) AS cause,
       (rv.return_id IS NOT NULL) AS is_reviewed
FROM returns r
LEFT JOIN return_review   rv ON rv.return_id = r.id
LEFT JOIN return_analysis ra ON ra.return_id = r.id AND ra.is_current;

-- ───────────── Read-only role for the tool layer ─────────────
-- The returniq_tools role is created by scripts/init_db.py (needs admin rights).
-- Agents' tools connect as this role: no writes, no customer PII, no eval labels.
GRANT USAGE ON SCHEMA public TO returniq_tools;
GRANT SELECT ON seller, category_profile, policy, product, orders, shipment, returns,
                return_media, return_analysis, media_finding, return_review,
                v_return_effective_cause
  TO returniq_tools;
GRANT SELECT (id, created_at) ON customer TO returniq_tools;
