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
├── views/
│   └── account_tax_view.xml     # Campo diario en form de impuesto
├── report/
│   └── report_withholding_certificate.xml  # Certificado profesional QWeb
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

#### Test 2: Retención Ganancias (tabla_ganancias)

1. Misma factura de $150.000 neto
2. Calcular retenciones
3. **Verificar chatter**: muestra régimen 94, % inscripto 2%, monto no sujeto $67.170
4. **Verificar pago**: retención = (150.000 - 67.170) × 2% = $1.656,60

#### Test 3: Retención = $0 (diagnóstico)

1. Proveedor sin alícuota IIBB o con alícuota 0%
2. Calcular retenciones
3. **Verificar chatter**: checklist de 5 puntos con ✓/✗/⚠

#### Test 4: Certificado de retención

1. Desde grupo de pago confirmado con retención > $0
2. Imprimir certificado
3. Verificar 8 secciones: encabezado, agente, sujeto, detalle, liquidación, comprobantes, observaciones, firma
4. IIBB: dice "IIBB Buenos Aires", muestra nro IIBB
5. Ganancias: dice "Impuesto a las Ganancias", muestra régimen

#### Test 5: Envío por email

1. Desde grupo de pago confirmado
2. Clickear "Enviar por email"
3. Verificar adjuntos: PDF Orden de Pago + PDF Certificado/s
4. Enviar y verificar recepción

#### Test 6: Casos borde

- Múltiples retenciones (IIBB + Ganancias) en mismo grupo de pago
- NC de proveedor incluida → base imponible neta correcta
- Segundo pago al mismo proveedor en el período → acumulado previo descontado
- Cambiar diario del impuesto y recalcular → usa nuevo diario
