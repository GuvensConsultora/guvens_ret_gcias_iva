# Retenciones Ganancias/IVA — Mejoras UX

## Bloque 1: Introducción

### Qué hace Odoo nativamente (con módulos OCA)

Los módulos OCA (`account_withholding`, `account_withholding_automatic`, `l10n_ar_account_withholding_automatic`) implementan el cálculo automático de retenciones de Ganancias e IIBB al crear Grupos de Pago a proveedores. El cálculo se ejecuta en silencio: no deja rastro de qué evaluó, qué alícuotas usó, ni por qué una retención dio $0.

### Limitaciones

1. **Sin trazabilidad**: el cálculo es opaco — si una retención no se genera, no hay forma de saber por qué sin debuggear
2. **Bug en selección de diario**: OCA compara `payment_method.id == payment_method.id` (siempre `True`), tomando siempre el primer diario de efectivo
3. **Certificado genérico**: el reporte OCA no distingue entre IIBB y Ganancias, no muestra régimen, alícuota ni comprobantes que originan la retención
4. **Sin envío por email**: no hay integración para enviar Orden de Pago + Certificados como adjuntos

### Qué mejora este módulo

- **Diagnóstico completo en chatter**: cada cálculo de retención deja un mensaje detallado con todos los pasos, valores y un checklist de diagnóstico si la retención es $0
- **Diario por impuesto**: permite asignar un diario específico a cada impuesto de retención (corrige el bug OCA)
- **Certificado profesional**: template QWeb con 8 secciones, diferenciando IIBB vs Ganancias, mostrando régimen, alícuota y comprobantes
- **Email con adjuntos**: envío de Orden de Pago + Certificados de retención pre-generados en PDF

---

## Bloque 2: Funcionamiento para el usuario final

### Flujo de trabajo

#### 1. Calcular retenciones en un Grupo de Pago

1. Crear factura de proveedor y confirmarla
2. Ir a **Contabilidad → Proveedores → Grupos de Pago → Nuevo**
3. Seleccionar el proveedor y la/s factura/s a pagar
4. Clickear **"Calcular retenciones"**

**Resultado**: en el chatter del Grupo de Pago aparece un mensaje detallado con:

| Paso | Contenido |
|------|-----------|
| **Paso 1** | Datos del pago: partner, CUIT, monto a pagar, fecha |
| **Paso 2** | Impuestos de retención encontrados en el sistema |
| **Paso 3+** | Por cada impuesto: configuración, tipo, alícuota, base imponible, cálculo, resultado |

#### 2. Si la retención se calcula correctamente (> $0)

El sistema:
- Crea un pago de retención con el monto calculado
- Usa el diario específico configurado en el impuesto
- Al confirmar el grupo de pago, asigna número de retención desde la secuencia del diario

#### 3. Si la retención da $0 (diagnóstico)

El chatter muestra un **checklist de diagnóstico** con 5 verificaciones:

| Check | Qué verifica |
|-------|-------------|
| 1. Padrón ARBA | ¿Hay registros de retención cargados? ¿El CUIT del proveedor está en el padrón? |
| 2. Alícuota en partner | ¿El proveedor tiene percepción cargada con alícuota > 0? |
| 3. Retenciones automáticas | ¿Está habilitado el flag en la compañía? |
| 4. Diario de retenciones | ¿Existe un diario de efectivo con método de pago "Withholding"? |
| 5. Provincia del partner | ¿El proveedor es de Buenos Aires? (para IIBB ARBA) |

Cada check muestra ✓ (OK), ✗ (problema) o ⚠ (advertencia).

#### 4. Imprimir certificado de retención

Desde un Grupo de Pago confirmado con retenciones:
- Imprimir el certificado de retención

El certificado incluye 8 secciones:

1. **Encabezado**: título según tipo (IIBB / Ganancias), nro certificado, fecha
2. **Agente de retención**: razón social, CUIT, condición IVA, domicilio, nro IIBB o régimen
3. **Sujeto retenido**: nombre, CUIT, condición IVA, nro IIBB, domicilio
4. **Detalle de la retención**: impuesto, régimen, fecha, nro comprobante
5. **Liquidación**: base imponible, alícuota (o "Según escala" para Ganancias con escala), importe retenido
6. **Comprobantes que originan la retención**: tabla con fecha, comprobante, referencia, importe, saldo
7. **Observaciones** (si las hay)
8. **Firma**: línea de firma + leyenda legal

#### 5. Enviar por email

Desde el Grupo de Pago confirmado:
1. Clickear **"Enviar por email"**
2. Se abre el wizard con adjuntos pre-generados:
   - PDF de la Orden de Pago
   - PDF del Certificado de retención (uno por cada retención)
3. Enviar al proveedor

### Ejemplo concreto

**Proveedor**: ACME S.A. — CUIT 30-71234567-9 — Inscripto — Buenos Aires
**Factura**: $150.000 neto + IVA 21% = $181.500

| Retención | Base | Alícuota | Monto no sujeto | Cálculo | Resultado |
|-----------|------|----------|-----------------|---------|-----------|
| IIBB ARBA | $150.000 | 3% (del padrón) | — | 150.000 × 3% | **$4.500** |
| Ganancias (rég. 94) | $150.000 | 2% inscripto | $67.170 | (150.000 - 67.170) × 2% | **$1.656,60** |

**Pago neto al proveedor**: $181.500 - $4.500 - $1.656,60 = **$175.343,40**

---

## Bloque 3: Parametrización

### Paso 1: Configurar el impuesto de retención IIBB

1. Ir a **Contabilidad → Configuración → Impuestos**
2. Buscar el impuesto de retención IIBB (ej: `Ret IIBB ARBA A`)
3. Verificar que el **Tipo de impuesto** sea `Pagos a proveedores` (valor técnico: `supplier`)
4. En la sección de retenciones (scroll abajo), configurar:

| Campo | Valor | Descripción |
|-------|-------|-------------|
| Tipo de retención | `Alícuota en el partner` | Toma la alícuota del padrón/percepción del proveedor |
| Diario de retención | Diario de efectivo con método Withholding | Diario específico para esta retención |
| Tipo de cálculo | Según corresponda | Porcentaje fijo, sobre pago, etc. |

### Paso 2: Configurar el impuesto de retención Ganancias

1. Buscar el impuesto `Ret Ganancias A`
2. Tipo de impuesto: `Pagos a proveedores` (`supplier`)
3. Configurar:

| Campo | Valor |
|-------|-------|
| Tipo de retención | `Tabla de ganancias` |
| Diario de retención | Diario de efectivo con método Withholding |

### Paso 3: Configurar el proveedor

1. Ir a **Contactos** → abrir el proveedor
2. Pestaña **Contabilidad** → sección **Alícuotas**:
   - Agregar línea con el impuesto `Ret IIBB ARBA A` y la alícuota (ej: 3%)
   - O clickear **"Calcular percepciones"** si el padrón ARBA está importado
3. Pestaña **Fiscal Data**:

| Campo | Valor |
|-------|-------|
| CUIT | CUIT del proveedor |
| Responsabilidad AFIP | IVA Responsable Inscripto |
| Condición Ganancias | `Inscripto` |
| Régimen Ganancias | Seleccionar el régimen (ej: `94 - Locaciones de obra/servicios`) |

### Paso 4: Verificar la compañía

1. **Ajustes → Compañías → Mi compañía**
2. Verificar que tenga:
   - CUIT completo
   - Responsabilidad AFIP configurada
   - Domicilio completo (calle, ciudad, provincia, CP)
   - Nro de Ingresos Brutos (para certificados IIBB)
   - **Retenciones automáticas habilitadas** (flag en configuración contable)

### Paso 5: Verificar diarios de retención

1. **Contabilidad → Configuración → Diarios**
2. Verificar que exista al menos un diario tipo **Efectivo** con:
   - Método de pago **"Withholding"** habilitado en pagos salientes
   - Secuencia configurada (para numeración automática de certificados)

### Regímenes de Ganancias disponibles (RG 830)

| Código | Concepto | % Inscripto | % No Inscripto | Monto no sujeto |
|--------|----------|-------------|----------------|-----------------|
| 19 | Intereses entidades financieras | 3% | 10% | $0 |
| 21 | Otros intereses | 6% | 28% | $7.870 |
| 30 | Alquileres bienes muebles | 6% | 28% | $11.200 |
| 31 | Inmuebles urbanos | 6% | 28% | $11.200 |
| 32 | Inmuebles rurales | 6% | 28% | $11.200 |
| 35 | Regalías | 6% | 28% | $7.870 |
| 43 | Interés accionario cooperativas | 6% | 28% | $7.870 |
| 51 | Obligaciones de no hacer | 6% | 28% | $7.870 |
| 78 | Enajenación bienes muebles/cambio | 2% | 10% | $224.000 |
| 86 | Derechos de llave, marcas, patentes | 2% | 10% | $224.000 |
| 94 | Locaciones de obra/servicios | 2% | 28% | $67.170 |
| 95 | Transporte de carga | 0,25% | 28% | $67.170 |
| 99 | Factura M | 3% | 3% | $1.000 |
| 110 | Derechos de autor | Escala | 28% | $10.000 |
| 116 I | Honorarios directores SA | Escala | 28% | $67.170 |
| 116 II | Profesionales liberales | Escala | 28% | $16.830 |
| 124 | Corredor, viajante, despachante | Escala | 28% | $16.830 |
| 25 | Comisionistas, rematadores | Escala | 28% | $16.830 |

> **Nota**: los montos no sujetos a retención están congelados desde agosto 2019 (excepto régimen 119 de profesionales). Fuente: RG 830/2000, última actualización RG 5423/2023.

---

## Bloque 4: Referencia técnica

### Arquitectura

```
guvens_ret_gcias_iva/
├── __manifest__.py              # Metadata, depends OCA
├── __init__.py
├── models/
│   ├── __init__.py
│   ├── account_tax.py           # Fix diario + campo withholding_journal_id
│   ├── account_payment_group.py # Chatter diagnóstico + email con adjuntos
│   └── account_payment.py       # Numeración por diario + helpers template
├── wizard/
│   ├── __init__.py
│   ├── sicore_export_wizard.py      # Wizard exportación SICORE (2 TXT + PDF)
│   └── sicore_export_wizard_view.xml # Vista form + menú del wizard
├── views/
│   └── account_tax_view.xml     # Campo diario en form de impuesto
├── report/
│   ├── report_withholding_certificate.xml  # Certificado profesional QWeb
│   └── report_sicore_retenciones.xml       # Reporte PDF retenciones SICORE
└── security/
    └── ir.model.access.csv      # ACLs (hereda de módulos base)
```

### Modelos extendidos (herencia)

| Modelo | Archivo | Qué agrega |
|--------|---------|------------|
| `account.tax` | `account_tax.py` | Campo `withholding_journal_id` + override `create_payment_withholdings()` |
| `account.payment.group` | `account_payment_group.py` | Override `compute_withholdings()` con chatter + `action_payment_sent()` + `_generate_payment_attachments()` |
| `account.payment` | `account_payment.py` | Override `post()` para numeración + helpers: `is_iibb_withholding()`, `is_ganancias_withholding()`, `get_withholding_type_label()`, `get_withholding_alicuota()`, `get_withholding_invoices()`, `get_regimen_ganancias_label()` |

No se crean modelos nuevos — es 100% herencia sobre modelos existentes.

### Decisiones técnicas

#### Fix del diario OCA (account_tax.py)

**Problema**: el método OCA `create_payment_withholdings()` tiene un bug en la selección de diario:
```python
# OCA original (bug): compara el ID consigo mismo → siempre True
if payment_method.id == payment_method.id:
```

**Solución**: campo `withholding_journal_id` (Many2one → account.journal) por impuesto. Si está configurado, se usa directamente. Si no, se busca correctamente comparando IDs de métodos de pago.

#### Chatter diagnóstico (account_payment_group.py)

**Decisión**: loguear ANTES de ejecutar `super().compute_withholdings()` para capturar el estado pre-cálculo. El chatter usa HTML con estilos inline (no CSS classes) para portabilidad en emails.

**Patrón**: el override no modifica la lógica de cálculo — solo observa y loguea, luego delega en OCA.

#### Numeración por diario (account_payment.py)

**Decisión**: usar la secuencia del diario (`withholding_journal_id.sequence_id`) en vez de la secuencia del impuesto (`withholding_sequence_id`). Esto permite tener numeración separada por tipo de retención.

### Dependencias

```
account (Odoo core)
mail (Odoo core)
account_withholding (OCA)
account_withholding_automatic (OCA)
l10n_ar_report_withholding (OCA)
l10n_ar_report_payment_group (OCA)
```

Dependencias indirectas (instaladas por los OCA):
- `l10n_ar_account_withholding`
- `l10n_ar_account_withholding_automatic`

> **⚠ Requerido explícito — `l10n_ar_percepciones`**
> Este módulo **debe estar instalado** antes que `guvens_ret_gcias_iva`.
> Agrega el campo `partner_type` al modelo `account.tax` y la pestaña de alícuotas
> en el partner. Sin él, al abrir cualquier impuesto de retención aparece:
> `OwlError: "account.tax"."partner_type" field is undefined.`
> Instalarlo desde: **Ajustes → Aplicaciones → buscar `l10n_ar_percepciones`**.

### Datos de ejemplo para las dos tablas de Ganancias

#### Tabla 1 — Alícuotas y Montos (`afip.tabla_ganancias.alicuotasymontos`)

| Campo | Ej. 1 — Bienes | Ej. 2 — Servicios | Ej. 3 — Profesionales | Ej. 4 — Honorarios directores |
|---|---|---|---|---|
| **Código régimen** | `0078` | `0094` | `0116` | `0025` |
| **Anexo referencia** | II | II | II | II |
| **Concepto referencia** | Enajenación bienes muebles y cambio | Locaciones de obra y servicios | Profesiones liberales, oficios | Comisionistas, rematadores |
| **% Inscripto** | `2.00` | `2.00` | `-1` (escala) | `-1` (escala) |
| **% No Inscripto** | `10.00` | `28.00` | `28.00` | `28.00` |
| **Monto no sujeto** | `224000.00` | `67170.00` | `16830.00` | `16830.00` |

> Ejemplos 3 y 4 usan `-1` en `% Inscripto` → el sistema aplica la escala progresiva.

#### Tabla 2 — Escala progresiva (`afip.tabla_ganancias.escala`) — Marzo 2026

Solo la usan los ejemplos 3 y 4. Cargar estos 9 tramos en **Contabilidad → Configuración → Tabla Ganancias Escala**:

| Desde | Hasta | Fijo $ | % | Excedente de $ |
|---|---|---|---|---|
| `0` | `500007.52` | `0` | `5` | `0` |
| `500007.52` | `1000015.04` | `25000.38` | `9` | `500007.52` |
| `1000015.04` | `1500022.56` | `70001.05` | `12` | `1000015.04` |
| `1500022.56` | `2250033.85` | `130001.96` | `15` | `1500022.56` |
| `2250033.85` | `4500067.70` | `242503.65` | `19` | `2250033.85` |
| `4500067.70` | `6750101.55` | `670010.08` | `23` | `4500067.70` |
| `6750101.55` | `10125152.32` | `1187517.87` | `27` | `6750101.55` |
| `10125152.32` | `15187728.49` | `2098781.57` | `31` | `10125152.32` |
| `15187728.49` | `999999999` | `3668180.19` | `35` | `15187728.49` |

#### Verificación de cálculo esperado

| Ejemplo | Base bruta | Monto no sujeto | Base imponible | Cálculo | Retención esperada |
|---|---|---|---|---|---|
| Ej. 1 — Bienes ($300.000) | $300.000 | $224.000 | $76.000 | $76.000 × 2% | **$1.520,00** |
| Ej. 2 — Servicios ($150.000) | $150.000 | $67.170 | $82.830 | $82.830 × 2% | **$1.656,60** |
| Ej. 3 — Profesional ($500.000) | $500.000 | $16.830 | $483.170 | $483.170 × 5% (tramo 1) | **$24.158,50** |
| Ej. 4 — Director ($1.200.000) | $1.200.000 | $16.830 | $1.183.170 | $70.001,05 + ($183.155 × 12%) | **$91.979,65** |

---

### Verificación / Testing funcional

#### Pre-requisitos

- [ ] Módulo `guvens_ret_gcias_iva` instalado
- [ ] Módulos OCA de retenciones instalados (6 módulos)
- [ ] Compañía con CUIT, domicilio, responsabilidad AFIP, nro IIBB
- [ ] Proveedor de prueba con CUIT, condición IVA, provincia Buenos Aires

#### Configuración del proveedor test

| Campo | Valor |
|-------|-------|
| Nombre | PROVEEDOR TEST RETENCIONES |
| CUIT | CUIT válido |
| Responsabilidad AFIP | IVA Responsable Inscripto |
| Provincia | Buenos Aires |
| Alícuota IIBB | Ret IIBB ARBA A — 3% |
| Condición Ganancias | Inscripto |
| Régimen Ganancias | 94 — Locaciones de obra/servicios |

#### Configuración de impuestos

| Impuesto | Tipo retención | Diario |
|----------|---------------|--------|
| Ret IIBB ARBA A | Alícuota en el partner | Diario efectivo con Withholding |
| Ret Ganancias A | Tabla de ganancias | Diario efectivo con Withholding |

**Importante**: el tipo de impuesto debe ser `supplier` (Pagos a proveedores) para que aparezcan los campos de retención.

#### Test 1: Retención IIBB (partner_tax)

1. Crear factura proveedor: $150.000 + IVA = $181.500
2. Confirmar factura
3. Crear Grupo de Pago → seleccionar factura
4. Calcular retenciones
5. **Verificar chatter**: pasos 1-3 con datos del pago, impuestos, cálculo
6. **Verificar pago**: retención IIBB creada con monto = $150.000 × 3% = $4.500
7. **Verificar diario**: usa el diario configurado en el impuesto
8. Confirmar → verificar número de retención asignado

#### Test 2: Retención Ganancias porcentaje fijo (régimen 94)

**Proveedor**: régimen 94 — Locaciones de obra/servicios, 2% inscripto, monto no sujeto $67.170

1. Factura proveedor: $150.000 neto + IVA
2. Calcular retenciones
3. **Verificar chatter**: muestra régimen 94, % inscripto 2%, monto no sujeto $67.170
4. **Verificar cálculo**:
   - Base: $150.000 - $67.170 = $82.830
   - Retención: $82.830 × 2% = **$1.656,60**

#### Test 3: Retención Ganancias con escala (régimen 116 II)

**Proveedor**: régimen 116 II — Profesionales liberales, escala, monto no sujeto $16.830

1. Factura proveedor: $1.500.000 neto + IVA
2. Calcular retenciones
3. **Verificar cálculo** (escala marzo 2026):
   - Base: $1.500.000 - $16.830 = $1.483.170
   - Tramo: $1.000.015,04 a $1.500.022,56 → fijo $70.001,05 + 12%
   - Retención: $70.001,05 + ($1.483.170 - $1.000.015,04) × 12%
   - = $70.001,05 + $483.154,96 × 0,12
   - = $70.001,05 + $57.978,60
   - = **$127.979,65**

#### Test 4: Retención = $0 (diagnóstico)

1. Proveedor sin alícuota IIBB o con alícuota 0%
2. Calcular retenciones
3. **Verificar chatter**: checklist de 5 puntos con ✓/✗/⚠

#### Test 5: Certificado de retención

1. Desde grupo de pago confirmado con retención > $0
2. Imprimir certificado
3. Verificar 8 secciones: encabezado, agente, sujeto, detalle, liquidación, comprobantes, observaciones, firma
4. IIBB: dice "IIBB Buenos Aires", muestra nro IIBB
5. Ganancias: dice "Impuesto a las Ganancias", muestra régimen

#### Test 6: Envío por email

1. Desde grupo de pago confirmado
2. Clickear "Enviar por email"
3. Verificar adjuntos: PDF Orden de Pago + PDF Certificado/s
4. Enviar y verificar recepción

#### Test 7: Casos borde

- Múltiples retenciones (IIBB + Ganancias) en mismo grupo de pago
- NC de proveedor incluida → base imponible neta correcta
- Segundo pago al mismo proveedor en el período → acumulado previo descontado
- Cambiar diario del impuesto y recalcular → usa nuevo diario

### Escala de retención Ganancias RG 830 — Marzo 2026

Valores mensuales acumulados (fuente: ARCA, Art. 94 LIG, ene-jun 2026):

| Desde | Hasta | Fijo | % | Excedente |
|-------|-------|------|---|-----------|
| 0 | 500.007,52 | 0 | 5 | 0 |
| 500.007,52 | 1.000.015,04 | 25.000,38 | 9 | 500.007,52 |
| 1.000.015,04 | 1.500.022,56 | 70.001,05 | 12 | 1.000.015,04 |
| 1.500.022,56 | 2.250.033,85 | 130.001,96 | 15 | 1.500.022,56 |
| 2.250.033,85 | 4.500.067,70 | 242.503,65 | 19 | 2.250.033,85 |
| 4.500.067,70 | 6.750.101,55 | 670.010,08 | 23 | 4.500.067,70 |
| 6.750.101,55 | 10.125.152,32 | 1.187.517,87 | 27 | 6.750.101,55 |
| 10.125.152,32 | 15.187.728,49 | 2.098.781,57 | 31 | 10.125.152,32 |
| 15.187.728,49 | en adelante | 3.668.180,19 | 35 | 15.187.728,49 |

> **Nota**: la escala varía por mes (enero = 1/12 del anual, febrero = 2/12, etc.). Estos valores son para marzo. Actualizar mensualmente en Odoo: Contabilidad → Configuración → Tabla Ganancias Escala.

### Exportación SICORE — Archivo TXT para ARCA

Este módulo incluye un wizard para generar el archivo TXT que se importa en SICORE de ARCA usando el formato **"Estándar Retenciones Versión 3.0"** (posición fija, 198 caracteres por registro).

#### Acceso

**Contabilidad → Informes → Exportar SICORE Ganancias**

#### Paso a paso

1. Abrir el wizard desde el menú
2. Configurar los filtros:

| Campo | Descripción | Ejemplo |
|-------|-------------|---------|
| Desde | Primer día del período a declarar | 01/03/2026 |
| Hasta | Último día del período | 31/03/2026 |
| Impuesto Ret. Ganancias | Impuesto tipo `Tabla de ganancias` configurado | Ret Ganancias A |
| Código Impuesto ARCA | Código numérico ARCA (3 dígitos) | `217` (Ganancias general) |

3. Clickear **"Generar Archivos"**
4. Descargar los 2 archivos generados:

| Archivo | Formato | Para qué |
|---------|---------|----------|
| `SICORE_retenciones_YYYYMM.txt` | Posición fija 198 chars/línea | Importar en SICORE → "Estándar Retenciones Versión 3.0" |
| `Retenciones_Ganancias_YYYYMM.pdf` | PDF | Resumen imprimible |

#### Diseño de registro — 21 campos, 198 caracteres por línea

Un registro por factura asociada al pago. Si un pago tiene 2 facturas, genera 2 registros prorrateando base e importe de retención proporcionalmente.

| # | Campo | Pos | Long | Tipo | Fuente Odoo |
|---|-------|-----|------|------|-------------|
| 1 | Código comprobante | 1 | 2 | Num | `l10n_latam_document_type_id.code` → tabla |
| 2 | Fecha emisión comprobante | 3 | 10 | Alfa | `invoice.invoice_date` DD/MM/AAAA |
| 3 | Número comprobante | 13 | 16 | Alfa | `invoice.name` ljust(16) |
| 4 | Importe comprobante | 29 | 16 | Num | `invoice.amount_total` → 13ent,2dec |
| 5 | Código impuesto | 45 | 3 | Num | Campo wizard `cod_impuesto` zfill(3) |
| 6 | Código régimen | 48 | 4 | Num | `regimen_ganancias_id.codigo_de_regimen` zfill(4) |
| 7 | Código operación | 52 | 1 | Num | `1` fijo (retención) |
| 8 | Base de cálculo | 53 | 14 | Num | `payment.withholding_base_amount` → 11ent,2dec |
| 9 | Fecha emisión retención | 67 | 10 | Alfa | `payment.date` DD/MM/AAAA |
| 10 | Código condición | 77 | 2 | Num | `partner.imp_ganancias_padron` → `AC`=01, `NI`=02, `EX`=04 |
| 11 | Ret. sujeto suspendido | 79 | 1 | Num | `0` fijo |
| 12 | Importe retención | 80 | 14 | Num | `payment.amount` prorrateado → 11ent,2dec |
| 13 | Porcentaje exclusión | 94 | 6 | Num | `000,00` fijo |
| 14 | Fecha boletín oficial | 100 | 10 | Alfa | 10 espacios |
| 15 | Tipo doc retenido | 110 | 2 | Num | `80` fijo (CUIT) |
| 16 | Nro. doc retenido | 112 | 20 | Alfa | `partner.vat` 11 dig + 9 espacios |
| 17 | Nro. certificado original | 132 | 14 | Num | `00000000000000` fijo |
| 18 | Denominación ordenante | 146 | 30 | Alfa | `company.name` ljust(30) |
| 19 | Acrecentamiento | 176 | 1 | Num | `0` fijo |
| 20 | CUIT país exterior | 177 | 11 | Num | `00000000000` fijo |
| 21 | CUIT ordenante/pagador | 188 | 11 | Num | `company.vat` sin guiones |

> **Formato numérico**: separador decimal = coma (`,`). Ej: `00000001500,75`
> **Campos alfanuméricos**: alineados a izquierda, relleno con espacios a la derecha.
> **Campos numéricos**: alineados a derecha, relleno con ceros a la izquierda.

#### Códigos de impuesto ARCA (campo 5)

| Código | Descripción |
|--------|-------------|
| `217` | Impuesto a las Ganancias (general) — **default** |
| `787` | Ganancias — Relación de Dependencia |

#### Mapeo tipo comprobante Odoo → SICORE (campo 1)

| Tipo en Odoo | Código SICORE |
|--------------|---------------|
| Factura A/B/M/FCE | `01` |
| Nota de Débito | `04` |
| Nota de Crédito | `03` |
| Anticipo sin factura | `02` (Recibo) |

#### Importación en SICORE

1. Abrir SICORE
2. Ir a **Archivo → Importar datos**
3. Seleccionar formato: **"Estándar Retenciones Versión 3.0"**
4. Seleccionar el archivo `SICORE_retenciones_YYYYMM.txt`
5. Validar — si acepta, presentar la DDJJ

#### Casos especiales

| Caso | Comportamiento |
|------|---------------|
| Anticipo sin factura | 1 registro con tipo `02` (Recibo), base e importe del pago completos |
| Nota de crédito | Tipo comprobante `03`, importe prorrateado |
| Múltiples facturas en un pago | 1 registro por factura, base e importe prorrateados por proporción |
| Proveedor sin CUIT | CUIT `00000000000` en campo 16 |

---

### Bugs OCA corregidos por este módulo

| Bug | Causa raíz | Fix |
|-----|-----------|-----|
| Diario incorrecto | `payment_method.id == payment_method.id` (siempre True) → toma primer diario | Campo `withholding_journal_id` por impuesto |
| Escala no se guarda | `vals['period_withholding_amount'] = amount` comentado (línea 217) → retención negativa para regímenes con escala | Override `get_withholding_vals()` recalcula y guarda post-super() |
| Monto no sujeto = $0 | OCA lee de `partner.default_regimen_ganancias_id` en vez de `payment_group.regimen_ganancias_id` | Override usa régimen del payment group |
