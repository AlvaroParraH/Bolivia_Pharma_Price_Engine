COPY INTO BOLIVIA_PHARMA_PRICE_ENGINE.BRONZE.SCRAPED_HIPERMAXI_PRICES (
    RUN_ID, OBSERVED_AT, RETAILER, CITY, BRANCH, CATEGORY, CATEGORY_URL,
    PAGE_URL, BATCH, PRODUCT_ID, PRODUCT_URL, NAME, CURRENCY, PRICE,
    DISCOUNT_PRICE, CURRENT_PRICE, DISCOUNT_PERCENT, DISCOUNT_LABEL,
    AVAILABILITY_LABEL, IMAGE_URL, CURRENT_PRICE_TEXT, REGULAR_PRICE_TEXT,
    MARKET_CONTEXT, SOURCE_FILE, SOURCE_ROW_NUMBER
)
FROM (
    SELECT
        $1:run_id::VARCHAR,
        $1:observed_at::TIMESTAMP_TZ,
        $1:retailer::VARCHAR,
        $1:city::VARCHAR,
        $1:branch::VARCHAR,
        $1:category::VARCHAR,
        $1:category_url::VARCHAR,
        $1:page_url::VARCHAR,
        $1:batch::NUMBER(38, 0),
        $1:product_id::VARCHAR,
        $1:product_url::VARCHAR,
        $1:name::VARCHAR,
        $1:currency::VARCHAR,
        $1:price::NUMBER(18, 2),
        $1:discount_price::NUMBER(18, 2),
        $1:current_price::NUMBER(18, 2),
        $1:discount_percent::NUMBER(5, 2),
        $1:discount_label::VARCHAR,
        $1:availability_label::VARCHAR,
        $1:image_url::VARCHAR,
        $1:current_price_text::VARCHAR,
        $1:regular_price_text::VARCHAR,
        $1:market_context::VARCHAR,
        METADATA$FILENAME,
        METADATA$FILE_ROW_NUMBER
    FROM @BOLIVIA_PHARMA_PRICE_ENGINE.BRONZE.HIPERMAXI_SCRAPED_PRICES_STAGE
)
PATTERN = '.*[0-9]{8}/scrape_hipermaxi_[0-9]{8}T[0-9]{6}Z[.]parquet'
ON_ERROR = ABORT_STATEMENT
FORCE = FALSE
PURGE = FALSE
LOAD_UNCERTAIN_FILES = FALSE;
