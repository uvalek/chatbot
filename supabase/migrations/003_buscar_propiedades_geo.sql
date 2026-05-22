-- buscar_propiedades ahora también busca y devuelve estado, municipio y
-- código postal (columnas agregadas a la tabla `propiedades`).
DROP FUNCTION IF EXISTS public.buscar_propiedades(text, numeric, integer);

CREATE OR REPLACE FUNCTION public.buscar_propiedades(busqueda text DEFAULT NULL::text, precio_max numeric DEFAULT NULL::numeric, recamaras_min integer DEFAULT NULL::integer)
 RETURNS TABLE(id integer, nombre text, tipo text, zona text, direccion text, precio numeric, recamaras integer, banos integer, metros_cuadrados numeric, acepta_credito boolean, tipos_credito text, descripcion text, asesor_asignado text, tipo_oferta text, galeria jsonb, estado text, municipio text, codigo_postal text)
 LANGUAGE sql
 STABLE
AS $function$
  WITH tokens AS (
    SELECT DISTINCT lower(trim(t)) AS token
    FROM regexp_split_to_table(COALESCE(busqueda, ''), '\s+') AS t
    WHERE length(trim(t)) >= 3
  ),
  scored AS (
    SELECT
      p.id, p.nombre, p.tipo, p.zona, p.direccion, p.precio, p.recamaras,
      p.banos, p.metros_cuadrados, p.acepta_credito, p.tipos_credito,
      p.descripcion, p.asesor_asignado, p.tipo_oferta, p.galeria,
      p.estado, p.municipio, p.codigo_postal,
      COALESCE((SELECT COUNT(*) FROM tokens t WHERE p.nombre        ILIKE '%' || t.token || '%'), 0) * 10 +
      COALESCE((SELECT COUNT(*) FROM tokens t WHERE p.descripcion   ILIKE '%' || t.token || '%'), 0) * 6  +
      COALESCE((SELECT COUNT(*) FROM tokens t WHERE p.direccion     ILIKE '%' || t.token || '%'), 0) * 5  +
      COALESCE((SELECT COUNT(*) FROM tokens t WHERE p.municipio     ILIKE '%' || t.token || '%'), 0) * 5  +
      COALESCE((SELECT COUNT(*) FROM tokens t WHERE p.codigo_postal ILIKE '%' || t.token || '%'), 0) * 5  +
      COALESCE((SELECT COUNT(*) FROM tokens t WHERE p.zona          ILIKE '%' || t.token || '%'), 0) * 4  +
      COALESCE((SELECT COUNT(*) FROM tokens t WHERE p.estado        ILIKE '%' || t.token || '%'), 0) * 3  +
      COALESCE((SELECT COUNT(*) FROM tokens t WHERE p.tipo          ILIKE '%' || t.token || '%'), 0) * 3
      AS score
    FROM propiedades p
    WHERE p.disponible = true
      AND (precio_max IS NULL OR p.precio <= precio_max)
      AND (recamaras_min IS NULL OR p.recamaras >= recamaras_min)
  )
  SELECT
    id, nombre, tipo, zona, direccion, precio, recamaras, banos,
    metros_cuadrados, acepta_credito, tipos_credito, descripcion,
    asesor_asignado, tipo_oferta, galeria, estado, municipio, codigo_postal
  FROM scored
  WHERE busqueda IS NULL OR trim(busqueda) = '' OR score > 0
  ORDER BY score DESC, precio ASC
  LIMIT 5;
$function$;
