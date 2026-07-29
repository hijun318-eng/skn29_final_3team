CREATE TABLE IF NOT EXISTS outlet (
    outlet_id INT PRIMARY KEY,
    outlet_name VARCHAR(100) NOT NULL,
    location_code VARCHAR(30) NOT NULL UNIQUE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci;

CREATE TABLE IF NOT EXISTS menu_item (
    menu_item_id INT PRIMARY KEY,
    item_name VARCHAR(120) NOT NULL,
    category VARCHAR(50) NOT NULL,
    unit_price DECIMAL(12,2) NOT NULL,
    active BOOLEAN NOT NULL DEFAULT TRUE,
    CONSTRAINT chk_menu_price CHECK (unit_price >= 0)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci;

CREATE TABLE IF NOT EXISTS pos_transaction (
    transaction_id BIGINT PRIMARY KEY,
    outlet_id INT NOT NULL,
    menu_item_id INT NOT NULL,
    quantity INT NOT NULL,
    gross_amount DECIMAL(14,2) NOT NULL,
    paid_at DATETIME NOT NULL,
    payment_method VARCHAR(30) NOT NULL,
    CONSTRAINT fk_transaction_outlet FOREIGN KEY (outlet_id) REFERENCES outlet(outlet_id),
    CONSTRAINT fk_transaction_menu FOREIGN KEY (menu_item_id) REFERENCES menu_item(menu_item_id),
    CONSTRAINT chk_transaction_quantity CHECK (quantity > 0),
    CONSTRAINT chk_transaction_amount CHECK (gross_amount >= 0)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci;

CREATE TABLE IF NOT EXISTS schema_version (
    version VARCHAR(30) PRIMARY KEY,
    seed BIGINT NOT NULL,
    applied_at DATETIME NOT NULL
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci;
