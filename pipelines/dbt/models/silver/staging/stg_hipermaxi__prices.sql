{{
    config(
        materialized='incremental',
        incremental_strategy='merge',
        unique_key=['SOURCE_FILE', 'SOURCE_ROW_NUMBER'],
        on_schema_change='fail'
    )
}}

SELECT
    RUN_ID,
    OBSERVED_AT,
    RETAILER,
    CITY,
    BRANCH,
    CATEGORY,
    CATEGORY_URL,
    PAGE_URL,
    BATCH,
    PRODUCT_ID,
    PRODUCT_URL,
    NAME,
    CURRENCY,
    PRICE,
    DISCOUNT_PRICE,
    CURRENT_PRICE,
    DISCOUNT_PERCENT,
    DISCOUNT_LABEL,
    AVAILABILITY_LABEL,
    IMAGE_URL,
    CURRENT_PRICE_TEXT,
    REGULAR_PRICE_TEXT,
    MARKET_CONTEXT,
    SOURCE_FILE,
    SOURCE_ROW_NUMBER,
    LOADED_AT
FROM {{ source('bronze', 'scraped_hipermaxi_prices') }} AS bronze
{% if is_incremental() %}
WHERE TO_DATE(bronze.LOADED_AT) >= COALESCE(
    DATEADD(day, -1, (SELECT MAX(TO_DATE(LOADED_AT)) FROM {{ this }})),
    '1900-01-01'::DATE
)
{% endif %}
