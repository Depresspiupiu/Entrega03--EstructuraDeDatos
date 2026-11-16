# FinSim — Coca-Cola y Nike

Aplicación de escritorio educativa para practicar la compraventa **simulada**
de acciones de Coca-Cola (`KO`) y Nike (`NKE`). Consulta sus precios diarios en
Yahoo Finance, muestra un gráfico de velas OHLC y calcula la rentabilidad de
las posiciones y de la cartera en USD.

## Funciones

- Consulta manual y concurrente de precios históricos de los últimos seis
  meses para `KO` y `NKE`.
- Gráfico de velas diarias con apertura, máximo, mínimo y cierre ajustados por
  Yahoo Finance.
- Compras y ventas simuladas con cantidad, fecha y comisión configurables. Las
  operaciones se registran al último cierre consultado; no se envían órdenes a
  un bróker.
- Rentabilidad no realizada por acción: valor de mercado menos costo de
  adquisición, incluidas las comisiones de compra.
- Rentabilidad acumulada de la cartera: efectivo más posiciones frente al
  capital inicial. El resumen por acción muestra solo KO y NKE; el total de la
  cartera conserva las operaciones históricas que existan en la base local.
- Historial local de operaciones.

Las cotizaciones requieren conexión a Internet y pueden tener retraso. La
aplicación es para fines educativos y no constituye asesoramiento financiero.

## Requisitos

- Windows 10/11 (también puede ejecutarse en macOS o Linux).
- Python 3.10 o superior.
- Conexión a Internet para consultar las cotizaciones.

## Instalación y ejecución

El proyecto no incluye un entorno virtual ni dependencias instaladas. Cada
persona debe instalarlas en su equipo antes de ejecutar la aplicación:

```powershell
python -m pip install -r requirements.txt
python main.py
```

Si solo se va a ejecutar la aplicación y no se van a crear ejecutables, basta
con instalar las dependencias de ejecución:

```powershell
python -m pip install -r requirements-runtime.txt
python main.py
```

La cartera y las operaciones se guardan en
`~/.finsim/simulation.sqlite3` (en Windows, dentro del perfil del usuario).
Los datos anteriores no se eliminan al actualizar la aplicación.

## Pruebas

```powershell
python -m unittest discover -s tests -v
```

## Crear ejecutables para Windows

Con las dependencias de desarrollo instaladas:

```powershell
python -m PyInstaller --noconfirm --clean FinSim.spec
```

El ejecutable se genera en `dist\FinSim.exe`. Para crear la distribución
portátil o dividida en archivos, consulta `FinSimPortable.spec` y
`build_finsim_parts.bat`.
