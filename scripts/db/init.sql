-- Pre-install extensions on first DB boot. Migrations also CREATE EXTENSION IF NOT EXISTS,
-- but having them here avoids a migration round-trip for fresh local volumes.
CREATE EXTENSION IF NOT EXISTS pg_trgm;
