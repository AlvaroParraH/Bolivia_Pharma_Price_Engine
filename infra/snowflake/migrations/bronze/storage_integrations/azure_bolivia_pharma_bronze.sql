-- Review the target account and Azure authorization before execution.
CREATE STORAGE INTEGRATION AZURE_BOLIVIA_PHARMA_BRONZE
    TYPE = EXTERNAL_STAGE
    STORAGE_PROVIDER = 'AZURE'
    ENABLED = TRUE
    AZURE_TENANT_ID = '327b9747-2905-4026-b2fb-40ea0944dec5'
    STORAGE_ALLOWED_LOCATIONS = (
        'azure://blobprojects.blob.core.windows.net/bolivia-pharma-price-engine/'
    )
    COMMENT = 'Read access intended for Bolivia pharmacy Bronze ingestion from Azure Blob Storage.';
