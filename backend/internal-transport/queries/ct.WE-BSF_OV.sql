WITH 
-- Table 1: Your main target records (The '42's)
t1_main AS (
    SELECT *
    FROM HISTORIE_V
    WHERE TRANSPORTTASKQUELLE = 'WE' 
      AND TRANSPORTREQUESTZIEL LIKE '%BSF_O%'
      AND TYP_ID = '42' 
      AND LAGBEZ = 'Wareneingang'
      AND CREATED >= (SYSDATE - 2)
),

-- Table 2: The Typ 47 exclusion list
t2_typ47 AS (
    -- Added ZUG_ID here
    SELECT DISTINCT TRANSPORTLHMNR, ZUG_ID
    FROM HISTORIE_V
    WHERE TYP_ID = '47'
),

-- Table 3: The Typ 39 exclusion list
t3_typ39 AS (
    -- Added ZUG_ID here
    SELECT DISTINCT TRANSPORTLHMNR, ZUG_ID
    FROM HISTORIE_V
	WHERE TYP_ID = '39'
)

-- The Final Check: Count the active matches!
SELECT COUNT(*) AS WE_BESF_OV
FROM t1_main t1
LEFT JOIN t2_typ47 t2 
  ON t1.TRANSPORTLHMNR = t2.TRANSPORTLHMNR
  AND t1.ZUG_ID = t2.ZUG_ID  -- Ties the Typ 47 exclusion to the specific transport lifecycle
LEFT JOIN t3_typ39 t3 
  ON t1.TRANSPORTLHMNR = t3.TRANSPORTLHMNR
  AND t1.ZUG_ID = t3.ZUG_ID  -- Ties the Typ 39 exclusion to the specific transport lifecycle
-- Count only rows that matched neither t2 nor t3
WHERE t2.TRANSPORTLHMNR IS NULL 
  AND t3.TRANSPORTLHMNR IS NULL