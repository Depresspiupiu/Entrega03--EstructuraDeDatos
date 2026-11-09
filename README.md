# FinSim

Aplicacion de escritorio educativa para comparar acciones con datos de Yahoo
Finance y practicar compras y ventas sin enviar ordenes reales.

## Requisitos

- Windows
- Python 3.10 o posterior
- Dependencias de `requirements.txt`
- Conexion a internet para consultar cotizaciones

## Ejecutar desde Python

```powershell
python -m pip install -r requirements.txt
python main.py
```

La aplicacion consulta seis meses de precios diarios ajustados. Calcula el
cambio de un dia, un mes (21 sesiones) y tres meses (63 sesiones). Su regla
orientativa pondera el rendimiento mensual al 60 % y el trimestral al 40 %:

- **COMPRA** si el puntaje ponderado es igual o superior a +3 %.
- **VENTA** si es igual o inferior a -3 %.
- **MANTENER** en los demas casos.

La tabla ordena las acciones por puntaje. La recomendacion es una regla
historica sencilla, no una prediccion ni asesoramiento financiero.

## Simulacion

La cuenta empieza con 10,000 USD y 0 COP. En **Configurar saldo inicial** se
puede establecer el capital simulado de una moneda antes de registrar
operaciones en ella. Los saldos COP y USD se mantienen separados; no se hace
conversion de moneda.

El formulario permite registrar compras y ventas de acciones, certificados de
deposito a termino (CDT), bonos y titulos de deuda publica (TES). Cada registro
incluye fecha de operacion, nombre o simbolo del instrumento, cantidad, valor
unitario, comision y moneda. Las acciones usan USD por defecto; CDT, bonos y TES
usan COP por defecto, pero la moneda se puede cambiar. El valor de transaccion
es cantidad por valor unitario. En compras, valor y comision se descuentan del
saldo; en ventas, la comision se resta del ingreso. No se permite vender mas
unidades de las registradas ni comprar por encima del saldo disponible.

Las operaciones se guardan en una base de datos local en
`%USERPROFILE%\\.finsim\\simulation.sqlite3`. Las bases existentes se actualizan
automaticamente y sus operaciones previas se conservan. Los valores de CDT,
bonos y TES se ingresan manualmente; Yahoo Finance se usa para consultar las
cotizaciones de acciones. No se conectan cuentas de corretaje ni se transmiten
ordenes reales.

## Crear un ejecutable de Windows

Desde la carpeta del proyecto, instala las dependencias y ejecuta:

```powershell
pyinstaller --noconfirm --clean --onefile --windowed --name FinSim main.py
```

El ejecutable se crea en `dist\\FinSim.exe`. El equipo que lo ejecute necesita
acceso a internet para descargar cotizaciones. La base de datos de simulacion
permanece en el perfil local del usuario.

## Pruebas

```powershell
python -m unittest discover -s tests -v
```
