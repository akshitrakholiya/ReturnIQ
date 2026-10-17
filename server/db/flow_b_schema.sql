-- ReturnIQ · Flow B schema. Applied after schema.sql by scripts/init_db.py.

-- "Now" for every report window. REPORT_AS_OF (passed by the API as the returniq.as_of setting)
-- pins it to a date so demo data never ages out of the 90-day window; unset = now().
CREATE FUNCTION returniq_as_of() RETURNS timestamptz LANGUAGE sql STABLE AS $$
  SELECT COALESCE(NULLIF(current_setting('returniq.as_of', true), '')::timestamptz, now())
$$;

-- Flow B
CREATE TYPE report_run_status AS ENUM ('gathering', 'finding_causes', 'preparing_fixes', 'done', 'failed');
CREATE TYPE report_status     AS ENUM ('analyzed', 'not_enough_data', 'healthy');

CREATE SEQUENCE listing_change_seq; CREATE SEQUENCE pack_seq; CREATE SEQUENCE report_seq;
CREATE SEQUENCE report_run_seq;     CREATE SEQUENCE qa_seq;

-- Per-category cost of one return, used for the ₹ impact calculation.
CREATE TABLE cost_model (
  category          text PRIMARY KEY REFERENCES category_profile(category),
  reverse_shipping  numeric(10,2) NOT NULL CHECK (reverse_shipping >= 0),
  restocking        numeric(10,2) NOT NULL CHECK (restocking >= 0),
  write_off_rate    numeric(3,2)  NOT NULL CHECK (write_off_rate BETWEEN 0 AND 1),
  margin            numeric(10,2) NOT NULL CHECK (margin >= 0)  -- lost margin per write-off
);

CREATE TABLE listing_change (
  id          text PRIMARY KEY DEFAULT 'lc_' || nextval('listing_change_seq'),
  product_id  text NOT NULL REFERENCES product(id) ON DELETE CASCADE,
  field       text NOT NULL,
  old_value   text,
  new_value   text,
  changed_at  timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX listing_change_product_idx ON listing_change (product_id, changed_at);

-- ───────────── Flow B outputs ─────────────
CREATE TABLE evidence_pack (
  id                  text PRIMARY KEY DEFAULT 'pack_' || nextval('pack_seq'),
  product_id          text NOT NULL REFERENCES product(id) ON DELETE CASCADE,
  period              text NOT NULL DEFAULT 'last_90d',
  items               jsonb NOT NULL,               -- {"metrics": {...}, "breakdown:size": {...}, ...}
  completeness_notes  jsonb NOT NULL DEFAULT '[]',
  created_at          timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX evidence_pack_product_idx ON evidence_pack (product_id, created_at);

CREATE TABLE product_report (
  id                    text PRIMARY KEY DEFAULT 'rep_' || nextval('report_seq'),
  product_id            text NOT NULL REFERENCES product(id) ON DELETE CASCADE,
  evidence_pack_id      text REFERENCES evidence_pack(id),
  is_current            boolean NOT NULL DEFAULT true,
  status                report_status NOT NULL,
  report                jsonb NOT NULL,             -- ProductReport JSON
  returns_count_at_build integer NOT NULL,          -- reviewed returns, for the "3 new" rebuild rule
  model_version         text,
  created_at            timestamptz NOT NULL DEFAULT now()
);
CREATE UNIQUE INDEX product_report_current_idx
  ON product_report (product_id) WHERE is_current;

CREATE TABLE report_run (
  id           text PRIMARY KEY DEFAULT 'rr_' || nextval('report_run_seq'),
  product_id   text NOT NULL REFERENCES product(id) ON DELETE CASCADE,
  status       report_run_status NOT NULL DEFAULT 'gathering',
  report_id    text REFERENCES product_report(id),
  error        text,
  started_at   timestamptz NOT NULL DEFAULT now(),
  finished_at  timestamptz
);
CREATE INDEX report_run_product_idx ON report_run (product_id, started_at);
-- One active run per product (the API also takes an advisory lock before starting one).
CREATE UNIQUE INDEX report_run_active_idx ON report_run (product_id)
  WHERE status IN ('gathering', 'finding_causes', 'preparing_fixes');

CREATE TABLE product_qa (
  id          text PRIMARY KEY DEFAULT 'qa_' || nextval('qa_seq'),
  product_id  text NOT NULL REFERENCES product(id) ON DELETE CASCADE,
  session_id  text NOT NULL,
  question    text NOT NULL,
  answer      jsonb NOT NULL,                       -- QAAnswer JSON
  tool_calls  jsonb NOT NULL DEFAULT '[]',
  created_at  timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX product_qa_session_idx ON product_qa (product_id, session_id, created_at);


-- Return rate is by order cohort: of orders placed in the last 90 days, how many came back.
CREATE VIEW v_product_metrics_90d AS
SELECT p.id AS product_id, p.seller_id, p.category, p.name,
       count(o.id)  AS orders,
       count(r.id)  AS returns,
       CASE WHEN count(o.id) = 0 THEN 0
            ELSE round(count(r.id)::numeric / count(o.id), 4) END AS return_rate
FROM product p
LEFT JOIN orders  o ON o.product_id = p.id AND o.order_date >= returniq_as_of() - interval '90 days' AND o.order_date < returniq_as_of()
LEFT JOIN returns r ON r.order_id = o.id
GROUP BY p.id;

CREATE VIEW v_category_baseline_90d AS
SELECT category,
       sum(orders)  AS orders,
       sum(returns) AS returns,
       CASE WHEN sum(orders) = 0 THEN 0
            ELSE round(sum(returns)::numeric / sum(orders), 4) END AS return_rate
FROM v_product_metrics_90d
GROUP BY category;

-- Seller "My Products" list: orders, returns, rate and top cause per product.
CREATE VIEW v_seller_product_list AS
SELECT m.product_id, m.seller_id, m.category, m.name,
       m.orders, m.returns, m.return_rate,
       (SELECT ec.cause
          FROM returns r
          JOIN orders o ON o.id = r.order_id AND o.order_date >= returniq_as_of() - interval '90 days' AND o.order_date < returniq_as_of()
          JOIN v_return_effective_cause ec ON ec.return_id = r.id
         WHERE r.product_id = m.product_id AND ec.cause IS NOT NULL
         GROUP BY ec.cause ORDER BY count(*) DESC, ec.cause LIMIT 1) AS top_cause
FROM v_product_metrics_90d m;


GRANT SELECT ON cost_model, listing_change, evidence_pack, product_report, product_qa,
                v_product_metrics_90d, v_category_baseline_90d, v_seller_product_list
  TO returniq_tools;
