-- Additive: existing imported/local results retain their original directory.
ALTER TABLE jobs ADD COLUMN IF NOT EXISTS result_owner varchar(36);
