# FinSim - Sistema de Seguimiento y Simulación de Portafolio de Inversión

**FinSim** es una aplicación de escritorio educativa desarrollada en Python (PySide6) que permite monitorear, simular y evaluar el desempeño de un portafolio de inversión compuesto por activos de **renta variable** (acciones) y **renta fija** (CDT, bonos y TES).

La plataforma permite comparar acciones analizando precios históricos desde Yahoo Finance, registrar compras/ventas sin ejecutar órdenes reales y calcular métricas clave como la rentabilidad acumulada y la **Rentabilidad Efectiva Anual (E.A.)**.

## 📸 Vista Previa de la Aplicación

| Módulo Principal / Análisis | Resumen de Portafolio y Operaciones | 
| ----- | ----- | 
|  |  | 

*(Nota: Reemplaza los enlaces anteriores con las capturas de pantalla reales guardadas en la carpeta `docs/` o la raíz de tu repositorio).*

## 🛠️ Requisitos del Sistema

* **Sistema Operativo:** Windows 10/11 (Recomendado) o macOS/Linux.
* **Python:** Versión 3.10 o superior.
* **Conexión a Internet:** Requerida para consultar cotizaciones en tiempo real mediante `yfinance`.

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
pyinstaller --noconfirm --clean --onefile --windowed --name FinSim main.py
```

El ejecutable resultante se guardará en la carpeta `dist\FinSim.exe`.

## ⚙️ ¿Cómo Funciona el Código? (Arquitectura Interna)

El código sigue un diseño modular orientado a objetos dividiendo la lógica de negocio, la base de datos y la interfaz de usuario:

### 1. Punto de Entrada (`main.py`)

Inicializa la ruta de la base de datos SQLite en el directorio local del usuario (`~/.finsim/simulation.sqlite3`) y arranca el ciclo de vida de la aplicación llamando a `create_application()`.

### 2. Capas del Sistema (`finance_app/`)

* **Capa UI (`finance_app/ui`):** Desarrollada en PySide6. Contiene los formularios para ingresar operaciones, selectores de activos, vistas tabulares para el resumen de saldos y gráficos interactivos de rendimiento.

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