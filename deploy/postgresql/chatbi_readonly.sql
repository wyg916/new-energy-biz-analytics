\set ON_ERROR_STOP on

-- Required psql variables:
--   target_database  Existing PostgreSQL database name.
--   chatbi_role      Role name managed by the deployment administrator.
-- The script never creates or stores a password. A LOGIN credential must be
-- attached by the external secret-management process before enabling runtime.

SELECT format(
  'CREATE ROLE %I NOLOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE NOREPLICATION NOBYPASSRLS',
  :'chatbi_role'
)
WHERE NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = :'chatbi_role')
\gexec

CREATE SCHEMA IF NOT EXISTS chatbi_semantic;

CREATE OR REPLACE VIEW chatbi_semantic.dim_station AS
SELECT station_id, station_name, city_id, region_id, operator_code, station_type,
       open_date, connector_count, rated_power_kw, status, source_type
FROM public.dim_station;

CREATE OR REPLACE VIEW chatbi_semantic.fact_charging_session AS
SELECT session_id, station_id, device_id, connector_no, user_id, start_time, end_time,
       settlement_time, charging_duration_seconds, energy_kwh,
       electricity_fee_net_amount, service_fee_net_amount, session_status,
       batch_id, source_type, created_at
FROM public.fact_charging_session;

CREATE OR REPLACE VIEW chatbi_semantic.fact_energy_cost AS
SELECT station_id, cost_date, tariff_period, purchase_price_per_kwh,
       settled_energy_kwh, energy_cost, batch_id, source_type
FROM public.fact_energy_cost;

CREATE OR REPLACE VIEW chatbi_semantic.fact_operation_expense AS
SELECT station_id, expense_date, expense_type, amount, is_variable,
       allocation_rule, batch_id, source_type
FROM public.fact_operation_expense;

CREATE OR REPLACE VIEW chatbi_semantic.fact_device_status_event AS
SELECT status_event_id, device_id, station_id, status, start_time, end_time,
       reason_code, is_planned, batch_id, source_type
FROM public.fact_device_status_event;

REVOKE ALL ON SCHEMA public FROM :"chatbi_role";
REVOKE ALL ON ALL TABLES IN SCHEMA public FROM :"chatbi_role";
REVOKE ALL ON SCHEMA chatbi_semantic FROM :"chatbi_role";
REVOKE ALL ON ALL TABLES IN SCHEMA chatbi_semantic FROM :"chatbi_role";
GRANT USAGE ON SCHEMA chatbi_semantic TO :"chatbi_role";
GRANT SELECT ON ALL TABLES IN SCHEMA chatbi_semantic TO :"chatbi_role";

REVOKE pg_monitor FROM :"chatbi_role";
REVOKE pg_read_all_settings FROM :"chatbi_role";
REVOKE pg_read_all_stats FROM :"chatbi_role";
REVOKE pg_stat_scan_tables FROM :"chatbi_role";
REVOKE pg_read_server_files FROM :"chatbi_role";
REVOKE pg_write_server_files FROM :"chatbi_role";
REVOKE pg_execute_server_program FROM :"chatbi_role";

ALTER ROLE :"chatbi_role" SET default_transaction_read_only = on;
ALTER ROLE :"chatbi_role" SET statement_timeout = '5s';
ALTER ROLE :"chatbi_role" SET lock_timeout = '2s';
ALTER ROLE :"chatbi_role" SET idle_in_transaction_session_timeout = '10s';
ALTER ROLE :"chatbi_role" SET search_path = chatbi_semantic, pg_catalog;

GRANT CONNECT ON DATABASE :"target_database" TO :"chatbi_role";

SELECT
  :'chatbi_role' AS configured_role,
  :'target_database' AS configured_database,
  has_schema_privilege(:'chatbi_role', 'chatbi_semantic', 'USAGE') AS semantic_usage,
  has_table_privilege(
    :'chatbi_role', 'chatbi_semantic.fact_charging_session', 'SELECT'
  ) AS semantic_select,
  has_table_privilege(:'chatbi_role', 'public.app_user', 'SELECT') AS sensitive_select;
