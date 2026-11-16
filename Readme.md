# FinSim - Sistema de Seguimiento y Simulación de Portafolio de Inversión

**FinSim** es una aplicación de escritorio educativa desarrollada en Python (PySide6) que permite monitorear, simular y evaluar el desempeño de un portafolio de inversión compuesto por activos de **renta variable** (acciones) y **renta fija** (CDT, bonos y TES).

La plataforma permite comparar acciones analizando precios históricos desde Yahoo Finance, registrar compras/ventas sin ejecutar órdenes reales y calcular métricas clave como la rentabilidad acumulada y la **Rentabilidad Efectiva Anual (E.A.)**. Incluye una simulación histórica diaria de 2023 para empresas cotizadas en NASDAQ y NYSE, con gráficos lineales y de velas.

## 📸 Vista Previa de la Aplicación

| Módulo Principal / Análisis | Resumen de Portafolio y Operaciones | 
| ----- | ----- | 
|  |  | 

*(Nota: Reemplaza los enlaces anteriores con las capturas de pantalla reales guardadas en la carpeta `docs/` o la raíz de tu repositorio).*

## 🛠️ Requisitos del Sistema

* **Sistema Operativo:** Windows 10/11 (Recomendado) o macOS/Linux.
* **Python:** Versión 3.10 o superior.
* **Conexión a Internet:** Requerida para consultar cotizaciones históricas mediante `yfinance`, incluso al ejecutar el `.exe`.

### Dependencias Principales (`requirements.txt`)

* **Interfaz Gráfica:** `PySide6`
* **Mercados y Análisis de Datos:** `yfinance`, `pandas`, `numpy`, `scipy`, `statsmodels`, `scikit-learn`
* **Análisis de Portafolio e Indicadores:** `ta`, `quantstats`, `backtesting`
* **Visualización:** `matplotlib`, `plotly`
* **Persistencia y Validación:** `SQLAlchemy`, `pydantic`, `python-dotenv`
* **Empaquetado y Pruebas:** `pyinstaller`, `pytest`

## 🚀 Instalación y Ejecución

### 1. Clonar el repositorio e instalar dependencias

```powershell
python -m pip install --upgrade pip
python -m pip install -r requirements.txt
```

### 2. Ejecutar la aplicación

```powershell
python main.py
```

### 3. Crear ejecutable (.exe) para Windows

```powershell
pyinstaller --noconfirm --clean --onefile --windowed --name FinSim --collect-all yfinance --collect-all curl_cffi --collect-data matplotlib main.py
```

El ejecutable resultante se guardará en la carpeta `dist\FinSim.exe`.

## Simulación histórica 2023

En la pestaña **Simulación histórica 2023** se puede elegir NASDAQ o NYSE, seleccionar empresas para las tenencias iniciales, fijar un capital inicial (USD 100.000 por defecto) y elegir una fecha de inicio. Al iniciar, cada empresa seleccionada recibe entre 0 y 50 acciones aleatorias y el saldo restante queda en efectivo. Los precios se descargan para todas las empresas del mercado elegido, así que también puedes comprar cualquiera de las otras empresas del mismo mercado aunque no tenga tenencias iniciales. Puedes escoger una empresa y comprar o vender entre 1 y 50 acciones; las compras validan el saldo y las ventas las acciones disponibles.

El mercado avanza automáticamente según las cotizaciones históricas de 2023; se puede pausar, reanudar, ajustar el intervalo o avanzar manualmente. El gráfico lineal o de velas muestra la empresa seleccionada y marca las compras y ventas. Las sesiones pueden guardarse con nombre y cargarse después; el archivo local SQLite conserva también los datos históricos de la sesión, que puede reanudarse sin volver a descargarlos.

Empresas incluidas: Apple (AAPL), PepsiCo (PEP) y Nvidia (NVDA) en NASDAQ; Nike (NKE), Coca-Cola (KO) y TSMC (TSM, ADR) en NYSE. Se requiere Internet al iniciar una simulación nueva para consultar Yahoo Finance. La simulación es educativa y no representa órdenes ni recomendaciones de inversión.

## ⚙️ ¿Cómo Funciona el Código? (Arquitectura Interna)

El código sigue un diseño modular orientado a objetos dividiendo la lógica de negocio, la base de datos y la interfaz de usuario:

### 1. Punto de Entrada (`main.py`)

Inicializa la ruta de la base de datos SQLite en el directorio local del usuario (`~/.finsim/simulation.sqlite3`) y arranca el ciclo de vida de la aplicación llamando a `create_application()`.

### 2. Capas del Sistema (`finance_app/`)

* **Capa UI (`finance_app/ui`):** Desarrollada en PySide6. Contiene los formularios para ingresar operaciones, selectores de activos, vistas tabulares para el resumen de saldos y gráficos interactivos de rendimiento.

* **Simulación histórica (`finance_app/historical_simulation`):** Descarga y alinea cotizaciones diarias ajustadas de 2023, asigna tenencias iniciales aleatorias, procesa operaciones y avanza la trayectoria de precios según el historial con una pequeña perturbación aleatoria.
* **Sesiones históricas (`finance_app/historical_sessions`):** Guarda y recupera sesiones nombradas en la misma base de datos SQLite del usuario, incluidos precios, tenencias, operaciones y progreso.

* **Capa de Negocio y Cálculo (`finance_app/models` / `services`):**

  * **Scoring de Acciones:** Consulta 6 meses de precios diarios ajustados de Yahoo Finance. Calcula el retorno diario, mensual (21 sesiones) y trimestral (63 sesiones). Asigna un puntaje ponderado:
    
    $$
    \text{Puntaje} = (0.6 \times \text{Rendimiento Mensual}) + (0.4 \times \text{Rendimiento Trimestral})
    $$

    * **COMPRA:** Puntaje $\ge +3\%$
    * **VENTA:** Puntaje $\le -3\%$
    * **MANTENER:** Entre $-3\%$ y $+3\%$

  * **Renta Fija (CDT, Bonos, TES):** Si no hay una valoración manual configurada, se estima capitalizando el costo promedio hasta la fecha de vencimiento dada su Tasa Efectiva Anual (E.A.). Los intereses cobrados permanecen en caja para evitar doble contabilización.

  * **Métricas de Rendimiento:**
    * **Rentabilidad Acumulada:** Compara la valoración total actual (efectivo + activos) contra el saldo inicial configurado por moneda.
    * **Rentabilidad Efectiva Anual (E.A.):** Se anualiza a partir del flujo de caja generado desde la fecha de la primera operación.

* **Capa de Persistencia:** Utiliza SQLAlchemy / SQLite local para mantener el historial de transacciones, dividendos, pagos de capital, comisiones y saldos multi-moneda (**USD** y **COP**) de forma independiente (sin conversión automática de divisa).

## 🧪 Ejecución de Pruebas Unitarias

Para verificar el correcto funcionamiento de los algoritmos financieros y las reglas de negocio, ejecuta:

```powershell
python -m unittest discover -s tests -v
```
