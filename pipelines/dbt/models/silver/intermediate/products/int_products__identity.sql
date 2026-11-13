WITH observations AS (

    SELECT
        RETAILER,
        PRODUCT_HANDLE AS RETAILER_PRODUCT_ID,
        PRODUCT_URL,
        NAME,
        BRAND,
        OBSERVED_AT,
        SOURCE_FILE,
        SOURCE_ROW_NUMBER,
        LOADED_AT,
        'farmacorp' AS SOURCE_RETAILER
    FROM {{ ref('stg_farmacorp__prices') }}

    UNION ALL

    SELECT
        RETAILER,
        PRODUCT_ID AS RETAILER_PRODUCT_ID,
        PRODUCT_URL,
        NAME,
        NULL AS BRAND,
        OBSERVED_AT,
        SOURCE_FILE,
        SOURCE_ROW_NUMBER,
        LOADED_AT,
        'farmacias_chavez' AS SOURCE_RETAILER
    FROM {{ ref('stg_farmacias_chavez__prices') }}

    UNION ALL

    SELECT
        RETAILER,
        PRODUCT_ID AS RETAILER_PRODUCT_ID,
        PRODUCT_URL,
        NAME,
        NULL AS BRAND,
        OBSERVED_AT,
        SOURCE_FILE,
        SOURCE_ROW_NUMBER,
        LOADED_AT,
        'hipermaxi' AS SOURCE_RETAILER
    FROM {{ ref('stg_hipermaxi__prices') }}

),

normalized AS (

    SELECT
        NULLIF(TRIM(RETAILER), '') AS RETAILER,
        NULLIF(TRIM(RETAILER_PRODUCT_ID), '') AS RETAILER_PRODUCT_ID,
        PRODUCT_URL,
        NAME,
        BRAND,
        OBSERVED_AT,
        SOURCE_FILE,
        SOURCE_ROW_NUMBER,
        LOADED_AT,
        SOURCE_RETAILER
    FROM observations

),

identified AS (

    SELECT
        RETAILER,
        RETAILER_PRODUCT_ID,
        PRODUCT_URL,
        NAME,
        BRAND,
        OBSERVED_AT,
        SOURCE_FILE,
        SOURCE_ROW_NUMBER,
        LOADED_AT,
        SOURCE_RETAILER,
        'identified' AS IDENTITY_STATUS
    FROM normalized
    WHERE RETAILER IS NOT NULL AND RETAILER_PRODUCT_ID IS NOT NULL
    QUALIFY ROW_NUMBER() OVER (
        PARTITION BY RETAILER, RETAILER_PRODUCT_ID
        ORDER BY OBSERVED_AT DESC NULLS LAST, LOADED_AT DESC NULLS LAST,
            SOURCE_RETAILER, SOURCE_FILE, SOURCE_ROW_NUMBER
    ) = 1

),

unresolved AS (

    SELECT
        RETAILER,
        RETAILER_PRODUCT_ID,
        PRODUCT_URL,
        NAME,
        BRAND,
        OBSERVED_AT,
        SOURCE_FILE,
        SOURCE_ROW_NUMBER,
        LOADED_AT,
        SOURCE_RETAILER,
        'unresolved' AS IDENTITY_STATUS
    FROM normalized
    WHERE RETAILER IS NULL OR RETAILER_PRODUCT_ID IS NULL

)

SELECT * FROM identified
UNION ALL
SELECT * FROM unresolved
