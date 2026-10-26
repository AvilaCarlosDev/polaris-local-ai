# Informe de investigación: mejoras para la IA local de Carlos

Fecha: 26 de octubre de 2026

## Resumen

El mayor cuello de botella no es el decode del modelo, sino el prefill de prompts de 18–20 K tokens y el arranque de Hermes/OpenCode. La configuración actual de Qwen3.6 ya evita el error más grave: llenar completamente la RX 580 con `-ngl 99`. La mejora con mayor probabilidad es reducir y estabilizar los prompts de los agentes, mantener sesiones persistentes y aprovechar correctamente el guardado/restauración de slots. `--cache-reuse 4096` ya está activo y funciona: el segundo turno reduce el prefijo evaluado de 20.109 a unos 25 tokens. `-fa` merece una prueba A/B, pero no debe asumirse que será positivo en Polaris/RADV. `--override-tensor` puede sustituir pruebas de `--n-cpu-moe`, aunque su beneficio es incierto. La especulación basada en n-gram ya mejora ediciones, pero los GGUF actuales no contienen MTP. No hay evidencia independiente suficiente para recomendar otro modelo ≤18 GB que supere claramente a Qwen3.6 en este equipo. Para imágenes, SDXL Turbo es la alternativa más razonable; FLUX Schnell y Chroma probablemente serán demasiado lentos en Polaris.

## Datos verificados en el repositorio

- Hardware: Ryzen 5 5600G, 32 GB RAM, RX 580 2048SP de 8 GB, RADV/Vulkan.
- Qwen3.6-35B-A3B UD-IQ4_XS:
  - `--n-cpu-moe 32`: 6,491 MiB VRAM, prefill 254 tok/s.
  - `--n-cpu-moe 30`: 7,221 MiB VRAM, configuración actual.
  - `--n-cpu-moe 26`: 7,909 MiB y caída a 171 tok/s.
  - Prefill práctico: aproximadamente 240 tok/s.
  - Decode: aproximadamente 17–19 tok/s.
- Forzar todo a GPU fue contraproducente:

  | Configuración | Decode |
  |---|---:|
  | `-ngl 99`, VRAM al 99,4 % | 8,12 tok/s |
  | Ajuste automático con margen libre | 22,26 tok/s |

- Prompt de Hermes:
  - Primer turno: 20.109 tokens, 123,6 s de prefill.
  - Segundo turno: 25 tokens re-evaluados, 1,7 s.
  - Arranque del proceso Hermes: aproximadamente 11,7 s.
- OpenCode con prompt reducido:
  - Qwen3.6: 18.639 tokens, 192 tok/s de prefill, 244 s totales.
- `ngram-mod`:

  | Tarea | Sin especulación | `ngram-mod` |
  |---|---:|---:|
  | Editar archivo | 17,0 tok/s | 27,4 tok/s |
  | Código nuevo | 18,8 tok/s | 17,6 tok/s |
  | Chat | 15,2 tok/s | 18,8 tok/s |

- `draft-mtp` falla porque el GGUF de Qwen3.6 no contiene capas MTP.
- Ornith 35B obtuvo 39/40 en la matriz de tareas, frente a 38/40 para Qwen3.6+n-gram, pero la diferencia está dentro de la variabilidad observada.
- SD 3.5 Medium tarda aproximadamente 61–74 s a 512²; SD 1.5, aproximadamente 33 s.

Fuentes internas: [router.py](/home/carlosdev/Projects/polaris-local-ai/router.py), [BENCHMARKS.md](/home/carlosdev/Projects/polaris-local-ai/docs/BENCHMARKS.md), [HARDWARE.md](/home/carlosdev/Projects/polaris-local-ai/docs/HARDWARE.md).

## Propuestas priorizadas

| Prioridad | Cambio | Mejora esperada | Riesgo | Esfuerzo | Cómo medir |
|---|---|---|---|---|---|
| P0 | Reducir el prompt base de Hermes/OpenCode y eliminar herramientas no usadas | 2–5× menor latencia del primer turno; potencialmente decenas de segundos | Puede perder capacidades o instrucciones | Bajo/medio | `scripts/bench-agents/rondas.sh`; comparar tamaño de prompt y tiempo total |
| P0 | Mantener una sesión persistente por agente/modelo | Elimina casi todo el coste de prefill después del primer turno | Mayor consumo de RAM/KV; peor aislamiento | Bajo | Tres turnos consecutivos con `scripts/bench-agents` y registro de timings |
| P0 | Usar `--slot-save-path` y save/restore por sesión | Recuperar sesiones después de reinicios sin repetir todo el prefill | El archivo KV depende de modelo, build y configuración | Bajo/medio | Comparar `/slots/{id}?action=save/restore`; medir tokens restaurados y `save_ms` |
| P1 | Probar `-fa` en Qwen3.6 y Ornith 35B | Posible mejora de prefill y menor memoria KV; 0–30 % como estimación | Puede ser neutro, más lento o inestable en RADV/Polaris | Bajo | A/B con `scripts/bench-agents/bench_chat.py`, prompts de 5,7 K y 18 K |
| P1 | Probar `-ub 1024`, `2048`, `4096` y batches equivalentes | Posible mejora de prefill de 5–20 % | Más memoria temporal; riesgo de `VK_ERROR_OUT_OF_DEVICE_MEMORY` | Bajo | `bench_chat.py`; medir pp512, pp4096 y prompt real |
| P1 | Probar `--override-tensor` para mover selectivamente expertos o FFN a CPU | Quizá permita subir prefill sin sobrellenar VRAM | El patrón de tensores puede variar; puede empeorar por transferencias | Medio | Comparar con `--n-cpu-moe 30/32`; registrar VRAM y tok/s |
| P1 | Comparar KV `q8_0` frente a `q4_0` | Más margen de VRAM; posiblemente permitir más expertos en GPU | Pérdida de calidad/estabilidad y posible penalización en modelos híbridos | Bajo | Misma matriz de tareas, misma semilla; medir VRAM, prefill y score |
| P1 | Actualizar llama.cpp y repetir pruebas antes de adoptar | Posibles mejoras en qwen35moe, Vulkan, MTP y especulación | Regresiones de RADV o cambios incompatibles | Medio | Guardar build actual; ejecutar `bench-agents` y `bench-spec` antes/después |
| P2 | Probar `GGML_VK_VISIBLE_DEVICES` para separar RX 580 e iGPU | Permitir asignar una tarea secundaria a la Vega | La iGPU comparte RAM y ancho de banda; puede frenar al modelo principal | Medio | Medir Qwen3.6 solo y simultáneo con Whisper/visión |
| P2 | CPU o Vega para Whisper, embeddings o Qwen2.5-VL 3B | Libera la RX 580 para el modelo principal | Contención de RAM/PCIe; ganancia no garantizada | Medio | Benchmarks concurrentes y no concurrentes; medir p95 de latencia |
| P2 | Probar SDXL Turbo | Mejor calidad que SD 1.5 con pocos pasos | Probablemente más lento y con mayor consumo que SD 1.5 | Medio | `scripts/bench-images.py`, 512², 1–4 pasos, misma semilla |
| P3 | Probar FLUX Schnell cuantizado | Mejor composición y calidad general potencial | Muy lento en RX 580; posible uso intensivo de RAM | Medio/alto | Medir 512² y 768²; registrar tiempo, VRAM y RAM |
| P3 | Probar Chroma cuantizado | Alternativa más pequeña derivada de FLUX | Ecosistema y soporte menos maduros; calidad variable | Medio/alto | Igual que FLUX; no asumir que será más rápido |
| P3 | Buscar un GGUF de Qwen3.6 con MTP real | Podría superar ampliamente a n-gram en decode | Debe ser compatible con la build, vocabulario y arquitectura | Alto | `scripts/bench-spec`; validar metadatos GGUF antes de ejecutarlo |

Las opciones `-fa`, `--override-tensor`, `--cache-reuse`, slots y `--n-cpu-moe` están documentadas en la interfaz actual de `llama-server` ([README oficial de server](https://github.com/ggml-org/llama.cpp/blob/master/tools/server/README.md), consultado el 26-10-2026).

## 1. Vulkan, RADV y flags de llama.cpp

### Flash Attention: probar, no activar a ciegas

`-fa` puede reducir memoria y mejorar atención, especialmente con contextos largos. Sin embargo, la ruta Vulkan históricamente no tenía una implementación general equivalente a CUDA; además, existe una incidencia reciente sobre rutas de Flash Attention en modelos híbridos Qwen3.5/Qwen3.8 con KV no unificado ([incidencia de llama.cpp #28135](https://github.com/ggml-org/llama.cpp/issues/28135), 2026).

Recomendación:

```text
A/B:
sin -fa
con -fa
```

Medir por separado:

- prefill de 512 y 4096 tokens;
- prompt real de 5.700 y 18.000 tokens;
- decode;
- VRAM;
- errores `VK_ERROR_DEVICE_LOST`.

No esperaría más de 0–30 % de mejora sin medirlo. En Polaris, la ausencia de matrix cores e int-dot limita la ganancia potencial.

### Batch y ubatch

El valor actual `-ub 2048` es razonable. El batch grande beneficia el prefill, pero el ubatch aumenta memoria temporal y presión sobre Vulkan. Conviene probar:

```text
-ub 512
-ub 1024
-ub 2048
-ub 4096
```

La prueba debe hacerse con el mismo contexto, modelo y prompt. El objetivo es encontrar el máximo que no provoque spill adicional ni inestabilidad.

### `--override-tensor` frente a `--n-cpu-moe`

`--n-cpu-moe` mueve expertos de las primeras capas a CPU. `--override-tensor` permite escoger por patrón de tensor el buffer de destino, por ejemplo CPU o Vulkan. La documentación oficial lo describe como una selección por patrón de nombre, mientras que `--n-cpu-moe` es una política más específica para expertos ([server README](https://github.com/ggml-org/llama.cpp/blob/master/tools/server/README.md)).

La prueba interesante sería mantener atención y partes densas en GPU, y mover solamente ciertos tensores de expertos. No hay evidencia local de que supere a `--n-cpu-moe 30`; por tanto, es una optimización experimental, no una recomendación inmediata.

### mmap, mlock e hilos

- `mmap`: debe permanecer activado salvo que se observe paginación problemática.
- `mlock`: probablemente no cabe de forma segura con 24 GB asignados al LXC y el modelo de 16–19 GB; puede provocar presión de RAM. No lo recomendaría por defecto.
- Hilos: el valor actual `--threads 6` coincide con los seis hilos asignados al LXC. Subirlo no crea CPU adicional y puede aumentar contención. Probar 4, 6 y 8 solo si Proxmox realmente expone más CPU al contenedor.
- `--numa`: el Ryzen 5600G es esencialmente un sistema de un nodo NUMA. No espero mejora. La documentación de llama.cpp reserva esta opción para sistemas NUMA y recomienda medirla ([server README](https://github.com/ggml-org/llama.cpp/blob/master/tools/server/README.md)).

### Variables Vulkan/Mesa

Variables relevantes:

- `GGML_VK_VISIBLE_DEVICES`: seleccionar explícitamente RX 580 o Vega.
- `GGML_VK_DISABLE_F16=1`: útil como prueba de compatibilidad/rendimiento.
- `GGML_VK_DISABLE_COOPMAT=1`: relevante para aislar rutas cooperativas si causan errores.
- `RADV_PERFTEST`: solo debe probarse con valores documentados por la versión instalada de Mesa.
- `RADV_PROFILE_PSTATE`: aparece en la documentación actual de Mesa, pero no debe asumirse que ayude en una RX 580.

La documentación oficial de Mesa lista las variables RADV disponibles ([Mesa Environment Variables](https://docs.mesa3d.org/envvars.html), consultada el 26-10-2026). No encontré evidencia sólida de que `RADV_PERFTEST` mejore específicamente Polaris en esta carga. Tratarlo como diagnóstico, no como optimización garantizada.

### Actualizar llama.cpp

Sí merece una prueba controlada. La build local es de `0c1e570`, del 1 de octubre de 2026. Desde entonces, la documentación y el código upstream incluyen cambios en:

- tipos de especulación `draft-eagle3`, `draft-dflash`, `draft-dspark`, `draft-mtp`;
- métricas de aceptación especulativa;
- soporte y ajustes para modelos híbridos;
- rutas Vulkan y selección de dispositivos.

Fuentes: [speculative decoding de llama.cpp](https://github.com/ggml-org/llama.cpp/blob/master/docs/speculative.md), [server README](https://github.com/ggml-org/llama.cpp/blob/master/tools/server/README.md).

La actualización solo debe adoptarse si mejora simultáneamente:

1. `bench-spec`;
2. prefill real de agentes;
3. decode;
4. estabilidad durante sesiones largas.

## 2. Prompts largos y caching

Esta es la mejora más segura.

El repositorio ya demuestra que el caching funciona: el segundo turno de Hermes solo reevalúa 25 tokens frente a los 20.109 iniciales. Por tanto:

- reducir el primer prompt produce la mayor ganancia inmediata;
- reducir herramientas inútiles tiene más impacto que ajustar unos pocos flags Vulkan;
- el modelo debe permanecer residente;
- se debe evitar alternar entre Qwen3.6, Ornith, visión e imagen durante una misma sesión.

`--cache-reuse 4096` ya está configurado. Conviene probar 2048, 4096 y 8192, pero no asumir que un valor mayor sea mejor: la búsqueda de coincidencias puede consumir más CPU y memoria.

El guardado de slots es especialmente útil para reinicios y swaps. La API oficial permite guardar y restaurar el prompt cache de un slot mediante `/slots/{id}/?action=save|restore` ([server README](https://github.com/ggml-org/llama.cpp/blob/master/tools/server/README.md)).

### Recorte recomendado

Prioridad de recorte:

1. herramientas MCP no usadas por el agente;
2. instrucciones duplicadas;
3. documentación de skills que no aplican a la tarea;
4. historial redundante;
5. ejemplos largos que no son necesarios;
6. schemas completos cuando el agente solo necesita un subconjunto.

No recomiendo truncar ciegamente el historial: puede romper la coherencia del agente. Es mejor resumir por sesión y mantener intactos los últimos turnos y las decisiones relevantes.

## 3. Decodificación especulativa

### Estado actual

El resultado local es claro:

- `ngram-mod` es útil para editar archivos;
- empeora ligeramente código nuevo;
- no necesita VRAM adicional;
- el GGUF de Qwen3.6 no tiene capas MTP.

La documentación upstream confirma que llama.cpp soporta draft model, MTP, EAGLE3, DFlash, DSpark y variantes n-gram ([speculative.md](https://github.com/ggml-org/llama.cpp/blob/master/docs/speculative.md)).

### Qué tendría que verificarse

Para usar un modelo draft externo:

- vocabulario compatible;
- tokenizer compatible;
- arquitectura compatible;
- salida de logits compatible;
- suficiente aceptación;
- coste del draft menor que el ahorro de verificación.

Un Qwen3-0.6B o Qwen3-1.7B podría caber en la VRAM libre, pero no hay evidencia local de que sea compatible con Qwen3.6-35B-A3B. No debe descargarse ni adoptarse solo por compartir la marca Qwen.

`draft-eagle3`, `dflash` y `dspark` requieren checkpoints especialmente entrenados o exportados. Un modelo pequeño genérico no sustituye a un draft EAGLE/DFlash.

### Recomendación

Mantener:

- `ngram-mod` para ediciones;
- modo normal para código nuevo;
- una prueba futura con GGUF MTP real de Qwen3.6, si aparece una versión compatible.

No priorizar EAGLE3/DFlash/DSpark hasta disponer de un checkpoint explícitamente compatible y una build que lo soporte.

## 4. Modelos alternativos ≤18 GB

### Conclusión

No encontré evidencia independiente suficiente para afirmar que un modelo ≤18 GB supere a Qwen3.6 en este hardware y en tareas de agente/código.

La evidencia interna favorece actualmente a:

1. Ornith 35B-A3B: mejor score medido, 39/40.
2. Qwen3.6-35B-A3B: 38/40 con OpenCode y 38/40 en la medición comparable de Hermes.
3. Ornith 9B: más rápido y sorprendentemente competitivo en tareas acotadas.
4. Qwen3-30B-A3B: peor calidad en la matriz, especialmente en `refactor`.

Fuentes externas sugieren que Qwen3.6 es fuerte en coding y agentes, pero varias cifras proceden de benchmarks agregados, model cards o pruebas comunitarias, no de comparaciones controladas en una RX 580:

- [Qwen3.6-35B-A3B model card](https://huggingface.co/Qwen/Qwen3.6-35B-A3B)
- [llmrun benchmark aggregation](https://llmrun.dev/model/qwen-qwen3-6-35b-a3b/benchmarks)
- [llm-bench model results](https://llm-bench.io/models/qwen-qwen3-6-35b-a3b)

Candidatos que merecen benchmark, pero no recomendación anticipada:

- Qwen3.5-9B Q4: cabe holgadamente y puede ser rápido.
- Qwen3.5-27B Q4: probablemente demasiado cercano al límite de RAM/VRAM y podría perder en prefill.
- DeepSeek-Coder-V2 Lite 16B: candidato MoE/code, pero la evidencia de calidad agente en este hardware es insuficiente.
- Gemma 4 12B: buen modelo general, pero no hay evidencia local de superioridad en código.
- Qwen3-Coder pequeño: interesante si el objetivo es código, pero debe evaluarse con los graders del repositorio.

### Cuantización

Cambiar de IQ4_XS a Q4_K_M o una cuantización con menor error KLD puede mejorar calidad, pero normalmente aumenta memoria. La opción solo tiene sentido si:

- el modelo sigue dejando margen para KV;
- la mejora de score compensa la caída de velocidad;
- se mide con `bench-agents`.

La comparación correcta no es solo perplexity: debe incluir `semver`, `bugfix`, `cli`, `refactor` y tareas reales de OpenCode/Hermes.

## 5. Vega iGPU y CPU

La Vega integrada no tiene matrix cores y usa RAM compartida. Puede ser útil para tareas secundarias, pero no conviene asumir que la ejecución concurrente sea gratuita.

Usos razonables:

- Whisper;
- embeddings;
- Qwen2.5-VL 3B;
- modelo draft pequeño;
- reranking o clasificación.

Usos poco recomendables:

- mover parte de Qwen3.6 a la Vega mientras la RX 580 ejecuta el resto;
- ejecutar simultáneamente dos modelos grandes Vulkan;
- usarla para SD mientras la RX 580 atiende al LLM.

El experimento correcto sería:

1. medir Qwen3.6 solo;
2. medir Whisper o visión en CPU;
3. medir en Vega;
4. medir simultáneamente;
5. aceptar la opción solo si la latencia p95 del modelo principal no empeora más de aproximadamente 10 %.

## 6. Imagen

### SDXL Turbo

Es la alternativa más razonable a probar. Requiere pocos pasos y puede producir más calidad estructural que SD 1.5. Sin embargo, el modelo es más pesado y la RX 580 carece de aceleradores modernos. Estimación: entre 1,5× y 4× el tiempo de SD 1.5, dependiendo de resolución y cuantización.

### FLUX Schnell

`stable-diffusion.cpp` soporta FLUX Schnell y SDXL Turbo ([stable-diffusion.cpp](https://github.com/leejet/stable-diffusion.cpp)). FLUX Schnell puede generar en pocos pasos, pero el coste por paso y sus encoders son mucho mayores. En una RX 580, esperaría:

- 512²: aproximadamente 2–10 minutos;
- 768²: potencialmente más de 10 minutos;
- posible uso significativo de RAM y swapping.

Estas cifras son estimaciones, no mediciones locales.

### Chroma

Chroma deriva de FLUX Schnell y reduce el tamaño del modelo, pero sigue siendo una carga mucho mayor que SD 1.5/SD 3.5. Puede ser interesante por calidad, no por velocidad. Lo pondría detrás de SDXL Turbo y antes de FLUX Dev.

### Recomendación de imagen

1. Mantener SD 3.5 Medium para calidad y texto legible.
2. Mantener SD 1.5 para velocidad.
3. Probar SDXL Turbo para borradores de mejor calidad.
4. Solo después evaluar Chroma y FLUX Schnell.

## Lo que no conviene

- `-ngl 99` en Qwen3.6/Ornith 35B: ya se midió una caída aproximada de 22,26 a 8,12 tok/s.
- Bonsai 27B Q1_0: prefill aproximadamente cuatro veces peor y decode inferior; además, la calidad no fue demostrada.
- `draft-mtp` con los GGUF actuales: no contienen MTP.
- `qwen3-30b-a3b` como sustituto principal: obtuvo peor score en la matriz.
- `mlock` indiscriminado: puede presionar los 24 GB de RAM del LXC.
- Forzar la Vega como segunda GPU sin medir: comparte RAM y puede ralentizar el modelo principal.
- ComfyUI/ROCm en Polaris: ROCm no soporta oficialmente `gfx803`; el repositorio ya verificó que la ruta práctica es stable-diffusion.cpp + Vulkan.
- FLUX Dev: demasiado grande y lento para esta RX 580.
- Cambiar cuantización solo por el nombre `IQ`/`Q`: debe medirse con los graders, no con una expectativa teórica.
- Cambiar de modelo constantemente: los swaps cuestan aproximadamente 8–38 s y destruyen la ventaja del KV cache.

## Plan recomendado

1. Recortar prompts y herramientas de Hermes/OpenCode.
2. Medir sesiones persistentes y save/restore de slots.
3. Hacer A/B de `-fa` y `-ub`.
4. Comparar `--n-cpu-moe 30/32` con dos o tres reglas `--override-tensor`.
5. Actualizar llama.cpp en un entorno controlado y repetir `bench-agents` y `bench-spec`.
6. Probar Qwen3.5-9B, DeepSeek-Coder-V2 Lite y Gemma 4 12B solo como candidatos experimentales.
7. Probar SDXL Turbo; dejar FLUX/Chroma para una segunda fase.

La mayor mejora esperable, con menor riesgo, está en el prompt y la persistencia de sesiones; la mayor incertidumbre técnica está en `-fa`, `--override-tensor` y los nuevos modos de especulación Vulkan.