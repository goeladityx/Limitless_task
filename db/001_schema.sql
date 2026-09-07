-- Step 5, part 1: the tables.
--
-- Two layers.
--   src_*      exactly what came out of sources/. Ugly on purpose. Text dates, quintals,
--              free-text party names. Nothing is cleaned on the way in, so we can always
--              show a controller the row exactly as it appeared in his own system.
--   everything else  what we build on top: resolved parties and items, classified
--              purchases, definitions, checks, and the log of what we told people.
--
-- Every table carries tenant_id. Row level security is in 002_rls.sql.

BEGIN;

CREATE TABLE IF NOT EXISTS tenant (
    tenant_id   text PRIMARY KEY,
    name        text NOT NULL,
    created_at  timestamptz NOT NULL DEFAULT now()
);

-- ============================================================ src: Tally
CREATE TABLE IF NOT EXISTS src_tally_ledger (
    tenant_id       text NOT NULL,
    ledger_name     text NOT NULL,
    parent_group    text,
    gstin           text,                    -- blank on roughly one in five
    opening_balance numeric,
    PRIMARY KEY (tenant_id, ledger_name)
);

CREATE TABLE IF NOT EXISTS src_tally_stock_item (
    tenant_id     text NOT NULL,
    item_name     text NOT NULL,
    parent_group  text,
    PRIMARY KEY (tenant_id, item_name)
);

CREATE TABLE IF NOT EXISTS src_tally_voucher (
    tenant_id     text NOT NULL,
    guid          text NOT NULL,
    voucher_type  text NOT NULL,             -- Purchase / Sales / Receipt / Credit Note / Payment
    vch_no        integer,
    vch_date      text NOT NULL,             -- TEXT, as Tally stores it: 21-Apr-2023
    ledger_name   text NOT NULL,
    amount        numeric,
    dr_cr         text,
    narration     text,
    entered_at    text,                      -- when it was typed in. Differs on the back-dated rows
    PRIMARY KEY (tenant_id, guid)
);

CREATE TABLE IF NOT EXISTS src_tally_inventory_entry (
    tenant_id        text NOT NULL,
    guid             text NOT NULL,
    voucher_guid     text NOT NULL,
    stock_item_name  text,
    qty_qtl          numeric,                -- QUINTALS. Ten to a tonne
    rate             numeric,
    PRIMARY KEY (tenant_id, guid)
);

-- ============================================================ src: the registers
CREATE TABLE IF NOT EXISTS src_dispatch_register (
    tenant_id     text NOT NULL,
    dispatch_no   text NOT NULL,
    dispatch_date date,
    vehicle_no    text,
    grade_code    text,
    destination   text,                      -- typed in caps, never matches the ledger exactly
    tender_ref    text,                      -- blank on ~60 rows
    qty_gross_t   numeric,
    qty_net_t     numeric,                   -- this one is the delivered tonnage
    invoice_no    text,                      -- blank where nothing was raised
    PRIMARY KEY (tenant_id, dispatch_no)
);

CREATE TABLE IF NOT EXISTS src_production_register (
    tenant_id            text NOT NULL,
    month                text NOT NULL,
    grade_code           text,
    opening_stock_t      numeric,
    planned_qty_t        numeric,
    actual_qty_t         numeric,
    feedstock_consumed_t numeric,
    PRIMARY KEY (tenant_id, month)
);

CREATE TABLE IF NOT EXISTS src_tender_award (
    tenant_id     text NOT NULL,
    tender_ref    text NOT NULL,
    plant         text,
    grade_code    text,
    tonnes        numeric,
    window_start  date,
    window_end    date,
    rate_per_t    numeric,
    freight_per_t numeric,
    quoted_gcv    numeric,                   -- rate_per_t / quoted_gcv = rupees per GCV
    option_pct    numeric,
    loa_no        text,
    -- The two kinds of contract are not the same promise, and treating them the same is
    -- how you invent an obligation nobody made.
    --   cumulative : a government tender. One total, one deadline. The producer decides
    --                which month each load goes out in. No monthly promise exists.
    --   scheduled  : a private buyer. A fixed draw every month, written into the contract.
    --                That one really is a monthly promise and missing it is a breach.
    contract_type text,
    PRIMARY KEY (tenant_id, tender_ref)
);

-- The numbers a plant manager would give you off the top of his head, and which change
-- from company to company: how much residue makes a tonne of pellets, what conversion
-- costs, where the GCV bands sit. Typed into Python they are quietly wrong for the second
-- customer, so they live here.
CREATE TABLE IF NOT EXISTS src_config (
    tenant_id text NOT NULL,
    key       text NOT NULL,
    value     text,
    note      text,
    PRIMARY KEY (tenant_id, key)
);

-- What each buyer's contract says about when the money comes. A PSU pays thirty days after
-- acceptance and a bottling plant pays in fifteen, and an owner planning his cash cannot
-- treat those the same. It is in the contract, so it belongs in a table, not in a constant.
CREATE TABLE IF NOT EXISTS src_buyer_terms (
    tenant_id   text NOT NULL,
    ledger_name text NOT NULL,               -- the name as it appears on the sales voucher
    buyer       text,
    kind        text,                        -- psu or private
    pay_days    integer,
    PRIMARY KEY (tenant_id, ledger_name)
);

-- Only scheduled contracts have this. If a tender_ref has no rows here, nothing is owed
-- in any particular month, only by the deadline.
CREATE TABLE IF NOT EXISTS src_contract_schedule (
    tenant_id  text NOT NULL,
    tender_ref text NOT NULL,
    month      text NOT NULL,               -- YYYY-MM
    qty_t      numeric,
    PRIMARY KEY (tenant_id, tender_ref, month)
);

CREATE TABLE IF NOT EXISTS src_goods_receipt (
    tenant_id     text NOT NULL,
    grn_no        text NOT NULL,
    received_date date,
    vendor_name   text,
    qty_qtl       numeric,                   -- quintals again
    rate          numeric,
    PRIMARY KEY (tenant_id, grn_no)
);

CREATE TABLE IF NOT EXISTS src_email (
    tenant_id  text NOT NULL,
    msg_id     text NOT NULL,
    thread_id  text,
    sent_at    date,
    from_addr  text,
    to_addr    text,
    subject    text,
    body       text,                         -- the commitment is a sentence in here
    PRIMARY KEY (tenant_id, msg_id)
);

-- ============================================================ what we build
CREATE TABLE IF NOT EXISTS party (
    tenant_id  text NOT NULL,
    party_id   bigserial,
    name       text NOT NULL,
    gstin      text,
    pan        text,
    kind       text NOT NULL CHECK (kind IN ('vendor', 'buyer')),
    PRIMARY KEY (tenant_id, party_id)
);

-- Keyed on the SOURCE system's own key, which is what makes a human correction survive
-- the next import instead of being guessed again.
CREATE TABLE IF NOT EXISTS party_link (
    tenant_id   text NOT NULL,
    system      text NOT NULL,               -- tally / dispatch_register / goods_receipt / email
    source_key  text NOT NULL,
    party_id    bigint NOT NULL,
    method      text NOT NULL CHECK (method IN ('gstin', 'pan', 'exact_name', 'human')),
    decided_by  text,
    decided_at  timestamptz DEFAULT now(),
    PRIMARY KEY (tenant_id, system, source_key)
);
-- Note there is no 'similarity' method. Similarity never decides, it only ever raises a
-- review_queue row for a person to confirm.

CREATE TABLE IF NOT EXISTS party_split (
    tenant_id     text NOT NULL,
    source_key_a  text NOT NULL,
    source_key_b  text NOT NULL,
    decided_by    text,
    decided_at    timestamptz DEFAULT now(),
    PRIMARY KEY (tenant_id, source_key_a, source_key_b)
);

CREATE TABLE IF NOT EXISTS item (
    tenant_id  text NOT NULL,
    item_id    bigserial,
    code       text NOT NULL,
    valid_from date NOT NULL,
    valid_to   date NOT NULL,
    made_from  text,
    gcv_min    numeric,
    gcv_typical numeric,
    gcv_max    numeric,
    kind       text CHECK (kind IN ('pellet', 'feedstock')),
    PRIMARY KEY (tenant_id, item_id)
);

-- Item identity is time dependent: PLT-A1 resolves to a different item before and after
-- the recipe changed. That is the only thing that catches the reused code.
CREATE TABLE IF NOT EXISTS item_link (
    tenant_id   text NOT NULL,
    system      text NOT NULL,
    source_key  text NOT NULL,
    txn_date    date NOT NULL,
    item_id     bigint NOT NULL,
    PRIMARY KEY (tenant_id, system, source_key, txn_date)
);

CREATE TABLE IF NOT EXISTS purchase (
    tenant_id      text NOT NULL,
    purchase_id    bigserial,
    src_guid       text NOT NULL,
    txn_date       date NOT NULL,
    entered_at     date,
    party_id       bigint,
    item_id        bigint,
    tonnes         numeric,
    amount         numeric,
    rate_per_t     numeric,
    channel        text CHECK (channel IN ('feedstock', 'finished')),   -- NULL is honest, not a failure
    channel_method text CHECK (channel_method IN ('item_master', 'rate_band', 'human')),
    PRIMARY KEY (tenant_id, purchase_id)
);
-- channel NULL means we could not tell. Any answer that touches a NULL-channel row is withheld.

CREATE TABLE IF NOT EXISTS dispatch (
    tenant_id     text NOT NULL,
    dispatch_id   bigserial,
    src_no        text NOT NULL,
    dispatch_date date NOT NULL,
    plant         text,
    item_id       bigint,
    tonnes        numeric,
    PRIMARY KEY (tenant_id, dispatch_id)
);

-- No row here means the dispatch is unattributed. There is deliberately no confidence
-- column, because if one existed somebody would eventually average over it.
CREATE TABLE IF NOT EXISTS dispatch_tender (
    tenant_id   text NOT NULL,
    -- The dispatch NUMBER from the register, not an internal id. That is what makes a
    -- human decision survive the next import: re-ingest replays the link instead of
    -- asking the same question again.
    dispatch_id text NOT NULL,
    tender_ref  text NOT NULL,
    method      text NOT NULL CHECK (method IN ('stated', 'only_candidate', 'rate_match', 'human')),
    decided_by  text,
    decided_at  timestamptz DEFAULT now(),
    PRIMARY KEY (tenant_id, dispatch_id)
);

-- Pulled out of email. Nothing counts until a person confirms it, and every row keeps the
-- sentence it came from so she can check it in two seconds.
CREATE TABLE IF NOT EXISTS vendor_commitment (
    tenant_id     text NOT NULL,
    commitment_id bigserial,
    party_id      bigint,
    item_id       bigint,
    qty_t         numeric,
    rate_agreed   numeric,
    promised_date date,
    source_msg_id text,
    source_quote  text,
    status        text NOT NULL DEFAULT 'proposed' CHECK (status IN ('proposed', 'confirmed', 'rejected')),
    confirmed_by  text,
    confirmed_at  timestamptz,
    PRIMARY KEY (tenant_id, commitment_id)
);

-- The one table the product writes to on the owner's behalf.
CREATE TABLE IF NOT EXISTS delivery_plan (
    tenant_id     text NOT NULL,
    tender_ref    text NOT NULL,
    month         text NOT NULL,
    planned_qty_t numeric,
    recorded_by   text,
    recorded_at   timestamptz DEFAULT now(),
    PRIMARY KEY (tenant_id, tender_ref, month)
);

CREATE TABLE IF NOT EXISTS review_queue (
    tenant_id   text NOT NULL,
    review_id   bigserial,
    kind        text NOT NULL,               -- party_match / purchase_channel / dispatch_tender / commitment
    subject_ref text NOT NULL,
    proposal    jsonb,
    status      text NOT NULL DEFAULT 'open' CHECK (status IN ('open', 'resolved', 'dismissed')),
    resolved_by text,
    resolved_at timestamptz,
    PRIMARY KEY (tenant_id, review_id)
);

-- Definitions are typed parameters, not stored SQL. A controller can review "do we count
-- the option clause or not". She cannot review a SQL string. Versioned, never updated in
-- place, so an answer given in June is still reproducible in December.
CREATE TABLE IF NOT EXISTS definitions (
    tenant_id  text NOT NULL,
    word       text NOT NULL,
    params     jsonb NOT NULL,
    valid_from date NOT NULL,
    valid_to   date,
    set_by     text,
    set_at     timestamptz DEFAULT now(),
    PRIMARY KEY (tenant_id, word, valid_from)
);

CREATE TABLE IF NOT EXISTS control_total (
    tenant_id  text NOT NULL,
    check_name text NOT NULL,
    period     text NOT NULL,
    expected   numeric,
    actual     numeric,
    status     text CHECK (status IN ('ok', 'failed')),
    checked_at timestamptz DEFAULT now(),
    PRIMARY KEY (tenant_id, check_name, period)
);

CREATE TABLE IF NOT EXISTS answer_log (
    tenant_id           text NOT NULL,
    answer_id           bigserial,
    question            text,
    plan                jsonb,
    definition_versions jsonb,
    verdict             text CHECK (verdict IN ('answered', 'withheld')),
    payload             jsonb,
    created_at          timestamptz DEFAULT now(),
    PRIMARY KEY (tenant_id, answer_id)
);

-- ============================================================ indexes
-- tenant_id leads every index, because the RLS predicate is applied on every scan and a
-- plan that ignores it degrades badly once there is more than one tenant.
CREATE INDEX IF NOT EXISTS ix_src_tally_voucher_tenant_id_voucher_type_ledger_name ON src_tally_voucher (tenant_id, voucher_type, ledger_name);
CREATE INDEX IF NOT EXISTS ix_src_tally_inventory_entry_tenant_id_voucher_guid ON src_tally_inventory_entry (tenant_id, voucher_guid);
CREATE INDEX IF NOT EXISTS ix_src_dispatch_register_tenant_id_dispatch_date ON src_dispatch_register (tenant_id, dispatch_date);
CREATE INDEX IF NOT EXISTS ix_src_dispatch_register_tenant_id_tender_ref ON src_dispatch_register (tenant_id, tender_ref);
CREATE INDEX IF NOT EXISTS ix_src_email_tenant_id_thread_id ON src_email (tenant_id, thread_id);
CREATE INDEX IF NOT EXISTS ix_purchase_tenant_id_txn_date ON purchase (tenant_id, txn_date);
CREATE INDEX IF NOT EXISTS ix_purchase_tenant_id_channel ON purchase (tenant_id, channel);
CREATE INDEX IF NOT EXISTS ix_dispatch_tenant_id_dispatch_date ON dispatch (tenant_id, dispatch_date);
CREATE INDEX IF NOT EXISTS ix_vendor_commitment_tenant_id_status ON vendor_commitment (tenant_id, status);
CREATE INDEX IF NOT EXISTS ix_review_queue_tenant_id_status ON review_queue (tenant_id, status);

COMMIT;


-- ---------------------------------------------------------------------------------------
-- Columns added after the tables were first written.
--
-- CREATE TABLE IF NOT EXISTS does nothing at all to a table that already exists, so a
-- column added later has to be said twice: once in the CREATE above for a fresh database,
-- and once here for one that already has the table. Both forms are idempotent, which is
-- what lets this file run against an empty database and against yesterday's.
--
-- These live at the end because an ALTER cannot run before its own CREATE, and putting one
-- next to the table it belongs to reads better right up until somebody clones the repo and
-- the very first migration fails.
-- ---------------------------------------------------------------------------------------
ALTER TABLE src_tender_award ADD COLUMN IF NOT EXISTS contract_type text;

-- What was actually bought, once somebody has said so. Null until then, because the books
-- do not record it and a guess here is a wrong cost per unit of energy later.
ALTER TABLE purchase       ADD COLUMN IF NOT EXISTS material text;
