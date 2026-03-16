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
- `l10n_ar_percepciones` (campo `perception_ids` en partner)

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

### Exportación SICORE — Archivos TXT para ARCA

Este módulo incluye un wizard para generar los archivos TXT que se importan en SICORE/SIRE de ARCA para declarar retenciones de Ganancias.

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
| Código Impuesto ARCA | Código numérico ARCA del impuesto | `0787` (Ganancias) |

3. Clickear **"Generar Archivos"**
4. Descargar los 3 archivos generados:

| Archivo | Formato | Para qué |
|---------|---------|----------|
| `SICORE_generan_beneficio_YYYYMM.txt` | CSV (coma) | Importar en SICORE → "Comprobantes que Generan Beneficio" (Modelo 1) |
| `SICORE_perfeccionan_derecho_YYYYMM.txt` | CSV (coma) | Importar en SICORE → "Comprobantes que Perfeccionan Derecho a Beneficio" (Modelo 8) |
| `Retenciones_Ganancias_YYYYMM.pdf` | PDF | Resumen imprimible con detalle de retenciones y comprobantes |

#### Archivo 1: Generan Beneficio (Modelo 1) — 21 campos

Este archivo contiene **una línea por cada retención** practicada en el período.

| # | Campo | Valor que genera | Fuente Odoo |
|---|-------|------------------|-------------|
| 1 | Tipo Comprobante | `04` (Recibo A) | Fijo para retenciones |
| 2 | Punto de venta | Del nro de retención | `payment.withholding_number` |
| 3 | Nro Comprobante | Del nro de retención | `payment.withholding_number` |
| 4 | CUIT Emisor | CUIT de la empresa | `company.vat` |
| 5 | CUIT Vendedor | CUIT del proveedor retenido | `partner.vat` |
| 6 | Descripción | "RETENCION GANANCIAS" | Fijo |
| 7 | Importe IVA Facturado | Suma IVA facturas asociadas | `invoice.amount_tax` |
| 8 | Importe Neto | Suma neto facturas asociadas | `invoice.amount_untaxed` |
| 9 | IVA Computable | `0.00` | No aplica para Ganancias |
| 10 | Signo | `+` | Positivo para retenciones |
| 11 | Período DDJJ IVA | `YYYYMM` del período | `date_from` |
| 12 | Período Pago | `YYYYMM` del período | `date_from` |
| 13 | Medio Pago | `6` (Efectivo) | Fijo |
| 14 | Crédito Fiscal | `D` (Directa) | Fijo |
| 15 | Nro Certificado SIRE | vacío | No aplica |
| 16 | Nro Certificado SICORE | vacío | No aplica |
| 17 | Agente Ret IVA | `N` (No) | Ganancias, no IVA |
| 18 | Monto Retenido | Importe de la retención | `payment.amount` |
| 19 | Motivo no retención | `0` (Sin motivo) | Porque sí retuvimos |
| 20 | Fecha Comprobante | Fecha del pago | `payment.date` |
| 21 | Código Régimen | Código del régimen | `regimen_ganancias_id.codigo_de_regimen` |

**Ejemplo de línea generada:**
```
04,00001,00000001,30712345679,20123456783,RETENCION GANANCIAS,31500.00,150000.00,0.00,+,202603,202603,6,D,,,N,1656.60,0,15/03/2026,94
```

#### Archivo 2: Perfeccionan Derecho a Beneficio (Modelo 8) — 17 campos

Este archivo contiene **una línea por cada factura/NC** que originó la retención.

| # | Campo | Valor que genera | Fuente Odoo |
|---|-------|------------------|-------------|
| 1 | Tipo Comprobante | Código AFIP del documento | `l10n_latam_document_type_id.code` |
| 2 | Punto de venta | Del nro de factura | `invoice.name` |
| 3 | Nro Comprobante | Del nro de factura | `invoice.name` |
| 4 | Fecha Comprobante | Fecha de la factura | `invoice.invoice_date` |
| 5 | CUIT Cliente | CUIT del proveedor | `partner.vat` |
| 6 | Precio Total | Total de la factura | `invoice.amount_total` |
| 7-16 | Campos transporte/exportación | vacío | No aplica para servicios locales |
| 17 | Fecha Perfeccionamiento | Fecha de la factura | `invoice.invoice_date` |

**Ejemplo de línea generada:**
```
01,00001,00000020,10/03/2026,20123456783,181500.00,,,,,,,,,,10/03/2026
```

#### Mapeo tipo comprobante Odoo → SICORE

| Código AFIP | Tipo comprobante | Código SICORE |
|-------------|-----------------|---------------|
| 1 | Factura A | 01 |
| 6 | Factura B | 06 |
| 3 | Nota de Crédito A | 03 |
| 8 | Nota de Crédito B | 08 |
| 2 | Nota de Débito A | 02 |
| 7 | Nota de Débito B | 07 |
| 11/51 | Factura M | 51 |
| 201 | FCE A | 201 |
| 206 | FCE B | 206 |

#### Importación en ARCA

1. Ingresar a **ARCA → Mis Retenciones → SIRE/SICORE**
2. Seleccionar el período (ej: 03/2026)
3. Ir a **Importar datos**
4. Subir primero el archivo **Perfeccionan Derecho** (Modelo 8)
5. Subir luego el archivo **Generan Beneficio** (Modelo 1)
6. Validar y presentar la DDJJ

> **Nota**: el código de impuesto para Ganancias es `0787`. El código de régimen (campo 21) se toma del régimen seleccionado en el Grupo de Pago de Odoo (ej: `94` para locaciones de obra, `116` para profesionales liberales).

#### Casos especiales

| Caso | Comportamiento |
|------|---------------|
| Anticipo sin factura | Genera línea con tipo `04` (Recibo) y punto venta/nro `00000`/`00000000` |
| Nota de crédito | Precio total negativo en archivo Perfeccionan Derecho |
| Múltiples facturas en un pago | Una línea por factura en Perfeccionan Derecho, una línea de retención en Generan Beneficio |
| Proveedor sin CUIT | CUIT `00000000000` (el wizard advierte pero no bloquea) |

---

### Bugs OCA corregidos por este módulo

| Bug | Causa raíz | Fix |
|-----|-----------|-----|
| Diario incorrecto | `payment_method.id == payment_method.id` (siempre True) → toma primer diario | Campo `withholding_journal_id` por impuesto |
| Escala no se guarda | `vals['period_withholding_amount'] = amount` comentado (línea 217) → retención negativa para regímenes con escala | Override `get_withholding_vals()` recalcula y guarda post-super() |
| Monto no sujeto = $0 | OCA lee de `partner.default_regimen_ganancias_id` en vez de `payment_group.regimen_ganancias_id` | Override usa régimen del payment group |
