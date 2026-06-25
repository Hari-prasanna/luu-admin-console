WITH 
-- Table 1: Your main target records
t1_main AS (
    SELECT *
    FROM HISTORIE_V
    WHERE TRANSPORTTASKQUELLE = 'FIN_AP01' 
      AND TRANSPORTREQUESTZIEL LIKE '%BGL%'
      AND TYP_ID = '42' 
      AND CREATED >= (SYSDATE - 5)
),

-- Table 2: The Typ 47 exclusion list tied to the lifecycle
t2_typ47 AS (
    SELECT DISTINCT TRANSPORTLHMNR, ZUG_ID
    FROM HISTORIE_V
    WHERE TYP_ID = '47'
),

-- Table 3: The Typ 39 exclusion list tied to the lifecycle
t3_typ39 AS (
    SELECT DISTINCT TRANSPORTLHMNR, ZUG_ID
    FROM HISTORIE_V
    WHERE TYP_ID = '39'
)

-- The Final Check: Count the active transports
SELECT COUNT(*) AS fIN_AP_BGL
FROM t1_main t1
LEFT JOIN t2_typ47 t2 
  ON t1.TRANSPORTLHMNR = t2.TRANSPORTLHMNR
  AND t1.ZUG_ID = t2.ZUG_ID  -- Ensures the 47 belongs to the current transport attempt
LEFT JOIN t3_typ39 t3 
  ON t1.TRANSPORTLHMNR = t3.TRANSPORTLHMNR
  AND t1.ZUG_ID = t3.ZUG_ID  -- Ensures the 39 belongs to the current transport attempt
-- Keep only rows that didn't find a 47 AND didn't find a 39
WHERE t2.TRANSPORTLHMNR IS NULL 
  AND t3.TRANSPORTLHMNR IS NULL