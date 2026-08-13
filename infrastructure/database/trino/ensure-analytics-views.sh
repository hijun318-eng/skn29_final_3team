#!/bin/sh
set -eu

while true; do
    until trino --server http://trino:8080 --user hotel_synthetic_setup \
        --execute 'SELECT 1' >/dev/null 2>&1; do
        sleep 2
    done

    view_count="$(trino --server http://trino:8080 --user hotel_synthetic_setup \
        --output-format TSV --execute \
        "SELECT count(*) FROM serving.information_schema.tables WHERE table_schema = 'analytics'" \
        2>/dev/null | tail -n 1 || true)"
    if [ "$view_count" != "8" ]; then
        trino --server http://trino:8080 --user hotel_synthetic_setup \
            --file /sql/ddl/06_trino_analytics_views.sql >/dev/null
    fi
    sleep 10
done
