CREATE STAGE
BOLIVIA_PHARMA_PRICE_ENGINE.BRONZE.FARMACORP_SCRAPED_PRICES_STAGE
    URL = 'azure://blobprojects.blob.core.windows.net/bolivia-pharma-price-engine/bronze/farmacorp/' -- noqa: LT05
    STORAGE_INTEGRATION = AZURE_BOLIVIA_PHARMA_BRONZE
    FILE_FORMAT = (
        FORMAT_NAME
        = 'BOLIVIA_PHARMA_PRICE_ENGINE.BRONZE.PARQUET_SNAPSHOTS_FORMAT'
    )
    COMMENT = 'Farmacorp Parquet snapshots across upload-date folders.';

CREATE STAGE
BOLIVIA_PHARMA_PRICE_ENGINE.BRONZE.FARMACIAS_CHAVEZ_SCRAPED_PRICES_STAGE
    URL = 'azure://blobprojects.blob.core.windows.net/bolivia-pharma-price-engine/bronze/farmacias_chavez/' -- noqa: LT05
    STORAGE_INTEGRATION = AZURE_BOLIVIA_PHARMA_BRONZE
    FILE_FORMAT = (
        FORMAT_NAME
        = 'BOLIVIA_PHARMA_PRICE_ENGINE.BRONZE.PARQUET_SNAPSHOTS_FORMAT'
    )
    COMMENT = 'Farmacias Chavez Parquet snapshots across upload-date folders.';

CREATE STAGE
BOLIVIA_PHARMA_PRICE_ENGINE.BRONZE.HIPERMAXI_SCRAPED_PRICES_STAGE
    URL = 'azure://blobprojects.blob.core.windows.net/bolivia-pharma-price-engine/bronze/hipermaxi/' -- noqa: LT05
    STORAGE_INTEGRATION = AZURE_BOLIVIA_PHARMA_BRONZE
    FILE_FORMAT = (
        FORMAT_NAME
        = 'BOLIVIA_PHARMA_PRICE_ENGINE.BRONZE.PARQUET_SNAPSHOTS_FORMAT'
    )
    COMMENT = 'Hipermaxi Parquet snapshots across upload-date folders.';
