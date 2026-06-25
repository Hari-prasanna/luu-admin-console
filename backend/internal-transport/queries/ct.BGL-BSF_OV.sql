WITH 
-- Table 1: Your main KPI target records
t1_main AS (
    SELECT *
    FROM HISTORIE_V
    WHERE TRANSPORTTASKQUELLE LIKE '%BGL%' 
      AND TRANSPORTREQUESTZIEL LIKE '%BSF_O%'
      AND TYP_ID = '42' 
      AND CREATED >= (SYSDATE - 7)
),

-- Table 2: The Typ 47 exclusion list
t2_typ47 AS (
    SELECT TRANSPORTLHMNR, ZUG_ID, CREATED
    FROM HISTORIE_V
    WHERE TYP_ID = '47'
),

-- Table 3: The Typ 39 exclusion list
t3_typ39 AS (
    SELECT TRANSPORTLHMNR, ZUG_ID
    FROM HISTORIE_V
    WHERE TYP_ID = '39' 
)

-- The Final Check: Count the active transports!
SELECT COUNT(*) AS BGL_BSF_OV
FROM t1_main t1
WHERE NOT EXISTS (
    -- Excludes the row ONLY if there is a Typ 47 for this LHM in the SAME ZUG_ID family
    SELECT 1 
    FROM t2_typ47 t2 
    WHERE t2.TRANSPORTLHMNR = t1.TRANSPORTLHMNR
      AND t2.ZUG_ID = t1.ZUG_ID  -- << The magic happens here!
      AND t2.CREATED > t1.CREATED 
)
AND NOT EXISTS (
    -- Excludes the row if there is ANY Typ 39 for this LHM in the SAME ZUG_ID family
    SELECT 1 
    FROM t3_typ39 t3 
    WHERE t3.TRANSPORTLHMNR = t1.TRANSPORTLHMNR
      AND t3.ZUG_ID = t1.ZUG_ID  -- << And here!
)