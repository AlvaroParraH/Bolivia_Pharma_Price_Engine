# Bronze file formats

[parquet_snapshots_format.sql](parquet_snapshots_format.sql) defines the shared
`BOLIVIA_PHARMA_PRICE_ENGINE.BRONZE.PARQUET_SNAPSHOTS_FORMAT`.
It uses the same Parquet defaults as the previous inline stage definitions.
Typed conversions remain in the COPY scripts.

This is local SQL, not deployed. Create the format before the retailer stages.
The deployer needs Bronze `CREATE FILE FORMAT`; the ingestor is granted format
`USAGE` separately after creation. Review the target and approve deployment
before execution. Plain `CREATE FILE FORMAT` fails if the object already exists;
it does not replace an existing format.
