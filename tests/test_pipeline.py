"""Pruebas del motor de CommunityLab (modo demo, sin API ni credenciales)."""
import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from core import pipeline as pl  # noqa: E402
from core.oci_storage import AlmacenLocal  # noqa: E402

EJEMPLO = Path(__file__).resolve().parents[1] / "data" / "interacciones_semana04.json"


@pytest.fixture(scope="module")
def resultado():
    return pl.MotorCommunityLab(modo="demo").procesar(json.loads(EJEMPLO.read_text(encoding="utf-8")))


def a(**kw):
    base = {"sentimiento_puntaje": 0.0, "categoria": "otro", "requiere_apoyo": False}
    base.update(kw)
    return base


# ---------- ingesta
def test_normaliza_y_descarta_vacios():
    items = pl.normalizar_interacciones([{"texto": "  hola   mundo "}, {"texto": ""}, "basura", {"mensaje": "x", "id": "1"}])
    assert [i["texto"] for i in items] == ["hola mundo", "x"]
    assert items[0]["autor"] == "Anónimo" and items[0]["canal"] == "#general"


def test_ids_duplicados_se_desambiguan():
    items = pl.normalizar_interacciones([{"id": "a", "texto": "1"}, {"id": "a", "texto": "2"}])
    assert len({i["id"] for i in items}) == 2


def test_leer_lote_acepta_objeto_y_lista():
    assert pl.leer_lote({"origen_comunidad": "X", "interacciones": [1]})[0] == "X"
    assert pl.leer_lote([1, 2])[2] == [1, 2]
    with pytest.raises(ValueError):
        pl.leer_lote("texto")


# ---------- parser del LLM
def test_parse_json_con_cercas_de_codigo():
    assert pl.parse_json('```json\n{"a": 1}\n```') == {"a": 1}
    assert pl.parse_json('Claro, aquí está: {"a": [1, 2]} ¡listo!') == {"a": [1, 2]}
    with pytest.raises(ValueError):
        pl.parse_json("sin json")


def test_saneamiento_recorta_rangos_y_rechaza_categorias():
    h = pl.analizar_heuristico({"texto": "hola", "tipo": "otro"})
    s = pl._sanear({"sentimiento_puntaje": 3, "relevancia": 250, "categoria": "inventada", "temas": ["A"]}, h)
    assert s["sentimiento_puntaje"] == 1.0 and s["relevancia"] == 100
    assert s["categoria"] == h["categoria"] and s["temas"] == ["A"]


# ---------- ruteo condicional
@pytest.mark.parametrize("entrada,ruta", [
    (a(categoria="testimonio", sentimiento_puntaje=0.8), "caso_exito"),
    (a(categoria="proyecto_destacado", sentimiento_puntaje=0.5), "caso_exito"),
    (a(categoria="testimonio", sentimiento_puntaje=0.2), "archivo"),
    (a(categoria="pregunta_tecnica", sentimiento_puntaje=-0.7), "faq"),
    (a(categoria="pregunta_tecnica", requiere_apoyo=True), "alerta_apoyo"),
    (a(categoria="feedback", sentimiento_puntaje=-0.5), "alerta_apoyo"),
    (a(categoria="debate", sentimiento_puntaje=0.1), "archivo"),
])
def test_enrutar(entrada, ruta):
    assert pl.enrutar(entrada, umbral_exito=0.4) == ruta


def test_puntaje_relevancia():
    assert pl.puntaje_relevancia({"relevancia": 80, "sentimiento_puntaje": -0.5}) == 71
    assert pl.etiqueta_sentimiento(0.6) == "Altamente Positivo"
    assert pl.etiqueta_sentimiento(-0.61) == "Altamente Negativo"


# ---------- extremo a extremo (lote del reto)
def test_lote_de_ejemplo(resultado):
    rutas = {x["autor"]: x["ruta"] for x in resultado["analisis"]}
    assert rutas["Mariana Souza"] == "caso_exito"
    assert rutas["Lucas Albuquerque"] == "faq"
    assert rutas["Camila Torres"] == "alerta_apoyo"
    assert resultado["resumen"]["total_interacciones_procesadas"] == 9
    tipos = {x["tipo"] for x in resultado["activos"]}
    assert {"post_linkedin", "post_x", "caso_exito", "faq", "newsletter", "highlights"} <= tipos


def test_posts_x_respetan_280(resultado):
    assert all(len(x["contenido"]) <= 280 for x in resultado["activos"] if x["tipo"] == "post_x")


def test_ranking_descendente(resultado):
    p = [x["puntaje_relevancia"] for x in resultado["analisis"]]
    assert p == sorted(p, reverse=True)


# ---------- curaduría y paquete
def test_paquete_solo_incluye_aprobados(resultado):
    activos = [dict(x) for x in resultado["activos"]]
    activos[0]["estado"] = "aprobado"
    activos[1]["estado"] = "rechazado"
    pq = pl.construir_paquete(resultado, activos)
    total = sum(len(v) for v in pq["activos_distribucion_generados"].values())
    assert total == 1 and pq["curaduria"]["rechazados"] == 1
    assert pq["status"] == "exito"


def test_guardado_crea_tres_objetos(tmp_path, resultado):
    activos = [dict(x, estado="aprobado") for x in resultado["activos"]]
    pq = pl.construir_paquete(resultado, activos)
    g = pl.guardar_paquete(AlmacenLocal("bucket-test", tmp_path), pq, resultado)
    assert g["ok"] and len(g["objetos"]) == 3
    assert g["paquete"]["almacenamiento_oci"]["ruta_objeto"].startswith("activos/")
    guardado = json.loads((tmp_path / "bucket-test" / g["paquete"]["almacenamiento_oci"]["ruta_objeto"]).read_text(encoding="utf-8"))
    assert guardado["almacenamiento_oci"]["status"] == "guardado_con_exito"


def test_gemini_sin_api_key_falla_claro():
    with pytest.raises(ValueError, match="GOOGLE_API_KEY"):
        pl.MotorCommunityLab(modo="gemini", api_key="")
