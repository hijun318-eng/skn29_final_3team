BEGIN;

UPDATE documents
SET role_scope = ARRAY(
    SELECT DISTINCT role_name
    FROM unnest(role_scope || ARRAY['ANALYST', 'PLATFORM_ADMIN']) AS role_name
    ORDER BY role_name
)
WHERE NOT role_scope @> ARRAY['ANALYST', 'PLATFORM_ADMIN'];

UPDATE document_versions
SET role_scope = ARRAY(
    SELECT DISTINCT role_name
    FROM unnest(role_scope || ARRAY['ANALYST', 'PLATFORM_ADMIN']) AS role_name
    ORDER BY role_name
)
WHERE NOT role_scope @> ARRAY['ANALYST', 'PLATFORM_ADMIN'];

COMMIT;
