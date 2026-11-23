// ===========================================
// PAGOS.JS - Modal de pago, historial y recaudación
// Depende de helpers de app.js: apiFetch, apiFetchFile, esc, formatCurrency, showAlert, dashboardContent
// ===========================================

// ---------- Utilidades ----------

function luhnValido(numero) {
    let suma = 0, doble = false;
    for (let i = numero.length - 1; i >= 0; i--) {
        let d = parseInt(numero[i], 10);
        if (doble) { d *= 2; if (d > 9) d -= 9; }
        suma += d;
        doble = !doble;
    }
    return numero.length >= 13 && suma % 10 === 0;
}

function marcaTarjeta(numero) {
    if (/^4/.test(numero)) return 'VISA';
    if (/^(5[1-5]|22[2-9]|2[3-6]|27[01]|2720)/.test(numero)) return 'MASTERCARD';
    if (/^3[47]/.test(numero)) return 'AMEX';
    if (/^(36|38|30[0-5])/.test(numero)) return 'DINERS';
    return '';
}

function formatearFecha(iso) {
    if (!iso) return '—';
    return new Date(iso).toLocaleString('es-PE', { day: '2-digit', month: '2-digit', year: 'numeric', hour: '2-digit', minute: '2-digit' });
}

const ETIQUETA_METODO = { TARJETA: 'Tarjeta', YAPE: 'Yape', PLIN: 'Plin' };

// ---------- Modal de pago ----------
/**
 * Abre el modal de pago.
 * opts: { titulo, concepto, referencia, monto (string "177.12"), desglose: [{label, value}], endpoint, onClose(pagoOk|null) }
 */
function openPaymentModal(opts) {
    const root = document.getElementById('modal-root');
    const previoFoco = document.activeElement;
    const estado = { metodo: 'TARJETA', procesando: false, pago: null, valores: {} };
    const monto = String(opts.monto);

    const desgloseHTML = (opts.desglose || []).map(d => `<div class="row"><span>${esc(d.label)}</span><b>${esc(d.value)}</b></div>`).join('');

    root.innerHTML = `
      <div class="modal-backdrop" id="pay-backdrop">
        <div class="modal" role="dialog" aria-modal="true" aria-labelledby="pay-title">
          <button type="button" class="modal-close" id="pay-close" aria-label="Cerrar">&times;</button>
          <div class="pay-head">
            <span class="pay-lock"><i class="fas fa-lock"></i> Pago seguro · entorno de demostración</span>
            <h2 id="pay-title">${esc(opts.titulo || 'Realizar pago')}</h2>
          </div>
          <div class="pay-summary">
            <div class="row"><span>Concepto</span><b>${esc(opts.concepto)}</b></div>
            ${opts.referencia ? `<div class="row"><span>Referencia</span><b>${esc(opts.referencia)}</b></div>` : ''}
            ${desgloseHTML}
            <div class="total"><span>Total a pagar</span><strong>S/ ${formatCurrency(monto)}</strong></div>
          </div>
          <div class="pay-body" id="pay-body"></div>
        </div>
      </div>`;
    document.body.classList.add('modal-open');

    const backdrop = document.getElementById('pay-backdrop');
    const body = document.getElementById('pay-body');

    function cerrar() {
        if (estado.procesando) return;
        document.removeEventListener('keydown', onKey);
        root.innerHTML = '';
        document.body.classList.remove('modal-open');
        if (previoFoco && previoFoco.focus) previoFoco.focus();
        if (typeof opts.onClose === 'function') opts.onClose(estado.pago);
    }
    function onKey(e) { if (e.key === 'Escape') cerrar(); }
    document.addEventListener('keydown', onKey);
    document.getElementById('pay-close').addEventListener('click', cerrar);
    backdrop.addEventListener('mousedown', (e) => { if (e.target === backdrop) cerrar(); });

    // ----- Formulario -----
    function renderFormulario(mensajeError = '') {
        const t = estado.metodo === 'TARJETA';
        body.innerHTML = `
          <form id="pay-form" novalidate>
            <fieldset style="border:0;padding:0;margin:0">
              <legend class="sr-only" style="position:absolute;left:-9999px">Medio de pago</legend>
              <div class="pay-methods">
                ${[['TARJETA', 'fa-credit-card', 'Tarjeta'], ['YAPE', 'fa-mobile-screen-button', 'Yape'], ['PLIN', 'fa-mobile-screen', 'Plin']].map(([v, ic, n]) => `
                  <label class="pay-method"><input type="radio" name="pm" value="${v}" ${estado.metodo === v ? 'checked' : ''}>
                  <span><i class="fas ${ic}"></i>${n}</span></label>`).join('')}
              </div>
            </fieldset>

            ${mensajeError ? `<div class="pay-alert" role="alert"><i class="fas fa-circle-exclamation"></i> ${esc(mensajeError)}</div>` : ''}

            ${t ? `
              <div class="pay-hint">Demo: usa <b>4111 1111 1111 1111</b> (aprobada) o <b>4000 0000 0000 0002</b> (rechazada).
                <button type="button" id="pay-fill">Autocompletar</button></div>
              <div class="field" data-f="numero"><label for="pay-numero">Número de tarjeta</label>
                <div class="input-wrap"><input class="form-input" id="pay-numero" inputmode="numeric" autocomplete="cc-number" maxlength="23" placeholder="0000 0000 0000 0000">
                <span class="field-badge" id="pay-marca" hidden></span></div><div class="field-error">Número de tarjeta inválido.</div></div>
              <div class="field" data-f="titular"><label for="pay-titular">Nombre del titular</label>
                <input class="form-input" id="pay-titular" autocomplete="cc-name" maxlength="60" placeholder="Como aparece en la tarjeta" style="padding-right:.85rem">
                <div class="field-error">Ingrese el nombre del titular.</div></div>
              <div class="field-row">
                <div class="field" data-f="venc"><label for="pay-venc">Vencimiento</label>
                  <input class="form-input" id="pay-venc" inputmode="numeric" autocomplete="cc-exp" maxlength="5" placeholder="MM/AA" style="padding-right:.85rem">
                  <div class="field-error">Fecha inválida o vencida.</div></div>
                <div class="field" data-f="cvv"><label for="pay-cvv">CVV</label>
                  <input class="form-input" id="pay-cvv" type="password" inputmode="numeric" autocomplete="cc-csc" maxlength="4" placeholder="•••" style="padding-right:.85rem">
                  <div class="field-error">CVV inválido.</div></div>
              </div>` : `
              <div class="pay-hint">Demo: cualquier celular de 9 dígitos y un código de 6 dígitos (el <b>000000</b> se rechaza).</div>
              <div class="field" data-f="celular"><label for="pay-celular">Celular afiliado a ${ETIQUETA_METODO[estado.metodo]}</label>
                <input class="form-input" id="pay-celular" inputmode="numeric" maxlength="9" autocomplete="tel-national" placeholder="9XXXXXXXX" style="padding-right:.85rem">
                <div class="field-error">Debe tener 9 dígitos y empezar con 9.</div></div>
              <div class="field" data-f="codigo"><label for="pay-codigo">Código de aprobación (6 dígitos)</label>
                <input class="form-input" id="pay-codigo" inputmode="numeric" maxlength="6" autocomplete="one-time-code" placeholder="000000" style="padding-right:.85rem">
                <div class="field-error">Ingrese los 6 dígitos del código.</div></div>`}

            <button type="submit" class="btn btn-exito btn-block" id="pay-submit" style="font-size:1.05rem;padding:.9rem">
              <i class="fas fa-lock"></i> Pagar S/ ${formatCurrency(monto)}</button>
            <p class="pay-secure"><i class="fas fa-shield-halved"></i> Los datos de tu tarjeta no se guardan en el sistema.</p>
          </form>`;
        conectarFormulario();
    }

    function conectarFormulario() {
        body.querySelectorAll('input[name="pm"]').forEach(r => r.addEventListener('change', () => { estado.metodo = r.value; renderFormulario(); }));
        // Al corregir un campo se quita el aviso de error
        body.querySelectorAll('.form-input').forEach(i => i.addEventListener('input', () => i.closest('.field')?.classList.remove('invalid')));
        const soloDigitos = (el, max) => el.addEventListener('input', () => { el.value = el.value.replace(/\D/g, '').slice(0, max); });

        if (estado.metodo === 'TARJETA') {
            const num = body.querySelector('#pay-numero'), venc = body.querySelector('#pay-venc'), cvv = body.querySelector('#pay-cvv');
            num.addEventListener('input', () => {
                const d = num.value.replace(/\D/g, '').slice(0, 19);
                num.value = d.replace(/(.{4})/g, '$1 ').trim();
                const m = marcaTarjeta(d), badge = body.querySelector('#pay-marca');
                badge.hidden = !m; badge.textContent = m;
            });
            venc.addEventListener('input', () => {
                let d = venc.value.replace(/\D/g, '').slice(0, 4);
                if (d.length >= 3) d = d.slice(0, 2) + '/' + d.slice(2);
                venc.value = d;
            });
            soloDigitos(cvv, 4);
            body.querySelector('#pay-fill').addEventListener('click', () => {
                num.value = '4111 1111 1111 1111'; num.dispatchEvent(new Event('input'));
                body.querySelector('#pay-titular').value = 'JUAN PRUEBA'; venc.value = '12/35'; cvv.value = '123';
            });
        } else {
            soloDigitos(body.querySelector('#pay-celular'), 9);
            soloDigitos(body.querySelector('#pay-codigo'), 6);
        }
        // Conserva lo ya escrito si hubo un error (no se restauran CVV ni código de aprobación)
        Object.entries(estado.valores).forEach(([id, valor]) => {
            const el = body.querySelector('#' + id);
            if (el && valor) { el.value = valor; el.dispatchEvent(new Event('input')); }
        });
        body.querySelector('#pay-form').addEventListener('submit', enviar);
        const primerVacio = [...body.querySelectorAll('.form-input')].find(i => !i.value);
        if (primerVacio) primerVacio.focus();
    }

    const marcar = (campo, ok) => { const f = body.querySelector(`[data-f="${campo}"]`); if (f) f.classList.toggle('invalid', !ok); return ok; };

    function validar() {
        if (estado.metodo === 'TARJETA') {
            const numero = body.querySelector('#pay-numero').value.replace(/\D/g, '');
            const titular = body.querySelector('#pay-titular').value.trim();
            const venc = body.querySelector('#pay-venc').value;
            const cvv = body.querySelector('#pay-cvv').value;
            const m = venc.match(/^(0[1-9]|1[0-2])\/(\d{2})$/);
            const hoy = new Date();
            const vigente = m && (2000 + +m[2] > hoy.getFullYear() || (2000 + +m[2] === hoy.getFullYear() && +m[1] >= hoy.getMonth() + 1));
            const oks = [marcar('numero', luhnValido(numero)), marcar('titular', titular.length >= 3),
                         marcar('venc', !!vigente), marcar('cvv', /^\d{3,4}$/.test(cvv))];
            return oks.every(Boolean) ? { tarjeta: { numero, vencimiento: venc, cvv, titular } } : null;
        }
        const celular = body.querySelector('#pay-celular').value, codigo = body.querySelector('#pay-codigo').value;
        const oks = [marcar('celular', /^9\d{8}$/.test(celular)), marcar('codigo', /^\d{6}$/.test(codigo))];
        return oks.every(Boolean) ? { celular, codigo_aprobacion: codigo } : null;
    }

    async function enviar(e) {
        e.preventDefault();
        const datos = validar();
        if (!datos) return;
        ['pay-numero', 'pay-titular', 'pay-venc', 'pay-celular'].forEach(id => {
            const el = body.querySelector('#' + id);
            if (el) estado.valores[id] = el.value;
        });
        estado.procesando = true;
        document.getElementById('pay-close').hidden = true;
        body.innerHTML = `<div class="pay-processing" role="status"><div class="loader-spinner"></div>
            <b>Procesando tu pago…</b><p style="color:var(--c-muted);font-size:.88rem;margin-top:.3rem">No cierres esta ventana.</p></div>`;
        try {
            const pago = await apiFetch(opts.endpoint, {
                method: 'POST', silent: true,
                body: JSON.stringify({ monto, metodo: estado.metodo, ...datos })
            });
            estado.pago = pago;
            estado.procesando = false;
            renderExito(pago);
        } catch (err) {
            estado.procesando = false;
            document.getElementById('pay-close').hidden = false;
            // Rechazo (402), importe cambiado (400), ya pagado (409), bloqueo (429), etc.
            renderFormulario(err.message || 'No se pudo procesar el pago. Intente nuevamente.');
            if (err.status === 409) { estado.pago = null; opts.refrescar = true; }
        }
    }

    function renderExito(pago) {
        document.getElementById('pay-close').hidden = false;
        body.innerHTML = `
          <div class="pay-success">
            <div class="pay-check"><i class="fas fa-check"></i></div>
            <h3>¡Pago exitoso!</h3>
            <p class="sub">${esc(pago.mensaje)}</p>
            <div class="pay-receipt">
              <div class="row"><span>Boleta N.º</span><b>${esc(pago.numero_comprobante)}</b></div>
              <div class="row"><span>Monto pagado</span><b>S/ ${formatCurrency(pago.monto)}</b></div>
              <div class="row"><span>Medio de pago</span><b>${esc(pago.detalle_metodo || ETIQUETA_METODO[pago.metodo])}</b></div>
              <div class="row"><span>N.º de operación</span><b>${esc(pago.transaccion_id)}</b></div>
              <div class="row"><span>Fecha y hora</span><b>${esc(formatearFecha(pago.fecha_pago))}</b></div>
              ${pago.tramite_expediente ? `<div class="row"><span>Expediente</span><b>${esc(pago.tramite_expediente)}</b></div>` : ''}
            </div>
            <div class="pay-actions">
              <button type="button" class="btn btn-primario" id="pay-boleta"><i class="fas fa-file-pdf"></i> Descargar boleta (PDF)</button>
              <button type="button" class="btn btn-secundario" id="pay-done">Cerrar</button>
            </div>
          </div>`;
        document.getElementById('pay-boleta').addEventListener('click', () =>
            apiFetchFile(`/pagos/comprobante/${pago.id}`, `boleta_${pago.numero_comprobante}.pdf`).catch(() => {}));
        const hecho = document.getElementById('pay-done');
        hecho.addEventListener('click', cerrar);
        hecho.focus();
    }

    renderFormulario();
}

// ---------- Descargas de boletas (delegado) ----------
document.addEventListener('click', (e) => {
    const btn = e.target.closest('.btn-boleta');
    if (!btn) return;
    apiFetchFile(`/pagos/comprobante/${btn.dataset.id}`, `boleta_${btn.dataset.num || btn.dataset.id}.pdf`).catch(() => {});
});

function badgeEstado(estado) {
    const texto = { COMPLETADO: 'Pagado', FALLIDO: 'Rechazado', PENDIENTE: 'Pendiente' }[estado] || estado;
    return `<span class="status-badge status-${esc(estado)}">${esc(texto)}</span>`;
}

// ---------- Ciudadano: Mis pagos ----------
async function renderMisPagos() {
    dashboardContent.innerHTML = `<div class="card"><h2 class="card-header">Mis Pagos</h2><div id="mp-cuerpo">${RENDER.loadingState()}</div></div>`;
    const cuerpo = document.getElementById('mp-cuerpo');
    try {
        const pagos = await apiFetch('/pagos/mis-pagos', { method: 'GET', silent: true });
        if (!pagos.length) {
            cuerpo.innerHTML = `<div class="text-center py-8" style="color:var(--c-muted)"><i class="fas fa-receipt text-4xl mb-3"></i>
                <p>Aún no has realizado pagos. Cuando pagues un trámite o una deuda, tu boleta aparecerá aquí.</p></div>`;
            return;
        }
        const filas = pagos.map(p => `
            <tr>
                <td>${esc(formatearFecha(p.fecha_pago))}</td>
                <td><div>${esc(p.concepto || 'Pago')}</div>
                    ${p.numero_comprobante ? `<div style="font-size:.78rem;color:var(--c-muted)" class="font-mono">${esc(p.numero_comprobante)}</div>` : ''}
                    ${p.motivo_rechazo ? `<div style="font-size:.8rem;color:var(--c-danger)">${esc(p.motivo_rechazo)}</div>` : ''}</td>
                <td>${esc(p.detalle_metodo || ETIQUETA_METODO[p.metodo])}</td>
                <td class="num"><b>S/ ${formatCurrency(p.monto)}</b></td>
                <td>${badgeEstado(p.estado)}</td>
                <td>${p.estado === 'COMPLETADO' ? `<button class="btn btn-secundario btn-boleta" style="padding:.35rem .7rem;font-size:.8rem" data-id="${esc(p.id)}" data-num="${esc(p.numero_comprobante)}"><i class="fas fa-file-pdf"></i> Boleta</button>` : ''}</td>
            </tr>`).join('');
        cuerpo.innerHTML = `<div class="table-wrapper"><table class="table">
            <thead><tr><th>Fecha</th><th>Concepto</th><th>Medio</th><th class="num">Monto</th><th>Estado</th><th></th></tr></thead>
            <tbody>${filas}</tbody></table></div>`;
    } catch (err) {
        cuerpo.innerHTML = `<p class="text-center py-8" style="color:var(--c-danger)">No se pudo cargar el historial: ${esc(err.message)}</p>`;
    }
}

// ---------- Admin: Recaudación ----------
function renderRecaudacion() {
    dashboardContent.innerHTML = `
      <div class="card">
        <h2 class="card-header">Recaudación y Pagos</h2>
        <form id="rc-filtros" class="filter-bar">
          <div class="field"><label for="rc-desde">Desde</label><input type="date" id="rc-desde" class="form-input" style="padding-right:.85rem"></div>
          <div class="field"><label for="rc-hasta">Hasta</label><input type="date" id="rc-hasta" class="form-input" style="padding-right:.85rem"></div>
          <div class="field"><label for="rc-metodo">Medio</label>
            <select id="rc-metodo" class="form-select"><option value="">Todos</option><option value="TARJETA">Tarjeta</option><option value="YAPE">Yape</option><option value="PLIN">Plin</option></select></div>
          <div class="field"><label for="rc-estado">Estado</label>
            <select id="rc-estado" class="form-select"><option value="">Todos</option><option value="COMPLETADO">Pagados</option><option value="FALLIDO">Rechazados</option></select></div>
          <button type="submit" class="btn btn-primario"><i class="fas fa-filter"></i> Filtrar</button>
          <button type="button" id="rc-csv" class="btn btn-secundario"><i class="fas fa-file-csv"></i> Exportar CSV</button>
        </form>
        <div id="rc-resultado">${RENDER.loadingState()}</div>
      </div>`;

    const consulta = () => {
        const qs = new URLSearchParams();
        [['desde', 'rc-desde'], ['hasta', 'rc-hasta'], ['metodo', 'rc-metodo'], ['estado', 'rc-estado']].forEach(([k, id]) => {
            const v = document.getElementById(id).value; if (v) qs.set(k, v);
        });
        return qs.toString();
    };

    async function cargar() {
        const out = document.getElementById('rc-resultado');
        out.innerHTML = RENDER.loadingState();
        try {
            const d = await apiFetch(`/admin/pagos?${consulta()}`, { method: 'GET', silent: true });
            document.getElementById('rc-desde').value = d.desde;
            document.getElementById('rc-hasta').value = d.hasta;
            const m = d.porMetodo;
            const filas = d.pagos.map(p => `
                <tr>
                    <td>${esc(formatearFecha(p.fecha_pago))}</td>
                    <td><div>${esc(p.ciudadano_nombre)}</div><div style="font-size:.78rem;color:var(--c-muted)">DNI ${esc(p.ciudadano_dni)}</div></td>
                    <td><div>${esc(p.concepto || 'Pago')}</div>
                        ${p.numero_comprobante ? `<div class="font-mono" style="font-size:.78rem;color:var(--c-muted)">${esc(p.numero_comprobante)}</div>` : ''}
                        ${p.motivo_rechazo ? `<div style="font-size:.8rem;color:var(--c-danger)">${esc(p.motivo_rechazo)}</div>` : ''}</td>
                    <td>${esc(p.detalle_metodo || ETIQUETA_METODO[p.metodo])}</td>
                    <td class="num"><b>S/ ${formatCurrency(p.monto)}</b></td>
                    <td>${badgeEstado(p.estado)}</td>
                    <td>${p.estado === 'COMPLETADO' ? `<button class="btn btn-secundario btn-boleta" style="padding:.35rem .7rem;font-size:.8rem" data-id="${esc(p.id)}" data-num="${esc(p.numero_comprobante)}"><i class="fas fa-file-pdf"></i></button>` : ''}</td>
                </tr>`).join('');
            out.innerHTML = `
              <div class="stat-grid" style="margin-bottom:1.25rem">
                <div class="stat-card"><div class="stat-label">Total recaudado</div><div class="stat-value" style="color:var(--c-success)">S/ ${formatCurrency(d.totalRecaudado)}</div></div>
                <div class="stat-card"><div class="stat-label">Pagos completados</div><div class="stat-value">${esc(d.cantidadCompletados)}</div></div>
                <div class="stat-card"><div class="stat-label">Rechazados</div><div class="stat-value" style="color:var(--c-danger)">${esc(d.cantidadRechazados)}</div></div>
                <div class="stat-card"><div class="stat-label">Por medio</div>
                  <div style="font-size:.88rem;margin-top:.35rem">Tarjeta <b>S/ ${formatCurrency(m.TARJETA)}</b><br>Yape <b>S/ ${formatCurrency(m.YAPE)}</b><br>Plin <b>S/ ${formatCurrency(m.PLIN)}</b></div></div>
              </div>
              ${d.pagos.length ? `<div class="table-wrapper"><table class="table">
                <thead><tr><th>Fecha</th><th>Contribuyente</th><th>Concepto</th><th>Medio</th><th class="num">Monto</th><th>Estado</th><th></th></tr></thead>
                <tbody>${filas}</tbody></table></div>` : `<p class="text-center py-8" style="color:var(--c-muted)">No hay pagos en este periodo.</p>`}`;
        } catch (err) {
            out.innerHTML = `<p class="text-center py-8" style="color:var(--c-danger)">${esc(err.message)}</p>`;
        }
    }

    document.getElementById('rc-filtros').addEventListener('submit', (e) => { e.preventDefault(); cargar(); });
    document.getElementById('rc-csv').addEventListener('click', () =>
        apiFetchFile(`/admin/pagos/export.csv?${consulta()}`, 'recaudacion.csv').catch(() => {}));
    cargar();
}
