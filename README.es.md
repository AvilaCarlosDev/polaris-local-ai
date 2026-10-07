# polaris-local-ai

[English](README.md) · **Español**

<p align="center">
<a href="https://github.com/AvilaCarlosDev/polaris-local-ai/actions/workflows/ci.yml"><img src="https://github.com/AvilaCarlosDev/polaris-local-ai/actions/workflows/ci.yml/badge.svg" alt="CI"></a>
<a href="LICENSE"><img src="https://img.shields.io/github/license/AvilaCarlosDev/polaris-local-ai" alt="Licencia: MIT"></a>
<a href="https://github.com/AvilaCarlosDev/polaris-local-ai/releases"><img src="https://img.shields.io/github/v/release/AvilaCarlosDev/polaris-local-ai" alt="Release"></a>
<a href="docs/HARDWARE.md"><img src="https://img.shields.io/badge/AMD-RX%20580%208%20GB-orange" alt="Corre en AMD RX 580 8 GB"></a>
</p>

**Una pila de IA completa y local — texto, visión y generación de imágenes — en
una AMD Radeon RX 580 2048SP (8 GB de VRAM) con 32 GB de RAM.** Sin nube, sin
facturas de API. También sirve como motor de inferencia para un agente de
programación/asistente de IA (Hermes Agent).

**Lo que estás viendo:** una escena de demostración renderizada y codificada en la RX 580. Muestra el equipo haciendo trabajo real de principio a fin, no la salida de un modelo por sí sola.

<p align="center"><a href="https://github.com/AvilaCarlosDev/polaris-local-ai/releases/download/v0.2.0/hero-scene-720.mp4"><img src="docs/media/hero-scene-preview.webp" width="720" alt="FLOATING ISLAND MIRAGE: diorama voxel con una isla flotante, un sombrero de paja gigante, palmeras y un velero, con la cámara orbitando"></a><br>
<sub><a href="https://github.com/AvilaCarlosDev/polaris-local-ai/releases/download/v0.2.0/hero-scene-720.mp4">FLOATING ISLAND MIRAGE (29 s)</a> — 870 frames renderizados y codificados en la máquina local, título generado por el qwen2.5-7b local</sub></p>

**Segundo clip:** un comando lista todos los modelos que sirve el router, una petición de chat se responde en 6,1 s y arranca una generación de imagen con SD 3.5. Todo corre en la RX 580; nada sale de la máquina.

<p align="center"><a href="https://github.com/AvilaCarlosDev/polaris-local-ai/releases/download/v0.2.0/hero.mp4"><img src="docs/media/hero-preview.webp" width="720" alt="El stack listando sus modelos por categoría, respondiendo un chat en 6,1 s y arrancando una generación con SD 3.5"></a><br>
<sub><a href="https://github.com/AvilaCarlosDev/polaris-local-ai/releases/download/v0.2.0/hero.mp4">video completo (29 s)</a> — una corrida real: 57 s de reloj, reproducido a 2×</sub></p>

> **Inspirado en [Strata](https://github.com/Niko1221/Strata).**
> Strata demostró que un stack de inferencia local serio se puede empaquetar
> para que una persona normal lo ejecute en una PC normal. Este repositorio
> sigue esa misma idea: un script de instalación, una API compatible con OpenAI
> en localhost, documentación con números reales — pero para hardware más
> antiguo y con otro motor. Aquí no hay código de Strata. Créditos a su autor
> por el concepto y por el estándar que fijó.
> Ver [NOTICE](NOTICE) para el aviso de atribución completo.

---

## Por qué existe

Strata apunta a tarjetas de 12 GB o más, de la serie RX 6800 en adelante, y su
ruta AMD requiere ROCm 7, que dejó atrás la arquitectura Polaris hace años. Una
RX 580 — todavía muy común — queda fuera de su alcance.

A esta pila eso no le importa. Corre sobre **Vulkan a través del driver RADV de
Mesa**, que soporta Polaris perfectamente, y se apoya en **32 GB de RAM del
sistema** para los modelos que no caben en 8 GB de VRAM. El resultado: seis
modelos de texto/visión y dos modelos de imagen, todos accesibles a través de
un único endpoint compatible con OpenAI.

## Qué obtienes

| | |
|---|---|
| **Texto** | 6 modelos, desde un coder de 1.5 B hasta un MoE de 30 B, intercambiados bajo demanda |
| **Visión** | Qwen2.5-VL 3 B con su proyector mmproj |
| **Imágenes** | SD 3.5 Medium y SD 1.5 a través de stable-diffusion.cpp |
| **API** | Un endpoint compatible con OpenAI, una API key, 6 ids de texto/visión + generación de imágenes |
| **Selector** | `ia-models` lista todos los ids que sirve el router, agrupados por categoría |
| **Agente** | Funciona como motor backend de Hermes Agent, con tools MCP |
| **Huella** | Corre en un LXC de Debian sobre un host Proxmox, o en bare metal |

Los números medidos, los pasos de instalación, la guía de modelos y todo lo que
se rompió en el camino están en [`docs/`](docs/):

- [EXPECTATIONS.md](docs/EXPECTATIONS.md) — **empieza por aquí**: qué esperar y cómo usarlo bien
- [HARDWARE.md](docs/HARDWARE.md) — qué corre en esta tarjeta y qué no
- [BENCHMARKS.md](docs/BENCHMARKS.md) — tokens/segundo, cold vs warm, latencia de agente — medido
- [MODELS.md](docs/MODELS.md) — qué modelo para cada tarea
- [SETUP.md](docs/SETUP.md) — instalación desde cero
- [HERMES.md](docs/HERMES.md) — usarlo como motor de agentes
- [TROUBLESHOOTING.md](docs/TROUBLESHOOTING.md) — los bugs que encontramos

## Cómo se siente en la práctica

Medido en esta máquina, no estimado. Mismo prompt, mismo modelo, dos estados:

| Situación | Tiempo total |
|---|---:|
| Llamada **warm**, modelo ya cargado | **3,1 – 14,1 s** |
| Llamada **cold**, recién después de un swap | **11,0 – 55,0 s** |
| Primer mensaje a un agente, sesión nueva | **~161 s** |
| Cada mensaje posterior en esa misma sesión | **~21 – 25 s** |

**La fila 1 vs la fila 2 es el swap** — 7,9–38,5 s para reiniciar llama-server
con los pesos nuevos. La velocidad de generación es idéntica en ambos estados
(21–99 tok/s); un modelo frío no es más lento, tarda más en *llegar*. Mantén un solo modelo
cargado durante toda la sesión y vives en la fila 1.

**La fila 2 vs la fila 3 es el agente, no la GPU.** Hermes envía un prompt de
**~20.100 tokens** (55 KB de identidad más 27 esquemas de tools), así que el
modelo se tarda ~124 s en leer tu frase antes de responderla en ~2,5 s. El
caché de prompts reduce eso a 25–71 tokens a partir del segundo turno, y ~11,7 s
de cada turno son el CLI del agente reiniciándose en cada invocación.

Desglose completo:
[BENCHMARKS.md](docs/BENCHMARKS.md) ·
[Qué esperar y cómo usarlo](docs/EXPECTATIONS.md).

## Primeros pasos

```bash
./setup.sh
```

El script verifica tu GPU, el driver Vulkan, la RAM y el disco, construye lo
que falte, instala las units de systemd y arranca el router. Se niega a
continuar si tu hardware no puede correr el stack — ver
[HARDWARE.md](docs/HARDWARE.md) para los requisitos exactos.

Después:

```bash
export IA_API_KEY=your-key
curl http://127.0.0.1:8090/v1/chat/completions \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer $IA_API_KEY" \
  -d '{"model":"qwen2.5-7b-instruct-q4_k_m",
       "messages":[{"role":"user","content":"Hello"}]}'
```

## Elegir un modelo

Preguntale al router qué sirve en lugar de adivinarlo de la documentación:

```bash
ia-models               # todos los ids, agrupados por categoría
ia-models -c vision     # una sola categoría
ia-models --json        # lista cruda para scripts
```

| Categoría | Ids | Cuándo usarla |
|---|---|---|
| `texto` | coder de 1.5 B → 7 B, más ornith 9 B | chat, resúmenes, código |
| `vision` | Qwen2.5-VL 3 B | la tarea involucra una imagen |
| `multitarea` | Qwen3-30B-A3B (3 B activos) | razonamiento largo y trabajo de agente |
| `imagen` | SD 3.5 Medium, SD 1.5 | querés una imagen |
| `audio` | whisper medium | transcripción — servicio aparte, listado solo si está instalado |

Las categorías salen del endpoint mismo (`GET /v1/models`), así que la lista
siempre dice la verdad: un `*` marca el modelo cargado en este momento, y nada
de la tabla puede desincronizarse de lo que el router corre de verdad. Los
trade-offs modelo por modelo están en [MODELS.md](docs/MODELS.md).

## Estructura del repositorio

```
router.py              Router compatible con OpenAI: intercambia modelos bajo demanda
image-mcp.py           Puente de generación de imágenes
clients/ia-imagen      CLI para generar una imagen y guardarla localmente
clients/ia-models      CLI que lista todos los modelos, agrupados por categoría
scripts/hero-demo.sh   El script detrás del video de arriba — corrélo vos mismo
systemd/               Las units que corren el stack
docs/                  Notas de hardware, benchmarks, instalación, gotchas
setup.sh               Instalador de una sola ejecución
```

## Créditos y licencia

- **[Strata](https://github.com/Niko1221/Strata)** — MIT, de su autor. La
  inspiración para el alcance y el empaquetado de este proyecto. No es un fork;
  aquí no hay código fuente de Strata.
- **[llama.cpp](https://github.com/ggml-org/llama.cpp)** — el motor de
  inferencia de texto y visión.
- **[stable-diffusion.cpp](https://github.com/leejet/stable-diffusion.cpp)** —
  el motor de imágenes.
- **[Qwen](https://qwen.ai/)**, **Ornith**, **ISTA-DASLab** — las familias de
  modelos usadas acá; cada una con su propia licencia.

Este repositorio tiene licencia MIT. Los pesos de los modelos **no** están
incluidos y conservan sus propias licencias.
