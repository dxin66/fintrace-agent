ALTER TABLE documents
  ADD COLUMN storage_scope VARCHAR(10) NOT NULL DEFAULT 'LIBRARY',
  ADD COLUMN task_id BIGINT NULL,
  ADD CONSTRAINT chk_document_scope CHECK (storage_scope IN ('LIBRARY', 'TASK')),
  ADD CONSTRAINT chk_document_binding CHECK (storage_scope = 'TASK' OR task_id IS NULL),
  ADD CONSTRAINT fk_document_task FOREIGN KEY (task_id) REFERENCES tasks(id),
  ADD INDEX idx_document_scope (owner_id, storage_scope);
