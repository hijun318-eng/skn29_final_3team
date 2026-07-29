SET @create_datahub = CONCAT(
    "CREATE USER IF NOT EXISTS 'pos_datahub'@'%' IDENTIFIED BY '",
    @pos_datahub_password,
    "'"
);
PREPARE statement FROM @create_datahub;
EXECUTE statement;
DEALLOCATE PREPARE statement;

SET @create_trino = CONCAT(
    "CREATE USER IF NOT EXISTS 'pos_trino'@'%' IDENTIFIED BY '",
    @pos_trino_password,
    "'"
);
PREPARE statement FROM @create_trino;
EXECUTE statement;
DEALLOCATE PREPARE statement;

SET @alter_datahub = CONCAT(
    "ALTER USER 'pos_datahub'@'%' IDENTIFIED BY '",
    @pos_datahub_password,
    "'"
);
PREPARE statement FROM @alter_datahub;
EXECUTE statement;
DEALLOCATE PREPARE statement;

SET @alter_trino = CONCAT(
    "ALTER USER 'pos_trino'@'%' IDENTIFIED BY '",
    @pos_trino_password,
    "'"
);
PREPARE statement FROM @alter_trino;
EXECUTE statement;
DEALLOCATE PREPARE statement;

CREATE ROLE IF NOT EXISTS 'pos_ingest', 'pos_query';
GRANT SELECT, INSERT, UPDATE, DELETE ON hotel_pos.* TO 'pos_ingest';
GRANT SELECT ON hotel_pos.* TO 'pos_query';
GRANT 'pos_query' TO 'pos_datahub'@'%', 'pos_trino'@'%';
SET DEFAULT ROLE 'pos_query' TO 'pos_datahub'@'%', 'pos_trino'@'%';
