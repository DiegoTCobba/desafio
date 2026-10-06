# CommunityLab: motor de IA que convierte conversaciones de comunidad en contenido listo para publicar

CommunityLab ingiere un lote de mensajes de una comunidad tech, los analiza con un LLM, decide por reglas qué hacer con cada uno y genera posts, casos de éxito, FAQs y un resumen semanal que una persona aprueba antes de guardarlos en OCI Object Storage.

**Contenido:** [Resumen](#resumen) · [Problema](#problema) · [Arquitectura](#arquitectura) · [Pipeline](#pipeline-y-ruteo-condicional) · [Decisiones](#decisiones-de-arquitectura) · [Diseño de IA](#diseño-de-ia-y-prompts) · [Contrato de datos](#contrato-de-datos) · [Interfaz](#interfaz-y-panel-de-curaduría) · [OCI y seguridad](#persistencia-en-oci-y-seguridad) · [Calidad](#calidad-y-validación) · [Roadmap](#limitaciones-y-roadmap) · [Aprendizajes](#aprendizajes-técnicos)

---

## Resumen

Es un MVP completo, de la ingesta al almacenamiento en la nube, construido para el reto 3 del Hackathon ONE G10 (Oracle Next Education + Alura). La idea central: el LLM interpreta, pero las decisiones del flujo las toma código determinista, y nada se publica sin aprobación humana.

| Aspecto | Detalle |
| --- | --- |
| Contexto | Hackathon ONE G10 · Reto 3 · sector MarTech / gestión de comunidades |
| Rol | Diseño y desarrollo end-to-end: arquitectura, motor de IA, interfaz y persistencia |
| Stack | Python 3.11 · LangChain · Google Gemini 2.0 Flash · Streamlit · Pandas · Altair · OCI Python SDK |
| Nube | OCI Object Storage, capa Always Free |
| Entradas | JSON del reto, CSV (autor, canal, tipo, texto) o JSON pegado |
| Salidas | 6 tipos de activo: post LinkedIn, post X, caso de éxito, Tip/FAQ, destaque de newsletter, Community Highlights |
| Rutas del flujo | 4: caso de éxito, FAQ, alerta de apoyo, archivo |
| Persistencia | 3 objetos por ejecución: paquete JSON, análisis por interacción e informe Markdown |
| Resultado con el lote de ejemplo | 9 mensajes procesados → 14 activos generados en una sola ejecución |

## Problema

Las comunidades de aprendizaje generan cada semana testimonios, proyectos y dudas valiosas, pero ese material se pierde en el historial de Discord o Slack. Encontrarlo, interpretarlo y redactarlo para cada canal es trabajo manual que compite con todo lo demás que hace un equipo de Community Management.

El reto pide resolver tres necesidades del cliente, cada una con un costo distinto si no se atiende:

| Necesidad | Hoy (proceso manual) | Con CommunityLab |
| --- | --- | --- |
| Detectar historias de éxito | Alguien lee los canales y depende de su memoria | Clasificación por categoría y sentimiento; ranking por relevancia |
| Producir contenido por canal | Redacción desde cero para LinkedIn, X y newsletter | Borradores con la voz de marca, listos para editar y aprobar |
| Saber cómo está la comunidad | Percepción subjetiva; los miembros frustrados pasan desapercibidos | Tablero de sentimiento, temas en tendencia y alertas de apoyo |

El enunciado del reto señala que el contenido generado por usuarios (UGC) alcanza hasta 4 veces más engagement que la publicidad corporativa. Por eso el objetivo no es escribir posts genéricos, sino aprovechar las voces reales de la comunidad.

Requisitos obligatorios del MVP: ingesta de interacciones, análisis con LLM, al menos 2 formatos de activo, orquestación del flujo con bifurcación condicional, interfaz de curaduría e integración con OCI Object Storage Always Free.

## Arquitectura

Tres capas con responsabilidades separadas. La interfaz no conoce el SDK de OCI y el motor no conoce Streamlit, así que cada parte se puede reemplazar o probar por separado.

![Arquitectura de CommunityLab](img/arquitectura.png)

El ruteo (resaltado) es la única pieza que decide qué contenido se produce, y es código determinista. Gemini se consulta en el análisis y en la generación, y cada llamada tiene su respaldo.

## Pipeline y ruteo condicional

El LLM devuelve datos (sentimiento, categoría, si la persona necesita apoyo) y una función pura aplica tres reglas en orden de prioridad. La primera que se cumple define la ruta, así que un logro escrito con frustración se atiende antes de convertirse en publicidad.

![Ruteo condicional: 3 reglas en orden, 4 rutas](img/ruteo-condicional.png)

Por defecto se transforman hasta 3 mensajes por ruta, los de mayor relevancia. El umbral de éxito y ese límite se ajustan desde la barra lateral sin tocar código.

## Decisiones de arquitectura

Cada decisión priorizó tres cosas: que la demo no falle en vivo, que el costo sea cero y que el código se pueda migrar sin reescribirlo.

| # | Decisión | Alternativas descartadas | Por qué | Costo aceptado |
| --- | --- | --- | --- | --- |
| 1 | Pipeline en Python + LangChain, sin n8n | n8n, LangGraph | Un solo proceso, fácil de probar y de depurar; el ruteo es una función pura | Sin editor visual de flujos; LangGraph queda en el roadmap |
| 2 | El LLM clasifica, el código decide la ruta | Que el LLM elija qué activo generar | Ruteo reproducible y auditable; el umbral se ajusta desde la interfaz | Reglas explícitas que hay que mantener |
| 3 | Salida JSON estricta + saneamiento campo por campo | Texto libre parseado con regex | Un campo inválido no rompe el lote: se reemplaza por el valor heurístico | Más código de validación |
| 4 | Análisis en lotes de 15 mensajes | Una llamada por mensaje | ~15 veces menos llamadas; menos riesgo de agotar la cuota gratuita | Un error afecta a todo el bloque (mitigado por el respaldo) |
| 5 | Respaldo heurístico y modo demo | Fallar si el LLM no responde | La demo funciona sin API key y degrada con elegancia si hay errores de red | Las plantillas son menos ricas que el texto del LLM |
| 6 | Humano en el circuito (aprobar / rechazar / editar) | Publicación automática | Un LLM puede inventar datos; la marca no se arriesga | Requiere un paso manual |
| 7 | Interfaz en Streamlit | Gradio, React + API | Tableros y formularios en Python puro; ideal para un MVP de datos | Menos control del estado y del diseño |
| 8 | Almacenamiento con interfaz común (OCI o local) | Acoplar el código al SDK de OCI | Se desarrolla sin credenciales y se cambia de destino sin tocar el pipeline | Dos implementaciones que mantener |

## Diseño de IA y prompts

Hay cuatro cadenas de prompts, cada una con un rol, un tono y un esquema JSON de salida propios. Todas comparten la misma voz de marca, que se puede editar desde la interfaz, y la misma regla: no inventar empresas, cifras ni hechos que no estén en el mensaje.

| Cadena | Rol del sistema | Tono y límites | Salida |
| --- | --- | --- | --- |
| Análisis | Analista de comunidades | Objetivo; cita literal de máx. 25 palabras | sentimiento (−1 a 1), categoría, 1–3 temas, relevancia (0–100), cita, requiere_apoyo, justificación |
| Caso de éxito | Copywriter senior | LinkedIn inspirador de 500–1100 caracteres con gancho y 3–5 hashtags; X de máx. 260 caracteres | Ficha del caso + post LinkedIn + post X |
| FAQ | Mentor técnico | Didáctico; si falta información, marca `derivado_a_mentoria` | Título, respuesta breve, pasos, snippet, nivel |
| Resumen semanal | Editor del newsletter | Titular de máx. 90 caracteres, resumen de máx. 280 | Lectura de salud, destaque de newsletter, Community Highlights |

**Few-shot.** El prompt de LinkedIn incluye como ejemplo el post del enunciado del reto, para que el modelo copie la estructura (gancho, historia, cierre, hashtags) sin copiar el contenido.

**Puntuación de relevancia.** Ordena los momentos de la semana. Combina el valor comunicacional que estima el LLM con la intensidad emocional del mensaje, sea positiva o negativa, porque una alerta también merece atención:

```
Relevancia = 0.7 × R(LLM) + 0.3 × |s| × 100
```

Donde R(LLM) es la relevancia de 0 a 100 que devuelve el modelo y s es el puntaje de sentimiento de −1 a 1.

**Robustez.** El parser extrae el primer objeto JSON aunque el modelo lo envuelva en bloques de código. Cada campo se valida: un rango fuera de límites se recorta y una categoría desconocida se descarta. Si una llamada falla, solo esa parte cae a la heurística, y la interfaz muestra un aviso con la causa.

## Contrato de datos

La entrada respeta el formato del enunciado del reto. La salida lo amplía con curaduría, ranking y metadatos de almacenamiento, y agrupa los activos en listas porque un lote produce varios de cada tipo.

**Entrada.** Un objeto con el origen, el período y la lista de interacciones. También se acepta una lista sola o un CSV con las mismas columnas.

```json
{
  "origen_comunidad": "Discord_Grupo_ONE_G10",
  "periodo_referencia": "Semana_04",
  "interacciones": [
    {"autor": "Mariana Souza", "canal": "#logros-y-empleos", "tipo": "testimonio",
     "texto": "Comunidad, quede seleccionada para el puesto de Desarrolladora Junior de IA! ..."}
  ]
}
```

**Salida.** Extracto real del paquete que generó el lote de ejemplo de 9 mensajes, en modo demo y con todos los activos aprobados:

```json
{
  "status": "exito",
  "origen_comunidad": "Discord_Grupo_ONE_G10",
  "periodo_referencia": "Semana_04",
  "resumen_comunidad": {
    "total_interacciones_procesadas": 9,
    "sentimiento_predominante": "Altamente Positivo",
    "puntaje_sentimiento_promedio": 0.22,
    "temas_principales": ["OCI / Oracle Cloud", "LangGraph / Agentes", "Empleabilidad / Logros"],
    "alertas_apoyo": 1
  },
  "activos_distribucion_generados": {
    "posts_linkedin": [{"titulo": "De la comunidad al mercado: la historia de Mariana",
                        "canal_recomendado": "LinkedIn Oficial", "potencial_engagement": "Alto",
                        "estado_curaduria": "aprobado", "copy": "..."}],
    "sugerencias_contenido_faq": [{"tema": "Tip rápido: OCI / Oracle Cloud",
                                   "origen": "Andrés Quispe · #dudas-oci",
                                   "status": "derivado_a_mentoria"}],
    "posts_x": ["..."], "casos_exito": ["..."],
    "destaque_newsletter_semanal": ["..."], "community_highlights": ["..."]
  },
  "curaduria": {"aprobados": 14, "rechazados": 0, "pendientes": 0},
  "almacenamiento_oci": {
    "bucket": "communitylab-activos-marketing",
    "ruta_objeto": "activos/2026-semana-04/<timestamp>/paquete-distribucion.json",
    "status": "guardado_con_exito"
  }
}
```

Cada interacción analizada conserva su sentimiento, categoría, temas, cita, ruta, puntaje y justificación. Esos registros se guardan aparte en `analisis-interacciones.json` para poder auditar por qué un mensaje tomó una ruta.

## Interfaz y panel de curaduría

La app sigue el orden en que trabaja un community manager: cargar el lote, entender la semana, revisar el contenido y guardar lo aprobado. Las capturas son de la app real en modo demo, con el lote de ejemplo.

**1 · Ingesta.** Carga de JSON o CSV, tabla editable antes de procesar y configuración del motor, la voz de marca y OCI en la barra lateral.

![Pestaña de ingesta](img/01-ingesta.png)

**2 · Salud de la comunidad.** Métricas, distribución de sentimiento, temas en tendencia, mapa de sentimiento frente a relevancia y reparto por ruta.

![Tablero de salud de la comunidad](img/02-salud.png)

Más abajo, el ranking explica cada decisión (categoría, puntaje, ruta y justificación) y las alertas de apoyo destacan a quien necesita ayuda.

![Ranking de interacciones y alertas de apoyo](img/03-ranking.png)

**3 · Curaduría.** Cada activo se puede editar, aprobar, rechazar o restablecer, con filtros por tipo y estado, contador de 280 caracteres para X y barra de avance.

![Panel de curaduría](img/04-curaduria.png)

**4 · Paquete y OCI.** El paquete solo incluye lo aprobado, se descarga en JSON o Markdown y se sube al bucket. En esta captura el destino es el respaldo local, porque la app corre sin credenciales de OCI.

![Paquete guardado e historial del bucket](img/05-paquete.png)

## Persistencia en OCI y seguridad

Cada guardado escribe una carpeta con fecha y hora dentro de un bucket privado de la capa Always Free. Nada se sobrescribe, así que el bucket funciona como historial auditable de lo que el equipo aprobó cada semana.

```text
communitylab-activos-marketing/
└── activos/
    └── 2026-semana-04/
        └── 20261001-191500/
            ├── paquete-distribucion.json   # activos aprobados + resumen + metadatos
            ├── analisis-interacciones.json # una fila por mensaje: ruta, puntaje, justificación
            └── informe-comunidad.md        # informe legible para el equipo
```

| Control | Cómo se implementa |
| --- | --- |
| Credenciales fuera del código | `GOOGLE_API_KEY` en `.env`; OCI vía `~/.oci/config` o variables de entorno; `.env` y `*.pem` en `.gitignore` |
| Bucket privado | `NoPublicAccess` al crearlo desde la app; acceso solo con API key firmada |
| Costo cero | Solo Object Storage Always Free; sin servicios de pago |
| Fallos de red acotados | Timeout de 60 s y 2 reintentos por llamada al LLM; luego, respaldo heurístico |
| Fallos de OCI visibles | El error exacto aparece en la barra lateral y el guardado cae al respaldo local |
| Control editorial | Ningún activo entra al paquete sin aprobación, salvo que se active la opción de incluir pendientes |
| Trazabilidad | Cada activo guarda su origen (autor y canal) y su estado de curaduría |

Los mensajes de la comunidad se envían a la API de Gemini. En un despliegue real conviene anonimizar los nombres antes de enviarlos e informar a los miembros, porque el contenido es de ellos.

## Calidad y validación

La suite de pruebas pasa completa (19 de 19 en 0,05 s) y no necesita API key ni credenciales: corre en modo demo con un almacenamiento local temporal.

| Área | Qué se prueba | Casos |
| --- | --- | --- |
| Ingesta | Limpieza de espacios, filas vacías o inválidas, IDs duplicados, formatos de lote | 3 |
| Parser del LLM | JSON dentro de bloques de código o de texto libre; error claro si no hay JSON | 1 |
| Saneamiento | Recorte de rangos y descarte de categorías inventadas por el modelo | 1 |
| Ruteo condicional | Las 4 rutas y sus bordes: umbral de éxito, dudas con sentimiento negativo, alertas | 7 |
| Puntuación | Fórmula de relevancia y etiquetas de sentimiento en los límites | 1 |
| Extremo a extremo | Lote del reto: rutas esperadas, 6 tipos de activo, posts de X ≤ 280 caracteres, ranking ordenado | 3 |
| Curaduría y guardado | Solo entran los aprobados; se escriben 3 objetos y el JSON guardado es válido | 2 |
| Configuración | Modo Gemini sin API key falla con un mensaje claro | 1 |

**Transformaciones demostradas.** Con el lote de ejemplo, el flujo tomó estas decisiones (modo demo):

| Mensaje | Ruta | Activos generados |
| --- | --- | --- |
| Mariana Souza: contratada como Dev Jr de IA | Caso de éxito | Ficha + post LinkedIn + post X |
| Joaquín Méndez: aprobó OCI Foundations | Caso de éxito | Ficha + post LinkedIn + post X |
| Valentina Rojas: publicó su chatbot RAG | Caso de éxito | Ficha + post LinkedIn + post X |
| Lucas Albuquerque: nodos condicionales en LangGraph | FAQ | Tip rápido |
| Andrés Quispe: error de fingerprint en OCI | FAQ | Tip rápido |
| Diego Huamán: persistir el estado de un grafo | FAQ | Tip rápido |
| Camila Torres: frustrada, piensa abandonar | Alerta de apoyo | Aviso en el tablero (no genera contenido) |
| Renata Lima y Sofía Paredes: feedback y debate | Archivo | Solo cuentan para métricas y temas |

En total: 9 mensajes → 14 activos, incluidos el destaque del newsletter y los Community Highlights. El reto exige al menos 3 transformaciones.

**Pruebas de interfaz.** El flujo completo (cargar, procesar, aprobar, editar, guardar) se automatizó con Streamlit AppTest y Playwright. La revisión visual detectó y corrigió dos defectos: al aprobar un activo, la app volvía a la primera pestaña, y una duda con la palabra "error" se marcaba como alerta.

**Pendiente de validar con credenciales reales.** Las llamadas a Gemini y la subida al bucket están implementadas, y sus rutas de error fueron probadas, pero falta medir con la API key y el bucket propios la calidad de los textos y la latencia por lote.

## Limitaciones y roadmap

El MVP resuelve el flujo por lotes de punta a punta. Lo que falta es lo que necesitaría un equipo para usarlo a diario.

| Limitación actual | Impacto | Mejora propuesta |
| --- | --- | --- |
| Ingesta manual por archivo | Alguien debe exportar los mensajes | Webhook o bot de Discord que alimente el lote automáticamente |
| El estado de curaduría vive en la sesión de Streamlit | Si se cierra el navegador, se pierden las aprobaciones no guardadas | Guardar borradores en el bucket o en Autonomous Database Always Free |
| Sin usuarios ni roles | Cualquiera con acceso a la app puede aprobar | Inicio de sesión y rol de aprobador |
| Heurística del modo demo basada en palabras clave | Clasifica peor que el LLM en mensajes ambiguos | Conjunto de evaluación etiquetado para medir precisión por ruta |
| Pipeline secuencial | Lotes grandes tardan más | Llamadas en paralelo y migración a LangGraph con reintentos por nodo |

Roadmap propuesto, en orden de valor:

1. Desplegar la app en una VM Always Free de OCI Compute con Docker; es el diferencial opcional del reto.
2. Conectar un webhook de Discord o un flujo de n8n para la ingesta continua.
3. Persistir el estado de curaduría y agregar el rol de aprobador.
4. Crear un set de evaluación de 50 mensajes etiquetados y medir la precisión del ruteo con Gemini.
5. Generar tarjetas visuales para los casos de éxito con un modelo multimodal.

## Aprendizajes técnicos

- **Separar interpretación de decisión.** El LLM es muy bueno para leer un mensaje, pero las reglas de negocio deben vivir en código que se pueda probar. Eso permitió cubrir el ruteo con 7 casos de prueba deterministas.
- **Diseñar para el fallo.** Sin timeout, una red bloqueada dejaba la app colgada varios minutos. Con timeout, reintentos limitados y respaldo, el mismo fallo se resuelve en unos 3 segundos con un aviso claro.
- **Validar todo lo que devuelve un modelo.** Tratar la salida del LLM como datos externos, con parser tolerante y saneamiento por campo, evita que una respuesta mal formada rompa el lote completo.
- **Probar la interfaz con capturas reales.** Las pruebas unitarias pasaban, pero solo al ver la app renderizada aparecieron el reinicio de pestañas y los textos cortados. Streamlit identifica cada pestaña por su etiqueta: si la etiqueta cambia, se reinicia la navegación.
- **Desacoplar la infraestructura.** Una interfaz común para OCI y almacenamiento local permitió desarrollar y probar todo sin credenciales de la nube.
