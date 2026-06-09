# Evidencia 2 - Procesa en paralelo

## Archivos principales

- `DatosYGraficas.xlsx`: datos, resumen y graficas de speed-up/eficiencia.
- `index.html`: interfaz web.
- `htmlcontroller.rkt`: servidor local para la interfaz.
- `verificacion-benchmarks.rkt`: verificador reproducible de tiempos, equivalencia y salidas.
- `benchmark-resultados.csv`: resultados generados por el verificador.
- `salidas/`: imagenes procesadas por cada filtro.
- `Evidencia_2_Procesa_en_Paralelo_entrega.zip`: paquete limpio para subir.

## Reproducir

```bash
raco make mainbase.rkt htmlcontroller.rkt filtrossecuenciales.rkt filtrosrecursivos.rkt filtrosparalelos.rkt verificacion-benchmarks.rkt
racket verificacion-benchmarks.rkt
python3 generar-artefactos.py
```

Para regenerar el PDF desde el HTML en macOS con Google Chrome instalado:

```bash
"/Applications/Google Chrome.app/Contents/MacOS/Google Chrome" \
  --headless --disable-gpu --no-sandbox --no-pdf-header-footer \
  --print-to-pdf="$PWD/Reporte_Evidencia_2_Procesa_en_Paralelo.pdf" \
  "file://$PWD/Reporte_Evidencia_2_Procesa_en_Paralelo.html"
```

Para ejecutar pruebas unitarias formales:

```bash
racket pruebas-unitarias.rkt
```

Para usar la interfaz:

```bash
racket htmlcontroller.rkt
```

Abrir `http://127.0.0.1:8080`.
