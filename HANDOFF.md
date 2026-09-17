# NovaForge — contexto para retomar el trabajo

Documento de traspaso. Escrito para una sesión que empieza sin historial.
Fecha: 2026-09-17.

---

## 1. Qué es el proyecto

NovaForge es un harness multiagente dirigido por especificación que escribe
novelas de ciencia ficción. Su afirmación central, y la razón de que exista:

> **El escritor de capítulos nunca ve la prosa de un capítulo anterior.** Recibe
> la Story Bible, su propia entrada del outline y un resumen rodante acotado. El
> prompt del capítulo 34 mide lo mismo que el del capítulo 1.

- **Ruta local:** `C:\Users\student\Desktop\novaforge`
- **GitHub:** https://github.com/davidcalham12/Harness-prueba1
- **Idioma de trabajo con el usuario:** español. Toda la documentación del repo
  está en inglés.

## 2. Hay DOS ramas y no son intercambiables

### `main` — la implementación en Python

149 ficheros. Paquete `novaforge/`, 810 tests, fixture reproducible byte a byte
en `output/golden-tiny/`, log de auditoría encadenado por hash, techos de gasto
comprobados antes de cada llamada, seis capas de seguridad SEC-1..SEC-6, e
integración Langfuse en vivo (`novaforge/observability/langfuse.py`).

**Su debilidad:** el motor que se envía es `mock` y **ignora la premisa**. Dos
premisas opuestas producen capítulos byte-idénticos. `--engine anthropic` nunca
se implementó, así que lo único que el proyecto dice hacer es lo único que nunca
demostró.

### `claude-orchestrator` — la rama actual, y donde está el trabajo

33 ficheros. Claude Code es el orquestador; los 8 agentes son subagentes de
Claude Code. Registrado en `specs/changes/CHG-003-claude-as-orchestrator.md`.

Commits, del más antiguo al más reciente:

```
96e2240  Claude Code as the orchestrator, the agents as subagents
dfc3667  Ship a finished run to Langfuse from its log
ccc23aa  auth_check raises, it does not return False
9e990c9  Token spend in the traces, with the cost honestly bounded
```

`main` está intacta. El usuario eligió explícitamente hacer la refactorización
en rama para no perder nada.

## 3. Estructura de `claude-orchestrator`

```
.claude/agents/           los 8 subagentes: prompt + lista de herramientas
.claude/skills/novaforge/ SKILL.md, el procedimiento de orquestación
specs/flow.yaml           las 6 etapas, su orden y política de fallo
specs/agents/*.md         una spec por agente, requisitos AGT-*
specs/acceptance.md       ACC-1..ACC-11, cada uno marcado con cómo se establece
specs/CONFIG-SPEC.md      CFG-1..CFG-13, con CFG-4/7/11/12 retirados
specs/changes/            CHG-001, CHG-002 (históricos), CHG-003 (esta refact.)
config/novel.config.json  la base
config/profiles/          tiny(3 cap) small(8) medium(18) full(34)
config/pricing.json       tarifas de modelo y la suposición del coste
tools/export_to_langfuse.py
tools/backfill_tokens.py
docs/novaforge_flow.mermaid
README.md  SECURITY.md  HANDOFF.md
```

`output/` está en `.gitignore`: en esta rama nada reproduce, así que una
ejecución comiteada sería una muestra, no algo que un diff pueda comprobar.

## 4. Los 8 subagentes y el modelo de autoridad

La columna de herramientas **es** el modelo de autoridad. No es cosmética.

| agente | etapa | tools | escribe la Bible |
|---|---|---|---|
| `worldbuilder` | FLOW-1 | `Write` | sí |
| `character-architect` | FLOW-2 | `Write` | sí |
| `plot-architect` | FLOW-3 | `Glob` | no |
| `chapter-writer` | FLOW-4 | `Glob` | no |
| `style-editor` | FLOW-5 | `Glob` | no |
| `publisher` | FLOW-6 | `Glob` | no |
| `continuity-critic` | gate FLOW-4 | `Glob` | no |
| `science-critic` | gate FLOW-4 | `Glob` | no |

Modelos: los cuatro primeros en `opus`, los cuatro últimos en `sonnet`.

**La línea que justifica toda la rama** está en
`.claude/agents/chapter-writer.md`:

```yaml
tools: Glob
```

`Glob` devuelve rutas de fichero y **no puede devolver el contenido**. El
subagente corre en su propia ventana de contexto, así que `chapters/ch01.md` le
es inalcanzable incluso queriendo. En `main` la misma política es un `assert` en
`novaforge/context.py:assert_no_prior_prose` que relee el prompt ya montado — una
comprobación que se puede quitar. Aquí es aritmética sobre lo que el agente puede
hacer.

Los dos agentes con `writes_bible: true` en `specs/flow.yaml` son exactamente los
dos con la herramienta `Write`. Está verificado.

## 5. El gate

Cuatro críticos por borrador, agregados con `min` — un capítulo vale lo que su
peor crítico. Umbral 8. Hasta 2 reescrituras, luego `accept_with_warnings`.

| crítico | quién lo corre | reproducible |
|---|---|---|
| `length` | el orquestador, `wc -w` | **sí** |
| `chatter` | el orquestador, escaneo de encabezado | **sí** |
| `continuity` | subagente | **no** |
| `science` | subagente | **no** |

Esa columna es el coste honesto de la rama. En `main` los cuatro eran
deterministas, que es lo que hacía posible el fixture comiteado.

## 6. La ejecución que se hizo

`output/deep-space-salvage-derelict/`, perfil `tiny`, config_hash `5558f78997e9`.

Premisa: *"A deep-space salvage crew finds a derelict that remembers them"*
(la canónica del proyecto, para poder comparar con el fixture que `main` conserva).

**Resultado:** 3 capítulos, 1.360 palabras de prosa, 24 llamadas a subagentes de
un techo de 120.

| capítulo | borrador 1 | borrador 2 | palabras | líneas |
|---|---|---|---|---|
| ch01 Warm Hull | 10/10/10/10 accept | — | 425 | 31 |
| ch02 Timestamps | 7/8/10/10 **retry** | 9/10/10/10 accept | 465 | 27 |
| ch03 Attendance | 3/10/10/10 **retry** | 10/10/10/10 accept | 470 | 29 |

El canon: nave remolcadora *Bittern* (ORC-114), pecio *Thule Rise* perdido en
2180. Personajes canónicos: **Ilse Tarkanen, Jonah Rook, Priya Mahalingam,
Nadia Devereaux, Emmerich Vogel**.

### El hallazgo más importante de la ejecución

En el capítulo 3 **los dos críticos se contradijeron sobre el mismo párrafo**:

- `continuity-critic` puntuó 3/10 alegando que *"Departure spent 1.6 of the
  remaining 1.9"* contradecía la Biblia (2.9 − 1.6 = 1.3).
- `science-critic` puntuó 10/10 diciendo que era coherente.

El orquestador lo comprobó con aritmética. La regla de `bible/world.md` dice
*"Rendezvous, station-keeping, and departure all spend from it"*, así que cuatro
días en posición gastan ~1.0: 2.9 − 1.0 = 1.9, y 1.9 − 1.6 = 0.3. **El hallazgo
de continuidad era falso y NO se le pasó al escritor**, porque le habría hecho
estropear un texto correcto. Queda registrado con `"upheld": false` en
`critiques/ch03.continuity.json` y como fila `critic_disagreement` en el log.

En `main` esto era imposible: los cuatro críticos eran código.

### Otros defectos que salieron ejecutando, no leyendo

- El `worldbuilder` reportó ~870 palabras cuando eran **948**. Lo pilló el
  `wc -w` del orquestador, no el informe del agente.
- Los resúmenes que escribió el propio orquestador se pasaron del tope de 120
  palabras **cuatro veces** (145, 139, 135, 121).
- Ninguna línea de prosa empezó por `## `, pero **nada lo impide** — ver §9.

## 7. Langfuse

**Funciona y está verificado contra el proyecto real del usuario.**

- Host: `https://us.cloud.langfuse.com` — **EEUU, no Europa**. El SDK cae en la
  región europea por defecto y devuelve un 401 que no menciona regiones. Este
  proyecto ha tropezado con esto **tres veces**.
- Proyecto: `cmu5oyaks0269ad0iaary15mg`
- Credenciales guardadas a nivel de usuario en Windows:
  `LANGFUSE_PUBLIC_KEY`, `LANGFUSE_SECRET_KEY`, `LANGFUSE_BASE_URL`.

No hay MCP de Langfuse cargado en la sesión. No hace falta; el SDK basta.

### Cómo se usa

```powershell
python tools/export_to_langfuse.py output/<slug> --dry-run   # sin claves ni red
python tools/export_to_langfuse.py output/<slug>             # sube
python tools/export_to_langfuse.py output/<slug> --fresh etiqueta
```

`--fresh` acuña una traza nueva. Sin él, reexportar añade una **segunda copia**
de cada generación a la traza existente en vez de reemplazarla.

Trazas de la ejecución actual:

```
sin tokens: .../traces/6bc36ec055b1ffdc2f5c5924f766c783
CON tokens: .../traces/4c3cd7a6f4b968a64a6c041b086e25d4   <- usar esta
```

### Tokens y coste

**281.202 tokens.** Reparto:

```
continuity-critic    76.333   27,1%
science-critic       67.852   24,1%
chapter-writer       41.129   14,6%
worldbuilder         28.738   10,2%
style-editor         25.415    9,0%
publisher            15.524    5,5%
plot-architect       13.112    4,7%
character-architect  13.099    4,7%
```

**Los dos críticos se llevan el 51%** — más que el escritor, el worldbuilder y el
outline juntos. El gate es la mitad cara del pipeline.

**El coste está acotado, no calculado.** El harness reporta un solo total de
tokens por subagente, sin separar entrada de salida, así que:

- $0,85 si cada token fuera de entrada (cota exacta)
- $4,25 si cada token fuera de salida (cota exacta)
- **$1,36 estimado**, asumiendo 85% de entrada

Ese 85% es `assumed_input_share` en `config/pricing.json` y es una suposición,
no una medida. Las tres cifras viajan en metadata de cada generación.

Tarifas en `config/pricing.json`, de la página de precios de Anthropic con fecha:
Opus 5 $5/$25 y Sonnet 5 $2/$10 por millón.

Los tokens de esta ejecución van marcados **`tokens_source: reconstructed`**:
se copiaron del transcript de la sesión, no se registraron en vivo.
`SKILL.md` ya indica registrarlos en vivo de ahora en adelante.

## 8. PENDIENTE — lo primero que hay que atender

### 8.1 Defecto de diseño bloqueado por permisos

`.claude/agents/worldbuilder.md` y `.claude/agents/character-architect.md` tienen
`tools: Write` **sin `Read`**. La herramienta Write se niega a sobrescribir un
fichero que la sesión no ha leído, así que **un escritor de la Biblia puede
crearla pero no revisarla**. Durante la ejecución esto bloqueó al worldbuilder;
se resolvió borrando el fichero para que lo escribiera limpio. Costó **17.479
tokens en una llamada que no produjo nada**.

El arreglo es:

```yaml
tools: Read, Write
```

Intenté hacerlo y **el clasificador de permisos lo denegó como Self-Modification**.
Necesita que el usuario lo autorice. No toca la garantía del `chapter-writer`,
que sigue con `Glob` solo.

### 8.2 Rotación de claves Langfuse

El usuario ha pegado **cuatro claves** en conversaciones (dos pares completos).
Las actuales funcionan pero están comprometidas. Rotar en Settings → API Keys y
volver a guardarlas con:

```powershell
[Environment]::SetEnvironmentVariable('LANGFUSE_PUBLIC_KEY','<valor real>','User')
[Environment]::SetEnvironmentVariable('LANGFUSE_SECRET_KEY','<valor real>','User')
```

**Nunca pedirle que pegue una clave en el chat.** El exportador las lee del
entorno; una sesión puede verificarlas con `auth_check()` sin verlas jamás.

## 9. Lo que esta rama NO da

Está todo en `specs/acceptance.md` y `SECURITY.md`, marcado criterio por criterio.
Resumen:

- **Cero verificación automática.** No hay suite de tests. ACC-6
  (reproducibilidad) y ACC-9 (techo de gasto) están **retirados**, no matizados.
- **El gate no reproduce.** "Pasó el gate" es una afirmación sobre una ejecución,
  no una propiedad del texto.
- **No hay auditoría a prueba de manipulación.** `logs/agents.jsonl` es un
  fichero plano sin encadenar.
- **No hay validación de entrada ni escapado de salida.** Un párrafo que empiece
  por `## ` se convierte en encabezado de capítulo al concatenar `dist/book.md`.
  En `main` eso lo escapaba SEC-5.
- **No corre desatendido.** No hay punto de entrada headless: ni CI, ni cron.
- **No hay PDF.** Era `novaforge/export/pdf.py`.

`SECURITY.md` compara las seis capas contra `main` en una tabla: **una mejoró,
cinco empeoraron.**

## 10. Cómo ejecutar una novela nueva

Dentro de Claude Code, en el directorio del proyecto:

```
/novaforge
```

Da premisa y perfil. `tiny` son 3 capítulos y ~16 llamadas mínimo. `full` son 34
capítulos por un gate de cuatro críticos — el procedimiento obliga a decir el
número de llamadas antes de empezar, y **nada frena el gasto durante**.

El procedimiento completo está en `.claude/skills/novaforge/SKILL.md` y es lo
primero que debe leer cualquier sesión que vaya a orquestar.
