CREATE ROLE PHARMA_DEV_DEPLOYER
    COMMENT = 'Deploys approved Bolivia pharmacy development infrastructure; not a pipeline runtime role.';

CREATE ROLE PHARMA_DEV_INGESTOR
    COMMENT = 'Loads staged pharmacy observations into development Bronze tables.';

CREATE ROLE PHARMA_DEV_DBT
    COMMENT = 'Reads development Bronze data and manages dbt models in Silver and Gold.';

CREATE ROLE PHARMA_DEV_READER
    COMMENT = 'Reads approved development Gold reporting tables and views.';
