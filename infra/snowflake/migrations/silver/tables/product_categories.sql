CREATE TABLE BOLIVIA_PHARMA_PRICE_ENGINE.SILVER.PRODUCT_CATEGORIES (
    CATEGORY_ID NUMBER(38, 0) NOT NULL,
    CATEGORY_GROUP VARCHAR NOT NULL,
    CATEGORY_NAME VARCHAR NOT NULL,
    ATC_SCOPE VARCHAR,
    EXAMPLES VARCHAR,
    CONSTRAINT PK_PRODUCT_CATEGORIES PRIMARY KEY (CATEGORY_ID)
)
COMMENT = 'Project product classification reference; ATC scopes are illustrative and may overlap, not verified product ATC assignments.';

INSERT INTO BOLIVIA_PHARMA_PRICE_ENGINE.SILVER.PRODUCT_CATEGORIES (
    CATEGORY_ID, CATEGORY_GROUP, CATEGORY_NAME, ATC_SCOPE, EXAMPLES
)
VALUES
    (1, 'Medicines', 'Analgesics & Anti-inflammatories', 'M01, N02', 'paracetamol, ibuprofeno, diclofenaco, ketorolaco, metamizol, tramadol'),
    (2, 'Medicines', 'Anesthetics', 'N01', 'lidocaína, bupivacaína'),
    (3, 'Medicines', 'Musculoskeletal', 'M03–M05', 'tiocolchicósido, orfenadrina, alopurinol, alendronato'),
    (4, 'Medicines', 'Antibiotics', 'J01', 'amoxicilina, azitromicina, ciprofloxacino, ceftriaxona'),
    (5, 'Medicines', 'Antifungals', 'J02, D01', 'fluconazol, clotrimazol, ketoconazol, terbinafina'),
    (6, 'Medicines', 'Antivirals', 'J05', 'aciclovir, valaciclovir, oseltamivir'),
    (7, 'Medicines', 'Antiparasitics', 'P', 'albendazol, nitazoxanida, ivermectina, metronidazol, permetrina'),
    (8, 'Medicines', 'Vaccines & Immunoglobulins', 'J06, J07', 'vacunas, sueros antiofídicos'),
    (9, 'Medicines', 'Cardiovascular', 'C', 'losartán, amlodipino, atorvastatina, amiodarona, furosemida'),
    (10, 'Medicines', 'Blood & Anticoagulants', 'B01–B02', 'enoxaparina, warfarina, clopidogrel, ácido tranexámico'),
    (11, 'Medicines', 'Diabetes', 'A10', 'metformina, insulina, glibenclamida, sitagliptina'),
    (12, 'Medicines', 'Thyroid & Other Hormones', 'H01, H03, H05', 'levotiroxina, tiamazol'),
    (13, 'Medicines', 'Corticosteroids (systemic)', 'H02', 'dexametasona, prednisona, hidrocortisona'),
    (14, 'Medicines', 'Gastrointestinal', 'A02, A03, A06, A07', 'omeprazol, loperamida, butilescopolamina, lactulosa, probióticos'),
    (15, 'Medicines', 'Antiemetics & Vertigo', 'A04, N07C', 'ondansetrón, dimenhidrinato, betahistina'),
    (16, 'Medicines', 'Respiratory', 'R03, R05', 'salbutamol, budesonida, ambroxol, acetilcisteína'),
    (17, 'Medicines', 'Cold & Flu', 'R01, R05X', 'antigripales, fenilefrina, pseudoefedrina'),
    (18, 'Medicines', 'Allergy', 'R06', 'loratadina, cetirizina, desloratadina, clorfenamina'),
    (19, 'Medicines', 'CNS & Mental Health', 'N05, N06', 'sertralina, clonazepam, quetiapina, zolpidem'),
    (20, 'Medicines', 'Neurology', 'N03, N04, N02C', 'levetiracetam, pregabalina, levodopa, sumatriptán'),
    (21, 'Medicines', 'Urology & Men''s Health', 'G04', 'tamsulosina, finasterida, sildenafil, tadalafil'),
    (22, 'Medicines', 'Women''s Health & Contraception', 'G01–G03', 'anticonceptivos, levonorgestrel, progesterona, óvulos vaginales'),
    (23, 'Medicines', 'Oncology & Immunosuppressants', 'L', 'metotrexato, tamoxifeno, anastrozol'),
    (24, 'Medicines', 'Dermatological (medicated)', 'D', 'mupirocina, clobetasol, sulfadiazina de plata, cicatrizantes'),
    (25, 'Medicines', 'Ophthalmic', 'S01', 'colirios, lágrimas artificiales, timolol'),
    (26, 'Medicines', 'Otic', 'S02', 'gotas óticas'),
    (27, 'Medicines', 'IV Fluids & Electrolytes', 'B05', 'suero fisiológico, glucosa 5%, sales de rehidratación'),
    (28, 'Medicines', 'Vitamins & Minerals', 'A11, A12, B03', 'vitaminas, complejo B, hierro, calcio, zinc, ácido fólico'),
    (29, 'Medicines', 'Natural, Herbal & Homeopathic', NULL, 'extractos de plantas, remedios tradicionales, homeopatía'),
    (30, 'Medicines', 'Pharmacy-Compounded Preparations', NULL, 'alcohol, agua oxigenada, vaselina, preparados magistrales'),
    (31, 'Medicines', 'Antidotes & Hospital Use', 'V', 'flumazenil, naloxona, medios de contraste'),
    (32, 'Medicines', 'Weight Control & Smoking Cessation', 'A08, N07B', 'orlistat, reemplazo de nicotina'),
    (33, 'Medicines', 'Other Medicines', NULL, 'any medicine not matching 1–32'),
    (34, 'Health products', 'Medical Supplies & Devices', NULL, 'jeringas, gasas, vendas, guantes, termómetros, tiras reactivas'),
    (35, 'Health products', 'Sexual Health', NULL, 'preservativos, lubricantes'),
    (36, 'Health products', 'Nutritional Supplements', NULL, 'proteínas, nutrición deportiva, suplementos no vitamínicos'),
    (37, 'Health products', 'Medical Nutrition', NULL, 'fórmulas infantiles, nutrición enteral y clínica'),
    (38, 'Other', 'Other Products', NULL, 'cosméticos, higiene, alimentos, hogar');
