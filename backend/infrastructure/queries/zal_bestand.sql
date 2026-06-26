SELECT zb."MainLhm", zb.ARTNR, zb."Qualität", zb."Sortierziel ID", zb."SortKriterium", zb.ANZ 
FROM ZAL_BESTAND zb
WHERE zb."MainLhm" = :lhm_num
